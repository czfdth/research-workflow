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

    def test_ci_recreates_the_product_virtualenv_layout(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("python -m venv tools/.venv", workflow)
        self.assertIn("python -m venv app/.venv", workflow)
        self.assertIn(
            "tools/.venv/Scripts/python.exe -m unittest",
            workflow,
        )
        self.assertIn(
            "app/.venv/Scripts/python.exe -m unittest",
            workflow,
        )
        self.assertEqual(workflow.count("PYTHONUTF8: '1'"), 2)

    def test_actions_use_current_node24_compatible_majors(self):
        workflow_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / ".github" / "workflows"
            ).glob("*.yml")
        )

        self.assertNotIn("actions/checkout@v4", workflow_text)
        self.assertNotIn("actions/setup-python@v5", workflow_text)
        self.assertNotIn("actions/upload-artifact@v4", workflow_text)


if __name__ == "__main__":
    unittest.main()
