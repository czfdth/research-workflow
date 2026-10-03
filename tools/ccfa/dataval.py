"""Scan LaTeX sources for \\dataval tags.

A tag is ``\\dataval{source_path:key_path}{claimed_value}``. Tags inside
comments do not count, and an escaped percent does not truncate a line.
Scanning is read-only and never touches the files it reads.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple

from ccfa.texcomment import strip_comment


class Tag(NamedTuple):
    path: str
    line: int
    source_path: str
    key_path: str
    claimed: str


_TAG = re.compile(r"\\dataval\{([^:}]+):([^}]+)\}\{([^}]*)\}")


def find_tags(paths: Iterable[Path]) -> list[Tag]:
    tags: list[Tag] = []
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, raw_line in enumerate(text.splitlines(), start=1):
            line = strip_comment(raw_line)
            for match in _TAG.finditer(line):
                tags.append(
                    Tag(
                        str(path),
                        number,
                        match.group(1).strip(),
                        match.group(2).strip(),
                        match.group(3).strip(),
                    )
                )
    return tags
