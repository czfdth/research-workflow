"""Deterministic Beamer deck generation from a talk plan."""

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import yaml

from ccfa import talk_deck as module
from ccfa import talk_gates

from . import request_latex_engine


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _png_bytes(width: int, height: int) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _slide(**overrides):
    slide = {
        "id": "s1",
        "title": "Motivation",
        "claim_ids": ["c1"],
        "figure_ids": [],
        "talking_points": ["one", "two"],
        "speaker_notes": "explain the motivation",
    }
    slide.update(overrides)
    return slide


def _plan(**overrides):
    payload = {
        "version": 1,
        "status": "polished",
        "title": "A Study",
        "author": "A. Author",
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
        "slides": [_slide()],
    }
    payload.update(overrides)
    return payload


class EscapeTests(unittest.TestCase):
    def test_latex_specials_are_escaped(self):
        self.assertEqual(
            module.escape_latex("100% & $5 #1_2"),
            r"100\% \& \$5 \#1\_2",
        )

    def test_cjk_detection(self):
        self.assertTrue(module.has_cjk("中文标题"))
        self.assertFalse(module.has_cjk("plain ascii"))


class TypographyTests(unittest.TestCase):
    def test_aspect_is_derived_from_the_declared_canvas(self):
        self.assertEqual(module.aspect_ratio_option(_plan()["format"]), "169")
        self.assertEqual(
            module.aspect_ratio_option(
                {"width_in": 10.0, "height_in": 7.5}
            ),
            "43",
        )

    def test_declared_type_sizes_are_used_literally(self):
        fmt = _plan()["format"]

        spec = module.typography(fmt)

        # The page is sized to the plan, so no rescaling is needed.
        self.assertAlmostEqual(spec["title_pt"], 28.0)
        self.assertAlmostEqual(spec["body_pt"], 20.0)
        self.assertEqual(spec["base_size"], 20)

    def test_base_size_never_exceeds_the_requested_body_size(self):
        self.assertEqual(module._base_size(13.0), 12)
        self.assertEqual(module._base_size(6.0), 8)
        self.assertEqual(module._base_size(20.0), 20)


class VenueTests(unittest.TestCase):
    def test_known_venues_use_their_palette(self):
        name, colors, findings = module._venue("NeurIPS")

        self.assertEqual(name, "NeurIPS")
        self.assertEqual(colors, ("8B5CF6", "2563EB"))
        self.assertEqual(findings, [])

    def test_an_unknown_venue_falls_back_and_says_so(self):
        name, colors, findings = module._venue("SIGBOVIK")

        self.assertEqual(name, "GENERIC")
        self.assertEqual(colors, module.VENUE_COLORS["GENERIC"])
        self.assertEqual(len(findings), 1)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        (self.root / "figures").mkdir()
        self._write_plan(_plan())

    def _write_plan(self, payload):
        (self.root / "data" / "talk-plan.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def test_rendering_twice_gives_identical_bytes(self):
        first = module.render_deck(self.root)
        second = module.render_deck(self.root)

        self.assertEqual(first["files"], second["files"])

    def test_the_tex_has_the_venue_theme_and_one_frame_per_slide(self):
        self._write_plan(_plan(slides=[_slide(), _slide(id="s2", title="B")]))

        rendered = module.render_deck(self.root, venue="ICML")
        tex = rendered["files"][module.TEX_NAME]

        self.assertIn("\\definecolor{primary}{HTML}{DC2626}", tex)
        self.assertIn("\\definecolor{accent}{HTML}{1D4ED8}", tex)
        self.assertIn("\\documentclass[aspectratio=169,20pt]{beamer}", tex)
        # The page is pinned to the declared canvas, not Beamer's default 16cm.
        self.assertIn(
            "\\geometry{paperwidth=13.333in,paperheight=7.5in}",
            tex,
        )
        self.assertIn("\\setbeamerfont{normal text}{size=\\fontsize{20}{27}",
                      tex)
        # Title frame + two content frames + thank-you frame.
        self.assertEqual(tex.count("\\begin{frame}"), 4)
        self.assertIn("\\note{explain the motivation}", tex)
        self.assertNotIn("\\usepackage{ctex}", tex)
        self.assertEqual(rendered["state"]["frame_count"], 4)

    def test_cjk_switches_the_engine_and_adds_ctex(self):
        self._write_plan(
            _plan(slides=[_slide(title="中文标题", talking_points=["要点一"])])
        )

        rendered = module.render_deck(self.root)
        tex = rendered["files"][module.TEX_NAME]

        self.assertIn("\\usepackage{ctex}", tex)
        self.assertEqual(rendered["state"]["engine"], "xelatex")
        self.assertTrue(rendered["state"]["cjk"])

    def test_a_figure_is_resolved_copied_and_included(self):
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.png\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.png").write_bytes(_png_bytes(400, 300))
        self._write_plan(_plan(slides=[_slide(figure_ids=["fig1"])]))

        rendered = module.write_deck(self.root)
        tex = rendered["files"][module.TEX_NAME]

        self.assertIn(
            "\\includegraphics[width=0.85\\textwidth,"
            "height=0.6\\textheight,keepaspectratio]{fig1.png}",
            tex,
        )
        self.assertTrue(
            (rendered["output_dir"] / "figures" / "fig1.png").is_file()
        )
        self.assertEqual(rendered["state"]["figures"], {"fig1": "fig1.png"})

    def test_a_vector_figure_is_reported_because_beamer_cannot_embed_it(self):
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n  - id: fig1\n    name: fig1\n    file: figures/fig1.svg\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "fig1.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"/>',
            encoding="utf-8",
        )
        self._write_plan(_plan(slides=[_slide(figure_ids=["fig1"])]))

        rendered = module.render_deck(self.root)

        self.assertEqual(len(rendered["findings"]), 1)
        self.assertIn("Beamer 只能直接包含", rendered["findings"][0])
        self.assertNotIn(
            "includegraphics",
            rendered["files"][module.TEX_NAME],
        )

    def test_a_missing_figure_is_reported_not_ignored(self):
        self._write_plan(_plan(slides=[_slide(figure_ids=["ghost"])]))

        rendered = module.render_deck(self.root)

        self.assertEqual(len(rendered["findings"]), 1)
        self.assertIn("ghost", rendered["findings"][0])
        tex = rendered["files"][module.TEX_NAME]
        self.assertNotIn("includegraphics", tex)

    def test_a_plan_venue_is_used_unless_the_cli_overrides_it(self):
        self._write_plan(_plan(venue="ICML"))

        from_plan = module.render_deck(self.root)
        overridden = module.render_deck(self.root, venue="NeurIPS")

        self.assertEqual(from_plan["state"]["venue"], "ICML")
        self.assertIn(
            "\\definecolor{primary}{HTML}{DC2626}",
            from_plan["files"][module.TEX_NAME],
        )
        self.assertEqual(overridden["state"]["venue"], "NeurIPS")

    def test_the_state_file_records_what_was_not_generated(self):
        rendered = module.render_deck(self.root)

        state = json.loads(rendered["files"][module.STATE_NAME])

        self.assertEqual(state["not_implemented"], ["pptx"])
        self.assertEqual(state["slide_count"], 1)
        self.assertEqual(state["venue"], "GENERIC")

    def test_notes_markdown_lists_every_slide(self):
        self._write_plan(
            _plan(slides=[_slide(), _slide(id="s2", title="Results")])
        )

        rendered = module.render_deck(self.root)
        notes = rendered["files"][module.NOTES_NAME]

        self.assertIn("## 1. Motivation", notes)
        self.assertIn("## 2. Results", notes)
        self.assertIn("explain the motivation", notes)

    def test_write_deck_creates_the_files_on_disk(self):
        rendered = module.write_deck(self.root)

        out = rendered["output_dir"]
        self.assertTrue((out / module.TEX_NAME).is_file())
        self.assertTrue((out / module.NOTES_NAME).is_file())
        self.assertTrue((out / module.STATE_NAME).is_file())


class CompileTests(unittest.TestCase):
    def test_a_missing_engine_is_an_error(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / module.TEX_NAME).write_text("x", encoding="utf-8")

            with mock.patch.object(
                module.subprocess,
                "run",
                side_effect=FileNotFoundError,
            ):
                with self.assertRaisesRegex(ValueError, "未安装"):
                    module.compile_deck(out, engine="pdflatex")

    def test_an_unknown_engine_is_rejected_before_running_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / module.TEX_NAME).write_text("x", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "engine 非法"):
                module.compile_deck(out, engine="rm -rf /")

    def test_a_missing_source_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "没有可编译的"):
                module.compile_deck(Path(tmp))


class RoundTripTests(unittest.TestCase):
    """Generate -> compile -> measure the PDF. Needs a real LaTeX engine."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        (self.root / "figures").mkdir()
        self._write_plan(
            _plan(
                format={
                    "width_in": 6.2992,
                    "height_in": 3.5433,
                    "margin_in": 0.25,
                    "title_pt": 20,
                    "body_pt": 14,
                    "line_spacing": 1.3,
                },
                slides=[
                    _slide(),
                    _slide(id="s2", title="Method", talking_points=["step one"]),
                    _slide(id="s3", title="Results", talking_points=["win"]),
                ],
            )
        )

    def _write_plan(self, payload):
        (self.root / "data" / "talk-plan.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def test_generated_deck_compiles_to_the_expected_frame_count(self):
        request_latex_engine(self)

        rendered = module.write_deck(self.root)
        compiled = module.compile_deck(rendered["output_dir"])
        findings, detail = talk_gates.verify_final(
            Path(compiled["pdf"]),
            expected_canvas=(6.2992, 3.5433),
            expected_pages=rendered["state"]["frame_count"],
        )

        self.assertEqual(findings, [])
        self.assertEqual(detail["pages"], 5)

    def test_the_generated_deck_passes_the_measure_gate(self):
        rendered = module.write_deck(self.root)

        report = talk_gates.run_gates(
            self.root,
            deck=rendered["output_dir"] / module.TEX_NAME,
        )

        self.assertEqual(report["overall"], "pass")
        self.assertFalse(
            [
                gate
                for gate in report["gates"]
                if gate["status"] == "fail"
            ]
        )


if __name__ == "__main__":
    unittest.main()
