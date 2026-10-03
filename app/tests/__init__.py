"""Shared helpers for the workbench app tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from ccfa.stages import gate_for

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "ccfa.yaml.template"


def project_state(
    slug: str,
    mode: str = "conference",
    stage: str = "idea",
    deadline: str | None = None,
) -> dict:
    state = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    state["project"]["title"] = slug
    state["project"]["short_name"] = slug
    state["target_venue"]["name"] = "NeurIPS"
    state["target_venue"]["year"] = "2027"
    state["target_venue"]["mode"] = mode
    state["target_venue"]["deadline"] = deadline
    state["stage"]["current"] = stage
    try:
        state["stage"]["gate"] = gate_for(mode, stage).id
    except ValueError:
        state["stage"]["gate"] = "scope_defined"
    state["stage"]["updated_at"] = "2026-10-04"
    return state


def write_project(root, slug: str, **kwargs) -> Path:
    project_dir = Path(root) / "papers" / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "ccfa.yaml").write_text(
        yaml.safe_dump(
            project_state(slug, **kwargs),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return project_dir
