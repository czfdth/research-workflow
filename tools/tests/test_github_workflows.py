import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.test_impact import select_tests


ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = ROOT / "papers" / "rag-attack-defense"
PYTHON = sys.executable


def _workflow_run_commands(path):
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    commands = []
    for job in payload.get("jobs", {}).values():
        for step in job.get("steps", []):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            current = None
            for raw in run.splitlines():
                line = raw.strip()
                continued = line.endswith("`")
                clean = line.rstrip("`").strip()
                if current is not None:
                    current = f"{current} {clean}"
                    if not continued:
                        commands.append(current)
                        current = None
                    continue
                if clean.startswith("python -m ccfa."):
                    if continued:
                        current = clean
                    else:
                        commands.append(clean)
    return commands


def _run_workflow_command(command, *, cwd):
    command = command.replace(
        "${{ inputs.profile || 'standard' }}",
        "standard",
    ).replace(
        "${{ inputs.profile }}",
        "standard",
    )
    tokens = shlex.split(command, posix=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "tools")
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [PYTHON, *tokens[1:]],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        shell=False,
        check=False,
    )


def _assert_no_argparse_failure(testcase, result, command):
    stderr = result.stderr.casefold()
    with testcase.subTest(command=command):
        testcase.assertNotIn("unrecognized arguments", stderr)
        testcase.assertNotIn("the following arguments are required", stderr)
        testcase.assertNotIn("invalid choice", stderr)


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
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        workflow_dir = PAPER_ROOT / ".github" / "workflows"
        expected = {"paper-check.yml", "repro-smoke.yml"}

        self.assertEqual({path.name for path in workflow_dir.glob("*.yml")}, expected)
        for path in workflow_dir.glob("*.yml"):
            with self.subTest(path=path.name):
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                self.assertIn("jobs", payload)

    def test_main_cross_repository_token_is_not_embedded(self):
        main_check = (ROOT / ".github" / "workflows" / "paper-check.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("secrets.PAPER_REPOSITORY_TOKEN", main_check)
        self.assertNotRegex(main_check, r"github_pat_|ghp_[A-Za-z0-9]")

    def test_paper_cross_repository_token_is_not_embedded(self):
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        paper_check = (
            PAPER_ROOT
            / ".github"
            / "workflows"
            / "paper-check.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("secrets.RESEARCH_WORKFLOW_TOKEN", paper_check)
        self.assertNotRegex(paper_check, r"github_pat_|ghp_[A-Za-z0-9]")

    def test_ci_recreates_the_product_virtualenv_layout(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("python -m venv tools/.venv", workflow)
        self.assertIn("python -m venv app/.venv", workflow)
        self.assertIn(
            "scripts/test-impact.ps1 run --suite tools",
            workflow,
        )
        self.assertIn(
            "scripts/test-impact.ps1 run --suite app",
            workflow,
        )
        self.assertEqual(workflow.count("PYTHONUTF8: '1'"), 2)

    def test_ci_covers_cross_review_downstream_e2e_modules(self):
        selection = select_tests(
            ["tools/ccfa/cross_review.py"],
            suite="tools",
        )
        expected = (
            "tools.tests.test_automation_e2e",
            "tools.tests.test_evidence_integrity_e2e",
        )
        for module in expected:
            with self.subTest(module=module):
                self.assertIn(module, selection.tests)

    def test_ci_uses_impact_selection_and_scheduled_full_regression(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("schedule:", workflow)
        self.assertIn("--base \"${{ github.event.pull_request.base.sha }}\"", workflow)
        self.assertIn("${{ github.event.before }}", workflow)
        self.assertIn("scripts/test-impact.ps1 run --suite tools --full", workflow)
        self.assertIn("scripts/test-impact.ps1 run --suite app --full", workflow)

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

    def test_main_paper_commands_are_parseable(self):
        workflow = ROOT / ".github" / "workflows" / "paper-check.yml"
        commands = _workflow_run_commands(workflow)
        self.assertTrue(commands)

        with tempfile.TemporaryDirectory() as temporary:
            paper = Path(temporary) / "paper"
            paper.mkdir()
            (paper / "ccfa.yaml").write_text(
                "version: '0.4.0'\n",
                encoding="utf-8",
            )
            for command in commands:
                rendered = command.replace("_paper", str(paper))
                result = _run_workflow_command(rendered, cwd=ROOT)
                _assert_no_argparse_failure(self, result, command)

    def test_paper_repository_commands_are_parseable(self):
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        workflow = PAPER_ROOT / ".github" / "workflows" / "paper-check.yml"
        commands = _workflow_run_commands(workflow)
        self.assertTrue(commands)

        with tempfile.TemporaryDirectory() as temporary:
            paper = Path(temporary)
            (paper / "ccfa.yaml").write_text(
                "version: '0.4.0'\n",
                encoding="utf-8",
            )
            for command in commands:
                result = _run_workflow_command(command, cwd=paper)
                _assert_no_argparse_failure(self, result, command)


if __name__ == "__main__":
    unittest.main()
