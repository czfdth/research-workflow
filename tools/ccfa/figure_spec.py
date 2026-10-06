"""Deterministic JSON/YAML -> SVG renderer for method and pipeline figures.

Figure skills produce good-looking output but are not reproducible: the same
input can come back with different geometry, and nothing in the repository can
re-render a figure without a model. This module is the deterministic half. It
takes a declarative spec and emits SVG bytes; the same spec always yields
byte-identical output, so a figure can be diffed and re-checked like code.

Three details that usually break hand-rolled renderers are handled here:

* **Shape-aware edge trimming.** An edge stops on the node boundary it points
  at (rectangle, ellipse or diamond), not at the node centre, so arrowheads do
  not hide under the shape.
* **Self-loops.** ``from == to`` draws a real loop with its own arrowhead.
* **CJK width.** Text width is measured with ``east_asian_width`` instead of a
  character count, so a Chinese label does not overflow its box.
* **Obstacle-aware edges.** A straight edge that would run through an unrelated
  node is bowed around it, because a line crossing a box reads as a pipeline
  that does not exist. Edges with a clear path stay straight.

Layout is optional: nodes with ``x``/``y`` keep them, and the rest are placed by
a layered (longest-path) rank so a left-to-right pipeline reads in edge order.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error

SPEC_VERSION = 1
SHAPES = ("box", "roundrect", "ellipse", "diamond")
EDGE_STYLES = ("solid", "dashed")
FONT_SIZE = 14.0
LINE_HEIGHT = 18.0
PAD_X = 14.0
PAD_Y = 10.0
MARGIN = 24.0
GAP_X = 72.0
GAP_Y = 32.0
NARROW_RATIO = 0.6
DEFAULT_FILL = "#ffffff"
DEFAULT_STROKE = "#333333"
DEFAULT_TEXT = "#111111"
DEFAULT_EDGE = "#333333"


def _num(value: float) -> str:
    """Format a coordinate without trailing noise, so output stays stable."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def text_width(text: str, size: float = FONT_SIZE) -> float:
    """Approximate advance width; wide/fullwidth glyphs take a full em.

    A character count would look fine for ASCII and be wrong for every Chinese
    label, which is exactly the case a research figure usually hits.
    """
    total = 0.0
    for char in text:
        if unicodedata.combining(char):
            continue
        if char == "\t":
            total += size * NARROW_RATIO * 4
        elif unicodedata.east_asian_width(char) in ("W", "F"):
            total += size
        else:
            total += size * NARROW_RATIO
    return total


def _positive_number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} 必须是数字")
    if value <= 0:
        raise ValueError(f"{where} 必须是正数")
    return float(value)


def _optional_number(value: object, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} 必须是数字")
    return float(value)


def parse_spec(payload: object) -> dict:
    """Validate and normalise a figure spec."""
    if not isinstance(payload, dict):
        raise ValueError("figure spec 顶层必须是对象")
    if payload.get("version") != SPEC_VERSION:
        raise ValueError(
            f"figure spec version 必须是 {SPEC_VERSION}: "
            f"{payload.get('version')!r}"
        )
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("figure spec 需要非空 nodes 列表")
    nodes: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_nodes, start=1):
        where = f"nodes[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        node_id = item.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError(f"{where} 缺少非空 id")
        node_id = node_id.strip()
        if node_id in seen:
            raise ValueError(f"{where} id 重复: {node_id}")
        seen.add(node_id)
        label = item.get("label", node_id)
        if not isinstance(label, str):
            raise ValueError(f"{where} label 必须是字符串")
        shape = item.get("shape", "box")
        if shape not in SHAPES:
            raise ValueError(
                f"{where} shape 非法: {shape!r}，应为 {'/'.join(SHAPES)}"
            )
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "shape": shape,
                "x": _optional_number(item.get("x"), f"{where}.x"),
                "y": _optional_number(item.get("y"), f"{where}.y"),
                "width": _optional_number(item.get("width"), f"{where}.width"),
                "height": _optional_number(
                    item.get("height"), f"{where}.height"
                ),
                "fill": str(item.get("fill") or DEFAULT_FILL),
                "stroke": str(item.get("stroke") or DEFAULT_STROKE),
            }
        )
    raw_edges = payload.get("edges", [])
    if not isinstance(raw_edges, list):
        raise ValueError("figure spec 的 edges 必须是列表")
    edges: list[dict] = []
    for index, item in enumerate(raw_edges, start=1):
        where = f"edges[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        source = item.get("from")
        target = item.get("to")
        for value, name in ((source, "from"), (target, "to")):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{where} 缺少非空 {name}")
            if value.strip() not in seen:
                raise ValueError(f"{where}.{name} 指向不存在的节点: {value!r}")
        label = item.get("label", "")
        if not isinstance(label, str):
            raise ValueError(f"{where} label 必须是字符串")
        style = item.get("style", "solid")
        if style not in EDGE_STYLES:
            raise ValueError(
                f"{where} style 非法: {style!r}，应为 {'/'.join(EDGE_STYLES)}"
            )
        arrow = item.get("arrow", True)
        if not isinstance(arrow, bool):
            raise ValueError(f"{where} arrow 必须是布尔值")
        edges.append(
            {
                "from": source.strip(),
                "to": target.strip(),
                "label": label,
                "style": style,
                "arrow": arrow,
                "color": str(item.get("color") or DEFAULT_EDGE),
            }
        )
    raw_groups = payload.get("groups", [])
    if not isinstance(raw_groups, list):
        raise ValueError("figure spec 的 groups 必须是列表")
    groups: list[dict] = []
    for index, item in enumerate(raw_groups, start=1):
        where = f"groups[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        members = item.get("nodes")
        if not isinstance(members, list) or not members:
            raise ValueError(f"{where} nodes 必须是非空列表")
        for member in members:
            if not isinstance(member, str) or member not in seen:
                raise ValueError(f"{where} 指向不存在的节点: {member!r}")
        groups.append(
            {
                "id": str(item.get("id") or f"group-{index}"),
                "label": str(item.get("label") or ""),
                "nodes": list(members),
                "fill": str(item.get("fill") or "#f4f6f8"),
                "stroke": str(item.get("stroke") or "#9aa5b1"),
            }
        )
    size = payload.get("size")
    canvas: dict = {}
    if size is not None:
        if not isinstance(size, dict):
            raise ValueError("size 必须是对象")
        canvas = {
            "width": _positive_number(size.get("width"), "size.width"),
            "height": _positive_number(size.get("height"), "size.height"),
        }
    return {"nodes": nodes, "edges": edges, "groups": groups, "canvas": canvas}


def load_spec(path: Path) -> object:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 figure spec {path}: {exc}") from exc
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"figure spec 解析失败: {exc}") from exc


def _label_lines(label: str) -> list[str]:
    return label.split("\n") if label else [""]


def _node_box(node: dict) -> tuple[float, float, float, float]:
    """Return (width, height, text_width, text_height) for one node."""
    lines = _label_lines(node["label"])
    text_w = max((text_width(line) for line in lines), default=0.0)
    text_h = LINE_HEIGHT * len(lines)
    width = node["width"] or (text_w + 2 * PAD_X)
    height = node["height"] or (text_h + 2 * PAD_Y)
    if width <= 0 or height <= 0:
        raise ValueError(f"节点 {node['id']!r} 的尺寸退化为 0")
    return width, height, text_w, text_h


def _ranks(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Longest-path layering; the cap is what keeps a cycle from looping."""
    rank = {node["id"]: 0 for node in nodes}
    for _ in range(len(nodes)):
        changed = False
        for edge in edges:
            if edge["from"] == edge["to"]:
                continue
            if rank[edge["to"]] < rank[edge["from"]] + 1:
                rank[edge["to"]] = rank[edge["from"]] + 1
                changed = True
        if not changed:
            break
    return rank


def _layout(nodes: list[dict], edges: list[dict]) -> dict[str, dict]:
    """Place every node, honouring explicit coordinates where given."""
    sized: dict[str, dict] = {}
    for node in nodes:
        width, height, text_w, text_h = _node_box(node)
        sized[node["id"]] = {
            "node": node,
            "width": width,
            "height": height,
            "text_width": text_w,
            "text_height": text_h,
        }
    rank = _ranks(nodes, edges)
    columns: dict[int, list[str]] = {}
    for node in nodes:
        columns.setdefault(rank[node["id"]], []).append(node["id"])
    column_width = {
        position: max(sized[id_]["width"] for id_ in ids)
        for position, ids in columns.items()
    }
    column_height = {
        position: max(sized[id_]["height"] for id_ in ids)
        for position, ids in columns.items()
    }
    column_x: dict[int, float] = {}
    offset = MARGIN
    for position in sorted(columns):
        column_x[position] = offset
        offset += column_width[position] + GAP_X
    placed: dict[str, dict] = {}
    for position in sorted(columns):
        for row, node_id in enumerate(columns[position]):
            entry = sized[node_id]
            x = entry["node"]["x"]
            y = entry["node"]["y"]
            if x is None:
                x = column_x[position]
            if y is None:
                y = MARGIN + row * (column_height[position] + GAP_Y)
            placed[node_id] = {
                "x": float(x),
                "y": float(y),
                "width": entry["width"],
                "height": entry["height"],
                "text_width": entry["text_width"],
                "text_height": entry["text_height"],
                "node": entry["node"],
            }
    return placed


def _boundary_point(
    shape: str,
    box: dict,
    toward_x: float,
    toward_y: float,
) -> tuple[float, float]:
    """Where the ray from the node centre toward (toward_x, toward_y) exits."""
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    dx = toward_x - cx
    dy = toward_y - cy
    if dx == 0 and dy == 0:
        return cx, cy
    half_w = box["width"] / 2
    half_h = box["height"] / 2
    if shape == "ellipse":
        scale = 1.0 / ((dx / half_w) ** 2 + (dy / half_h) ** 2) ** 0.5
    elif shape == "diamond":
        scale = 1.0 / (abs(dx) / half_w + abs(dy) / half_h)
    else:
        ratios = []
        if dx:
            ratios.append(half_w / abs(dx))
        if dy:
            ratios.append(half_h / abs(dy))
        scale = min(ratios)
    return cx + dx * scale, cy + dy * scale


def _segment_hits_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    box: dict,
) -> bool:
    """Liang-Barsky clip test: does the segment touch this node's box?

    A straight edge that runs through an unrelated node reads as a wrong
    pipeline, so the renderer has to notice before it draws.
    """
    left = box["x"]
    top = box["y"]
    right = left + box["width"]
    bottom = top + box["height"]
    dx = x2 - x1
    dy = y2 - y1
    low, high = 0.0, 1.0
    for p, q in (
        (-dx, x1 - left),
        (dx, right - x1),
        (-dy, y1 - top),
        (dy, bottom - y1),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            if ratio > high:
                return False
            low = max(low, ratio)
        else:
            if ratio < low:
                return False
            high = min(high, ratio)
    return True


def _bow_control(
    start: tuple[float, float],
    end: tuple[float, float],
    blockers: list[dict],
) -> tuple[float, float]:
    """Pick a curve control point that pushes the edge clear of *blockers*."""
    mid_x = (start[0] + end[0]) / 2
    mid_y = (start[1] + end[1]) / 2
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    normal_x, normal_y = -dy / length, dx / length
    centre_x = sum(item["x"] + item["width"] / 2 for item in blockers) / len(
        blockers
    )
    centre_y = sum(item["y"] + item["height"] / 2 for item in blockers) / len(
        blockers
    )
    # Offset away from the obstacle, not into it.
    if normal_x * (mid_x - centre_x) + normal_y * (mid_y - centre_y) > 0:
        normal_x, normal_y = -normal_x, -normal_y
    offset = 28.0 + 12.0 * (len(blockers) - 1)
    return mid_x + normal_x * offset, mid_y + normal_y * offset


def _node_markup(placed: dict) -> str:
    node = placed["node"]
    x = placed["x"]
    y = placed["y"]
    width = placed["width"]
    height = placed["height"]
    parts: list[str] = []
    common = (
        f'fill="{_xml(node["fill"])}" stroke="{_xml(node["stroke"])}" '
        'stroke-width="1.5"'
    )
    shape = node["shape"]
    if shape == "ellipse":
        parts.append(
            f'<ellipse cx="{_num(x + width / 2)}" cy="{_num(y + height / 2)}" '
            f'rx="{_num(width / 2)}" ry="{_num(height / 2)}" {common}/>'
        )
    elif shape == "diamond":
        points = " ".join(
            f"{_num(px)},{_num(py)}"
            for px, py in (
                (x + width / 2, y),
                (x + width, y + height / 2),
                (x + width / 2, y + height),
                (x, y + height / 2),
            )
        )
        parts.append(f'<polygon points="{points}" {common}/>')
    else:
        radius = ' rx="8"' if shape == "roundrect" else ""
        parts.append(
            f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(width)}" '
            f'height="{_num(height)}"{radius} {common}/>'
        )
    lines = _label_lines(node["label"])
    first_y = y + height / 2 - (len(lines) - 1) * LINE_HEIGHT / 2 + 5
    for index, line in enumerate(lines):
        parts.append(
            f'<text x="{_num(x + width / 2)}" '
            f'y="{_num(first_y + index * LINE_HEIGHT)}" '
            'text-anchor="middle" '
            f'fill="{_xml(DEFAULT_TEXT)}" font-size="{_num(FONT_SIZE)}">'
            f"{_xml(line)}</text>"
        )
    return "".join(parts)


def _self_loop(placed: dict, color: str, dashed: bool, arrow: bool) -> list[str]:
    x = placed["x"]
    y = placed["y"]
    width = placed["width"]
    height = placed["height"]
    start = (x + width * 0.7, y)
    end = (x + width * 0.3, y)
    lift = max(28.0, height * 0.8)
    path = (
        f"M {_num(start[0])} {_num(start[1])} "
        f"C {_num(start[0] + 12)} {_num(y - lift)}, "
        f"{_num(end[0] - 12)} {_num(y - lift)}, "
        f"{_num(end[0])} {_num(end[1])}"
    )
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    marker = f' marker-end="url(#arrow-{_marker_key(color)})"' if arrow else ""
    return [
        f'<path d="{path}" fill="none" stroke="{_xml(color)}" '
        f'stroke-width="1.5"{dash}{marker}/>'
    ]


def _marker_key(color: str) -> str:
    return "".join(char for char in color if char.isalnum()) or "default"


def render(spec: object) -> tuple[str, list[str]]:
    """Render a spec to deterministic SVG text plus layout warnings."""
    parsed = parse_spec(spec)
    nodes = parsed["nodes"]
    edges = parsed["edges"]
    groups = parsed["groups"]
    placed = _layout(nodes, edges)
    warnings: list[str] = []
    for node in nodes:
        entry = placed[node["id"]]
        if node["width"] and entry["text_width"] > node["width"] - 2 * PAD_X:
            warnings.append(
                f"节点 {node['id']!r} 的文字宽度 "
                f"{entry['text_width']:.1f} 超过给定 width {node['width']:.1f}"
            )
        if (
            node["height"]
            and entry["text_height"] > node["height"] - 2 * PAD_Y
        ):
            warnings.append(
                f"节点 {node['id']!r} 的文字高度 "
                f"{entry['text_height']:.1f} 超过给定 height "
                f"{node['height']:.1f}"
            )

    body: list[str] = []
    for group in groups:
        members = [placed[member] for member in group["nodes"]]
        left = min(entry["x"] for entry in members) - 16
        top = min(entry["y"] for entry in members) - 26
        right = max(entry["x"] + entry["width"] for entry in members) + 16
        bottom = max(entry["y"] + entry["height"] for entry in members) + 16
        body.append(
            f'<rect x="{_num(left)}" y="{_num(top)}" '
            f'width="{_num(right - left)}" height="{_num(bottom - top)}" '
            f'rx="10" fill="{_xml(group["fill"])}" '
            f'stroke="{_xml(group["stroke"])}" stroke-dasharray="4 3"/>'
        )
        if group["label"]:
            body.append(
                f'<text x="{_num(left + 10)}" y="{_num(top + 18)}" '
                f'fill="{_xml(DEFAULT_TEXT)}" font-size="{_num(FONT_SIZE)}">'
                f"{_xml(group['label'])}</text>"
            )

    colors: set[str] = set()
    edge_paths: list[str] = []
    labels: list[str] = []
    for edge in edges:
        color = edge["color"]
        colors.add(color)
        dashed = edge["style"] == "dashed"
        if edge["from"] == edge["to"]:
            edge_paths.extend(
                _self_loop(
                    placed[edge["from"]],
                    color,
                    dashed,
                    edge["arrow"],
                )
            )
            continue
        source = placed[edge["from"]]
        target = placed[edge["to"]]
        sx, sy = _boundary_point(
            source["node"]["shape"],
            source,
            target["x"] + target["width"] / 2,
            target["y"] + target["height"] / 2,
        )
        tx, ty = _boundary_point(
            target["node"]["shape"],
            target,
            source["x"] + source["width"] / 2,
            source["y"] + source["height"] / 2,
        )
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        marker = (
            f' marker-end="url(#arrow-{_marker_key(color)})"'
            if edge["arrow"]
            else ""
        )
        blockers = [
            entry
            for node_id, entry in placed.items()
            if node_id not in (edge["from"], edge["to"])
            and _segment_hits_box(sx, sy, tx, ty, entry)
        ]
        if blockers:
            control_x, control_y = _bow_control((sx, sy), (tx, ty), blockers)
            edge_paths.append(
                f'<path d="M {_num(sx)} {_num(sy)} '
                f'Q {_num(control_x)} {_num(control_y)} '
                f'{_num(tx)} {_num(ty)}" fill="none" '
                f'stroke="{_xml(color)}" stroke-width="1.5"{dash}{marker}/>'
            )
            # Midpoint of a quadratic Bezier, so the label follows the curve.
            mid_x = 0.25 * sx + 0.5 * control_x + 0.25 * tx
            mid_y = 0.25 * sy + 0.5 * control_y + 0.25 * ty - 6
        else:
            edge_paths.append(
                f'<line x1="{_num(sx)}" y1="{_num(sy)}" x2="{_num(tx)}" '
                f'y2="{_num(ty)}" stroke="{_xml(color)}" stroke-width="1.5"'
                f"{dash}{marker}/>"
            )
            mid_x = (sx + tx) / 2
            mid_y = (sy + ty) / 2 - 6
        if edge["label"]:
            width = text_width(edge["label"]) + 8
            labels.append(
                f'<rect x="{_num(mid_x - width / 2)}" '
                f'y="{_num(mid_y - LINE_HEIGHT + 4)}" width="{_num(width)}" '
                f'height="{_num(LINE_HEIGHT)}" fill="#ffffff" '
                'fill-opacity="0.9"/>'
                f'<text x="{_num(mid_x)}" y="{_num(mid_y)}" '
                'text-anchor="middle" '
                f'fill="{_xml(DEFAULT_TEXT)}" font-size="{_num(FONT_SIZE)}">'
                f"{_xml(edge['label'])}</text>"
            )

    body.extend(edge_paths)
    for node in nodes:
        body.append(_node_markup(placed[node["id"]]))
    body.extend(labels)

    extent_x = max(
        (entry["x"] + entry["width"] for entry in placed.values()),
        default=0.0,
    )
    extent_y = max(
        (entry["y"] + entry["height"] for entry in placed.values()),
        default=0.0,
    )
    width = parsed["canvas"].get("width") or extent_x + MARGIN
    height = parsed["canvas"].get("height") or extent_y + MARGIN

    defs = "".join(
        f'<marker id="arrow-{_marker_key(color)}" viewBox="0 0 10 10" '
        'refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{_xml(color)}"/></marker>'
        for color in sorted(colors)
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_num(width)}" height="{_num(height)}" '
        f'viewBox="0 0 {_num(width)} {_num(height)}" '
        f'font-family="sans-serif">\n'
        f"<defs>{defs}</defs>\n" + "\n".join(body) + "\n</svg>\n"
    )
    return svg, warnings


def check_spec(path: Path) -> tuple[list[Problem], list[Problem]]:
    """Schema problems (blocking) and layout warnings (advisory)."""
    path = Path(path)
    try:
        payload = load_spec(path)
        _svg, warnings = render(payload)
    except (ValueError, OSError) as exc:
        return [
            Problem("figure-spec-invalid", str(path), None, str(exc))
        ], []
    return [], [
        Problem("figure-spec-overflow", str(path), None, message)
        for message in warnings
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "把声明式 figure spec 确定性地渲染成 SVG：形状感知裁边、"
            "自环、CJK 宽度；同一份 spec 永远得到同样的字节。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render_parser = sub.add_parser("render", help="渲染 spec 为 SVG")
    render_parser.add_argument("--spec", required=True)
    render_parser.add_argument("--out", default=None, help="省略则写 stdout")

    check_parser = sub.add_parser("check", help="校验 spec 与文字溢出")
    check_parser.add_argument("--spec", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check_spec(Path(args.spec))
            return emit(problems, advisories)
        payload = load_spec(Path(args.spec))
        svg, warnings = render(payload)
        for warning in warnings:
            print(f"布局警告: {warning}", file=sys.stderr)
        if args.out:
            save_text_atomically(
                Path(args.out),
                svg,
                description="figure SVG",
            )
            print(
                json.dumps(
                    {
                        "out": str(args.out),
                        "bytes": len(svg.encode("utf-8")),
                        "warnings": len(warnings),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            sys.stdout.write(svg)
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
