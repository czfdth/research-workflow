"""Layout-only polish pass over a Beamer deck, with versioned output.

The reference implementation (ARIS ``slides-polish``) is a per-page review that
fixes layout and typography and is explicitly forbidden from touching content:
no claims, numbers, citations, URLs, author names, affiliations or results, and
no adding, removing or reordering slides. Its other load-bearing rule is
``OUTPUT_VERSIONING``: the original is snapshotted and never overwritten; edits
land in ``<stem>_polished.<ext>``.

This module keeps both rules and drops the model. A deterministic pass can only
apply rewrites that are provably content-preserving, so it does exactly one
mechanical fix and *reports* the rest for a human or a model to act on:

* **fix** ``\\includegraphics[width=...]`` with no height bound. On a wide canvas
  the image grows taller than the frame and pushes the body off the slide; both
  bounds with ``keepaspectratio`` is the standard remedy and cannot change what
  the slide says.
* **report** typography below the projector floor, a missing page geometry pin,
  and visible navigation symbols, without rewriting them.

The safety claim is checkable rather than asserted: every changed line must
match an allowed rule, every change is recorded in ``POLISH_CHANGELOG.md``, and
all other lines must be byte-identical. ``polish`` returns the diff so a caller
can verify that before it trusts the output.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, emit, tool_error

STATE_DIR = Path(".ccfa") / "slides-polish"
STATE_NAME = "POLISH_STATE.json"
CHANGELOG_NAME = "POLISH_CHANGELOG.md"
SCHEMA_VERSION = 1
SNAPSHOT_SUFFIX = "_pre_polish"
POLISHED_SUFFIX = "_polished"
# A projector cannot show much below this; the reference skill's floor for body
# text is 20pt on a 13.33in canvas and 14pt for footnotes.
FONT_FLOOR_PT = 14.0
FIGURE_HEIGHT_BOUND = "height=0.6\\textheight,keepaspectratio"
FRAME_RE = re.compile(r"\\begin\{frame\}(?:\{([^}]*)\})?")
INCLUDE_RE = re.compile(r"\\includegraphics(\[[^\]]*\])?\{([^}]*)\}")
FONT_RE = re.compile(r"\\fontsize\{([\d.]+)\}\{([\d.]+)\}")
GEOMETRY_RE = re.compile(r"\\geometry\{[^}]*\}")
NAV_SYMBOLS_RE = re.compile(r"\\setbeamertemplate\{navigation symbols\}\{\}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _state_dir(deck_dir: Path) -> Path:
    return Path(deck_dir) / STATE_DIR


def _versioned_path(base: Path, suffix: str, extension: str) -> Path:
    """Never overwrite: ``main_polished.tex``, then ``_v2``, ``_v3``, ..."""
    candidate = base.with_name(f"{base.stem}{suffix}{extension}")
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = base.with_name(f"{base.stem}{suffix}_v{index}{extension}")
        if not candidate.exists():
            return candidate
        index += 1


def inspect(tex_text: str) -> dict:
    """Inventory the deck: frames, includes and declared font sizes."""
    frames = [
        {"index": index, "title": (match.group(1) or "").strip()}
        for index, match in enumerate(FRAME_RE.finditer(tex_text), start=1)
    ]
    includes = []
    for match in INCLUDE_RE.finditer(tex_text):
        options = (match.group(1) or "")[1:-1]
        includes.append(
            {
                "file": match.group(2),
                "options": options,
                "has_height": "height=" in options,
            }
        )
    fonts = [
        {"pt": float(match.group(1)), "leading": float(match.group(2))}
        for match in FONT_RE.finditer(tex_text)
    ]
    return {
        "frames": frames,
        "frame_count": len(frames),
        "includes": includes,
        "fonts": fonts,
        "has_geometry_pin": bool(GEOMETRY_RE.search(tex_text)),
        "hides_navigation_symbols": bool(NAV_SYMBOLS_RE.search(tex_text)),
    }


def polish_text(tex_text: str) -> tuple[str, list[dict], list[dict]]:
    """Return (polished text, changes, findings). Content is never touched."""
    changes: list[dict] = []
    findings: list[dict] = []
    output_lines: list[str] = []
    for number, line in enumerate(tex_text.splitlines(), start=1):
        match = INCLUDE_RE.search(line)
        if match and match.group(1) and "height=" not in match.group(1):
            options = match.group(1)[1:-1]
            merged = f"{options},{FIGURE_HEIGHT_BOUND}" if options else (
                FIGURE_HEIGHT_BOUND
            )
            replaced = (
                line[: match.start(1)]
                + f"[{merged}]"
                + line[match.end(1) :]
            )
            changes.append(
                {
                    "line": number,
                    "rule": "figure-height-bound",
                    "before": line,
                    "after": replaced,
                }
            )
            output_lines.append(replaced)
            continue
        output_lines.append(line)
    polished = "\n".join(output_lines) + ("\n" if tex_text.endswith("\n") else "")
    inventory = inspect(polished)
    for entry in inventory["fonts"]:
        if entry["pt"] < FONT_FLOOR_PT:
            findings.append(
                {
                    "rule": "font-below-floor",
                    "message": f"字号 {entry['pt']}pt 低于投影下限 "
                    f"{FONT_FLOOR_PT}pt；未自动改写，请人工确认",
                }
            )
    if not inventory["has_geometry_pin"]:
        findings.append(
            {
                "rule": "no-geometry-pin",
                "message": "没有 \\geometry 钉住画布，PDF 页尺寸可能与声明的画布不同",
            }
        )
    if not inventory["hides_navigation_symbols"]:
        findings.append(
            {
                "rule": "navigation-symbols",
                "message": "没有关闭 beamer 导航符号",
            }
        )
    return polished, changes, findings


def _render_pages(
    pdf: Path,
    out_dir: Path,
    *,
    dpi: int = 110,
    timeout: float = 300,
) -> list[dict]:
    """Render each PDF page to PNG so a review can look at pixels.

    The reference skill requires this ("visual review without rendered pages
    produces low-confidence feedback") and refuses to continue when no renderer
    exists. Here a missing renderer is reported as an unavailable step rather
    than a hard failure, because the deterministic rewrite does not depend on it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / "slide"
    attempts = (
        ["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(stem)],
        ["mutool", "draw", "-r", str(dpi), "-o", f"{stem}-%d.png", str(pdf)],
        [
            "magick",
            "-density",
            str(dpi),
            f"{pdf}",
            f"{stem}-%d.png",
        ],
    )
    for argv in attempts:
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode != 0:
            continue
        produced = sorted(out_dir.glob("slide*.png"))
        if produced:
            return [
                {"page": index, "image": str(path)}
                for index, path in enumerate(produced, start=1)
            ]
    return []


def polish(
    deck: Path,
    *,
    tex_name: str = "main.tex",
    render_pages: bool = True,
) -> dict:
    """Snapshot, rewrite a copy, and record what happened."""
    deck = Path(deck)
    tex = deck / tex_name if deck.is_dir() else deck
    deck_dir = tex.parent
    if not tex.is_file():
        raise ValueError(f"找不到 deck 源文件: {tex}")
    original = _read(tex)
    snapshot = tex.with_name(f"{tex.stem}{SNAPSHOT_SUFFIX}{tex.suffix}")
    if not snapshot.exists():
        shutil.copyfile(tex, snapshot)
    polished_text, changes, findings = polish_text(original)
    out = _versioned_path(tex, POLISHED_SUFFIX, tex.suffix)
    _write(out, polished_text)

    state_dir = _state_dir(deck_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    inventory = inspect(polished_text)
    inspect_path = state_dir / f"INSPECT_{tex.stem}.json"
    _write(
        inspect_path,
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    pages: list[dict] = []
    pdf = deck_dir / f"{tex.stem}.pdf"
    if render_pages and pdf.is_file():
        pages = _render_pages(pdf, state_dir / "traces")
        for entry in pages:
            _write(
                state_dir / "traces" / f"slide_{entry['page']:02d}.json",
                json.dumps(
                    {"page": entry["page"], "image": entry["image"]},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
    changelog = [
        f"# Polish changelog: {tex.name}",
        "",
        f"- snapshot: `{snapshot.name}`",
        f"- output: `{out.name}`",
        f"- changes: {len(changes)}",
        f"- findings: {len(findings)}",
        "",
    ]
    for change in changes:
        changelog.extend(
            [
                f"## line {change['line']} — {change['rule']}",
                "",
                "```diff",
                f"- {change['before'].strip()}",
                f"+ {change['after'].strip()}",
                "```",
                "",
            ]
        )
    if findings:
        changelog.append("## findings（未自动改写）")
        changelog.append("")
        changelog.extend(
            f"- `{item['rule']}`: {item['message']}" for item in findings
        )
        changelog.append("")
    changelog_path = state_dir / CHANGELOG_NAME
    _write(changelog_path, "\n".join(changelog).rstrip("\n") + "\n")

    state = {
        "schema_version": SCHEMA_VERSION,
        "skill": "slides-polish",
        "source": tex.name,
        "snapshot": snapshot.name,
        "output": out.name,
        "phase": "polished",
        "status": "complete" if not findings else "needs-review",
        "updated_at": _now_iso(),
        "changes": len(changes),
        "findings": len(findings),
        "frames": inventory["frame_count"],
        "rendered_pages": len(pages),
        "not_implemented": ["pptx"],
    }
    state_path = state_dir / STATE_NAME
    _write(
        state_path,
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "source": str(tex),
        "snapshot": str(snapshot),
        "output": str(out),
        "state": str(state_path),
        "changelog": str(changelog_path),
        "inspect": str(inspect_path),
        "changes": changes,
        "findings": findings,
        "pages": pages,
        "polished_text": polished_text,
    }


def check(deck: Path, *, tex_name: str = "main.tex") -> tuple[list[Problem], list[Problem]]:
    """Verify the polish output only changed lines an allowed rule covers."""
    deck = Path(deck)
    tex = deck / tex_name if deck.is_dir() else deck
    deck_dir = tex.parent
    state_path = _state_dir(deck_dir) / STATE_NAME
    if not state_path.is_file():
        return [], [
            Problem(
                "slides-polish-not-run",
                str(state_path),
                None,
                "还没有跑过 slides-polish",
            )
        ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    snapshot = deck_dir / state["snapshot"]
    output = deck_dir / state["output"]
    if not snapshot.is_file() or not output.is_file():
        return [
            Problem(
                "slides-polish-missing-files",
                str(state_path),
                None,
                "快照或 polished 输出不存在",
            )
        ], []
    before = _read(snapshot).splitlines()
    after = _read(output).splitlines()
    problems: list[Problem] = []
    if len(before) != len(after):
        problems.append(
            Problem(
                "slides-polish-line-count",
                str(output),
                None,
                f"行数从 {len(before)} 变成 {len(after)}；"
                "polish 只允许改写行，不允许增删",
            )
        )
        return problems, []
    for index, (old, new) in enumerate(zip(before, after), start=1):
        if old == new:
            continue
        match = INCLUDE_RE.search(old)
        authorised = (
            match is not None
            and match.group(1) is not None
            and "height=" not in match.group(1)
            and merge_strip(old) == merge_strip(new)
        )
        if authorised:
            continue
        problems.append(
            Problem(
                "slides-polish-unauthorised-change",
                str(output),
                index,
                f"第 {index} 行的改动不匹配任何允许的规则: {new.strip()[:80]}",
            )
        )
    return problems, []


def merge_strip(text: str) -> str:
    """Compare lines ignoring the options polish is allowed to add."""
    stripped = text.replace(FIGURE_HEIGHT_BOUND, "").replace(" ", "")
    return stripped.replace(",]", "]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "对现有 Beamer deck 做只改版式、绝不改内容的 polish：快照原文件、"
            "输出 _polished 副本、逐行记录改动与人工待办；不覆盖原件。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="执行 polish")
    run.add_argument("--deck", required=True, help="deck 目录或 .tex 文件")
    run.add_argument("--tex-name", default="main.tex")
    run.add_argument("--no-render", action="store_true")
    check_parser = sub.add_parser("check", help="校验改动只来自允许的规则")
    check_parser.add_argument("--deck", required=True)
    check_parser.add_argument("--tex-name", default="main.tex")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check(
                Path(args.deck),
                tex_name=args.tex_name,
            )
            return emit(problems, advisories)
        result = polish(
            Path(args.deck),
            tex_name=args.tex_name,
            render_pages=not args.no_render,
        )
        print(
            json.dumps(
                {
                    "output": result["output"],
                    "changes": len(result["changes"]),
                    "findings": len(result["findings"]),
                    "pages": len(result["pages"]),
                    "state": result["state"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        for finding in result["findings"]:
            print(
                f"待人工确认 [{finding['rule']}]: {finding['message']}",
                file=sys.stderr,
            )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
