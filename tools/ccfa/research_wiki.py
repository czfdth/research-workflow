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
from ccfa.friction_log import write_text_output


WIKI_VERSION = 1
KINDS = {"source", "claim", "decision", "dead-end", "method", "result"}
STATUSES = {"active", "superseded", "rejected", "archived"}
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
        if path.name.casefold() == "readme.md":
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
    return problems, []


def build_index(wiki_dir: Path) -> dict:
    """Build a deterministic JSON index for wiki search."""
    problems, _advisories = check_wiki(wiki_dir)
    if problems:
        first = problems[0]
        raise ValueError(f"research wiki 无效: {first.code}: {first.message}")
    wiki_dir = Path(wiki_dir)
    entries = []
    for path in sorted(wiki_dir.rglob("*.md")):
        if path.name.casefold() == "readme.md":
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
    return {
        "version": WIKI_VERSION,
        "entry_count": len(entries),
        "entries": entries,
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
