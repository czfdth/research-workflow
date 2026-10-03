"""Record where each data file came from, and keep that record honest.

The store is a claim about real bytes; a checksum is what lets `check` notice
when the claim drifts. Writing is deliberately strict: atomic, and refusing to
overwrite an existing entry, because the record of a failed or superseded
source is itself evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, ToolEnvironmentError, emit, tool_error

VALID_CLASSIFICATIONS = ("real", "rescaled-real", "documented-substitute")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def load_store(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 store {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"store 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("store 顶层必须是对象")
    files = data.get("files")
    if not isinstance(files, dict):
        raise ValueError("store 的 files 必须是对象")
    return data


def save_store(path: Path, store: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def add_entry(
    store_path: Path,
    paper_root: Path,
    relpath: str,
    *,
    source: str,
    classification: str,
    units: str | None = None,
    coverage: str | None = None,
    notes: str | None = None,
    force: bool = False,
) -> dict:
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(
            f"classification 非法: {classification!r}，应为 {' / '.join(VALID_CLASSIFICATIONS)}"
        )
    if Path(relpath).is_absolute():
        raise ValueError(f"条目路径必须是相对 paper_root 的相对路径: {relpath}")
    target = Path(paper_root) / relpath
    if not target.is_file():
        raise ValueError(f"来源文件不存在: {target}")

    store = load_store(store_path)
    files = store.setdefault("files", {})
    if relpath in files and not force:
        raise ValueError(f"条目已存在: {relpath}（如需覆盖请显式使用 --force）")

    entry = {
        "source": source,
        "classification": classification,
        "sha256": sha256_of(target),
        "size": target.stat().st_size,
        "recorded_at": _now_iso(),
    }
    for key, value in (("units", units), ("coverage", coverage), ("notes", notes)):
        if value is not None:
            entry[key] = value
    files[relpath] = entry
    save_store(store_path, store)
    return entry


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="数据来源记录与核对")
    parser.add_argument("--store", required=True)
    parser.add_argument("--paper-root", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="登记一个数据文件的来源")
    add.add_argument("relpath")
    add.add_argument("--source", required=True)
    add.add_argument("--classification", required=True, choices=VALID_CLASSIFICATIONS)
    add.add_argument("--units")
    add.add_argument("--coverage")
    add.add_argument("--notes")
    add.add_argument("--force", action="store_true")

    args = parser.parse_args(argv[1:])
    try:
        if args.command == "add":
            add_entry(
                Path(args.store),
                Path(args.paper_root),
                args.relpath,
                source=args.source,
                classification=args.classification,
                units=args.units,
                coverage=args.coverage,
                notes=args.notes,
                force=args.force,
            )
            return emit([], [])
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知子命令: {args.command}")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
