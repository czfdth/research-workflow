import unittest
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]


class TestScaffoldContract(unittest.TestCase):
    def test_required_directories_exist(self):
        required = [
            "checklists",
            "library",
            "library/papers",
            "tools/ccfa",
            "tools/newpaper",
            "tools/build",
            "tools/tests",
        ]
        for rel in required:
            with self.subTest(rel=rel):
                self.assertTrue((TEMPLATE_ROOT / rel).is_dir(), f"缺少目录: {rel}")

    def test_gitignore_excludes_build_products(self):
        gitignore = (TEMPLATE_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ["tools/.venv/", "*.aux", "*.log", "*.pdf"]:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)

    def test_papers_dir_kept_but_pdfs_ignored(self):
        gitignore = (TEMPLATE_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!library/papers/.gitkeep", gitignore)
        self.assertTrue((TEMPLATE_ROOT / "library" / "papers" / ".gitkeep").is_file())
