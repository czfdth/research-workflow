import contextlib
import io
import json
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
        self.templates_root = self.tmp / "templates"
        self.templates_root.mkdir()
        self._venue_template("NeurIPS")
        patcher = mock.patch(
            "newpaper.venues.templates_root",
            return_value=self.templates_root,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create(
        self,
        slug="demo-paper",
        venue="NeurIPS",
        mode="conference",
        title="Demo Paper",
        year="2027",
        deadline=None,
    ):
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue=venue,
            year=year,
            mode=mode,
            title=title,
            deadline=deadline,
        )

    def _venue_template(self, name="fake-venue"):
        template = self.templates_root / name
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
            "data/provenance.json",
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
        self.assertFalse((root / "data" / "provenance.md").exists())
        self.assertEqual(
            json.loads((root / "data" / "provenance.json").read_text(encoding="utf-8")),
            {"version": 1, "files": {}},
        )

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

    def test_copies_nested_venue_tree_preserving_relative_paths(self):
        template = self.templates_root / "NestedVenue"
        (template / "styles").mkdir(parents=True)
        (template / "figs").mkdir()
        (template / "empty").mkdir()
        (template / "sections").mkdir()
        (template / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        (template / "styles" / "x.sty").write_text("% style\n", encoding="utf-8")
        (template / "figs" / "f.pdf").write_bytes(b"%PDF-1.4 nested\n")
        (template / "sections" / "intro.tex").write_text(
            "% intro\n",
            encoding="utf-8",
        )

        root = self._create(slug="nested-venue", venue="NestedVenue")

        self.assertEqual(
            (root / "manuscript" / "styles" / "x.sty").read_text(
                encoding="utf-8"
            ),
            "% style\n",
        )
        self.assertEqual(
            (root / "manuscript" / "figs" / "f.pdf").read_bytes(),
            b"%PDF-1.4 nested\n",
        )
        self.assertEqual(
            (root / "manuscript" / "sections" / "intro.tex").read_text(
                encoding="utf-8"
            ),
            "% intro\n",
        )
        self.assertTrue((root / "manuscript" / "empty").is_dir())

    def test_flat_venue_files_keep_landing_at_manuscript_root(self):
        template = self._venue_template("FlatVenue")
        (template / "venue.cls").write_text("% class\n", encoding="utf-8")

        root = self._create(slug="flat-venue", venue="FlatVenue")

        self.assertTrue((root / "manuscript" / "main.tex").is_file())
        self.assertEqual(
            (root / "manuscript" / "venue.cls").read_text(encoding="utf-8"),
            "% class\n",
        )
        self.assertFalse((root / "manuscript" / "FlatVenue").exists())

    def test_nested_main_tex_is_found_and_recorded(self):
        template = self.templates_root / "NestedMain"
        nested = template / "src" / "paper"
        nested.mkdir(parents=True)
        (nested / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )

        root = self._create(slug="nested-main", venue="NestedMain")

        from ccfa.texdoc import find_main_tex

        main = find_main_tex(root / "manuscript")
        self.assertEqual(
            main.relative_to(root).as_posix(),
            "manuscript/src/paper/main.tex",
        )
        data = yaml.safe_load((root / "ccfa.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            data["artifacts"]["manuscript"],
            "manuscript/src/paper/main.tex",
        )

    def test_copy_failure_cleans_target_and_propagates_oserror(self):
        template = self.templates_root / "BrokenVenue"
        (template / "styles").mkdir(parents=True)
        (template / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        (template / "styles" / "x.sty").write_text("% style\n", encoding="utf-8")

        with mock.patch(
            "newpaper.create.shutil.copy2",
            side_effect=OSError("copy failed"),
        ):
            with self.assertRaises(OSError):
                self._create(slug="copy-failure", venue="BrokenVenue")

        self.assertFalse((self.papers / "copy-failure").exists())

    def test_main_reports_copy_failure_as_tool_error_and_cleans_target(self):
        template = self.templates_root / "CliBrokenVenue"
        (template / "styles").mkdir(parents=True)
        (template / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        (template / "styles" / "x.sty").write_text("% style\n", encoding="utf-8")
        stderr = io.StringIO()

        with mock.patch(
            "newpaper.create.shutil.copy2",
            side_effect=OSError("copy failed"),
        ):
            with contextlib.redirect_stderr(stderr):
                code = create_module.main(
                    [
                        "create.py",
                        "cli-copy-failure",
                        "--venue",
                        "CliBrokenVenue",
                        "--year",
                        "2027",
                        "--mode",
                        "conference",
                        "--papers-root",
                        str(self.papers),
                    ]
                )

        self.assertEqual(code, 2)
        self.assertIn("工具错误", stderr.getvalue())
        self.assertFalse((self.papers / "cli-copy-failure").exists())

    def test_recursive_copy_failure_leaves_project_retryable(self):
        template = self.templates_root / "RetryVenue"
        (template / "styles").mkdir(parents=True)
        (template / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        (template / "styles" / "x.sty").write_text("% style\n", encoding="utf-8")

        with mock.patch(
            "newpaper.create.shutil.copy2",
            side_effect=OSError("copy failed"),
        ):
            with self.assertRaises(OSError):
                self._create(slug="retry-nested", venue="RetryVenue")

        root = self._create(slug="retry-nested", venue="RetryVenue")

        self.assertTrue((root / "manuscript" / "styles" / "x.sty").is_file())

    def test_copy_failure_cleans_absent_papers_root_and_retry_succeeds(self):
        papers_root = self.tmp / "absent-papers-root"
        template = self.templates_root / "RootBrokenVenue"
        (template / "styles").mkdir(parents=True)
        (template / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        (template / "styles" / "x.sty").write_text("% style\n", encoding="utf-8")

        with mock.patch(
            "newpaper.create.shutil.copy2",
            side_effect=OSError("copy failed"),
        ):
            with self.assertRaises(OSError):
                create_project(
                    papers_root=papers_root,
                    slug="retry-root",
                    venue="RootBrokenVenue",
                    year="2027",
                    mode="conference",
                    title="Retry Root",
                )

        self.assertFalse(
            papers_root.exists(),
            "复制失败后 papers/ 根目录残留，重试会被 FileExistsError 挡住",
        )

        root = create_project(
            papers_root=papers_root,
            slug="retry-root",
            venue="RootBrokenVenue",
            year="2027",
            mode="conference",
            title="Retry Root",
        )
        self.assertTrue((root / "ccfa.yaml").is_file())
        self.assertTrue((root / "manuscript" / "styles" / "x.sty").is_file())

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
        before = sorted(entry.name for entry in self.tmp.iterdir())
        for slug in ["..", "../escape", "a/b", "a\\b", "UPPER"]:
            with self.subTest(slug=slug):
                with self.assertRaises(ValueError):
                    self._create(slug=slug)
        self.assertEqual(list(self.papers.iterdir()), [])
        self.assertEqual(
            sorted(entry.name for entry in self.tmp.iterdir()),
            before,
        )

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

    def test_create_records_optional_deadline(self):
        root = self._create(deadline="2027-05-01")

        data = yaml.safe_load((root / "ccfa.yaml").read_text(encoding="utf-8"))
        self.assertEqual(data["target_venue"]["deadline"], "2027-05-01")
        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])

    def test_create_rejects_invalid_deadline_without_debris(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = create_module.main(
                [
                    "create.py",
                    "bad-deadline",
                    "--venue",
                    "NeurIPS",
                    "--year",
                    "2027",
                    "--mode",
                    "conference",
                    "--deadline",
                    "2027-02-30",
                    "--papers-root",
                    str(self.papers),
                ]
            )

        self.assertEqual(code, 2)
        self.assertFalse((self.papers / "bad-deadline").exists())

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
