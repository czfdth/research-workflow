import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.run_log import git_state, main, new_run_id, read_config, run_command


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.log_dir = self.root / "experiments" / "log"
        self.config = self.root / "configs" / "a.yaml"
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text("epochs: 5\n", encoding="utf-8")

    def runner(self, exit_code=0, output="ok\n"):
        calls = []

        def run(argv, cwd):
            calls.append(list(argv))
            return exit_code, output

        return run, calls


class TestRunId(BaseCase):
    def test_first_id_uses_stamp_and_counter(self):
        run_id, path = new_run_id(self.log_dir, stamp="20261003T142530")
        self.assertEqual(run_id, "20261003T142530-01")
        self.assertTrue(path.is_file())  # the claim file exists immediately
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})

    def test_second_id_does_not_clobber_the_first(self):
        first_id, first_path = new_run_id(self.log_dir, stamp="20261003T142530")
        second_id, second_path = new_run_id(self.log_dir, stamp="20261003T142530")
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(second_id, "20261003T142530-02")
        self.assertEqual(json.loads(first_path.read_text(encoding="utf-8")), {})


class TestGitState(BaseCase):
    def test_non_repo_returns_none_and_false(self):
        commit, dirty = git_state(self.root)
        self.assertIsNone(commit)
        self.assertFalse(dirty)


class TestReadConfig(BaseCase):
    def test_records_path_hash_and_parsed_content(self):
        entry = read_config(self.config, paper_root=self.root)
        self.assertEqual(entry["path"], "configs/a.yaml")
        self.assertEqual(entry["content"], {"epochs": 5})
        self.assertTrue(entry["sha256"].startswith("sha256:"))

    def test_relative_config_path_resolves_against_paper_root(self):
        entry = read_config(Path("configs/a.yaml"), paper_root=self.root)
        self.assertEqual(entry["path"], "configs/a.yaml")
        self.assertEqual(entry["content"], {"epochs": 5})

    def test_missing_config_is_a_tool_error(self):
        with self.assertRaises(ValueError):
            read_config(self.root / "nope.yaml", paper_root=self.root)


class TestRunCommand(BaseCase):
    def _record(self, run_id):
        return json.loads((self.log_dir / f"{run_id}.json").read_text(encoding="utf-8"))

    def test_records_a_completed_run(self):
        run, calls = self.runner(exit_code=0)
        run_id, record = run_command(
            ["python", "train.py"],
            self.log_dir,
            self.root,
            config=self.config,
            seed="42",
            runner=run,
        )
        self.assertEqual(calls, [["python", "train.py"]])
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["seed"], "42")
        self.assertIsNone(record["metrics"])
        self.assertIsNotNone(record["finished_at"])
        self.assertEqual(self._record(run_id)["run_id"], run_id)

    def test_records_a_failed_run_without_raising(self):
        run, _ = self.runner(exit_code=3)
        _, record = run_command(["false"], self.log_dir, self.root, runner=run)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["exit_code"], 3)

    def test_running_record_exists_before_the_command_finishes(self):
        seen = {}

        def run(argv, cwd):
            # At the moment the command starts, the record must already say running.
            paths = list(self.log_dir.glob("*.json"))
            seen["count"] = len(paths)
            seen["status"] = json.loads(paths[0].read_text(encoding="utf-8"))["status"]
            return 0, ""

        run_command(["python", "train.py"], self.log_dir, self.root, runner=run)
        self.assertEqual(seen["count"], 1)
        self.assertEqual(seen["status"], "running")

    def test_command_is_recorded_relative_to_paper_root(self):
        run, _ = self.runner()
        _, record = run_command(["python", "train.py"], self.log_dir, self.root, runner=run)
        self.assertEqual(record["cwd"], ".")

    def test_unwritable_log_dir_is_a_tool_error(self):
        # A file used as a directory parent fails deterministically on every OS,
        # unlike a root-level path whose permissions vary by machine.
        blocker = self.root / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        run, _ = self.runner()
        with self.assertRaises(ValueError):
            run_command(["python", "train.py"], blocker / "log", self.root, runner=run)


class TestMain(BaseCase):
    def test_defaults_to_zero_and_propagates_only_when_asked(self):
        command = [sys.executable, "-c", "raise SystemExit(3)"]
        base = [
            "run-log",
            "--log-dir",
            str(self.log_dir),
            "--paper-root",
            str(self.root),
            "run",
        ]
        with redirect_stdout(StringIO()):
            self.assertEqual(main(base + ["--", *command]), 0)
        with redirect_stdout(StringIO()):
            self.assertEqual(main(base + ["--propagate-exit", "--", *command]), 3)
        records = sorted(self.log_dir.glob("*.json"))
        self.assertEqual(len(records), 2)
        self.assertTrue(
            all(
                json.loads(path.read_text(encoding="utf-8"))["status"] == "failed"
                for path in records
            )
        )


if __name__ == "__main__":
    unittest.main()
