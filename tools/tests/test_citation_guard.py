import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ccfa.citation_guard import check, main

BIB = r"""
@misc{good, doi = {10.1/ok}}
@misc{unverified, doi = {10.1/unverified}}
@misc{orphan, doi = {10.1/orphan}}
@misc{dupa, doi = {10.1/same}}
@misc{dupb, doi = {10.1/same}}
"""

LEDGER = {
    "version": 1,
    "entries": {
        "good": {"status": "verified", "doi": "10.1/ok"},
        "unverified": {"status": "unverified", "doi": "10.1/unverified"},
        "orphan": {"status": "verified", "doi": "10.1/orphan"},
        "dupa": {"status": "verified", "doi": "10.1/same"},
        "dupb": {"status": "verified", "doi": "10.1/same"},
    },
}


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "manuscript").mkdir()
        self.bib = self.root / "references.bib"
        self.bib.write_text(BIB, encoding="utf-8")
        self.ledger = self.root / "citation-ledger.json"
        self.ledger.write_text(json.dumps(LEDGER), encoding="utf-8")

    def cite(self, body: str):
        (self.root / "manuscript" / "main.tex").write_text(body, encoding="utf-8")

    def run_check(self):
        return check(self.root / "manuscript", self.bib, self.ledger)

    @staticmethod
    def codes(problems):
        return sorted(p.code for p in problems)


class TestCheck(BaseCase):
    def test_clean_manuscript_has_no_problems(self):
        # 用一份全部已核验的最小语料。共享 fixture 里含有故意置为 unverified
        # 的条目，而守卫要求 bib 中每个条目都已核验——不论是否被引用。
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {"good": {"status": "verified"}}}),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        problems, advisories = self.run_check()
        self.assertEqual(problems, [], problems)
        self.assertEqual(advisories, [])

    def test_dangling_cite_is_a_problem_with_location(self):
        self.cite(r"\cite{ghost}")
        problems, _ = self.run_check()
        self.assertIn("dangling-cite", self.codes(problems))
        dangling = [p for p in problems if p.code == "dangling-cite"][0]
        self.assertIn("ghost", dangling.message)
        self.assertEqual(dangling.line, 1)
        self.assertTrue(dangling.path.endswith("main.tex"))

    def test_unverified_entry_is_a_problem(self):
        self.cite(r"\cite{good} \cite{unverified}")
        problems, _ = self.run_check()
        self.assertIn("unverified-entry", self.codes(problems))

    def test_entry_missing_from_ledger_is_a_problem(self):
        self.cite(r"\cite{good}")
        self.ledger.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
        problems, _ = self.run_check()
        self.assertIn("unverified-entry", self.codes(problems))

    def test_duplicate_doi_is_a_problem(self):
        self.cite(r"\cite{good} \cite{dupa} \cite{dupb}")
        problems, _ = self.run_check()
        self.assertIn("duplicate-doi", self.codes(problems))

    def test_orphan_entry_is_only_an_advisory(self):
        self.cite(r"\cite{good}")
        problems, advisories = self.run_check()
        self.assertNotIn("orphan-entry", self.codes(problems))
        self.assertIn("orphan-entry", self.codes(advisories))

    def test_entry_without_doi_is_not_a_duplicate(self):
        self.bib.write_text("@misc{a, title={A}}\n@misc{b, title={B}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "a": {"status": "verified"},
                        "b": {"status": "verified"},
                    },
                }
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{a} \cite{b}")
        problems, _ = self.run_check()
        self.assertNotIn("duplicate-doi", self.codes(problems))


class TestMain(BaseCase):
    def test_clean_run_exits_zero(self):
        # 共享 fixture 含故意未核验与重复 DOI 的条目，无法干净退出；
        # 与 TestCheck.test_clean_manuscript_has_no_problems 用同一最小语料。
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {"good": {"status": "verified"}}}),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "manuscript"),
                    "--bib",
                    str(self.bib),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 0)

    def test_problem_run_exits_one(self):
        self.cite(r"\cite{ghost}")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "manuscript"),
                    "--bib",
                    str(self.bib),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 1)

    def test_missing_bib_exits_two(self):
        self.cite(r"\cite{good}")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "manuscript"),
                    "--bib",
                    str(self.root / "nope.bib"),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 2)

    def test_missing_manuscript_exits_two(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "nope"),
                    "--bib",
                    str(self.bib),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 2)


class TestVerifyOnline(BaseCase):
    def test_online_flag_is_off_by_default(self):
        self.cite(r"\cite{good}")
        problems, _ = check(self.root / "manuscript", self.bib, self.ledger)
        self.assertNotIn("doi-not-found", self.codes(problems))

    def test_online_flag_reports_a_dead_doi(self):
        self.cite(r"\cite{good}")
        import ccfa.citation_guard as guard
        from ccfa.doi_lookup import LookupResult

        def fake_lookup(doi, fetch=None, timeout=20.0):
            return LookupResult(doi, False, None, "crossref: HTTP 404")

        original = guard.lookup
        guard.lookup = fake_lookup
        try:
            problems, _ = check(
                self.root / "manuscript", self.bib, self.ledger, verify_online=True
            )
        finally:
            guard.lookup = original
        self.assertIn("doi-not-found", self.codes(problems))
