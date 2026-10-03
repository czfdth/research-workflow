"""Create a new paper project from the template repository."""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

from ccfa.stages import gate_for
from ccfa.texdoc import find_main_tex
from newpaper.venues import resolve_venue

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]

PAPER_DIRS = [
    "manuscript/sections",
    "data",
    "experiments/log",
    "experiments/results",
    "figures",
    "tables",
    "reviews",
    "submission/repro",
    "memory",
    "ccfa-workfiles/literature",
    "ccfa-workfiles/figures",
    "ccfa-workfiles/writing",
]

SEED_FILES = {
    "memory/ideas.md": "# 选题记忆\n",
    "memory/dead-ends.md": "# 反重复记忆\n",
    "reviews/revision-ledger.md": "# 审稿意见矩阵\n",
    "submission/checks.md": "# 投稿检查\n",
    "data/provenance.md": "# 数据来源\n",
}


def create_project(
    papers_root: Path,
    slug: str,
    venue: str,
    year: str,
    mode: str,
    title: str,
) -> Path:
    target = Path(papers_root) / slug
    if target.exists():
        raise FileExistsError(f"目标目录已存在，拒绝覆盖: {target}")

    venue_dir = resolve_venue(venue)
    target.mkdir(parents=True)

    for rel in PAPER_DIRS:
        (target / rel).mkdir(parents=True, exist_ok=True)

    manuscript = target / "manuscript"
    for entry in venue_dir.iterdir():
        if entry.is_file():
            shutil.copy2(entry, manuscript / entry.name)

    shared_bib = TEMPLATE_ROOT / "library" / "refs.bib"
    bib_target = manuscript / "references.bib"
    if shared_bib.is_file():
        shutil.copy2(shared_bib, bib_target)
    else:
        bib_target.write_text("", encoding="utf-8")

    main_tex = find_main_tex(manuscript)
    main_rel = main_tex.relative_to(target).as_posix()

    date = dt.date.today().isoformat()
    template = (TEMPLATE_ROOT / "ccfa.yaml.template").read_text(encoding="utf-8")
    rendered = (
        template.replace("__TITLE__", title)
        .replace("__SLUG__", slug)
        .replace("__VENUE__", venue)
        .replace("__YEAR__", str(year))
        .replace("__MODE__", mode)
        .replace("__DATE__", date)
        .replace('manuscript: "manuscript/main.tex"', f'manuscript: "{main_rel}"')
    )
    (target / "ccfa.yaml").write_text(rendered, encoding="utf-8")

    for rel, content in SEED_FILES.items():
        (target / rel).write_text(content, encoding="utf-8")

    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="派生一个新的论文项目")
    parser.add_argument("slug")
    parser.add_argument("--venue", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--mode", required=True, choices=["conference", "journal"])
    parser.add_argument("--title", default="")
    parser.add_argument(
        "--papers-root",
        default=str(Path.home() / "Documents" / "Codex" / "papers"),
    )
    args = parser.parse_args(argv[1:])

    try:
        target = create_project(
            papers_root=Path(args.papers_root),
            slug=args.slug,
            venue=args.venue,
            year=args.year,
            mode=args.mode,
            title=args.title or args.slug,
        )
    except FileExistsError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"工具错误: {exc}", file=sys.stderr)
        return 2

    gate = gate_for(args.mode, "idea")
    print(str(target))
    print(f"起始 gate: {gate.id} — {gate.criterion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
