"""Check deadline-relative milestone checkpoints and gate gaps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

from ccfa.cli import Problem, tool_error
from ccfa.stages import gate_for, stages_for

_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_CHECKPOINT_STAGES = {
    "T-14": "internal-review",
    "T-7": "internal-review",
    "T-3": "submission-check",
}
_SEQUENTIAL_ADVISORY = "无投稿目标日，按顺序推进"


def parse_deadline(value: object) -> date | None:
    """Parse an optional YYYY-MM-DD deadline."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"deadline 必须是 YYYY-MM-DD 日期字符串: {value!r}"
        )
    text = value.strip()
    if not text:
        return None
    if _DATE_PATTERN.fullmatch(text) is None:
        raise ValueError(f"deadline 非法: {value!r}，应为 YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"deadline 不是合法日期: {value!r}") from exc


def checkpoints(deadline: date) -> dict[str, date]:
    """Return the T-14, T-7 and T-3 checkpoint dates."""
    return {
        "T-14": deadline - timedelta(days=14),
        "T-7": deadline - timedelta(days=7),
        "T-3": deadline - timedelta(days=3),
    }


def _load_state(paper_root: Path) -> dict:
    path = Path(paper_root) / "ccfa.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    try:
        state = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败于 {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return state


def _problem(
    code: str,
    path: Path,
    message: str,
) -> dict:
    return dict(Problem(code, str(path), None, message)._asdict())


def _gate_problems(
    mode: str,
    current: str,
    target: str,
    path: Path,
) -> list[dict]:
    stages = stages_for(mode)
    current_index = stages.index(current)
    target_index = stages.index(target)
    if current_index > target_index:
        return []
    problems: list[dict] = []
    for stage in stages[current_index : target_index + 1]:
        gate = gate_for(mode, stage)
        problems.append(
            _problem(
                "milestone-gate-missing",
                path,
                f"stage {stage} gate {gate.id} 未完成: {gate.criterion}",
            )
        )
    return problems


def _due_item(checkpoint: str, checkpoint_date: date | None, mode: str, stage: str) -> dict:
    gate = gate_for(mode, stage)
    return {
        "checkpoint": checkpoint,
        "date": checkpoint_date.isoformat() if checkpoint_date else None,
        "stage": stage,
        "gate": gate.id,
        "criterion": gate.criterion,
    }


def due_report(paper_root: Path, today: date) -> dict:
    """Return a read-only milestone report for one injected date."""
    paper_root = Path(paper_root)
    state_path = paper_root / "ccfa.yaml"
    state = _load_state(paper_root)
    venue = state.get("target_venue")
    if not isinstance(venue, dict):
        raise ValueError(f"{state_path} 的 target_venue 必须是映射")

    mode = venue.get("mode", "conference")
    stages_for(mode)
    stage_data = state.get("stage")
    current = stage_data.get("current") if isinstance(stage_data, dict) else None
    stage_known = isinstance(current, str) and current in stages_for(mode)

    problems: list[dict] = []
    if not stage_known:
        problems.append(
            _problem(
                "stage-unknown",
                state_path,
                f"stage.current 不在 stages.py 中: {current!r}",
            )
        )
        current = None

    raw_deadline = venue.get("deadline")
    try:
        deadline = parse_deadline(raw_deadline)
    except ValueError as exc:
        if raw_deadline is not None and not isinstance(raw_deadline, str):
            raise
        problems.append(
            _problem("deadline-invalid", state_path, str(exc))
        )
        return {
            "mode": "countdown",
            "deadline": raw_deadline if isinstance(raw_deadline, str) else None,
            "due": [],
            "missing_gates": [],
            "problems": problems,
            "advisory": None,
        }

    if deadline is None:
        due: list[dict] = []
        advisory = _SEQUENTIAL_ADVISORY
        if stage_known:
            due.append(_due_item("next", None, mode, current))
        return {
            "mode": "sequential",
            "deadline": None,
            "due": due,
            "missing_gates": [],
            "problems": problems,
            "advisory": advisory,
        }

    due = []
    missing_gates: list[dict] = []
    if today > deadline:
        due.append(_due_item("overdue", deadline, mode, "submission-check"))
        problems.append(
            _problem(
                "deadline-passed",
                state_path,
                f"已超过投稿目标日 {deadline.isoformat()}",
            )
        )
        if stage_known:
            missing_gates = _gate_problems(
                mode,
                current,
                "submission-check",
                state_path,
            )
            problems.extend(missing_gates)
    else:
        checkpoint_dates = checkpoints(deadline)
        checkpoint = next(
            (
                name
                for name, checkpoint_date in checkpoint_dates.items()
                if today == checkpoint_date
            ),
            None,
        )
        if checkpoint is not None:
            target_stage = _CHECKPOINT_STAGES[checkpoint]
            stages = stages_for(mode)
            target_passed = (
                stage_known
                and stages.index(current) > stages.index(target_stage)
            )
            if not target_passed:
                due.append(
                    _due_item(
                        checkpoint,
                        checkpoint_dates[checkpoint],
                        mode,
                        target_stage,
                    )
                )
            if stage_known:
                missing_gates = _gate_problems(
                    mode,
                    current,
                    target_stage,
                    state_path,
                )
                problems.extend(missing_gates)

    return {
        "mode": "countdown",
        "deadline": deadline.isoformat(),
        "due": due,
        "missing_gates": missing_gates,
        "problems": problems,
        "advisory": None,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查投稿倒排里程碑")
    subparsers = parser.add_subparsers(dest="command", required=True)
    due = subparsers.add_parser("due", help="检查到期 checkpoint 与 gate 缺口")
    due.add_argument("--paper-root", default=".")
    due.add_argument("--today", help="注入今天日期 YYYY-MM-DD（默认系统日期）")
    args = parser.parse_args(argv[1:])

    try:
        today = parse_deadline(args.today) if args.today else date.today()
        if today is None:
            raise ValueError("--today 不能为空")
        report = due_report(Path(args.paper_root), today)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    for problem in report["problems"]:
        print(
            f"{problem['path']}: {problem['code']}: {problem['message']}",
            file=sys.stderr,
        )
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
