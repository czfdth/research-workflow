"""Search external scholarly indexes for candidate references.

This is an *evidence-gathering* tool, not a gate. It never edits the manuscript,
the bibliography or any ledger unless ``--write-bib`` is passed explicitly, and
it never decides that a claim or a paper is ready. Its job is to turn a title or
keyword query into structured candidates that a human can review and that
``citation_guard`` can later verify.

Network access is opt-in: nothing here performs I/O until ``search()`` is called
with ``online=True``. Every provider takes an injectable ``fetch`` so tests run
fully offline. The fetch/evidence contract mirrors ``ccfa.doi_lookup`` so a
candidate carries the same fail-closed semantics (HTTP ok is not enough: the
body must parse and contain a usable title).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple

from ccfa.cli import Problem, tool_error
from ccfa.doi_lookup import normalize_title, title_similarity
from ccfa.literature_transport import make_default_fetcher

Fetcher = Callable[[str, float], "tuple[int, str | bytes]"]

USER_AGENT = "ccfa-literature-search/0.1"
DEFAULT_TIMEOUT = 20.0
MAX_RESULTS = 10

PROVIDERS = ("openalex", "arxiv", "semanticscholar")

_ENDPOINTS = {
    "openalex": "https://api.openalex.org/works?search={query}&per-page={limit}",
    "arxiv": "https://export.arxiv.org/api/query?search_query=all:{query}&max_results={limit}",
    "semanticscholar": "https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit={limit}&fields=title,authors,year,externalIds,url",
}


class Candidate(NamedTuple):
    """One search hit, bound to the fetched body it came from."""

    provider: str
    title: str
    authors: list[str]
    year: int | None
    doi: str
    url: str
    body_sha256: str
    retrieved_at: str


class SearchResult(NamedTuple):
    """Provider-level outcome: candidates plus any problem from the fetch."""

    provider: str
    candidates: list[Candidate]
    problem: Problem | None
    http_ok: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _body_sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _default_fetch(url: str, timeout: float) -> tuple[int, str | bytes]:
    # Shared resilient transport (retry/backoff/429/circuit breaker). An
    # injected ``fetch`` still bypasses this entirely, so tests stay offline.
    return _DEFAULT_TRANSPORT(url, timeout)


_DEFAULT_TRANSPORT = make_default_fetcher()


def _decode(raw: str | bytes) -> str:
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _authors_openalex(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = _as_text((item.get("author") or {}).get("display_name"))
                if name:
                    names.append(name)
    return names


def _doi_from_openalex(payload: dict) -> str:
    doi = _as_text(payload.get("doi"))
    if doi.startswith("https://doi.org/"):
        return doi[len("https://doi.org/") :]
    return doi


def _parse_openalex(text: str, provider: str, digest: str, at: str) -> list[Candidate]:
    payload = json.loads(text)
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("OpenAlex 响应缺少 results 数组")
    out: list[Candidate] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _as_text(item.get("display_name") or item.get("title"))
        if not title:
            continue
        out.append(
            Candidate(
                provider=provider,
                title=title,
                authors=_authors_openalex(item.get("authorships")),
                year=item.get("publication_year")
                if isinstance(item.get("publication_year"), int)
                else None,
                doi=_doi_from_openalex(item),
                url=_as_text(item.get("doi")) or _as_text(item.get("id")),
                body_sha256=digest,
                retrieved_at=at,
            )
        )
    return out


def _parse_arxiv(text: str, provider: str, digest: str, at: str) -> list[Candidate]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out: list[Candidate] = []
    for entry in root.findall("a:entry", ns):
        title = _as_text(entry.findtext("a:title", default="", namespaces=ns))
        if not title:
            continue
        authors = [
            _as_text(node.findtext("a:name", default="", namespaces=ns))
            for node in entry.findall("a:author", ns)
        ]
        published = _as_text(entry.findtext("a:published", default="", namespaces=ns))
        year = int(published[:4]) if published[:4].isdigit() else None
        doi = ""
        url = ""
        for link in entry.findall("a:link", ns):
            href = _as_text(link.get("href"))
            if href and not url:
                url = href
        out.append(
            Candidate(
                provider=provider,
                title=" ".join(title.split()),
                authors=[a for a in authors if a],
                year=year,
                doi=doi,
                url=url,
                body_sha256=digest,
                retrieved_at=at,
            )
        )
    return out


def _parse_semanticscholar(
    text: str, provider: str, digest: str, at: str
) -> list[Candidate]:
    payload = json.loads(text)
    results = payload.get("data")
    if not isinstance(results, list):
        raise ValueError("Semantic Scholar 响应缺少 data 数组")
    out: list[Candidate] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _as_text(item.get("title"))
        if not title:
            continue
        authors = [
            _as_text(a.get("name"))
            for a in item.get("authors", [])
            if isinstance(a, dict)
        ]
        external = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
        out.append(
            Candidate(
                provider=provider,
                title=title,
                authors=[a for a in authors if a],
                year=item.get("year") if isinstance(item.get("year"), int) else None,
                doi=_as_text(external.get("DOI")),
                url=_as_text(item.get("url")),
                body_sha256=digest,
                retrieved_at=at,
            )
        )
    return out


_PARSERS = {
    "openalex": _parse_openalex,
    "arxiv": _parse_arxiv,
    "semanticscholar": _parse_semanticscholar,
}


def search_provider(
    provider: str,
    query: str,
    *,
    limit: int = MAX_RESULTS,
    online: bool = False,
    fetch: Fetcher | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> SearchResult:
    """Run one provider. No I/O when ``online`` is false."""
    if provider not in PROVIDERS:
        raise ValueError(f"未知 provider: {provider!r}，应为 {', '.join(PROVIDERS)}")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("检索关键词不能为空")
    if not online:
        return SearchResult(provider, [], None, False)

    getter = fetch or _default_fetch
    url = _ENDPOINTS[provider].format(
        query=urllib.parse.quote(query.strip(), safe=""),
        limit=max(1, min(int(limit), MAX_RESULTS)),
    )
    try:
        status, raw = getter(url, timeout)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return SearchResult(
            provider,
            [],
            Problem("literature-search-fetch-error", url, None, f"检索请求失败: {exc}"),
            False,
        )
    body = _decode(raw)
    digest = _body_sha256(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
    at = _utc_now()
    if not 200 <= status < 300:
        return SearchResult(
            provider,
            [],
            Problem("literature-search-http-error", url, None, f"检索返回 HTTP {status}"),
            True,
        )
    try:
        candidates = _PARSERS[provider](body, provider, digest, at)
    except Exception as exc:
        # Parsers touch third-party formats (JSON, XML). Any parse failure is a
        # problem, never a pass and never a crash that escapes the CLI contract.
        return SearchResult(
            provider,
            [],
            Problem("literature-search-malformed", url, None, f"检索响应无法解析: {exc}"),
            True,
        )
    return SearchResult(provider, candidates, None, True)


def search(
    query: str,
    *,
    providers: tuple[str, ...] = PROVIDERS,
    limit: int = MAX_RESULTS,
    online: bool = False,
    fetch: Fetcher | None = None,
    title_hint: str | None = None,
) -> dict:
    """Search several providers and merge results, keeping evidence bound."""
    all_candidates: list[Candidate] = []
    problems: list[Problem] = []
    for provider in providers:
        result = search_provider(
            provider, query, limit=limit, online=online, fetch=fetch
        )
        if result.problem is not None:
            problems.append(result.problem)
        all_candidates.extend(result.candidates)

    if title_hint:
        all_candidates.sort(
            key=lambda c: title_similarity(title_hint, c.title), reverse=True
        )

    return {
        "query": query,
        "online": online,
        "providers": list(providers),
        "count": len(all_candidates),
        "candidates": [candidate._asdict() for candidate in all_candidates],
        "problems": [p._asdict() for p in problems],
    }


def candidate_to_bibtex(candidate: Candidate) -> str:
    """Render one candidate as a review-pending BibTeX entry."""
    slug = normalize_title(candidate.title).replace(" ", "_")[:60] or "candidate"
    key = f"{candidate.provider}:{slug}"
    authors = " and ".join(candidate.authors)
    lines = [
        f"@article{{{key},",
        f"  title = {{{candidate.title}}},",
    ]
    if authors:
        lines.append(f"  author = {{{authors}}},")
    if candidate.year is not None:
        lines.append(f"  year = {{{candidate.year}}},")
    if candidate.doi:
        lines.append(f"  doi = {{{candidate.doi}}},")
    if candidate.url:
        lines.append(f"  url = {{{candidate.url}}},")
    lines.append(f"  note = {{candidate from {candidate.provider}; retrieved {candidate.retrieved_at}; {candidate.body_sha256}; needs human review}}")
    lines.append("}")
    return "\n".join(lines)


def _write_bib(path: Path, candidates: list[Candidate]) -> int:
    """Append candidates that are not already present. Never overwrite."""
    path = Path(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    additions = 0
    with path.open("a", encoding="utf-8") as handle:
        for candidate in candidates:
            block = candidate_to_bibtex(candidate)
            marker = block.split("\n", 1)[0]
            if marker and marker in existing:
                continue
            handle.write("\n" + block + "\n")
            additions += 1
    return additions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 OpenAlex / arXiv / Semantic Scholar 检索候选文献（只读，显式联网）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("providers", help="列出可用检索源")
    listing.set_defaults(command="providers")

    searching = sub.add_parser("search", help="检索候选文献")
    searching.add_argument("--query", required=True, help="标题或关键词")
    searching.add_argument(
        "--provider", action="append", choices=PROVIDERS, help="可重复；默认全部"
    )
    searching.add_argument("--limit", type=int, default=MAX_RESULTS)
    searching.add_argument(
        "--online",
        action="store_true",
        help="真正发起网络请求；不传则只校验参数、不联网",
    )
    searching.add_argument("--title-hint", help="按与该标题的相似度排序")
    searching.add_argument("--write-bib", help="把候选追加写入指定 .bib（不覆盖）")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "providers":
            print(json.dumps({"providers": list(PROVIDERS)}, ensure_ascii=False))
            return 0
        if args.command == "search":
            providers = tuple(args.provider) if args.provider else PROVIDERS
            result = search(
                args.query,
                providers=providers,
                limit=args.limit,
                online=args.online,
                title_hint=args.title_hint,
            )
            if args.write_bib:
                candidates = [
                    Candidate(**item) for item in result["candidates"]
                ]
                result["written"] = _write_bib(Path(args.write_bib), candidates)
            problems = [Problem(**item) for item in result["problems"]]
            return _emit_result(result, problems)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知命令: {args.command}")


def _emit_result(result: dict, problems: list[Problem]) -> int:
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    for problem in problems:
        print(f"{problem.path}: {problem.code}: {problem.message}", file=sys.stderr)
    # Match the ccfa.cli.emit contract: a provider/parse failure is a problem,
    # so the CLI must fail closed instead of reporting success with empty hits.
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
