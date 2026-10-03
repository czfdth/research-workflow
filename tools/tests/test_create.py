import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import newpaper.create as create_module
import yaml
from ccfa.validate import validate_yaml
from newpaper.create import create_project
from newpaper.venues import VenueNotFound


class TestCreateProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.papers = self.tmp / "papers"
        self.papers.mkdir()

    def _create(
        self,
        slug="demo-paper",
        venue="NeurIPS",
        mode="conference",
        title="Demo Paper",
        year="2027",
    ):
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue=venue,
            year=year,
            mode=mode,
            title=title,
        )

    def _venue_template(self, name="fake-venue"):
        template = self.tmp / name
        template.mkdir()
        (template / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        return template

    def test_creates_expected_tree(self):
        root = self._create()
        for rel in [
            "ccfa.yaml",
            "manuscript/sections",
            "manuscript/references.bib",
            "data/provenance.md",
            "experiments/log",
            "experiments/results",
            "figures",
            "tables",
            "reviews/revision-ledger.md",
            "submission/repro",
            "memory/ideas.md",
            "memory/dead-ends.md",
            "ccfa-workfiles/literature",
        ]:
            with self.subTest(rel=rel):
                self.assertTrue((root / rel).exists(), f"缺少 {rel}")

    def test_ccfa_yaml_is_valid_and_carries_mode(self):
        root = self._create(mode="journal")
        problems = validate_yaml(root / "ccfa.yaml")
        self.assertEqual(problems, [], problems)
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn('mode: "journal"', text)

    def test_stage_starts_at_idea(self):
        root = self._create()
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn('current: "idea"', text)

    def test_refuses_to_overwrite_existing_directory(self):
        root = self._create()
        marker = root / "manuscript" / "keep-me.txt"
        marker.write_text("user content", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self._create()
        self.assertTrue(marker.exists(), "已存在的用户文件被破坏")

    def test_seeds_bibliography_and_manuscript(self):
        root = self._create()
        self.assertTrue((root / "manuscript" / "references.bib").is_file())
        tex_files = list((root / "manuscript").glob("*.tex"))
        tex_files += list((root / "manuscript").glob("*.sty"))
        self.assertTrue(tex_files, "venue 模板文件未被复制到 manuscript/")

    def test_unknown_venue_propagates(self):
        with self.assertRaises(VenueNotFound):
            self._create(venue="NotAVenue2099")

    def test_records_detected_main_tex_in_ccfa_yaml(self):
        from ccfa.texdoc import find_main_tex

        root = self._create()
        main = find_main_tex(root / "manuscript")
        rel = main.relative_to(root).as_posix()
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn(f'manuscript: "{rel}"', text)

    def test_validate_slug_rejects_unsafe_names(self):
        for slug in [
            "..",
            "../escape",
            "a/b",
            "a\\b",
            "C:\\evil",
            "/abs/evil",
            "UPPER",
            "",
            "with space",
            "-leading-dash",
        ]:
            with self.subTest(slug=slug):
                with self.assertRaises(ValueError):
                    create_module.validate_slug(slug)

    def test_validate_slug_accepts_conservative_names(self):
        for slug in [
            "a",
            "demo-paper",
            "paper.v2",
            "p_1",
            "a-1_b.c",
            "console",
            "content",
        ]:
            with self.subTest(slug=slug):
                self.assertEqual(create_module.validate_slug(slug), slug)

    def test_validate_slug_rejects_windows_reserved_device_names(self):
        for slug in ["con", "con.txt", "aux.paper", "CON", "com1", "lpt9"]:
            with self.subTest(slug=slug):
                with self.assertRaises(ValueError):
                    create_module.validate_slug(slug)

    def test_create_project_rejects_unsafe_slug_without_writing(self):
        for slug in ["..", "../escape", "a/b", "a\\b", "UPPER"]:
            with self.subTest(slug=slug):
                with self.assertRaises(ValueError):
                    self._create(slug=slug)
        self.assertEqual(list(self.papers.iterdir()), [])
        self.assertEqual([entry.name for entry in self.tmp.iterdir()], ["papers"])

    def test_create_project_rechecks_target_containment(self):
        escape = str(self.tmp / "outside" / "paper")
        with mock.patch("newpaper.create.validate_slug", return_value=escape):
            with self.assertRaises(ValueError):
                self._create(slug="whatever")
        self.assertFalse((self.tmp / "outside").exists())

    def test_main_reports_unsafe_slug_as_problem(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = create_module.main(
                [
                    "create.py",
                    "../oops",
                    "--venue",
                    "NeurIPS",
                    "--year",
                    "2027",
                    "--mode",
                    "conference",
                    "--papers-root",
                    str(self.papers),
                ]
            )
        self.assertEqual(code, 1)
        self.assertFalse((self.tmp / "oops").exists())
        self.assertEqual(list(self.papers.iterdir()), [])

    def test_main_reports_reserved_slug_as_problem(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = create_module.main(
                [
                    "create.py",
                    "con",
                    "--venue",
                    "NeurIPS",
                    "--year",
                    "2027",
                    "--mode",
                    "conference",
                    "--papers-root",
                    str(self.papers),
                ]
            )
        self.assertEqual(code, 1)
        self.assertEqual(list(self.papers.iterdir()), [])

    def test_title_with_quotes_still_validates(self):
        root = self._create(title='My "Quoted" Paper')
        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])
        data = yaml.safe_load((root / "ccfa.yaml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["title"], 'My "Quoted" Paper')

    def test_tricky_scalars_round_trip_as_strings(self):
        template = self._venue_template()
        venue = 'NeurIPS: "Main" #1'
        title = 'A "title": #not-a-comment'
        year = "20:27"
        with mock.patch("newpaper.create.resolve_venue", return_value=template):
            root = create_project(
                papers_root=self.papers,
                slug="tricky-scalars",
                venue=venue,
                year=year,
                mode="conference",
                title=title,
            )
        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])
        data = yaml.safe_load((root / "ccfa.yaml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["title"], title)
        self.assertEqual(data["project"]["short_name"], "tricky-scalars")
        self.assertEqual(data["target_venue"]["name"], venue)
        self.assertEqual(data["target_venue"]["year"], year)

    def test_main_defaults_papers_root_to_repository_papers(self):
        captured = {}

        def fake_create_project(**kwargs):
            captured.update(kwargs)
            return Path("unused")

        with mock.patch("newpaper.create.create_project", new=fake_create_project):
            with contextlib.redirect_stdout(io.StringIO()):
                code = create_module.main(
                    [
                        "create.py",
                        "demo-paper",
                        "--venue",
                        "NeurIPS",
                        "--year",
                        "2027",
                        "--mode",
                        "conference",
                        "--title",
                        "Demo",
                    ]
                )
        self.assertEqual(code, 0)
        expected = Path(create_module.__file__).resolve().parents[2] / "papers"
        self.assertEqual(captured["papers_root"], expected)

    def test_failed_template_leaves_no_debris_and_stays_retryable(self):
        broken = self.tmp / "broken-template"
        broken.mkdir()
        (broken / "venue.cls").write_text("% no documentclass here\n", encoding="utf-8")
        with mock.patch("newpaper.create.resolve_venue", return_value=broken):
            with self.assertRaises(FileNotFoundError):
                self._create(slug="retry-demo")
        self.assertFalse(
            (self.papers / "retry-demo").exists(),
            "失败后残留了半成品目录，重试会被 FileExistsError 挡住",
        )

        good = self._venue_template("good-template")
        with mock.patch("newpaper.create.resolve_venue", return_value=good):
            root = self._create(slug="retry-demo")
        self.assertTrue((root / "ccfa.yaml").is_file())
        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])
