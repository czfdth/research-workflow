import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from ccfa.queue import build_parser, load_queue, main, run_queue
from ccfa.run_log import check_runs


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


class FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = StringIO(stdout)
        self.stderr = StringIO(stderr)

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        raise AssertionError("kill should not be called")


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
        self.assertIs(items[0]["retry_on_timeout"], False)
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
            {
                "schema_version": 1,
                "queue": [
                    {
                        "name": "bad-timeout-retry",
                        "command": ["python"],
                        "retry_on_timeout": "yes",
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
                    retry_on_timeout=True,
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

    def test_timeout_without_explicit_flag_does_not_retry(self):
        self._write_queue(
            [
                self._item(
                    timeout_s=5,
                    max_attempts=2,
                )
            ]
        )
        runner = RecordingRunner(
            [
                subprocess.TimeoutExpired(["python"], 5),
                0,
            ],
            log_dir=self.log_dir,
        )

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result["runs"][0]["attempts"], 1)
        self.assertEqual(result["runs"][0]["status"], "timeout")
        self.assertIsNone(result["stopped"])

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
        process = FakeProcess(returncode=0)
        with mock.patch("ccfa.queue.subprocess.Popen", return_value=process) as popen:
            from ccfa.queue import _default_runner

            code = _default_runner(["cmd"], self.root, None)

        self.assertEqual(code, 0)
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.root))

    def test_default_runner_streams_output_before_child_exits(self):
        from ccfa.queue import _default_runner

        script = (
            "import time\n"
            "print('FIRST', flush=True)\n"
            "time.sleep(1.5)\n"
            "print('SECOND', flush=True)\n"
        )
        stderr = StringIO()
        result = {}

        def invoke():
            with redirect_stderr(stderr):
                result["code"] = _default_runner(
                    [sys.executable, "-c", script],
                    self.root,
                    None,
                )

        worker = threading.Thread(target=invoke)
        started = time.monotonic()
        worker.start()
        deadline = started + 1.35
        while time.monotonic() < deadline and "FIRST" not in stderr.getvalue():
            time.sleep(0.02)
        elapsed = time.monotonic() - started

        self.assertIn("FIRST", stderr.getvalue())
        self.assertLess(elapsed, 1.35)
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result["code"], 0)
        self.assertIn("SECOND", stderr.getvalue())

    def test_default_runner_forwards_partial_output_on_timeout(self):
        from ccfa.queue import _default_runner

        script = (
            "import sys, time\n"
            "print('PARTIAL_STDOUT', flush=True)\n"
            "print('PARTIAL_STDERR', file=sys.stderr, flush=True)\n"
            "time.sleep(5)\n"
        )
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(subprocess.TimeoutExpired):
            _default_runner([sys.executable, "-c", script], self.root, 1.0)

        self.assertIn("PARTIAL_STDOUT", stderr.getvalue())
        self.assertIn("PARTIAL_STDERR", stderr.getvalue())


class TestRunLogIntegration(QueueTests):
    def test_queue_records_resolved_cwd_in_run_log_field(self):
        sub = self.root / "sub"
        sub.mkdir()
        self._write_queue([self._item(cwd="sub")])

        self._run(RecordingRunner([0]))

        record = self._records()[0]
        self.assertEqual(record["cwd"], str(sub.resolve()))
        self.assertIsNone(record["metrics"])

    def test_completed_queue_run_still_reports_metrics_pending(self):
        self._write_queue([self._item()])

        self._run(RecordingRunner([0]))

        problems, _ = check_runs(self.log_dir)
        self.assertIn(
            "run-log-metrics-pending",
            [problem.code for problem in problems],
        )


class TestMain(QueueTests):
    def test_missing_cwd_still_records_failed_then_exits_two(self):
        self._write_queue([self._item(cwd="does-not-exist")])
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "queue",
                    "run",
                    "--queue",
                    str(self.queue_path),
                    "--log-dir",
                    str(self.log_dir),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("工具错误", stderr.getvalue())
        records = self._records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "failed")

    def test_real_child_stdout_is_forwarded_to_stderr_not_stdout(self):
        self._write_queue(
            [
                self._item(
                    command=[
                        sys.executable,
                        "-c",
                        "print('CHILD_STDOUT_MARKER')",
                    ]
                )
            ]
        )
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "queue",
                    "run",
                    "--queue",
                    str(self.queue_path),
                    "--log-dir",
                    str(self.log_dir),
                ]
            )

        self.assertEqual(code, 0)
        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["runs"][0]["status"], "complete")
        self.assertIn("CHILD_STDOUT_MARKER", stderr.getvalue())
        self.assertNotIn("CHILD_STDOUT_MARKER", stdout.getvalue())

    def test_help_and_docstring_state_missing_cwd_behavior(self):
        import ccfa.queue as queue_module

        self.assertIn("cwd 不存在", queue_module.__doc__)
        self.assertIn("cwd 不存在", build_parser().format_help())
        self.assertIn("stdout 只输出 JSON", queue_module.__doc__)
        self.assertIn("子进程 stdout/stderr", queue_module.__doc__)
        self.assertIn("转发到 stderr", queue_module.__doc__)

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
