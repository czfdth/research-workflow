"""Read and write project-scoped research memory.

Ideas live in ``memory/ideas.md`` and dead ends in ``memory/dead-ends.md``.
Both files are YAML lists with fixed field order. A dead end must include
``reopen_if`` so it can be reconsidered when conditions change.

Claim status writeback is not implemented in this layer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from ccfa.cli import save_text_atomically, tool_error

VALID_IDEA_STATUSES = ("active", "abandoned", "merged")
IDEAS_FILE = "memory/ideas.md"
DEAD_ENDS_FILE = "memory/dead-ends.md"

IDEA_FIELDS = ("id", "date", "idea", "status", "notes")
DEAD_END_FIELDS = ("id", "date", "idea", "reason", "evidence", "reopen_if")

_IDEAS_HEADER = "# 研究记忆（脚本读写，勿改字段名）\n"
_DEAD_ENDS_HEADER = "# 反重复记忆（脚本读写，勿改字段名）\n"
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def load_memory(path: Path) -> list[dict]:
    """Load a YAML list. A missing file is an empty memory."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取记忆文件 {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"记忆文件不是合法 YAML: {path}: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"记忆文件顶层必须是列表: {path}")
    return data


def _ordered_entry(entry: object) -> object:
    if not isinstance(entry, dict):
        return entry
    if any(key in entry for key in ("reason", "evidence", "reopen_if")):
        order = DEAD_END_FIELDS
    else:
        order = IDEA_FIELDS
    ordered = {key: entry[key] for key in order if key in entry}
    for key, value in entry.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _dump_memory(path: Path, entries: list[dict]) -> str:
    header = (
        _DEAD_ENDS_HEADER
        if Path(path).name == "dead-ends.md"
        else _IDEAS_HEADER
    )
    ordered = [_ordered_entry(entry) for entry in entries]
    body = yaml.safe_dump(
        ordered,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    if not body.endswith("\n"):
        body += "\n"
    return header + body


def save_memory(path: Path, entries: list[dict]) -> None:
    """Atomically write entries with fixed field order."""
    save_text_atomically(
        Path(path),
        _dump_memory(Path(path), entries),
        description="记忆文件",
    )


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 不能为空")
    return value


def _validate_date(value: object) -> str:
    text = _required_text("date", value)
    if _DATE_PATTERN.fullmatch(text) is None:
        raise ValueError(f"date 必须匹配 YYYY-MM-DD: {text!r}")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"date 不是合法日期: {text!r}") from exc
    return text


def _next_id(entries: list[dict], prefix: str) -> str:
    pattern = re.compile(rf"^{prefix}([1-9][0-9]*)$")
    numbers: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str):
            continue
        match = pattern.fullmatch(entry_id)
        if match is not None:
            numbers.append(int(match.group(1)))
    return f"{prefix}{max(numbers, default=0) + 1}"


def add_idea(
    paper_root: Path,
    *,
    idea: str,
    date: str,
    status: str = "active",
    notes: str | None = None,
) -> dict:
    """Append one idea and return the written entry."""
    idea = _required_text("idea", idea)
    date_text = _validate_date(date)
    if status not in VALID_IDEA_STATUSES:
        raise ValueError(
            f"status 非法: {status!r}，应为 {' / '.join(VALID_IDEA_STATUSES)}"
        )

    path = Path(paper_root) / IDEAS_FILE
    entries = load_memory(path)
    entry = {
        "id": _next_id(entries, "I"),
        "date": date_text,
        "idea": idea,
        "status": status,
        "notes": notes,
    }
    entries.append(entry)
    save_memory(path, entries)
    return entry


def add_dead_end(
    paper_root: Path,
    *,
    idea: str,
    date: str,
    reason: str | None = None,
    evidence: str | None = None,
    reopen_if: str | None = None,
) -> dict:
    """Append one dead end and return the written entry."""
    idea = _required_text("idea", idea)
    reason = _required_text("reason", reason)
    evidence = _required_text("evidence", evidence)
    reopen_if = _required_text("reopen_if", reopen_if)
    date_text = _validate_date(date)

    path = Path(paper_root) / DEAD_ENDS_FILE
    entries = load_memory(path)
    entry = {
        "id": _next_id(entries, "DE"),
        "date": date_text,
        "idea": idea,
        "reason": reason,
        "evidence": evidence,
        "reopen_if": reopen_if,
    }
    entries.append(entry)
    save_memory(path, entries)
    return entry


def list_memory(
    paper_root: Path,
    *,
    kind: str = "all",
    status: str | None = None,
) -> dict:
    """List stored ideas and dead ends, optionally filtered."""
    if kind not in ("all", "ideas", "dead-ends"):
        raise ValueError("kind 必须是 all / ideas / dead-ends")
    if status is not None and status not in VALID_IDEA_STATUSES:
        raise ValueError(
            f"status 非法: {status!r}，应为 {' / '.join(VALID_IDEA_STATUSES)}"
        )

    paper_root = Path(paper_root)
    ideas = (
        load_memory(paper_root / IDEAS_FILE)
        if kind in ("all", "ideas")
        else []
    )
    dead_ends = (
        load_memory(paper_root / DEAD_ENDS_FILE)
        if kind in ("all", "dead-ends")
        else []
    )
    if status is not None:
        ideas = [
            entry
            for entry in ideas
            if isinstance(entry, dict) and entry.get("status") == status
        ]
    return {"ideas": ideas, "dead_ends": dead_ends}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "读写项目研究记忆；claim 状态回写未实现。"
        )
    )
    parser.add_argument(
        "--paper-root",
        default=".",
        help="论文项目根目录（默认: 当前目录）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    idea = subparsers.add_parser("add-idea", help="追加一条选题想法")
    idea.add_argument("--idea", required=True)
    idea.add_argument("--date", required=True)
    idea.add_argument(
        "--status",
        choices=VALID_IDEA_STATUSES,
        default="active",
    )
    idea.add_argument("--notes")

    dead_end = subparsers.add_parser("add-dead-end", help="追加一条反重复死路")
    dead_end.add_argument("--idea", required=True)
    dead_end.add_argument("--reason", required=True)
    dead_end.add_argument("--evidence", required=True)
    dead_end.add_argument("--reopen-if", required=True)
    dead_end.add_argument("--date", required=True)

    listing = subparsers.add_parser("list", help="列出记忆条目")
    listing.add_argument(
        "--kind",
        choices=("all", "ideas", "dead-ends"),
        default="all",
    )
    listing.add_argument("--status", choices=VALID_IDEA_STATUSES)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        paper_root = Path(args.paper_root)
        if args.command == "add-idea":
            result = add_idea(
                paper_root,
                idea=args.idea,
                date=args.date,
                status=args.status,
                notes=args.notes,
            )
        elif args.command == "add-dead-end":
            result = add_dead_end(
                paper_root,
                idea=args.idea,
                reason=args.reason,
                evidence=args.evidence,
                reopen_if=args.reopen_if,
                date=args.date,
            )
        else:
            result = list_memory(
                paper_root,
                kind=args.kind,
                status=args.status,
            )
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
