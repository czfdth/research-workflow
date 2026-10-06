"""Tests for :mod:`ccfa.cost_metrics`."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import cost_metrics


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _state(root: Path, at: str = "2026-10-04T02:00:00Z") -> None:
    _write(
        root / "ccfa.yaml",
        yaml.safe_dump(
            {
                "version": "0.4.0",
                "stage": {
                    "current": "internal-review",
                    "history": [
                        {
                            "from": "idea",
                            "to": "grounded",
                            "at": at,
                            "reason": "scope defined",
                            "kind": "advance",
                        }
                    ],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
    )


def _run(
    root: Path,
    run_id: str,
    *,
    purpose: str = "experiment",
    started_at: str = "2026-10-04T04:16:05Z",
) -> None:
    _write(
        root / "experiments" / "log" / f"{run_id}.json",
        json.dumps(
            {
                "run_id": run_id,
                "declared_purpose": purpose,
                "started_at": started_at,
                "finished_at": started_at,
            },
            ensure_ascii=False,
        ),
    )


def _compute_entry(root: Path, **fields) -> None:
    entry = {
        "command": "python train.py",
        "backend": "local",
        "budget_minutes": 30,
        "wall_seconds": 60.0,
        "gpu_minutes": 0.0,
        "returncode": 0,
        "timed_out": False,
        "recorded_at": "2026-10-04T05:00:00Z",
    }
    entry.update(fields)
    path = root / "experiments" / "log" / "compute-ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _compute_config(root: Path, pricing: dict | None, backends: list | None = None) -> None:
    payload: dict = {"version": 1, "backends": backends or []}
    if pricing is not None:
        payload["pricing"] = pricing
    _write(
        root / "data" / "compute.yaml",
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
    )


def _ledger(
    root: Path,
    metrics: dict,
    *,
    budgets: dict | None = None,
    extra: str = "",
) -> None:
    payload = {
        "version": 1,
        "currency": "USD",
        "notes": "fixture ledger",
        "entries": [{"kind": "gpu", "amount": 0, "unit": "hours"}],
    }
    if budgets is not None:
        payload["budgets"] = budgets
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    text = text.rstrip("\n") + "\n" + yaml.safe_dump(
        {"metrics": metrics}, allow_unicode=True, sort_keys=False
    )
    _write(root / "data" / "cost-ledger.yaml", text + extra)


class TimeToFirstAttemptTests(unittest.TestCase):
    def test_uses_the_state_history_timestamp_and_the_first_non_build_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root, at="2026-10-04T02:00:00Z")
            _run(
                root,
                "20261004T041605-01",
                purpose="experiment",
                started_at="2026-10-04T04:16:05Z",
            )

            verdict = cost_metrics.derive_time_to_first_attempt(root)

            self.assertEqual(verdict.status, "recorded")
            self.assertAlmostEqual(verdict.value, 2.2681, places=4)
            self.assertEqual(verdict.unit, "hours")
            self.assertIn("20261004T041605-01", verdict.source)

    def test_skips_build_runs_when_choosing_the_first_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root, at="2026-10-04T02:00:00Z")
            _run(
                root,
                "20261004T030000-01",
                purpose="build",
                started_at="2026-10-04T03:00:00Z",
            )
            _run(
                root,
                "20261004T050000-01",
                purpose="experiment",
                started_at="2026-10-04T05:00:00Z",
            )

            verdict = cost_metrics.derive_time_to_first_attempt(root)

            self.assertEqual(verdict.status, "recorded")
            self.assertIn("20261004T050000-01", verdict.source)
            self.assertAlmostEqual(verdict.value, 3.0, places=4)

    def test_date_only_freeze_is_not_applicable_with_the_fix_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root, at="2026-10-04")
            _run(root, "20261004T050000-01")

            verdict = cost_metrics.derive_time_to_first_attempt(root)

            self.assertEqual(verdict.status, "not-applicable")
            self.assertIn("没有时刻", verdict.reason)
            self.assertIn("ISO-8601", verdict.reason)

    def test_no_non_build_attempt_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root)
            _run(root, "20261004T050000-01", purpose="build")

            verdict = cost_metrics.derive_time_to_first_attempt(root)

            self.assertEqual(verdict.status, "not-applicable")
            self.assertIn("没有非 build 运行记录", verdict.reason)
            self.assertIn("1 条 build", verdict.reason)

    def test_an_attempt_before_the_freeze_refuses_to_produce_a_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root, at="2026-10-05T00:00:00Z")
            _run(root, "20261004T050000-01", started_at="2026-10-04T05:00:00Z")

            verdict = cost_metrics.derive_time_to_first_attempt(root)

            self.assertEqual(verdict.status, "not-applicable")
            self.assertIn("顺序不成立", verdict.reason)

    def test_frozen_at_line_in_the_plan_artifact_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / cost_metrics.PLAN_ARTIFACT,
                "# Idea selection\n\nDate: 2026-10-04\n"
                "Frozen at: 2026-10-04T02:00:00Z\n",
            )
            _run(root, "20261004T041605-01", started_at="2026-10-04T04:16:05Z")

            verdict = cost_metrics.derive_time_to_first_attempt(root)

            self.assertEqual(verdict.status, "recorded")
            self.assertAlmostEqual(verdict.value, 2.2681, places=4)


class CostPerAttemptTests(unittest.TestCase):
    def test_prices_the_compute_ledger_with_the_declared_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _compute_config(
                root,
                {"currency": "USD", "cpu_hour_usd": 0.0, "gpu_hour_usd": 2.0},
            )
            _compute_entry(
                root, backend="slurm:gpu.example", wall_seconds=1800.0, gpus_used=1
            )

            verdict = cost_metrics.derive_cost_per_attempt(root)

            self.assertEqual(verdict.status, "recorded")
            self.assertAlmostEqual(verdict.value, 1.0, places=6)
            self.assertEqual(verdict.currency, "USD")
            self.assertIn("pricing", verdict.source)

    def test_zero_attempts_is_not_applicable_rather_than_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run(root, "20261004T041605-01", purpose="build")

            verdict = cost_metrics.derive_cost_per_attempt(root)

            self.assertEqual(verdict.status, "not-applicable")
            self.assertIn("没有可测对象", verdict.reason)

    def test_a_remote_backend_without_pricing_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _compute_config(root, None, backends=[{"kind": "ssh", "host": "box"}])
            _compute_entry(root, backend="ssh:box", wall_seconds=600.0)

            verdict = cost_metrics.derive_cost_per_attempt(root)

            self.assertEqual(verdict.status, "not-applicable")
            self.assertIn("缺 pricing.cpu_hour_usd", verdict.reason)

    def test_local_attempts_without_pricing_are_zero_but_the_gap_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _compute_config(root, None)
            _run(root, "20261004T050000-01")
            _run(root, "20261004T060000-01")

            verdict = cost_metrics.derive_cost_per_attempt(root)

            self.assertEqual(verdict.status, "recorded")
            self.assertEqual(verdict.value, 0.0)
            self.assertIn("不代表免费", verdict.source)
            self.assertIn("2 次尝试", verdict.source)

    def test_malformed_ledger_lines_are_skipped_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _compute_config(root, {"cpu_hour_usd": 1.0})
            _compute_entry(root, backend="local", wall_seconds=3600.0)
            path = root / "experiments" / "log" / "compute-ledger.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write("{not json}\n")

            verdict = cost_metrics.derive_cost_per_attempt(root)

            self.assertEqual(verdict.status, "recorded")
            self.assertAlmostEqual(verdict.value, 1.0, places=6)
            self.assertIn("1 行 compute-ledger 无法解析", verdict.source)


class CheckTests(unittest.TestCase):
    def _matching_ledger(self, root: Path) -> None:
        report = cost_metrics.derive(root)
        metrics = {name: report["metrics"][name] for name in cost_metrics.METRIC_NAMES}
        _ledger(root, metrics)

    def test_check_passes_when_the_ledger_matches_the_derivation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root)
            _run(root, "20261004T041605-01")
            self._matching_ledger(root)

            problems, advisories = cost_metrics.check(root)

            self.assertEqual(problems, [])
            self.assertEqual(advisories, [])

    def test_check_reports_drift_when_the_ledger_keeps_a_stale_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root)
            _ledger(
                root,
                {
                    "time_to_first_attempt": {
                        "status": "recorded",
                        "value": 99.0,
                        "unit": "hours",
                        "source": "hand written",
                    },
                    "cost_per_attempt": {
                        "status": "not-applicable",
                        "reason": "fixture",
                    },
                },
            )

            problems, advisories = cost_metrics.check(root)

            codes = {problem.code for problem in problems}
            self.assertIn("cost-ledger-drift", codes)
            self.assertTrue(any("99.0" in item.message for item in problems))
            self.assertEqual(len(advisories), 1)
            self.assertIn(
                "cost-metrics-not-applicable",
                {item.code for item in advisories},
            )

    def test_check_reports_a_recorded_value_the_artifacts_cannot_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ledger(
                root,
                {
                    "time_to_first_attempt": {
                        "status": "not-applicable",
                        "reason": "no attempts",
                    },
                    "cost_per_attempt": {
                        "status": "recorded",
                        "value": 0.0,
                        "currency": "USD",
                        "source": "hand written",
                    },
                },
            )

            problems, _advisories = cost_metrics.check(root)

            self.assertEqual(
                [problem.code for problem in problems],
                ["cost-ledger-drift"],
            )
            self.assertIn("推不出这个值", problems[0].message)

    def test_write_metrics_only_replaces_the_metrics_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root)
            _run(root, "20261004T041605-01")
            _ledger(
                root,
                {
                    "time_to_first_attempt": {"status": "recorded", "value": 1.0},
                    "cost_per_attempt": {"status": "recorded", "value": 0.0},
                },
                extra="# keep this trailing comment\n",
            )

            path = cost_metrics.write_metrics(root)

            text = path.read_text(encoding="utf-8")
            self.assertIn("notes: fixture ledger", text)
            self.assertIn("kind: gpu", text)
            self.assertIn("# keep this trailing comment", text)
            problems, _advisories = cost_metrics.check(root)
            self.assertEqual(problems, [])


class BudgetTests(unittest.TestCase):
    def _exceeded_fixture(self, root: Path, budgets: dict) -> None:
        _state(root, at="2026-10-04T02:00:00Z")
        _run(root, "20261004T041605-01", started_at="2026-10-04T04:16:05Z")
        report = cost_metrics.derive(root)
        _ledger(
            root,
            {name: report["metrics"][name] for name in cost_metrics.METRIC_NAMES},
            budgets=budgets,
        )

    def test_a_stage_budget_that_is_exceeded_becomes_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._exceeded_fixture(
                root,
                {"default": {"time_to_first_attempt_hours_max": 1.0}},
            )

            problems, advisories = cost_metrics.check(root)

            codes = {problem.code for problem in problems}
            self.assertIn("cost-budget-exceeded", codes)
            self.assertTrue(any("2.2681" in item.message for item in problems))
            self.assertEqual(advisories, [])

    def test_a_stage_entry_overrides_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._exceeded_fixture(
                root,
                {
                    "default": {"time_to_first_attempt_hours_max": 1.0},
                    "internal-review": {"time_to_first_attempt_hours_max": 10.0},
                },
            )

            problems, advisories = cost_metrics.check(root)

            self.assertEqual(problems, [])
            self.assertEqual(advisories, [])

    def test_unknown_budget_stage_and_key_are_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._exceeded_fixture(
                root,
                {
                    "not-a-stage": {"time_to_first_attempt_hours_max": 1.0},
                    "default": {"bogus_max": 1.0},
                },
            )

            problems, _advisories = cost_metrics.check(root)

            messages = " ".join(item.message for item in problems)
            self.assertIn("不是合法 stage", messages)
            self.assertIn("不是已知预算项", messages)

    def test_a_budget_for_an_unmeasurable_metric_is_an_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root)
            _ledger(
                root,
                {
                    "time_to_first_attempt": {
                        "status": "not-applicable",
                        "reason": "no attempts yet",
                    },
                    "cost_per_attempt": {
                        "status": "not-applicable",
                        "reason": "no attempts yet",
                    },
                },
                budgets={"default": {"time_to_first_attempt_hours_max": 72.0}},
            )

            problems, advisories = cost_metrics.check(root)

            self.assertEqual(problems, [])
            codes = {item.code for item in advisories}
            self.assertIn("cost-budget-unmeasured", codes)

    def test_write_metrics_preserves_the_budgets_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._exceeded_fixture(
                root,
                {"default": {"time_to_first_attempt_hours_max": 1.0}},
            )

            path = cost_metrics.write_metrics(root)

            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["budgets"]["default"]["time_to_first_attempt_hours_max"],
                1.0,
            )


class CliTests(unittest.TestCase):
    def test_derive_and_check_run_through_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state(root)
            _run(root, "20261004T041605-01")
            report = cost_metrics.derive(root)
            _ledger(
                root,
                {
                    name: report["metrics"][name]
                    for name in cost_metrics.METRIC_NAMES
                },
            )

            self.assertEqual(
                cost_metrics.main(["ccfa cost-metrics", "derive", "--paper-root", tmp]),
                0,
            )
            self.assertEqual(
                cost_metrics.main(["ccfa cost-metrics", "check", "--paper-root", tmp]),
                0,
            )
            self.assertEqual(
                cost_metrics.main(
                    [
                        "ccfa cost-metrics",
                        "derive",
                        "--paper-root",
                        tmp,
                        "--write",
                    ]
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
