"""Generate a Beamer deck from ``data/talk-plan.yaml``, deterministically.

``talk_pipeline`` checks the plan and ``talk_gates`` measures the result, but
until now nothing turned the plan into slides: the deck was hand-written, so
"the talk plan is complete" and "the deck exists" were separate facts.

The contract is taken from ARIS's ``paper-slides`` skill: a Beamer source with
the venue colour scheme, one frame per slide, ``\\note{}`` speaker notes,
figures pulled from the paper's figure manifest, a standalone
``speaker_notes.md`` and a ``SLIDES_STATE.json`` recovery record. The same plan
always produces byte-identical sources.

Beamer's own 16:9 page is 16cm wide, which is about half of the 13.33in canvas
the plan (and ``talk_gates.measure``) declares, so the generated document sets
``paperwidth``/``paperheight`` with ``geometry`` to the declared canvas and uses
the declared point sizes directly. Without that, the measured typography and the
rendered deck would be two different things, and ``verify-final --from-plan``
could never agree with the PDF.

One deviation from the reference is deliberate: ARIS symlinks
``paper/figures/*``. Symlinks need privileges on Windows, so the figures are
copied and the deck is self-contained.

The PPTX export in the reference is not implemented here: it needs
python-pptx, which this toolchain does not ship. The state file records that
gap explicitly.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

from ccfa.cli import tool_error
from ccfa.figure_manifest import _resolve_figure
from ccfa.talk_gates import load_plan, manifest_index, parse_format

DEFAULT_OUTPUT_DIR = Path("slides")
STATE_NAME = "SLIDES_STATE.json"
TEX_NAME = "main.tex"
NOTES_NAME = "speaker_notes.md"
FIGURES_DIR = "figures"
SCHEMA_VERSION = 1
INCLUDABLE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg")
BEAMER_BASE_SIZES = (8, 9, 10, 11, 12, 14, 17, 20)
# Venue palettes, copied from the reference skill's colour table.
VENUE_COLORS = {
    "NeurIPS": ("8B5CF6", "2563EB"),
    "ICML": ("DC2626", "1D4ED8"),
    "ICLR": ("059669", "0284C7"),
    "CVPR": ("2563EB", "7C3AED"),
    "GENERIC": ("334155", "2563EB"),
}
_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_ESCAPE_RE = re.compile("|".join(re.escape(key) for key in _LATEX_ESCAPES))


def escape_latex(text: str) -> str:
    return _ESCAPE_RE.sub(lambda match: _LATEX_ESCAPES[match.group(0)], str(text))


def _pt(value: float) -> str:
    """Format a point size without trailing noise, so output stays stable."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def has_cjk(text: str) -> bool:
    return any(
        unicodedata.east_asian_width(char) in ("W", "F") for char in text
    )


def aspect_ratio_option(fmt: dict) -> str:
    ratio = fmt["width_in"] / fmt["height_in"]
    return "169" if ratio >= 1.6 else "43"


def _base_size(body_pt: float) -> int:
    """Nearest Beamer base size at or below the requested body size."""
    chosen = BEAMER_BASE_SIZES[0]
    for size in BEAMER_BASE_SIZES:
        if size <= body_pt:
            chosen = size
    return chosen


def typography(fmt: dict) -> dict:
    """The declared sizes are used as-is; the page is sized to match them."""
    return {
        "title_pt": round(fmt["title_pt"], 2),
        "body_pt": round(fmt["body_pt"], 2),
        "base_size": _base_size(fmt["body_pt"]),
    }


def _venue(name: str | None) -> tuple[str, tuple[str, str], list[str]]:
    findings: list[str] = []
    if not name:
        return "GENERIC", VENUE_COLORS["GENERIC"], findings
    if name in VENUE_COLORS:
        return name, VENUE_COLORS[name], findings
    findings.append(
        f"venue {name!r} 没有配色定义，已回退 GENERIC"
    )
    return "GENERIC", VENUE_COLORS["GENERIC"], findings


def _figure_files(paper_root: Path, plan: dict) -> tuple[dict[str, Path], list[str]]:
    """Resolve every figure a slide references to a real file on disk."""
    index, _manifest = manifest_index(paper_root)
    resolved: dict[str, Path] = {}
    findings: list[str] = []
    for slide in plan.get("slides", []):
        if not isinstance(slide, dict):
            continue
        for figure_id in slide.get("figure_ids") or []:
            key = str(figure_id)
            if key in resolved:
                continue
            item = index.get(key)
            if item is None:
                findings.append(f"figure {key!r} 不在 figures/manifest.yaml 中")
                continue
            path, _advisory = _resolve_figure(item, Path(paper_root))
            if not path.is_file():
                findings.append(f"figure {key!r} 的文件不存在: {path}")
                continue
            if path.suffix.casefold() not in INCLUDABLE_SUFFIXES:
                # graphicx cannot embed svg/eps without a converter step, and
                # emitting an include anyway would only break the compile.
                findings.append(
                    f"figure {key!r} 是 {path.suffix}，Beamer 只能直接包含 "
                    f"{'/'.join(INCLUDABLE_SUFFIXES)}；请先转换"
                )
                continue
            resolved[key] = path
    return resolved, findings


def render_main_tex(
    plan: dict,
    *,
    figures: dict[str, Path],
    venue_name: str,
    colors: tuple[str, str],
    cjk: bool,
) -> str:
    fmt, _findings = parse_format(plan)
    aspect = aspect_ratio_option(fmt)
    type_spec = typography(fmt)
    primary, accent = colors
    title = escape_latex(str(plan.get("title") or "Conference Talk"))
    author = escape_latex(str(plan.get("author") or "Author"))
    institute = escape_latex(str(plan.get("institute") or ""))
    date = escape_latex(str(plan.get("date") or ""))
    lines = [
        "% Generated by ccfa.talk_deck from data/talk-plan.yaml; do not edit by hand.",
        f"% venue: {venue_name}",
        f"% declared canvas: {fmt['width_in']}x{fmt['height_in']}in "
        f"(body {fmt['body_pt']}pt, title {fmt['title_pt']}pt)",
        "% the page is pinned to that canvas so the declared sizes are literal",
        f"\\documentclass[aspectratio={aspect},{type_spec['base_size']}pt]{{beamer}}",
        "",
        "\\usepackage{xcolor}",
        "\\usepackage{graphicx,amsmath,booktabs}",
        "\\usepackage{geometry}",
        f"\\geometry{{paperwidth={fmt['width_in']}in,"
        f"paperheight={fmt['height_in']}in}}",
    ]
    if cjk:
        lines.append("\\usepackage{ctex}")
    lines.extend(
        [
            f"\\definecolor{{primary}}{{HTML}}{{{primary}}}",
            f"\\definecolor{{accent}}{{HTML}}{{{accent}}}",
            "\\usetheme{default}",
            "\\usecolortheme{default}",
            "\\setbeamercolor{frametitle}{fg=primary}",
            "\\setbeamercolor{title}{fg=primary}",
            "\\setbeamercolor{structure}{fg=accent}",
            "\\setbeamercolor{itemize item}{fg=primary}",
            "\\setbeamercolor{itemize subitem}{fg=accent}",
            "\\setbeamertemplate{navigation symbols}{}",
            "\\setbeamertemplate{footline}{"
            "\\hfill\\insertframenumber/\\inserttotalframenumber"
            "\\hspace{2mm}\\vspace{2mm}}",
            "\\setbeamerfont{frametitle}{size=\\fontsize"
            f"{{{_pt(type_spec['title_pt'])}}}"
            f"{{{_pt(type_spec['title_pt'] * 1.2)}}}\\selectfont}}",
            "\\setbeamerfont{normal text}{size=\\fontsize"
            f"{{{_pt(type_spec['body_pt'])}}}"
            f"{{{_pt(type_spec['body_pt'] * 1.35)}}}\\selectfont}}",
            f"\\graphicspath{{{{{FIGURES_DIR}/}}}}",
            "",
            f"\\title{{{title}}}",
            f"\\author{{{author}}}",
            f"\\institute{{{institute}}}",
            f"\\date{{{date}}}",
            "",
            "\\begin{document}",
            "",
            "\\begin{frame}",
            "\\titlepage",
            "\\end{frame}",
            "",
        ]
    )
    for slide in plan.get("slides", []):
        if not isinstance(slide, dict):
            continue
        frame_title = escape_latex(str(slide.get("title", "")))
        lines.append(f"\\begin{{frame}}{{{frame_title}}}")
        figure_ids = [
            str(item) for item in (slide.get("figure_ids") or [])
        ]
        available = [fid for fid in figure_ids if fid in figures]
        if available:
            lines.append("\\centering")
            for figure_id in available:
                lines.append(
                    # Both bounds with keepaspectratio: a wide page makes a
                    # width-only include taller than the frame, which pushes
                    # the bullets off the slide.
                    f"\\includegraphics[width=0.85\\textwidth,"
                    f"height=0.6\\textheight,keepaspectratio]"
                    f"{{{escape_latex(figures[figure_id].name)}}}"
                )
            lines.append("\\vspace{0.5em}")
        points = [item for item in (slide.get("talking_points") or [])]
        if points:
            lines.append("\\begin{itemize}")
            for point in points:
                lines.append(f"  \\item {escape_latex(str(point))}")
            lines.append("\\end{itemize}")
        notes = slide.get("speaker_notes")
        if isinstance(notes, str) and notes.strip():
            lines.append(f"\\note{{{escape_latex(notes.strip())}}}")
        lines.append("\\end{frame}")
        lines.append("")
    lines.extend(
        [
            "\\begin{frame}{Thank You}",
            "\\centering",
            "{\\Large Questions?}\\\\[2em]",
            "\\end{frame}",
            "",
            "\\end{document}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_notes(plan: dict) -> str:
    lines = [f"# Speaker Notes: {plan.get('title') or 'Conference Talk'}", ""]
    for index, slide in enumerate(plan.get("slides", []), start=1):
        if not isinstance(slide, dict):
            continue
        lines.append(f"## {index}. {slide.get('title', '')}")
        lines.append("")
        notes = slide.get("speaker_notes")
        if isinstance(notes, str) and notes.strip():
            lines.append(notes.strip())
        else:
            lines.append("（无 speaker notes）")
        lines.append("")
        points = slide.get("talking_points") or []
        if points:
            lines.append("要点：")
            lines.extend(f"- {point}" for point in points)
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_deck(
    paper_root: Path,
    *,
    output_dir: Path | None = None,
    venue: str | None = None,
) -> dict:
    """Render every deck source in memory. Nothing is written here."""
    paper_root = Path(paper_root).resolve()
    plan = load_plan(paper_root)
    out = Path(output_dir) if output_dir is not None else paper_root / DEFAULT_OUTPUT_DIR
    declared_venue = plan.get("venue")
    if venue is None and isinstance(declared_venue, str) and declared_venue.strip():
        venue = declared_venue.strip()
    venue_name, colors, findings = _venue(venue)
    figures, figure_findings = _figure_files(paper_root, plan)
    findings.extend(figure_findings)
    slides = [item for item in plan.get("slides", []) if isinstance(item, dict)]
    every_text = "\n".join(
        [str(plan.get("title") or "")]
        + [
            str(slide.get("title", ""))
            + "".join(str(point) for point in slide.get("talking_points") or [])
            for slide in slides
        ]
    )
    cjk = has_cjk(every_text)
    fmt, _ = parse_format(plan)
    aspect = aspect_ratio_option(fmt)
    type_spec = typography(fmt)
    state = {
        "schema_version": SCHEMA_VERSION,
        "skill": "talk-deck",
        "venue": venue_name,
        "aspect_ratio": aspect,
        "engine": "xelatex" if cjk else "pdflatex",
        "cjk": cjk,
        "slide_count": len(slides),
        "frame_count": len(slides) + 2,
        "declared_canvas_in": [fmt["width_in"], fmt["height_in"]],
        "declared_type_pt": [fmt["title_pt"], fmt["body_pt"]],
        "deck_type_pt": [type_spec["title_pt"], type_spec["body_pt"]],
        "deck_base_size_pt": type_spec["base_size"],
        "figures": {
            key: path.name for key, path in sorted(figures.items())
        },
        "not_implemented": ["pptx"],
    }
    return {
        "output_dir": out,
        "files": {
            TEX_NAME: render_main_tex(
                plan,
                figures=figures,
                venue_name=venue_name,
                colors=colors,
                cjk=cjk,
            ),
            NOTES_NAME: render_notes(plan),
            STATE_NAME: json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        },
        "figures": figures,
        "state": state,
        "findings": findings,
    }


def write_deck(
    paper_root: Path,
    *,
    output_dir: Path | None = None,
    venue: str | None = None,
) -> dict:
    rendered = render_deck(paper_root, output_dir=output_dir, venue=venue)
    out: Path = rendered["output_dir"]
    (out / FIGURES_DIR).mkdir(parents=True, exist_ok=True)
    for name, text in rendered["files"].items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    copied: list[str] = []
    for figure_id, source in rendered["figures"].items():
        target = out / FIGURES_DIR / source.name
        shutil.copyfile(source, target)
        copied.append(figure_id)
    written = {
        **{name: str(out / name) for name in rendered["files"]},
        "figures": copied,
        "state": str(out / STATE_NAME),
    }
    return {**rendered, "written": written}


def compile_deck(
    output_dir: Path,
    *,
    engine: str = "pdflatex",
    runs: int = 2,
    timeout: float = 600,
) -> dict:
    """Compile twice so ``\\inserttotalframenumber`` settles, then report."""
    output_dir = Path(output_dir)
    tex = output_dir / TEX_NAME
    if not tex.is_file():
        raise ValueError(f"没有可编译的 {tex}")
    if engine not in ("pdflatex", "xelatex", "lualatex"):
        raise ValueError(f"engine 非法: {engine!r}")
    log = ""
    for _ in range(max(1, runs)):
        try:
            completed = subprocess.run(
                [
                    engine,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    TEX_NAME,
                ],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise ValueError(f"{engine} 未安装，无法编译 deck") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"{engine} 编译超时") from exc
        log = completed.stdout or ""
        if completed.returncode != 0:
            tail = "\n".join(log.strip().splitlines()[-12:])
            raise ValueError(f"{engine} 编译失败 (exit {completed.returncode}):\n{tail}")
    pdf = output_dir / f"{tex.stem}.pdf"
    if not pdf.is_file():
        raise ValueError(f"编译完成但没有产出 {pdf}")
    return {"pdf": str(pdf), "engine": engine, "runs": max(1, runs)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从 data/talk-plan.yaml 确定性生成 Beamer deck（venue 配色、"
            "每页对应一帧、\\note 讲者备注、独立 speaker_notes.md 与 "
            "SLIDES_STATE.json）；同一份 plan 永远得到同样的源码。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="生成 slides/main.tex 等源码")
    render.add_argument("--paper-root", required=True)
    render.add_argument("--output-dir", default=None)
    render.add_argument("--venue", default=None)

    compile_parser = sub.add_parser("compile", help="编译生成的 deck")
    compile_parser.add_argument("--output-dir", required=True)
    compile_parser.add_argument("--engine", default=None)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "render":
            result = write_deck(
                Path(args.paper_root),
                output_dir=(
                    Path(args.output_dir) if args.output_dir else None
                ),
                venue=args.venue,
            )
            for message in result["findings"]:
                print(f"警告: {message}", file=sys.stderr)
            print(
                json.dumps(
                    {
                        "output_dir": str(result["output_dir"]),
                        "venue": result["state"]["venue"],
                        "engine": result["state"]["engine"],
                        "slides": result["state"]["slide_count"],
                        "frames": result["state"]["frame_count"],
                        "written": result["written"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        output_dir = Path(args.output_dir)
        engine = args.engine
        if engine is None:
            state_path = output_dir / STATE_NAME
            if state_path.is_file():
                engine = json.loads(
                    state_path.read_text(encoding="utf-8")
                ).get("engine")
            engine = engine or "pdflatex"
        result = compile_deck(output_dir, engine=engine)
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
