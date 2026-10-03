"""Discover and load paper projects under papers/*/ccfa.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ccfa.milestones import parse_deadline
from ccfa.stages import stages_for


class ProjectError(ValueError):
    """Raised when a project state file is missing or invalid."""


@dataclass(frozen=True)
class ProjectRef:
    slug: str
    dir: Path
    error: str | None = None


@dataclass(frozen=True)
class ProjectState:
    slug: str
    dir: Path
    mode: str
    current_stage: str
    gate: str
    deadline: str | None
    updated_at: str


def _yaml_path(path: Path) -> tuple[Path, Path]:
    path = Path(path)
    if path.is_dir():
        yaml_path = path / "ccfa.yaml"
    elif path.name == "ccfa.yaml":
        yaml_path = path
    else:
        yaml_path = path / "ccfa.yaml"
    return yaml_path.parent, yaml_path


def load_project(path: Path) -> ProjectState:
    """Load one project state, validating mode/stage against ccfa.stages."""
    project_dir, yaml_path = _yaml_path(path)
    try:
        raw = yaml_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectError(f"无法读取项目状态 {yaml_path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ProjectError(f"项目状态解析失败 {yaml_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectError(f"{yaml_path} 顶层必须是映射")

    venue = data.get("target_venue")
    if not isinstance(venue, dict):
        raise ProjectError(f"{yaml_path} 缺少 target_venue 映射")
    stage = data.get("stage")
    if not isinstance(stage, dict):
        raise ProjectError(f"{yaml_path} 缺少 stage 映射")

    mode = venue.get("mode")
    if not isinstance(mode, str) or not mode.strip():
        raise ProjectError(f"{yaml_path} 缺少 target_venue.mode")
    try:
        valid_stages = stages_for(mode)
    except ValueError as exc:
        raise ProjectError(f"{yaml_path} 的 mode 非法: {mode!r}: {exc}") from exc

    current_stage = stage.get("current")
    if not isinstance(current_stage, str) or not current_stage.strip():
        raise ProjectError(f"{yaml_path} 缺少 stage.current")
    if current_stage not in valid_stages:
        raise ProjectError(
            f"{yaml_path} 的 stage.current 非法: {current_stage!r}"
        )

    gate = stage.get("gate")
    if not isinstance(gate, str) or not gate.strip():
        raise ProjectError(f"{yaml_path} 缺少 stage.gate")
    updated_at = stage.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ProjectError(f"{yaml_path} 缺少 stage.updated_at")

    deadline = venue.get("deadline")
    try:
        parse_deadline(deadline)
    except ValueError as exc:
        raise ProjectError(
            f"{yaml_path} 的 target_venue.deadline 非法: {exc}"
        ) from exc

    return ProjectState(
        slug=project_dir.name,
        dir=project_dir,
        mode=mode,
        current_stage=current_stage,
        gate=gate,
        deadline=deadline,
        updated_at=updated_at,
    )


def find_projects(repo_root: Path) -> list[ProjectRef]:
    """Return one ref per papers/*/ccfa.yaml; bad entries carry an error."""
    papers = Path(repo_root) / "papers"
    if not papers.is_dir():
        return []

    refs: list[ProjectRef] = []
    project_dirs = sorted(
        (path for path in papers.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )
    for project_dir in project_dirs:
        yaml_path = project_dir / "ccfa.yaml"
        if not yaml_path.is_file():
            continue
        try:
            load_project(yaml_path)
        except (ProjectError, OSError, ValueError) as exc:
            refs.append(
                ProjectRef(
                    slug=project_dir.name,
                    dir=project_dir,
                    error=str(exc),
                )
            )
        else:
            refs.append(ProjectRef(slug=project_dir.name, dir=project_dir))
    return refs
