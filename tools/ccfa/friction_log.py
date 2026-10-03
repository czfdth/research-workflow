"""Record workflow friction in a structured, hand-editable JSON store."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa import cli
from ccfa.cli import Problem, emit, tool_error

DEFAULT_STORE = "friction_log.json"
VALID_CATEGORIES = ("tool-bug", "skill-gap", "environment", "other")
VALID_SEVERITIES = ("low", "medium", "high")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump_store(store: dict) -> str:
    return json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_store(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": 1, "entries": []}
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取摩擦记录 store {path}: {exc}") from exc
    try:
        store = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"摩擦记录 store 不是合法 JSON: {exc}") from exc
    if not isinstance(store, dict):
        raise ValueError("摩擦记录 store 顶层必须是对象")
    if "version" not in store:
        raise ValueError("摩擦记录 store 缺少 version 字段")
    if type(store["version"]) is not int or store["version"] != 1:
        raise ValueError(f"摩擦记录 store version 不支持: {store['version']!r}")
    if not isinstance(store.get("entries"), list):
        raise ValueError("摩擦记录 store 的 entries 必须是列表")
    return store


def save_store(path: Path, store: dict) -> None:
    cli.save_text_atomically(
        Path(path),
        _dump_store(store),
        description="摩擦记录 store",
    )


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 不能为空")
    return value


def add_entry(
    store_path: Path,
    *,
    stage: str,
    component: str,
    category: str,
    severity: str,
    description: str,
    workaround: str | None = None,
) -> dict:
    stage = _required_text("stage", stage)
    component = _required_text("component", component)
    description = _required_text("description", description)
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"category 非法: {category!r}，应为 {' / '.join(VALID_CATEGORIES)}"
        )
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"severity 非法: {severity!r}，应为 {' / '.join(VALID_SEVERITIES)}"
        )

    store = load_store(store_path)
    existing_ids = [
        entry["id"]
        for entry in store["entries"]
        if isinstance(entry, dict)
        and type(entry.get("id")) is int
    ]
    entry = {
        "id": max(existing_ids, default=0) + 1,
        "created_at": _now_iso(),
        "stage": stage,
        "component": component,
        "category": category,
        "severity": severity,
        "description": description,
        "workaround": workaround,
    }
    store["entries"].append(entry)
    save_store(Path(store_path), store)
    return entry


def _entry_line(entry: dict) -> int | None:
    entry_id = entry.get("id")
    return entry_id if type(entry_id) is int else None


def check_store(store_path: Path) -> list[Problem]:
    path = Path(store_path)
    store = load_store(path)
    problems: list[Problem] = []

    for index, entry in enumerate(store["entries"], start=1):
        if not isinstance(entry, dict):
            problems.append(
                Problem(
                    "friction-missing-field",
                    str(path),
                    None,
                    f"条目 {index} 必须是对象",
                )
            )
            continue

        line = _entry_line(entry)
        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            problems.append(
                Problem(
                    "friction-missing-description",
                    str(path),
                    line,
                    f"条目 {index} 缺少非空 description",
                )
            )
        if entry.get("category") not in VALID_CATEGORIES:
            problems.append(
                Problem(
                    "friction-invalid-enum",
                    str(path),
                    line,
                    f"条目 {index} 的 category 非法: {entry.get('category')!r}",
                )
            )
        if entry.get("severity") not in VALID_SEVERITIES:
            problems.append(
                Problem(
                    "friction-invalid-enum",
                    str(path),
                    line,
                    f"条目 {index} 的 severity 非法: {entry.get('severity')!r}",
                )
            )
        stage = entry.get("stage")
        if not isinstance(stage, str) or not stage.strip():
            problems.append(
                Problem(
                    "friction-missing-field",
                    str(path),
                    line,
                    f"条目 {index} 缺少非空 stage",
                )
            )
        component = entry.get("component")
        if not isinstance(component, str) or not component.strip():
            problems.append(
                Problem(
                    "friction-missing-field",
                    str(path),
                    line,
                    f"条目 {index} 缺少非空 component",
                )
            )
    return problems


def filter_entries(
    store: dict,
    *,
    category: str | None = None,
    component: str | None = None,
    severity: str | None = None,
) -> list[dict]:
    selected: list[dict] = []
    for entry in store.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if category is not None and entry.get("category") != category:
            continue
        if component is not None and entry.get("component") != component:
            continue
        if severity is not None and entry.get("severity") != severity:
            continue
        selected.append(entry)
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="记录和查看工作流摩擦")
    parser.add_argument(
        "--store",
        default=DEFAULT_STORE,
        help=f"JSON store 路径（默认: {DEFAULT_STORE}）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="新增一条摩擦记录")
    add.add_argument("--stage", required=True)
    add.add_argument("--component", required=True)
    add.add_argument("--category", required=True, choices=VALID_CATEGORIES)
    add.add_argument("--severity", required=True, choices=VALID_SEVERITIES)
    add.add_argument("--description", required=True)
    add.add_argument("--workaround")

    list_parser = sub.add_parser("list", help="查看摩擦记录")
    list_parser.add_argument("--category", choices=VALID_CATEGORIES)
    list_parser.add_argument("--component")
    list_parser.add_argument("--severity", choices=VALID_SEVERITIES)

    sub.add_parser("check", help="重新校验 store 中的每条记录")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "add":
            entry = add_entry(
                Path(args.store),
                stage=args.stage,
                component=args.component,
                category=args.category,
                severity=args.severity,
                description=args.description,
                workaround=args.workaround,
            )
            print(f"已记录摩擦条目 #{entry['id']}", file=sys.stderr)
            return 0
        if args.command == "list":
            entries = filter_entries(
                load_store(Path(args.store)),
                category=args.category,
                component=args.component,
                severity=args.severity,
            )
            print(
                json.dumps(
                    entries,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        return emit(check_store(Path(args.store)))
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
