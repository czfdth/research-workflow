"""Verify every \\dataval tag against its live source.

Read-only: never edits the manuscript or the data files it reads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from ccfa.cli import Problem, emit, tool_error
from ccfa.datasource import SourceError, load_source, navigate, resolve_within_base_dir
from ccfa.dataval import Tag, find_tags
from ccfa.datavalue import values_match

_TAG_ERRORS = (SourceError, OSError, ValueError, KeyError, IndexError, TypeError)


def _resolve(tag: Tag, base_dir: Path | None) -> object:
    try:
        source = resolve_within_base_dir(tag.source_path, base_dir)
        kind, data = load_source(source)
        return navigate(kind, data, tag.key_path)
    except _TAG_ERRORS as exc:
        raise SourceError(str(exc)) from exc


def _documents(paths: Iterable[str]) -> list[Path]:
    docs: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"文档不存在或不是文件: {path}")
        docs.append(path)
    return docs


def check(
    docs: Iterable[Path],
    base_dir: Path | None = None,
    tolerance: float = 1e-9,
    rel_tolerance: float = 0.0,
) -> tuple[list[Problem], list[Problem]]:
    problems: list[Problem] = []
    for tag in find_tags(docs):
        try:
            actual = _resolve(tag, base_dir)
        except SourceError as exc:
            problems.append(
                Problem(
                    "dataval-error",
                    tag.path,
                    tag.line,
                    f"标签源不可解析（{tag.source_path}:{tag.key_path}）: {exc}",
                )
            )
            continue
        if not values_match(tag.claimed, actual, tolerance, rel_tolerance):
            problems.append(
                Problem(
                    "dataval-mismatch",
                    tag.path,
                    tag.line,
                    f"标记值 {tag.claimed!r} 与源值 {str(actual)!r} 不符"
                    f"（{tag.source_path}:{tag.key_path}）",
                )
            )
    return problems, []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="核验正文数字与源数据一致")
    parser.add_argument("--doc", action="append", required=True, dest="docs")
    parser.add_argument("--base-dir")
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--rel-tolerance", type=float, default=0.0)
    args = parser.parse_args(argv[1:])

    try:
        docs = _documents(args.docs)
        base_dir = Path(args.base_dir) if args.base_dir else None
        problems, advisories = check(docs, base_dir, args.tolerance, args.rel_tolerance)
    except ValueError as exc:
        return tool_error(str(exc))

    return emit(problems, advisories)


if __name__ == "__main__":
    # Windows consoles default to a locale code page; pin the contract streams.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
