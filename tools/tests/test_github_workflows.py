import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class GitHubWorkflowTests(unittest.TestCase):
    def test_main_workflows_are_valid_yaml(self):
        workflow_dir = ROOT / ".github" / "workflows"
        expected = {"tests.yml", "paper-check.yml", "repro-smoke.yml", "release.yml"}

        self.assertEqual({path.name for path in workflow_dir.glob("*.yml")}, expected)
        for path in workflow_dir.glob("*.yml"):
            with self.subTest(path=path.name):
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                self.assertIn("jobs", payload)

    def test_paper_workflows_are_valid_yaml(self):
        workflow_dir = ROOT / "papers" / "rag-attack-defense" / ".github" / "workflows"
        expected = {"paper-check.yml", "repro-smoke.yml"}

        self.assertEqual({path.name for path in workflow_dir.glob("*.yml")}, expected)
        for path in workflow_dir.glob("*.yml"):
            with self.subTest(path=path.name):
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                self.assertIn("jobs", payload)

    def test_cross_repository_tokens_are_not_embedded(self):
        main_check = (ROOT / ".github" / "workflows" / "paper-check.yml").read_text(
            encoding="utf-8"
        )
        paper_check = (
            ROOT
            / "papers"
            / "rag-attack-defense"
            / ".github"
            / "workflows"
            / "paper-check.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("secrets.PAPER_REPOSITORY_TOKEN", main_check)
        self.assertIn("secrets.RESEARCH_WORKFLOW_TOKEN", paper_check)
        self.assertNotRegex(main_check + paper_check, r"github_pat_|ghp_[A-Za-z0-9]")


if __name__ == "__main__":
    unittest.main()
