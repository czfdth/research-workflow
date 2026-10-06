"""Editable PPTX export from the talk plan."""

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import yaml
from pptx import Presentation
from pptx.util import Inches

from ccfa import pptx_export as module


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _png_bytes(width: int, height: int) -> bytes:
    """A real PNG: python-pptx decodes images, so a fake header is not enough."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x20\x40\x60" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _plan(**overrides):
    payload = {
        "version": 1,
        "status": "polished",
        "venue": "ICML",
        "title": "Memory Poisoning",
        "authors": "A. Author",
        "institute": "Lab",
        "date": "2026",
        "format": {
            "width_in": 13.333,
            "height_in": 7.5,
            "margin_in": 0.6,
            "title_pt": 28,
            "body_pt": 20,
            "line_spacing": 1.35,
        },
        "slides": [
            {
                "id": "s1",
                "title": "Motivation",
                "claim_ids": ["c1"],
                "figure_ids": [],
                "talking_points": ["RAG is everywhere"],
                "speaker_notes": "Open with the problem.",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _write_plan(root: Path, payload) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "talk-plan.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _texts(presentation) -> str:
    return "\n".join(
        shape.text_frame.text
        for slide in presentation.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )


class CanvasTests(unittest.TestCase):
    def test_a_slide_sized_plan_keeps_its_canvas(self):
        width, height, source = module.canvas_for(_plan()["format"])

        self.assertEqual((width, height), (13.333, 7.5))
        self.assertEqual(source, "declared")

    def test_a_beamer_page_size_maps_onto_the_standard_16_9(self):
        fmt = dict(_plan()["format"], width_in=6.2992, height_in=3.5433)

        width, height, source = module.canvas_for(fmt)

        self.assertEqual((width, height), (13.333, 7.5))
        self.assertEqual(source, "standard-169")

    def test_a_four_three_plan_maps_onto_the_standard_4_3(self):
        fmt = dict(_plan()["format"], width_in=6.4, height_in=4.8)

        width, height, source = module.canvas_for(fmt)

        self.assertEqual((width, height), (10.0, 7.5))
        self.assertEqual(source, "standard-43")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "figures").mkdir()

    def test_the_deck_has_a_title_content_and_closing_slide(self):
        _write_plan(self.root, _plan())

        result = module.export(self.root)
        presentation = Presentation(result["pptx"])

        # Title + one content slide + thank-you.
        self.assertEqual(len(presentation.slides), 3)
        self.assertEqual(result["slides"], 3)
        self.assertIn("Memory Poisoning", _texts(presentation))
        self.assertIn("Motivation", _texts(presentation))
        self.assertIn("RAG is everywhere", _texts(presentation))
        self.assertIn("Thank You", _texts(presentation))

    def test_the_canvas_is_written_into_the_deck(self):
        _write_plan(self.root, _plan())

        result = module.export(self.root)
        presentation = Presentation(result["pptx"])

        self.assertEqual(presentation.slide_width, Inches(13.333))
        self.assertEqual(presentation.slide_height, Inches(7.5))

    def test_speaker_notes_land_in_the_notes_field(self):
        _write_plan(self.root, _plan())

        result = module.export(self.root)
        presentation = Presentation(result["pptx"])
        notes = presentation.slides[1].notes_slide.notes_text_frame.text

        self.assertEqual(notes, "Open with the problem.")
        self.assertEqual(result["notes"], 1)

    def test_a_figure_is_embedded(self):
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.png").write_bytes(_png_bytes(400, 300))
        _write_plan(
            self.root,
            _plan(
                slides=[
                    {
                        "id": "s1",
                        "title": "Method",
                        "claim_ids": ["c1"],
                        "figure_ids": ["fig1"],
                        "talking_points": ["overview"],
                        "speaker_notes": "walk it",
                    }
                ]
            ),
        )

        result = module.export(self.root)
        presentation = Presentation(result["pptx"])

        self.assertEqual(result["figures"], ["fig1"])
        pictures = [
            shape
            for slide in presentation.slides
            for shape in slide.shapes
            if shape.shape_type == 13  # PICTURE
        ]
        self.assertEqual(len(pictures), 1)

    def test_a_tall_figure_stays_inside_the_slide(self):
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.png\n",
            encoding="utf-8",
        )
        # A portrait figure: sizing by width alone would run off the slide.
        (self.root / "figures" / "fig1.png").write_bytes(_png_bytes(400, 1200))
        _write_plan(
            self.root,
            _plan(
                slides=[
                    {
                        "id": "s1",
                        "title": "Method",
                        "claim_ids": ["c1"],
                        "figure_ids": ["fig1"],
                        "talking_points": ["overview"],
                        "speaker_notes": "walk it",
                    }
                ]
            ),
        )

        result = module.export(self.root)
        presentation = Presentation(result["pptx"])
        picture = next(
            shape
            for slide in presentation.slides
            for shape in slide.shapes
            if shape.shape_type == 13
        )

        self.assertLessEqual(
            picture.top + picture.height,
            presentation.slide_height,
        )

    def test_a_non_image_figure_is_reported_and_skipped(self):
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.svg\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.svg").write_text("<svg/>", encoding="utf-8")
        _write_plan(
            self.root,
            _plan(
                slides=[
                    {
                        "id": "s1",
                        "title": "M",
                        "claim_ids": ["c1"],
                        "figure_ids": ["fig1"],
                        "talking_points": ["x"],
                        "speaker_notes": "y",
                    }
                ]
            ),
        )

        result = module.export(self.root)

        self.assertEqual(result["figures"], [])
        self.assertTrue(any("svg" in item for item in result["findings"]))

    def test_an_unknown_venue_falls_back_and_says_so(self):
        _write_plan(self.root, _plan(venue="SIGBOVIK"))

        result = module.export(self.root)

        self.assertEqual(result["venue"], "generic")
        self.assertEqual(len(result["findings"]), 1)

    def test_type_sizes_scale_with_the_canvas(self):
        _write_plan(
            self.root,
            _plan(
                format={
                    "width_in": 6.2992,
                    "height_in": 3.5433,
                    "margin_in": 0.25,
                    "title_pt": 20,
                    "body_pt": 14,
                    "line_spacing": 1.3,
                }
            ),
        )

        result = module.export(self.root)

        # 13.333 / 6.2992 is about 2.12.
        self.assertAlmostEqual(result["type_scale"], 2.1166, places=3)
        self.assertAlmostEqual(result["type_pt"][0], 42.3, places=1)
        self.assertAlmostEqual(result["type_pt"][1], 29.6, places=1)

    def test_the_same_plan_yields_the_same_slides(self):
        _write_plan(self.root, _plan())

        first = module.export(self.root, output=self.root / "a.pptx")
        second = module.export(self.root, output=self.root / "b.pptx")
        first_text = _texts(Presentation(first["pptx"]))
        second_text = _texts(Presentation(second["pptx"]))

        self.assertEqual(first_text, second_text)
        self.assertEqual(first["slides"], second["slides"])


class PptxCliTests(unittest.TestCase):
    def test_export_writes_a_deck(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "figures").mkdir()
            _write_plan(root, _plan())
            out = root / "deck.pptx"

            code = module.main(
                [
                    "pptx-export",
                    "export",
                    "--paper-root",
                    str(root),
                    "--out",
                    str(out),
                ]
            )
            written = out.is_file()

        self.assertEqual(code, 0)
        self.assertTrue(written)


if __name__ == "__main__":
    unittest.main()
