"""Report citations that cannot be trusted.

The manuscript and bibliography are never edited. ``--verify-online``
performs the DOI lookups and rewrites the citation ledger with the fetched
evidence; without it the tool is read-only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.bib import load_entries, normalize_doi
from ccfa.citation_ledger import (
    LedgerEvidence,
    LedgerRecord,
    load_ledger,
    save_ledger,
    verify_evidence_body,
)
from ccfa.cli import Problem, emit, tool_error
from ccfa.doi_lookup import lookup
from ccfa.texscan import find_cited_keys, iter_tex_files


def check(
    manuscript: Path,
    bib_path: Path,
    ledger_path: Path,
    verify_online: bool = False,
    fetch=None,
    verify_titles_online: bool = False,
    title_fetch=None,
    arxiv_fetch=None,
) -> tuple[list[Problem], list[Problem]]:
    """Check citations; the ``fetch`` arguments are offline test injection points.

    ``verify_titles_online`` resolves entries that have no DOI. An entry with
    an arXiv ``eprint`` is verified by ID first (stronger than a fuzzy title
    hit); otherwise the indexes are searched by title. Both are opt-in and
    fail closed: only a high-similarity match with a fetched-body evidence
    record is accepted; weak, ambiguous or errored lookups stay unverified and
    are reported as a problem or advisory.
    """
    manuscript = Path(manuscript)
    if not manuscript.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
    cited = find_cited_keys(iter_tex_files(manuscript))
    entries = load_entries(Path(bib_path))
    ledger = load_ledger(Path(ledger_path))

    problems: list[Problem] = []
    advisories: list[Problem] = []

    if verify_online:
        refreshed = dict(ledger)
        for key in sorted(entries):
            entry = entries[key]
            if not entry.doi:
                continue
            result = lookup(
                entry.doi,
                fetch=fetch,
                expected_title=entry.title,
            )
            if result.found and result.evidence is not None:
                refreshed[key] = LedgerRecord(
                    key=key,
                    doi=normalize_doi(entry.doi),
                    status="verified",
                    verified_at=result.evidence.retrieved_at,
                    source=result.evidence.source,
                    evidence=LedgerEvidence(**result.evidence._asdict()),
                    evidence_error="",
                )
            else:
                if result.http_ok:
                    code = "doi-lookup-failed"
                    message = (
                        f"条目 {key} 的 DOI {entry.doi} 核验失败"
                        f"（{result.detail}）"
                    )
                else:
                    code = "doi-not-found"
                    message = (
                        f"条目 {key} 的 DOI {entry.doi} 无法解析"
                        f"（{result.detail}）"
                    )
                refreshed[key] = LedgerRecord(
                    key=key,
                    doi=normalize_doi(entry.doi),
                    status="failed",
                    verified_at="",
                    source=result.source or "",
                    evidence=None,
                    evidence_error="",
                    detail=result.detail,
                )
                problems.append(
                    Problem(
                        code,
                        str(bib_path),
                        None,
                        message,
                    )
                )
        save_ledger(Path(ledger_path), refreshed)
        ledger = refreshed

    if verify_titles_online:
        from ccfa import arxiv_lookup, literature_search
        from ccfa.doi_lookup import TITLE_MATCH_THRESHOLD, title_similarity

        refreshed = dict(ledger)
        for key in sorted(entries):
            entry = entries[key]
            if entry.doi:
                continue
            title = (entry.title or "").strip()
            if not title:
                continue

            # An arXiv eprint is stronger evidence than a fuzzy title hit:
            # resolve by ID first, binding the same fetched-body evidence as
            # the DOI path. A failed ID lookup falls through to title search.
            if entry.eprint:
                arx = arxiv_lookup.lookup(
                    entry.eprint,
                    fetch=arxiv_fetch,
                    expected_title=title or None,
                )
                if arx.found and arx.evidence is not None:
                    refreshed[key] = LedgerRecord(
                        key=key,
                        doi=arx.doi or None,
                        status="verified",
                        verified_at=arx.evidence.retrieved_at,
                        source=arx.evidence.source,
                        evidence=LedgerEvidence(**arx.evidence._asdict()),
                        evidence_error="",
                        detail=f"arxiv-id match: {entry.eprint}",
                    )
                    continue
                advisories.append(
                    Problem(
                        "arxiv-id-lookup-unresolved",
                        str(bib_path),
                        None,
                        f"条目 {key} 的 arXiv ID {entry.eprint} 未能核验"
                        f"（{arx.detail}）；转为标题反查",
                    )
                )

            result = literature_search.search(
                title,
                providers=("openalex", "semanticscholar"),
                online=True,
                fetch=title_fetch,
                title_hint=title,
            )
            for search_problem in result.get("problems", []):
                problems.append(
                    Problem(
                        "title-lookup-failed",
                        str(bib_path),
                        None,
                        f"条目 {key} 的标题反查失败（{search_problem['code']}）",
                    )
                )
            candidates = result.get("candidates", [])
            if not candidates:
                advisories.append(
                    Problem(
                        "title-no-match",
                        str(bib_path),
                        None,
                        f"条目 {key} 无 DOI 且标题反查没有返回候选: {title}",
                    )
                )
                continue
            from ccfa.doi_lookup import normalize_title

            best = candidates[0]
            similarity = title_similarity(title, best["title"])
            best_normalized = normalize_title(best["title"])
            # A second hit with the same normalized title is cross-source
            # corroboration, not ambiguity. Only a *different* high-similarity
            # title makes the match ambiguous.
            conflicting = any(
                title_similarity(title, item["title"]) >= TITLE_MATCH_THRESHOLD
                and normalize_title(item["title"]) != best_normalized
                for item in candidates[1:]
            )
            if similarity < TITLE_MATCH_THRESHOLD:
                advisories.append(
                    Problem(
                        "title-weak-match",
                        str(bib_path),
                        None,
                        f"条目 {key} 标题反查最高相似度 {similarity:.2f} "
                        f"低于阈值 {TITLE_MATCH_THRESHOLD}；"
                        f"保持未核验，候选: {best['title']}",
                    )
                )
                continue
            if conflicting:
                advisories.append(
                    Problem(
                        "title-ambiguous-match",
                        str(bib_path),
                        None,
                        f"条目 {key} 标题反查有多个高相似候选，"
                        "无法机械判定，保持未核验；需人工选择",
                    )
                )
                continue
            refreshed[key] = LedgerRecord(
                key=key,
                doi=best.get("doi") or None,
                status="verified",
                verified_at=best["retrieved_at"],
                source=best["provider"],
                evidence=LedgerEvidence(
                    body_sha256=best["body_sha256"],
                    retrieved_at=best["retrieved_at"],
                    matched_title=best["title"],
                    source=best["provider"],
                    body_b64=best.get("body_b64", ""),
                ),
                evidence_error="",
                detail=f"title-match similarity={similarity:.2f}",
            )
        save_ledger(Path(ledger_path), refreshed)
        ledger = refreshed

    for key, locations in sorted(cited.items()):
        if key not in entries:
            for location in locations:
                problems.append(
                    Problem(
                        "dangling-cite",
                        location.path,
                        location.line,
                        f"正文引用了文献表中不存在的键: {key}",
                    )
                )

    for key in sorted(entries):
        record = ledger.get(key)
        if record is None or record.status != "verified":
            reason = "台账中无记录" if record is None else f"台账状态为 {record.status}"
            problems.append(
                Problem(
                    "unverified-entry",
                    str(bib_path),
                    None,
                    f"条目未通过检索期核验（{reason}）: {key}",
                )
            )
        elif record.evidence is None:
            reason = record.evidence_error or "evidence 缺失或非法"
            problems.append(
                Problem(
                    "citation-self-asserted",
                    str(bib_path),
                    None,
                    f"条目 {key} 声明 verified 但没有可核验的响应体证据"
                    f"（{reason}）；请运行 citation_guard --verify-online 重新核验",
                )
            )
        else:
            # Re-derive the digest from the archived body. A hand-written
            # ledger with a plausible hash but no real body fails here; a
            # legacy record without a stored body only gets an advisory.
            body_check = verify_evidence_body(record.evidence)
            if body_check.verdict == "body-absent":
                advisories.append(
                    Problem(
                        "evidence-body-not-stored",
                        str(bib_path),
                        None,
                        f"条目 {key} 的证据未归档响应体，无法离线重算哈希；"
                        "请重新联网核验以写入 body_b64",
                    )
                )
            elif body_check.verdict != "verified":
                problems.append(
                    Problem(
                        "evidence-body-tampered",
                        str(bib_path),
                        None,
                        f"条目 {key} 的证据体校验失败"
                        f"（{body_check.verdict}: {body_check.detail}）；"
                        "台账可能被手写篡改或损坏，请重新联网核验",
                    )
                )

    by_doi: dict[str, list[str]] = {}
    for key, entry in entries.items():
        if entry.doi:
            by_doi.setdefault(entry.doi, []).append(key)
    for doi, keys in sorted(by_doi.items()):
        if len(keys) > 1:
            problems.append(
                Problem(
                    "duplicate-doi",
                    str(bib_path),
                    None,
                    f"DOI {doi} 被多个条目共用: {', '.join(sorted(keys))}",
                )
            )

    for key in sorted(entries):
        if key not in cited:
            advisories.append(
                Problem(
                    "orphan-entry",
                    str(bib_path),
                    None,
                    f"条目从未被正文引用: {key}",
                )
            )

    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查引用的可信性")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--bib", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument(
        "--verify-online",
        action="store_true",
        help=(
            "在线核验 DOI，并把响应体证据（sha256、时间、标题、来源）"
            "写入 --ledger；会改写台账文件。body_sha256 证明某次取回发生过，"
            "但未存响应体时无法离线复算，防伪造边界不完整"
        ),
    )
    parser.add_argument(
        "--verify-titles-online",
        action="store_true",
        help=(
            "对没有 DOI 的条目按标题从 OpenAlex/arXiv/Semantic Scholar 反查；"
            "只有高相似度且带响应体证据的命中才会写成 verified，"
            "弱匹配/歧义保持未核验并给出 advisory；会改写台账文件"
        ),
    )
    args = parser.parse_args(argv[1:])

    try:
        problems, advisories = check(
            Path(args.manuscript),
            Path(args.bib),
            Path(args.ledger),
            verify_online=args.verify_online,
            verify_titles_online=args.verify_titles_online,
        )
    except ValueError as exc:
        return tool_error(str(exc))

    return emit(problems, advisories)


if __name__ == "__main__":
    # Windows consoles default to a locale code page (e.g. GBK). The CLI
    # contract is UTF-8 JSON on stdout, so pin both streams before any write.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
