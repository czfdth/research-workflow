"""Run experiment queues with explicit retry and budget stop conditions.

The injected runner contract is ``runner(argv, cwd, timeout_s) -> int``.
It may raise ``subprocess.TimeoutExpired`` or ``TimeoutError``. The default
runner uses ``subprocess.Popen(..., shell=False)``, streams 子进程 stdout/stderr
line by line and forwards both 转发到 stderr so queue stdout 只输出 JSON.
Timeouts still forward output that was already produced.

Timeouts retry only when the manifest explicitly sets
``retry_on_timeout: true``. A cwd 不存在 is a runtime error: that attempt still
gets a failed run-log record, then the queue raises ValueError and exits 2.

For automation consumption, ``queue run`` stdout 只输出 JSON. Child output
remains visible without corrupting the machine-readable result. This differs
deliberately from ``run-log run``, which passes stdio through.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

from ccfa.cli import tool_error
from ccfa.run_log import log_metrics, run_command

QUEUE_VERSION = 1


def _load_payload(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取队列清单 {path}: {exc}") from exc
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"队列清单解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("队列清单顶层必须是对象")
    return payload


def load_queue(path: Path) -> list[dict]:
    """Load and normalize a queue manifest."""
    path = Path(path)
    payload = _load_payload(path)
    if payload.get("schema_version") != QUEUE_VERSION:
        raise ValueError(
            f"队列 schema_version 必须是 {QUEUE_VERSION}: "
            f"{payload.get('schema_version')!r}"
        )
    items = None
    for key in ("queue", "items", "runs"):
        if key in payload:
            items = payload[key]
            break
    if not isinstance(items, list):
        raise ValueError("队列清单必须包含 queue/items/runs 列表")

    normalized: list[dict] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"队列第 {index} 项必须是对象")
        name = item.get("name")
        command = item.get("command")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"队列第 {index} 项缺少非空 name")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise ValueError(f"队列第 {index} 项 command 必须是非空字符串列表")
        cwd = item.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError(f"队列第 {index} 项 cwd 必须是字符串")
        timeout_s = item.get("timeout_s")
        if timeout_s is not None and (
            not isinstance(timeout_s, (int, float))
            or isinstance(timeout_s, bool)
            or timeout_s <= 0
        ):
            raise ValueError(f"队列第 {index} 项 timeout_s 必须是正数")
        retry_exit_codes = item.get("retry_exit_codes", [])
        if not isinstance(retry_exit_codes, list) or not all(
            type(code) is int for code in retry_exit_codes
        ):
            raise ValueError(
                f"队列第 {index} 项 retry_exit_codes 必须是整数列表"
            )
        retry_on_timeout = item.get("retry_on_timeout", False)
        if not isinstance(retry_on_timeout, bool):
            raise ValueError(
                f"队列第 {index} 项 retry_on_timeout 必须是布尔值"
            )
        max_attempts = item.get("max_attempts", 1)
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError(f"队列第 {index} 项 max_attempts 必须是正整数")
        normalized.append(
            {
                "name": name,
                "command": list(command),
                "cwd": cwd,
                "timeout_s": timeout_s,
                "retry_exit_codes": list(retry_exit_codes),
                "retry_on_timeout": retry_on_timeout,
                "max_attempts": max_attempts,
            }
        )
    return normalized


def _forward_stream(stream) -> None:
    try:
        for line in stream:
            sys.stderr.write(line)
            flush = getattr(sys.stderr, "flush", None)
            if flush is not None:
                flush()
    finally:
        stream.close()


def _default_runner(argv: list[str], cwd: Path, timeout_s: float | None) -> int:
    process = subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    pumps = [
        threading.Thread(
            target=_forward_stream,
            args=(process.stdout,),
            daemon=True,
        ),
        threading.Thread(
            target=_forward_stream,
            args=(process.stderr,),
            daemon=True,
        ),
    ]
    for pump in pumps:
        pump.start()
    try:
        returncode = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        process.wait()
        for pump in pumps:
            pump.join()
        raise
    for pump in pumps:
        pump.join()
    return int(returncode)


def _item_cwd(queue_root: Path, item: dict) -> Path:
    cwd = item.get("cwd")
    if not cwd:
        return queue_root
    path = Path(cwd)
    resolved = path if path.is_absolute() else queue_root / path
    return resolved.resolve()


def run_queue(
    queue_path: Path,
    *,
    log_dir: Path,
    runner=None,
    budget_s: float | None = None,
    clock=None,
) -> dict:
    """Run queue items in order and return per-run outcomes."""
    queue_path = Path(queue_path)
    queue_root = queue_path.parent
    log_dir = Path(log_dir)
    if budget_s is not None and budget_s < 0:
        raise ValueError("budget_s 必须是非负数")
    run = runner or _default_runner
    now = clock or time.monotonic
    items = load_queue(queue_path)

    started = now()
    runs: list[dict] = []
    stopped: str | None = None
    for index, item in enumerate(items):
        if budget_s is not None and now() - started >= budget_s:
            for skipped in items[index:]:
                runs.append(
                    {
                        "name": skipped["name"],
                        "attempts": 0,
                        "status": "skipped-budget",
                    }
                )
            stopped = "budget"
            break

        cwd = _item_cwd(queue_root, item)
        attempts = 0
        status = "failed"
        while attempts < item["max_attempts"]:
            attempts += 1
            timed_out = False

            def attempt_runner(argv, attempt_cwd):
                nonlocal timed_out
                try:
                    code = run(
                        list(argv),
                        Path(attempt_cwd),
                        item["timeout_s"],
                    )
                except (subprocess.TimeoutExpired, TimeoutError):
                    timed_out = True
                    return 124, ""
                return int(code), ""

            run_id, record = run_command(
                item["command"],
                log_dir,
                cwd,
                cwd=str(cwd),
                runner=attempt_runner,
            )
            exit_code = record["exit_code"]
            if timed_out:
                log_metrics(
                    log_dir,
                    run_id,
                    {"timeout": True, "timeout_s": item["timeout_s"]},
                )
            if exit_code == 0:
                status = "complete"
                break
            if timed_out:
                status = "timeout"
            else:
                status = "failed"
            retryable = (
                exit_code in item["retry_exit_codes"]
                or (timed_out and item["retry_on_timeout"])
            )
            if retryable and attempts < item["max_attempts"]:
                continue
            if retryable and item["max_attempts"] > 1:
                stopped = "retries"
            break

        runs.append(
            {
                "name": item["name"],
                "attempts": attempts,
                "status": status,
            }
        )
        if stopped == "retries":
            break

    return {"runs": runs, "stopped": stopped}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "顺序运行实验队列。超时仅在 retry_on_timeout=true 时重试；"
            "cwd 不存在时该次尝试仍写 failed 记录，整体退出 2。"
            "stdout 只输出结果 JSON；子进程 stdout/stderr 流式转发到 stderr。"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="运行队列")
    run.add_argument("--queue", required=True)
    run.add_argument("--log-dir", required=True)
    run.add_argument("--budget-seconds", type=float)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        result = run_queue(
            Path(args.queue),
            log_dir=Path(args.log_dir),
            budget_s=args.budget_seconds,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if any(item["status"] != "complete" for item in result["runs"]):
        return 1
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
