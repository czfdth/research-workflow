"""Create a new paper project from the template repository."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

import yaml

from ccfa.stages import gate_for
from ccfa.texdoc import find_main_tex
from ccfa.milestones import parse_deadline
from newpaper.venues import resolve_venue

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PAPERS_ROOT = TEMPLATE_ROOT / "papers"

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Windows reserves these device names before the first dot.
WINDOWS_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "com1",
        "com2",
        "com3",
        "com4",
        "com5",
        "com6",
        "com7",
        "com8",
        "com9",
        "lpt1",
        "lpt2",
        "lpt3",
        "lpt4",
        "lpt5",
        "lpt6",
        "lpt7",
        "lpt8",
        "lpt9",
    }
)

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
    "data/provenance.json": '{\n  "version": 1,\n  "files": {}\n}\n',
}


class InvalidSlugError(ValueError):
    """Raised when a slug is not safe to use as a directory name."""


def validate_slug(slug: str) -> str:
    """Return the slug unchanged; raise when it could escape the papers root."""
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
        raise InvalidSlugError(
            f"非法 slug: {slug!r}；只允许 [a-z0-9._-]，且必须由小写字母或数字开头"
        )
    stem = slug.split(".", 1)[0]
    if stem.lower() in WINDOWS_RESERVED_NAMES:
        raise InvalidSlugError(
            f"非法 slug: {slug!r}；{stem!r} 是 Windows 保留设备名，不能作为目录名"
        )
    return slug


class _QuotedString(str):
    """Marker type emitted in double quotes so scalars cannot change type."""


class _StateDumper(yaml.SafeDumper):
    """SafeDumper that writes _QuotedString values in double quotes."""


_StateDumper.add_representer(
    _QuotedString,
    lambda dumper, value: dumper.represent_scalar(
        "tag:yaml.org,2002:str", str(value), style='"'
    ),
)


def _quote_strings(value: object) -> object:
    """Return the structure with every string leaf wrapped as _QuotedString."""
    if isinstance(value, str):
        return _QuotedString(value)
    if isinstance(value, dict):
        return {key: _quote_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_quote_strings(item) for item in value]
    return value


def create_project(
    papers_root: Path,
    slug: str,
    venue: str,
    year: str,
    mode: str,
    title: str,
    deadline: str | None = None,
) -> Path:
    slug = validate_slug(slug)
    deadline_date = parse_deadline(deadline)
    root = Path(papers_root).resolve()
    target = (root / slug).resolve()
    if not target.is_relative_to(root):
        raise InvalidSlugError(f"非法 slug: {slug!r}；目标目录逃出 papers root {root}")
    if target.exists():
        raise FileExistsError(f"目标目录已存在，拒绝覆盖: {target}")

    venue_dir = resolve_venue(venue)
    root_existed = root.is_dir()
    created_target = False
    try:
        target.mkdir(parents=True)
        created_target = True

        for rel in PAPER_DIRS:
            (target / rel).mkdir(parents=True, exist_ok=True)

        manuscript = target / "manuscript"
        shutil.copytree(
            venue_dir,
            manuscript,
            dirs_exist_ok=True,
            copy_function=shutil.copy2,
        )

        shared_bib = TEMPLATE_ROOT / "library" / "refs.bib"
        bib_target = manuscript / "references.bib"
        if shared_bib.is_file():
            shutil.copy2(shared_bib, bib_target)
        else:
            bib_target.write_text("", encoding="utf-8")

        main_tex = find_main_tex(manuscript)
        main_rel = main_tex.relative_to(target).as_posix()

        date = dt.date.today().isoformat()
        state = yaml.safe_load(
            (TEMPLATE_ROOT / "ccfa.yaml.template").read_text(encoding="utf-8")
        )
        if not isinstance(state, dict):
            raise ValueError("ccfa.yaml.template 顶层必须是映射")
        state["project"]["title"] = title
        state["project"]["short_name"] = slug
        state["target_venue"]["name"] = venue
        state["target_venue"]["year"] = str(year)
        state["target_venue"]["mode"] = mode
        state["target_venue"]["deadline"] = (
            deadline_date.isoformat() if deadline_date else None
        )
        state["stage"]["updated_at"] = date
        state["artifacts"]["manuscript"] = main_rel
        rendered = yaml.dump(
            _quote_strings(state),
            Dumper=_StateDumper,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            line_break="\n",
        )
        (target / "ccfa.yaml").write_text(rendered, encoding="utf-8")

        for rel, content in SEED_FILES.items():
            (target / rel).write_text(content, encoding="utf-8")
    except BaseException:
        # A failed scaffold must not block a retry with leftover files.
        if created_target:
            shutil.rmtree(target, ignore_errors=True)
        if not root_existed:
            try:
                root.rmdir()
            except OSError:
                pass
        raise

    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="派生一个新的论文项目")
    parser.add_argument("slug")
    parser.add_argument("--venue", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--mode", required=True, choices=["conference", "journal"])
    parser.add_argument("--title", default="")
    parser.add_argument("--deadline")
    parser.add_argument(
        "--papers-root",
        default=str(DEFAULT_PAPERS_ROOT),
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
            deadline=args.deadline,
        )
    except (FileExistsError, InvalidSlugError) as exc:
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
