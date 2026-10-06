"""Generate a print-ready HTML poster from a plan, deterministically.

The reference implementation (ARIS ``paper-poster-html``) ships three HTML
scaffolds plus machine-readable token packs, and is explicit about the rule that
makes the poster checkable:

    TWO places that must stay in sync -- the ``@page { size: ... }`` rule and the
    poster container's width/height.

It also requires every layout-critical element to carry ``data-measure-role``
(``poster`` / column / hero / footer) because the measurement gate locates
regions through those attributes, and it forbids removing them.

This module generates that HTML from ``data/poster-plan.yaml`` so the two sizes
cannot drift: both come from the same computed inches. The venue palettes are
copied verbatim from the reference ``templates/tokens/*.json`` packs, and the
``@page`` rule is what ``talk_gates verify-final --from-html`` reads, so the
printed PDF is checked against the poster's own declaration rather than a
default.

Printing needs a headless browser. Edge/Chrome are used when present; when no
browser can print, the step is reported as unavailable instead of being
pretended (the same rule the page renderer follows).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from html import escape
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error
from ccfa.figure_manifest import _resolve_figure
from ccfa.talk_gates import canvas_from_html, manifest_index

PLAN = Path("data") / "poster-plan.yaml"
FIGURE_MANIFEST = Path("figures") / "manifest.yaml"
HTML_NAME = "poster.html"
FIGURES_DIR = "figures"
SCHEMA_VERSION = 1

# Copied from the reference templates/tokens/*.json packs, verbatim.
TOKEN_PACKS = {
    "generic": {
        "accent": {"base": "#2D5F8B", "deep": "#1F4566", "light": "#E8F1F8", "soft": "#D7E5F0"},
        "gold": {"base": "#C9A24A", "soft": "#FFF7E0"},
        "bg_page": "#F6F2F0",
    },
    "neurips": {
        "accent": {"base": "#3A5A7A", "deep": "#26405A", "light": "#EDF0F3", "soft": "#DEE3E8"},
        "gold": {"base": "#C9A24A", "soft": "#FFF7E0"},
        "bg_page": "#F2F3F5",
    },
    "icml": {
        "accent": {"base": "#8B3A4A", "deep": "#642430", "light": "#F3ECEE", "soft": "#E9DDDF"},
        "gold": {"base": "#C9A24A", "soft": "#FFF7E0"},
        "bg_page": "#F7F1F1",
    },
    "iclr": {
        "accent": {"base": "#2E6048", "deep": "#1E4231", "light": "#EDF3F0", "soft": "#DEE8E3"},
        "gold": {"base": "#C9A24A", "soft": "#FFF7E0"},
        "bg_page": "#F3F4F1",
    },
    "cvpr": {
        "accent": {"base": "#27407A", "deep": "#1A2C57", "light": "#EBEEF4", "soft": "#DCE0EA"},
        "gold": {"base": "#C9A24A", "soft": "#FFF7E0"},
        "bg_page": "#F1F2F6",
    },
    "acl": {
        "accent": {"base": "#256E72", "deep": "#16494C", "light": "#EBF4F4", "soft": "#DCE9EA"},
        "gold": {"base": "#C9A24A", "soft": "#FFF7E0"},
        "bg_page": "#F0F4F3",
    },
}
# Canvas and column count per scaffold, from the reference template README.
TEMPLATES = {
    "landscape_4col": {"width_in": 60.0, "height_in": 36.0, "columns": 4},
    "landscape_hero": {"width_in": 60.0, "height_in": 36.0, "columns": 2},
    "portrait_2col": {"width_in": 24.0, "height_in": 36.0, "columns": 2},
}
INCLUDABLE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".svg")
POSTER_SIZE_RE = re.compile(
    r"\.poster\s*\{[^}]*?width:\s*([\d.]+)in[^}]*?height:\s*([\d.]+)in",
    re.DOTALL,
)


def _num(value: float) -> str:
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def load_plan(paper_root: Path) -> dict:
    path = Path(paper_root) / PLAN
    if not path.is_file():
        raise ValueError(f"没有 poster plan: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    if payload.get("version") != SCHEMA_VERSION:
        raise ValueError(f"{path} 的 version 必须是 {SCHEMA_VERSION}")
    template = payload.get("template", "landscape_4col")
    if template not in TEMPLATES:
        raise ValueError(
            f"template 非法: {template!r}，应为 {'/'.join(TEMPLATES)}"
        )
    columns = payload.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError(f"{path} 需要非空 columns 列表")
    return payload


def canvas_for(plan: dict) -> tuple[float, float]:
    """Explicit canvas wins; otherwise the scaffold's own dimensions apply."""
    spec = TEMPLATES[plan.get("template", "landscape_4col")]
    canvas = plan.get("canvas")
    if canvas is None:
        return spec["width_in"], spec["height_in"]
    if not isinstance(canvas, dict):
        raise ValueError("canvas 必须是映射")
    width = canvas.get("width_in", spec["width_in"])
    height = canvas.get("height_in", spec["height_in"])
    for value, name in ((width, "canvas.width_in"), (height, "canvas.height_in")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{name} 必须是正数")
    return float(width), float(height)


def _figure_files(paper_root: Path, plan: dict) -> tuple[dict[str, Path], list[str]]:
    index, _manifest = manifest_index(paper_root)
    resolved: dict[str, Path] = {}
    findings: list[str] = []
    for column in plan.get("columns", []):
        if not isinstance(column, dict):
            continue
        for card in column.get("cards") or []:
            if not isinstance(card, dict) or not card.get("figure"):
                continue
            key = str(card["figure"])
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
                findings.append(f"figure {key!r} 的格式 {path.suffix} 不适合网页嵌入")
                continue
            resolved[key] = path
    return resolved, findings


def _root_tokens(tokens: dict, width_in: float) -> str:
    accent = tokens["accent"]
    # One design unit is 1/100 inch: a 60in poster then has a 6000u canvas and
    # every gap stays proportional when the canvas changes.
    return "\n".join(
        [
            ":root {",
            f"  --accent: {accent['base']};",
            f"  --accent-deep: {accent['deep']};",
            f"  --accent-light: {accent['light']};",
            f"  --accent-soft: {accent['soft']};",
            f"  --gold: {tokens['gold']['base']};",
            f"  --gold-soft: {tokens['gold']['soft']};",
            f"  --bg-page: {tokens['bg_page']};",
            "  --text: #1A1A1A;",
            "  --muted: #555555;",
            "  --card-bg: #FFFFFF;",
            "  --border: #D8D8D8;",
            f"  --u: calc({_num(width_in)}in / 6000);",
            "  --fs-1: calc(150 * var(--u));",
            "  --fs-2: calc(96 * var(--u));",
            "  --fs-3: calc(72 * var(--u));",
            "  --fs-4: calc(56 * var(--u));",
            "  --fs-5: calc(44 * var(--u));",
            "  --fs-6: calc(36 * var(--u));",
            "  --fs-7: calc(30 * var(--u));",
            "  --fs-8: calc(26 * var(--u));",
            "  --fs-9: calc(22 * var(--u));",
            "}",
        ]
    )


def _card_markup(card: dict, figures: dict[str, Path]) -> str:
    heading = escape(str(card.get("heading", "")))
    parts = ['<section class="card">']
    if heading:
        parts.append(f'<h3 class="card-title">{heading}</h3>')
    figure = card.get("figure")
    if figure and str(figure) in figures:
        source = f"{FIGURES_DIR}/{escape(figures[str(figure)].name)}"
        parts.append(
            f'<img class="card-figure" src="{source}" alt="{escape(str(figure))}">'
        )
    bullets = card.get("bullets") or []
    if bullets:
        parts.append('<ul class="card-list">')
        parts.extend(
            f"<li>{escape(str(point))}</li>" for point in bullets
        )
        parts.append("</ul>")
    body = card.get("body")
    if isinstance(body, str) and body.strip():
        parts.append(f'<p class="card-body">{escape(body.strip())}</p>')
    parts.append("</section>")
    return "".join(parts)


def render_html(
    plan: dict,
    *,
    figures: dict[str, Path],
    venue_name: str,
    tokens: dict,
    width_in: float,
    height_in: float,
) -> str:
    columns = plan.get("columns") or []
    column_markup = []
    for column in columns:
        title = escape(str(column.get("title", "")))
        cards = "".join(
            _card_markup(card, figures)
            for card in (column.get("cards") or [])
            if isinstance(card, dict)
        )
        column_markup.append(
            '<section class="column" data-measure-role="column">'
            f'<h2 class="column-title">{title}</h2>{cards}</section>'
        )
    footer = plan.get("footer")
    footer_markup = (
        f'<footer class="footer" data-measure-role="footer">{escape(str(footer))}</footer>'
        if footer
        else '<footer class="footer" data-measure-role="footer"></footer>'
    )
    return f"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{escape(str(plan.get("title", "Poster")))}</title>
<!-- Generated by ccfa.poster_html; venue tokens from the reference token pack. -->
<style>
@page {{ size: {_num(width_in)}in {_num(height_in)}in; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: var(--bg-page); }}
* {{ box-sizing: border-box; }}
{_root_tokens(tokens, width_in)}
body {{ font-family: "Helvetica Neue", Arial, "Noto Sans SC", sans-serif; color: var(--text); }}
.poster {{
  width: {_num(width_in)}in; height: {_num(height_in)}in;
  padding: calc(40 * var(--u)); display: flex; flex-direction: column;
  gap: calc(24 * var(--u));
}}
.header {{ border-bottom: calc(6 * var(--u)) solid var(--accent); padding-bottom: calc(16 * var(--u)); }}
.header h1 {{ margin: 0; font-size: var(--fs-1); color: var(--accent-deep); line-height: 1.1; }}
.authors {{ margin: calc(10 * var(--u)) 0 0; font-size: var(--fs-5); color: var(--muted); }}
.venue {{ display: inline-block; margin-top: calc(10 * var(--u)); padding: calc(6 * var(--u)) calc(14 * var(--u));
  background: var(--accent-light); color: var(--accent-deep); font-size: var(--fs-7);
  border-radius: calc(6 * var(--u)); }}
.columns {{ flex: 1 1 auto; display: grid; grid-template-columns: repeat({len(columns)}, 1fr);
  gap: calc(28 * var(--u)); align-content: start; }}
.column {{ display: flex; flex-direction: column; gap: calc(20 * var(--u)); }}
.column-title {{ margin: 0; font-size: var(--fs-3); color: var(--accent-deep); }}
.card {{ background: var(--card-bg); border: 1px solid var(--border);
  border-radius: calc(10 * var(--u)); padding: calc(18 * var(--u)); }}
.card-title {{ margin: 0 0 calc(10 * var(--u)); font-size: var(--fs-5); color: var(--accent); }}
.card-figure {{ display: block; width: 100%; height: auto; }}
.card-list {{ margin: 0; padding-left: calc(28 * var(--u)); font-size: var(--fs-7); line-height: 1.4; }}
.card-body {{ margin: calc(10 * var(--u)) 0 0; font-size: var(--fs-7); line-height: 1.4; }}
.footer {{ border-top: calc(2 * var(--u)) solid var(--border); padding-top: calc(12 * var(--u));
  font-size: var(--fs-8); color: var(--muted); }}
</style>
</head>
<body>
<div class="poster" data-measure-role="poster">
<header class="header">
<h1>{escape(str(plan.get("title", "")))}</h1>
<p class="authors">{escape(str(plan.get("authors", "")))}</p>
<span class="venue">{escape(venue_name)}</span>
</header>
<main class="columns">
{chr(10).join(column_markup)}
</main>
{footer_markup}
</div>
</body>
</html>
"""


def build(paper_root: Path) -> dict:
    """Render the poster HTML in memory plus any findings."""
    paper_root = Path(paper_root).resolve()
    plan = load_plan(paper_root)
    width_in, height_in = canvas_for(plan)
    raw_venue = str(plan.get("venue") or "generic").strip().casefold()
    findings: list[str] = []
    if raw_venue not in TOKEN_PACKS:
        findings.append(f"venue {plan.get('venue')!r} 没有 token pack，回退 generic")
        raw_venue = "generic"
    figures, figure_findings = _figure_files(paper_root, plan)
    findings.extend(figure_findings)
    html = render_html(
        plan,
        figures=figures,
        venue_name=raw_venue,
        tokens=TOKEN_PACKS[raw_venue],
        width_in=width_in,
        height_in=height_in,
    )
    return {
        "html": html,
        "figures": figures,
        "width_in": width_in,
        "height_in": height_in,
        "venue": raw_venue,
        "findings": findings,
    }


def write_poster(paper_root: Path) -> dict:
    paper_root = Path(paper_root).resolve()
    built = build(paper_root)
    html_path = paper_root / HTML_NAME
    html_path.write_text(built["html"], encoding="utf-8", newline="\n")
    copied: list[str] = []
    for figure_id, source in built["figures"].items():
        target = paper_root / FIGURES_DIR / source.name
        if target.resolve() != source.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        copied.append(figure_id)
    return {**built, "html_path": str(html_path), "written": copied}


def _browser_candidates() -> list[str]:
    found: list[str] = []
    for name in ("msedge", "chrome", "chromium", "google-chrome"):
        path = shutil.which(name)
        if path:
            found.append(path)
    for path in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
    ):
        if Path(path).is_file():
            found.append(path)
    return found


def render_pdf(
    html_path: Path,
    out_pdf: Path,
    *,
    timeout: float = 300,
) -> dict:
    """Print the poster HTML to PDF with a headless browser."""
    html_path = Path(html_path).resolve()
    out_pdf = Path(out_pdf).resolve()
    if not html_path.is_file():
        raise ValueError(f"HTML 不存在: {html_path}")
    browsers = _browser_candidates()
    if not browsers:
        return {"rendered": False, "engine": None, "reason": "no-browser"}
    # Keep the throwaway browser profile out of the paper directory: the user's
    # poster folder must not grow a browser cache.
    profile = Path(tempfile.mkdtemp(prefix="ccfa-poster-print-"))
    url = "file:///" + html_path.as_posix().lstrip("/")
    last_error = ""
    try:
        for browser in browsers:
            if out_pdf.exists():
                out_pdf.unlink()
            try:
                completed = subprocess.run(
                    [
                        browser,
                        "--headless=new",
                        "--no-sandbox",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-default-browser-check",
                        f"--user-data-dir={profile}",
                        "--no-pdf-header-footer",
                        f"--print-to-pdf={out_pdf}",
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = f"{browser}: {type(exc).__name__}"
                continue
            # The launcher can return before the renderer has written the file,
            # so wait for it instead of checking once.
            deadline = time.monotonic() + min(60.0, timeout)
            while time.monotonic() < deadline:
                if out_pdf.is_file() and out_pdf.stat().st_size > 0:
                    break
                time.sleep(0.25)
            if out_pdf.is_file() and out_pdf.stat().st_size > 0:
                return {"rendered": True, "engine": browser, "reason": ""}
            last_error = (completed.stderr or "").strip()[-200:] or "no output"
        return {"rendered": False, "engine": None, "reason": last_error}
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def check(root: Path) -> tuple[list[Problem], list[Problem]]:
    """The generated poster's own invariants, worst first."""
    root = Path(root).resolve()
    html_path = root / HTML_NAME
    if not html_path.is_file():
        return [], [
            Problem(
                "poster-html-not-configured",
                str(html_path),
                None,
                "尚未生成 poster.html",
            )
        ]
    text = html_path.read_text(encoding="utf-8")
    problems: list[Problem] = []
    advisories: list[Problem] = []
    poster = POSTER_SIZE_RE.search(text)
    try:
        page_w, page_h = canvas_from_html(html_path)
    except ValueError:
        page_w = page_h = None
        problems.append(
            Problem("poster-page-missing", str(html_path), None, "缺少 @page size")
        )
    if poster is None:
        problems.append(
            Problem(
                "poster-container-missing",
                str(html_path),
                None,
                "缺少 .poster 的 width/height",
            )
        )
    if page_w is not None and poster:
        body_w = float(poster.group(1))
        body_h = float(poster.group(2))
        if abs(page_w - body_w) > 0.01 or abs(page_h - body_h) > 0.01:
            problems.append(
                Problem(
                    "poster-size-drift",
                    str(html_path),
                    None,
                    f"@page {page_w:.2f}x{page_h:.2f}in 与 "
                    f".poster {body_w:.2f}x{body_h:.2f}in 不一致；"
                    "打印会裁切或留白",
                )
            )
    for role in ("poster", "column", "footer"):
        if f'data-measure-role="{role}"' not in text:
            problems.append(
                Problem(
                    "poster-measure-role-missing",
                    str(html_path),
                    None,
                    f"缺少 data-measure-role=\"{role}\"；测量 gate 依赖这些属性",
                )
            )
    if "TODO" in text:
        advisories.append(
            Problem(
                "poster-placeholder",
                str(html_path),
                None,
                "仍含 TODO 占位",
            )
        )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从 data/poster-plan.yaml 确定性生成印刷级 poster.html："
            "@page 与容器尺寸由同一次计算得出所以不会漂移，"
            "venue 配色取自参考 token pack，布局区带 data-measure-role。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser_ = sub.add_parser("build", help="生成 poster.html")
    build_parser_.add_argument("--paper-root", required=True)
    pdf_parser = sub.add_parser("pdf", help="用无头浏览器打印成 PDF")
    pdf_parser.add_argument("--paper-root", required=True)
    pdf_parser.add_argument("--out", default=None)
    check_parser = sub.add_parser("check", help="校验 @page 与容器尺寸是否同步")
    check_parser.add_argument("--paper-root", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check(Path(args.paper_root))
            return emit(problems, advisories)
        if args.command == "build":
            result = write_poster(Path(args.paper_root))
            for message in result["findings"]:
                print(f"警告: {message}", file=sys.stderr)
            print(
                json.dumps(
                    {
                        "html": result["html_path"],
                        "venue": result["venue"],
                        "canvas_in": [result["width_in"], result["height_in"]],
                        "figures": result["written"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        root = Path(args.paper_root)
        html_path = root / HTML_NAME
        out = Path(args.out) if args.out else root / "poster.pdf"
        result = render_pdf(html_path, out)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result["rendered"]:
            print(
                "无法打印 PDF：本机没有可用的无头浏览器（Edge/Chrome）",
                file=sys.stderr,
            )
            return 0
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
