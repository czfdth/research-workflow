"""Write one durable record for each computational run."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import date, datetime, time as datetime_time, timezone
from pathlib import Path

import yaml

from ccfa import cli
from ccfa.cli import Problem, ToolEnvironmentError, emit, save_text_atomically, tool_error


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump_record(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _json_safe(value):
    if isinstance(value, dict):
        return {
            key if isinstance(key, str) else str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _save_record(path: Path, record: dict) -> None:
    cli.save_text_atomically(path, _dump_record(record), description="运行记录")


def new_run_id(log_dir: Path, stamp: str | None = None) -> tuple[str, Path]:
    log_dir = Path(log_dir)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"无法创建运行记录目录 {log_dir}: {exc}") from exc

    counter = 1
    while True:
        run_id = f"{stamp}-{counter:02d}"
        path = log_dir / f"{run_id}.json"
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write("{}")
        except FileExistsError:
            counter += 1
            continue
        except OSError as exc:
            raise ValueError(f"无法占位运行记录 {path}: {exc}") from exc
        return run_id, path


def git_state(paper_root: Path) -> tuple[str | None, bool]:
    paper_root = Path(paper_root)
    commands = (
        ["git", "-C", str(paper_root), "rev-parse", "HEAD"],
        ["git", "-C", str(paper_root), "status", "--porcelain"],
    )
    results = []
    try:
        for command in commands:
            results.append(
                subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
            )
    except (OSError, subprocess.TimeoutExpired):
        return None, False

    head, status = results
    if head.returncode != 0 or status.returncode != 0:
        return None, False
    commit = head.stdout.strip() or None
    dirty = bool(status.stdout.strip())
    return commit, dirty


def read_config(path: Path, *, paper_root: Path) -> dict:
    path = Path(path)
    root = Path(paper_root)
    try:
        resolved = path if path.is_absolute() else root / path
        resolved = resolved.resolve()
        relative = resolved.relative_to(root.resolve()).as_posix()
        raw = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取配置 {path}: {exc}") from exc
    try:
        content = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法解析配置 {path}: {exc}") from exc
    content = _json_safe(content)
    digest = hashlib.sha256(raw).hexdigest()
    return {"path": relative, "sha256": f"sha256:{digest}", "content": content}


def _subprocess_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd),
        check=False,
        stdout=sys.stderr,
    )
    return completed.returncode, ""


def run_command(
    argv: list[str],
    log_dir: Path,
    paper_root: Path,
    *,
    config: Path | None = None,
    seed: str | None = None,
    notes: str | None = None,
    runner=None,
) -> tuple[str, dict]:
    argv = list(argv)
    if not argv:
        raise ValueError("运行命令不能为空")
    log_dir = Path(log_dir)
    paper_root = Path(paper_root)
    runner = runner or _subprocess_runner

    run_id, record_path = new_run_id(log_dir)
    config_entry = read_config(config, paper_root=paper_root) if config else None
    commit, dirty = git_state(paper_root)
    started_at = _now_iso()
    started = time.monotonic()
    record = {
        "run_id": run_id,
        "command": argv,
        "cwd": ".",
        "config": config_entry,
        "seed": seed,
        "git_commit": commit,
        "git_dirty": dirty,
        "started_at": started_at,
        "finished_at": None,
        "duration_s": None,
        "exit_code": None,
        "status": "running",
        "metrics": None,
        "notes": notes,
    }
    _save_record(record_path, record)

    try:
        exit_code, _output = runner(argv, paper_root)
    except OSError as exc:
        finished_at = _now_iso()
        record.update(
            finished_at=finished_at,
            duration_s=round(time.monotonic() - started, 6),
            exit_code=127,
            status="failed",
        )
        _save_record(record_path, record)
        raise ValueError(f"无法运行命令 {argv[0]!r}: {exc}") from exc

    finished_at = _now_iso()
    record.update(
        finished_at=finished_at,
        duration_s=round(time.monotonic() - started, 6),
        exit_code=int(exit_code),
        status="completed" if exit_code == 0 else "failed",
    )
    _save_record(record_path, record)
    return run_id, record


def record_path(log_dir: Path, run_id: str) -> Path:
    return Path(log_dir) / f"{run_id}.json"


def log_metrics(log_dir: Path, run_id: str, metrics: dict) -> dict:
    if not isinstance(metrics, dict):
        raise ValueError("metrics 必须是 JSON 对象")
    path = record_path(log_dir, run_id)
    if not path.is_file():
        raise ValueError(f"没有这条运行记录: {run_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"运行记录不是对象: {run_id}")
    record["metrics"] = metrics
    save_text_atomically(
        path,
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="运行记录",
    )
    return record


def _parse_started(value: object) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


def check_runs(
    log_dir: Path,
    stale_hours: float = 24.0,
    now: datetime | None = None,
) -> tuple[list[Problem], list[Problem]]:
    log_dir = Path(log_dir)
    reference = now or datetime.now(timezone.utc)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not log_dir.is_dir():
        return problems, advisories
    for path in sorted(log_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(
                Problem("run-log-malformed", str(path), None, f"运行记录不可读: {exc}")
            )
            continue
        if not isinstance(record, dict) or "status" not in record:
            problems.append(
                Problem(
                    "run-log-malformed",
                    str(path),
                    None,
                    "运行记录缺少 status 字段",
                )
            )
            continue
        status = record.get("status")
        started = _parse_started(record.get("started_at"))
        if status not in {"running", "completed", "failed"}:
            problems.append(
                Problem(
                    "run-log-malformed",
                    str(path),
                    None,
                    f"运行记录 status 非法: {status!r}",
                )
            )
            continue
        if status == "running":
            if started is None:
                problems.append(
                    Problem(
                        "run-log-malformed",
                        str(path),
                        None,
                        "running 记录缺少可解析的 started_at",
                    )
                )
            elif (reference - started).total_seconds() > stale_hours * 3600:
                problems.append(
                    Problem(
                        "run-log-stale-running",
                        str(path),
                        None,
                        f"记录停留在 running 超过 {stale_hours:g} 小时: {record.get('run_id')}",
                    )
                )
            continue
        if status == "completed":
            metrics = record.get("metrics")
            if metrics is None:
                problems.append(
                    Problem(
                        "run-log-metrics-pending",
                        str(path),
                        None,
                        f"运行已完成但未登记指标: {record.get('run_id')}",
                    )
                )
            elif not isinstance(metrics, dict):
                problems.append(
                    Problem(
                        "run-log-malformed",
                        str(path),
                        None,
                        f"运行记录的 metrics 不是对象: {record.get('run_id')}",
                    )
                )
            elif metrics == {}:
                problems.append(
                    Problem(
                        "run-log-empty-metrics",
                        str(path),
                        None,
                        f"运行指标为空对象: {record.get('run_id')}",
                    )
                )
        if not record.get("git_commit"):
            problems.append(
                Problem(
                    "run-log-missing-commit",
                    str(path),
                    None,
                    f"记录缺少 git commit: {record.get('run_id')}",
                )
            )
        if record.get("git_dirty") is True:
            advisories.append(
                Problem(
                    "run-log-dirty-tree",
                    str(path),
                    None,
                    f"该运行发生在脏树上，无法仅凭 commit 复现: {record.get('run_id')}",
                )
            )
    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="记录并运行一次计算")
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--paper-root", required=True)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    run = sub.add_parser("run", help="运行命令并写入运行记录")
    run.add_argument("--config")
    run.add_argument("--seed")
    run.add_argument("--notes")
    run.add_argument("--propagate-exit", action="store_true")
    run.add_argument("command", nargs=argparse.REMAINDER)

    metrics = sub.add_parser("log-metrics", help="为已有运行记录登记指标")
    metrics.add_argument("run_id")
    metrics.add_argument("--metrics", required=True)

    check = sub.add_parser("check", help="检查运行记录完整性")
    check.add_argument("--stale-hours", type=float, default=24.0)

    args = parser.parse_args(argv[1:])
    if args.subcommand == "log-metrics":
        try:
            parsed_metrics = json.loads(args.metrics)
            record = log_metrics(Path(args.log_dir), args.run_id, parsed_metrics)
        except (ValueError, OSError) as exc:
            return tool_error(str(exc))
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return 0

    if args.subcommand == "check":
        return emit(
            *check_runs(
                Path(args.log_dir),
                stale_hours=args.stale_hours,
            )
        )

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        return tool_error("run 需要 `--` 后的命令")

    try:
        run_id, record = run_command(
            command,
            Path(args.log_dir),
            Path(args.paper_root),
            config=Path(args.config) if args.config else None,
            seed=args.seed,
            notes=args.notes,
        )
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))

    print(
        json.dumps(
            {
                "run_id": run_id,
                "status": record["status"],
                "exit_code": record["exit_code"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    print(
        f"运行 {run_id}: {record['status']} (exit_code={record['exit_code']})",
        file=sys.stderr,
    )
    if args.propagate_exit:
        return int(record["exit_code"])
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
