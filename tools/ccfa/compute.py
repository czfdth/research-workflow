"""Compute-backend discovery, budgeted execution, and attempt-cost ledger.

The workflow previously assumed "local machine plus a Docker sandbox", which
makes a pilot's cost invisible: nothing recorded how long an attempt took or
how much GPU time it burned. That is the throughput problem named in the
top-venue evaluation: when an attempt is expensive, teams rationally drift
into auditing instead of experimenting.

This module does three things:

* :func:`probe_local` reports the actual ceiling — CPU, RAM, every GPU and
  whether Docker exposes an NVIDIA runtime.
* :func:`plan` answers whether a backend can serve a pilot budget, and refuses
  to pretend a remote cluster exists when none is configured.
* :func:`run_local` executes a command under a wall-clock budget and appends a
  record to ``experiments/log/compute-ledger.jsonl`` with ``wall_seconds`` and
  ``gpu_minutes`` so ``cost_per_attempt`` becomes measurable rather than
  anecdotal.

Remote schedulers (Slurm, PBS/Torque) are adapters over SSH. They are absent
until a host is configured in ``data/compute.yaml``; :func:`probe_remote`
reports exactly that instead of reporting a false capability.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from ccfa.cli import Problem, emit, tool_error
from ccfa.toolchain import which as toolchain_which

COMPUTE_CONFIG = Path("data/compute.yaml")
COMPUTE_LEDGER = Path("experiments/log/compute-ledger.jsonl")

_PROBE_TIMEOUT_S = 20
# ``ssh`` is the universal remote: any host with an account, which covers a
# lab box and the SSH endpoint a rented GPU (Vast.ai, Modal, RunPod) hands out.
# ``slurm`` and ``pbs`` stay probe-only until a cluster is actually reachable.
_REMOTE_KINDS = ("ssh", "slurm", "pbs")
_EXECUTABLE_KINDS = ("ssh",)
_SSH_BATCH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=8")
# One round trip that proves the account works and reports any visible GPU, so
# a probe result can be audited instead of trusted.
_SSH_PROBE_COMMAND = (
    "printf 'ccfa-ok\\n'; "
    "(command -v nvidia-smi >/dev/null 2>&1 && "
    "nvidia-smi -L 2>/dev/null | head -n 8) || true"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Gpu:
    index: int
    name: str
    memory_mib: int
    compute_cap: str = ""


@dataclass
class LocalResources:
    cpu_count: int
    ram_gib: float
    gpus: list[Gpu] = field(default_factory=list)
    docker: bool = False
    docker_gpu: bool = False

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    def as_dict(self) -> dict:
        return {
            "cpu_count": self.cpu_count,
            "ram_gib": round(self.ram_gib, 1),
            "gpus": [
                {
                    "index": gpu.index,
                    "name": gpu.name,
                    "memory_mib": gpu.memory_mib,
                    "compute_cap": gpu.compute_cap,
                }
                for gpu in self.gpus
            ],
            "docker": self.docker,
            "docker_gpu": self.docker_gpu,
        }


def _default_run(argv: Sequence[str], timeout: float = _PROBE_TIMEOUT_S) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout or ""


def parse_nvidia_smi(output: str) -> list[Gpu]:
    """Parse ``--query-gpu=index,name,memory.total,compute_cap`` CSV output."""
    gpus: list[Gpu] = []
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        try:
            memory = int(float(cells[2].split()[0]))
        except (ValueError, IndexError):
            continue
        gpus.append(
            Gpu(
                index=int(cells[0]),
                name=cells[1],
                memory_mib=memory,
                compute_cap=cells[3] if len(cells) > 3 else "",
            )
        )
    return gpus


def _ram_gib() -> float:
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024**3)
    except (AttributeError, OSError):
        pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return pages * size / (1024**3)
    except (ValueError, OSError, AttributeError):
        return 0.0


def probe_local(
    *,
    which: Callable[[str], str | None] | None = None,
    run: Callable[[Sequence[str]], tuple[int, str]] | None = None,
    cpu_count: int | None = None,
    ram_gib: float | None = None,
) -> LocalResources:
    which = which or toolchain_which
    run = run or _default_run
    gpus: list[Gpu] = []
    if which("nvidia-smi"):
        code, output = run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,compute_cap",
                "--format=csv,noheader",
            ]
        )
        if code == 0:
            gpus = parse_nvidia_smi(output)
    docker = bool(which("docker"))
    docker_gpu = False
    if docker:
        code, output = run(["docker", "info", "--format", "{{json .Runtimes}}"])
        docker_gpu = code == 0 and "nvidia" in output
    return LocalResources(
        cpu_count=cpu_count if cpu_count is not None else (os.cpu_count() or 1),
        ram_gib=ram_gib if ram_gib is not None else _ram_gib(),
        gpus=gpus,
        docker=docker,
        docker_gpu=docker_gpu,
    )


@dataclass(frozen=True)
class RemoteBackend:
    kind: str
    host: str
    user: str = ""
    partition: str = ""
    gpus: int = 0
    name: str = ""
    port: int = 0
    workdir: str = ""
    identity_file: str = ""
    options: tuple[str, ...] = ()

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def label(self) -> str:
        return self.name or f"{self.kind}:{self.target}"

    @property
    def executable(self) -> bool:
        return self.kind in _EXECUTABLE_KINDS

    def as_dict(self) -> dict:
        return {
            "name": self.label,
            "kind": self.kind,
            "host": self.host,
            "user": self.user,
            "port": self.port,
            "partition": self.partition,
            "gpus": self.gpus,
            "workdir": self.workdir,
            "executable": self.executable,
            "identity_file": self.identity_file,
            "options": list(self.options),
        }


def _parse_backends_at(path: Path) -> tuple[list[RemoteBackend], list[Problem]]:
    """Parse one compute config file into backends plus structural problems."""
    path = Path(path)
    if not path.is_file():
        return [], []
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a problem, not a crash
        return [], [
            Problem(
                "compute-config-invalid",
                str(path),
                None,
                f"data/compute.yaml 无法解析: {type(exc).__name__}",
            )
        ]
    if not isinstance(payload, dict):
        return [], [
            Problem(
                "compute-config-invalid",
                str(path),
                None,
                "data/compute.yaml 顶层必须是映射",
            )
        ]
    entries = payload.get("backends")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        return [], [
            Problem(
                "compute-config-invalid",
                str(path),
                None,
                "backends 必须是列表",
            )
        ]
    backends: list[RemoteBackend] = []
    problems: list[Problem] = []
    seen: dict[str, int] = {}
    for index, item in enumerate(entries):
        where = f"backends[{index}]"
        if not isinstance(item, dict):
            problems.append(
                Problem(
                    "compute-config-invalid",
                    str(path),
                    None,
                    f"{where} 必须是映射",
                )
            )
            continue
        kind = item.get("kind")
        if kind not in _REMOTE_KINDS:
            problems.append(
                Problem(
                    "compute-backend-unknown-kind",
                    str(path),
                    None,
                    f"{where}.kind 非法: {kind!r}，"
                    f"应为 {'/'.join(_REMOTE_KINDS)}",
                )
            )
            continue
        host = item.get("host")
        if not isinstance(host, str) or not host.strip():
            problems.append(
                Problem(
                    "compute-backend-missing-host",
                    str(path),
                    None,
                    f"{where} 缺少 host",
                )
            )
            continue
        port = 0
        raw_port = item.get("port")
        if raw_port is not None:
            if (
                isinstance(raw_port, bool)
                or not isinstance(raw_port, int)
                or not 1 <= raw_port <= 65535
            ):
                problems.append(
                    Problem(
                        "compute-config-invalid",
                        str(path),
                        None,
                        f"{where}.port 必须是 1..65535 的整数",
                    )
                )
                continue
            port = raw_port
        gpus = 0
        raw_gpus = item.get("gpus")
        if raw_gpus is not None:
            if (
                isinstance(raw_gpus, bool)
                or not isinstance(raw_gpus, int)
                or raw_gpus < 0
            ):
                problems.append(
                    Problem(
                        "compute-config-invalid",
                        str(path),
                        None,
                        f"{where}.gpus 必须是非负整数",
                    )
                )
                continue
            gpus = raw_gpus
        raw_options = item.get("options")
        options: tuple[str, ...] = ()
        if raw_options is not None:
            if not isinstance(raw_options, list) or not all(
                isinstance(entry, str) for entry in raw_options
            ):
                problems.append(
                    Problem(
                        "compute-config-invalid",
                        str(path),
                        None,
                        f"{where}.options 必须是字符串列表",
                    )
                )
                continue
            options = tuple(raw_options)
        raw_identity = item.get("identity_file")
        if raw_identity is not None and not isinstance(raw_identity, str):
            problems.append(
                Problem(
                    "compute-config-invalid",
                    str(path),
                    None,
                    f"{where}.identity_file 必须是字符串",
                )
            )
            continue
        backend = RemoteBackend(
            kind=kind,
            host=host.strip(),
            user=str(item.get("user") or "").strip(),
            partition=str(item.get("partition") or "").strip(),
            gpus=gpus,
            name=str(item.get("name") or "").strip(),
            port=port,
            workdir=str(item.get("workdir") or "").strip(),
            identity_file=str(raw_identity or "").strip(),
            options=options,
        )
        if backend.label in seen:
            problems.append(
                Problem(
                    "compute-backend-duplicate-name",
                    str(path),
                    None,
                    f"{where} 与 backends[{seen[backend.label]}] 重名: "
                    f"{backend.label}",
                )
            )
            continue
        seen[backend.label] = index
        backends.append(backend)
    return backends, problems


def _parse_backends(
    paper_root: Path,
) -> tuple[list[RemoteBackend], list[Problem]]:
    """Parse the conventional ``<paper-root>/data/compute.yaml``."""

    return _parse_backends_at(Path(paper_root) / COMPUTE_CONFIG)


def load_backends(paper_root: Path) -> list[RemoteBackend]:
    """Read the valid backends from ``data/compute.yaml``.

    Invalid entries are skipped so a single typo cannot take down ``plan``.
    :func:`validate_config` reports them, and ``check`` treats them as
    blocking, so the loose read never hides a broken declaration.
    """

    backends, _problems = _parse_backends(paper_root)
    return backends


def validate_config(
    paper_root: Path,
) -> tuple[list[RemoteBackend], list[Problem]]:
    """Parse ``data/compute.yaml`` and return its structural problems."""

    return _parse_backends(paper_root)


def load_backend_file(
    path: Path,
) -> tuple[list[RemoteBackend], list[Problem]]:
    """Parse a compute config at an explicit path.

    The queue knows exactly which file its manifest points at, so it does not
    go through the ``<paper-root>/data/compute.yaml`` convention.
    """

    return _parse_backends_at(path)


def _ssh_argv(backend: RemoteBackend, remote_command: str) -> list[str]:
    argv = ["ssh", *_SSH_BATCH_OPTIONS]
    if backend.port:
        argv += ["-p", str(backend.port)]
    if backend.identity_file:
        argv += ["-i", backend.identity_file]
    argv += list(backend.options)
    argv += [backend.target, remote_command]
    return argv


def _ssh_remote_command(
    backend: RemoteBackend,
    command: Sequence[str],
    *,
    workdir: str | None = None,
) -> str:
    joined = " ".join(shlex.quote(str(part)) for part in command)
    directory = backend.workdir if workdir is None else workdir
    if directory:
        return f"cd {shlex.quote(directory)} && {joined}"
    return joined


def remote_argv(
    backend: RemoteBackend,
    command: Sequence[str],
    *,
    workdir: str | None = None,
) -> list[str]:
    """Build the argv that runs *command* on *backend*.

    Refuses kinds that cannot execute, so a scheduler host is never silently
    treated as a login box. ``workdir`` overrides the backend default, which is
    how a queue item asks to run somewhere other than the backend root.
    """

    if backend.kind not in _EXECUTABLE_KINDS:
        raise ValueError(
            f"后端 {backend.label!r} 的类型 {backend.kind!r} 暂不支持直接执行："
            "调度器提交尚未验证；请声明一个 kind: ssh 的主机，"
            "或在该集群上手动提交"
        )
    return _ssh_argv(
        backend,
        _ssh_remote_command(backend, command, workdir=workdir),
    )


def probe_remote(
    backend: RemoteBackend,
    *,
    run: Callable[[Sequence[str]], tuple[int, str]] | None = None,
) -> dict:
    """Check that SSH reaches *host* and the backend's tools answer."""
    run = run or _default_run
    if backend.kind == "ssh":
        command = _SSH_PROBE_COMMAND
    elif backend.kind == "slurm":
        command = "sbatch --version"
    else:
        command = "qstat --version"
    code, output = run(_ssh_argv(backend, command))
    result = {
        **backend.as_dict(),
        "reachable": code == 0,
        "detail": output.strip()[:200] if code == 0 else "SSH 或调度器不可用",
    }
    if backend.kind == "ssh":
        # The probe prints a known token; its presence is the receipt that the
        # account really ran something, not just that TCP answered.
        result["ccfa_ok"] = code == 0 and "ccfa-ok" in output
        result["gpus_observed"] = sum(
            1
            for line in output.splitlines()
            if line.strip().startswith("GPU ")
        )
    return result


@dataclass
class Attempt:
    command: str
    backend: str
    budget_minutes: float
    wall_seconds: float
    returncode: int
    gpus_used: int
    timed_out: bool

    @property
    def gpu_minutes(self) -> float:
        return round(self.wall_seconds / 60.0 * self.gpus_used, 3)

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "backend": self.backend,
            "budget_minutes": self.budget_minutes,
            "wall_seconds": round(self.wall_seconds, 2),
            "gpu_minutes": self.gpu_minutes,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "recorded_at": _now_iso(),
        }


def _execute(
    argv: Sequence[str],
    *,
    budget_minutes: float,
    gpus_used: int,
    backend: str,
    command_text: str,
    cwd: Path | None = None,
    popen: Callable[..., subprocess.Popen] | None = None,
) -> Attempt:
    runner = popen or subprocess.Popen
    started = time.monotonic()
    timed_out = False
    process = runner(
        list(argv),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        process.communicate(timeout=budget_minutes * 60)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.communicate()
    wall = time.monotonic() - started
    return Attempt(
        command=command_text,
        backend=backend,
        budget_minutes=budget_minutes,
        wall_seconds=wall,
        returncode=process.returncode if process.returncode is not None else -1,
        gpus_used=gpus_used,
        timed_out=timed_out,
    )


def run_local(
    command: Sequence[str],
    *,
    budget_minutes: float,
    gpus_used: int = 0,
    cwd: Path | None = None,
    popen: Callable[..., subprocess.Popen] | None = None,
) -> Attempt:
    """Run *command* under a wall-clock budget and return measured cost."""
    if budget_minutes <= 0:
        raise ValueError("budget_minutes 必须为正数")
    return _execute(
        list(command),
        budget_minutes=budget_minutes,
        gpus_used=gpus_used,
        backend="local",
        command_text=" ".join(str(part) for part in command),
        cwd=cwd,
        popen=popen,
    )


def run_remote(
    backend: RemoteBackend,
    command: Sequence[str],
    *,
    budget_minutes: float,
    gpus_used: int = 0,
    popen: Callable[..., subprocess.Popen] | None = None,
) -> Attempt:
    """Run *command* on a remote backend under a wall-clock budget.

    Only ``ssh`` executes today. A scheduler host is refused rather than
    silently treated as a login box: the probe still reports whether it is
    reachable, but nothing pretends a Slurm/PBS job was submitted.
    """
    if budget_minutes <= 0:
        raise ValueError("budget_minutes 必须为正数")
    argv = remote_argv(backend, command)
    return _execute(
        argv,
        budget_minutes=budget_minutes,
        gpus_used=gpus_used,
        backend=f"ssh:{backend.target}",
        command_text=argv[-1],
        popen=popen,
    )


def append_attempt(paper_root: Path, attempt: Attempt) -> Path:
    path = Path(paper_root) / COMPUTE_LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(attempt.as_dict(), ensure_ascii=False) + "\n")
    return path


def plan(
    paper_root: Path,
    *,
    budget_minutes: float,
    needs_gpu: bool = False,
    resources: LocalResources | None = None,
    backends: list[RemoteBackend] | None = None,
) -> dict:
    """Decide which backends can serve a pilot, without overstating reach."""
    resources = resources or probe_local()
    if backends is None:
        backends, config_problems = validate_config(paper_root)
    else:
        config_problems = []
    local_ok = not needs_gpu or resources.gpu_count > 0
    return {
        "budget_minutes": budget_minutes,
        "needs_gpu": needs_gpu,
        "local": {
            "usable": local_ok,
            "gpus": resources.gpu_count,
            "docker_gpu": resources.docker_gpu,
            "note": (
                "本地 GPU 秒预算可用" if local_ok else "本机无 GPU，pilot 只能 CPU 级或需要远程算力"
            ),
        },
        "remote": [backend.as_dict() for backend in backends],
        "remote_configured": bool(backends),
        "executable_remote": any(backend.executable for backend in backends),
        "config_problems": [problem._asdict() for problem in config_problems],
        "recommendation": (
            "local" if local_ok and not backends else ("remote" if backends else "blocked")
        ),
    }


def check_environment(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Report compute capability as problems (blocking) and advisories."""
    resources = probe_local()
    backends, config_problems = validate_config(paper_root)
    problems: list[Problem] = list(config_problems)
    advisories: list[Problem] = []
    path = Path(paper_root) / COMPUTE_CONFIG
    if not resources.gpu_count and not backends:
        advisories.append(
            Problem(
                "compute-no-gpu-no-remote",
                str(path),
                None,
                "本机无 GPU 且未配置远程算力：experiment-loop 的 pilot 受限",
            )
        )
    if not any(backend.executable for backend in backends):
        advisories.append(
            Problem(
                "compute-remote-unconfigured",
                str(path),
                None,
                "未配置可执行远程后端（kind: ssh；Slurm/PBS 目前只能探测，"
                "不能提交）",
            )
        )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="算力探测、pilot 预算执行与单次尝试成本台账")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="探测本机 CPU/内存/GPU/Docker 与远程后端")
    probe.add_argument("--paper-root", default=".")
    check_parser = sub.add_parser(
        "check",
        help="以 problem/advisory 形式报告算力缺口",
    )
    check_parser.add_argument("--paper-root", default=".")

    plan_parser = sub.add_parser("plan", help="判断某预算能否被某个后端承接")
    plan_parser.add_argument("--paper-root", default=".")
    plan_parser.add_argument("--minutes", type=float, required=True)
    plan_parser.add_argument("--needs-gpu", action="store_true")

    validate_parser = sub.add_parser(
        "validate",
        help="校验 data/compute.yaml 的后端声明",
    )
    validate_parser.add_argument("--paper-root", default=".")

    run_parser = sub.add_parser("run", help="在墙钟预算内执行命令并记账")
    run_parser.add_argument("--paper-root", default=".")
    run_parser.add_argument("--minutes", type=float, required=True)
    run_parser.add_argument("--gpus", type=int, default=0)
    run_parser.add_argument(
        "--backend",
        default=None,
        help="data/compute.yaml 里声明的后端名；省略则在本机执行",
    )
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "probe":
            resources = probe_local()
            backends = load_backends(Path(args.paper_root))
            payload = {
                "local": resources.as_dict(),
                "remote": [probe_remote(backend) for backend in backends],
                "remote_configured": bool(backends),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check":
            problems, advisories = check_environment(Path(args.paper_root))
            return emit(problems, advisories)
        if args.command == "validate":
            _backends, problems = validate_config(Path(args.paper_root))
            return emit(problems, [])
        if args.command == "plan":
            payload = plan(
                Path(args.paper_root),
                budget_minutes=args.minutes,
                needs_gpu=args.needs_gpu,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            if payload["recommendation"] == "blocked":
                print(
                    "PILOT 受阻：无可用算力承接该预算",
                    file=sys.stderr,
                )
                return 1
            return 0
        command = [item for item in args.command if item != "--"]
        if not command:
            return tool_error("run 需要一条命令")
        if args.backend:
            backends = load_backends(Path(args.paper_root))
            match = next(
                (item for item in backends if item.label == args.backend),
                None,
            )
            if match is None:
                return tool_error(
                    f"未找到后端 {args.backend!r}；"
                    "先在 data/compute.yaml 声明"
                )
            attempt = run_remote(
                match,
                command,
                budget_minutes=args.minutes,
                gpus_used=args.gpus,
            )
        else:
            attempt = run_local(
                command,
                budget_minutes=args.minutes,
                gpus_used=args.gpus,
            )
        path = append_attempt(Path(args.paper_root), attempt)
        print(json.dumps(attempt.as_dict(), ensure_ascii=False))
        print(f"已记录到 {path}", file=sys.stderr)
        return 1 if attempt.timed_out else attempt.returncode
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
