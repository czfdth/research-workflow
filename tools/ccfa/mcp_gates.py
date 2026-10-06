"""Read-only MCP server exposing this workflow's gates to other agents.

The workflow's value to a generating agent (Codex, ARIS, open-science) is that
it can *check* things, but until now the only way to reach it was to shell out
to a CLI. This exposes the four read-only views over the Model Context Protocol
so any MCP client can ask:

* ``readiness`` — is this paper ready, and what blocks it;
* ``worklist`` — the ordered human tasks with their packets and criteria;
* ``argument_audit`` — proof / citation / figure review status;
* ``e2e_check`` — the one-page snapshot;
* ``doctor`` — is the toolchain healthy.

Two properties are deliberate and tested:

1. **Read-only by construction.** Every tool is a pure query over files that
   already exist. There is no tool that advances a stage, writes a ledger,
   marks a review complete or applies a patch — a generating agent may ask
   "what does the gate say", never "make the gate pass".
2. **No gate is re-implemented here.** Each tool calls the same function the
   CLI calls, so an agent cannot get a different answer than a human does.

Transport is stdio with newline-delimited JSON-RPC 2.0 (no dependencies). The
``call`` subcommand runs one tool without an MCP client, which is what the
tests and quick manual checks use.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from ccfa import argument_audit, e2e_check, quickstart, readiness, worklist
from ccfa import doctor
from ccfa.cli import tool_error

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "ccfa-gates"
SERVER_VERSION = "0.1.0"


def _tool_readiness(arguments: dict) -> dict:
    paper_root = Path(arguments.get("paper_root", "."))
    profile = arguments.get("profile")
    report = readiness.build_report(paper_root, profile=profile)
    gates = {
        item["name"]: {
            "status": item["status"],
            "problem_count": item["problem_count"],
            "problems": [p["code"] for p in item.get("problems", [])],
        }
        for item in report.get("gate_results", [])
    }
    return {
        "ready": report.get("ready"),
        "stage": report.get("stage", {}).get("current"),
        "gate": report.get("stage", {}).get("gate"),
        "blocking": report.get("blocking", []),
        "dimensions": report.get("dimensions", {}),
        "gates": gates,
        "human_pending": report.get("human_review", {}).get("pending", []),
    }


def _tool_worklist(arguments: dict) -> dict:
    return worklist.collect(Path(arguments.get("paper_root", ".")))


def _tool_argument_audit(arguments: dict) -> dict:
    problems, advisories = argument_audit.check(Path(arguments.get("paper_root", ".")))
    return {
        "problem_count": len(problems),
        "problems": [{"code": p.code, "message": p.message} for p in problems],
        "advisories": [{"code": a.code, "message": a.message} for a in advisories],
    }


def _tool_e2e_check(arguments: dict) -> dict:
    paper_root = Path(arguments.get("paper_root", "."))
    report = readiness.build_report(paper_root)
    repo_root = Path(arguments.get("repo_root") or paper_root.parent.parent)
    env_problems, env_advisories, env_statuses = doctor.check_environment(repo_root)
    snapshot = e2e_check.render_snapshot(
        report,
        env_problems,
        env_advisories,
        env_statuses,
        today=date.today(),
        history=e2e_check.read_history(paper_root),
    )
    return {"markdown": snapshot}


def _tool_doctor(arguments: dict) -> dict:
    repo_root = Path(arguments.get("repo_root", "."))
    problems, advisories, statuses = doctor.check_environment(repo_root)
    return {
        "problem_count": len(problems),
        "advisory_count": len(advisories),
        "problems": [{"code": p.code, "message": p.message} for p in problems],
        "advisories": [{"code": a.code, "message": a.message} for a in advisories],
        "status_count": len(statuses),
    }


def _tool_brief(arguments: dict) -> dict:
    return quickstart.collect(
        Path(arguments.get("repo_root", ".")),
        paper_root=Path(arguments["paper_root"])
        if arguments.get("paper_root")
        else None,
    )


# Tool name -> (callable, description, JSON-schema properties, required)
TOOLS: dict[str, tuple[Callable[[dict], dict], str, dict, list[str]]] = {
    "brief": (
        _tool_brief,
        "环境 + 论文列表 + 当前唯一该做的下一步（等价于 quickstart）",
        {
            "repo_root": {"type": "string"},
            "paper_root": {"type": "string"},
        },
        [],
    ),
    "readiness": (
        _tool_readiness,
        "这篇论文是否 ready、卡在哪些 gate（等价于 readiness）",
        {
            "paper_root": {"type": "string"},
            "profile": {"type": "string", "enum": list(readiness.PROFILES)},
        },
        ["paper_root"],
    ),
    "worklist": (
        _tool_worklist,
        "按阻塞优先级排序的人工待办，含 packet、台账与完成判据（等价于 worklist）",
        {"paper_root": {"type": "string"}},
        ["paper_root"],
    ),
    "argument_audit": (
        _tool_argument_audit,
        "证明 / 引用语义 / 图表语义三项人工台账的状态（等价于 argument-audit）",
        {"paper_root": {"type": "string"}},
        ["paper_root"],
    ),
    "e2e_check": (
        _tool_e2e_check,
        "单篇论文的一页式现状快照（等价于 e2e-check）",
        {"paper_root": {"type": "string"}},
        ["paper_root"],
    ),
    "doctor": (
        _tool_doctor,
        "工具链与环境健康（等价于 doctor，非 strict）",
        {"repo_root": {"type": "string"}},
        [],
    ),
}


def tool_descriptors() -> list[dict]:
    """The MCP ``tools/list`` payload."""
    return [
        {
            "name": name,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        }
        for name, (_fn, description, properties, required) in sorted(TOOLS.items())
    ]


def call_tool(name: str, arguments: dict) -> dict:
    """Run one read-only tool; raises ValueError on an unknown or bad call."""
    entry = TOOLS.get(name)
    if entry is None:
        raise ValueError(
            f"未知工具: {name!r}，可用: {', '.join(sorted(TOOLS))}"
        )
    function, _description, _properties, required = entry
    if not isinstance(arguments, dict):
        raise ValueError("arguments 必须是对象")
    missing = [key for key in required if not str(arguments.get(key, "")).strip()]
    if missing:
        raise ValueError(f"{name} 缺少参数: {', '.join(missing)}")
    return function(arguments)


def _result(request_id: object, payload: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            ],
            "isError": False,
        },
    }


def _error(request_id: object, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle(request: dict) -> dict | None:
    """Handle one JSON-RPC message; returns None for notifications."""
    if not isinstance(request, dict):
        return _error(None, -32600, "请求必须是对象")
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None and isinstance(method, str) and method.startswith(
        "notifications/"
    ):
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "只读门禁：只回答 gate 结论，不提供任何写入或开释操作。"
                ),
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tool_descriptors()},
        }
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            payload = call_tool(str(name), arguments)
        except (OSError, ValueError) as exc:
            return _error(request_id, -32602, str(exc))
        return _result(request_id, payload)
    return _error(request_id, -32601, f"不支持的方法: {method!r}")


def serve(stdin, stdout) -> int:
    """Serve newline-delimited JSON-RPC until stdin closes."""
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            stdout.write(
                json.dumps(_error(None, -32700, f"JSON 解析失败: {exc}")) + "\n"
            )
            stdout.flush()
            continue
        response = handle(request)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "只读 MCP 门禁服务：把 readiness / worklist / argument-audit / "
            "e2e-check / doctor 暴露给其他 agent（不含任何写入操作）"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="用 stdio 提供 MCP 服务")
    sub.add_parser("list-tools", help="打印 tools/list 的内容")
    call = sub.add_parser("call", help="直接调用一个工具（不需要 MCP 客户端）")
    call.add_argument("--tool", required=True)
    call.add_argument(
        "--arg",
        action="append",
        default=[],
        help="KEY=VALUE，可重复",
    )
    return parser


def _parse_args_pairs(pairs: list[str]) -> dict:
    arguments: dict = {}
    for raw in pairs:
        key, separator, value = raw.partition("=")
        if not separator or not key:
            raise ValueError(f"--arg 必须写成 KEY=VALUE: {raw!r}")
        arguments[key] = value
    return arguments


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "serve":
            return serve(sys.stdin, sys.stdout)
        if args.command == "list-tools":
            print(json.dumps(tool_descriptors(), ensure_ascii=False, indent=2))
            return 0
        payload = call_tool(args.tool, _parse_args_pairs(args.arg))
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
