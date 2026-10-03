"""Report citations that cannot be trusted.

Read-only. Never edits the manuscript or the bibliography.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.bib import load_entries
from ccfa.citation_ledger import load_ledger
from ccfa.cli import Problem, emit, tool_error
from ccfa.doi_lookup import lookup
from ccfa.texscan import find_cited_keys, iter_tex_files


def check(
    manuscript: Path,
    bib_path: Path,
    ledger_path: Path,
    verify_online: bool = False,
) -> tuple[list[Problem], list[Problem]]:
    manuscript = Path(manuscript)
    if not manuscript.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
    cited = find_cited_keys(iter_tex_files(manuscript))
    entries = load_entries(Path(bib_path))
    ledger = load_ledger(Path(ledger_path))

    problems: list[Problem] = []
    advisories: list[Problem] = []

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

    if verify_online:
        for key in sorted(entries):
            doi = entries[key].doi
            if not doi:
                continue
            result = lookup(doi)
            if not result.found:
                problems.append(
                    Problem(
                        "doi-not-found",
                        str(bib_path),
                        None,
                        f"条目 {key} 的 DOI {doi} 无法解析（{result.detail}）",
                    )
                )

    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查引用的可信性")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--bib", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--verify-online", action="store_true")
    args = parser.parse_args(argv[1:])

    try:
        problems, advisories = check(
            Path(args.manuscript),
            Path(args.bib),
            Path(args.ledger),
            verify_online=args.verify_online,
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
