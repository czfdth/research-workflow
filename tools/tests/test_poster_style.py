"""The poster style gate: source rules plus the rendered rules 4 and 12."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from ccfa import poster_html, poster_style

PLAN = {
    "version": 1,
    "template": "portrait_2col",
    "venue": "ICLR",
    "title": "T",
    "authors": "A",
    "columns": [{"title": "C", "cards": [{"heading": "H", "bullets": ["b"]}]}],
    "footer": "f",
}


def _generated_html(root: Path) -> str:
    (root / "data").mkdir(exist_ok=True)
    (root / "figures").mkdir(exist_ok=True)
    (root / "data" / "poster-plan.yaml").write_text(
        yaml.safe_dump(PLAN, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return poster_html.write_poster(root)["html"]


def _status(results, rule: int) -> str:
    return next(item.status for item in results if item.rule == rule)


def _rule(results, rule: int) -> poster_style.RuleResult:
    return next(item for item in results if item.rule == rule)


def _metrics(colors, *, poster_area=1000.0, dark_area=0.0) -> dict:
    return {
        "colors": [{"prop": "color", "rgba": value} for value in colors],
        "posterArea": poster_area,
        "darkArea": dark_area,
    }


# Resolved once; the render-gate integration tests skip cleanly without a browser.
_RENDER_READY: bool | None = None


def _render_ready() -> bool:
    global _RENDER_READY
    if _RENDER_READY is None:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser, _engine = poster_style._launch_browser(playwright)
                browser.close()
            _RENDER_READY = True
        except Exception:
            _RENDER_READY = False
    return _RENDER_READY


class SourceRuleTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.html = _generated_html(self.root)

    def test_the_generated_poster_passes_every_implemented_rule(self):
        results = poster_style.run_source_rules(self.html)

        failing = [item.rule for item in results if item.status == "fail"]
        self.assertEqual(failing, [])
        self.assertEqual(_status(results, 1), "pass")
        self.assertEqual(_status(results, 2), "pass")
        self.assertEqual(_status(results, 3), "pass")
        self.assertEqual(_status(results, 7), "pass")
        self.assertEqual(_status(results, 8), "pass")

    def test_render_and_component_contract_rules_are_reported_as_skipped(self):
        results = poster_style.run_source_rules(self.html)

        for rule in (4, 10, 11, 12):
            self.assertEqual(_status(results, rule), "skip")

    def test_a_missing_token_block_fails_rule_one(self):
        broken = self.html.replace("/* ===== DESIGN TOKENS ===== */", "")

        results = poster_style.run_source_rules(broken)

        self.assertEqual(_status(results, 1), "fail")
        self.assertIn("design-token", next(r.detail for r in results if r.rule == 1))

    def test_a_colour_literal_outside_the_token_block_fails_rule_one(self):
        broken = self.html.replace(
            ".card-list {",
            ".card-list { color: #ff0000;",
            1,
        )

        results = poster_style.run_source_rules(broken)

        self.assertEqual(_status(results, 1), "fail")
        self.assertIn("#ff0000", next(r.offenders for r in results if r.rule == 1))

    def test_an_inline_style_fails_rule_two(self):
        broken = self.html.replace("<h1>", '<h1 style="color: red">', 1)

        results = poster_style.run_source_rules(broken)

        self.assertEqual(_status(results, 2), "fail")

    def test_a_component_colour_literal_fails_rule_three(self):
        broken = self.html.replace(
            ".card-list {",
            ".card-list { color: rgb(1, 2, 3);",
            1,
        )

        results = poster_style.run_source_rules(broken)

        self.assertEqual(_status(results, 3), "fail")

    def test_a_non_whitelisted_font_fails_rule_seven(self):
        broken = self.html.replace(
            "--font-sans: Inter, Aptos, Helvetica Neue, Arial, sans-serif;",
            "--font-sans: Comic Sans MS, sans-serif;",
        )

        results = poster_style.run_source_rules(broken)

        self.assertEqual(_status(results, 7), "fail")

    def test_a_raw_font_size_fails_rule_eight(self):
        broken = self.html.replace(
            ".footer {",
            ".footer { font-size: 19px;",
            1,
        )

        results = poster_style.run_source_rules(broken)

        self.assertEqual(_status(results, 8), "fail")

    def test_too_many_font_size_tokens_warns_rule_nine(self):
        extra = "".join(
            f"  --fs-{index}: calc({index * 10} * var(--u));\n"
            for index in range(10, 14)
        )
        # The tokens have to land inside the design-token block, not just
        # anywhere in the stylesheet.
        broken = self.html.replace(
            "  --fs-9: calc(22 * var(--u));\n",
            "  --fs-9: calc(22 * var(--u));\n" + extra,
        )

        results = poster_style.run_source_rules(broken)

        self.assertEqual(_status(results, 9), "warn")
        # A warning alone must not fail the gate.
        self.assertEqual(poster_style.check(self._write(broken))[1]["overall"], "pass")

    def _write(self, text: str) -> Path:
        path = self.root / "poster.html"
        path.write_text(text, encoding="utf-8")
        return path

    def test_check_reports_a_hard_failure_and_exit_code(self):
        path = self._write(self.html.replace("<h1>", '<h1 style="x: 1">', 1))

        _results, report = poster_style.check(path)

        self.assertEqual(report["overall"], "fail")
        self.assertGreaterEqual(report["hard_failures"], 1)
        self.assertIn(
            2, [rule["rule"] for rule in report["rules"] if rule["status"] == "fail"]
        )

    def test_check_without_render_marks_the_render_gate_unevaluated(self):
        path = self._write(self.html)

        _results, report = poster_style.check(path, render=False)

        self.assertFalse(report["render"]["requested"])
        self.assertFalse(report["render"]["evaluated"])
        self.assertIn(4, report["skipped_rules"])
        self.assertIn(12, report["skipped_rules"])

    def test_a_missing_file_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "找不到"):
            poster_style.check(self.root / "nope.html")


class HueMathTests(unittest.TestCase):
    def test_hue_of_rgb_unpacks_hls_in_the_right_order(self):
        hue, saturation, lightness = poster_style._hue_of_rgb(255, 0, 0)

        self.assertAlmostEqual(hue, 0.0)
        self.assertAlmostEqual(saturation, 1.0)
        self.assertAlmostEqual(lightness, 0.5)

    def test_hue_distance_is_circular(self):
        self.assertAlmostEqual(poster_style._hue_dist(350, 5), 15.0)
        self.assertAlmostEqual(poster_style._hue_dist(0, 180), 180.0)

    def test_cluster_hues_merges_across_the_wrap_around(self):
        centers = poster_style.cluster_hues([350.0, 355.0, 5.0, 10.0])

        self.assertEqual(len(centers), 1)
        self.assertLess(poster_style._hue_dist(centers[0], 0.0), 18.0)

    def test_cluster_hues_splits_distinct_families(self):
        centers = poster_style.cluster_hues([10.0, 120.0, 240.0])

        self.assertEqual(len(centers), 3)

    def test_cluster_hues_is_empty_for_no_hues(self):
        self.assertEqual(poster_style.cluster_hues([]), [])

    def test_parse_rgba_handles_percent_alpha(self):
        self.assertEqual(
            poster_style._parse_rgba_str("rgba(1, 2, 3, 50%)"), (1, 2, 3, 0.5)
        )
        self.assertEqual(
            poster_style._parse_rgba_str("rgb(10, 20, 30)"), (10, 20, 30, 1.0)
        )
        self.assertIsNone(poster_style._parse_rgba_str("not a colour"))

    def test_hue_from_hex_accepts_short_and_long_forms(self):
        self.assertAlmostEqual(poster_style._hue_from_hex("#f00"), 0.0)
        self.assertAlmostEqual(poster_style._hue_from_hex("#00FF00"), 120.0)
        self.assertIsNone(poster_style._hue_from_hex("red"))

    def test_hue_centers_resolve_from_the_token_block(self):
        centers = poster_style.resolve_hue_centers(
            None, poster_style.token_block_of(_generated_html(self._tmp()))
        )

        self.assertAlmostEqual(centers["accent"], 151.2, places=1)
        self.assertAlmostEqual(centers["gold"], 41.6, places=1)

    def _tmp(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)


class RenderRuleEvaluationTests(unittest.TestCase):
    """Rule 4/12 thresholds, exercised without a browser."""

    CENTERS = {"accent": 151.2, "gold": 41.6}

    def test_three_hue_families_fail_rule_four(self):
        metrics = _metrics(["rgb(46, 96, 72)", "rgb(201, 162, 74)", "rgb(176, 58, 106)"])

        results = poster_style.evaluate_render_metrics(metrics, self.CENTERS)

        self.assertEqual(_status(results, 4), "fail")
        self.assertEqual(_rule(results, 4).severity, "hard")

    def test_a_single_accent_hue_passes_rule_four(self):
        metrics = _metrics(["rgb(46, 96, 72)", "rgb(30, 66, 49)"])

        results = poster_style.evaluate_render_metrics(metrics, self.CENTERS)

        self.assertEqual(_status(results, 4), "pass")

    def test_neutral_greys_are_not_hue_families(self):
        metrics = _metrics(["rgb(26, 26, 26)", "rgb(255, 255, 255)", "rgb(216, 216, 216)"])

        results = poster_style.evaluate_render_metrics(metrics, self.CENTERS)

        self.assertEqual(_status(results, 4), "pass")
        self.assertIn("0 个色相聚类", _rule(results, 4).detail)

    def test_an_off_palette_cluster_fails_rule_four(self):
        metrics = _metrics(["rgb(46, 96, 72)", "rgb(0, 255, 0)"])

        results = poster_style.evaluate_render_metrics(metrics, self.CENTERS)

        self.assertEqual(_status(results, 4), "fail")

    def test_missing_palette_centers_fails_rule_four(self):
        metrics = _metrics(["rgb(46, 96, 72)"])

        results = poster_style.evaluate_render_metrics(metrics, {})

        self.assertEqual(_status(results, 4), "fail")
        self.assertIn("色相中心", _rule(results, 4).detail)

    def test_dark_area_over_the_threshold_warns_but_never_fails(self):
        metrics = _metrics([], poster_area=1000.0, dark_area=200.0)

        results = poster_style.evaluate_render_metrics(metrics, self.CENTERS)
        rule12 = _rule(results, 12)

        self.assertEqual(rule12.status, "warn")
        self.assertEqual(rule12.severity, "warn")
        self.assertNotIn(
            "fail",
            [item.status for item in results if item.severity == "hard"],
        )

    def test_a_small_dark_area_passes_rule_twelve(self):
        metrics = _metrics([], poster_area=1000.0, dark_area=50.0)

        results = poster_style.evaluate_render_metrics(metrics, self.CENTERS)

        self.assertEqual(_status(results, 12), "pass")

    def test_transparent_and_near_transparent_colours_are_ignored(self):
        metrics = _metrics(["rgba(255, 0, 0, 0.01)", "rgba(0, 0, 0, 0)"])

        results = poster_style.evaluate_render_metrics(metrics, self.CENTERS)

        self.assertEqual(_status(results, 4), "pass")


class StyleCliTests(unittest.TestCase):
    def test_cli_writes_a_json_report_and_returns_one_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = _generated_html(root)
            path = root / "poster.html"
            path.write_text(
                html.replace("<h1>", '<h1 style="x: 1">', 1), encoding="utf-8"
            )
            report_path = root / "report.json"

            code = poster_style.main(
                [
                    "poster-style",
                    "run",
                    "--html",
                    str(path),
                    "--no-render",
                    "--json",
                    str(report_path),
                ]
            )

            self.assertEqual(code, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["skill"], "poster-style")

    def test_cli_no_render_reports_rules_four_and_twelve_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "poster.html"
            path.write_text(_generated_html(root), encoding="utf-8")
            report_path = root / "report.json"

            code = poster_style.main(
                [
                    "poster-style",
                    "run",
                    "--html",
                    str(path),
                    "--no-render",
                    "--json",
                    str(report_path),
                ]
            )

            self.assertEqual(code, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["render"]["evaluated"])
            self.assertIn(4, report["skipped_rules"])
            self.assertIn(12, report["skipped_rules"])

    def test_cli_reports_an_unavailable_renderer_as_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "poster.html"
            path.write_text(_generated_html(root), encoding="utf-8")

            with mock.patch.object(
                poster_style,
                "collect_render_metrics",
                side_effect=poster_style.RenderUnavailable("没有浏览器"),
            ):
                code = poster_style.main(
                    ["poster-style", "run", "--html", str(path)]
                )

            self.assertEqual(code, 2)


@unittest.skipUnless(_render_ready(), "no usable headless browser (Edge/Chrome)")
class RenderGateIntegrationTests(unittest.TestCase):
    """Rules 4 and 12 against a real Playwright render of a generated poster."""

    @classmethod
    def setUpClass(cls):
        if not _render_ready():
            raise unittest.SkipTest("no usable headless browser (Edge/Chrome)")

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.html = _generated_html(self.root)
        self.path = self.root / "poster.html"
        self.path.write_text(self.html, encoding="utf-8")

    def _check(self, text: str) -> dict:
        path = self.root / "mutated.html"
        path.write_text(text, encoding="utf-8")
        _results, report = poster_style.check(path, render=True)
        return report

    def test_a_generated_poster_renders_and_passes_rules_four_and_twelve(self):
        _results, report = poster_style.check(self.path, render=True)
        rules = {item["rule"]: item for item in report["rules"]}

        self.assertEqual(report["overall"], "pass")
        self.assertTrue(report["render"]["evaluated"])
        self.assertEqual(rules[4]["status"], "pass")
        self.assertEqual(rules[12]["status"], "pass")
        self.assertNotIn(4, report["skipped_rules"])
        self.assertNotIn(12, report["skipped_rules"])

    def test_a_third_hue_family_fails_rule_four_when_rendered(self):
        broken = self.html.replace(
            "  --gold: #C9A24A;", "  --gold: #C9A24A;\n  --probe: #B03A6A;"
        ).replace(
            ".footer {",
            ".card-title { color: var(--probe); }\n.footer { background: var(--gold);",
            1,
        )

        report = self._check(broken)
        rules = {item["rule"]: item for item in report["rules"]}

        self.assertEqual(report["overall"], "fail")
        self.assertEqual(rules[4]["status"], "fail")

    def test_a_poster_wide_dark_background_warns_rule_twelve(self):
        broken = self.html.replace("  --bg-page: #F3F4F1;", "  --bg-page: #0B0B0B;")

        report = self._check(broken)
        rules = {item["rule"]: item for item in report["rules"]}

        self.assertEqual(report["overall"], "pass")
        self.assertEqual(rules[12]["status"], "warn")
        self.assertGreaterEqual(report["warnings"], 1)

    def test_a_color_exempt_subtree_is_not_counted_by_rule_four(self):
        def probe(markup: str) -> str:
            text = self.html.replace(
                "  --gold: #C9A24A;", "  --gold: #C9A24A;\n  --probe: #00FF00;"
            ).replace(".footer {", ".probe { color: var(--probe); }\n.footer {", 1)
            return text.replace(
                '<div class="poster" data-measure-role="poster">',
                '<div class="poster" data-measure-role="poster">' + markup,
            )

        exempt = self._check(
            probe('<div data-color-exempt="logo"><span class="probe">x</span></div>')
        )
        counted = self._check(probe('<div><span class="probe">x</span></div>'))
        exempt_rules = {item["rule"]: item for item in exempt["rules"]}
        counted_rules = {item["rule"]: item for item in counted["rules"]}

        self.assertEqual(exempt_rules[4]["status"], "pass")
        self.assertEqual(counted_rules[4]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
