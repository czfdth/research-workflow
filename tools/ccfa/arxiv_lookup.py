"""Verify an arXiv identifier via the public Atom API.

A 200 response is not evidence by itself. The feed must parse, contain an
``<entry>`` whose id resolves to the requested arXiv id, and carry a usable
non-empty title. When an expected title is supplied, it must be at least 0.9
similar after normalization. A successful lookup reuses ``doi_lookup``'s
:class:`LookupEvidence` / :class:`LookupResult` so a ledger entry written from
an arXiv id has the same shape as one written from a DOI.

As with ``doi_lookup``, ``body_sha256`` proves a fetch happened but is not a
complete anti-forgery boundary without the stored body.

Network access is opt-in at the caller level: nothing here runs unless
lookup() is called explicitly. ``fetch`` is injectable so tests stay offline.
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable

from ccfa.bib import normalize_arxiv_id
from ccfa.doi_lookup import (
    TITLE_MATCH_THRESHOLD,
    LookupEvidence,
    LookupResult,
    title_similarity,
)

Fetcher = Callable[[str, float], "tuple[int, str | bytes]"]

_ENDPOINT = "https://export.arxiv.org/api/query?id_list={arxiv_id}"
_USER_AGENT = "ccfa-arxiv-lookup/0.1"

_ATOM = "{http://www.w3.org/2005/Atom}"
_ERROR_TITLE = "error"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _body_sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _default_fetch(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def _failed(arxiv_id: str, detail: str, http_ok: bool) -> LookupResult:
    return LookupResult(
        doi=arxiv_id,
        found=False,
        source=None,
        detail=detail,
        evidence=None,
        http_ok=http_ok,
    )


def _entry_for_id(root: ET.Element, arxiv_id: str) -> ET.Element | None:
    """Return the Atom entry whose id carries *arxiv_id*, else None.

    arXiv answers an unknown id with an error entry whose title is literally
    "Error" and whose id points at its API error namespace; such an entry must
    never be mistaken for a resolved paper.
    """
    for entry in root.findall(f"{_ATOM}entry"):
        entry_id = entry.findtext(f"{_ATOM}id") or ""
        if normalize_arxiv_id(entry_id) != arxiv_id:
            continue
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        if not title or title.casefold() == _ERROR_TITLE:
            continue
        return entry
    return None


def lookup(
    arxiv_id: str,
    fetch: Fetcher | None = None,
    timeout: float = 20.0,
    *,
    expected_title: str | None = None,
) -> LookupResult:
    """Resolve *arxiv_id* and bind a successful answer to the fetched body.

    ``arxiv_id`` is normalized first; an empty or unrecognizable id fails
    closed without any I/O. HTTP errors, malformed XML, a missing/mismatched
    entry and a title mismatch are all ``found=False``.
    """
    normalized = normalize_arxiv_id(arxiv_id)
    if not normalized:
        return _failed("", "arXiv ID 为空或格式非法", False)

    fetcher = fetch or _default_fetch
    url = _ENDPOINT.format(arxiv_id=urllib.parse.quote(normalized, safe=""))
    try:
        status, body = fetcher(url, timeout)
    except (OSError, TimeoutError) as exc:
        return _failed(normalized, f"网络错误 {exc}", False)
    if not 200 <= status < 300:
        return _failed(normalized, f"HTTP {status}", True)

    raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return _failed(normalized, f"Atom 解析失败 {exc}", True)

    entry = _entry_for_id(root, normalized)
    if entry is None:
        return _failed(normalized, "响应中没有匹配的 arXiv entry", True)
    title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
    if not title:
        return _failed(normalized, "entry 缺少标题", True)

    if expected_title:
        similarity = title_similarity(expected_title, title)
        if similarity < TITLE_MATCH_THRESHOLD:
            return _failed(normalized, "title mismatch", True)

    evidence = LookupEvidence(
        body_sha256=_body_sha256(raw),
        retrieved_at=_utc_now(),
        matched_title=title,
        source="arxiv",
    )
    return LookupResult(
        doi=normalized,
        found=True,
        source="arxiv",
        detail="arxiv Atom 返回 200 且 ID/标题匹配",
        evidence=evidence,
        http_ok=True,
    )
