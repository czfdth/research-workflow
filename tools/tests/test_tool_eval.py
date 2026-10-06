"""The gate self-evaluation harness.

Two things are being pinned here: the shipped case set must actually
discriminate (every injected defect caught, every clean fixture accepted), and
the harness must grade honestly — an error is neither a detection nor a clean
pass, and a miss must move the rate.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

from ccfa import tool_eval


def _case(case_id: str, expectation: str, *, rejected: bool = False, boom: bool = False):
    def build(_root):
        if boom:
            raise RuntimeError("fixture exploded")

    return tool_eval.Case(
        case_id,
        "test-gate",
        expectation,
        "synthetic case",
        build,
        lambda _root: rejected,
    )


class ShippedCaseSetTests(unittest.TestCase):
    def test_shipped_cases_all_discriminate(self):
        summary = tool_eval.summarise(tool_eval.run_cases())
        totals = summary["totals"]

        self.assertEqual(totals["errors"], 0, summary["results"])
        self.assertEqual(totals["missed"], 0, summary["results"])
        self.assertEqual(totals["false_alarms"], 0, summary["results"])
        self.assertEqual(summary["detection_rate"], 1.0)
        self.assertEqual(summary["false_alarm_rate"], 0.0)
        self.assertGreaterEqual(totals["caught"], 4)
        self.assertGreaterEqual(totals["clean"], 2)

    def test_shipped_cases_cover_several_gates(self):
        summary = tool_eval.summarise(tool_eval.run_cases())

        self.assertGreaterEqual(len(summary["gates"]), 3)
        for name, item in summary["gates"].items():
            with self.subTest(gate=name):
                # Every registered gate needs both a defect and a clean probe,
                # otherwise the rate says nothing about false alarms.
                self.assertGreaterEqual(item["caught"] + item["missed"], 1)


class GradingTests(unittest.TestCase):
    def test_error_is_graded_and_kept_out_of_the_denominator(self):
        cases = (
            _case("boom", tool_eval.REJECT, boom=True),
            _case("good", tool_eval.REJECT, rejected=True),
        )

        summary = tool_eval.summarise(tool_eval.run_cases(cases))

        self.assertEqual(summary["totals"]["errors"], 1)
        self.assertEqual(summary["detection_rate"], 1.0)
        outcomes = {r["id"]: r["outcome"] for r in summary["results"]}
        self.assertEqual(outcomes["boom"], tool_eval.ERROR)
        self.assertEqual(outcomes["good"], tool_eval.CAUGHT)

    def test_a_miss_moves_the_detection_rate(self):
        cases = (
            _case("caught", tool_eval.REJECT, rejected=True),
            _case("missed", tool_eval.REJECT, rejected=False),
        )

        summary = tool_eval.summarise(tool_eval.run_cases(cases))

        self.assertEqual(summary["totals"]["missed"], 1)
        self.assertEqual(summary["detection_rate"], 0.5)

    def test_a_clean_fixture_flagged_is_a_false_alarm(self):
        cases = (_case("noisy", tool_eval.ACCEPT, rejected=True),)

        summary = tool_eval.summarise(tool_eval.run_cases(cases))

        self.assertEqual(summary["totals"]["false_alarms"], 1)
        self.assertEqual(summary["false_alarm_rate"], 1.0)

    def test_rates_are_none_without_graded_probes(self):
        cases = (_case("boom", tool_eval.REJECT, boom=True),)

        summary = tool_eval.summarise(tool_eval.run_cases(cases))

        self.assertIsNone(summary["detection_rate"])
        self.assertIsNone(summary["false_alarm_rate"])

    def test_markdown_report_names_the_gates_and_the_rates(self):
        summary = tool_eval.summarise(tool_eval.run_cases())

        text = tool_eval.render_markdown(summary)

        self.assertIn("detection_rate", text)
        self.assertIn("stats-plan", text)
        self.assertIn("只测量，不改写", text)


class CliTests(unittest.TestCase):
    def test_completed_run_exits_zero_whatever_the_rates(self):
        # Measurement, not a gate: the exit code only reports that the harness
        # ran, exactly as the aligned ARIS trigger_eval does.
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = tool_eval.main(
                ["tool-eval", "--case", "statistics-null-baseline-recorded"]
            )

        self.assertEqual(code, 0)

    def test_unknown_case_is_a_setup_error(self):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = tool_eval.main(["tool-eval", "--case", "nope"])

        self.assertEqual(code, 2)


def _spec(root: Path, tasks: list[dict]) -> Path:
    path = root / "benchmark.yaml"
    path.write_text(
        yaml.safe_dump(
            {"version": 1, "name": "demo-bench", "tasks": tasks},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _metric_writer(score: float) -> list[str]:
    return [
        sys.executable,
        "-c",
        "import json,pathlib;"
        f"pathlib.Path('metrics.json').write_text(json.dumps({{'score': {score}}}))",
    ]


class BenchmarkSpecTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_a_missing_spec_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "找不到 benchmark spec"):
            tool_eval.load_benchmark(self.root / "nope.yaml")

    def test_an_empty_task_list_is_an_error(self):
        path = _spec(self.root, [])

        with self.assertRaisesRegex(ValueError, "非空 tasks"):
            tool_eval.load_benchmark(path)

    def test_a_task_without_a_command_is_an_error(self):
        path = _spec(self.root, [{"id": "a"}])

        with self.assertRaisesRegex(ValueError, "缺少 command"):
            tool_eval.load_benchmark(path)

    def test_duplicate_task_ids_are_an_error(self):
        path = _spec(
            self.root,
            [
                {"id": "a", "command": ["echo", "1"]},
                {"id": "a", "command": ["echo", "2"]},
            ],
        )

        with self.assertRaisesRegex(ValueError, "task id 重复"):
            tool_eval.load_benchmark(path)

    def test_a_non_list_command_is_an_error(self):
        path = _spec(self.root, [{"id": "a", "command": "echo hi"}])

        with self.assertRaisesRegex(ValueError, "非空字符串数组"):
            tool_eval.load_benchmark(path)


class BenchmarkRunTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_a_metric_above_threshold_passes(self):
        path = _spec(
            self.root,
            [
                {
                    "id": "good",
                    "source": "external/task-good",
                    "command": _metric_writer(0.9),
                    "metric": {"path": "metrics.json", "key": "score"},
                    "threshold": 0.5,
                }
            ],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        self.assertEqual(summary["totals"]["pass"], 1)
        self.assertEqual(summary["pass_rate"], 1.0)
        self.assertEqual(summary["results"][0]["outcome"], tool_eval.BENCH_PASS)

    def test_a_metric_below_threshold_fails(self):
        path = _spec(
            self.root,
            [
                {
                    "id": "weak",
                    "command": _metric_writer(0.1),
                    "metric": {"path": "metrics.json", "key": "score"},
                    "threshold": 0.5,
                }
            ],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        self.assertEqual(summary["totals"]["fail"], 1)
        self.assertEqual(summary["pass_rate"], 0.0)

    def test_a_missing_metric_fails_when_a_threshold_is_declared(self):
        path = _spec(
            self.root,
            [
                {
                    "id": "silent",
                    "command": [sys.executable, "-c", "pass"],
                    "metric": {"path": "metrics.json", "key": "score"},
                    "threshold": 0.5,
                }
            ],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        self.assertEqual(summary["totals"]["fail"], 1)
        self.assertIn("没有读到度量值", summary["results"][0]["detail"])

    def test_a_nonzero_exit_fails(self):
        path = _spec(
            self.root,
            [{"id": "boom", "command": [sys.executable, "-c", "raise SystemExit(3)"]}],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        self.assertEqual(summary["totals"]["fail"], 1)
        self.assertIn("退出码 3", summary["results"][0]["detail"])

    def test_a_missing_workdir_is_unavailable_and_excluded(self):
        path = _spec(
            self.root,
            [
                {"id": "gone", "command": ["echo", "hi"], "workdir": "nope"},
                {
                    "id": "good",
                    "command": _metric_writer(0.9),
                    "metric": {"path": "metrics.json", "key": "score"},
                    "threshold": 0.5,
                },
            ],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        self.assertEqual(summary["totals"]["unavailable"], 1)
        # The unavailable task must not move the denominator.
        self.assertEqual(summary["pass_rate"], 1.0)

    def test_a_missing_executable_is_unavailable(self):
        path = _spec(
            self.root,
            [{"id": "no-binary", "command": ["definitely-not-a-real-binary-xyz"]}],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        self.assertEqual(summary["totals"]["unavailable"], 1)
        self.assertIsNone(summary["pass_rate"])

    def test_dry_run_plans_without_executing(self):
        path = _spec(
            self.root,
            [{"id": "good", "command": _metric_writer(0.9)}],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path, dry_run=True)
        )

        self.assertEqual(summary["totals"]["planned"], 1)
        self.assertFalse((self.root / "metrics.json").exists())

    def test_a_metric_path_outside_the_workdir_is_refused(self):
        path = _spec(
            self.root,
            [
                {
                    "id": "escape",
                    "command": [sys.executable, "-c", "pass"],
                    "metric": {"path": "../metrics.json", "key": "score"},
                    "threshold": 0.5,
                }
            ],
        )
        spec = tool_eval.load_benchmark(path)

        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        self.assertEqual(summary["totals"]["fail"], 1)

    def test_markdown_report_names_the_benchmark_and_rate(self):
        path = _spec(
            self.root,
            [
                {
                    "id": "good",
                    "source": "external/task-good",
                    "command": _metric_writer(0.9),
                    "metric": {"path": "metrics.json", "key": "score"},
                    "threshold": 0.5,
                }
            ],
        )
        spec = tool_eval.load_benchmark(path)
        summary = tool_eval.summarise_benchmark(
            tool_eval.run_benchmark(spec, spec_path=path)
        )

        text = tool_eval.render_benchmark_markdown(summary)

        self.assertIn("demo-bench", text)
        self.assertIn("external/task-good", text)
        self.assertIn("只测量", text)


class BenchmarkCliTests(unittest.TestCase):
    def test_a_completed_benchmark_exits_zero_even_with_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _spec(
                root,
                [{"id": "boom", "command": [sys.executable, "-c", "raise SystemExit(1)"]}],
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = tool_eval.main(
                    ["tool-eval", "--benchmark", str(path)]
                )

        self.assertEqual(code, 0)

    def test_a_broken_spec_is_a_setup_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "benchmark.yaml"
            path.write_text("tasks: []\n", encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = tool_eval.main(
                    ["tool-eval", "--benchmark", str(path)]
                )

        self.assertEqual(code, 2)

    def test_json_report_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _spec(
                root,
                [
                    {
                        "id": "good",
                        "command": _metric_writer(0.9),
                        "metric": {"path": "metrics.json", "key": "score"},
                        "threshold": 0.5,
                    }
                ],
            )
            out = root / "report.json"

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = tool_eval.main(
                    [
                        "tool-eval",
                        "--benchmark",
                        str(path),
                        "--json",
                        str(out),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["totals"]["pass"], 1)


class CorpusTests(unittest.TestCase):
    """The labelled-corpus calibration mode."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _corpus(self, cases: list[dict]) -> Path:
        (self.root / "corpus.yaml").write_text(
            yaml.safe_dump({"version": 1, "cases": cases}, sort_keys=False),
            encoding="utf-8",
        )
        for case in cases:
            (self.root / str(case["id"])).mkdir(exist_ok=True)
        return self.root

    def _case(self, case_id, gate, label, **extra):
        payload = {
            "id": case_id,
            "gate": gate,
            "label": label,
            "source": "test",
        }
        payload.update(extra)
        return payload

    def _row(self, row_id, label, outcome, gate="g"):
        return {
            "id": row_id,
            "gate": gate,
            "label": label,
            "outcome": outcome,
            "source": "t",
            "note": "",
        }

    def test_a_missing_manifest_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "找不到语料清单"):
            tool_eval.load_corpus(self.root / "nope")

    def test_an_empty_case_list_is_an_error(self):
        path = self._corpus([])

        with self.assertRaisesRegex(ValueError, "非空 cases"):
            tool_eval.load_corpus(path)

    def test_a_missing_field_is_an_error(self):
        path = self._corpus([{"id": "a", "gate": "stats-plan", "label": "clean"}])

        with self.assertRaisesRegex(ValueError, "缺少 source"):
            tool_eval.load_corpus(path)

    def test_an_unknown_gate_is_an_error(self):
        path = self._corpus([self._case("a", "made-up", "clean")])

        with self.assertRaisesRegex(ValueError, "未知 gate"):
            tool_eval.load_corpus(path)

    def test_an_unknown_label_is_an_error(self):
        path = self._corpus([self._case("a", "stats-plan", "maybe")])

        with self.assertRaisesRegex(ValueError, "label 必须是"):
            tool_eval.load_corpus(path)

    def test_a_missing_case_directory_is_an_error(self):
        path = self._corpus([self._case("a", "stats-plan", "clean")])
        (path / "a").rmdir()

        with self.assertRaisesRegex(ValueError, "找不到用例目录"):
            tool_eval.load_corpus(path)

    def test_a_valid_corpus_loads_with_its_root(self):
        path = self._corpus([self._case("a", "stats-plan", "clean")])

        cases = tool_eval.load_corpus(path)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["root"], path / "a")

    def test_tpr_rewards_a_gate_that_rejects_defective_cases(self):
        summary = tool_eval.summarise_corpus(
            [
                self._row("d1", tool_eval.DEFECTIVE, "rejected"),
                self._row("c1", tool_eval.CLEAN_LABEL, "accepted"),
            ]
        )

        self.assertEqual(summary["totals"]["tpr"], 1.0)
        self.assertEqual(summary["totals"]["fpr"], 0.0)

    def test_a_missed_defect_lowers_tpr(self):
        summary = tool_eval.summarise_corpus(
            [self._row("d1", tool_eval.DEFECTIVE, "accepted")]
        )

        self.assertEqual(summary["totals"]["tpr"], 0.0)
        self.assertEqual(summary["totals"]["missed"], 1)

    def test_an_error_is_excluded_from_both_denominators(self):
        summary = tool_eval.summarise_corpus(
            [
                self._row("d1", tool_eval.DEFECTIVE, tool_eval.ERROR),
                self._row("d2", tool_eval.DEFECTIVE, "rejected"),
            ]
        )

        self.assertEqual(summary["totals"]["errors"], 1)
        # One scored defect, and it was caught: the error neither helps nor hurts.
        self.assertEqual(summary["totals"]["tpr"], 1.0)
        self.assertEqual(summary["totals"]["missed"], 0)

    def test_the_interval_widens_as_the_sample_shrinks(self):
        small = tool_eval._wilson(1, 1)
        large = tool_eval._wilson(50, 50)

        self.assertIsNotNone(small)
        self.assertIsNotNone(large)
        # Wilson(1,1) = [0.21, 1.0] versus Wilson(50,50) = [0.93, 1.0]: the
        # tiny sample is wider, which is the point of reporting the interval.
        self.assertGreater(small[1] - small[0], large[1] - large[0])

    def test_the_interval_is_none_without_scored_cases(self):
        self.assertIsNone(tool_eval._wilson(0, 0))

    def test_run_corpus_grades_a_raising_gate_as_an_error(self):
        def boom(_root):
            raise RuntimeError("x")

        with mock.patch.object(
            tool_eval, "gate_registry", return_value={"boom": boom}
        ):
            results = tool_eval.run_corpus(
                [
                    {
                        "id": "a",
                        "gate": "boom",
                        "label": "clean",
                        "source": "t",
                        "note": "",
                        "root": self.root,
                    }
                ]
            )

        self.assertEqual(results[0]["outcome"], tool_eval.ERROR)

    def test_the_markdown_report_states_the_sample_size(self):
        summary = tool_eval.summarise_corpus(
            [self._row("d1", tool_eval.DEFECTIVE, "rejected")]
        )

        text = tool_eval.render_corpus_markdown(summary)

        self.assertIn("Wilson", text)
        self.assertIn("样本量", text)
        self.assertIn("`d1`", text)

    def test_the_cli_runs_the_shipped_seed_corpus(self):
        shipped = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "examples"
            / "calibration-corpus"
        )
        self.assertTrue((shipped / "corpus.yaml").is_file())

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = tool_eval.main(["tool-eval", "--corpus", str(shipped)])

        self.assertEqual(code, 0)

    def test_the_cli_rejects_a_broken_corpus_with_exit_two(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = tool_eval.main(
                ["tool-eval", "--corpus", str(self.root / "nope")]
            )

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
