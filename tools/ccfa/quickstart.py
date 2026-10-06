"""One command that answers "is the toolchain healthy, where are my papers, what next".

The daily entry point was three commands plus reading: ``doctor`` for the
environment, ``dashboard`` for the paper list, ``worklist`` for the single next
human action. Each is right on its own; together they were the reason a fresh
session always began with a round of orientation.

This composes them, read-only, into one screen:

* environment — ``doctor`` problem/advisory counts;
* papers — the dashboard one-liner and the focus paper's stage/readiness;
* next — the first item from ``worklist``, with the packet to read, the ledger
  to write and the criterion its own checker enforces.

It adds no gate and changes no verdict, and it never hides a failing doctor:
problems are printed in full before the summary. Exit 0 means the brief was
produced, not that the paper is ready — ``ready`` is in the output, and
``readiness`` remains the thing that decides it.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ccfa import dashboard, doctor, readiness, worklist
from ccfa.cli import tool_error

SCHEMA_VERSION = 1
DEFAULT_PAPERS_ROOT = Path("papers")


def _doctor_brief(repo_root: Path) -> dict:
    problems, advisories, statuses = doctor.check_environment(repo_root)
    interesting = [
        line
        for line in statuses
        if line.startswith(("MISSING", "reachable", "functional"))
    ]
    return {
        "problems": [
            {"code": item.code, "message": item.message} for item in problems
        ],
        "advisories": [
            {"code": item.code, "message": item.message} for item in advisories
        ],
        "problem_count": len(problems),
        "advisory_count": len(advisories),
        "service_status": interesting[:8],
    }


def _papers_brief(
    papers_root: Path,
    *,
    profile: str | None,
    today: date | None,
) -> dict:
    if not papers_root.is_dir():
        return {
            "papers": [],
            "summary": {
                "paper_count": 0,
                "ready_count": 0,
                "blocked_count": 0,
                "human_pending_count": 0,
                "dirty_count": 0,
            },
            "missing_root": str(papers_root),
        }
    summary = dashboard.summarize(
        dashboard.collect_reports(papers_root, profile=profile, today=today)
    )
    return {
        "papers": [
            {
                "paper": item.get("paper"),
                "title": item.get("title"),
                "stage": item.get("stage"),
                "gate": item.get("gate"),
                "ready": item.get("ready"),
                "blocking_count": item.get("blocking_count"),
                "human_review": item.get("human_review"),
                "next_action": item.get("next_action"),
            }
            for item in summary.get("papers", [])
        ],
        "summary": {
            "paper_count": summary.get("paper_count", 0),
            "ready_count": summary.get("ready_count", 0),
            "blocked_count": summary.get("blocked_count", 0),
            "human_pending_count": summary.get("human_pending_count", 0),
            "dirty_count": summary.get("dirty_count", 0),
        },
        "missing_root": None,
    }


def _focus_paper(papers: dict, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    for item in papers.get("papers", []):
        if item.get("ready") is False and item.get("paper"):
            candidate = Path(papers["_root"]) / str(item["paper"])
            if (candidate / "ccfa.yaml").is_file():
                return candidate
    return None


def collect(
    repo_root: Path,
    *,
    papers_root: Path | None = None,
    paper_root: Path | None = None,
    profile: str | None = None,
    today: date | None = None,
) -> dict:
    """Compose the three existing views into one brief."""
    repo_root = Path(repo_root).resolve()
    papers_root = (
        Path(papers_root)
        if papers_root is not None
        else repo_root / DEFAULT_PAPERS_ROOT
    )
    environment = _doctor_brief(repo_root)
    papers = _papers_brief(papers_root, profile=profile, today=today)
    papers["_root"] = str(papers_root)
    focus = _focus_paper(papers, paper_root)
    next_action = None
    if focus is not None and (Path(focus) / "ccfa.yaml").is_file():
        try:
            plan = worklist.collect(Path(focus))
        except (OSError, ValueError):
            plan = {"items": []}
        if plan.get("items"):
            next_action = plan["items"][0]
    papers.pop("_root", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "repo_root": str(repo_root),
        "environment": environment,
        "papers": papers,
        "focus": str(focus) if focus is not None else None,
        "next_action": next_action,
    }


def render_markdown(payload: dict) -> str:
    env = payload["environment"]
    papers = payload["papers"]
    summary = papers.get("summary") or {}
    lines = [
        "# ccfa quickstart",
        "",
        "## 环境",
        "",
        f"- doctor: {env['problem_count']} problems, {env['advisory_count']} advisories",
    ]
    for item in env["problems"]:
        lines.append(f"  - P: `{item['code']}` {item['message']}")
    for item in env["advisories"]:
        lines.append(f"  - A: `{item['code']}` {item['message']}")
    for status in env["service_status"]:
        lines.append(f"  - `{status}`")
    lines.extend(["", "## 论文", ""])
    if papers.get("missing_root"):
        lines.append(f"- 找不到 {papers['missing_root']}（还没有论文）")
    else:
        lines.append(
            f"- 共 {summary.get('paper_count', 0)} 篇："
            f"ready {summary.get('ready_count', 0)}、"
            f"blocked {summary.get('blocked_count', 0)}、"
            f"待人工 {summary.get('human_pending_count', 0)}"
        )
        for item in papers["papers"]:
            lines.append(
                f"- `{item['paper']}` stage={item['stage']} "
                f"gate={item['gate']} ready={item['ready']} "
                f"阻塞={item['blocking_count']} 人工={item['human_review']}"
            )
    lines.extend(["", "## 下一步（一条）", ""])
    action = payload.get("next_action")
    if action is None:
        lines.append("- 没有待办项（或还没有可检查的论文）")
    else:
        marker = " **[阻塞]**" if action["implicated_by_blocking"] else ""
        lines.append(f"### `{action['id']}`{marker}")
        lines.append("")
        lines.append(f"- 要判断什么：{action.get('question')}")
        if action.get("progress"):
            lines.append(f"- 当前进度：{action['progress']}")
        if action.get("read_first"):
            lines.append(
                "- 先读：" + "、".join(f"`{p}`" for p in action["read_first"])
            )
        if action.get("write_into"):
            lines.append(f"- 写进：`{action['write_into']}`")
        if action.get("finished_when"):
            lines.append(f"- 完成判据：{action['finished_when']}")
        if action.get("checked_by"):
            lines.append(f"- 谁校验：`{action['checked_by']}`")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 这条命令只做汇总，不校验任何东西，也不改变任何 gate 结论；",
            "- `ready` 由 `readiness` 判定，人工复核只能由人签字；",
            "- 投稿前仍需 `scripts/doctor.ps1 --strict`。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "一条命令给出：环境健康、论文列表与当前唯一该做的下一步"
            "（组合 doctor / dashboard / worklist，只读）"
        )
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--papers-root", default=None)
    parser.add_argument("--paper-root", default=None)
    parser.add_argument("--profile", choices=readiness.PROFILES, default=None)
    parser.add_argument("--today", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default=None)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        payload = collect(
            Path(args.repo_root),
            papers_root=Path(args.papers_root) if args.papers_root else None,
            paper_root=Path(args.paper_root) if args.paper_root else None,
            profile=args.profile,
            today=date.fromisoformat(args.today) if args.today else None,
        )
        text = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.json
            else render_markdown(payload)
        )
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(text, end="")
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
