import unittest

from ccfa.doi_lookup import lookup


def _fetcher(responses):
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        for needle, response in responses.items():
            if needle in url:
                return response
        return (404, "")

    return fetch, calls


class TestLookup(unittest.TestCase):
    def test_crossref_hit_does_not_consult_datacite(self):
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        result = lookup("10.1/x", fetch=fetch)
        self.assertTrue(result.found)
        self.assertEqual(result.source, "crossref")
        self.assertEqual(len(calls), 1)

    def test_datacite_is_tried_when_crossref_misses(self):
        fetch, calls = _fetcher({"api.datacite.org": (200, "{}")})
        result = lookup("10.1/x", fetch=fetch)
        self.assertTrue(result.found)
        self.assertEqual(result.source, "datacite")
        self.assertEqual(len(calls), 2)

    def test_both_miss_reports_not_found(self):
        fetch, _ = _fetcher({})
        result = lookup("10.1/x", fetch=fetch)
        self.assertFalse(result.found)
        self.assertIsNone(result.source)
        self.assertIn("404", result.detail)

    def test_network_error_is_reported_not_raised(self):
        def fetch(url, timeout):
            raise OSError("connection reset")

        result = lookup("10.1/x", fetch=fetch)
        self.assertFalse(result.found)
        self.assertIn("connection reset", result.detail)

    def test_doi_is_normalized_before_the_request(self):
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        lookup("https://doi.org/10.1/MiXeD", fetch=fetch)
        self.assertIn("10.1%2Fmixed", calls[0])

    def test_empty_doi_is_not_found_without_a_request(self):
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        result = lookup("", fetch=fetch)
        self.assertFalse(result.found)
        self.assertEqual(calls, [])

    def test_url_uses_the_crossref_endpoint(self):
        fetch, calls = _fetcher({"crossref.org": (200, "{}")})
        lookup("10.1/x", fetch=fetch)
        self.assertTrue(calls[0].startswith("https://api.crossref.org/works/"))
