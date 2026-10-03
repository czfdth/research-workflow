"""Load a BibTeX file into a key -> entry mapping.

DOI values are normalized: a URL prefix is stripped and the result is
lowercased, so the same DOI written two ways compares equal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import bibtexparser


class BibEntry(NamedTuple):
    key: str
    doi: str | None
    title: str | None


_DOI_URL_PREFIX = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_BRACES = re.compile(r"[{}]")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip()
    doi = _DOI_URL_PREFIX.sub("", doi)
    return doi.lower() or None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return _BRACES.sub("", value).strip() or None


def load_entries(path: Path) -> dict[str, BibEntry]:
    """Return entries by key. Raises ValueError on a missing or invalid file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc

    library = bibtexparser.parse_string(text)
    if library.failed_blocks:
        kinds = ", ".join(type(block).__name__ for block in library.failed_blocks)
        raise ValueError(f"BibTeX 解析失败于 {path}: {kinds}")

    entries: dict[str, BibEntry] = {}
    for entry in library.entries:
        fields = entry.fields_dict
        doi = fields.get("doi")
        title = fields.get("title")
        entries[entry.key] = BibEntry(
            key=entry.key,
            doi=normalize_doi(doi.value if doi else None),
            title=_clean(title.value if title else None),
        )
    return entries
