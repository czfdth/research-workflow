"""Resilient HTTP transport for the literature search clients.

The search providers in :mod:`ccfa.literature_search` need to survive the
ordinary failures of public scholarly APIs: transient 5xx, 429 rate limits and
short network outages. This module adds exponential backoff with jitter,
``Retry-After`` handling, an optional ``mailto`` contact for polite pools and
a per-instance circuit breaker that trips on repeated 429s.

Design constraints, inherited from the rest of this repository:

* No new third-party dependencies; urllib and the standard library only.
* Fail closed. After retries are exhausted a transient HTTP failure is
  returned as a non-2xx status, and a network failure is re-raised as an
  ``OSError``. A tripped breaker raises :class:`CircuitOpenError`. None of
  these can be mistaken for "the search succeeded with zero hits".
* Everything is injectable. ``raw_fetch``, ``sleep`` and ``clock`` are
  constructor arguments, so tests never touch the network or wait in real
  time. Breaker state lives on the instance, not in module globals; the single
  shared default fetcher is the only process-wide instance and callers that
  inject their own fetch bypass it entirely.
* Secrets are never logged. :func:`redact_url` masks API keys and tokens in
  query parameters; :meth:`TransportFetcher.last_redacted_url` is the value
  callers can safely record for diagnostics.
"""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

RawFetcher = Callable[
    [str, float], "tuple[int, str | bytes] | tuple[int, str | bytes, dict]"
]

# Statuses that are worth retrying: rate limiting and server-side faults.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
BASE_DELAY = 0.5
MAX_DELAY = 8.0
# A Retry-After larger than this is not worth blocking a CLI for; skip it.
MAX_RETRY_AFTER = 300.0
CB_THRESHOLD = 3
CB_INITIAL_COOLDOWN = 30.0
CB_MAX_COOLDOWN = 300.0
_SENSITIVE_KEYS = frozenset({"api_key", "apikey", "key", "token", "access_token"})


class CircuitOpenError(OSError):
    """Raised when the breaker is open and the request is not allowed."""


def redact_url(url: str) -> str:
    """Mask credential-like query parameters in *url* for safe diagnostics."""
    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted = [
        (key, "***" if key.lower() in _SENSITIVE_KEYS else value)
        for key, value in pairs
    ]
    # Keep the literal asterisks readable in diagnostics (urlencode would
    # otherwise escape them to %2A%2A%2A).
    query = urllib.parse.urlencode(redacted, safe="*")
    return urllib.parse.urlunsplit(parsed._replace(query=query))


def _retry_after_seconds(value: object) -> float | None:
    """Parse a numeric Retry-After header; ignore HTTP-dates (indeterminate)."""
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except (ValueError, TypeError):
        return None
    return seconds if seconds >= 0 else None


class CircuitBreaker:
    """CLOSED -> OPEN on repeated 429s, then HALF_OPEN after a cooldown.

    Instance state only; ``clock`` is injectable so cooldown transitions are
    deterministic in tests. Successful non-429 requests reset the breaker.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        *,
        threshold: int = CB_THRESHOLD,
        initial_cooldown: float = CB_INITIAL_COOLDOWN,
        max_cooldown: float = CB_MAX_COOLDOWN,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.initial_cooldown = initial_cooldown
        self.max_cooldown = max_cooldown
        self._clock = clock
        self.state = self.CLOSED
        self.consecutive_429 = 0
        self.cooldown = initial_cooldown
        self._opened_at = 0.0
        self.trip_count = 0

    def allow(self) -> bool:
        """Whether a request may proceed; moves OPEN -> HALF_OPEN when due."""
        if self.state == self.CLOSED:
            return True
        if self.state == self.HALF_OPEN:
            return True
        if self._clock() - self._opened_at >= self.cooldown:
            self.state = self.HALF_OPEN
            return True
        return False

    def on_success(self) -> None:
        self.consecutive_429 = 0
        if self.state != self.CLOSED:
            self.state = self.CLOSED
            self.cooldown = self.initial_cooldown

    def on_429(self) -> None:
        self.consecutive_429 += 1
        if self.state == self.HALF_OPEN:
            # A failed probe is a repeated trip: back off further.
            self._trip(backoff=True)
        elif self.consecutive_429 >= self.threshold:
            # First trip from CLOSED uses the current (initial) cooldown.
            self._trip(backoff=False)

    def on_failure(self) -> None:
        """A non-429 failure during HALF_OPEN keeps the breaker open."""
        if self.state == self.HALF_OPEN:
            self._trip(backoff=True)

    def _trip(self, *, backoff: bool) -> None:
        if backoff:
            self.cooldown = min(self.cooldown * 2, self.max_cooldown)
        self.state = self.OPEN
        self._opened_at = self._clock()
        self.trip_count += 1

    def reset(self) -> None:
        self.state = self.CLOSED
        self.consecutive_429 = 0
        self.cooldown = self.initial_cooldown
        self._opened_at = 0.0
        self.trip_count = 0


def default_raw_fetch(url: str, timeout: float) -> tuple[int, bytes, dict]:
    """urllib GET returning (status, body, headers) with HTTPError normalized."""
    request = urllib.request.Request(url, headers={"User-Agent": "ccfa-lit-transport/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, b"", dict(exc.headers or {})


class TransportFetcher:
    """Callable ``(url, timeout) -> (status, body)`` with retry and a breaker.

    ``raw_fetch`` may return a 2- or 3-tuple; the third element, when present,
    is the response header mapping used for ``Retry-After``. Sleep is jittered
    unless ``jitter=False`` (tests set this to avoid nondeterminism).
    """

    def __init__(
        self,
        raw_fetch: RawFetcher = default_raw_fetch,
        *,
        sleep: Callable[[float], None] = time.sleep,
        breaker: CircuitBreaker | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        base_delay: float = BASE_DELAY,
        max_delay: float = MAX_DELAY,
        jitter: bool = True,
        contact: str = "",
    ) -> None:
        self._fetch = raw_fetch
        self._sleep = sleep
        self.breaker = breaker or CircuitBreaker()
        self.max_attempts = max(1, max_attempts)
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.contact = contact.strip()
        self.last_redacted_url = ""

    def _delay(self, attempt: int) -> float:
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay += random.uniform(0, delay * 0.2)
        return delay

    def __call__(self, url: str, timeout: float) -> tuple[int, str | bytes]:
        self.last_redacted_url = redact_url(url)
        if not self.breaker.allow():
            raise CircuitOpenError(
                f"断路器打开，拒绝请求: {self.last_redacted_url}"
            )

        last_error: OSError | None = None
        last_status = 0
        last_body: str | bytes = b""
        for attempt in range(self.max_attempts):
            try:
                outcome = self._fetch(url, timeout)
            except OSError as exc:
                last_error = exc
                self.breaker.on_failure()
                if attempt + 1 < self.max_attempts:
                    self._sleep(self._delay(attempt))
                    continue
                raise  # network failure is never reported as an empty success
            if len(outcome) == 3:
                status, body, headers = outcome
            else:
                status, body = outcome
                headers = {}
            last_status, last_body = status, body

            if status in RETRY_STATUSES and attempt + 1 < self.max_attempts:
                if status == 429:
                    self.breaker.on_429()
                    declared = _retry_after_seconds(headers.get("Retry-After"))
                    if declared is not None and declared > MAX_RETRY_AFTER:
                        break  # absurd wait: fail closed with the 429 status
                    delay = declared if declared is not None else self._delay(attempt)
                else:
                    self.breaker.on_failure()
                    delay = self._delay(attempt)
                self._sleep(min(delay, MAX_RETRY_AFTER))
                continue

            # Non-retryable status (including a final retryable one) is
            # returned verbatim so the provider reports an HTTP problem.
            if 200 <= status < 300:
                self.breaker.on_success()
            elif status == 429:
                self.breaker.on_429()
            else:
                self.breaker.on_failure()
            return status, body

        if last_error is not None:
            raise last_error
        return last_status, last_body


def make_default_fetcher(contact: str = "") -> TransportFetcher:
    """Build the shared default fetcher; ``contact`` feeds polite-pool UA."""
    fetcher = TransportFetcher(contact=contact)
    if contact:
        def polite_fetch(url: str, timeout: float) -> tuple[int, bytes, dict]:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": f"ccfa-lit-transport/0.1 (mailto:{contact})"
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.status, response.read(), dict(response.headers)
            except urllib.error.HTTPError as exc:
                return exc.code, b"", dict(exc.headers or {})

        fetcher._fetch = polite_fetch
    return fetcher
