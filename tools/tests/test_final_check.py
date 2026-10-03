import hashlib
import tempfile
import unittest
from pathlib import Path

from ccfa.final_check import check

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
CLEAN_TEXT = "Limitations and Data Availability are stated here."
MANIFEST = (
    "- name: plot\n"
    "  file: figures/plot.png\n"
    "  bytes_format: png\n"
    "  generator: src/plot.py\n"
    "  generator_hash: \"{hash}\"\n"
    "  referenced_in: [\"manuscript/main.tex:1\"]\n"
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        (self.manuscript / "main.tex").write_text("\\section{Intro}\n", encoding="utf-8")
        self.pdf = self.manuscript / "main.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n")
        self.figures = self.root / "figures"
        self.figures.mkdir()
        self.reader = lambda path: CLEAN_TEXT

    def run_check(self, **kwargs):
        kwargs.setdefault("reader", self.reader)
        return check(self.manuscript, pdf=self.pdf, **kwargs)

    def write_generator(self, body="print('x')\n"):
        path = self.root / "src" / "plot.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def write_manifest(self, body):
        path = self.root / "manifest.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    @staticmethod
    def codes(items):
        return sorted(item.code for item in items)


class TestCheck(BaseCase):
    def test_clean_paper_has_no_problems(self):
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_marker_in_pdf_text_is_a_problem(self):
        self.reader = lambda path: CLEAN_TEXT + " Figure ?? here"
        problems, _ = self.run_check()
        self.assertIn("unresolved-marker", self.codes(problems))

    def test_unreadable_pdf_is_skipped_not_passed(self):
        self.reader = lambda path: None
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertIn("check-skipped", self.codes(advisories))

    def test_jpeg_bytes_named_png_is_a_problem(self):
        (self.figures / "a.png").write_bytes(JPEG)
        problems, _ = self.run_check()
        self.assertIn("figure-format", self.codes(problems))

    def test_manifest_hash_mismatch_is_a_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        self.write_generator()
        manifest = self.write_manifest(MANIFEST.format(hash="sha256:deadbeef"))
        problems, _ = self.run_check(manifest=manifest)
        self.assertIn("figure-hash", self.codes(problems))

    def test_malformed_manifest_raises_value_error(self):
        manifest = self.write_manifest("name: not-a-list\n")
        with self.assertRaises(ValueError):
            self.run_check(manifest=manifest)

    def test_untagged_number_is_an_advisory(self):
        (self.manuscript / "main.tex").write_text(
            "Accuracy was 92.5 percent.\n", encoding="utf-8"
        )
        _, advisories = self.run_check()
        self.assertIn("untagged-number", self.codes(advisories))

    def test_missing_declaration_is_an_advisory(self):
        self.reader = lambda path: "nothing relevant here"
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertIn("missing-declaration", self.codes(advisories))

    def test_missing_pdf_raises_value_error(self):
        with self.assertRaises(ValueError):
            check(self.manuscript, pdf=self.root / "gone.pdf", reader=self.reader)

    def test_one_bad_figure_can_report_both_codes(self):
        # Decision 4: the two codes answer different questions, so both fire.
        (self.figures / "plot.png").write_bytes(JPEG)
        manifest = self.write_manifest(
            MANIFEST.format(hash=self.write_generator())
        )
        problems, _ = self.run_check(manifest=manifest)
        codes = self.codes(problems)
        self.assertIn("figure-format", codes)
        self.assertIn("figure-manifest-format", codes)


if __name__ == "__main__":
    unittest.main()
