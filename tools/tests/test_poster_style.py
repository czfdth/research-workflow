"""The static style gate for a poster's HTML source."""

import json
import tempfile
import unittest
from pathlib import Path

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


class SourceRuleTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.html = _generated_html(self.root)

    def test_the_generated_poster_passes_every_implemented_rule(self):
        results = poster_style.run_source_rules(self.html)

        failing = [
            item.rule
            for item in results
            if item.status == "fail"
        ]
        self.assertEqual(failing, [])
        self.assertEqual(_status(results, 1), "pass")
        self.assertEqual(_status(results, 2), "pass")
        self.assertEqual(_status(results, 3), "pass")
        self.assertEqual(_status(results, 7), "pass")
        self.assertEqual(_status(results, 8), "pass")

    def test_render_only_rules_are_reported_as_skipped(self):
        report = poster_style.check  # keep the import meaningful
        results = poster_style.run_source_rules(self.html)

        self.assertEqual(_status(results, 4), "skip")
        self.assertEqual(_status(results, 12), "skip")
        self.assertEqual(_status(results, 10), "skip")
        self.assertEqual(_status(results, 11), "skip")
        self.assertIsNotNone(report)

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
        self.assertEqual(
            poster_style.check(
                self._write(broken)
            )[1]["overall"],
            "pass",
        )

    def _write(self, text: str) -> Path:
        path = self.root / "poster.html"
        path.write_text(text, encoding="utf-8")
        return path

    def test_check_reports_a_hard_failure_and_exit_code(self):
        path = self._write(self.html.replace("<h1>", '<h1 style="x: 1">', 1))

        _results, report = poster_style.check(path)

        self.assertEqual(report["overall"], "fail")
        self.assertGreaterEqual(report["hard_failures"], 1)
        self.assertIn(2, [rule["rule"] for rule in report["rules"] if rule["status"] == "fail"])

    def test_a_missing_file_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "找不到"):
            poster_style.check(self.root / "nope.html")


class StyleCliTests(unittest.TestCase):
    def test_cli_writes_a_json_report_and_returns_one_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = _generated_html(root)
            path = root / "poster.html"
            path.write_text(html.replace("<h1>", '<h1 style="x: 1">', 1), encoding="utf-8")
            report_path = root / "report.json"

            code = poster_style.main(
                [
                    "poster-style",
                    "run",
                    "--html",
                    str(path),
                    "--json",
                    str(report_path),
                ]
            )

            self.assertEqual(code, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["skill"], "poster-style")


if __name__ == "__main__":
    unittest.main()
