import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from ccfa.run_log import (
    check_runs,
    git_state,
    log_metrics,
    main,
    new_run_id,
    read_config,
    run_command,
)


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
        self.assertEqual(record["purpose"], "experiment")
        self.assertEqual(self._record(run_id)["run_id"], run_id)

    def test_records_a_build_purpose(self):
        run, _ = self.runner(exit_code=0)
        _, record = run_command(
            ["python", "render.py"],
            self.log_dir,
            self.root,
            purpose="build",
            runner=run,
        )
        self.assertEqual(record["purpose"], "build")

    def test_invalid_purpose_is_rejected(self):
        run, _ = self.runner(exit_code=0)
        with self.assertRaises(ValueError):
            run_command(
                ["python", "render.py"],
                self.log_dir,
                self.root,
                purpose="other",
                runner=run,
            )

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

    def test_explicit_cwd_is_recorded(self):
        run, _ = self.runner()
        _, record = run_command(
            ["python", "train.py"],
            self.log_dir,
            self.root,
            cwd="subdir",
            runner=run,
        )
        self.assertEqual(record["cwd"], "subdir")

    def test_date_config_is_normalized_and_run_completes(self):
        self.config.write_text("date: 2026-10-03\n", encoding="utf-8")
        run, _ = self.runner()
        run_id, record = run_command(
            ["python", "train.py"],
            self.log_dir,
            self.root,
            config=self.config,
            runner=run,
        )
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["config"]["content"]["date"], "2026-10-03")
        self.assertEqual(
            self._record(run_id)["config"]["content"]["date"],
            "2026-10-03",
        )
        self.assertNotEqual(self._record(run_id), {})
        self.assertEqual(len(list(self.log_dir.glob("*.json"))), 1)

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


class TestLogMetrics(BaseCase):
    def _make_run(self, exit_code=0):
        run, _ = self.runner(exit_code=exit_code)
        return run_command(["python", "train.py"], self.log_dir, self.root, runner=run)[0]

    def test_metrics_are_recorded_on_an_existing_run(self):
        run_id = self._make_run()
        record = log_metrics(self.log_dir, run_id, {"accuracy": 0.91})
        self.assertEqual(record["metrics"], {"accuracy": 0.91})
        self.assertEqual(record["status"], "completed")

    def test_status_is_not_touched_by_log_metrics(self):
        run_id = self._make_run(exit_code=3)
        record = log_metrics(self.log_dir, run_id, {"loss": 1.5})
        self.assertEqual(record["status"], "failed")

    def test_unknown_run_id_is_a_tool_error(self):
        with self.assertRaises(ValueError):
            log_metrics(self.log_dir, "20260101T000000-99", {"accuracy": 1.0})

    def test_metrics_must_be_an_object(self):
        run_id = self._make_run()
        with self.assertRaises(ValueError):
            log_metrics(self.log_dir, run_id, [1, 2, 3])

    def test_log_metrics_on_non_object_record_is_tool_error(self):
        path = self.log_dir / "20260101T000000-01.json"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            log_metrics(self.log_dir, "20260101T000000-01", {"accuracy": 1.0})


class TestCheckRuns(BaseCase):
    def _codes(self, problems):
        return sorted(p.code for p in problems)

    def _write_record(self, name, payload):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _base(self, **overrides):
        record = {
            "run_id": "20261003T142530-01",
            "status": "completed",
            "metrics": {"accuracy": 0.9},
            "git_commit": "abc1234",
            "git_dirty": False,
            "started_at": "2026-10-03T14:25:30Z",
        }
        record.update(overrides)
        return record

    def test_a_complete_record_is_clean(self):
        self._write_record("a", self._base())
        problems, advisories = check_runs(self.log_dir)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_completed_without_metrics_is_a_problem(self):
        self._write_record("a", self._base(metrics=None))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-metrics-pending"])

    def test_completed_with_empty_metrics_is_a_problem(self):
        self._write_record("a", self._base(metrics={}))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-empty-metrics"])

    def test_completed_with_non_object_metrics_is_malformed(self):
        self._write_record("a", self._base(metrics=[1, 2]))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-malformed"])

    def test_a_failed_run_is_not_reported(self):
        self._write_record("a", self._base(status="failed", metrics=None, exit_code=3))
        problems, advisories = check_runs(self.log_dir)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_missing_status_is_malformed(self):
        self._write_record("a", {})
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-malformed"])

    def test_unknown_status_is_malformed(self):
        self._write_record("a", self._base(status="metrics-pending", metrics=None))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-malformed"])

    def test_missing_commit_is_a_problem(self):
        self._write_record("a", self._base(git_commit=None))
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-missing-commit"])

    def test_dirty_tree_is_only_an_advisory(self):
        self._write_record("a", self._base(git_dirty=True))
        problems, advisories = check_runs(self.log_dir)
        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["run-log-dirty-tree"])

    def test_stale_running_record_is_a_problem(self):
        self._write_record("a", self._base(status="running", metrics=None))
        problems, _ = check_runs(
            self.log_dir, now=datetime(2026, 10, 5, 14, 25, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(self._codes(problems), ["run-log-stale-running"])

    def test_a_recent_running_record_is_not_reported(self):
        self._write_record("a", self._base(status="running", metrics=None))
        problems, _ = check_runs(
            self.log_dir, now=datetime(2026, 10, 3, 15, 0, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(problems, [])

    def test_unreadable_json_does_not_crash_the_whole_check(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "broken.json").write_text("{not json", encoding="utf-8")
        self._write_record("a", self._base())
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-malformed"])

    def test_non_utf8_record_does_not_crash_the_whole_check(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "broken.json").write_bytes(b"\xff\xfe\x00garbage")
        self._write_record("a", self._base())
        problems, _ = check_runs(self.log_dir)
        self.assertEqual(self._codes(problems), ["run-log-malformed"])

    def test_check_does_not_write(self):
        path = self._write_record("a", self._base())
        before = path.read_bytes()
        check_runs(self.log_dir)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
