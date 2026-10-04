import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.readiness import build_report, main, render_markdown


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paper_root = Path(self.tmp.name)
        self._write_state()

    def _write_state(self, extra=""):
        self.paper_root.joinpath("ccfa.yaml").write_text(
            "version: '0.4.0'\n"
            "project:\n"
            "  title: Demo\n"
            "  short_name: demo\n"
            "  root: .\n"
            "target_venue:\n"
            "  name: NeurIPS\n"
            "  year: 2026\n"
            "  mode: conference\n"
            "  deadline: null\n"
            "stage:\n"
            "  current: idea\n"
            "  gate: scope_defined\n"
            "  updated_at: '2026-10-04'\n"
            "  history: []\n"
            "artifacts:\n"
            "  manuscript: manuscript/main.tex\n"
            "  bibliography: manuscript/references.bib\n"
            "  figures: figures/\n"
            "  tables: tables/\n"
            "  experiments: experiments/\n"
            "  reviews: reviews/\n"
            "  submission: submission/\n"
            "claims: []\n"
            "experiments: []\n"
            "reviews: []\n"
            "revision_ledger:\n"
            "  path: reviews/revision-ledger.md\n"
            "  status: not_started\n"
            "submission_checks:\n"
            "  path: submission/checks.md\n"
            "  status: not_started\n"
            f"{extra}",
            encoding="utf-8",
        )

    def _touch_ledgers(self, names):
        paths = {
            "proof": "data/proof-audit.yaml",
            "citation-support": "data/citation-support.yaml",
            "figure-support": "data/figure-support.yaml",
            "governance": "data/governance.yaml",
            "novelty": "data/novelty-audit.yaml",
            "statistics": "data/statistics-plan.yaml",
            "repro-environment": "data/repro-environment.yaml",
            "human-coding": "data/human-coding-report.json",
        }
        for name in names:
            path = self.paper_root / paths[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")

    def test_standard_profile_reports_missing_required_ledgers_and_no_science_claim(self):
        report = build_report(self.paper_root)

        self.assertFalse(report["ready"])
        self.assertEqual(report["profile"], "standard")
        self.assertEqual(report["dimensions"]["schema-valid"], "pass")
        self.assertEqual(report["dimensions"]["evidence-present"], "problem")
        self.assertEqual(
            report["dimensions"]["scientifically-accepted"],
            "not-claimed",
        )
        self.assertIn("citation-support", report["evidence"]["missing_required"])

    def test_high_assurance_requires_all_ledgers(self):
        self._touch_ledgers(["novelty"])

        report = build_report(self.paper_root, profile="high-assurance")

        self.assertIn("proof", report["evidence"]["missing_required"])
        self.assertEqual(
            report["dimensions"]["independently-reviewed"],
            "missing-human-evidence",
        )

    def test_high_assurance_rejects_pending_human_ledgers(self):
        self._touch_ledgers(
            [
                "proof",
                "citation-support",
                "figure-support",
                "governance",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        report_path = self.paper_root / "data" / "human-coding-report.json"
        report_path.write_text(
            '{"version": 1, "status": "pending-human-dual-coding"}\n',
            encoding="utf-8",
        )
        (self.paper_root / "data" / "proof-audit.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nreviews: []\n",
            encoding="utf-8",
        )
        (self.paper_root / "data" / "citation-support.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nsupports: []\n",
            encoding="utf-8",
        )
        (self.paper_root / "data" / "figure-support.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nfigures: []\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="high-assurance")

        self.assertFalse(report["ready"])
        self.assertEqual(
            report["dimensions"]["independently-reviewed"],
            "pending-human-review",
        )
        self.assertIn("required human review is incomplete", report["blocking"])

    def test_minimal_can_be_ready_without_scientific_acceptance(self):
        self._touch_ledgers(["novelty"])

        report = build_report(self.paper_root, profile="minimal")

        self.assertTrue(report["ready"])
        self.assertEqual(
            report["dimensions"]["scientifically-accepted"],
            "not-claimed",
        )

    def test_profile_can_come_from_ccfa_yaml(self):
        self._write_state("workflow:\n  profile: high-assurance\n")

        report = build_report(self.paper_root)

        self.assertEqual(report["profile"], "high-assurance")

    def test_git_remote_and_workflow_status_are_reported(self):
        subprocess.run(["git", "init"], cwd=self.paper_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "add", "ccfa.yaml"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.paper_root, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", "https://example.test/repo.git"], cwd=self.paper_root, check=True)
        (self.paper_root / ".github" / "workflows").mkdir(parents=True)

        report = build_report(self.paper_root, profile="minimal")

        self.assertTrue(report["git"]["present"])
        self.assertFalse(report["git"]["dirty"])
        self.assertEqual(report["git"]["remotes"], ["origin"])
        self.assertTrue(report["git"]["workflows_present"])

    def test_standard_requires_git_remote_and_workflows(self):
        self._touch_ledgers(
            [
                "citation-support",
                "figure-support",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        subprocess.run(["git", "init"], cwd=self.paper_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.paper_root, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.paper_root, check=True, capture_output=True)

        report = build_report(self.paper_root, profile="standard")

        self.assertFalse(report["ready"])
        self.assertEqual(report["dimensions"]["collaboration-ready"], "problem")
        self.assertIn("paper git remote is missing", report["blocking"])
        self.assertIn("GitHub Actions workflows are missing", report["blocking"])

    def test_render_markdown_names_scientific_boundary(self):
        report = build_report(self.paper_root, profile="minimal")
        markdown = render_markdown(report)

        self.assertIn("Scientific Boundary", markdown)
        self.assertIn("does not certify", markdown)

    def test_main_can_write_markdown_report(self):
        with redirect_stdout(StringIO()):
            code = main([
                "readiness",
                "--paper-root",
                str(self.paper_root),
                "--profile",
                "minimal",
                "--out",
                "reviews/readiness.md",
            ])

        self.assertEqual(code, 1)
        self.assertTrue((self.paper_root / "reviews" / "readiness.md").is_file())


if __name__ == "__main__":
    unittest.main()
