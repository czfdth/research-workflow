"""Load the citation verification ledger.

This ledger is the record of what was checked at retrieval time. It is what
separates "a key that exists because someone verified it" from "a key that
exists because a model typed it".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from ccfa.bib import normalize_doi

VALID_STATUSES = ("verified", "unverified", "failed")


class LedgerRecord(NamedTuple):
    key: str
    doi: str | None
    status: str
    verified_at: str
    source: str


def load_ledger(path: Path) -> dict[str, LedgerRecord]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取台账 {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"台账不是合法 JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("台账顶层必须是对象")
    if "version" not in data:
        raise ValueError("台账缺少 version 字段")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("台账 entries 必须是对象")

    records: dict[str, LedgerRecord] = {}
    for key, value in entries.items():
        if not isinstance(value, dict):
            raise ValueError(f"台账条目 {key} 必须是对象")
        status = value.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"台账条目 {key} 的 status 非法: {status!r}，应为 {' / '.join(VALID_STATUSES)}"
            )
        doi = value.get("doi")
        if doi is not None and not isinstance(doi, str):
            raise ValueError(f"台账条目 {key} 的 doi 必须是字符串或 null，实际是 {type(doi).__name__}")
        records[key] = LedgerRecord(
            key=key,
            doi=normalize_doi(doi),
            status=status,
            verified_at=str(value.get("verified_at", "")),
            source=str(value.get("source", "")),
        )
    return records
