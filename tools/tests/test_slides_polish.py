"""Layout-only Beamer polish with versioned, content-preserving output."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz

from ccfa import slides_polish as module

TEX = """\\documentclass[aspectratio=169,20pt]{beamer}
\\usepackage{graphicx}
\\setbeamerfont{normal text}{size=\\fontsize{10}{12}\\selectfont}
\\begin{document}
\\begin{frame}{Intro}
\\includegraphics[width=0.85\\textwidth]{fig.png}
\\end{frame}
\\begin{frame}{Bounded}
\\includegraphics[width=0.5\\textwidth,height=0.4\\textheight,keepaspectratio]{ok.png}
\\end{frame}
\\end{document}
"""


def _write_pdf(path: Path, pages: int = 2) -> None:
    document = fitz.open()
    for _ in range(pages):
        document.new_page(width=960, height=540)
    document.save(str(path))
    document.close()


class InspectTests(unittest.TestCase):
    def test_inventory_reports_frames_includes_and_fonts(self):
        inventory = module.inspect(TEX)

        self.assertEqual(inventory["frame_count"], 2)
        self.assertEqual(
            [frame["title"] for frame in inventory["frames"]],
            ["Intro", "Bounded"],
        )
        self.assertEqual(len(inventory["includes"]), 2)
        self.assertFalse(inventory["includes"][0]["has_height"])
        self.assertTrue(inventory["includes"][1]["has_height"])
        self.assertEqual(inventory["fonts"][0]["pt"], 10.0)
        self.assertFalse(inventory["has_geometry_pin"])
        self.assertFalse(inventory["hides_navigation_symbols"])


class PolishTextTests(unittest.TestCase):
    def test_a_width_only_include_gets_a_height_bound(self):
        polished, changes, _findings = module.polish_text(TEX)

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["rule"], "figure-height-bound")
        self.assertIn(
            "\\includegraphics[width=0.85\\textwidth,"
            "height=0.6\\textheight,keepaspectratio]{fig.png}",
            polished,
        )
        # The bounded include is left alone.
        self.assertIn(
            "\\includegraphics[width=0.5\\textwidth,height=0.4\\textheight,"
            "keepaspectratio]{ok.png}",
            polished,
        )

    def test_only_the_offending_line_changes(self):
        polished, _changes, _findings = module.polish_text(TEX)

        before = TEX.splitlines()
        after = polished.splitlines()
        self.assertEqual(len(before), len(after))
        differing = [
            index
            for index, (old, new) in enumerate(zip(before, after))
            if old != new
        ]
        # 0-based: the width-only include sits on the sixth line.
        self.assertEqual(differing, [5])

    def test_fonts_and_theme_gaps_are_reported_not_rewritten(self):
        polished, _changes, findings = module.polish_text(TEX)

        rules = {item["rule"] for item in findings}
        self.assertIn("font-below-floor", rules)
        self.assertIn("no-geometry-pin", rules)
        self.assertIn("navigation-symbols", rules)
        # Reported, not silently changed.
        self.assertIn("\\fontsize{10}{12}", polished)


class PolishRunTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.deck = Path(self._temporary.name)
        self.tex = self.deck / "main.tex"
        self.tex.write_text(TEX, encoding="utf-8", newline="\n")

    def test_the_original_is_snapshotted_and_never_overwritten(self):
        first = module.polish(self.deck, render_pages=False)
        snapshot = Path(first["snapshot"])
        self.assertEqual(snapshot.read_text(encoding="utf-8"), TEX)

        # A second, later original must not clobber the first snapshot.
        self.tex.write_text(TEX.replace("Intro", "Renamed"), encoding="utf-8")
        module.polish(self.deck, render_pages=False)

        self.assertEqual(snapshot.read_text(encoding="utf-8"), TEX)

    def test_outputs_are_versioned(self):
        first = module.polish(self.deck, render_pages=False)
        second = module.polish(self.deck, render_pages=False)

        self.assertTrue(Path(first["output"]).name.endswith("_polished.tex"))
        self.assertIn("_v2", Path(second["output"]).name)
        self.assertNotEqual(first["output"], second["output"])

    def test_state_changelog_and_inventory_are_written(self):
        result = module.polish(self.deck, render_pages=False)

        state = json.loads(Path(result["state"]).read_text(encoding="utf-8"))
        self.assertEqual(state["skill"], "slides-polish")
        self.assertEqual(state["changes"], 1)
        self.assertEqual(state["frames"], 2)
        self.assertEqual(state["not_implemented"], ["pptx"])
        changelog = Path(result["changelog"]).read_text(encoding="utf-8")
        self.assertIn("figure-height-bound", changelog)
        self.assertIn("findings（未自动改写）", changelog)
        self.assertTrue(Path(result["inspect"]).is_file())


class CheckTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.deck = Path(self._temporary.name)
        self.tex = self.deck / "main.tex"
        self.tex.write_text(TEX, encoding="utf-8", newline="\n")

    def test_a_fresh_polish_passes(self):
        module.polish(self.deck, render_pages=False)

        problems, advisories = module.check(self.deck)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_an_unauthorised_content_change_is_caught(self):
        result = module.polish(self.deck, render_pages=False)
        output = Path(result["output"])
        output.write_text(
            output.read_text(encoding="utf-8").replace("Intro", "Hacked"),
            encoding="utf-8",
        )

        problems, _advisories = module.check(self.deck)

        self.assertEqual(
            [problem.code for problem in problems],
            ["slides-polish-unauthorised-change"],
        )

    def test_an_added_line_is_caught(self):
        result = module.polish(self.deck, render_pages=False)
        output = Path(result["output"])
        output.write_text(
            output.read_text(encoding="utf-8") + "% extra\n",
            encoding="utf-8",
        )

        problems, _advisories = module.check(self.deck)

        self.assertEqual(
            [problem.code for problem in problems],
            ["slides-polish-line-count"],
        )

    def test_check_before_running_is_only_an_advisory(self):
        problems, advisories = module.check(self.deck)

        self.assertEqual(problems, [])
        self.assertEqual(
            [advisory.code for advisory in advisories],
            ["slides-polish-not-run"],
        )


class PageRenderTests(unittest.TestCase):
    def test_pages_are_rendered_and_traced(self):
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp)
            (deck / "main.tex").write_text(TEX, encoding="utf-8", newline="\n")
            _write_pdf(deck / "main.pdf", pages=2)
            # A binary on PATH is not a working renderer: ImageMagick ships a
            # policy that blocks PDF, so probe the real path before asserting.
            if not module._render_pages(deck / "main.pdf", deck / "probe"):
                self.skipTest("no PDF page renderer actually works here")

            result = module.polish(deck)

            self.assertEqual(len(result["pages"]), 2)
            self.assertEqual(result["page_render"], "rendered")
            self.assertTrue(Path(result["pages"][0]["image"]).is_file())
            traces = sorted((deck / module.STATE_DIR / "traces").glob("slide_*.json"))
            self.assertEqual(len(traces), 2)

    def test_an_unavailable_renderer_is_reported_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp)
            (deck / "main.tex").write_text(TEX, encoding="utf-8", newline="\n")
            _write_pdf(deck / "main.pdf", pages=2)
            with mock.patch.object(module, "_render_pages", return_value=[]):
                result = module.polish(deck)

            self.assertEqual(result["pages"], [])
            self.assertEqual(result["page_render"], "unavailable")
            state = json.loads(Path(result["state"]).read_text(encoding="utf-8"))
            self.assertEqual(state["page_render"], "unavailable")
            changelog = Path(result["changelog"]).read_text(encoding="utf-8")
            self.assertIn("逐页像素复核：未完成", changelog)


class SlidesPolishCliTests(unittest.TestCase):
    def test_run_then_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp)
            (deck / "main.tex").write_text(TEX, encoding="utf-8", newline="\n")

            run_code = module.main(
                ["slides-polish", "run", "--deck", str(deck), "--no-render"]
            )
            check_code = module.main(
                ["slides-polish", "check", "--deck", str(deck)]
            )

        self.assertEqual(run_code, 0)
        self.assertEqual(check_code, 0)


if __name__ == "__main__":
    unittest.main()
