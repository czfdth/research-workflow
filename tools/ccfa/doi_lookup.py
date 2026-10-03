"""Check whether a DOI resolves, via Crossref then DataCite.

Network access is opt-in at the caller level: nothing here runs unless
lookup() is called explicitly.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, NamedTuple

from ccfa.bib import normalize_doi

Fetcher = Callable[[str, float], "tuple[int, str]"]

_ENDPOINTS = (
    ("crossref", "https://api.crossref.org/works/{doi}"),
    ("datacite", "https://api.datacite.org/dois/{doi}"),
)

_USER_AGENT = "paper-template-citation-guard/0.1"


class LookupResult(NamedTuple):
    doi: str
    found: bool
    source: str | None
    detail: str


def _default_fetch(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def lookup(doi: str, fetch: Fetcher | None = None, timeout: float = 20.0) -> LookupResult:
    normalized = normalize_doi(doi)
    if not normalized:
        return LookupResult(doi="", found=False, source=None, detail="DOI 为空")

    fetcher = fetch or _default_fetch
    attempts: list[str] = []
    for source, template in _ENDPOINTS:
        url = template.format(doi=urllib.parse.quote(normalized, safe=""))
        try:
            status, _body = fetcher(url, timeout)
        except OSError as exc:
            attempts.append(f"{source}: 网络错误 {exc}")
            continue
        if status == 200:
            return LookupResult(normalized, True, source, f"{source} 返回 200")
        attempts.append(f"{source}: HTTP {status}")

    return LookupResult(normalized, False, None, "; ".join(attempts))
