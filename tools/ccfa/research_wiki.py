"""Build a cross-project Markdown research wiki with a deterministic index."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error
from ccfa.bib import load_records
from ccfa.friction_log import write_text_output


WIKI_VERSION = 1
KINDS = {
    "paper",
    "idea",
    "experiment",
    "claim",
    "gap",
    "source",
    "decision",
    "dead-end",
    "method",
    "result",
}
STATUSES = {"active", "superseded", "rejected", "archived"}
EDGE_TYPES = {
    "extends",
    "contradicts",
    "addresses_gap",
    "inspired_by",
    "tested_by",
    "supports",
    "invalidates",
    "supersedes",
}
REQUIRED_FIELDS = (
    "id",
    "kind",
    "title",
    "status",
    "tags",
    "projects",
    "evidence",
    "related",
    "updated_at",
)
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
URL = re.compile(r"^https?://[^\s]+$")
FAILURE_CODES = {
    "research-wiki-missing",
    "research-wiki-invalid",
    "research-wiki-missing-field",
    "research-wiki-duplicate-id",
    "research-wiki-unknown-link",
    "research-wiki-invalid-evidence",
}


def _problem(code: str, path: Path, message: str) -> Problem:
    return Problem(code, str(path), None, message)


def _parse_entry(path: Path) -> tuple[dict | None, str, list[Problem]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, "", [
            _problem("research-wiki-invalid", path, f"无法读取: {exc}")
        ]
    if not text.startswith("---\n"):
        return None, text, [
            _problem("research-wiki-invalid", path, "缺少 frontmatter")
        ]
    end = text.find("\n---", 4)
    if end < 0:
        return None, text, [
            _problem("research-wiki-invalid", path, "frontmatter 没有结束分隔")
        ]
    raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    try:
        metadata = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, body, [
            _problem("research-wiki-invalid", path, f"frontmatter YAML 非法: {exc}")
        ]
    if not isinstance(metadata, dict):
        return None, body, [
            _problem("research-wiki-invalid", path, "frontmatter 必须是映射")
        ]
    return metadata, body, []


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _evidence_problem(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    if value.startswith("doi:"):
        return DOI.fullmatch(value[4:]) is None
    if value.startswith("url:"):
        return URL.fullmatch(value[4:]) is None
    return not value.startswith(("run:", "file:", "claim:", "project:"))


def _edge_path(wiki_dir: Path) -> Path:
    return Path(wiki_dir) / "graph" / "edges.jsonl"


# Files this module generates itself; they are catalogues, not entry pages, so
# the frontmatter validator must not try to parse them as entities.
GENERATED_WIKI_FILES = frozenset(
    {"readme.md", "index.md", "gap_map.md", "query_pack.md", "log.md"}
)


def _is_wiki_entry(path: Path) -> bool:
    return path.name.casefold() not in GENERATED_WIKI_FILES


def _load_edges(
    wiki_dir: Path,
    known_ids: set[str],
) -> tuple[list[dict], list[Problem]]:
    """Load and validate graph/edges.jsonl when it exists."""
    path = _edge_path(wiki_dir)
    if not path.is_file():
        return [], []
    problems: list[Problem] = []
    edges: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [], [
            _problem("research-wiki-invalid-edge", path, f"无法读取 edges: {exc}")
        ]
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            edge = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(
                Problem(
                    "research-wiki-invalid-edge",
                    str(path),
                    line_number,
                    f"edge JSON 非法: {exc}",
                )
            )
            continue
        if not isinstance(edge, dict):
            problems.append(
                Problem(
                    "research-wiki-invalid-edge",
                    str(path),
                    line_number,
                    "edge 必须是对象",
                )
            )
            continue
        missing = [
            field
            for field in ("from", "to", "type", "evidence")
            if field not in edge
        ]
        if missing:
            problems.append(
                Problem(
                    "research-wiki-invalid-edge",
                    str(path),
                    line_number,
                    f"edge 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        if edge.get("type") not in EDGE_TYPES:
            problems.append(
                Problem(
                    "research-wiki-invalid-edge-type",
                    str(path),
                    line_number,
                    f"edge type 非法: {edge.get('type')!r}",
                )
            )
        for endpoint in ("from", "to"):
            value = edge.get(endpoint)
            if value not in known_ids:
                problems.append(
                    Problem(
                        "research-wiki-unknown-edge-endpoint",
                        str(path),
                        line_number,
                        f"edge {endpoint} 不存在: {value!r}",
                    )
                )
        if not isinstance(edge.get("evidence"), str) or not edge["evidence"].strip():
            problems.append(
                Problem(
                    "research-wiki-invalid-edge-evidence",
                    str(path),
                    line_number,
                    "edge evidence 必须是非空字符串",
                )
            )
        edges.append(edge)
    return edges, problems


def check_wiki(wiki_dir: Path) -> tuple[list[Problem], list[Problem]]:
    """Validate all Markdown wiki entries and their cross-links."""
    wiki_dir = Path(wiki_dir)
    problems: list[Problem] = []
    if not wiki_dir.is_dir():
        return [
            _problem(
                "research-wiki-missing",
                wiki_dir,
                "wiki 目录不存在",
            )
        ], []

    parsed: list[tuple[Path, dict, str]] = []
    for path in sorted(wiki_dir.rglob("*.md")):
        if not _is_wiki_entry(path):
            continue
        metadata, body, parse_problems = _parse_entry(path)
        problems.extend(parse_problems)
        if metadata is None:
            continue
        missing = [field for field in REQUIRED_FIELDS if field not in metadata]
        if missing:
            problems.append(
                _problem(
                    "research-wiki-missing-field",
                    path,
                    f"缺少字段: {', '.join(missing)}",
                )
            )
            continue
        item_id = metadata.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            problems.append(
                _problem("research-wiki-invalid", path, "id 必须是非空字符串")
            )
            continue
        kind = metadata.get("kind")
        if kind not in KINDS:
            problems.append(
                _problem("research-wiki-invalid", path, f"kind 非法: {kind!r}")
            )
        status = metadata.get("status")
        if status not in STATUSES:
            problems.append(
                _problem(
                    "research-wiki-invalid",
                    path,
                    f"status 非法: {status!r}",
                )
            )
        if not isinstance(metadata.get("title"), str) or not metadata["title"].strip():
            problems.append(
                _problem("research-wiki-invalid", path, "title 必须是非空字符串")
            )
        for field in ("tags", "projects", "related"):
            if not _string_list(metadata.get(field)):
                problems.append(
                    _problem(
                        "research-wiki-invalid",
                        path,
                        f"{field} 必须是字符串数组",
                    )
                )
        if not _valid_date(metadata.get("updated_at")):
            problems.append(
                _problem(
                    "research-wiki-invalid",
                    path,
                    "updated_at 必须是 YYYY-MM-DD",
                )
            )
        evidence = metadata.get("evidence")
        if not _string_list(evidence):
            problems.append(
                _problem(
                    "research-wiki-invalid-evidence",
                    path,
                    "evidence 必须是字符串数组",
                )
            )
        elif any(_evidence_problem(value) for value in evidence):
            problems.append(
                _problem(
                    "research-wiki-invalid-evidence",
                    path,
                    "evidence 必须是 run:/file:/doi:/url:/claim:/project: 引用",
                )
            )
        parsed.append((path, metadata, body))

    ids: dict[str, Path] = {}
    for path, metadata, _body in parsed:
        item_id = metadata["id"]
        if item_id in ids:
            problems.append(
                _problem(
                    "research-wiki-duplicate-id",
                    path,
                    f"id 重复: {item_id!r}",
                )
            )
        else:
            ids[item_id] = path
    known = set(ids)
    for path, metadata, _body in parsed:
        for related in metadata.get("related", []):
            if related not in known:
                problems.append(
                    _problem(
                        "research-wiki-unknown-link",
                        path,
                        f"related 引用了不存在的 id: {related!r}",
                    )
                )
    _edges, edge_problems = _load_edges(wiki_dir, known)
    problems.extend(edge_problems)
    return problems, []


def add_edge(
    wiki_dir: Path,
    *,
    from_id: str,
    to_id: str,
    edge_type: str,
    evidence: str,
) -> dict:
    """Append one typed edge to graph/edges.jsonl after endpoint checks."""
    wiki_dir = Path(wiki_dir)
    if edge_type not in EDGE_TYPES:
        raise ValueError(
            f"edge type 非法: {edge_type!r}，应为 {' / '.join(sorted(EDGE_TYPES))}"
        )
    if not evidence or not evidence.strip():
        raise ValueError("edge evidence 不能为空")
    index = build_index(wiki_dir)
    known = {entry["id"] for entry in index.get("entries", [])}
    for label, value in (("from", from_id), ("to", to_id)):
        if value not in known:
            raise ValueError(f"edge {label} 不存在: {value!r}")
    edge = {
        "from": from_id,
        "to": to_id,
        "type": edge_type,
        "evidence": evidence.strip(),
    }
    path = _edge_path(wiki_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(edge, ensure_ascii=False, sort_keys=True) + "\n")
    return edge


def query_pack(wiki_dir: Path) -> str:
    """Build a compact, deterministic query pack for downstream ideation."""
    index = build_index(wiki_dir)
    entries = index.get("entries", [])
    edges = index.get("edges", [])
    by_kind: dict[str, int] = {}
    for entry in entries:
        kind = str(entry.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
    lines = [
        "# Research Wiki Query Pack",
        "",
        f"- entries: {len(entries)}",
        f"- edges: {len(edges)}",
        "",
        "## Entities",
        "",
    ]
    for entry in entries[:50]:
        lines.append(f"- `{entry['id']}` [{entry['kind']}] {entry['title']}")
    lines.extend(["", "## Edges", ""])
    if edges:
        for edge in edges:
            lines.append(
                f"- `{edge['from']}` --{edge['type']}--> `{edge['to']}`: "
                f"{edge['evidence']}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Kind Counts", ""])
    for kind in sorted(by_kind):
        lines.append(f"- `{kind}`: {by_kind[kind]}")
    return "\n".join(lines) + "\n"


def sync_bibliography(wiki_dir: Path, bib_path: Path) -> dict:
    """Create paper cards for BibTeX entries not yet present in the wiki."""
    wiki_dir = Path(wiki_dir)
    bib_path = Path(bib_path)
    try:
        records = load_records(bib_path).records
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    index = build_index(wiki_dir)
    known = {entry["id"] for entry in index.get("entries", [])}
    created = []
    for key, record in records.items():
        paper_id = f"paper:{key}"
        if paper_id in known:
            continue
        title = record.title or key
        year = record.year or ""
        authors = record.authors or ""
        metadata = {
            "id": paper_id,
            "kind": "paper",
            "title": str(title),
            "status": "active",
            "tags": [],
            "projects": [],
            "evidence": [f"file:{bib_path.name}"],
            "related": [],
            "updated_at": dt.date.today().isoformat(),
            "authors": authors,
            "year": str(year),
        }
        content = "---\n" + yaml.safe_dump(
            metadata,
            sort_keys=False,
            allow_unicode=True,
        ) + "---\n\n# " + str(title) + "\n"
        target = wiki_dir / "papers" / f"{key}.md"
        save = write_text_output
        save(target, content)
        created.append(paper_id)
    return {"created": sorted(created), "count": len(created)}


def rebuild_catalog(wiki_dir: Path) -> dict:
    """Regenerate index.md and gap_map.md from wiki entities and edges."""
    wiki_dir = Path(wiki_dir)
    index = build_index(wiki_dir)
    entries = index.get("entries", [])
    edges = index.get("edges", [])
    by_kind: dict[str, list[dict]] = {}
    for entry in entries:
        by_kind.setdefault(str(entry.get("kind")), []).append(entry)
    index_lines = ["# Research Wiki Index", ""]
    for kind in sorted(by_kind):
        index_lines.extend([f"## {kind}", ""])
        for entry in sorted(by_kind[kind], key=lambda item: item["id"]):
            index_lines.append(f"- `{entry['id']}` {entry['title']}")
        index_lines.append("")
    index_path = wiki_dir / "index.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    gap_lines = ["# Gap Map", ""]
    for entry in sorted(
        (item for item in entries if item.get("kind") == "gap"),
        key=lambda item: item["id"],
    ):
        gap_lines.append(f"## {entry['id']}: {entry['title']}")
        related = [
            edge
            for edge in edges
            if edge.get("to") == entry["id"] or edge.get("from") == entry["id"]
        ]
        if related:
            for edge in related:
                gap_lines.append(
                    f"- {edge['from']} --{edge['type']}--> {edge['to']}"
                )
        else:
            gap_lines.append("- no mapped edges")
        gap_lines.append("")
    gap_path = wiki_dir / "gap_map.md"
    gap_path.write_text("\n".join(gap_lines) + "\n", encoding="utf-8")
    return {
        "files": ["index.md", "gap_map.md"],
        "entry_count": len(entries),
        "edge_count": len(edges),
    }


def append_log(wiki_dir: Path, message: str) -> None:
    path = Path(wiki_dir) / "log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"- {timestamp}: {message.strip()}\n")


def build_index(wiki_dir: Path) -> dict:
    """Build a deterministic JSON index for wiki search."""
    problems, _advisories = check_wiki(wiki_dir)
    if problems:
        first = problems[0]
        raise ValueError(f"research wiki 无效: {first.code}: {first.message}")
    wiki_dir = Path(wiki_dir)
    entries = []
    for path in sorted(wiki_dir.rglob("*.md")):
        if not _is_wiki_entry(path):
            continue
        metadata, body, _problems = _parse_entry(path)
        if metadata is None:
            continue
        relative = path.relative_to(wiki_dir).as_posix()
        entries.append(
            {
                "id": metadata["id"],
                "kind": metadata["kind"],
                "title": metadata["title"],
                "status": metadata["status"],
                "tags": metadata["tags"],
                "projects": metadata["projects"],
                "evidence": metadata["evidence"],
                "related": metadata["related"],
                "updated_at": metadata["updated_at"],
                "path": relative,
                "body_sha256": "sha256:"
                + hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "search_text": " ".join(
                    [metadata["title"], *metadata["tags"], body]
                ).casefold(),
            }
        )
    known_ids = {entry["id"] for entry in entries}
    edges, _edge_problems = _load_edges(wiki_dir, known_ids)
    return {
        "version": WIKI_VERSION,
        "entry_count": len(entries),
        "edge_count": len(edges),
        "entries": entries,
        "edges": edges,
    }


def search_index(index: dict, query: str) -> list[dict]:
    needle = query.strip().casefold()
    if not needle:
        return []
    results = []
    for entry in index.get("entries", []):
        if not isinstance(entry, dict):
            continue
        haystack = str(entry.get("search_text", "")).casefold()
        if needle in haystack:
            results.append(
                {
                    key: entry.get(key)
                    for key in (
                        "id",
                        "kind",
                        "title",
                        "status",
                        "tags",
                        "projects",
                        "path",
                    )
                }
            )
    return results


# ---------------------------------------------------------------------------
# Paper scaffolding, enrichment and the lifecycle hook.
#
# The reference (ARIS ``research-wiki`` + ``wiki-enrich``) keeps one page per
# paper with a fixed section skeleton; ``ingest_paper`` renders the scaffold
# and ``wiki-enrich`` is the missing back half that fills the ten fillable
# ``_TODO`` sections. Two sections are protected by construction: ``Connections``
# is the graph summary and ``Abstract (original)`` is immutable source data.
# Capture hygiene is the other half: an idea/claim/experiment note that records
# an operational accident ("the tool can't do X", "connection timed out") must
# not harden into a durable, self-cited falsehood.
# ---------------------------------------------------------------------------

FILLABLE_SECTIONS = (
    ("One-line thesis", "_TODO: fill in after reading._"),
    ("Problem / Gap", "_TODO._"),
    ("Method", "_TODO._"),
    ("Key Results", "_TODO._"),
    ("Assumptions", "_TODO._"),
    ("Limitations / Failure Modes", "_TODO._"),
    ("Reusable Ingredients", "_TODO._"),
    ("Open Questions", "_TODO._"),
    ("Claims", "_TODO._"),
    ("Relevance to This Project", "_TODO._"),
)
PROTECTED_SECTIONS = ("Connections", "Abstract (original)")
SECTION_ORDER = (
    "One-line thesis",
    "Problem / Gap",
    "Method",
    "Key Results",
    "Assumptions",
    "Limitations / Failure Modes",
    "Reusable Ingredients",
    "Open Questions",
    "Claims",
    "Connections",
    "Relevance to This Project",
    "Abstract (original)",
)
TODO_MARKERS = ("_TODO._", "_TODO: fill in after reading._")

# Capture-hygiene screens, transcribed from the reference's
# ``shared-references/capture-antipatterns.md`` intent: do not store an
# operational accident as a durable research fact.
_SCREEN_PATTERNS = (
    (
        "env-failure",
        re.compile(
            r"\b(?:command not found|no such file|not installed|ENOENT"
            r"|ModuleNotFoundError|ImportError|permission denied)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "transient-error",
        re.compile(
            r"\b(?:timed out|timeout|rate limit|429|temporarily unavailable"
            r"|connection reset|ECONNRESET|auth(?:entication)? required)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "negative-tool-claim",
        re.compile(
            r"\b(?:codex|claude|gemini|chatgpt|the reviewer|the agent|the model"
            r"|the tool|the workflow|the api|the mcp)\b[^.?!\n]{0,40}?"
            r"\b(?:can'?t|cannot|does not work|doesn'?t work|is broken"
            r"|failed to|unable to)\b",
            re.IGNORECASE,
        ),
    ),
)


def screen_text(text: str) -> list[dict]:
    """Flag operational noise that must not be stored as a durable fact."""
    findings: list[dict] = []
    for code, pattern in _SCREEN_PATTERNS:
        match = pattern.search(text or "")
        if match:
            findings.append(
                {
                    "code": code,
                    "message": (
                        "疑似把运行环境事故写成研究事实；改成修复/配置/绕行后再存"
                    ),
                    "match": match.group(0),
                }
            )
    return findings


def _slugify(key: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", key.strip()).strip("-").lower()
    return slug or "paper"


def _paper_body(
    title: str,
    *,
    abstract: str | None,
    url: str | None,
) -> str:
    lines = [f"# {title}", ""]
    for section in SECTION_ORDER:
        if section == "Abstract (original)":
            if not abstract:
                continue
            lines.extend([f"## {section}", "", abstract.strip(), ""])
            continue
        lines.extend([f"## {section}", ""])
        if section == "Connections":
            lines.extend(["_Auto-generated from graph/edges.jsonl._", ""])
            continue
        lines.append(dict(FILLABLE_SECTIONS).get(section, "_TODO._"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def ingest_paper(
    wiki_dir: Path,
    *,
    key: str,
    title: str,
    year: str = "",
    authors: str = "",
    abstract: str | None = None,
    url: str | None = None,
    evidence: str | None = None,
    force: bool = False,
) -> dict:
    """Render one paper scaffold; never overwrite an existing page by default."""
    wiki_dir = Path(wiki_dir)
    key = key.strip()
    if not key:
        raise ValueError("paper key 不能为空")
    target = wiki_dir / "papers" / f"{_slugify(key)}.md"
    if target.exists() and not force:
        return {"id": f"paper:{key}", "path": target.as_posix(), "created": False}
    reference = evidence or (f"url:{url}" if url else "file:references.bib")
    metadata = {
        "id": f"paper:{key}",
        "kind": "paper",
        "title": title.strip() or key,
        "status": "active",
        "tags": [],
        "projects": [],
        "evidence": [reference],
        "related": [],
        "updated_at": dt.date.today().isoformat(),
        "authors": authors,
        "year": str(year or ""),
    }
    if url:
        metadata["url"] = url
    content = (
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + _paper_body(metadata["title"], abstract=abstract, url=url)
    )
    write_text_output(target, content, force=force)
    return {"id": f"paper:{key}", "path": target.as_posix(), "created": True}


def ingest(
    wiki_dir: Path,
    *,
    bib_path: Path | None = None,
    pdf_dir: Path | None = None,
    arxiv_ids: tuple[str, ...] = (),
    force: bool = False,
) -> dict:
    """Create missing paper scaffolds from BibTeX, a PDF dir and/or arXiv ids."""
    created: list[str] = []
    if bib_path is not None:
        try:
            records = load_records(Path(bib_path)).records
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        for key, record in records.items():
            result = ingest_paper(
                wiki_dir,
                key=key,
                title=str(record.title or key),
                year=str(record.year or ""),
                authors=record.authors or "",
                evidence=f"file:{Path(bib_path).name}",
                force=force,
            )
            if result["created"]:
                created.append(result["id"])
    if pdf_dir is not None:
        for pdf in sorted(Path(pdf_dir).glob("*.pdf")):
            result = ingest_paper(
                wiki_dir,
                key=pdf.stem,
                title=pdf.stem.replace("_", " "),
                evidence=f"file:{pdf.name}",
                force=force,
            )
            if result["created"]:
                created.append(result["id"])
    for arxiv_id in arxiv_ids:
        result = ingest_paper(
            wiki_dir,
            key=f"arxiv-{arxiv_id}",
            title=f"arXiv {arxiv_id}",
            url=f"https://arxiv.org/abs/{arxiv_id}",
            force=force,
        )
        if result["created"]:
            created.append(result["id"])
    return {"created": sorted(created), "count": len(created)}


def _split_sections(body: str) -> list[tuple[str, list[str]]]:
    """Return ``(heading, lines)`` blocks split on level-2 Markdown headings."""
    blocks: list[tuple[str, list[str]]] = []
    current: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current is not None:
                blocks.append((current, buffer))
            current = line[3:].strip()
            buffer = [line]
        elif current is not None:
            buffer.append(line)
    if current is not None:
        blocks.append((current, buffer))
    return blocks


def enrich_report(wiki_dir: Path) -> dict:
    """List the fillable sections still carrying a TODO marker per paper."""
    wiki_dir = Path(wiki_dir)
    papers: list[dict] = []
    for path in sorted((wiki_dir / "papers").glob("*.md")):
        metadata, body, _problems = _parse_entry(path)
        if metadata is None:
            continue
        pending = []
        for heading, lines in _split_sections(body):
            if heading in PROTECTED_SECTIONS:
                continue
            if any(line.strip() in TODO_MARKERS for line in lines):
                pending.append(heading)
        if pending:
            papers.append(
                {
                    "path": path.name,
                    "id": metadata.get("id", path.stem),
                    "pending": pending,
                    "pending_count": len(pending),
                }
            )
    return {
        "papers": papers,
        "paper_count": len(papers),
        "pending_count": sum(item["pending_count"] for item in papers),
    }


def enrich_apply(
    wiki_dir: Path,
    slug: str,
    sections: dict[str, str],
) -> dict:
    """Fill named sections of one paper; refuse protected names and noise."""
    wiki_dir = Path(wiki_dir)
    path = wiki_dir / "papers" / f"{_slugify(slug)}.md"
    if not path.is_file():
        raise ValueError(f"paper 不存在: {path}")
    forbidden = [name for name in sections if name in PROTECTED_SECTIONS]
    if forbidden:
        raise ValueError(
            "受保护 section 不可改写: " + ", ".join(sorted(forbidden))
        )
    unknown = [name for name in sections if name not in dict(FILLABLE_SECTIONS)]
    if unknown:
        raise ValueError("未知 section: " + ", ".join(sorted(unknown)))
    for name, text in sections.items():
        findings = screen_text(text)
        if findings:
            raise ValueError(
                f"{name}: {findings[0]['code']}（{findings[0]['match']}）——"
                "运行事故不能写成持久研究事实"
            )
    metadata, body, _problems = _parse_entry(path)
    if metadata is None:
        raise ValueError(f"paper frontmatter 非法: {path}")
    written: list[str] = []
    blocks = _split_sections(body)
    for heading, lines in blocks:
        if heading not in sections:
            continue
        text = sections[heading].strip()
        replaced = False
        for index in range(1, len(lines)):
            if lines[index].strip() in TODO_MARKERS:
                lines[index] = text
                replaced = True
                break
        if not replaced:
            lines.extend(["", text])
        written.append(heading)
    rebuilt: list[str] = []
    for _heading, lines in blocks:
        rebuilt.extend(lines)
    content = (
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + "\n".join(rebuilt).rstrip()
        + "\n"
    )
    path.write_text(content, encoding="utf-8", newline="\n")
    return {"path": path.name, "written": sorted(written)}


def lifecycle_hook(
    wiki_dir: Path,
    *,
    bib_path: Path | None = None,
    pdf_dir: Path | None = None,
    arxiv_ids: tuple[str, ...] = (),
    summaries: dict[str, dict[str, str]] | None = None,
    force: bool = False,
) -> dict:
    """The lifecycle hook: ingest → enrich → rebuild the catalogue → log."""
    wiki_dir = Path(wiki_dir)
    ingested = ingest(
        wiki_dir,
        bib_path=bib_path,
        pdf_dir=pdf_dir,
        arxiv_ids=arxiv_ids,
        force=force,
    )
    enriched: list[dict] = []
    for slug, sections in (summaries or {}).items():
        enriched.append(enrich_apply(wiki_dir, slug, sections))
    report = enrich_report(wiki_dir)
    rebuilt = rebuild_catalog(wiki_dir)
    append_log(
        wiki_dir,
        f"hook: ingested {ingested['count']} paper(s), enriched "
        f"{len(enriched)} page(s), {report['pending_count']} TODO section(s) left",
    )
    return {
        "ingested": ingested,
        "enriched": enriched,
        "pending": report,
        "rebuilt": rebuilt,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="维护跨项目 Markdown research wiki 与确定性索引"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="校验 frontmatter、ID 与关联")
    check.add_argument("--dir", required=True)

    index = sub.add_parser("index", help="构建 JSON 索引")
    index.add_argument("--dir", required=True)
    index.add_argument("--out", required=True)
    index.add_argument("--force", action="store_true")

    search = sub.add_parser("search", help="在已构建索引中做确定性搜索")
    search.add_argument("--index", required=True)
    search.add_argument("--query", required=True)

    add_edge_parser = sub.add_parser("add-edge", help="追加一条 typed graph edge")
    add_edge_parser.add_argument("--dir", required=True)
    add_edge_parser.add_argument("--from", dest="from_id", required=True)
    add_edge_parser.add_argument("--to", dest="to_id", required=True)
    add_edge_parser.add_argument("--type", dest="edge_type", required=True)
    add_edge_parser.add_argument("--evidence", required=True)

    query = sub.add_parser("query-pack", help="生成紧凑的下游查询包")
    query.add_argument("--dir", required=True)
    query.add_argument("--out", required=True)
    query.add_argument("--force", action="store_true")
    sync = sub.add_parser("sync", help="从 BibTeX 批量创建缺失 paper cards")
    sync.add_argument("--dir", required=True)
    sync.add_argument("--bib", required=True)
    rebuild = sub.add_parser("rebuild", help="重建 index.md 与 gap_map.md")
    rebuild.add_argument("--dir", required=True)
    log = sub.add_parser("append-log", help="追加 wiki 时间线记录")
    log.add_argument("--dir", required=True)
    log.add_argument("--message", required=True)

    ingest_parser = sub.add_parser(
        "ingest", help="从 BibTeX / PDF 目录 / arXiv id 生成缺失的 paper 页"
    )
    ingest_parser.add_argument("--dir", required=True)
    ingest_parser.add_argument("--bib", default=None)
    ingest_parser.add_argument("--pdf-dir", dest="pdf_dir", default=None)
    ingest_parser.add_argument("--arxiv", action="append", default=[])
    ingest_parser.add_argument("--force", action="store_true")

    enrich_report_parser = sub.add_parser(
        "enrich-report", help="列出每个 paper 仍未填的 section"
    )
    enrich_report_parser.add_argument("--dir", required=True)

    enrich_parser = sub.add_parser(
        "enrich", help="用 JSON 里的正文填充某个 paper 的 section"
    )
    enrich_parser.add_argument("--dir", required=True)
    enrich_parser.add_argument("--slug", required=True)
    enrich_parser.add_argument("--from", dest="from_path", required=True)

    screen = sub.add_parser(
        "screen", help="检查文本是否把运行事故写成研究事实"
    )
    screen.add_argument("--text", required=True)

    hook = sub.add_parser(
        "hook", help="生命周期钩子：ingest → enrich → rebuild → log"
    )
    hook.add_argument("--dir", required=True)
    hook.add_argument("--bib", default=None)
    hook.add_argument("--pdf-dir", dest="pdf_dir", default=None)
    hook.add_argument("--arxiv", action="append", default=[])
    hook.add_argument("--summaries", default=None)
    hook.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check_wiki(Path(args.dir))
            return emit(problems, advisories)
        if args.command == "index":
            index = build_index(Path(args.dir))
            write_text_output(
                Path(args.out),
                json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                force=args.force,
            )
            return 0
        if args.command == "add-edge":
            edge = add_edge(
                Path(args.dir),
                from_id=args.from_id,
                to_id=args.to_id,
                edge_type=args.edge_type,
                evidence=args.evidence,
            )
            print(json.dumps(edge, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "query-pack":
            write_text_output(
                Path(args.out),
                query_pack(Path(args.dir)),
                force=args.force,
            )
            return 0
        if args.command == "sync":
            result = sync_bibliography(Path(args.dir), Path(args.bib))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "rebuild":
            result = rebuild_catalog(Path(args.dir))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "append-log":
            append_log(Path(args.dir), args.message)
            return 0
        if args.command == "ingest":
            result = ingest(
                Path(args.dir),
                bib_path=Path(args.bib) if args.bib else None,
                pdf_dir=Path(args.pdf_dir) if args.pdf_dir else None,
                arxiv_ids=tuple(args.arxiv or ()),
                force=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "enrich-report":
            print(
                json.dumps(
                    enrich_report(Path(args.dir)),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "enrich":
            payload = json.loads(
                Path(args.from_path).read_text(encoding="utf-8")
            )
            if not isinstance(payload, dict):
                raise ValueError("--from 必须是 {section: text} 的 JSON 对象")
            result = enrich_apply(Path(args.dir), args.slug, payload)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "screen":
            findings = screen_text(args.text)
            print(json.dumps(findings, ensure_ascii=False, indent=2))
            return 1 if findings else 0
        if args.command == "hook":
            summaries = None
            if args.summaries:
                summaries = json.loads(
                    Path(args.summaries).read_text(encoding="utf-8")
                )
                if not isinstance(summaries, dict):
                    raise ValueError("--summaries 必须是 {slug: {section: text}}")
            result = lifecycle_hook(
                Path(args.dir),
                bib_path=Path(args.bib) if args.bib else None,
                pdf_dir=Path(args.pdf_dir) if args.pdf_dir else None,
                arxiv_ids=tuple(args.arxiv or ()),
                summaries=summaries,
                force=args.force,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        index_path = Path(args.index)
        index = json.loads(index_path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                search_index(index, args.query),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
