import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_ROOT.parent
RUN_LOG = TOOLS_ROOT / "ccfa" / "run_log.py"


class TestRunLogEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.log_dir = self.root / "experiments" / "log"

    def _run(self, *args):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(RUN_LOG),
                "--log-dir",
                str(self.log_dir),
                "--paper-root",
                str(REPO_ROOT),
                *args,
            ],
            capture_output=True,
            encoding="utf-8",
            env=env,
        )

    def _run_successfully(self):
        result = self._run("run", "--", sys.executable, "-c", "print(1)")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip().splitlines()[-1]

    def test_completed_run_without_metrics_is_reported(self):
        self._run_successfully()

        result = self._run("check")

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [problem["code"] for problem in payload["problems"]],
            ["run-log-metrics-pending"],
        )

    def test_check_passes_after_metrics_are_logged(self):
        run_id = self._run_successfully()
        logged = self._run(
            "log-metrics",
            run_id,
            "--metrics",
            json.dumps({"accuracy": 0.9}),
        )
        self.assertEqual(logged.returncode, 0, logged.stderr)

        result = self._run("check")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_placeholder_record_is_malformed(self):
        self.log_dir.mkdir(parents=True)
        (self.log_dir / "20260101T000000-01.json").write_text(
            "{}", encoding="utf-8"
        )

        result = self._run("check")

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [problem["code"] for problem in payload["problems"]],
            ["run-log-malformed"],
        )

    def test_log_metrics_unknown_run_is_a_tool_error(self):
        result = self._run(
            "log-metrics",
            "20260101T000000-99",
            "--metrics",
            json.dumps({"accuracy": 0.9}),
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
