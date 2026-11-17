"""Load and write the citation verification ledger.

This ledger is the record of what was checked at retrieval time. It is what
separates "a key that exists because someone verified it" from "a key that
exists because a model typed it". A ``verified`` record must carry fetched
evidence; the loader never crashes on a missing or malformed evidence block,
it records the reason on the entry so ``citation_guard`` can report it.

``evidence.body_sha256`` is the sha256 of the raw response bytes, and
``evidence.body_b64`` archives those bytes (base64). Storing the body makes the
digest re-computable offline and binds the recorded title to the actual
response, so a hand-written ledger with a plausible hash but no real body is
detected. This is an internal-consistency and content-binding check, not
cryptographic proof: someone who fabricates a whole body and recomputes its
hash can still pass, but the body is archived for audit.

Ledgers written before ``body_b64`` existed load fine; those records get a
non-blocking advisory that the body is not stored.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import NamedTuple

from ccfa.bib import normalize_doi
from ccfa.cli import save_text_atomically
from ccfa.doi_lookup import normalize_title

VALID_STATUSES = ("verified", "unverified", "failed")

EVIDENCE_FIELDS = ("body_sha256", "retrieved_at", "matched_title", "source")
BODY_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class LedgerEvidence(NamedTuple):
    body_sha256: str
    retrieved_at: str
    matched_title: str
    source: str
    # base64 of the raw response bytes. Empty means a legacy record written
    # before the body was archived: the digest cannot be recomputed offline.
    body_b64: str = ""


class BodyCheck(NamedTuple):
    """Result of re-deriving an evidence body's digest offline."""

    verdict: str  # "verified" | "recompute-mismatch" | "body-invalid" | "body-absent"
    detail: str


class LedgerRecord(NamedTuple):
    key: str
    doi: str | None
    status: str
    verified_at: str
    source: str
    evidence: LedgerEvidence | None = None
    evidence_error: str = ""
    detail: str = ""


def _parse_evidence(value: object) -> LedgerEvidence:
    if not isinstance(value, dict):
        raise ValueError("evidence 必须是对象")
    for field in EVIDENCE_FIELDS:
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"evidence.{field} 必须是非空字符串")
    body_sha256 = value["body_sha256"].strip()
    if BODY_SHA256_PATTERN.fullmatch(body_sha256) is None:
        raise ValueError(
            "evidence.body_sha256 必须是 sha256:<64 位小写十六进制>"
        )
    body_b64 = value.get("body_b64", "")
    if not isinstance(body_b64, str):
        raise ValueError("evidence.body_b64 必须是字符串")
    return LedgerEvidence(
        body_sha256=body_sha256,
        retrieved_at=value["retrieved_at"].strip(),
        matched_title=value["matched_title"].strip(),
        source=value["source"].strip(),
        body_b64=body_b64.strip(),
    )


def verify_evidence_body(evidence: LedgerEvidence | None) -> BodyCheck:
    """Re-derive the stored body's digest and check the title is bound to it.

    * ``body-absent``: a legacy record with no archived body. Non-blocking;
      the digest cannot be recomputed offline.
    * ``body-invalid``: ``body_b64`` is not valid base64.
    * ``recompute-mismatch``: the bytes hash to something other than the
      declared ``body_sha256`` — the ledger was edited or corrupted.
    * ``title-unbound``: the body is intact but its text does not contain the
      recorded ``matched_title`` — evidence copied from a different response.
    * ``verified``: digest matches and the title is present in the body.
    """
    if evidence is None or not evidence.body_b64:
        return BodyCheck("body-absent", "证据未归档响应体，无法离线重算哈希")
    try:
        raw = base64.b64decode(evidence.body_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        return BodyCheck("body-invalid", f"body_b64 不是合法 base64: {exc}")
    recomputed = "sha256:" + hashlib.sha256(raw).hexdigest()
    if recomputed != evidence.body_sha256:
        return BodyCheck(
            "recompute-mismatch",
            f"响应体重算哈希 {recomputed} 与台账声明 "
            f"{evidence.body_sha256} 不一致",
        )
    text = raw.decode("utf-8", errors="replace")
    normalized_body = normalize_title(text)
    normalized_title = normalize_title(evidence.matched_title)
    if not normalized_title or normalized_title not in normalized_body:
        return BodyCheck(
            "title-unbound",
            "响应体中存在但找不到声明的匹配标题，证据可能被替换",
        )
    return BodyCheck("verified", "响应体哈希重算一致且标题绑定")


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

        evidence = None
        evidence_error = ""
        if status == "verified":
            raw_evidence = value.get("evidence")
            if raw_evidence is None:
                evidence_error = "缺少 evidence"
            else:
                try:
                    evidence = _parse_evidence(raw_evidence)
                except ValueError as exc:
                    evidence_error = str(exc)

        records[key] = LedgerRecord(
            key=key,
            doi=normalize_doi(doi),
            status=status,
            verified_at=str(value.get("verified_at", "")),
            source=str(value.get("source", "")),
            evidence=evidence,
            evidence_error=evidence_error,
            detail=(
                value.get("detail")
                if isinstance(value.get("detail"), str)
                else ""
            ),
        )
    return records


def save_ledger(path: Path, records: dict[str, LedgerRecord]) -> None:
    """Atomically write schema v1; evidence is serialized when present."""
    entries: dict[str, dict] = {}
    for key in sorted(records):
        record = records[key]
        entry: dict = {
            "doi": record.doi,
            "status": record.status,
            "verified_at": record.verified_at,
            "source": record.source,
        }
        if record.evidence is not None:
            evidence = dict(record.evidence._asdict())
            # Keep legacy ledgers byte-compatible: omit an empty body field.
            if not evidence.get("body_b64"):
                evidence.pop("body_b64", None)
            entry["evidence"] = evidence
        if record.detail:
            entry["detail"] = record.detail
        entries[key] = entry
    text = json.dumps(
        {"version": 1, "entries": entries},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    save_text_atomically(path, text, description="引用台账")
