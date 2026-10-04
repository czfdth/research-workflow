"""Report which platform pieces this workflow can actually use.

The workflow is deliberately coupled to a few local tools (git, a LaTeX
toolchain, codex, Docker, nvidia-smi) and to two virtualenvs. When one is
missing, the failure shows up later as a confusing crash inside an unrelated
step, so this preflight names what is absent and which capability it disables.
It never installs anything and never writes files.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, NamedTuple

from ccfa.cli import Problem, emit


class Dependency(NamedTuple):
    key: str
    executables: tuple[str, ...]
    required: bool
    capability: str
    daemon_args: tuple[str, ...] | None = None


class Venv(NamedTuple):
    key: str
    relative: str
    capability: str


DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency(
        "git",
        ("git",),
        True,
        "论文独立仓库、版本快照与 run-log commit",
    ),
    Dependency(
        "pdflatex",
        ("pdflatex",),
        False,
        "LaTeX 编译（latex-check --compile）",
    ),
    Dependency("bibtex", ("bibtex",), False, "参考文献编译"),
    Dependency("xelatex", ("xelatex",), False, "中文文稿编译"),
    Dependency(
        "codex",
        ("codex",),
        False,
        "cross-review run 与工作台 codex 引擎",
    ),
    Dependency(
        "docker",
        ("docker",),
        False,
        "queue 的 sandbox=docker 沙箱后端",
        daemon_args=("info", "--format", "{{.ServerVersion}}"),
    ),
    Dependency("nvidia-smi", ("nvidia-smi",), False, "queue 的 GPU 秒预算"),
)

VENVS: tuple[Venv, ...] = (
    Venv("tools", "tools/.venv", "所有 scripts/*.ps1 包装器与工具侧测试"),
    Venv("app", "app/.venv", "论文工作台 GUI 与 app 测试"),
)

_VENV_SUFFIXES = (
    Path("Scripts") / "python.exe",
    Path("bin") / "python",
)

_DAEMON_TIMEOUT_S = 15


def _default_which(name: str) -> str | None:
    return shutil.which(name)


def _default_run(argv: list[str]) -> int:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_DAEMON_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return 1
    return completed.returncode


def _venv_python(
    repo_root: Path,
    relative: str,
    path_exists: Callable[[Path], bool],
) -> Path | None:
    for suffix in _VENV_SUFFIXES:
        candidate = Path(repo_root) / relative / suffix
        if path_exists(candidate):
            return candidate
    return None


def check_environment(
    repo_root: Path,
    *,
    which: Callable[[str], str | None] | None = None,
    path_exists: Callable[[Path], bool] | None = None,
    dependencies: tuple[Dependency, ...] = DEPENDENCIES,
    venvs: tuple[Venv, ...] = VENVS,
    strict: bool = False,
    run: Callable[[list[str]], int] | None = None,
) -> tuple[list[Problem], list[Problem], list[str]]:
    """Return (problems, advisories, human status lines)."""
    repo_root = Path(repo_root)
    which = which or _default_which
    path_exists = path_exists or (lambda path: Path(path).exists())
    run = run or _default_run
    problems: list[Problem] = []
    advisories: list[Problem] = []
    statuses: list[str] = []

    def report(
        code: str,
        label: str,
        message: str,
        required: bool,
    ) -> None:
        problem = Problem(code, label, None, message)
        if required or strict:
            problems.append(problem)
        else:
            advisories.append(problem)

    for dependency in dependencies:
        found = None
        for executable in dependency.executables:
            found = which(executable)
            if found:
                break
        label = dependency.executables[0]
        if found:
            statuses.append(f"ok      {label:<12} {found}")
            if dependency.daemon_args is not None:
                try:
                    reachable = run([found, *dependency.daemon_args]) == 0
                except OSError:
                    reachable = False
                if not reachable:
                    statuses.append(f"MISSING {label} daemon 不可达")
                    report(
                        "doctor-daemon-down",
                        label,
                        f"{label} 已安装但 daemon 不可达："
                        f"{dependency.capability} 不可用",
                        False,
                    )
        else:
            statuses.append(f"MISSING {label:<12} -")
            report(
                "doctor-missing-command",
                label,
                f"缺少 {label}：{dependency.capability} 不可用"
                f"（{'必需' if dependency.required else '可选'}）",
                dependency.required,
            )

    for venv in venvs:
        python = _venv_python(repo_root, venv.relative, path_exists)
        if python is not None:
            statuses.append(f"ok      {venv.relative:<12} {python}")
        else:
            statuses.append(f"MISSING {venv.relative:<12} -")
            report(
                "doctor-missing-venv",
                venv.relative,
                f"缺少虚拟环境 {venv.relative}：{venv.capability} 不可用",
                False,
            )
    return problems, advisories, statuses


def main(
    argv: list[str],
    *,
    which: Callable[[str], str | None] | None = None,
    path_exists: Callable[[Path], bool] | None = None,
    dependencies: tuple[Dependency, ...] = DEPENDENCIES,
    venvs: tuple[Venv, ...] = VENVS,
    run: Callable[[list[str]], int] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="检查本地平台依赖：报告缺什么，以及缺它会禁用哪个能力"
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="仓库根（默认从本文件位置推导）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把可选依赖的缺失也算 problem（退 1），用于一次性装齐",
    )
    args = parser.parse_args(argv[1:])
    repo_root = (
        Path(args.repo_root)
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )
    problems, advisories, statuses = check_environment(
        repo_root,
        which=which,
        path_exists=path_exists,
        dependencies=dependencies,
        venvs=venvs,
        strict=args.strict,
        run=run,
    )
    for line in statuses:
        print(line, file=sys.stderr)
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
