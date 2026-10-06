"""Deterministic print-ready HTML poster generation."""

import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import poster_html as module
from ccfa import talk_gates


def _plan(**overrides):
    payload = {
        "version": 1,
        "template": "landscape_4col",
        "venue": "ICML",
        "title": "Memory Poisoning",
        "authors": "A. Author, B. Author",
        "columns": [
            {
                "title": "Motivation",
                "cards": [
                    {"heading": "Why", "bullets": ["RAG is everywhere"]},
                ],
            },
            {
                "title": "Method",
                "cards": [{"heading": "Pipeline", "figure": "pipeline"}],
            },
        ],
        "footer": "Contact: a@example.edu",
    }
    payload.update(overrides)
    return payload


class CanvasTests(unittest.TestCase):
    def test_each_template_has_its_own_canvas(self):
        self.assertEqual(
            module.canvas_for({"template": "landscape_4col"}),
            (60.0, 36.0),
        )
        self.assertEqual(
            module.canvas_for({"template": "portrait_2col"}),
            (24.0, 36.0),
        )

    def test_an_explicit_canvas_overrides_the_template(self):
        self.assertEqual(
            module.canvas_for(
                {"template": "portrait_2col", "canvas": {"width_in": 30, "height_in": 40}}
            ),
            (30.0, 40.0),
        )

    def test_a_nonsense_canvas_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "canvas.width_in"):
            module.canvas_for(
                {"template": "portrait_2col", "canvas": {"width_in": 0}}
            )


class BuildTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        (self.root / "figures").mkdir()
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: pipeline\n    name: pipeline\n    file: figures/pipeline.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "pipeline.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 4096)

    def _write_plan(self, payload):
        (self.root / "data" / "poster-plan.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def test_the_page_rule_and_the_container_stay_in_sync(self):
        self._write_plan(_plan())

        result = module.write_poster(self.root)
        html = result["html"]

        self.assertIn("@page { size: 60in 36in; margin: 0; }", html)
        self.assertIn("width: 60in; height: 36in;", html)

    def test_every_layout_region_carries_a_measure_role(self):
        self._write_plan(_plan())

        html = module.write_poster(self.root)["html"]

        for role in ("poster", "column", "footer"):
            self.assertIn(f'data-measure-role="{role}"', html)

    def test_venue_tokens_come_from_the_reference_pack(self):
        self._write_plan(_plan())

        html = module.write_poster(self.root)["html"]

        self.assertIn("--accent: #8B3A4A;", html)
        self.assertIn("--accent-deep: #642430;", html)

    def test_an_unknown_venue_falls_back_and_says_so(self):
        self._write_plan(_plan(venue="SIGBOVIK"))

        result = module.write_poster(self.root)

        self.assertEqual(result["venue"], "generic")
        self.assertIn("--accent: #2D5F8B;", result["html"])
        self.assertEqual(len(result["findings"]), 1)

    def test_rendering_twice_is_byte_identical(self):
        self._write_plan(_plan())

        first = module.build(self.root)["html"]
        second = module.build(self.root)["html"]

        self.assertEqual(first, second)

    def test_a_figure_card_embeds_the_real_file_name(self):
        self._write_plan(_plan())

        result = module.write_poster(self.root)

        self.assertIn('src="figures/pipeline.png"', result["html"])
        self.assertEqual(result["written"], ["pipeline"])

    def test_a_missing_figure_is_reported(self):
        self._write_plan(_plan())
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures: []\n",
            encoding="utf-8",
        )

        result = module.write_poster(self.root)

        self.assertEqual(len(result["findings"]), 1)
        self.assertIn("pipeline", result["findings"][0])


class CheckTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        (self.root / "data" / "poster-plan.yaml").write_text(
            yaml.safe_dump(_plan(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        (self.root / "figures").mkdir()

    def test_a_generated_poster_passes(self):
        module.write_poster(self.root)

        problems, advisories = module.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_size_drift_between_page_and_container_is_caught(self):
        result = module.write_poster(self.root)
        path = Path(result["html_path"])
        path.write_text(
            result["html"].replace("height: 36in;", "height: 40in;"),
            encoding="utf-8",
        )

        problems, _advisories = module.check(self.root)

        self.assertIn(
            "poster-size-drift",
            [problem.code for problem in problems],
        )

    def test_a_missing_measure_role_is_caught(self):
        result = module.write_poster(self.root)
        path = Path(result["html_path"])
        path.write_text(
            result["html"].replace(
                ' data-measure-role="footer"',
                "",
            ),
            encoding="utf-8",
        )

        problems, _advisories = module.check(self.root)

        self.assertIn(
            "poster-measure-role-missing",
            [problem.code for problem in problems],
        )

    def test_check_before_building_is_an_advisory(self):
        problems, advisories = module.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(
            [advisory.code for advisory in advisories],
            ["poster-html-not-configured"],
        )


class PrintTests(unittest.TestCase):
    def test_the_printed_pdf_matches_the_page_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "figures").mkdir()
            (root / "data" / "poster-plan.yaml").write_text(
                yaml.safe_dump(
                    _plan(canvas={"width_in": 24, "height_in": 36}),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            result = module.write_poster(root)
            printed = module.render_pdf(
                Path(result["html_path"]),
                root / "poster.pdf",
            )
            if not printed["rendered"]:
                self.skipTest("no headless browser can print here")

            findings, detail = talk_gates.verify_final(
                root / "poster.pdf",
                expected_canvas=talk_gates.canvas_from_html(
                    Path(result["html_path"])
                ),
                expected_pages=1,
            )

            self.assertEqual(findings, [])
            self.assertEqual(detail["actual_in"], [24.0, 36.0])


class PosterCliTests(unittest.TestCase):
    def test_build_then_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "figures").mkdir()
            (root / "data" / "poster-plan.yaml").write_text(
                yaml.safe_dump(_plan(), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

            build_code = module.main(
                ["poster-html", "build", "--paper-root", str(root)]
            )
            check_code = module.main(
                ["poster-html", "check", "--paper-root", str(root)]
            )

        self.assertEqual(build_code, 0)
        self.assertEqual(check_code, 0)


if __name__ == "__main__":
    unittest.main()
