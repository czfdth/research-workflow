"""Measure a printed poster's geometry: column balance, footer gap, fill.

The reference implementation (ARIS ``paper-poster-html``) is explicit that
``measure`` is *the* hard gate for a poster: print-emulate the HTML in headless
Chromium, read the geometry of every ``[data-measure-role]`` element, and report
two numbers — the spread of column bottoms (aim < 3 px, fail at 5) and the gap
from the lowest card to the footer strip (aim 30-50 px). An unfilled poster is
*expected* to fail it; that is the gate saying the poster is not finished.

This host has no WebSocket client, so the authoritative route (Chrome DevTools
Protocol ``Runtime.evaluate`` over ``getBoundingClientRect``) is not available.
Instead the measurement runs on the **printed PDF** with PyMuPDF: cards are the
white filled rectangles, columns are found by horizontal overlap, and the footer
is the lowest text block. Measuring the printed sheet is a different engine for
the same question, and it measures what actually prints rather than what the
layout engine intended.

Distances are reported in CSS-pixel equivalents (96 px/in) so the reference
bands apply unchanged: 1 pt = 96/72 px.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, tool_error

PX_PER_POINT = 96.0 / 72.0
# Bands carried over from the reference measure gate.
SPREAD_OK_PX = 3.0
SPREAD_FAIL_PX = 5.0
GAP_TARGET_PX = (30.0, 50.0)
GAP_HARD_PX = (12.0, 80.0)
FILL_TARGET = (0.9, 1.01)
MIN_CARD_WIDTH_PT = 24.0
MIN_CARD_HEIGHT_PT = 12.0
WHITE_TOLERANCE = 0.02


def _is_card(drawing: dict) -> bool:
    fill = drawing.get("fill")
    if not fill:
        return False
    if any(abs(channel - 1.0) > WHITE_TOLERANCE for channel in fill):
        return False
    rect = drawing["rect"]
    return rect.width >= MIN_CARD_WIDTH_PT and rect.height >= MIN_CARD_HEIGHT_PT


def _columns(cards: list) -> list[list]:
    """Group cards by horizontal overlap, left to right."""
    columns: list[dict] = []
    for rect in sorted(cards, key=lambda item: (item.x0, item.y0)):
        for column in columns:
            if rect.x0 < column["right"] - 1.0:
                column["rects"].append(rect)
                column["right"] = max(column["right"], rect.x1)
                break
        else:
            columns.append({"left": rect.x0, "right": rect.x1, "rects": [rect]})
    return [column["rects"] for column in columns]


def measure(pdf: Path) -> dict:
    """Return the poster's measured geometry, in CSS-pixel equivalents."""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise ValueError(f"PDF 不存在: {pdf}")
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise ValueError("需要 PyMuPDF 才能测量海报几何") from exc
    with fitz.open(str(pdf)) as document:
        if document.page_count == 0:
            raise ValueError(f"PDF 没有页面: {pdf}")
        page = document[0]
        page_width, page_height = float(page.rect.width), float(page.rect.height)
        seen: set[tuple[float, float, float, float]] = set()
        cards = []
        for drawing in page.get_drawings():
            if not _is_card(drawing):
                continue
            rect = drawing["rect"]
            key = (round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            cards.append(rect)
        columns = _columns(cards)
        if not cards:
            raise ValueError(
                f"{pdf} 里没有找到卡片（白色填充矩形）；"
                "无法测量列平衡，可能还没填内容"
            )
        column_bottoms = [max(rect.y1 for rect in group) for group in columns]
        blocks = [block for block in page.get_text("blocks") if block[4].strip()]
        footer_top = max((block[1] for block in blocks), default=page_height)
        lowest_card = max(column_bottoms)
        spread_px = (max(column_bottoms) - min(column_bottoms)) * PX_PER_POINT
        gap_px = (footer_top - lowest_card) * PX_PER_POINT
        fill_ratio = lowest_card / footer_top if footer_top else 0.0
    return {
        "pdf": pdf.as_posix(),
        "page_pt": [round(page_width, 2), round(page_height, 2)],
        "columns": len(columns),
        "cards": len(cards),
        "column_bottoms_px": [
            round(bottom * PX_PER_POINT, 2) for bottom in column_bottoms
        ],
        "spread_px": round(spread_px, 2),
        "gap_to_footer_px": round(gap_px, 2),
        "fill_ratio": round(fill_ratio, 4),
    }


def findings(reading: dict) -> list[dict]:
    """Turn the numbers into hard/soft findings against the reference bands."""
    out: list[dict] = []
    spread = reading["spread_px"]
    if spread >= SPREAD_FAIL_PX:
        out.append(
            {
                "code": "poster-column-spread",
                "severity": "hard",
                "message": f"列底落差 {spread:.1f}px，超过上限 "
                f"{SPREAD_FAIL_PX}px；海报看起来没填满平衡",
            }
        )
    elif spread > SPREAD_OK_PX:
        out.append(
            {
                "code": "poster-column-spread-tight",
                "severity": "soft",
                "message": f"列底落差 {spread:.1f}px，目标 <{SPREAD_OK_PX}px",
            }
        )
    gap = reading["gap_to_footer_px"]
    if not GAP_HARD_PX[0] <= gap <= GAP_HARD_PX[1]:
        out.append(
            {
                "code": "poster-footer-gap",
                "severity": "hard",
                "message": f"最低卡片到页脚 {gap:.1f}px，超出可接受范围 "
                f"{GAP_HARD_PX[0]:.0f}-{GAP_HARD_PX[1]:.0f}px",
            }
        )
    elif not GAP_TARGET_PX[0] <= gap <= GAP_TARGET_PX[1]:
        out.append(
            {
                "code": "poster-footer-gap-tight",
                "severity": "soft",
                "message": f"最低卡片到页脚 {gap:.1f}px，目标 "
                f"{GAP_TARGET_PX[0]:.0f}-{GAP_TARGET_PX[1]:.0f}px",
            }
        )
    fill = reading["fill_ratio"]
    if not FILL_TARGET[0] <= fill <= FILL_TARGET[1]:
        out.append(
            {
                "code": "poster-canvas-fill",
                "severity": "soft",
                "message": f"画布填充 {fill * 100:.1f}%，目标 "
                f"{FILL_TARGET[0] * 100:.0f}-{FILL_TARGET[1] * 100:.0f}%",
            }
        )
    return out


def check(pdf: Path) -> tuple[list[Problem], list[Problem]]:
    """Report the measured findings as problems (hard) and advisories (soft)."""
    try:
        reading = measure(pdf)
    except (ValueError, OSError) as exc:
        return [Problem("poster-measure-failed", str(pdf), None, str(exc))], []
    problems: list[Problem] = []
    advisories: list[Problem] = []
    for item in findings(reading):
        problem = Problem(item["code"], str(pdf), None, item["message"])
        if item["severity"] == "hard":
            problems.append(problem)
        else:
            advisories.append(problem)
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "测量印刷后海报的几何：列底落差、最低卡片到页脚的间距、画布填充率。"
            "阈值沿用参考实现的 CSS px 口径（1pt = 96/72px）。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("measure", "输出测量数字"),
        ("check", "按参考阈值判定 hard/soft"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--pdf", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check(Path(args.pdf))
            return emit(problems, advisories)
        print(json.dumps(measure(Path(args.pdf)), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
