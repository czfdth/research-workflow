"""Write one durable record for each computational run."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ccfa import cli
from ccfa.cli import ToolEnvironmentError, tool_error


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump_record(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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
        resolved = path.resolve()
        relative = resolved.relative_to(root.resolve()).as_posix()
        raw = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取配置 {path}: {exc}") from exc
    try:
        content = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法解析配置 {path}: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    return {"path": relative, "sha256": f"sha256:{digest}", "content": content}


def _subprocess_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(list(argv), cwd=str(cwd), check=False)
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

    args = parser.parse_args(argv[1:])
    if args.subcommand != "run":
        return tool_error(f"未知子命令: {args.subcommand}")

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

    print(run_id)
    if args.propagate_exit:
        return int(record["exit_code"])
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
