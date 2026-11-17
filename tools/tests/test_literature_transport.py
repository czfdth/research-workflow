"""Offline tests for the literature transport resilience layer."""

from __future__ import annotations

import unittest

from ccfa.literature_transport import (
    CircuitBreaker,
    CircuitOpenError,
    TransportFetcher,
    make_default_fetcher,
    redact_url,
)


class Clock:
    """Manually advanced clock for deterministic breaker windows."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RedactTests(unittest.TestCase):
    def test_masks_key_and_token_but_keeps_query(self):
        url = (
            "https://api.example.org/search?api_key=SECRET&token=T&query=gravity"
        )
        out = redact_url(url)
        self.assertNotIn("SECRET", out)
        self.assertNotIn("token=T", out)
        self.assertIn("query=gravity", out)
        self.assertIn("***", out)


class RetryTests(unittest.TestCase):
    def _fetcher(self, outcomes, **kwargs):
        calls = []
        iterator = iter(outcomes)

        def raw(url, timeout):
            calls.append(url)
            outcome = next(iterator)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        sleeps = []
        fetcher = TransportFetcher(
            raw,
            sleep=lambda seconds: sleeps.append(seconds),
            jitter=False,
            **kwargs,
        )
        return fetcher, calls, sleeps

    def test_429_retry_after_then_success(self):
        fetcher, calls, sleeps = self._fetcher(
            [
                (429, b"", {"Retry-After": "1"}),
                (200, b"ok", {}),
            ]
        )
        status, body = fetcher("https://x.test", 5.0)
        self.assertEqual((status, body), (200, b"ok"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1.0])

    def test_500_exponential_backoff_then_success(self):
        fetcher, calls, sleeps = self._fetcher(
            [(500, b"", {}), (502, b"", {}), (200, b"ok", {})]
        )
        status, body = fetcher("https://x.test", 5.0)
        self.assertEqual((status, body), (200, b"ok"))
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_retry_exhaustion_returns_last_status_not_success(self):
        fetcher, calls, _ = self._fetcher(
            [(503, b"", {}), (503, b"", {}), (503, b"", {})]
        )
        status, _ = fetcher("https://x.test", 5.0)
        self.assertEqual(status, 503)
        self.assertEqual(len(calls), 3)

    def test_absurd_retry_after_skips_wait(self):
        fetcher, calls, sleeps = self._fetcher(
            [(429, b"", {"Retry-After": "9999"})]
        )
        status, _ = fetcher("https://x.test", 5.0)
        self.assertEqual(status, 429)
        self.assertEqual(sleeps, [])
        self.assertEqual(len(calls), 1)

    def test_network_error_retried_then_raised(self):
        def raw(url, timeout):
            raise OSError("offline")

        sleeps = []
        fetcher = TransportFetcher(
            raw, sleep=lambda s: sleeps.append(s), jitter=False
        )
        with self.assertRaises(OSError):
            fetcher("https://x.test", 5.0)
        self.assertEqual(len(sleeps), 2)

    def test_success_reset_breaker_and_no_retry(self):
        calls = []

        def raw(url, timeout):
            calls.append(url)
            return 200, b"ok", {}

        breaker = CircuitBreaker()
        fetcher = TransportFetcher(raw, breaker=breaker, jitter=False)
        self.assertEqual(fetcher("https://x.test", 5.0)[0], 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)

    def test_last_redacted_url_is_safe(self):
        fetcher, _, _ = self._fetcher([(200, b"ok", {})])
        fetcher("https://x.test/s?api_key=SECRET", 5.0)
        self.assertNotIn("SECRET", fetcher.last_redacted_url)


class CircuitBreakerTests(unittest.TestCase):
    def test_trips_after_threshold_429s_then_denies(self):
        clock = Clock()
        breaker = CircuitBreaker(
            threshold=2, initial_cooldown=10, clock=clock
        )
        self.assertTrue(breaker.allow())
        breaker.on_429()
        breaker.on_429()
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)
        self.assertFalse(breaker.allow())

        clock.advance(10)
        self.assertTrue(breaker.allow())
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)
        breaker.on_success()
        self.assertEqual(breaker.state, CircuitBreaker.CLOSED)

    def test_open_breaker_raises_circuit_open_error(self):
        clock = Clock()
        breaker = CircuitBreaker(threshold=1, clock=clock)
        breaker.on_429()
        calls = []

        def raw(url, timeout):
            calls.append(url)
            return 200, b"ok", {}

        fetcher = TransportFetcher(raw, breaker=breaker, jitter=False)
        with self.assertRaises(CircuitOpenError):
            fetcher("https://x.test", 5.0)
        self.assertEqual(calls, [])

    def test_half_open_probe_failure_retrips(self):
        clock = Clock()
        breaker = CircuitBreaker(threshold=2, initial_cooldown=5, clock=clock)
        breaker.on_429()
        breaker.on_429()
        clock.advance(5)
        self.assertTrue(breaker.allow())
        self.assertEqual(breaker.state, CircuitBreaker.HALF_OPEN)
        breaker.on_failure()
        self.assertEqual(breaker.state, CircuitBreaker.OPEN)
        self.assertEqual(breaker.trip_count, 2)


class DefaultFetcherTests(unittest.TestCase):
    def test_make_default_fetcher_is_transport_instance(self):
        fetcher = make_default_fetcher("team@example.org")
        self.assertIsInstance(fetcher, TransportFetcher)
        self.assertIn("team@example.org", fetcher.contact)

    def test_polite_contact_is_used_in_wrapped_fetch(self):
        # The wrapped callable still obeys the (status, body, headers) contract.
        fetcher = make_default_fetcher("team@example.org")
        self.assertTrue(callable(fetcher._fetch))


if __name__ == "__main__":
    unittest.main()
