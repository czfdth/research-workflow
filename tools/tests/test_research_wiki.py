import json
import tempfile
import unittest
from pathlib import Path

from ccfa.research_wiki import (
    build_index,
    check_wiki,
    search_index,
)


ENTRY = """\
---
id: rw:001
kind: decision
title: Use a dedicated artifact badge ledger
status: active
tags: [artifact, reproducibility]
projects: [rag-attack-defense]
evidence: [run:RUN1, url:https://example.test/report]
related: []
updated_at: '2026-10-05'
---

# Decision

Keep artifact badge evidence machine readable.
"""


class ResearchWikiTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.wiki = Path(self._temporary.name)
        (self.wiki / "README.md").write_text("# Wiki\n", encoding="utf-8")

    def _write_entry(self, name: str, text: str = ENTRY) -> Path:
        path = self.wiki / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_entry_passes(self):
        self._write_entry("decision.md")

        problems, advisories = check_wiki(self.wiki)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_duplicate_id_is_problem(self):
        self._write_entry("one.md")
        self._write_entry(
            "two.md",
            ENTRY.replace("title: Use a dedicated", "title: Duplicate"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-duplicate-id",
            [problem.code for problem in problems],
        )

    def test_invalid_enum_is_problem(self):
        self._write_entry(
            "bad.md",
            ENTRY.replace("kind: decision", "kind: mystery"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-invalid",
            [problem.code for problem in problems],
        )

    def test_missing_fields_is_problem(self):
        self._write_entry(
            "missing.md",
            ENTRY.replace("title: Use a dedicated artifact badge ledger\n", ""),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-missing-field",
            [problem.code for problem in problems],
        )

    def test_unknown_related_link_is_problem(self):
        self._write_entry(
            "bad-link.md",
            ENTRY.replace("related: []", "related: [rw:404]"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-unknown-link",
            [problem.code for problem in problems],
        )

    def test_bad_evidence_is_problem(self):
        self._write_entry(
            "bad-evidence.md",
            ENTRY.replace("evidence: [run:RUN1, url:https://example.test/report]", "evidence: [doi:not-a-doi]"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-invalid-evidence",
            [problem.code for problem in problems],
        )

    def test_index_and_search(self):
        self._write_entry("decision.md")

        index = build_index(self.wiki)

        self.assertEqual(index["entry_count"], 1)
        self.assertEqual(index["entries"][0]["id"], "rw:001")
        self.assertEqual(
            search_index(index, "artifact badge")[0]["id"],
            "rw:001",
        )

    def test_missing_wiki_directory_is_problem(self):
        missing = self.wiki / "missing"

        problems, _advisories = check_wiki(missing)

        self.assertIn(
            "research-wiki-missing",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
