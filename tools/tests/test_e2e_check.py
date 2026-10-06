"""Metrics history and trend rendering for the one-page snapshot.

The snapshot used to be a single reading. These tests cover the part that turns
readings into a trend: reading the attempt metrics out of the cost ledger,
appending one sample per deliberate write, and rendering the delta.
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from ccfa import e2e_check

COST_LEDGER = """\
version: 1
currency: USD
paper: demo
entries:
  - kind: gpu
    amount: 0
    unit: hours
metrics:
  time_to_first_attempt:
    status: recorded
    value: 4.5
    unit: hours
    source: experiments/log/run-1.json
  cost_per_attempt:
    status: recorded
    value: 0.0
    currency: USD
    source: experiments/log/compute-ledger.jsonl
"""

UNRECORDED = """\
version: 1
currency: USD
paper: demo
entries:
  - kind: gpu
    amount: 0
    unit: hours
metrics:
  time_to_first_attempt:
    status: not-applicable
    reason: plan freeze had no timestamp
  cost_per_attempt:
    status: recorded
    value: 0.0
    currency: USD
    source: experiments/log/compute-ledger.jsonl
"""


class CollectSampleTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()

    def _write_ledger(self, text: str) -> None:
        (self.paper / "data" / "cost-ledger.yaml").write_text(
            text,
            encoding="utf-8",
        )

    def _report(self, *, ready: bool, blocking: list[str]) -> dict:
        return {
            "paper_root": str(self.paper),
            "ready": ready,
            "blocking": blocking,
        }

    def test_sample_reads_the_recorded_metrics(self):
        self._write_ledger(COST_LEDGER)

        sample = e2e_check.collect_sample(
            self._report(ready=False, blocking=["a", "b"]),
            today=date(2026, 10, 6),
        )

        self.assertEqual(sample["date"], "2026-10-06")
        self.assertRegex(
            sample["sampled_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )
        self.assertFalse(sample["ready"])
        self.assertEqual(sample["blocking"], 2)
        self.assertEqual(sample["time_to_first_attempt"], 4.5)
        self.assertEqual(sample["cost_per_attempt"], 0.0)

    def test_not_applicable_metric_is_recorded_as_none(self):
        self._write_ledger(UNRECORDED)

        sample = e2e_check.collect_sample(
            self._report(ready=False, blocking=[]),
            today=date(2026, 10, 6),
        )

        self.assertIsNone(sample["time_to_first_attempt"])

    def test_missing_ledger_is_not_an_error(self):
        sample = e2e_check.collect_sample(
            self._report(ready=True, blocking=[]),
            today=date(2026, 10, 6),
        )

        self.assertIsNone(sample["time_to_first_attempt"])
        self.assertIsNone(sample["cost_per_attempt"])
        self.assertEqual(sample["blocking"], 0)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)

    def test_append_and_read_round_trip(self):
        e2e_check.append_sample(self.paper, {"date": "2026-10-05", "blocking": 5})
        e2e_check.append_sample(self.paper, {"date": "2026-10-06", "blocking": 3})

        samples = e2e_check.read_history(self.paper)

        self.assertEqual([item["blocking"] for item in samples], [5, 3])

    def test_malformed_lines_are_skipped(self):
        path = self.paper / e2e_check.METRICS_HISTORY
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"date": "2026-10-05", "blocking": 5}\n'
            "not json\n"
            "\n"
            '["not", "an", "object"]\n'
            '{"date": "2026-10-06", "blocking": 3}\n',
            encoding="utf-8",
        )

        samples = e2e_check.read_history(self.paper)

        self.assertEqual(len(samples), 2)

    def test_trend_shows_the_delta_and_an_em_dash_for_missing_values(self):
        lines = e2e_check.render_trend(
            [
                {"date": "2026-10-05", "ready": False, "blocking": 5,
                 "time_to_first_attempt": None, "cost_per_attempt": 0.0},
                {"date": "2026-10-06", "ready": False, "blocking": 3,
                 "time_to_first_attempt": None, "cost_per_attempt": 0.0},
            ]
        )
        text = "\n".join(lines)

        self.assertIn("| date |", text)
        self.assertIn("—", text)
        self.assertIn("5 → 3（-2）", text)

    def test_trend_marks_the_sample_time_and_the_history_versus_current_gap(self):
        lines = e2e_check.render_trend(
            [
                {
                    "date": "2026-10-06",
                    "sampled_at": "2026-10-06T12:34:56Z",
                    "ready": False,
                    "blocking": 5,
                    "time_to_first_attempt": None,
                    "cost_per_attempt": None,
                    "time_to_first_attempt_status": "not-applicable",
                    "cost_per_attempt_status": "not-applicable",
                }
            ],
            current_blocking=2,
        )
        text = "\n".join(lines)

        self.assertIn("2026-10-06 12:34Z", text)
        self.assertIn("not-applicable", text)
        self.assertIn("历史 vs 当前", text)
        self.assertIn("当前快照阻塞 2", text)

    def test_empty_history_says_how_to_start_one(self):
        text = "\n".join(e2e_check.render_trend([]))

        self.assertIn("metrics-history.jsonl", text)


class SnapshotWiringTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "data" / "cost-ledger.yaml").write_text(
            COST_LEDGER,
            encoding="utf-8",
        )
        self.report = {
            "paper_root": str(self.paper),
            "ready": False,
            "blocking": ["one"],
        }

    def _run(self, *extra):
        import unittest.mock as mock

        with (
            mock.patch.object(
                e2e_check.readiness_module,
                "build_report",
                return_value=self.report,
            ),
            mock.patch.object(
                e2e_check,
                "collect_environment",
                return_value=([], [], []),
            ),
            mock.patch.object(
                e2e_check,
                "render_snapshot",
                return_value="# snapshot\n",
            ),
        ):
            return e2e_check.main(
                [
                    "e2e-check",
                    "--paper-root",
                    str(self.paper),
                    "--out",
                    str(self.paper / "reviews" / "e2e.md"),
                    *extra,
                ]
            )

    def test_out_records_one_sample(self):
        code = self._run()

        self.assertEqual(code, 0)
        samples = e2e_check.read_history(self.paper)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["blocking"], 1)
        self.assertEqual(samples[0]["time_to_first_attempt"], 4.5)

    def test_no_record_writes_the_snapshot_only(self):
        code = self._run("--no-record")

        self.assertEqual(code, 0)
        self.assertEqual(e2e_check.read_history(self.paper), [])


if __name__ == "__main__":
    unittest.main()
