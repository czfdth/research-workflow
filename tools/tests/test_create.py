import tempfile
import unittest
from pathlib import Path

from ccfa.validate import validate_yaml
from newpaper.create import create_project
from newpaper.venues import VenueNotFound


class TestCreateProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.papers = self.tmp / "papers"
        self.papers.mkdir()

    def _create(self, slug="demo-paper", venue="NeurIPS", mode="conference"):
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue=venue,
            year="2027",
            mode=mode,
            title="Demo Paper",
        )

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
