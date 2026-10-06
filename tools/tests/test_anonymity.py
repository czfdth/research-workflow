"""The anonymisation gate for double-blind submissions."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import anonymity


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _paper(root: Path, body: str = "\\author{\\IEEEauthorblockN{Anonymous Submission}}\n") -> Path:
    (root / "manuscript").mkdir(parents=True, exist_ok=True)
    _write(root / "manuscript" / "main.tex", body)
    return root


def _config(root: Path, **overrides) -> Path:
    payload = {"version": 1, "blind": True}
    payload.update(overrides)
    return _write(
        root / "data" / "anonymity.yaml",
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    )


def _codes(items) -> list[str]:
    return [item.code for item in items]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_a_missing_config_falls_back_to_double_blind_defaults(self):
        config, problems = anonymity.load_config(self.root)

        self.assertEqual(problems, [])
        self.assertTrue(config["blind"])
        self.assertFalse(config["config_present"])

    def test_an_invalid_version_is_a_problem(self):
        _config(self.root, version=99)

        _config_payload, problems = anonymity.load_config(self.root)

        self.assertEqual(_codes(problems), ["anonymity-config-invalid"])

    def test_an_invalid_acknowledgements_value_is_a_problem(self):
        _config(self.root, acknowledgements="maybe")

        _config_payload, problems = anonymity.load_config(self.root)

        self.assertEqual(_codes(problems), ["anonymity-config-invalid"])

    def test_a_non_mapping_config_is_a_problem(self):
        _write(self.root / "data" / "anonymity.yaml", "- a\n- b\n")

        _config_payload, problems = anonymity.load_config(self.root)

        self.assertEqual(_codes(problems), ["anonymity-config-invalid"])


class SourceScanTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _check(self, body: str, **config) -> tuple[list, list]:
        _paper(self.root, body)
        if config:
            _config(self.root, **config)
        return anonymity.check(self.root)

    def test_a_clean_anonymous_manuscript_passes(self):
        problems, advisories = self._check(
            "\\author{\\IEEEauthorblockN{Anonymous Submission}}\n"
            "\\begin{document}\nWe propose a framework.\\end{document}\n"
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_a_declared_author_name_fails(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\nWe thank Zhang San for help.\n",
            authors=["Zhang San"],
        )

        self.assertIn("anonymity-author-name", _codes(problems))

    def test_a_declared_affiliation_fails(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\nExample University, Beijing\n",
            affiliations=["Example University"],
        )

        self.assertIn("anonymity-affiliation", _codes(problems))

    def test_self_referential_phrasing_fails(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\nOur previous work studied this.\n"
        )

        self.assertIn("anonymity-self-reference", _codes(problems))

    def test_chinese_self_reference_fails(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\n我们之前的工作研究过这个问题。\n"
        )

        self.assertIn("anonymity-self-reference", _codes(problems))

    def test_ordinary_first_person_prose_is_not_flagged(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\nOur method improves recall; we show that "
            "our approach is faster than the baseline.\n"
        )

        self.assertEqual(problems, [])

    def test_a_non_anonymous_author_block_fails(self):
        problems, _advisories = self._check(
            "\\author{\\IEEEauthorblockN{Jane Doe}\\IEEEauthorblockA{MIT}}\n"
        )

        self.assertIn("anonymity-author-block", _codes(problems))

    def test_a_comment_line_is_ignored(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\n% Zhang San wrote this section\n",
            authors=["Zhang San"],
        )

        self.assertEqual(problems, [])

    def test_a_declared_self_url_fails(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\nSee https://github.com/czfdth/code for details.\n",
            self_urls=["github.com/czfdth"],
        )

        self.assertIn("anonymity-self-url", _codes(problems))

    def test_an_unlisted_code_url_is_only_an_advisory(self):
        problems, advisories = self._check(
            "\\author{Anonymous}\nArtifacts at https://github.com/someone/artifact.\n"
        )

        self.assertEqual(problems, [])
        self.assertIn("anonymity-url-review", _codes(advisories))

    def test_an_allowlisted_url_is_not_an_advisory(self):
        problems, advisories = self._check(
            "\\author{Anonymous}\nSee https://github.com/anonymous/release\n",
            allow=["github.com/anonymous"],
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_an_acknowledgements_section_is_an_advisory_by_default(self):
        problems, advisories = self._check(
            "\\author{Anonymous}\n\\section*{Acknowledgments}\nThanks to reviewers.\n"
        )

        self.assertEqual(problems, [])
        self.assertIn("anonymity-acknowledgement", _codes(advisories))

    def test_an_acknowledgements_section_fails_when_forbidden(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\n\\section*{Acknowledgments}\nThanks.\n",
            acknowledgements="forbidden",
        )

        self.assertIn("anonymity-acknowledgement", _codes(problems))

    def test_a_missing_manuscript_is_a_problem(self):
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        config, _problems = anonymity.load_config(self.root)

        problems, _advisories = anonymity.check_sources(self.root, config)

        self.assertEqual(_codes(problems), ["anonymity-manuscript-missing"])

    def test_a_cross_rebuttal_reference_fails(self):
        # ARIS resubmit-pipeline layer 4.
        problems, _advisories = self._check(
            "\\author{Anonymous}\n"
            "This revision addresses reviewer 2's concern from the prior submission.\n"
        )

        self.assertIn("anonymity-cross-rebuttal", _codes(problems))

    def test_chinese_cross_rebuttal_reference_fails(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\n本文回应了上次投稿的审稿意见。\n"
        )

        self.assertIn("anonymity-cross-rebuttal", _codes(problems))

    def test_an_internal_codename_fails(self):
        problems, _advisories = self._check(
            "\\author{Anonymous}\nThe Project Falcon harness collects traces.\n",
            codenames=["Project Falcon"],
        )

        self.assertIn("anonymity-codename", _codes(problems))

    def test_an_internal_workspace_link_is_an_advisory(self):
        # ARIS resubmit-pipeline layer 5.
        problems, advisories = self._check(
            "\\author{Anonymous}\nSee the internal wiki for details.\n"
        )

        self.assertEqual(problems, [])
        self.assertIn("anonymity-internal-link", _codes(advisories))

    def test_residual_revision_markup_is_an_advisory(self):
        problems, advisories = self._check(
            "\\author{Anonymous}\n\\todo{check this number} and \\textcolor{red}{fix}\n"
        )

        self.assertEqual(problems, [])
        self.assertIn("anonymity-residual-markup", _codes(advisories))

    def test_an_acknowledgements_macro_is_detected(self):
        problems, advisories = self._check(
            "\\author{Anonymous}\n\\acknowledgments{Thanks to the funders.}\n"
        )

        self.assertEqual(problems, [])
        self.assertIn("anonymity-acknowledgement", _codes(advisories))

    def test_a_standalone_acknowledgements_file_is_detected(self):
        _paper(self.root)
        _write(
            self.root / "manuscript" / "acknowledgments.tex",
            "We thank the funders.\n",
        )
        config, _problems = anonymity.load_config(self.root)

        _problems, advisories = anonymity.check_sources(self.root, config)

        self.assertIn("anonymity-acknowledgement", _codes(advisories))


class ConfigDrivenTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_blind_false_reports_not_applicable(self):
        _paper(self.root, "\\author{Jane Doe}\n")
        _config(self.root, blind=False)

        problems, advisories = anonymity.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(_codes(advisories), ["anonymity-not-applicable"])

    def test_a_missing_paper_root_is_an_error(self):
        problems, _advisories = anonymity.check(self.root / "nope")

        self.assertEqual(_codes(problems), ["anonymity-root-missing"])


class PdfMetadataTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        _paper(self.root)

    def _make_pdf(self, *, author: str) -> Path:
        import pymupdf

        path = self.root / "manuscript" / "main.pdf"
        document = pymupdf.open()
        document.new_page()
        document.set_metadata({"author": author})
        document.save(path)
        document.close()
        return path

    def test_an_empty_pdf_author_is_clean(self):
        self._make_pdf(author="")
        config, _problems = anonymity.load_config(self.root)

        problems, _advisories = anonymity.check_pdfs(self.root, config)

        self.assertEqual(problems, [])

    def test_a_non_anonymous_pdf_author_fails(self):
        self._make_pdf(author="Jane Doe")
        config, _problems = anonymity.load_config(self.root)

        problems, _advisories = anonymity.check_pdfs(self.root, config)

        self.assertIn("anonymity-pdf-author", _codes(problems))

    def test_a_declared_name_in_pdf_metadata_fails(self):
        self._make_pdf(author="Anonymous")
        config, _problems = anonymity.load_config(self.root)
        config["affiliations"] = ["Example University"]
        path = self.root / "manuscript" / "main.pdf"
        import pymupdf

        with pymupdf.open(path) as document:
            metadata = dict(document.metadata or {})
        metadata["subject"] = "Example University"
        with pymupdf.open(path) as document:
            document.set_metadata(metadata)
            document.saveIncr()

        problems, _advisories = anonymity.check_pdfs(self.root, config)

        self.assertIn("anonymity-pdf-metadata", _codes(problems))

    def test_an_anonymous_pdf_author_passes(self):
        self._make_pdf(author="Anonymous Submission")
        config, _problems = anonymity.load_config(self.root)

        problems, _advisories = anonymity.check_pdfs(self.root, config)

        self.assertEqual(problems, [])


class CliTests(unittest.TestCase):
    def _run(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = anonymity.main(["anonymity", *argv])
        return code, stdout.getvalue()

    def test_a_clean_paper_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _paper(Path(tmp))

            code, output = self._run(["--paper-root", str(root)])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["problem_count"], 0)

    def test_a_leak_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _paper(root, "\\author{Anonymous}\nOur previous work did this.\n")

            code, output = self._run(["--paper-root", str(root)])

        self.assertEqual(code, 1)
        self.assertGreaterEqual(json.loads(output)["problem_count"], 1)


if __name__ == "__main__":
    unittest.main()
