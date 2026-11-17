"""Tests for :mod:`ccfa.literature_search` (fully offline via injected fetch)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ccfa import literature_search as ls


OPENALEX_BODY = json.dumps(
    {
        "results": [
            {
                "display_name": "Attention Is All You Need",
                "publication_year": 2017,
                "doi": "https://doi.org/10.48550/arXiv.1706.03762",
                "authorships": [
                    {"author": {"display_name": "Ashish Vaswani"}},
                    {"author": {"display_name": "Noam Shazeer"}},
                ],
                "id": "https://openalex.org/W123",
            },
            {"display_name": "", "publication_year": 2017},
        ]
    }
)

S2_BODY = json.dumps(
    {
        "data": [
            {
                "title": "Attention Is All You Need",
                "year": 2017,
                "authors": [{"name": "Ashish Vaswani"}],
                "externalIds": {"DOI": "10.48550/arXiv.1706.03762"},
                "url": "https://example.test/paper",
            },
            {"authors": []},
        ]
    }
)

ARXIV_BODY = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Attention Is All You Need</title>
    <published>2017-06-12T00:00:00Z</published>
    <author><name>Ashish Vaswani</name></author>
    <link href="https://arxiv.org/abs/1706.03762"/>
  </entry>
</feed>"""


def fetch_ok(body: str):
    def getter(url: str, timeout: float):
        return 200, body

    return getter


class ProviderTests(unittest.TestCase):
    def test_openalex_parses_candidates_and_binds_evidence(self):
        result = ls.search_provider(
            "openalex", "attention", online=True, fetch=fetch_ok(OPENALEX_BODY)
        )
        self.assertIsNone(result.problem)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.title, "Attention Is All You Need")
        self.assertEqual(candidate.year, 2017)
        self.assertEqual(candidate.doi, "10.48550/arXiv.1706.03762")
        self.assertEqual(candidate.authors, ["Ashish Vaswani", "Noam Shazeer"])
        self.assertTrue(candidate.body_sha256.startswith("sha256:"))
        self.assertTrue(candidate.retrieved_at.endswith("Z"))

    def test_arxiv_parses_atom_feed(self):
        result = ls.search_provider(
            "arxiv", "attention", online=True, fetch=fetch_ok(ARXIV_BODY)
        )
        self.assertIsNone(result.problem)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].year, 2017)
        self.assertEqual(result.candidates[0].authors, ["Ashish Vaswani"])

    def test_semanticscholar_parses_candidates(self):
        result = ls.search_provider(
            "semanticscholar", "attention", online=True, fetch=fetch_ok(S2_BODY)
        )
        self.assertIsNone(result.problem)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].doi, "10.48550/arXiv.1706.03762")

    def test_http_status_is_a_problem_not_candidates(self):
        result = ls.search_provider(
            "openalex", "x", online=True, fetch=lambda u, t: (503, "nope")
        )
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.problem.code, "literature-search-http-error")
        self.assertTrue(result.http_ok)

    def test_malformed_body_fails_closed(self):
        for body in ("{not json", json.dumps({"unexpected": 1})):
            with self.subTest(body=body):
                result = ls.search_provider(
                    "openalex", "x", online=True, fetch=fetch_ok(body)
                )
                self.assertEqual(result.candidates, [])
                self.assertEqual(result.problem.code, "literature-search-malformed")

    def test_fetch_exception_is_a_problem(self):
        def boom(url: str, timeout: float):
            raise OSError("offline")

        result = ls.search_provider("openalex", "x", online=True, fetch=boom)
        self.assertEqual(result.problem.code, "literature-search-fetch-error")

    def test_empty_results_is_legal_not_a_problem(self):
        result = ls.search_provider(
            "openalex", "nothing", online=True, fetch=fetch_ok(json.dumps({"results": []}))
        )
        self.assertIsNone(result.problem)
        self.assertEqual(result.candidates, [])

    def test_unknown_provider_and_empty_query_rejected(self):
        with self.assertRaises(ValueError):
            ls.search_provider("nope", "x")
        with self.assertRaises(ValueError):
            ls.search_provider("arxiv", "   ")


class OfflineTests(unittest.TestCase):
    def test_default_search_does_no_network(self):
        def explode(url: str, timeout: float):
            raise AssertionError("network must not be touched without --online")

        result = ls.search("attention", fetch=explode)
        self.assertFalse(result["online"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["problems"], [])

    def test_title_hint_sorts_by_similarity(self):
        calls = {"n": 0}

        def mixed(url: str, timeout: float):
            calls["n"] += 1
            if "semanticscholar" in url:
                return 200, S2_BODY
            return 200, json.dumps(
                {
                    "results": [
                        {
                            "display_name": "A Completely Different Paper",
                            "publication_year": 2020,
                        }
                    ]
                }
            )

        result = ls.search(
            "attention",
            providers=("openalex", "semanticscholar"),
            online=True,
            fetch=mixed,
            title_hint="Attention Is All You Need",
        )
        self.assertEqual(result["candidates"][0]["title"], "Attention Is All You Need")


class WriteBibTests(unittest.TestCase):
    def test_write_bib_appends_without_overwriting(self):
        result = ls.search_provider(
            "openalex", "attention", online=True, fetch=fetch_ok(OPENALEX_BODY)
        )
        with tempfile.TemporaryDirectory() as tmp:
            bib = Path(tmp) / "refs.bib"
            bib.write_text("@article{existing, title={Keep me}}\n", encoding="utf-8")
            written = ls._write_bib(bib, result.candidates)
            self.assertEqual(written, 1)
            text = bib.read_text(encoding="utf-8")
            self.assertIn("@article{existing", text)
            self.assertIn("Attention Is All You Need", text)
            self.assertIn("needs human review", text)
            written_again = ls._write_bib(bib, result.candidates)
            self.assertEqual(written_again, 0)


class CliTests(unittest.TestCase):
    def test_providers_subcommand(self):
        self.assertEqual(ls.main(["literature-search", "providers"]), 0)

    def test_search_default_offline_exits_clean(self):
        self.assertEqual(
            ls.main(["literature-search", "search", "--query", "x"]), 0
        )

    def test_search_with_provider_problem_exits_nonzero(self):
        # A failed provider must fail closed at the CLI boundary too, matching
        # ccfa.cli.emit (1 when problems exist), not report success with no hits.
        from unittest.mock import patch

        def bad_fetch(url, timeout):
            return 503, "unavailable"

        with patch.object(ls, "_default_fetch", bad_fetch):
            code = ls.main(
                [
                    "literature-search",
                    "search",
                    "--query",
                    "x",
                    "--provider",
                    "openalex",
                    "--online",
                ]
            )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
