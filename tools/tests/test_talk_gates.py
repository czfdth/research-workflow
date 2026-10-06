"""Canonical gate orchestration for talk and poster artefacts."""

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import fitz
import yaml

from ccfa import talk_gates as module


def _slide(**overrides):
    slide = {
        "id": "s1",
        "title": "Intro",
        "claim_ids": ["c1"],
        "figure_ids": [],
        "talking_points": ["first point", "second point"],
        "speaker_notes": "spoken notes for this slide",
    }
    slide.update(overrides)
    return slide


def _plan(**overrides):
    payload = {
        "version": 1,
        "status": "draft",
        "slides": [_slide()],
    }
    payload.update(overrides)
    return payload


def _write_pdf(path: Path, *, width_pt=960, height_pt=540, pages=1):
    document = fitz.open()
    for _ in range(pages):
        document.new_page(width=width_pt, height=height_pt)
    document.save(str(path))
    document.close()
    return path


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _png_bytes(width: int, height: int) -> bytes:
    """A real, minimal RGB PNG so header parsing is exercised for real."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(
        b"\x00" + b"\xff\x00\x00" * width for _ in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


class FormatTests(unittest.TestCase):
    def test_defaults_are_16_9(self):
        fmt, findings = module.parse_format({})

        self.assertEqual(findings, [])
        self.assertAlmostEqual(fmt["width_in"], 13.333)
        self.assertAlmostEqual(fmt["height_in"], 7.5)

    def test_bad_numbers_are_reported_not_guessed(self):
        _fmt, findings = module.parse_format(
            {"format": {"title_pt": "big", "margin_in": -1}}
        )

        self.assertEqual(len(findings), 2)
        self.assertTrue(all(item["code"] == "talk-format-invalid" for item in findings))

    def test_a_margin_that_eats_the_canvas_is_rejected(self):
        _fmt, findings = module.parse_format(
            {"format": {"width_in": 2, "margin_in": 1.5}}
        )

        self.assertEqual(findings[0]["where"], "format.margin_in")


class WrappingTests(unittest.TestCase):
    def test_cjk_needs_more_lines_than_ascii_for_the_same_count(self):
        ascii_lines = module._wrapped_lines("abcde", 18.0, 1.0)
        cjk_lines = module._wrapped_lines("中文中文中", 18.0, 1.0)

        self.assertEqual(ascii_lines, 1)
        self.assertGreater(cjk_lines, ascii_lines)

    def test_empty_text_still_occupies_one_line(self):
        self.assertEqual(module._wrapped_lines("", 18.0, 1.0), 1)


class MeasureTests(unittest.TestCase):
    def test_a_short_slide_fits_comfortably(self):
        reading = module._measure_slide(_slide(), module.DEFAULT_FORMAT)

        self.assertLess(reading["fill"], 0.5)
        self.assertEqual(reading["slide"], "s1")

    def test_a_fifteen_line_slide_is_flagged_tight(self):
        slide = _slide(talking_points=[f"point {i}" for i in range(15)])

        reading = module._measure_slide(slide, module.DEFAULT_FORMAT)

        self.assertGreater(reading["fill"], module.MEASURE_WARN_FILL)
        self.assertLessEqual(reading["fill"], 1.0)

    def test_a_twenty_five_line_slide_overflows(self):
        slide = _slide(talking_points=[f"point {i}" for i in range(25)])

        reading = module._measure_slide(slide, module.DEFAULT_FORMAT)

        self.assertGreater(reading["fill"], 1.0)


class GateTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_preflight_flags_a_duplicate_id_and_a_placeholder(self):
        plan = _plan(
            slides=[
                _slide(id="dup"),
                _slide(id="dup", title="TODO: write me"),
            ]
        )

        findings = module.gate_preflight(self.root, plan, deck=None)

        codes = {item["code"] for item in findings}
        self.assertIn("talk-slide-duplicate-id", codes)
        self.assertIn("talk-placeholder", codes)

    def test_preflight_reads_the_deck_source_when_given_one(self):
        deck = self.root / "talk.tex"
        deck.write_text("Intro\nTBD: add the method slide\n", encoding="utf-8")

        findings = module.gate_preflight(self.root, _plan(), deck=deck)

        self.assertEqual(
            [item["code"] for item in findings],
            ["talk-deck-placeholder"],
        )

    def test_preflight_reports_a_missing_deck(self):
        findings = module.gate_preflight(
            self.root,
            _plan(),
            deck=self.root / "nope.tex",
        )

        self.assertEqual(findings[0]["code"], "talk-deck-missing")

    def test_asset_flags_an_unregistered_figure(self):
        (self.root / "figures").mkdir()
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.png").write_bytes(_png_bytes(400, 300))
        plan = _plan(slides=[_slide(figure_ids=["fig1", "ghost"])])

        findings = module.gate_asset(self.root, plan)

        self.assertEqual(
            [item["code"] for item in findings],
            ["talk-figure-unregistered"],
        )

    def test_asset_flags_a_registered_but_missing_or_empty_file(self):
        (self.root / "figures").mkdir()
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n"
            "  - id: missing\n    name: missing\n    file: figures/missing.png\n"
            "  - id: empty\n    name: empty\n    file: figures/empty.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "empty.png").write_bytes(b"x" * 10)
        plan = _plan(slides=[_slide(figure_ids=["missing", "empty"])])

        findings = module.gate_asset(self.root, plan)

        self.assertEqual(
            sorted(item["code"] for item in findings),
            ["talk-figure-empty", "talk-figure-missing"],
        )

    def test_asset_accepts_a_real_figure(self):
        (self.root / "figures").mkdir()
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.png").write_bytes(_png_bytes(400, 300))
        plan = _plan(slides=[_slide(figure_ids=["fig1"])])

        self.assertEqual(module.gate_asset(self.root, plan), [])

    def test_asset_flags_a_low_resolution_figure(self):
        (self.root / "figures").mkdir()
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.png").write_bytes(_png_bytes(32, 32))
        plan = _plan(slides=[_slide(figure_ids=["fig1"])])

        findings = module.gate_asset(self.root, plan)

        self.assertEqual(
            [item["code"] for item in findings],
            ["talk-figure-low-resolution"],
        )

    def test_asset_flags_a_file_that_is_not_an_image(self):
        (self.root / "figures").mkdir()
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.png").write_text(
            "not an image at all" * 10,
            encoding="utf-8",
        )
        plan = _plan(slides=[_slide(figure_ids=["fig1"])])

        findings = module.gate_asset(self.root, plan)

        self.assertEqual(
            [item["code"] for item in findings],
            ["talk-figure-unknown-format"],
        )

    def test_a_svg_figure_skips_the_pixel_checks(self):
        (self.root / "figures").mkdir()
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.svg\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<rect width="10" height="10"/></svg>',
            encoding="utf-8",
        )
        plan = _plan(slides=[_slide(figure_ids=["fig1"])])

        self.assertEqual(module.gate_asset(self.root, plan), [])

    def test_measure_reports_overflow_as_an_error(self):
        plan = _plan(
            slides=[_slide(talking_points=[f"point {i}" for i in range(25)])]
        )

        errors, warnings, measurements = module.gate_measure(self.root, plan)

        self.assertEqual(
            [item["code"] for item in errors],
            ["talk-slide-overflow"],
        )
        self.assertEqual(warnings, [])
        self.assertEqual(len(measurements), 1)
        self.assertGreater(measurements[0]["fill"], 1.0)

    def test_measure_reports_a_tight_slide_as_a_warning(self):
        plan = _plan(
            slides=[_slide(talking_points=[f"point {i}" for i in range(15)])]
        )

        errors, warnings, _measurements = module.gate_measure(self.root, plan)

        self.assertEqual(errors, [])
        self.assertEqual([item["code"] for item in warnings], ["talk-slide-tight"])

    def test_polish_is_advisory(self):
        plan = _plan(
            slides=[
                _slide(
                    title="T" * 70,
                    talking_points=[f"p{i}" for i in range(8)],
                    speaker_notes="hi",
                )
            ]
        )

        codes = {item["code"] for item in module.gate_polish(plan)}

        self.assertIn("talk-too-many-bullets", codes)
        self.assertIn("talk-title-long", codes)
        self.assertIn("talk-notes-thin", codes)


class RunGatesTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()

    def _write_plan(self, payload):
        (self.root / "data" / "talk-plan.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def test_the_report_runs_the_canonical_order(self):
        self._write_plan(_plan())

        report = module.run_gates(self.root)

        self.assertEqual(
            [gate["name"] for gate in report["gates"]],
            list(module.CANONICAL_ORDER),
        )
        self.assertEqual(report["overall"], "pass")
        self.assertEqual(report["hard_failures"], 0)
        self.assertEqual(report["not_implemented_gates"], ["style"])
        self.assertEqual(report["slides"], 1)

    def test_a_hard_gate_failure_fails_the_run(self):
        self._write_plan(
            _plan(slides=[_slide(talking_points=[f"p{i}" for i in range(25)])])
        )

        report = module.run_gates(self.root)

        self.assertEqual(report["overall"], "fail")
        self.assertEqual(report["hard_failures"], 1)
        measure = next(g for g in report["gates"] if g["name"] == "measure")
        self.assertEqual(measure["status"], "fail")

    def test_polish_warnings_do_not_fail_by_default(self):
        self._write_plan(
            _plan(slides=[_slide(talking_points=[f"p{i}" for i in range(8)])])
        )

        report = module.run_gates(self.root)

        polish = next(g for g in report["gates"] if g["name"] == "polish")
        self.assertEqual(polish["status"], "warn")
        self.assertEqual(report["overall"], "pass")
        # Eight bullets trips both the bullet ceiling and the text-only rule.
        self.assertEqual(report["warnings"], 2)

    def test_strict_polish_promotes_warnings_to_hard_failures(self):
        self._write_plan(
            _plan(slides=[_slide(talking_points=[f"p{i}" for i in range(8)])])
        )

        report = module.run_gates(self.root, strict_polish=True)

        polish = next(g for g in report["gates"] if g["name"] == "polish")
        self.assertEqual(polish["severity"], "hard")
        self.assertEqual(polish["status"], "fail")
        self.assertEqual(report["overall"], "fail")

    def test_fail_fast_stops_after_the_first_failing_gate(self):
        self._write_plan(
            _plan(slides=[_slide(title="TODO write me")])
        )

        report = module.run_gates(self.root, fail_fast=True)

        statuses = {gate["name"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(statuses["preflight"], "fail")
        self.assertEqual(statuses["asset"], "skipped")
        self.assertEqual(statuses["measure"], "skipped")

    def test_the_report_is_written_to_disk(self):
        self._write_plan(_plan())

        report = module.run_gates(self.root)
        path = module.write_report(self.root, report)

        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["skill"], "talk-gates")
        self.assertEqual(payload["overall"], "pass")

    def test_a_missing_plan_is_an_error_not_a_pass(self):
        with self.assertRaisesRegex(ValueError, "没有 talk plan"):
            module.run_gates(self.root)


class VerifyFinalTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_a_matching_deck_passes(self):
        pdf = _write_pdf(self.root / "deck.pdf", pages=5)

        findings, detail = module.verify_final(
            pdf,
            expected_canvas=(13.333, 7.5),
            expected_pages=5,
        )

        self.assertEqual(findings, [])
        self.assertEqual(detail["pages"], 5)
        self.assertAlmostEqual(detail["actual_in"][0], 13.333, places=2)

    def test_a_wrong_canvas_is_reported(self):
        pdf = _write_pdf(self.root / "four-three.pdf", width_pt=720, height_pt=540)

        findings, _detail = module.verify_final(
            pdf,
            expected_canvas=(13.333, 7.5),
            expected_pages=1,
        )

        self.assertEqual(
            [item["code"] for item in findings],
            ["talk-pdf-canvas-mismatch"],
        )

    def test_a_wrong_page_count_is_reported(self):
        pdf = _write_pdf(self.root / "deck.pdf", pages=3)

        findings, _detail = module.verify_final(
            pdf,
            expected_canvas=(13.333, 7.5),
            expected_pages=1,
        )

        self.assertEqual(
            [item["code"] for item in findings],
            ["talk-pdf-page-count"],
        )

    def test_an_oversized_file_is_reported(self):
        pdf = _write_pdf(self.root / "deck.pdf")

        findings, _detail = module.verify_final(
            pdf,
            expected_canvas=(13.333, 7.5),
            expected_pages=1,
            max_size_mb=0.000001,
        )

        self.assertEqual(
            [item["code"] for item in findings],
            ["talk-pdf-too-large"],
        )

    def test_the_library_fallback_reads_the_same_numbers(self):
        pdf = _write_pdf(self.root / "deck.pdf", pages=2)
        original = module._pdfinfo
        module._pdfinfo = lambda _path: (_ for _ in ()).throw(
            module.PdfInfoMissing("no poppler")
        )
        self.addCleanup(setattr, module, "_pdfinfo", original)

        findings, detail = module.verify_final(
            pdf,
            expected_canvas=(13.333, 7.5),
            expected_pages=2,
        )

        self.assertEqual(findings, [])
        self.assertEqual(detail["engine"], "pymupdf")

    def test_a_missing_pdf_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "PDF 不存在"):
            module.verify_final(
                self.root / "nope.pdf",
                expected_canvas=(13.333, 7.5),
                expected_pages=1,
            )


class CanvasTests(unittest.TestCase):
    def test_inches_and_points_are_both_accepted(self):
        self.assertEqual(module._parse_canvas("13.333x7.5in"), (13.333, 7.5))
        self.assertEqual(
            module._parse_canvas("960x540pt"),
            (960 / 72, 540 / 72),
        )

    def test_a_bad_canvas_is_rejected(self):
        for value in ("wide", "0x10in", "10x-1in"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    module._parse_canvas(value)


class TalkGatesCliTests(unittest.TestCase):
    def test_verify_final_requires_a_declared_canvas(self):
        code = module.main(
            [
                "talk-gates",
                "verify-final",
                "--pdf",
                "whatever.pdf",
                "--pages",
                "1",
            ]
        )

        self.assertEqual(code, 2)

    def test_run_writes_a_report_and_returns_one_on_a_hard_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "talk-plan.yaml").write_text(
                yaml.safe_dump(
                    _plan(
                        slides=[
                            _slide(
                                talking_points=[
                                    f"p{i}" for i in range(25)
                                ]
                            )
                        ]
                    ),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )

            code = module.main(
                ["talk-gates", "run", "--paper-root", str(root)]
            )

            self.assertEqual(code, 1)
            self.assertTrue((root / module.REPORT).is_file())


if __name__ == "__main__":
    unittest.main()
