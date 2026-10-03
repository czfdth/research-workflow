"""Deterministic tools exposed to the chat engine.

Read-only tools run immediately. Write tools require an explicit confirmation
callback and are declined when no callback is provided. Every call is audited
to ``<paper_root>/ccfa-workfiles/agent-tools.jsonl``; the audit stores only a
truncated sha256 digest of the arguments, never the arguments themselves.

``run-log run`` (arbitrary command execution) is deliberately not exposed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple

from ccfa import library, memory, milestones, state, trace_claims
from ccfa.cli import save_text_atomically

READ = "read"
WRITE = "write"

AUDIT_RELATIVE = Path("ccfa-workfiles") / "agent-tools.jsonl"


class ToolArgumentError(ValueError):
    """Raised when tool arguments do not match the declared schema."""


class Tool(NamedTuple):
    name: str
    description: str
    risk: str
    parameters: dict
    handler: Callable[[Path, dict], Any]


def _schema(properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _resolve_within(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("路径必须是非空字符串")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError(f"路径必须是相对路径: {raw!r}")
    root = Path(root).resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"路径越出论文根: {raw!r}") from None
    return resolved


def _tool_milestones_stage(root: Path, args: dict) -> dict:
    # The CLI ``stage`` subcommand uses the same private report function.
    return milestones._stage_report(root)


def _tool_milestones_due(root: Path, args: dict) -> dict:
    raw_today = args.get("today")
    if raw_today is None:
        today = date.today()
    else:
        today = milestones.parse_deadline(raw_today)
        if today is None:
            raise ValueError("today 不能为空字符串")
    return milestones.due_report(root, today)


def _tool_library_search(root: Path, args: dict) -> dict:
    return library.search_index(
        Path(root) / "library",
        args["query"],
        limit=args.get("limit", 20),
    )


def _tool_memory_search(root: Path, args: dict) -> dict:
    return memory.search_memory(root, args["query"])


def _tool_memory_list(root: Path, args: dict) -> dict:
    return memory.list_memory(
        root,
        kind=args.get("kind", "all"),
        status=args.get("status"),
    )


def _tool_memory_add_idea(root: Path, args: dict) -> dict:
    return memory.add_idea(
        root,
        idea=args["idea"],
        date=args["date"],
        status=args.get("status", "active"),
        notes=args.get("notes"),
    )


def _tool_memory_add_dead_end(root: Path, args: dict) -> dict:
    return memory.add_dead_end(
        root,
        idea=args["idea"],
        date=args["date"],
        reason=args["reason"],
        evidence=args["evidence"],
        reopen_if=args["reopen_if"],
    )


def _tool_state_set_stage(root: Path, args: dict) -> dict:
    # The GUI confirmation already happened; ``confirm`` stays mandatory in
    # the underlying implementation, which is the ``--confirm`` semantics.
    return state.set_stage(
        root,
        to=args["to"],
        reason=args["reason"],
        confirm=True,
    )


def _tool_state_rollback(root: Path, args: dict) -> dict:
    return state.rollback(
        root,
        to=args["to"],
        reason=args["reason"],
        confirm=True,
        void_artifacts=args.get("void_artifacts"),
    )


def _tool_trace_claims_check(root: Path, args: dict) -> dict:
    docs = [_resolve_within(root, raw) for raw in args["docs"]]
    base_dir = None
    if args.get("base_dir") is not None:
        base_dir = _resolve_within(root, args["base_dir"])
    problems, advisories = trace_claims.check(
        docs,
        base_dir=base_dir,
        untagged=args.get("untagged", True),
    )
    return {
        "problems": [dict(problem._asdict()) for problem in problems],
        "advisories": [dict(item._asdict()) for item in advisories],
        "problem_count": len(problems),
    }


TOOL_DEFINITIONS: tuple[Tool, ...] = (
    Tool(
        name="milestones_stage",
        description="读取论文当前 stage、gate 与 updated_at（只读）。",
        risk=READ,
        parameters=_schema({}),
        handler=_tool_milestones_stage,
    ),
    Tool(
        name="milestones_due",
        description=(
            "读取投稿倒排里程碑报告；可选 today=YYYY-MM-DD 注入日期（只读）。"
        ),
        risk=READ,
        parameters=_schema(
            {"today": {"type": "string", "description": "YYYY-MM-DD"}}
        ),
        handler=_tool_milestones_due,
    ),
    Tool(
        name="library_search",
        description=(
            "在 project/library/index.db 中检索文献元数据（只读，"
            "不含 PDF 全文）。"
        ),
        risk=READ,
        parameters=_schema(
            {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            required=("query",),
        ),
        handler=_tool_library_search,
    ),
    Tool(
        name="memory_search",
        description="检索 research memory 的 idea 与 dead-end（只读）。",
        risk=READ,
        parameters=_schema(
            {"query": {"type": "string"}},
            required=("query",),
        ),
        handler=_tool_memory_search,
    ),
    Tool(
        name="memory_list",
        description="列出 research memory，可按 kind/status 过滤（只读）。",
        risk=READ,
        parameters=_schema(
            {
                "kind": {
                    "type": "string",
                    "enum": ["all", "ideas", "dead-ends"],
                },
                "status": {"type": "string"},
            }
        ),
        handler=_tool_memory_list,
    ),
    Tool(
        name="memory_add_idea",
        description="写入一条 idea；这是写操作，执行前需要用户确认。",
        risk=WRITE,
        parameters=_schema(
            {
                "idea": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "status": {"type": "string"},
                "notes": {"type": "string"},
            },
            required=("idea", "date"),
        ),
        handler=_tool_memory_add_idea,
    ),
    Tool(
        name="memory_add_dead_end",
        description=(
            "写入一条 dead-end 及 reopen_if；这是写操作，执行前需要用户确认。"
        ),
        risk=WRITE,
        parameters=_schema(
            {
                "idea": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "reason": {"type": "string"},
                "evidence": {"type": "string"},
                "reopen_if": {"type": "string"},
            },
            required=("idea", "date", "reason", "evidence", "reopen_if"),
        ),
        handler=_tool_memory_add_dead_end,
    ),
    Tool(
        name="state_set_stage",
        description=(
            "推进 ccfa.yaml 的 stage（只允许向后推进）；这是写操作，"
            "执行前需要用户确认。"
        ),
        risk=WRITE,
        parameters=_schema(
            {"to": {"type": "string"}, "reason": {"type": "string"}},
            required=("to", "reason"),
        ),
        handler=_tool_state_set_stage,
    ),
    Tool(
        name="state_rollback",
        description=(
            "回退 ccfa.yaml 的 stage 并记录作废产物；这是写操作，"
            "执行前需要用户确认。"
        ),
        risk=WRITE,
        parameters=_schema(
            {
                "to": {"type": "string"},
                "reason": {"type": "string"},
                "void_artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            required=("to", "reason"),
        ),
        handler=_tool_state_rollback,
    ),
    Tool(
        name="trace_claims_check",
        description=(
            "核验正文 \\dataval 标签与源数据一致，并默认给出未标记数字提示"
            "（只读）。"
        ),
        risk=READ,
        parameters=_schema(
            {
                "docs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "base_dir": {"type": "string"},
                "untagged": {"type": "boolean"},
            },
            required=("docs",),
        ),
        handler=_tool_trace_claims_check,
    ),
)

_TOOLS_BY_NAME = {tool.name: tool for tool in TOOL_DEFINITIONS}

_TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: type(value) is int,
    "boolean": lambda value: type(value) is bool,
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}


def openai_tools() -> list[dict]:
    """Return fresh OpenAI function-calling specs for every tool."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": copy.deepcopy(tool.parameters),
            },
        }
        for tool in TOOL_DEFINITIONS
    ]


def _validate_arguments(schema: dict, arguments: Any) -> None:
    if not isinstance(arguments, dict):
        raise ToolArgumentError("参数必须是 JSON 对象")
    properties = schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ToolArgumentError(f"未知参数: {', '.join(unknown)}")
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise ToolArgumentError(f"缺少参数: {', '.join(missing)}")
    for name, value in arguments.items():
        declared = properties[name]
        check = _TYPE_CHECKS.get(declared.get("type"))
        if check is not None and not check(value):
            raise ToolArgumentError(f"参数 {name} 必须是 {declared['type']}")
        if declared.get("enum") is not None and value not in declared["enum"]:
            raise ToolArgumentError(
                f"参数 {name} 必须是 {' / '.join(declared['enum'])}"
            )
        if declared.get("type") == "array":
            min_items = declared.get("minItems")
            if min_items is not None and len(value) < min_items:
                raise ToolArgumentError(f"参数 {name} 至少需要 {min_items} 项")
            item_schema = declared.get("items")
            if item_schema is not None:
                item_check = _TYPE_CHECKS.get(item_schema.get("type"))
                if item_check is not None:
                    for item in value:
                        if not item_check(item):
                            raise ToolArgumentError(
                                f"参数 {name} 的每一项必须是 "
                                f"{item_schema['type']}"
                            )


def _digest(arguments: Any) -> str:
    payload = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        default=repr,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(name: Any, code: str, message: str) -> dict:
    return {
        "ok": False,
        "tool": name,
        "error": {"code": code, "message": message},
    }


class ToolBridge:
    """Dispatch model tool calls against one paper project."""

    def __init__(
        self,
        project_root: Path,
        *,
        confirm_write: Callable[[str, dict], bool] | None = None,
        on_call: Callable[[dict], None] | None = None,
    ):
        self.project_root = Path(project_root)
        self._confirm_write = confirm_write
        self._on_call = on_call
        self._tools = dict(_TOOLS_BY_NAME)

    def risk(self, name: str) -> str:
        return self._tools[name].risk

    def execute(self, name: Any, arguments: Any = None) -> dict:
        if arguments is None:
            arguments = {}
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            result = _error(name, "unknown-tool", f"未知工具: {name!r}")
            self._finish(name, arguments, "unknown", "unknown-tool", result)
            return result
        try:
            _validate_arguments(tool.parameters, arguments)
        except ToolArgumentError as exc:
            result = _error(name, "invalid-arguments", str(exc))
            self._finish(name, arguments, tool.risk, "invalid", result)
            return result
        if tool.risk == WRITE:
            allowed = False
            if self._confirm_write is not None:
                try:
                    allowed = bool(
                        self._confirm_write(name, dict(arguments))
                    )
                except Exception:
                    allowed = False
            if not allowed:
                result = _error(name, "user-declined", "user declined")
                self._finish(name, arguments, tool.risk, "declined", result)
                return result
        try:
            value = tool.handler(self.project_root, arguments)
        except Exception as exc:
            result = _error(
                name,
                "tool-error",
                f"{type(exc).__name__}: {exc}",
            )
            self._finish(name, arguments, tool.risk, "error", result)
            return result
        result = {
            "ok": True,
            "tool": name,
            "risk": tool.risk,
            "result": value,
        }
        self._finish(name, arguments, tool.risk, "ok", result)
        return result

    def _finish(
        self,
        name: Any,
        arguments: Any,
        risk: str,
        outcome: str,
        result: dict,
    ) -> None:
        error = self._audit(name, arguments, risk, outcome)
        if error is not None:
            result["audit_error"] = error
        if self._on_call is not None:
            try:
                self._on_call(
                    {
                        "tool": name,
                        "risk": risk,
                        "outcome": outcome,
                    }
                )
            except Exception:
                pass

    def _audit(
        self,
        name: Any,
        arguments: Any,
        risk: str,
        outcome: str,
    ) -> str | None:
        entry = {
            "time": _utc_now(),
            "tool": name if isinstance(name, str) else str(name),
            "args_digest": _digest(arguments),
            "risk": risk,
            "outcome": outcome,
        }
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        path = self.project_root / AUDIT_RELATIVE
        try:
            existing = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        except OSError as exc:
            return f"{type(exc).__name__}: {exc}"
        if existing and not existing.endswith("\n"):
            existing += "\n"
        try:
            save_text_atomically(
                path,
                existing + line,
                description="工具审计日志",
            )
        except (OSError, ValueError) as exc:
            return f"{type(exc).__name__}: {exc}"
        return None
