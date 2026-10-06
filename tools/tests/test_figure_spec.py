"""Deterministic JSON/YAML -> SVG rendering."""

import re
import tempfile
import unittest
from pathlib import Path

from ccfa import figure_spec as module

ROOT = Path(__file__).resolve().parents[2]


def _spec(**overrides):
    payload = {
        "version": 1,
        "nodes": [
            {"id": "a", "label": "input"},
            {"id": "b", "label": "process"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    payload.update(overrides)
    return payload


class TextWidthTests(unittest.TestCase):
    def test_cjk_glyphs_are_wider_than_ascii(self):
        ascii_width = module.text_width("abcd")
        cjk_width = module.text_width("中文")

        self.assertAlmostEqual(ascii_width, 4 * module.FONT_SIZE * 0.6)
        self.assertAlmostEqual(cjk_width, 2 * module.FONT_SIZE)

    def test_combining_marks_do_not_add_width(self):
        self.assertAlmostEqual(
            module.text_width("e\u0301"),
            module.text_width("e"),
        )


class ParseSpecTests(unittest.TestCase):
    def test_version_must_match(self):
        with self.assertRaisesRegex(ValueError, "version"):
            module.parse_spec({"version": 2, "nodes": [{"id": "a"}]})

    def test_duplicate_node_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "id 重复"):
            module.parse_spec(
                {
                    "version": 1,
                    "nodes": [{"id": "a"}, {"id": "a"}],
                }
            )

    def test_unknown_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "shape 非法"):
            module.parse_spec(
                {
                    "version": 1,
                    "nodes": [{"id": "a", "shape": "hexagon"}],
                }
            )

    def test_an_edge_to_a_missing_node_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不存在的节点"):
            module.parse_spec(
                {
                    "version": 1,
                    "nodes": [{"id": "a"}],
                    "edges": [{"from": "a", "to": "ghost"}],
                }
            )

    def test_arrow_must_be_a_boolean(self):
        with self.assertRaisesRegex(ValueError, "arrow"):
            module.parse_spec(
                {
                    "version": 1,
                    "nodes": [{"id": "a"}, {"id": "b"}],
                    "edges": [{"from": "a", "to": "b", "arrow": "yes"}],
                }
            )

    def test_size_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "size.width"):
            module.parse_spec(
                {
                    "version": 1,
                    "nodes": [{"id": "a"}],
                    "size": {"width": 0, "height": 100},
                }
            )

    def test_a_group_must_reference_real_nodes(self):
        with self.assertRaisesRegex(ValueError, "不存在的节点"):
            module.parse_spec(
                {
                    "version": 1,
                    "nodes": [{"id": "a"}],
                    "groups": [{"id": "g", "nodes": ["ghost"]}],
                }
            )


class BoundaryTests(unittest.TestCase):
    def _box(self, shape, width=100.0, height=50.0):
        return {
            "x": 0.0,
            "y": 0.0,
            "width": width,
            "height": height,
            "node": {"shape": shape},
        }

    def test_box_edge_stops_on_the_rectangle(self):
        x, y = module._boundary_point("box", self._box("box"), 1000.0, 25.0)

        # The box spans x 0..100, y 0..50, so a rightward ray exits at x=100.
        self.assertAlmostEqual(x, 100.0)
        self.assertAlmostEqual(y, 25.0)

    def test_ellipse_edge_stops_on_the_ellipse(self):
        x, y = module._boundary_point(
            "ellipse",
            self._box("ellipse"),
            1000.0,
            25.0,
        )

        # Rightward from the centre, an ellipse exits on its right vertex.
        self.assertAlmostEqual(x, 100.0, places=6)
        self.assertAlmostEqual(y, 25.0, places=6)

    def test_diamond_edge_stops_on_the_diamond(self):
        x, y = module._boundary_point(
            "diamond",
            self._box("diamond"),
            1000.0,
            25.0,
        )

        # Same for a diamond: the right vertex sits at x=100.
        self.assertAlmostEqual(x, 100.0, places=6)
        self.assertAlmostEqual(y, 25.0, places=6)

    def test_a_diagonal_edge_leaves_the_centre_untouched(self):
        x, y = module._boundary_point("box", self._box("box"), 100.0, 100.0)

        self.assertNotAlmostEqual(x, 50.0)
        self.assertNotAlmostEqual(y, 25.0)
        # A box exit lies on an edge, so one normalised axis hits 1 and the
        # other cannot exceed it.
        ratios = (abs(x - 50) / 50, abs(y - 25) / 25)
        self.assertAlmostEqual(max(ratios), 1.0, places=6)
        self.assertLessEqual(min(ratios), 1.0)

    def test_the_segment_box_test_matches_geometry(self):
        box = {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0}

        self.assertTrue(module._segment_hits_box(0, 20, 100, 20, box))
        self.assertFalse(module._segment_hits_box(0, 0, 100, 0, box))


class RenderTests(unittest.TestCase):
    def test_rendering_is_byte_stable(self):
        first, _warnings = module.render(_spec())
        second, _warnings = module.render(_spec())

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("<svg "))
        self.assertTrue(first.endswith("</svg>\n"))

    def test_edges_are_trimmed_to_the_node_boundary(self):
        svg, _warnings = module.render(_spec())
        line = re.search(r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', svg)
        self.assertIsNotNone(line)
        x1, y1, x2, y2 = (float(value) for value in line.groups())

        placed = module._layout(
            module.parse_spec(_spec())["nodes"],
            module.parse_spec(_spec())["edges"],
        )
        source = placed["a"]
        target = placed["b"]
        self.assertLess(x1, x2)
        # The start sits on a's right border, not at its centre.
        self.assertAlmostEqual(x1, source["x"] + source["width"], places=6)
        self.assertAlmostEqual(y1, source["y"] + source["height"] / 2, places=6)
        self.assertAlmostEqual(x2, target["x"], places=6)

    def test_a_self_loop_draws_a_path_not_a_line(self):
        svg, _warnings = module.render(
            {
                "version": 1,
                "nodes": [{"id": "a", "label": "retry"}],
                "edges": [{"from": "a", "to": "a", "label": "again"}],
            }
        )

        self.assertNotIn("<line", svg)
        self.assertIn("<path", svg)
        self.assertIn("marker-end=", svg)

    def test_a_cjk_label_gets_a_box_wide_enough_for_it(self):
        svg, warnings = module.render(
            {
                "version": 1,
                "nodes": [{"id": "a", "label": "中文标签"}],
            }
        )

        self.assertEqual(warnings, [])
        width = float(
            re.search(r'<rect x="[\d.]+" y="[\d.]+" width="([\d.]+)"', svg).group(1)
        )
        self.assertGreater(width, module.text_width("中文标签"))

    def test_multi_line_labels_stack(self):
        svg, _warnings = module.render(
            {
                "version": 1,
                "nodes": [{"id": "a", "label": "first\nsecond"}],
            }
        )

        self.assertIn(">first</text>", svg)
        self.assertIn(">second</text>", svg)

    def test_layout_ranks_nodes_along_the_edge_direction(self):
        payload = {
            "version": 1,
            # Deliberately out of edge order: the rank, not the listing, decides.
            "nodes": [{"id": "c"}, {"id": "a"}, {"id": "b"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        }
        parsed = module.parse_spec(payload)

        placed = module._layout(parsed["nodes"], parsed["edges"])

        self.assertLess(placed["a"]["x"], placed["b"]["x"])
        self.assertLess(placed["b"]["x"], placed["c"]["x"])
        _svg, _warnings = module.render(payload)

    def test_explicit_coordinates_are_kept(self):
        placed = module._layout(
            module.parse_spec(
                {
                    "version": 1,
                    "nodes": [{"id": "a", "x": 321, "y": 123}],
                }
            )["nodes"],
            [],
        )

        self.assertEqual(placed["a"]["x"], 321.0)
        self.assertEqual(placed["a"]["y"], 123.0)

    def test_a_group_draws_a_frame_behind_its_members(self):
        svg, _warnings = module.render(
            {
                "version": 1,
                "nodes": [{"id": "a"}, {"id": "b"}],
                "groups": [
                    {"id": "g", "label": "phase 1", "nodes": ["a", "b"]}
                ],
            }
        )

        self.assertIn("stroke-dasharray=\"4 3\"", svg)
        self.assertIn(">phase 1</text>", svg)
        # The frame is emitted before the node fills so it stays behind them.
        self.assertLess(svg.index('stroke-dasharray="4 3"'), svg.index('fill="#ffffff"'))

    def test_special_characters_are_escaped(self):
        svg, _warnings = module.render(
            {
                "version": 1,
                "nodes": [{"id": "a", "label": "a<b & c"}],
            }
        )

        self.assertIn("a&lt;b &amp; c", svg)
        self.assertNotIn("a<b & c", svg)

    def test_explicit_canvas_size_is_used(self):
        svg, _warnings = module.render(
            _spec(size={"width": 900, "height": 640})
        )

        self.assertIn('width="900"', svg)
        self.assertIn('height="640"', svg)
        self.assertIn('viewBox="0 0 900 640"', svg)

    def test_a_too_small_node_reports_an_overflow_warning(self):
        _svg, warnings = module.render(
            {
                "version": 1,
                "nodes": [{"id": "a", "label": "很长的标签", "width": 20}],
            }
        )

        self.assertEqual(len(warnings), 1)
        self.assertIn("超过给定 width", warnings[0])

    def test_an_edge_through_an_unrelated_node_is_bowed_around_it(self):
        svg, _warnings = module.render(
            {
                "version": 1,
                "nodes": [
                    {"id": "a", "x": 0, "y": 0},
                    {"id": "b", "x": 300, "y": 0},
                    {"id": "c", "x": 600, "y": 0},
                ],
                "edges": [{"from": "a", "to": "c"}],
            }
        )

        self.assertNotIn("<line", svg)
        self.assertIn("<path", svg)
        self.assertIn('Q ', svg)

    def test_an_unobstructed_edge_stays_a_straight_line(self):
        svg, _warnings = module.render(_spec())

        self.assertIn("<line", svg)
        self.assertNotIn('Q ', svg)


class CheckSpecTests(unittest.TestCase):
    def test_check_reports_an_overflow_as_an_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "figure.yaml"
            path.write_text(
                "version: 1\n"
                "nodes:\n"
                "  - id: a\n"
                "    label: 很长的标签\n"
                "    width: 20\n",
                encoding="utf-8",
            )

            problems, advisories = module.check_spec(path)

        self.assertEqual(problems, [])
        self.assertEqual(
            [advisory.code for advisory in advisories],
            ["figure-spec-overflow"],
        )

    def test_check_turns_a_bad_spec_into_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "figure.yaml"
            path.write_text("version: 1\nnodes: []\n", encoding="utf-8")

            problems, advisories = module.check_spec(path)

        self.assertEqual(advisories, [])
        self.assertEqual(
            [problem.code for problem in problems],
            ["figure-spec-invalid"],
        )


class FigureSpecCliTests(unittest.TestCase):
    def test_render_writes_an_svg_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "figure.json"
            spec.write_text(
                '{"version": 1, "nodes": [{"id": "a", "label": "x"}]}',
                encoding="utf-8",
            )
            out = Path(tmp) / "figure.svg"

            code = module.main(
                [
                    "figure-spec",
                    "render",
                    "--spec",
                    str(spec),
                    "--out",
                    str(out),
                ]
            )

            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertTrue(out.read_text(encoding="utf-8").startswith("<svg "))

    def test_check_exits_one_on_an_invalid_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "figure.json"
            spec.write_text('{"version": 9}', encoding="utf-8")

            code = module.main(
                ["figure-spec", "check", "--spec", str(spec)]
            )

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
