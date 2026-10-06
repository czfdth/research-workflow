"""Canonical gate orchestrator for a conference talk or poster.

``talk_pipeline`` already checks that a talk plan is structurally complete, but
structure is not delivery: a deck can be perfectly shaped and still overflow
every slide. ARIS splits this into a fixed-order poster gate run
(``preflight -> style -> asset -> measure -> polish``) that accumulates the
whole fix surface into one machine-readable report. This module brings the same
shape to the talk artefacts this repository actually produces.

Design points carried over from the reference implementation:

* **The order is load-bearing.** Cheap static lints run before measured ones, so
  an expensive check is never paid for on a deck that is obviously broken.
* **Accumulate by default.** ``--fail-fast`` is opt-in for CI; a human writing a
  deck wants every failure at once.
* **Severity is declared, not implied.** ``polish`` is soft until
  ``--strict-polish``.
* **One report.** Every run writes ``data/talk-gate-report.json``.
* **Measured, not asserted.** ``measure`` renders the slide's text into the
  declared canvas typography and reports a fill ratio; overflow is a hard
  failure rather than an opinion.

``style`` is deliberately not implemented: the reference gates design tokens
against a shipped theme, and inventing a token system here would be a scaffold.
The omission is recorded in the report itself.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.figurebytes import check_figure_formats, sniff
from ccfa.figure_manifest import _resolve_figure
from ccfa.figure_spec import text_width

PLAN = Path("data") / "talk-plan.yaml"
FIGURE_MANIFEST = Path("figures") / "manifest.yaml"
REPORT = Path("data") / "talk-gate-report.json"

# Canonical order. Static and cheap first, measured last; the orchestration
# depends on this sequence, so it is the single source of truth.
CANONICAL_ORDER = ("preflight", "asset", "measure", "polish")
GATE_SEVERITY = {
    "preflight": "hard",
    "asset": "hard",
    "measure": "hard",
    "polish": "soft",
}
# Implemented by the reference implementation but not here; reported so the
# gap is visible in the artefact instead of in somebody's memory.
NOT_IMPLEMENTED = ("style",)
SCHEMA_VERSION = 1

DEFAULT_FORMAT = {
    "width_in": 13.333,
    "height_in": 7.5,
    "margin_in": 0.6,
    "title_pt": 28.0,
    "body_pt": 18.0,
    "line_spacing": 1.35,
}
POINTS_PER_INCH = 72.0
PLACEHOLDER_RE = re.compile(
    r"\b(TODO|TBD|FIXME|XXX|PLACEHOLDER)\b|\?\?\?|待补|占位",
    re.IGNORECASE,
)
MAX_BULLETS = 7
MAX_TITLE_CHARS = 60
MIN_NOTES_CHARS = 20
MEASURE_WARN_FILL = 0.9
PDF_DIM_TOLERANCE_IN = 0.05
# A figure is checked by what it *is*, not by how many bytes it happens to
# compress to: a flat-colour PNG is legitimately tiny, and a 4096-byte text file
# is not a figure at all.
MIN_FIGURE_EDGE_PX = 64
MIN_FIGURE_BYTES = 64
VECTOR_SUFFIXES = (".svg", ".pdf")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finding(code: str, message: str, where: str = "") -> dict:
    return {"code": code, "message": message, "where": where}


def _load_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} 解析失败: {exc}") from exc


def load_plan(paper_root: Path) -> dict:
    path = Path(paper_root) / PLAN
    if not path.is_file():
        raise ValueError(f"没有 talk plan: {path}")
    payload = _load_yaml(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    slides = payload.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError(f"{path} 需要非空 slides 数组")
    return payload


def _slides(plan: dict) -> list[dict]:
    return [item for item in plan.get("slides", []) if isinstance(item, dict)]


def parse_format(plan: dict) -> tuple[dict, list[dict]]:
    """Read the slide geometry, refusing nonsense rather than guessing."""
    payload = plan.get("format")
    if payload is None:
        return dict(DEFAULT_FORMAT), []
    if not isinstance(payload, dict):
        return dict(DEFAULT_FORMAT), [
            _finding("talk-format-invalid", "format 必须是映射")
        ]
    resolved = dict(DEFAULT_FORMAT)
    findings: list[dict] = []
    for key, default in DEFAULT_FORMAT.items():
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            findings.append(
                _finding("talk-format-invalid", f"format.{key} 必须是数字", key)
            )
            continue
        if value <= 0:
            findings.append(
                _finding("talk-format-invalid", f"format.{key} 必须是正数", key)
            )
            continue
        resolved[key] = float(value)
    if resolved["margin_in"] * 2 >= resolved["width_in"]:
        findings.append(
            _finding(
                "talk-format-invalid",
                "margin_in 的两倍不小于画布宽度",
                "format.margin_in",
            )
        )
    return resolved, findings


def _slide_text(slide: dict) -> list[str]:
    values = [str(slide.get("title", ""))]
    for point in slide.get("talking_points") or []:
        values.append(str(point))
    return values


def _wrapped_lines(text: str, size_pt: float, content_width_in: float) -> int:
    if not text:
        return 1
    width_in = text_width(text, size_pt) / POINTS_PER_INCH
    return max(1, math.ceil(width_in / content_width_in))


def _measure_slide(slide: dict, fmt: dict) -> dict:
    """Render one slide's text into the declared typography."""
    content_width_in = fmt["width_in"] - 2 * fmt["margin_in"]
    content_height_in = fmt["height_in"] - 2 * fmt["margin_in"]
    title_lines = _wrapped_lines(
        str(slide.get("title", "")),
        fmt["title_pt"],
        content_width_in,
    )
    title_height = (
        title_lines * fmt["title_pt"] * fmt["line_spacing"] / POINTS_PER_INCH
    )
    body_height = 0.0
    for point in slide.get("talking_points") or []:
        lines = _wrapped_lines(str(point), fmt["body_pt"], content_width_in)
        body_height += (
            lines * fmt["body_pt"] * fmt["line_spacing"] / POINTS_PER_INCH
        )
    gap = 0.15 if body_height else 0.0
    used = title_height + gap + body_height
    return {
        "slide": str(slide.get("id", "")),
        "title_lines": title_lines,
        "used_in": round(used, 3),
        "available_in": round(content_height_in, 3),
        "fill": round(used / content_height_in, 4) if content_height_in else 0.0,
    }


def gate_preflight(
    paper_root: Path,
    plan: dict,
    *,
    deck: Path | None,
) -> list[dict]:
    findings: list[dict] = []
    seen: set[str] = set()
    for index, slide in enumerate(_slides(plan)):
        where = f"slides[{index}]"
        slide_id = slide.get("id")
        if not isinstance(slide_id, str) or not slide_id.strip():
            findings.append(
                _finding("talk-slide-missing-id", "slide 缺少非空 id", where)
            )
        elif slide_id in seen:
            findings.append(
                _finding("talk-slide-duplicate-id", f"id 重复: {slide_id}", where)
            )
        else:
            seen.add(slide_id)
        for text in _slide_text(slide):
            if PLACEHOLDER_RE.search(text):
                findings.append(
                    _finding(
                        "talk-placeholder",
                        f"仍含未完成占位: {text[:60]}",
                        str(slide_id or where),
                    )
                )
        notes = slide.get("speaker_notes")
        if isinstance(notes, str) and PLACEHOLDER_RE.search(notes):
            findings.append(
                _finding(
                    "talk-placeholder",
                    "speaker_notes 仍含未完成占位",
                    str(slide_id or where),
                )
            )
    if deck is not None:
        if not deck.is_file():
            findings.append(
                _finding("talk-deck-missing", f"deck 源文件不存在: {deck}")
            )
        else:
            try:
                raw = deck.read_text(encoding="utf-8")
            except OSError as exc:
                findings.append(
                    _finding("talk-deck-unreadable", f"无法读取 deck: {exc}")
                )
                raw = ""
            for line_number, line in enumerate(raw.splitlines(), start=1):
                if PLACEHOLDER_RE.search(line):
                    findings.append(
                        _finding(
                            "talk-deck-placeholder",
                            f"deck 第 {line_number} 行仍含占位: {line.strip()[:60]}",
                            str(deck),
                        )
                    )
    return findings


def _manifest_index(paper_root: Path) -> tuple[dict[str, dict], Path | None]:
    path = Path(paper_root) / FIGURE_MANIFEST
    if not path.is_file():
        return {}, None
    payload = _load_yaml(path)
    entries = payload.get("figures") if isinstance(payload, dict) else payload
    index: dict[str, dict] = {}
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            for key in ("id", "name"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    index.setdefault(value.strip(), item)
    return index, path


def image_size(path: Path, kind: str) -> tuple[int, int] | None:
    """Read pixel dimensions straight from the header.

    Only the bytes are trusted, and an unreadable header returns None rather
    than a guess: a figure whose size cannot be established is reported, not
    silently accepted.
    """
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(32)
            if kind == ".png":
                if len(head) < 24 or not head.startswith(b"\x89PNG\r\n\x1a\n"):
                    return None
                width, height = struct.unpack(">II", head[16:24])
                return int(width), int(height)
            if kind == ".gif":
                if len(head) < 10:
                    return None
                width, height = struct.unpack("<HH", head[6:10])
                return int(width), int(height)
            if kind == ".jpg":
                return _jpeg_size(handle)
    except (OSError, struct.error):
        return None
    return None


def _jpeg_size(handle) -> tuple[int, int] | None:
    handle.seek(2)
    while True:
        marker = handle.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return None
        (length_bytes,) = struct.unpack(">H", handle.read(2) or b"\x00\x00")
        if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
            body = handle.read(5)
            if len(body) < 5:
                return None
            height, width = struct.unpack(">HH", body[1:5])
            return int(width), int(height)
        if length_bytes < 2:
            return None
        handle.seek(length_bytes - 2, 1)


def _is_svg(path: Path) -> bool:
    try:
        head = Path(path).read_bytes()[:512].lower()
    except OSError:
        return False
    return b"<svg" in head


def gate_asset(paper_root: Path, plan: dict) -> list[dict]:
    """Every figure a slide claims must exist on disk, with real bytes."""
    findings: list[dict] = []
    index, manifest_path = _manifest_index(paper_root)
    for slide in _slides(plan):
        slide_id = str(slide.get("id", ""))
        for figure_id in slide.get("figure_ids") or []:
            item = index.get(str(figure_id))
            if item is None:
                if manifest_path is None:
                    findings.append(
                        _finding(
                            "talk-figure-manifest-missing",
                            "没有 figures/manifest.yaml，无法核对图件",
                            slide_id,
                        )
                    )
                else:
                    findings.append(
                        _finding(
                            "talk-figure-unregistered",
                            f"figure {figure_id!r} 不在 manifest 中",
                            slide_id,
                        )
                    )
                continue
            path, advisory = _resolve_figure(item, Path(paper_root))
            if advisory is not None or not path.is_file():
                findings.append(
                    _finding(
                        "talk-figure-missing",
                        f"figure {figure_id!r} 的文件不存在: {path}",
                        slide_id,
                    )
                )
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                findings.append(
                    _finding(
                        "talk-figure-unreadable",
                        f"figure {figure_id!r} 无法读取: {exc}",
                        slide_id,
                    )
                )
                continue
            if size < MIN_FIGURE_BYTES:
                findings.append(
                    _finding(
                        "talk-figure-empty",
                        f"figure {figure_id!r} 只有 {size} 字节，是空文件",
                        slide_id,
                    )
                )
                continue
            for problem in check_figure_formats([path]):
                findings.append(
                    _finding(
                        "talk-figure-format",
                        problem.message,
                        slide_id,
                    )
                )
            suffix = path.suffix.casefold()
            if suffix in VECTOR_SUFFIXES or _is_svg(path):
                continue
            kind = sniff(path)
            if kind is None:
                findings.append(
                    _finding(
                        "talk-figure-unknown-format",
                        f"figure {figure_id!r} 的字节不是已知图片格式: {path.name}",
                        slide_id,
                    )
                )
                continue
            dimensions = image_size(path, kind)
            if dimensions is None:
                findings.append(
                    _finding(
                        "talk-figure-size-unreadable",
                        f"figure {figure_id!r} 的图片头不可读",
                        slide_id,
                    )
                )
                continue
            width, height = dimensions
            if min(width, height) < MIN_FIGURE_EDGE_PX:
                findings.append(
                    _finding(
                        "talk-figure-low-resolution",
                        f"figure {figure_id!r} 只有 {width}x{height} 像素，"
                        f"投影会糊（下限 {MIN_FIGURE_EDGE_PX}px）",
                        slide_id,
                    )
                )
    return findings


def gate_measure(
    paper_root: Path,
    plan: dict,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Measure every slide against the declared canvas; overflow is hard."""
    fmt, format_findings = parse_format(plan)
    errors = list(format_findings)
    warnings: list[dict] = []
    measurements: list[dict] = []
    for slide in _slides(plan):
        reading = _measure_slide(slide, fmt)
        measurements.append(reading)
        if reading["fill"] > 1.0:
            errors.append(
                _finding(
                    "talk-slide-overflow",
                    f"内容需要 {reading['used_in']}in，超出可用 "
                    f"{reading['available_in']}in（fill "
                    f"{reading['fill']:.2f}）",
                    reading["slide"],
                )
            )
        elif reading["fill"] > MEASURE_WARN_FILL:
            warnings.append(
                _finding(
                    "talk-slide-tight",
                    f"内容填充到 {reading['fill']:.2f}，接近溢出",
                    reading["slide"],
                )
            )
    return errors, warnings, measurements


def gate_polish(plan: dict) -> list[dict]:
    """Soft advisories: the deck is readable but would present better."""
    findings: list[dict] = []
    for slide in _slides(plan):
        slide_id = str(slide.get("id", ""))
        bullets = slide.get("talking_points") or []
        title = str(slide.get("title", ""))
        if len(bullets) > MAX_BULLETS:
            findings.append(
                _finding(
                    "talk-too-many-bullets",
                    f"{len(bullets)} 条要点，超过 {MAX_BULLETS} 条建议上限",
                    slide_id,
                )
            )
        if len(title) > MAX_TITLE_CHARS:
            findings.append(
                _finding(
                    "talk-title-long",
                    f"标题 {len(title)} 字符，超过 {MAX_TITLE_CHARS}",
                    slide_id,
                )
            )
        if not slide.get("figure_ids") and len(bullets) > 4:
            findings.append(
                _finding(
                    "talk-text-only-dense",
                    "无图且要点 > 4，建议配图或拆页",
                    slide_id,
                )
            )
        notes = slide.get("speaker_notes")
        if isinstance(notes, str) and 0 < len(notes.strip()) < MIN_NOTES_CHARS:
            findings.append(
                _finding(
                    "talk-notes-thin",
                    f"speaker_notes 只有 {len(notes.strip())} 字符",
                    slide_id,
                )
            )
    return findings


def run_gates(
    paper_root: Path,
    *,
    deck: Path | None = None,
    strict_polish: bool = False,
    fail_fast: bool = False,
) -> dict:
    """Run the canonical gate order and aggregate one report."""
    paper_root = Path(paper_root).resolve()
    plan = load_plan(paper_root)
    if deck is not None and not Path(deck).is_absolute():
        deck = paper_root / deck
    results: list[dict] = []
    measurements: list[dict] = []
    warnings_total = 0
    for name in CANONICAL_ORDER:
        errors: list[dict] = []
        warnings: list[dict] = []
        if name == "preflight":
            errors = gate_preflight(paper_root, plan, deck=deck)
        elif name == "asset":
            errors = gate_asset(paper_root, plan)
        elif name == "measure":
            errors, warnings, measurements = gate_measure(paper_root, plan)
        else:
            warnings = gate_polish(plan)
        severity = GATE_SEVERITY[name]
        if name == "polish" and strict_polish:
            severity = "hard"
            errors, warnings = warnings, []
        results.append(
            {
                "name": name,
                "severity": severity,
                "status": (
                    "fail" if errors else "warn" if warnings else "pass"
                ),
                "findings": [*errors, *warnings],
            }
        )
        warnings_total += len(warnings)
        if fail_fast and errors:
            break
    ran = {item["name"] for item in results}
    for name in CANONICAL_ORDER:
        if name not in ran:
            results.append(
                {
                    "name": name,
                    "severity": GATE_SEVERITY[name],
                    "status": "skipped",
                    "findings": [],
                }
            )
    hard_failures = sum(
        1
        for item in results
        if item["status"] == "fail" and item["severity"] == "hard"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "skill": "talk-gates",
        "generated_at": _now_iso(),
        "plan": PLAN.as_posix(),
        "deck": Path(deck).as_posix() if deck is not None else None,
        "slides": len(_slides(plan)),
        "gate_order": list(CANONICAL_ORDER),
        "not_implemented_gates": list(NOT_IMPLEMENTED),
        "strict_polish": bool(strict_polish),
        "measurements": measurements,
        "gates": results,
        "hard_failures": hard_failures,
        "warnings": warnings_total,
        "overall": "pass" if hard_failures == 0 else "fail",
    }


def write_report(paper_root: Path, report: dict) -> Path:
    path = Path(paper_root) / REPORT
    save_text_atomically(
        path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="talk gate 报告",
    )
    return path


def _parse_canvas(text: str) -> tuple[float, float]:
    match = re.match(
        r"^\s*([\d.]+)\s*[x×]\s*([\d.]+)\s*(in|pt)?\s*$",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            f"canvas 必须写成 WxH 且单位可选（如 13.333x7.5in）: {text!r}"
        )
    width = float(match.group(1))
    height = float(match.group(2))
    if width <= 0 or height <= 0:
        raise ValueError(f"canvas 尺寸必须是正数: {text!r}")
    if (match.group(3) or "in").lower() == "pt":
        return width / POINTS_PER_INCH, height / POINTS_PER_INCH
    return width, height


def canvas_from_plan(paper_root: Path) -> tuple[float, float, list[dict]]:
    """Read the canvas from the plan so the check cannot drift from it."""
    plan = load_plan(paper_root)
    fmt, findings = parse_format(plan)
    return fmt["width_in"], fmt["height_in"], findings


class PdfInfoMissing(ValueError):
    """``pdfinfo`` is not installed; the caller may use the library fallback."""


def _pdfinfo(pdf: Path) -> dict:
    env = os.environ.copy()
    # Force the C locale: pdfinfo prints decimal points differently elsewhere.
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    try:
        output = subprocess.check_output(
            ["pdfinfo", str(pdf)],
            text=True,
            stderr=subprocess.STDOUT,
            env=env,
        )
    except FileNotFoundError as exc:
        raise PdfInfoMissing(
            "pdfinfo 未安装（poppler）。Windows: choco install poppler，"
            "Linux: apt install poppler-utils"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"pdfinfo 失败: {exc.output}") from exc
    info: dict[str, str] = {}
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            info[key.strip()] = value.strip()
    return info


def _pymupdf_metadata(pdf: Path) -> dict:
    """Fallback reader so the gate is usable where poppler is absent.

    The reference implementation hard-fails without ``pdfinfo``; this
    repository already depends on PyMuPDF, so the same three numbers are read
    from it instead of turning an environment gap into a deck failure.
    """
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise ValueError(
            "pdfinfo 未安装，且 PyMuPDF 也不可用；无法核对 PDF"
        ) from exc
    try:
        with fitz.open(str(pdf)) as document:
            if document.page_count == 0:
                raise ValueError(f"PDF 没有页面: {pdf}")
            page = document[0]
            return {
                "pages": document.page_count,
                "width_pt": float(page.rect.width),
                "height_pt": float(page.rect.height),
                "rotation": int(page.rotation or 0),
                "page_size": f"{page.rect.width:.0f} x {page.rect.height:.0f} pts",
                "engine": "pymupdf",
            }
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - fitz raises its own types
        raise ValueError(f"无法读取 PDF {pdf}: {exc}") from exc


def _pdf_metadata(pdf: Path) -> dict:
    """Page count, page size in points, and rotation, whichever way we can."""
    try:
        info = _pdfinfo(pdf)
    except PdfInfoMissing:
        return _pymupdf_metadata(pdf)
    try:
        pages = int(info.get("Pages", "0") or "0")
    except ValueError:
        pages = 0
    page_size = info.get("Page size", "")
    match = re.search(r"([\d.]+)\s*x\s*([\d.]+)\s*pts", page_size)
    if not match:
        raise ValueError(f"无法解析 pdfinfo 的 Page size: {page_size!r}")
    try:
        rotation = int(info.get("Page rot", "0") or "0")
    except ValueError:
        rotation = 0
    return {
        "pages": pages,
        "width_pt": float(match.group(1)),
        "height_pt": float(match.group(2)),
        "rotation": rotation,
        "page_size": page_size,
        "engine": "pdfinfo",
    }


def verify_final(
    pdf: Path,
    *,
    expected_canvas: tuple[float, float],
    expected_pages: int,
    max_size_mb: float = 40.0,
    dim_tol_in: float = PDF_DIM_TOLERANCE_IN,
) -> tuple[list[dict], dict]:
    """Check the exported PDF against the canvas the plan declared."""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise ValueError(f"PDF 不存在: {pdf}")
    if expected_pages < 1:
        raise ValueError("expected_pages 必须是正整数")
    metadata = _pdf_metadata(pdf)
    pages = metadata["pages"]
    page_size = metadata["page_size"]
    rotation = metadata["rotation"]
    size_mb = pdf.stat().st_size / (1024 * 1024)
    expected_w, expected_h = expected_canvas
    detail = {
        "pdf": pdf.as_posix(),
        "engine": metadata["engine"],
        "pages": pages,
        "page_size": page_size,
        "page_rot": rotation,
        "size_mb": round(size_mb, 3),
        "expected_in": [round(expected_w, 3), round(expected_h, 3)],
    }
    findings: list[dict] = []
    if pages != expected_pages:
        findings.append(
            _finding(
                "talk-pdf-page-count",
                f"页数 {pages}，期望 {expected_pages}",
                pdf.as_posix(),
            )
        )
    width_in = metadata["width_pt"] / POINTS_PER_INCH
    height_in = metadata["height_pt"] / POINTS_PER_INCH
    detail["actual_in"] = [round(width_in, 3), round(height_in, 3)]
    direct = (
        abs(width_in - expected_w) <= dim_tol_in
        and abs(height_in - expected_h) <= dim_tol_in
    )
    swapped = (
        abs(width_in - expected_h) <= dim_tol_in
        and abs(height_in - expected_w) <= dim_tol_in
    )
    if not direct and not (swapped and rotation in (90, 270)):
        findings.append(
            _finding(
                "talk-pdf-canvas-mismatch",
                f"实际 {width_in:.2f}x{height_in:.2f}in，期望 "
                f"{expected_w:.2f}x{expected_h:.2f}in"
                f"（容差 ±{dim_tol_in}in，rot {rotation}）",
                pdf.as_posix(),
            )
        )
    if size_mb > max_size_mb:
        findings.append(
            _finding(
                "talk-pdf-too-large",
                f"{size_mb:.2f} MB 超过上限 {max_size_mb} MB",
                pdf.as_posix(),
            )
        )
    return findings, detail


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "talk/poster 的规范 gate 编排：preflight → asset → measure → "
            "polish，默认累积全部问题并写一份 data/talk-gate-report.json；"
            "measure 按声明的画布排版真实测量填充率，溢出是硬失败。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="按规范顺序跑全部 gate")
    run_parser.add_argument("--paper-root", required=True)
    run_parser.add_argument("--deck", default=None, help="deck 源文件，可选")
    run_parser.add_argument("--strict-polish", action="store_true")
    run_parser.add_argument("--fail-fast", action="store_true")

    verify = sub.add_parser("verify-final", help="按声明画布核对导出的 PDF")
    verify.add_argument("--pdf", required=True)
    verify.add_argument("--canvas", default=None, help="如 13.333x7.5in")
    verify.add_argument("--from-plan", default=None, metavar="PAPER_ROOT")
    verify.add_argument("--pages", type=int, required=True)
    verify.add_argument("--max-size-mb", type=float, default=40.0)
    verify.add_argument("--dim-tol-in", type=float, default=PDF_DIM_TOLERANCE_IN)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "run":
            report = run_gates(
                Path(args.paper_root),
                deck=Path(args.deck) if args.deck else None,
                strict_polish=args.strict_polish,
                fail_fast=args.fail_fast,
            )
            path = write_report(Path(args.paper_root), report)
            print(
                json.dumps(
                    {
                        "overall": report["overall"],
                        "hard_failures": report["hard_failures"],
                        "warnings": report["warnings"],
                        "report": str(path),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1 if report["hard_failures"] else 0
        if args.canvas and args.from_plan:
            return tool_error("--canvas 与 --from-plan 互斥，只能给一个")
        if not args.canvas and not args.from_plan:
            return tool_error(
                "verify-final 需要 --canvas 或 --from-plan，"
                "以免默认画布悄悄判断错误"
            )
        if args.from_plan:
            width, height, format_findings = canvas_from_plan(
                Path(args.from_plan)
            )
            if format_findings:
                return tool_error(format_findings[0]["message"])
            expected = (width, height)
        else:
            expected = _parse_canvas(args.canvas)
        findings, detail = verify_final(
            Path(args.pdf),
            expected_canvas=expected,
            expected_pages=args.pages,
            max_size_mb=args.max_size_mb,
            dim_tol_in=args.dim_tol_in,
        )
        problems = [
            Problem(item["code"], item.get("where") or args.pdf, None, item["message"])
            for item in findings
        ]
        print(json.dumps(detail, ensure_ascii=False, sort_keys=True))
        return emit(problems, [])
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
