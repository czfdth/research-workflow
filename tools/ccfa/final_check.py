"""Final checks against the rendered paper: PDF baseline, figures, manifest.

Read-only. Every check that cannot run is reported as a `check-skipped`
advisory -- never silently treated as passing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.cli import Problem, ToolEnvironmentError, emit, tool_error
from ccfa.dataval import find_untagged
from ccfa.figure_manifest import check_manifest, load_manifest
from ccfa.figurebytes import check_figure_formats
from ccfa.pdftext import Reader, extract_text, find_unresolved_markers
from ccfa.texscan import iter_tex_files

_DECLARATION_KEYWORDS = ("limitation", "data availability", "局限性", "数据可用性")


def _find_pdf(manuscript: Path) -> Path | None:
    pdfs = sorted(
        Path(manuscript).rglob("*.pdf"),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    return pdfs[0] if pdfs else None


def _check_declarations(text: str, path: str) -> list[Problem]:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _DECLARATION_KEYWORDS):
        return []
    return [
        Problem(
            "missing-declaration",
            path,
            None,
            "渲染后的 PDF 中未找到局限或数据可用性声明",
        )
    ]


def check(
    manuscript: Path,
    pdf: Path | None = None,
    manifest: Path | None = None,
    paper_root: Path | None = None,
    reader: Reader | None = None,
) -> tuple[list[Problem], list[Problem]]:
    manuscript = Path(manuscript)
    if not manuscript.is_dir():
        raise ValueError(f"手稿目录不存在或不是目录: {manuscript}")
    root = Path(paper_root) if paper_root else manuscript.parent

    problems: list[Problem] = []
    advisories: list[Problem] = []

    target_pdf = Path(pdf) if pdf else _find_pdf(manuscript)
    if target_pdf is None or not target_pdf.is_file():
        raise ValueError(f"找不到渲染后的 PDF: {target_pdf}")
    text = extract_text(target_pdf, reader=reader)
    if text is None:
        advisories.append(
            Problem(
                "check-skipped",
                str(target_pdf),
                None,
                "PyMuPDF 不可用或 PDF 无法读取，未解析标记与声明检查已跳过",
            )
        )
    else:
        problems.extend(find_unresolved_markers(text, str(target_pdf)))
        advisories.extend(_check_declarations(text, str(target_pdf)))

    figures_dir = root / "figures"
    if figures_dir.is_dir():
        problems.extend(check_figure_formats(sorted(figures_dir.rglob("*"))))
    else:
        advisories.append(
            Problem(
                "check-skipped",
                str(figures_dir),
                None,
                "未找到 figures/ 目录，图片格式检查已跳过",
            )
        )

    if manifest is not None:
        items = load_manifest(Path(manifest))
        manifest_problems, manifest_advisories = check_manifest(items, root)
        problems.extend(manifest_problems)
        advisories.extend(manifest_advisories)

    for tex in iter_tex_files(manuscript):
        for item in find_untagged(tex):
            advisories.append(
                Problem(
                    "untagged-number",
                    item.path,
                    item.line,
                    f"未标记的数字线索（需人工复核）: {item.text}",
                )
            )

    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="终稿确定性检查")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--pdf")
    parser.add_argument("--manifest")
    parser.add_argument("--paper-root")
    args = parser.parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.manuscript),
            Path(args.pdf) if args.pdf else None,
            Path(args.manifest) if args.manifest else None,
            Path(args.paper_root) if args.paper_root else None,
        )
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
