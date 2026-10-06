"""Measuring a printed poster's geometry."""

import tempfile
import unittest
from pathlib import Path

import fitz

from ccfa import poster_measure as module


def _poster_pdf(
    path: Path,
    *,
    bottoms_pt,
    footer_baseline_pt: float,
    card_width: float = 700.0,
    page=(4320.0, 2592.0),
) -> Path:
    document = fitz.open()
    page_obj = document.new_page(width=page[0], height=page[1])
    for index, bottom in enumerate(bottoms_pt):
        x0 = 200 + index * 900
        page_obj.draw_rect(
            fitz.Rect(x0, 400, x0 + card_width, bottom),
            color=None,
            fill=(1.0, 1.0, 1.0),
        )
    page_obj.insert_text(
        fitz.Point(300, footer_baseline_pt),
        "footer contact",
        fontsize=40,
    )
    document.save(str(path))
    document.close()
    return path


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_aligned_columns_report_a_tiny_spread(self):
        pdf = _poster_pdf(
            self.root / "aligned.pdf",
            bottoms_pt=[2000.0, 2000.0, 2000.0],
            footer_baseline_pt=2060.0,
        )

        reading = module.measure(pdf)

        self.assertEqual(reading["columns"], 3)
        self.assertEqual(reading["cards"], 3)
        self.assertLess(reading["spread_px"], 1.0)

    def test_a_short_column_shows_up_as_spread(self):
        pdf = _poster_pdf(
            self.root / "ragged.pdf",
            bottoms_pt=[2000.0, 2000.0, 1900.0],
            footer_baseline_pt=2060.0,
        )

        reading = module.measure(pdf)

        # 100pt at 96/72 px per point is about 133 px.
        self.assertAlmostEqual(reading["spread_px"], 133.33, places=1)
        codes = {item["code"]: item["severity"] for item in module.findings(reading)}
        self.assertEqual(codes["poster-column-spread"], "hard")

    def test_a_small_spread_is_only_soft(self):
        pdf = _poster_pdf(
            self.root / "slightly-ragged.pdf",
            bottoms_pt=[2000.0, 2000.0, 1997.0],
            footer_baseline_pt=2075.0,
        )

        reading = module.measure(pdf)

        self.assertGreater(reading["spread_px"], module.SPREAD_OK_PX)
        self.assertLess(reading["spread_px"], module.SPREAD_FAIL_PX)
        codes = {item["code"]: item["severity"] for item in module.findings(reading)}
        self.assertEqual(codes["poster-column-spread-tight"], "soft")

    def test_a_close_footer_reads_as_a_healthy_gap(self):
        pdf = _poster_pdf(
            self.root / "healthy.pdf",
            bottoms_pt=[2000.0, 2000.0, 2000.0],
            # The text block starts above the baseline, so the baseline sits a
            # little lower than the gap alone would suggest.
            footer_baseline_pt=2075.0,
        )

        reading = module.measure(pdf)

        self.assertGreaterEqual(
            reading["gap_to_footer_px"],
            module.GAP_TARGET_PX[0],
        )
        self.assertLessEqual(
            reading["gap_to_footer_px"],
            module.GAP_TARGET_PX[1],
        )
        self.assertEqual(module.findings(reading), [])

    def test_a_distant_footer_is_a_hard_failure(self):
        pdf = _poster_pdf(
            self.root / "gap.pdf",
            bottoms_pt=[1800.0, 1800.0, 1800.0],
            footer_baseline_pt=2400.0,
        )

        reading = module.measure(pdf)

        self.assertGreater(
            reading["gap_to_footer_px"],
            module.GAP_HARD_PX[1],
        )
        codes = {item["code"]: item["severity"] for item in module.findings(reading)}
        self.assertEqual(codes["poster-footer-gap"], "hard")
        self.assertEqual(codes["poster-canvas-fill"], "soft")

    def test_a_poster_without_cards_is_an_error(self):
        document = fitz.open()
        page = document.new_page(width=4320, height=2592)
        page.insert_text(fitz.Point(100, 100), "empty", fontsize=40)
        path = self.root / "empty.pdf"
        document.save(str(path))
        document.close()

        with self.assertRaisesRegex(ValueError, "没有找到卡片"):
            module.measure(path)

    def test_check_splits_hard_from_soft(self):
        pdf = _poster_pdf(
            self.root / "hard.pdf",
            bottoms_pt=[2000.0, 1900.0, 2000.0],
            footer_baseline_pt=2300.0,
        )

        problems, advisories = module.check(pdf)

        self.assertIn(
            "poster-column-spread",
            [problem.code for problem in problems],
        )
        self.assertIn(
            "poster-canvas-fill",
            [advisory.code for advisory in advisories],
        )

    def test_a_missing_pdf_is_reported(self):
        problems, advisories = module.check(self.root / "nope.pdf")

        self.assertEqual(advisories, [])
        self.assertEqual(
            [problem.code for problem in problems],
            ["poster-measure-failed"],
        )


class PosterMeasureCliTests(unittest.TestCase):
    def test_measure_prints_the_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = _poster_pdf(
                Path(tmp) / "poster.pdf",
                bottoms_pt=[2000.0, 2000.0, 2000.0],
                footer_baseline_pt=2060.0,
            )

            code = module.main(["poster-measure", "measure", "--pdf", str(pdf)])
            check_code = module.main(["poster-measure", "check", "--pdf", str(pdf)])

        self.assertEqual(code, 0)
        self.assertEqual(check_code, 0)


if __name__ == "__main__":
    unittest.main()
