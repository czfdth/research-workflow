import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from ccfa.queue import load_queue, main, run_queue


class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


class RecordingRunner:
    def __init__(self, behaviors, *, clock=None, log_dir=None):
        self.behaviors = list(behaviors)
        self.calls = []
        self.clock = clock
        self.log_dir = Path(log_dir) if log_dir else None
        self.running_seen = []

    def __call__(self, argv, cwd, timeout_s):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": Path(cwd),
                "timeout_s": timeout_s,
            }
        )
        if self.log_dir is not None:
            records = sorted(self.log_dir.glob("*.json"))
            if records:
                self.running_seen.append(
                    json.loads(records[-1].read_text(encoding="utf-8")).get("status")
                )
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        if callable(behavior):
            return behavior()
        return int(behavior)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.queue_path = self.root / "queue.json"
        self.log_dir = self.root / "log"

    def _write_queue(self, items, *, version=1, key="queue"):
        self.queue_path.write_text(
            json.dumps({"schema_version": version, key: items}),
            encoding="utf-8",
        )

    def _item(self, name="run-1", command=None, **overrides):
        item = {
            "name": name,
            "command": command or ["python", "-c", "print('ok')"],
        }
        item.update(overrides)
        return item

    def _records(self):
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.log_dir.glob("*.json"))
        ]

    def _run(self, runner, *, budget_s=None, clock=None):
        return run_queue(
            self.queue_path,
            log_dir=self.log_dir,
            runner=runner,
            budget_s=budget_s,
            clock=clock,
        )


class TestLoadQueue(QueueTests):
    def test_load_queue_returns_items_with_defaults(self):
        self._write_queue(
            [
                {
                    "name": "one",
                    "command": ["python", "one.py"],
                }
            ]
        )

        items = load_queue(self.queue_path)

        self.assertEqual(items[0]["name"], "one")
        self.assertEqual(items[0]["command"], ["python", "one.py"])
        self.assertEqual(items[0]["retry_exit_codes"], [])
        self.assertEqual(items[0]["max_attempts"], 1)

    def test_load_queue_rejects_invalid_shape_and_version(self):
        cases = (
            {"schema_version": 2, "queue": []},
            {"schema_version": 1, "queue": {}},
            {"schema_version": 1, "queue": [{"name": "", "command": []}]},
            {
                "schema_version": 1,
                "queue": [
                    {
                        "name": "bad",
                        "command": ["python"],
                        "max_attempts": 0,
                    }
                ],
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.queue_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_queue(self.queue_path)


class TestRunQueue(QueueTests):
    def test_successful_command_exits_complete(self):
        self._write_queue([self._item()])
        runner = RecordingRunner([0], log_dir=self.log_dir)

        result = self._run(runner)

        self.assertEqual(
            result,
            {
                "runs": [{"name": "run-1", "attempts": 1, "status": "complete"}],
                "stopped": None,
            },
        )
        self.assertEqual(self._records()[0]["status"], "completed")

    def test_failure_outside_retry_codes_does_not_retry(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=3)])
        runner = RecordingRunner([3, 3, 3])

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result["runs"][0]["status"], "failed")
        self.assertIsNone(result["stopped"])

    def test_retry_code_retries_until_success(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=3)])
        runner = RecordingRunner([2, 0], log_dir=self.log_dir)

        result = self._run(runner)

        self.assertEqual(result["runs"][0]["attempts"], 2)
        self.assertEqual(result["runs"][0]["status"], "complete")
        self.assertEqual([record["status"] for record in self._records()], ["failed", "completed"])

    def test_retry_exhaustion_stops_with_retries(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=2)])
        runner = RecordingRunner([2, 2])

        result = self._run(runner)

        self.assertEqual(result["runs"][0]["attempts"], 2)
        self.assertEqual(result["runs"][0]["status"], "failed")
        self.assertEqual(result["stopped"], "retries")

    def test_timeout_counts_as_failure_and_retries(self):
        self._write_queue(
            [
                self._item(
                    timeout_s=5,
                    retry_exit_codes=[],
                    max_attempts=2,
                )
            ]
        )
        runner = RecordingRunner(
            [
                subprocess.TimeoutExpired(["python"], 5),
                subprocess.TimeoutExpired(["python"], 5),
            ],
            log_dir=self.log_dir,
        )

        result = self._run(runner)

        self.assertEqual(result["runs"][0]["attempts"], 2)
        self.assertEqual(result["runs"][0]["status"], "timeout")
        self.assertEqual(result["stopped"], "retries")
        self.assertTrue(self._records()[0]["metrics"]["timeout"])

    def test_timeout_with_default_attempt_limit_does_not_retry(self):
        self._write_queue([self._item(timeout_s=5)])
        runner = RecordingRunner(
            [subprocess.TimeoutExpired(["python"], 5)],
            log_dir=self.log_dir,
        )

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result["runs"][0]["status"], "timeout")
        self.assertIsNone(result["stopped"])

    def test_retry_exhaustion_stops_before_later_items(self):
        self._write_queue(
            [
                self._item("first", retry_exit_codes=[2], max_attempts=2),
                self._item("second"),
            ]
        )
        runner = RecordingRunner([2, 2, 0])

        result = self._run(runner)

        self.assertEqual([run["name"] for run in result["runs"]], ["first"])
        self.assertEqual(result["stopped"], "retries")
        self.assertEqual(len(runner.calls), 2)

    def test_budget_stops_before_next_item(self):
        self._write_queue([self._item("first"), self._item("second")])
        clock = FakeClock()

        def first():
            clock.advance(20)
            return 0

        runner = RecordingRunner([first, 0])

        result = self._run(runner, budget_s=10, clock=clock)

        self.assertEqual([run["name"] for run in result["runs"]], ["first", "second"])
        self.assertEqual(
            [run["status"] for run in result["runs"]],
            ["complete", "skipped-budget"],
        )
        self.assertEqual(result["runs"][1]["attempts"], 0)
        self.assertEqual(result["stopped"], "budget")

    def test_every_attempt_is_running_before_terminal_record(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=2)])
        runner = RecordingRunner([2, 0], log_dir=self.log_dir)

        self._run(runner)

        self.assertEqual(runner.running_seen, ["running", "running"])
        self.assertEqual(len(list(self.log_dir.glob("*.json"))), 2)

    def test_default_max_attempts_is_one_even_with_retry_code(self):
        self._write_queue([self._item(retry_exit_codes=[2])])
        runner = RecordingRunner([2])

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertIsNone(result["stopped"])

    def test_empty_queue_is_clean(self):
        self._write_queue([])
        result = self._run(RecordingRunner([]))
        self.assertEqual(result, {"runs": [], "stopped": None})

    def test_negative_budget_is_rejected(self):
        self._write_queue([self._item()])
        with self.assertRaises(ValueError):
            self._run(RecordingRunner([]), budget_s=-1)


class TestDefaultRunner(QueueTests):
    def test_default_runner_uses_shell_false(self):
        completed = subprocess.CompletedProcess(["cmd"], 0)
        with mock.patch("ccfa.queue.subprocess.run", return_value=completed) as run:
            from ccfa.queue import _default_runner

            code = _default_runner(["cmd"], self.root, None)

        self.assertEqual(code, 0)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["cwd"], str(self.root))


class TestMain(QueueTests):
    def test_main_success_zero_failure_one_and_invalid_two(self):
        self._write_queue([self._item()])
        with mock.patch(
            "ccfa.queue.run_queue",
            return_value={"runs": [{"name": "run-1", "attempts": 1, "status": "complete"}], "stopped": None},
        ):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "queue",
                            "run",
                            "--queue",
                            str(self.queue_path),
                            "--log-dir",
                            str(self.log_dir),
                        ]
                    ),
                    0,
                )

        with mock.patch(
            "ccfa.queue.run_queue",
            return_value={"runs": [{"name": "run-1", "attempts": 1, "status": "failed"}], "stopped": None},
        ):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "queue",
                            "run",
                            "--queue",
                            str(self.queue_path),
                            "--log-dir",
                            str(self.log_dir),
                        ]
                    ),
                    1,
                )

        self.queue_path.write_text("{bad json", encoding="utf-8")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(
                main(
                    [
                        "queue",
                        "run",
                        "--queue",
                        str(self.queue_path),
                        "--log-dir",
                        str(self.log_dir),
                    ]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
