"""The gate self-evaluation harness.

Two things are being pinned here: the shipped case set must actually
discriminate (every injected defect caught, every clean fixture accepted), and
the harness must grade honestly — an error is neither a detection nor a clean
pass, and a miss must move the rate.
"""

import unittest

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


if __name__ == "__main__":
    unittest.main()
