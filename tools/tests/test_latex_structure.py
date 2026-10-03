import tempfile
import unittest
from pathlib import Path

from ccfa.latex_structure import check_braces, check_environments, scan_structure


def _write(root: Path, body: str) -> Path:
    path = root / "main.tex"
    path.write_text(body, encoding="utf-8")
    return path


class TestBraces(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_balanced_braces_are_clean(self):
        self.assertEqual(check_braces(_write(self.root, r"\section{A} \textbf{b}")), [])

    def test_unclosed_brace_is_reported(self):
        problems = check_braces(_write(self.root, r"\section{A"))
        self.assertEqual([p.code for p in problems], ["unbalanced-brace"])

    def test_extra_closing_brace_is_reported_with_line(self):
        problems = check_braces(_write(self.root, "ok\n}\n"))
        self.assertEqual(problems[0].line, 2)

    def test_escaped_braces_do_not_count(self):
        self.assertEqual(check_braces(_write(self.root, r"a \{ b \}")), [])

    def test_brace_inside_a_comment_is_ignored(self):
        self.assertEqual(check_braces(_write(self.root, "% { unmatched")), [])

    def test_literal_backslash_then_comment_is_ignored(self):
        self.assertEqual(check_braces(_write(self.root, "line\\\\% { unmatched")), [])


class TestEnvironments(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_balanced_environments_are_clean(self):
        body = "\\begin{figure}\n\\end{figure}\n"
        self.assertEqual(check_environments(_write(self.root, body)), [])

    def test_mismatched_environment_names_are_reported(self):
        body = "\\begin{figure}\n\\end{table}\n"
        problems = check_environments(_write(self.root, body))
        self.assertEqual([p.code for p in problems], ["unmatched-environment"])
        self.assertIn("line 1", problems[0].message)

    def test_unclosed_environment_reports_its_open_line(self):
        problems = check_environments(_write(self.root, "text\n\\begin{table}\n"))
        self.assertEqual(problems[0].line, 2)

    def test_end_without_begin_is_reported(self):
        problems = check_environments(_write(self.root, "\\end{itemize}\n"))
        self.assertEqual(problems[0].line, 1)

    def test_environment_inside_a_comment_is_ignored(self):
        self.assertEqual(check_environments(_write(self.root, "% \\begin{figure}")), [])


class TestScanStructure(unittest.TestCase):
    def test_combines_both_checks(self):
        body = "\\begin{figure}\n{ unclosed\n"
        problems = scan_structure(_write(Path(tempfile.mkdtemp()), body))
        self.assertEqual(
            sorted(p.code for p in problems),
            ["unbalanced-brace", "unmatched-environment"],
        )


if __name__ == "__main__":
    unittest.main()
