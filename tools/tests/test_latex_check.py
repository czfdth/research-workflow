import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import ccfa.latex_check as latex_check
from ccfa.latex_check import check, main
from ccfa.latex_compile import CompileReport, CompileStep


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        self.tex = self.manuscript / "main.tex"
        self.tex.write_text("\\section{Intro}\n", encoding="utf-8")

    def write(self, body: str):
        self.tex.write_text(body, encoding="utf-8")

    def run_main(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["latex_check.py", "--manuscript", str(self.manuscript), *extra]
            )
        return code, out.getvalue(), err.getvalue()


class TestCheck(BaseCase):
    def test_clean_manuscript_has_no_problems(self):
        problems, advisories = check(self.manuscript)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_unclosed_brace_is_a_problem(self):
        self.write("\\section{Intro\n")
        problems, _ = check(self.manuscript)
        self.assertIn("unbalanced-brace", [p.code for p in problems])

    def test_missing_figure_is_a_problem(self):
        self.write("\\includegraphics{gone.png}\n")
        problems, _ = check(self.manuscript)
        self.assertIn("missing-figure", [p.code for p in problems])

    def test_missing_cite_key_is_a_problem(self):
        bib = self.root / "references.bib"
        bib.write_text("@misc{known, title={T}}\n", encoding="utf-8")
        self.write("\\cite{ghost}\n")
        problems, _ = check(self.manuscript, bib=bib)
        self.assertIn("missing-cite-key", [p.code for p in problems])

    def test_stray_percent_is_only_an_advisory(self):
        self.write("50% faster\n")
        problems, advisories = check(self.manuscript)
        self.assertNotIn("stray-percent", [p.code for p in problems])
        self.assertIn("stray-percent", [p.code for p in advisories])

    def test_failed_compile_step_becomes_a_problem(self):
        report = CompileReport("pdflatex", [CompileStep("pdflatex", "failed", 1)])
        original_compile = latex_check.compile_document
        original_engine = latex_check.find_engine
        latex_check.compile_document = lambda tex, engine: report
        latex_check.find_engine = lambda preferred=None: "pdflatex"
        try:
            problems, _ = check(self.manuscript, compile=True)
        finally:
            latex_check.compile_document = original_compile
            latex_check.find_engine = original_engine
        self.assertIn("compile-failed", [p.code for p in problems])


class TestMain(BaseCase):
    def test_missing_manuscript_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["latex_check.py", "--manuscript", str(self.root / "nope")]
            )
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")

    def test_compile_without_engine_exits_two(self):
        original = latex_check.find_engine
        latex_check.find_engine = lambda preferred=None: None
        try:
            code, _, _ = self.run_main("--compile")
        finally:
            latex_check.find_engine = original
        self.assertEqual(code, 2)

    def test_compile_tool_unavailable_exits_two(self):
        original_compile = latex_check.compile_document
        original_engine = latex_check.find_engine
        latex_check.find_engine = lambda preferred=None: "pdflatex"

        def _missing_tool(tex, engine):
            raise FileNotFoundError("bibtex")

        latex_check.compile_document = _missing_tool
        try:
            code, out, _ = self.run_main("--compile")
        finally:
            latex_check.compile_document = original_compile
            latex_check.find_engine = original_engine
        self.assertEqual(code, 2)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
