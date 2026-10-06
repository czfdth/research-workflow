"""Export the talk plan as an editable PPTX.

The reference ``paper-slides`` contract asks for both halves of a deck: a
Beamer PDF *and* an editable PPTX with the speaker notes transferred into the
PowerPoint notes field, at the standard 16:9 size (13.333in x 7.5in) or 4:3
(10in x 7.5in). ``talk_deck`` produced the Beamer half; this module produces the
editable one from the same ``data/talk-plan.yaml``, so the two can never
disagree about which slides exist or what the notes say.

Font sizes are derived rather than guessed: the plan's declared point sizes are
scaled by the ratio between the PPTX canvas and the canvas the plan declares, so
text keeps its physical size relative to the slide. (The reference instead
applies a flat ``1.6x`` hint from Beamer points to PowerPoint points; the ratio
is recorded in the result so either can be checked.)

Determinism caveat, stated rather than hidden: the document's core properties
are pinned so ``docProps/core.xml`` is stable, but a PPTX is a zip whose member
timestamps come from the filesystem, so the file is *semantically* reproducible
rather than byte-identical. The same plan always yields the same slides, text,
notes, geometry and pictures.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from PIL import Image

from ccfa.cli import tool_error
from ccfa.poster_html import TOKEN_PACKS
from ccfa.talk_deck import _figure_files
from ccfa.talk_gates import load_plan, parse_format

DEFAULT_OUTPUT = Path("slides") / "main.pptx"
SCHEMA_VERSION = 1
# Standard PowerPoint canvases, by the aspect the plan declares.
STANDARD_CANVASES = {"169": (13.333, 7.5), "43": (10.0, 7.5)}
PPTX_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff")
PINNED_TIMESTAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)
MIN_BODY_PT = 14.0


def _aspect(fmt: dict) -> str:
    return "169" if fmt["width_in"] / fmt["height_in"] >= 1.6 else "43"


def canvas_for(fmt: dict) -> tuple[float, float, str]:
    """Resolve the PPTX canvas: standard 16:9 / 4:3, else the declared size."""
    aspect = _aspect(fmt)
    standard = STANDARD_CANVASES[aspect]
    # A plan whose canvas is already slide-sized keeps it; a Beamer page size
    # (about 6.3in) is mapped onto the standard canvas for that aspect.
    if fmt["width_in"] >= 8.0:
        return fmt["width_in"], fmt["height_in"], "declared"
    return standard[0], standard[1], f"standard-{aspect}"


def _colour(hex_value: str) -> RGBColor:
    return RGBColor.from_string(hex_value.lstrip("#").upper())


def export(
    paper_root: Path,
    *,
    output: Path | None = None,
) -> dict:
    """Write the PPTX and return what was produced."""
    paper_root = Path(paper_root).resolve()
    plan = load_plan(paper_root)
    fmt, _format_findings = parse_format(plan)
    width_in, height_in, canvas_source = canvas_for(fmt)
    scale = width_in / fmt["width_in"]
    title_pt = max(MIN_BODY_PT, round(fmt["title_pt"] * scale, 1))
    body_pt = max(MIN_BODY_PT, round(fmt["body_pt"] * scale, 1))
    venue = str(plan.get("venue") or "generic").strip().casefold()
    findings: list[str] = []
    if venue not in TOKEN_PACKS:
        findings.append(f"venue {plan.get('venue')!r} 没有 token pack，回退 generic")
        venue = "generic"
    accent = _colour(TOKEN_PACKS[venue]["accent"]["deep"])
    figures, figure_findings = _figure_files(paper_root, plan)
    for figure_id, path in list(figures.items()):
        if path.suffix.casefold() not in PPTX_IMAGE_SUFFIXES:
            findings.append(
                f"figure {figure_id!r} 是 {path.suffix}，python-pptx 只支持 "
                f"{'/'.join(PPTX_IMAGE_SUFFIXES)}；已跳过"
            )
            del figures[figure_id]
    findings.extend(figure_findings)

    presentation = Presentation()
    presentation.slide_width = Inches(width_in)
    presentation.slide_height = Inches(height_in)
    blank = presentation.slide_layouts[6]

    def add_text(slide, text, *, size, colour=None, top_in, height_in_, level=0):
        box = slide.shapes.add_textbox(
            Inches(0.6),
            Inches(top_in),
            Inches(width_in - 1.2),
            Inches(height_in_),
        )
        frame = box.text_frame
        frame.word_wrap = True
        for index, line in enumerate(text.split("\n")):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = line
            paragraph.level = level
            for run in paragraph.runs:
                run.font.size = Pt(size)
                if colour is not None:
                    run.font.color.rgb = colour
        return box

    title_slide = presentation.slides.add_slide(blank)
    add_text(
        title_slide,
        str(plan.get("title") or "Conference Talk"),
        size=title_pt,
        colour=accent,
        top_in=2.2,
        height_in_=1.6,
    )
    add_text(
        title_slide,
        "\n".join(
            str(plan.get(key) or "")
            for key in ("authors", "institute", "date")
            if plan.get(key)
        ),
        size=body_pt,
        top_in=3.9,
        height_in_=1.4,
    )

    slides = [item for item in plan.get("slides", []) if isinstance(item, dict)]
    for slide_spec in slides:
        slide = presentation.slides.add_slide(blank)
        add_text(
            slide,
            str(slide_spec.get("title", "")),
            size=title_pt,
            colour=accent,
            top_in=0.5,
            height_in_=1.0,
        )
        figure_ids = [
            str(item)
            for item in (slide_spec.get("figure_ids") or [])
            if str(item) in figures
        ]
        top = 1.7
        if figure_ids:
            picture_path = figures[figure_ids[0]]
            # Bound the picture by BOTH the text column width and the vertical
            # room left after the title and bullets; sizing by width alone makes
            # a portrait or square figure run off the slide.
            with Image.open(picture_path) as image:
                pixel_width, pixel_height = image.size
            aspect = pixel_height / pixel_width if pixel_width else 0.75
            max_width = width_in - 1.2
            max_height = max(0.8, height_in - top - 1.8)
            draw_width = min(max_width, max_height / aspect if aspect else max_width)
            draw_height = draw_width * aspect
            try:
                slide.shapes.add_picture(
                    str(picture_path),
                    Inches(0.6),
                    Inches(top),
                    width=Inches(draw_width),
                    height=Inches(draw_height),
                )
            except Exception as exc:  # noqa: BLE001 - Pillow raises its own types
                raise ValueError(
                    f"figure {figure_ids[0]!r} 无法嵌入 PPTX（{picture_path.name}）: {exc}"
                ) from exc
            top += draw_height + 0.2
        points = [str(point) for point in (slide_spec.get("talking_points") or [])]
        if points:
            add_text(
                slide,
                "\n".join(points),
                size=body_pt,
                top_in=top,
                height_in_=max(1.0, height_in - top - 0.6),
            )
        notes = slide_spec.get("speaker_notes")
        if isinstance(notes, str) and notes.strip():
            slide.notes_slide.notes_text_frame.text = notes.strip()

    closing = presentation.slides.add_slide(blank)
    add_text(
        closing,
        "Thank You",
        size=title_pt,
        colour=accent,
        top_in=3.0,
        height_in_=1.2,
    )

    properties = presentation.core_properties
    properties.title = str(plan.get("title") or "Conference Talk")
    properties.author = str(plan.get("authors") or "")
    properties.created = PINNED_TIMESTAMP
    properties.modified = PINNED_TIMESTAMP
    properties.revision = 1

    out = Path(output) if output is not None else paper_root / DEFAULT_OUTPUT
    out.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(str(out))
    return {
        "pptx": str(out),
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "canvas_in": [round(width_in, 3), round(height_in, 3)],
        "canvas_source": canvas_source,
        "type_scale": round(scale, 4),
        "type_pt": [title_pt, body_pt],
        "slides": len(presentation.slides._sldIdLst),
        "plan_slides": len(slides),
        "notes": sum(
            1
            for item in slides
            if isinstance(item.get("speaker_notes"), str)
            and item["speaker_notes"].strip()
        ),
        "figures": sorted(figures),
        "findings": findings,
        "core_properties_pinned": PINNED_TIMESTAMP.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "把 data/talk-plan.yaml 导成可编辑 PPTX（与 Beamer deck 同一份 plan）："
            "标准 16:9 / 4:3 画布、讲者备注写进 PPT notes 字段、venue 主题色、"
            "字号按画布比例推导而不是拍一个常数。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("export", help="导出 PPTX")
    run.add_argument("--paper-root", required=True)
    run.add_argument("--out", default=None)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        result = export(
            Path(args.paper_root),
            output=Path(args.out) if args.out else None,
        )
        for message in result["findings"]:
            print(f"警告: {message}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
