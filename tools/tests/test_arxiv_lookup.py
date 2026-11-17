"""Offline tests for arXiv id normalization and fail-closed ID lookup."""

from __future__ import annotations

import unittest

from ccfa import arxiv_lookup
from ccfa.bib import normalize_arxiv_id

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
  </entry>
</feed>
"""

ATOM_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format</id>
    <title>Error</title>
  </entry>
</feed>
"""


class NormalizeTests(unittest.TestCase):
    def test_new_style_and_version(self):
        self.assertEqual(normalize_arxiv_id("1706.03762"), "1706.03762")
        self.assertEqual(normalize_arxiv_id("arXiv:1706.03762v7"), "1706.03762")

    def test_url_and_old_style(self):
        self.assertEqual(
            normalize_arxiv_id("https://arxiv.org/abs/cs/0501001"), "cs/0501001"
        )
        self.assertEqual(normalize_arxiv_id("math.GT/0309136v2"), "math.GT/0309136")

    def test_free_text_is_rejected(self):
        for value in ("", None, "attention is all you need", "10.1/not-arxiv"):
            self.assertIsNone(normalize_arxiv_id(value))


class LookupTests(unittest.TestCase):
    def _run(self, body=ATOM, status=200, *, title=None, fetch=None):
        getter = fetch or (lambda url, timeout: (status, body))
        return arxiv_lookup.lookup(
            "1706.03762", fetch=getter, expected_title=title
        )

    def test_success_binds_evidence(self):
        result = self._run(title="Attention Is All You Need")
        self.assertTrue(result.found)
        self.assertEqual(result.source, "arxiv")
        self.assertEqual(result.evidence.matched_title, "Attention Is All You Need")
        self.assertEqual(result.evidence.source, "arxiv")
        self.assertTrue(result.evidence.body_sha256.startswith("sha256:"))
        self.assertTrue(result.evidence.retrieved_at.endswith("Z"))

    def test_title_mismatch_fails_closed(self):
        result = self._run(title="A Completely Different Paper")
        self.assertFalse(result.found)
        self.assertEqual(result.detail, "title mismatch")
        self.assertIsNone(result.evidence)

    def test_wrong_entry_is_not_accepted(self):
        other = ATOM.replace("1706.03762v7", "1706.99999v1")
        result = self._run(body=other)
        self.assertFalse(result.found)
        self.assertIn("没有匹配", result.detail)

    def test_error_entry_is_not_accepted(self):
        result = self._run(body=ATOM_ERROR)
        self.assertFalse(result.found)

    def test_http_error_fails_closed(self):
        result = self._run(status=503)
        self.assertFalse(result.found)
        self.assertTrue(result.http_ok)
        self.assertIsNone(result.evidence)

    def test_malformed_xml_fails_closed(self):
        result = self._run(body="not xml at all")
        self.assertFalse(result.found)

    def test_fetch_exception_fails_closed(self):
        def explode(url, timeout):
            raise OSError("offline")

        result = self._run(fetch=explode)
        self.assertFalse(result.found)
        self.assertFalse(result.http_ok)

    def test_empty_id_does_no_io(self):
        def explode(url, timeout):
            raise AssertionError("no I/O for empty id")

        result = arxiv_lookup.lookup("not an id", fetch=explode)
        self.assertFalse(result.found)
        self.assertIn("非法", result.detail)


if __name__ == "__main__":
    unittest.main()
