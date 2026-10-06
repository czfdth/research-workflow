"""Scaffold a new ``tools/ccfa`` CLI module and wire every inventory at once.

Adding a module by hand means six files move together: the dispatcher
(``tools/ccfa/dispatch.py``), the wrapper manifest
(``tools/tests/test_scripts.py``), the docs manifest
(``tools/tests/test_docs_consistency.py``), the CI compile list
(``.github/workflows/tests.yml``), the impact selector
(``tools/ccfa/test_impact.py``) and the README module table. Landing them one
at a time is exactly the ordering mistake that turns CI red, so ``create``
computes every edit first, refuses on any missing anchor, and only then
writes, in one pass.

``audit`` is the read-only counterpart: it reports every module with a
``main()`` that is missing from an inventory (and every inventory entry that
points at a module which does not exist), so drift becomes a message instead
of a red pipeline.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
MODULE_DIR = "tools/ccfa"
WRAPPER_DIR = "scripts"
TEST_DIR = "tools/tests"
DISPATCH_PATH = "tools/ccfa/dispatch.py"
WRAPPER_MANIFEST = "tools/tests/test_scripts.py"
DOCS_MANIFEST = "tools/tests/test_docs_consistency.py"
WORKFLOW_PATH = ".github/workflows/tests.yml"
IMPACT_PATH = "tools/ccfa/test_impact.py"
README_PATH = "README.md"

_MODULE_TEMPLATE = '''"""__SUMMARY__

契约见 docs/workflow-guide.md 的「新增模块」一节：本模块的 CLI 与
scripts/__DASHED__.ps1 同名同参，check 只输出 problem/advisory，不修改论文。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, tool_error


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Return (problems, advisories) for one paper root.

    TODO: implement the deterministic check. Until then the module reports a
    single advisory instead of a pass, so an unfinished scaffold can never be
    mistaken for a green gate.
    """

    paper_root = Path(paper_root)
    return [], [
        Problem(
            "__DASHED__-not-implemented",
            str(paper_root),
            None,
            "脚手架生成的 __NAME__ 还没有实现检查逻辑",
        )
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="__SUMMARY__")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="校验当前论文")
    check_parser.add_argument("--paper-root", default=".")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check(Path(args.paper_root))
            return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知命令: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''

_WRAPPER_TEMPLATE = """$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
& "$root/tools/.venv/Scripts/python.exe" -m ccfa.__NAME__ @args
exit $LASTEXITCODE
"""

_TEST_TEMPLATE = '''"""Tests for :mod:`ccfa.__NAME__`."""

from __future__ import annotations

import unittest
from pathlib import Path

from ccfa import __NAME__


class __CAMEL__Tests(unittest.TestCase):
    def test_check_reports_the_scaffold_advisory_until_implemented(self):
        problems, advisories = __NAME__.check(Path("."))

        self.assertEqual(problems, [])
        self.assertEqual(len(advisories), 1)
        self.assertEqual(advisories[0].code, "__DASHED__-not-implemented")
'''


class ScaffoldError(ValueError):
    """A missing anchor, a taken name, or a malformed inventory file."""


def _line_ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _render(template: str, name: str, summary: str) -> str:
    dashed = name.replace("_", "-")
    camel = "".join(part.capitalize() for part in name.split("_"))
    return (
        template.replace("__SUMMARY__", summary)
        .replace("__DASHED__", dashed)
        .replace("__CAMEL__", camel)
        .replace("__NAME__", name)
    )


def _require_main(text: str, where: str) -> None:
    tree = ast.parse(text, filename=where)
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main"
        for node in tree.body
    ):
        raise ScaffoldError(f"{where} 必须定义顶层 main()")


def _insert_after(
    text: str,
    needle: str,
    new_line: str,
    *,
    where: str,
) -> str:
    """Insert *new_line* directly after the first line containing *needle*.

    Every manifest adds the newest entry at the top of its dict or list, so
    this matches the surrounding convention instead of appending at the end.
    """

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if needle in line:
            lines.insert(index + 1, new_line + _line_ending(text))
            return "".join(lines)
    raise ScaffoldError(f"{where} 里找不到锚点: {needle}")


def _append_readme_row(text: str, row: str, *, where: str) -> str:
    lines = text.splitlines(keepends=True)
    header = None
    for index, line in enumerate(lines):
        if "| 模块 |" in line:
            header = index
            break
    if header is None:
        raise ScaffoldError(f"{where} 里找不到模块表头 `| 模块 |`")
    last = header
    for index in range(header + 1, len(lines)):
        if lines[index].lstrip().startswith("|"):
            last = index
            continue
        break
    lines.insert(last + 1, row + _line_ending(text))
    return "".join(lines)


def _literal_dict(text: str, opener: str, *, where: str) -> dict:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if opener in line:
            start = index
            break
    if start is None:
        raise ScaffoldError(f"{where} 里找不到锚点: {opener}")
    body: list[str] = []
    for index in range(start + 1, len(lines)):
        if lines[index].strip() == "}":
            break
        body.append(lines[index])
    else:
        raise ScaffoldError(f"{where} 的 {opener} 没有闭合行")
    try:
        payload = ast.literal_eval("{" + "\n".join(body) + "}")
    except (SyntaxError, ValueError) as exc:
        raise ScaffoldError(f"{where} 的 {opener} 不是字面量字典: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScaffoldError(f"{where} 的 {opener} 不是字典")
    return payload


def _modules_with_main(root: Path) -> set[str]:
    modules: set[str] = set()
    directory = root / MODULE_DIR
    if not directory.is_dir():
        return modules
    for path in sorted(directory.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
            for node in tree.body
        ):
            modules.add(path.stem)
    return modules


def create(root: Path, name: str, summary: str) -> dict:
    """Write the module, its wrapper and test stub, and every inventory entry."""

    root = Path(root)
    if not NAME_PATTERN.match(name) or name == "__init__":
        raise ScaffoldError(
            f"模块名非法: {name!r}；要求小写字母开头，只含小写字母、数字和下划线"
        )
    dashed = name.replace("_", "-")
    summary = summary.strip() or f"{dashed} gate"
    module_path = root / MODULE_DIR / f"{name}.py"
    if module_path.exists():
        raise ScaffoldError(f"{MODULE_DIR}/{name}.py 已存在，脚手架不会覆盖")
    wrapper_path = root / WRAPPER_DIR / f"{dashed}.ps1"
    if wrapper_path.exists():
        raise ScaffoldError(f"{WRAPPER_DIR}/{dashed}.ps1 已存在，脚手架不会覆盖")
    test_path = root / TEST_DIR / f"test_{name}.py"
    if test_path.exists():
        raise ScaffoldError(f"{TEST_DIR}/test_{name}.py 已存在，脚手架不会覆盖")

    required = [
        DISPATCH_PATH,
        WRAPPER_MANIFEST,
        DOCS_MANIFEST,
        WORKFLOW_PATH,
        IMPACT_PATH,
        README_PATH,
    ]
    for relative in required:
        if not (root / relative).is_file():
            raise ScaffoldError(f"清单文件不存在: {relative}")

    module_text = _render(_MODULE_TEMPLATE, name, summary)
    _require_main(module_text, f"{MODULE_DIR}/{name}.py")
    test_text = _render(_TEST_TEMPLATE, name, summary)
    ast.parse(test_text, filename=f"{TEST_DIR}/test_{name}.py")

    edits: list[tuple[Path, str]] = [
        (module_path, module_text),
        (wrapper_path, _render(_WRAPPER_TEMPLATE, name, summary)),
        (test_path, test_text),
    ]

    dispatch_path = root / DISPATCH_PATH
    dispatch_text = dispatch_path.read_text(encoding="utf-8")
    edits.append(
        (
            dispatch_path,
            _insert_after(
                dispatch_text,
                "COMMANDS: dict[str, str] = {",
                f'    "{dashed}": "ccfa.{name}",',
                where=DISPATCH_PATH,
            ),
        )
    )

    wrapper_manifest_path = root / WRAPPER_MANIFEST
    wrapper_manifest_text = wrapper_manifest_path.read_text(encoding="utf-8")
    edits.append(
        (
            wrapper_manifest_path,
            _insert_after(
                wrapper_manifest_text,
                "CCFA_WRAPPERS = {",
                f'    "{name}": "{dashed}.ps1",',
                where=WRAPPER_MANIFEST,
            ),
        )
    )

    docs_manifest_path = root / DOCS_MANIFEST
    docs_manifest_text = docs_manifest_path.read_text(encoding="utf-8")
    edits.append(
        (
            docs_manifest_path,
            _insert_after(
                docs_manifest_text,
                "CLI_WRAPPERS = {",
                f'    "{name}": "scripts/{dashed}.ps1",',
                where=DOCS_MANIFEST,
            ),
        )
    )

    workflow_path = root / WORKFLOW_PATH
    workflow_text = workflow_path.read_text(encoding="utf-8")
    # PowerShell continues a command with a backtick, not a backslash; using
    # the wrong one silently truncates the compile list at that line.
    edits.append(
        (
            workflow_path,
            _insert_after(
                workflow_text,
                "py_compile",
                f"            tools/ccfa/{name}.py `",
                where=WORKFLOW_PATH,
            ),
        )
    )

    impact_path = root / IMPACT_PATH
    impact_text = impact_path.read_text(encoding="utf-8")
    impact_entry = "\n".join(
        [
            f'    "tools/ccfa/{name}.py": (',
            f'        "tools.tests.test_{name}",',
            '        "tools.tests.test_docs_consistency",',
            '        "tools.tests.test_scripts",',
            "    ),",
        ]
    )
    edits.append(
        (
            impact_path,
            _insert_after(
                impact_text,
                "_TOOLS_EXACT = {",
                impact_entry,
                where=IMPACT_PATH,
            ),
        )
    )

    readme_path = root / README_PATH
    readme_text = readme_path.read_text(encoding="utf-8")
    readme_row = (
        f"| `tools/ccfa/{name}.py` | {summary} | `scripts/{dashed}.ps1` |"
    )
    edits.append(
        (readme_path, _append_readme_row(readme_text, readme_row, where=README_PATH))
    )

    for path, text in edits:
        relative = str(path.relative_to(root)).replace("\\", "/")
        if path.suffix == ".py":
            ast.parse(text, filename=relative)
        save_text_atomically(path, text, description=relative)
    return {
        "module": f"ccfa.{name}",
        "command": dashed,
        "summary": summary,
        "files": [
            str(path.relative_to(root)).replace("\\", "/") for path, _text in edits
        ],
    }


def audit(root: Path) -> list[Problem]:
    """Report drift between the modules on disk and the inventories that bind.

    Two inventories are contract-bound and checked both ways: the wrapper and
    docs manifests must name exactly the modules that define ``main()``, and
    every wrapper they name must exist. The dispatcher is checked by value, so
    the irregular aliases (``archive`` -> ``ccfa.archive_client``,
    ``statistics`` -> ``ccfa.stats_plan``) stay legal. The CI compile list and
    the impact selector are deliberately *not* audited: the compile list only
    carries the core modules and the impact selector falls back to the full
    suite for anything unrouted, so a missing entry there is not drift.
    """

    root = Path(root)
    problems: list[Problem] = []

    def report(code: str, path: str, message: str) -> None:
        problems.append(Problem(code, path, None, message))

    modules = _modules_with_main(root)
    inventories: dict[str, set[str]] = {}

    def read_dict(relative: str, opener: str) -> dict:
        text = (root / relative).read_text(encoding="utf-8")
        return _literal_dict(text, opener, where=relative)

    dispatch = read_dict(DISPATCH_PATH, "COMMANDS: dict[str, str] = {")
    wrapper_manifest = read_dict(WRAPPER_MANIFEST, "CCFA_WRAPPERS = {")
    docs_manifest = read_dict(DOCS_MANIFEST, "CLI_WRAPPERS = {")
    inventories["wrapper-manifest"] = {str(key) for key in wrapper_manifest}
    inventories["docs-manifest"] = {str(key) for key in docs_manifest}
    dispatched = {str(value) for value in dispatch.values()}

    readme_text = (root / README_PATH).read_text(encoding="utf-8")
    for name in sorted(modules):
        dashed = name.replace("_", "-")
        if f"ccfa.{name}" not in dispatched:
            report(
                "new-module-missing-dispatch",
                DISPATCH_PATH,
                f"{name} 的模块没有被任何 dispatch 命令指向",
            )
        if name not in inventories["wrapper-manifest"]:
            report(
                "new-module-missing-wrapper-manifest",
                WRAPPER_MANIFEST,
                f"{name} 没有 CCFA_WRAPPERS 条目",
            )
        if name not in inventories["docs-manifest"]:
            report(
                "new-module-missing-docs-manifest",
                DOCS_MANIFEST,
                f"{name} 没有 CLI_WRAPPERS 条目",
            )
        if name not in readme_text:
            report(
                "new-module-missing-readme",
                README_PATH,
                f"{name} 没有出现在 README 里",
            )
        wrapper_file = wrapper_manifest.get(name, f"{dashed}.ps1")
        if not (root / WRAPPER_DIR / str(wrapper_file)).is_file():
            report(
                "new-module-missing-wrapper-file",
                f"{WRAPPER_DIR}/{wrapper_file}",
                f"{name} 缺少 PowerShell 包装器",
            )
        documented = docs_manifest.get(name)
        if isinstance(documented, str) and documented not in readme_text:
            report(
                "new-module-missing-readme-entry",
                README_PATH,
                f"README 没有点名 {documented}",
            )
        # No test-file check: the repository has never required a test module
        # named after its subject (stats_plan is covered from other modules),
        # and inventing that rule here would report drift that is not drift.

    for label, code, path in (
        ("wrapper-manifest", "new-module-stale-wrapper-manifest", WRAPPER_MANIFEST),
        ("docs-manifest", "new-module-stale-docs-manifest", DOCS_MANIFEST),
    ):
        stale = {
            entry
            for entry in inventories[label]
            if entry.replace("-", "_") not in modules
        }
        for entry in sorted(stale):
            report(
                code,
                path,
                f"清单里有 {entry!r}，但 {MODULE_DIR}/{entry}.py 没有 main()",
            )
    for entry, target in sorted(dispatch.items()):
        if not str(target).startswith("ccfa."):
            continue
        module_name = str(target).split(".", 1)[1]
        if module_name not in modules:
            report(
                "new-module-stale-dispatch",
                DISPATCH_PATH,
                f"命令 {entry!r} 指向 {target}，但 {MODULE_DIR}/{module_name}.py 没有 main()",
            )
    return problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="新增 ccfa 模块的一体化脚手架与清单审计"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create", help="创建模块并一次性接好六份清单")
    create_parser.add_argument("name", help="模块名，如 cost_metrics")
    create_parser.add_argument("--summary", default="", help="README 里的一句话作用")
    create_parser.add_argument("--root", default=None, help="仓库根目录（默认自动定位）")
    create_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要写入的文件，不落盘",
    )
    audit_parser = sub.add_parser("audit", help="审计六份清单与磁盘是否一致")
    audit_parser.add_argument("--root", default=None, help="仓库根目录（默认自动定位）")
    return parser


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else _repo_root()
    try:
        if args.command == "create":
            if args.dry_run:
                payload = {
                    "module": f"ccfa.{args.name}",
                    "command": args.name.replace("_", "-"),
                    "dry_run": True,
                }
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            payload = create(root, args.name, args.summary)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            for relative in payload["files"]:
                print(f"已写入 {relative}", file=sys.stderr)
            print(
                "下一步：实现 check()，补一条 docs/workflow-change-log.jsonl "
                "记录，再跑 scripts/test-impact.ps1。",
                file=sys.stderr,
            )
            return 0
        if args.command == "audit":
            return emit(audit(root), [])
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知命令: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
