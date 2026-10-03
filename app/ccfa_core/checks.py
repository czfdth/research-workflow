"""Run the existing deterministic checks; no tool logic is duplicated."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ccfa.milestones import due_report
from ccfa.validate import validate_yaml


class CheckError(RuntimeError):
    """Raised when a deterministic check cannot run."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    problems: tuple[object, ...] = ()
    report: dict | None = None


def _project_dir(project) -> Path:
    if isinstance(project, (str, Path)):
        path = Path(project)
        return path.parent if path.name == "ccfa.yaml" else path
    directory = getattr(project, "dir", None)
    if directory is None:
        raise CheckError("project 必须是 ProjectState、ProjectRef 或项目目录")
    return Path(directory)


def run_validate(project) -> CheckResult:
    """Run ccfa.validate.validate_yaml against the project state."""
    project_dir = _project_dir(project)
    yaml_path = project_dir / "ccfa.yaml"
    try:
        problems = validate_yaml(yaml_path)
    except (OSError, ValueError) as exc:
        raise CheckError(f"validate 失败 ({yaml_path}): {exc}") from exc
    return CheckResult(
        name="validate",
        ok=not problems,
        problems=tuple(problems),
    )


def run_milestones_due(project, today=None) -> CheckResult:
    """Run ccfa.milestones.due_report and keep its structured report."""
    project_dir = _project_dir(project)
    if today is None:
        today = date.today()
    elif isinstance(today, str):
        try:
            today = date.fromisoformat(today)
        except ValueError as exc:
            raise CheckError(f"today 非法: {today!r}: {exc}") from exc
    if not isinstance(today, date):
        raise CheckError("today 必须是 datetime.date 或 ISO 日期字符串")
    try:
        report = due_report(project_dir, today)
    except (OSError, ValueError) as exc:
        raise CheckError(
            f"milestones due 失败 ({project_dir}): {exc}"
        ) from exc
    problems = tuple(report.get("problems", []))
    return CheckResult(
        name="milestones-due",
        ok=not problems,
        problems=problems,
        report=report,
    )
