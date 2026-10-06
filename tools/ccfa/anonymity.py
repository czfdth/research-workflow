"""The anonymisation gate for double-blind submissions.

``checklists/conference.md`` and ``checklists/journal.md`` both list
"匿名" as a condition of the ``submission-check`` gate, but until now nothing
mechanically enforced it: the only code that touched anonymity was
``resubmit_pipeline`` (which checks *re-submission* targets, not the submitted
manuscript), and neither ``venue_fixtures`` nor ``final_check`` looked at it.
A double-blind venue desk-rejects on a leaked identity, so prose in a checklist
is not enough.

This gate reads the manuscript's ``.tex`` sources and any built PDFs and fails
closed on the vectors that actually get papers rejected:

* an author block that is not anonymised (``\\author{...}``);
* real author names or affiliations (declared in ``data/anonymity.yaml``)
  appearing anywhere in the sources, including inside an acknowledgements
  section;
* self-referential phrasing ("our previous work", "we previously showed",
  "in our prior work") that identifies the authors through their own citations;
* author-owned URLs declared in the config;
* PDF metadata (Author / Title / Subject / Keywords / Creator / Producer)
  carrying a real name, affiliation, or a non-anonymous author string.

Judgement calls stay advisories rather than hard failures, so the gate cannot
force a paper to lie: an acknowledgements section is an advisory by default
(venues such as CSF *require* an AI-use disclosure there), and an unlisted
repository URL is an advisory because a third-party artifact URL is legitimate.
Set ``acknowledgements: forbidden`` in the config when the venue genuinely bans
them.

Config (``data/anonymity.yaml``), all keys optional::

    version: 1
    blind: true                 # false -> the gate reports "not applicable"
    venue: CSF
    authors: ["Zhang San"]      # real names that must not appear
    affiliations: ["Example University"]
    self_urls: ["github.com/owner"]
    codenames: ["Project Falcon"]
    allow: ["anonymous.example"]  # strings exempt from the URL advisory
    acknowledgements: allowed   # allowed | forbidden

Exit codes follow the rest of the workflow: 0 pass, 1 problem, 2 setup error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error

SCHEMA_VERSION = 1
CONFIG_PATH = Path("data") / "anonymity.yaml"
MANUSCRIPT_DIR = Path("manuscript")

# Phrases that identify the authors through their own prior work. Kept narrow:
# "our method" is normal first-person writing and must not be flagged.
SELF_REFERENCE_PATTERNS = (
    re.compile(r"\bour\s+(?:previous|prior|earlier|past)\s+work\b", re.IGNORECASE),
    re.compile(r"\bwe\s+(?:previously|earlier)\s+(?:showed|proposed|introduced)", re.IGNORECASE),
    re.compile(r"\bin\s+our\s+(?:previous|prior|earlier)\b", re.IGNORECASE),
    # Chinese has no ASCII word boundaries between adjacent CJK characters, so
    # these patterns must not use ``\b`` at the end ("工作研究" has no boundary).
    re.compile(r"我们的?(?:之前|先前|以往)(?:的)?工作"),
    re.compile(r"我们(?:之前|先前)(?:提出|发表|证明)"),
)

AUTHOR_BLOCK_RE = re.compile(r"\\author\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", re.DOTALL)
ACK_SECTION_RE = re.compile(
    r"\\(?:section\*?|chapter\*?)\s*\{\s*(?:Acknowledg\w*|致谢|Acknowledgements?)\s*\}",
    re.IGNORECASE,
)
# ARIS's resubmit-pipeline scans acknowledgements as a *macro* too, not only as
# a section, and it also looks for a dedicated acknowledgments file.
ACK_MACRO_RE = re.compile(
    r"\\(?:acknowledg(?:e)?ments?|thanks)\s*\{"
    r"|\\begin\s*\{\s*acknowledg(?:e)?ments?\s*\}",
    re.IGNORECASE,
)
ACK_FILENAME_RE = re.compile(r"acknowledg(?:e)?ments?", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s{}\\]*", re.IGNORECASE)

# ARIS resubmit-pipeline Phase 0.5, layer 4: a cross-rebuttal reference breaks
# anonymity *and* advertises that an earlier venue rejected the paper. ARIS
# treats this as equally blocking as a leaked author name.
CROSS_REBUTTAL_PATTERNS = (
    re.compile(r"\b(?:rebuttal|response)\s+(?:at|from|to)\s+[A-Z]", 0),
    re.compile(r"\breviewer\s*#?\d+(?:'s|’s|\s+)?\s*(?:concern|comment|objection)", re.IGNORECASE),
    re.compile(r"\b(?:prior|previous|earlier)\s+(?:submission|version of this paper|rejected version)", re.IGNORECASE),
    re.compile(r"\bresubmission of\b", re.IGNORECASE),
    re.compile(r"\baddressing\s+reviewer\s*\d+", re.IGNORECASE),
    re.compile(r"(?:上次|之前|先前)(?:投稿|被拒|审稿意见)"),
)

# ARIS layer 5: internal codenames and project links that identify the lab.
INTERNAL_LINK_PATTERNS = (
    re.compile(r"https?://[^\s{}]*\bslack\.com\b", re.IGNORECASE),
    re.compile(r"\bslack\s+(?:channel|workspace)\b", re.IGNORECASE),
    re.compile(r"https?://[^\s{}]*\b(?:atlassian\.net|confluence)\b", re.IGNORECASE),
    re.compile(r"\binternal\s+(?:wiki|repo|repository|tracker)\b", re.IGNORECASE),
)

# ARIS's "residual coloring / margin-note scan": leftovers from a camera-ready
# cycle. ARIS lists them for the user to decide, so these are advisories.
RESIDUAL_MARKUP_PATTERNS = (
    re.compile(r"\\(?:revise|fix|todo|todonotes|note)\s*\{"),
    re.compile(r"\\textcolor\s*\{\s*(?:red|blue|green)\s*\}\s*\{"),
)

# Strings that mean "this author block is already anonymised".
ANONYMOUS_MARKERS = (
    "anonymous",
    "匿名",
    "redacted",
    "under review",
)


def _problem(code: str, path: Path | str, message: str, line: int | None = None) -> Problem:
    return Problem(code, str(path), line, message)


def load_config(paper_root: Path) -> tuple[dict, list[Problem]]:
    """Load ``data/anonymity.yaml``; a missing file means "double-blind defaults"."""
    path = Path(paper_root) / CONFIG_PATH
    if not path.is_file():
        return {
            "version": SCHEMA_VERSION,
            "blind": True,
            "venue": None,
            "authors": [],
            "affiliations": [],
            "self_urls": [],
            "allow": [],
            "codenames": [],
            "acknowledgements": "allowed",
            "config_present": False,
        }, []
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {}, [_problem("anonymity-config-invalid", path, f"无法解析: {exc}")]
    if not isinstance(payload, dict):
        return {}, [_problem("anonymity-config-invalid", path, "顶层必须是映射")]
    config = {
        "version": payload.get("version", SCHEMA_VERSION),
        "blind": bool(payload.get("blind", True)),
        "venue": payload.get("venue"),
        "authors": [str(item) for item in (payload.get("authors") or [])],
        "affiliations": [str(item) for item in (payload.get("affiliations") or [])],
        "self_urls": [str(item) for item in (payload.get("self_urls") or [])],
        "allow": [str(item) for item in (payload.get("allow") or [])],
        "codenames": [str(item) for item in (payload.get("codenames") or [])],
        "acknowledgements": str(payload.get("acknowledgements", "allowed")).casefold(),
        "config_present": True,
    }
    problems: list[Problem] = []
    if config["version"] != SCHEMA_VERSION:
        problems.append(
            _problem(
                "anonymity-config-invalid",
                path,
                f"version 必须是 {SCHEMA_VERSION}，当前 {config['version']!r}",
            )
        )
    if config["acknowledgements"] not in ("allowed", "forbidden"):
        problems.append(
            _problem(
                "anonymity-config-invalid",
                path,
                "acknowledgements 必须是 allowed 或 forbidden",
            )
        )
    return config, problems


def _tex_sources(paper_root: Path) -> list[Path]:
    root = Path(paper_root)
    manuscript = root / MANUSCRIPT_DIR
    if not manuscript.is_dir():
        return []
    return sorted(manuscript.rglob("*.tex"))


def _pdfs(paper_root: Path) -> list[Path]:
    root = Path(paper_root)
    found: list[Path] = []
    for folder in (root / MANUSCRIPT_DIR, root / "submission"):
        if folder.is_dir():
            found.extend(sorted(folder.rglob("*.pdf")))
    return found


def _is_anonymous_author_block(block: str) -> bool:
    lowered = block.casefold()
    return any(marker in lowered for marker in ANONYMOUS_MARKERS)


def check_sources(
    paper_root: Path, config: dict
) -> tuple[list[Problem], list[Problem]]:
    """Scan the manuscript sources for identity leaks."""
    problems: list[Problem] = []
    advisories: list[Problem] = []
    sources = _tex_sources(paper_root)
    if not sources:
        return [
            _problem(
                "anonymity-manuscript-missing",
                Path(paper_root) / MANUSCRIPT_DIR,
                "找不到 manuscript/*.tex；匿名门无法核对",
            )
        ], advisories
    names = [item for item in config.get("authors", []) if item.strip()]
    affiliations = [item for item in config.get("affiliations", []) if item.strip()]
    self_urls = [item.casefold() for item in config.get("self_urls", []) if item.strip()]
    allow = [item.casefold() for item in config.get("allow", []) if item.strip()]
    codenames = [item for item in config.get("codenames", []) if item.strip()]
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("%"):
                continue  # a comment never reaches the PDF
            for name in names:
                if name and name.casefold() in line.casefold():
                    problems.append(
                        _problem(
                            "anonymity-author-name",
                            path,
                            f"第 {line_number} 行出现作者名 {name!r}",
                        )
                    )
            for affiliation in affiliations:
                if affiliation and affiliation.casefold() in line.casefold():
                    problems.append(
                        _problem(
                            "anonymity-affiliation",
                            path,
                            f"第 {line_number} 行出现单位 {affiliation!r}",
                        )
                    )
            for pattern in SELF_REFERENCE_PATTERNS:
                match = pattern.search(line)
                if match:
                    problems.append(
                        _problem(
                            "anonymity-self-reference",
                            path,
                            f"第 {line_number} 行出现自指措辞 {match.group(0)!r}；"
                            "双盲投稿要求改写成第三人称（如 «prior work [12]»）",
                        )
                    )
            for codename in codenames:
                if codename and codename.casefold() in line.casefold():
                    problems.append(
                        _problem(
                            "anonymity-codename",
                            path,
                            f"第 {line_number} 行出现内部代号 {codename!r}",
                        )
                    )
            for pattern in CROSS_REBUTTAL_PATTERNS:
                match = pattern.search(line)
                if match:
                    problems.append(
                        _problem(
                            "anonymity-cross-rebuttal",
                            path,
                            f"第 {line_number} 行出现跨轮/跨会引用 {match.group(0)!r}；"
                            "ARIS layer 4：这同时泄漏身份与「前一次被拒」，必须整段删除",
                        )
                    )
            for pattern in INTERNAL_LINK_PATTERNS:
                match = pattern.search(line)
                if match:
                    advisories.append(
                        _problem(
                            "anonymity-internal-link",
                            path,
                            f"第 {line_number} 行出现内部链接/工作区线索 "
                            f"{match.group(0)!r}（ARIS layer 5）",
                        )
                    )
            for pattern in RESIDUAL_MARKUP_PATTERNS:
                match = pattern.search(line)
                if match:
                    advisories.append(
                        _problem(
                            "anonymity-residual-markup",
                            path,
                            f"第 {line_number} 行残留修订标记 {match.group(0)!r}；"
                            "camera-ready 循环的遗留物，双盲前应清掉",
                        )
                    )
            for url in URL_RE.findall(line):
                lowered = url.casefold()
                if any(item in lowered for item in allow):
                    continue
                if any(item in lowered for item in self_urls):
                    problems.append(
                        _problem(
                            "anonymity-self-url",
                            path,
                            f"第 {line_number} 行出现作者自有 URL {url!r}",
                        )
                    )
                elif re.search(r"(?:github|gitlab|bitbucket|huggingface)\.com/", lowered):
                    advisories.append(
                        _problem(
                            "anonymity-url-review",
                            path,
                            f"第 {line_number} 行出现代码托管 URL {url!r}；"
                            "确认它不是作者自有仓库（是则在 self_urls 里声明）",
                        )
                    )
        for match in AUTHOR_BLOCK_RE.finditer(text):
            if not _is_anonymous_author_block(match.group(1)):
                line = text[: match.start()].count("\n") + 1
                problems.append(
                    _problem(
                        "anonymity-author-block",
                        path,
                        f"第 {line} 行的 \\author{{...}} 不像匿名写法；"
                        "双盲投稿必须是 Anonymous 之类",
                    )
                )
        has_acknowledgements = bool(
            ACK_SECTION_RE.search(text)
            or ACK_MACRO_RE.search(text)
            or ACK_FILENAME_RE.search(path.stem)
        )
        if has_acknowledgements:
            if config.get("acknowledgements") == "forbidden":
                problems.append(
                    _problem(
                        "anonymity-acknowledgement",
                        path,
                        "config 声明禁止致谢，但仍存在致谢章节（双盲下致谢常泄漏身份）",
                    )
                )
            else:
                advisories.append(
                    _problem(
                        "anonymity-acknowledgement",
                        path,
                        "存在致谢章节；双盲下请确认其中没有姓名、基金号或单位"
                        "（venue 强制 AI 使用声明时保留是允许的）",
                    )
                )
    return problems, advisories


def check_pdfs(
    paper_root: Path, config: dict
) -> tuple[list[Problem], list[Problem]]:
    """Scan built PDFs for identity-bearing metadata."""
    problems: list[Problem] = []
    advisories: list[Problem] = []
    pdfs = _pdfs(paper_root)
    if not pdfs:
        return problems, advisories
    try:
        import pymupdf  # PyMuPDF >= 1.24 exposes this name
    except ImportError:  # pragma: no cover - older PyMuPDF only ships `fitz`
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError:
            pymupdf = None
    if pymupdf is None:  # pragma: no cover - dependency is pinned
        return [], [
            _problem(
                "anonymity-pdf-skipped",
                Path(paper_root),
                "没有 PyMuPDF，跳过 PDF 元数据检查",
            )
        ]
    names = [item for item in config.get("authors", []) if item.strip()]
    affiliations = [item for item in config.get("affiliations", []) if item.strip()]
    for path in pdfs:
        try:
            with pymupdf.open(path) as document:
                metadata = document.metadata or {}
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            problems.append(
                _problem("anonymity-pdf-unreadable", path, f"无法读取 PDF: {exc}")
            )
            continue
        for key in ("author", "title", "subject", "keywords", "creator", "producer"):
            value = metadata.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            lowered = value.casefold()
            for name in names:
                if name.casefold() in lowered:
                    problems.append(
                        _problem(
                            "anonymity-pdf-metadata",
                            path,
                            f"PDF 元数据 {key}={value!r} 含作者名 {name!r}",
                        )
                    )
            for affiliation in affiliations:
                if affiliation.casefold() in lowered:
                    problems.append(
                        _problem(
                            "anonymity-pdf-metadata",
                            path,
                            f"PDF 元数据 {key}={value!r} 含单位 {affiliation!r}",
                        )
                    )
            if key == "author" and not any(
                marker in lowered for marker in ANONYMOUS_MARKERS
            ):
                problems.append(
                    _problem(
                        "anonymity-pdf-author",
                        path,
                        f"PDF 的 Author 元数据是 {value!r}，不是匿名值；"
                        "PDF 属性会随投稿上传，属于常见 desk-reject 触发点",
                    )
                )
    return problems, advisories


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Run the anonymisation gate for a paper."""
    root = Path(paper_root)
    if not root.is_dir():
        return [_problem("anonymity-root-missing", root, f"论文目录不存在: {root}")], []
    config, problems = load_config(root)
    if problems:
        return problems, []
    if not config.get("blind", True):
        return [], [
            _problem(
                "anonymity-not-applicable",
                root / CONFIG_PATH,
                "config 声明 blind: false；该投稿不是双盲，匿名门不适用",
            )
        ]
    source_problems, source_advisories = check_sources(root, config)
    pdf_problems, pdf_advisories = check_pdfs(root, config)
    return (
        problems + source_problems + pdf_problems,
        source_advisories + pdf_advisories,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "双盲投稿的匿名门：扫 .tex 与 PDF，检查作者块、姓名/单位、"
            "自指措辞、作者自有 URL 与 PDF 元数据"
        )
    )
    parser.add_argument("--paper-root", default=".")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        problems, advisories = check(Path(args.paper_root))
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
