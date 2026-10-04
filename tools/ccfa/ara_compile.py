"""Compile existing ledgers into an ARA-shaped draft artifact.

This is deliberately a draft compiler, not a semantic paper reader. It maps
what the local ledgers actually contain, writes the ARA directory contract,
and reports every unfilled Seal Level 1 requirement instead of pretending the
artifact is complete.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error


ARA_DIRS = (
    "logic",
    "logic/solution",
    "src",
    "src/configs",
    "src/execution",
    "trace",
    "evidence",
    "evidence/tables",
    "evidence/figures",
)
MANDATORY_FILES = (
    "PAPER.md",
    "logic/problem.md",
    "logic/claims.md",
    "logic/concepts.md",
    "logic/experiments.md",
    "logic/solution/architecture.md",
    "logic/solution/algorithm.md",
    "logic/solution/constraints.md",
    "logic/solution/heuristics.md",
    "logic/related_work.md",
    "src/configs/training.md",
    "src/configs/model.md",
    "src/environment.md",
    "trace/exploration_tree.yaml",
    "evidence/README.md",
)
CLAIM_REGISTRY = Path("data/claim-registry.yaml")
EXPLORATION_GRAPH = Path("data/exploration-graph.yaml")
FIGURE_MANIFEST = Path("figures/manifest.yaml")
RUN_LOG_DIR = Path("experiments/log")
REPRO_ENV = Path("data/repro-environment.yaml")


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _claim_map(paper_root: Path) -> dict[str, str]:
    payload = _load_yaml(paper_root / CLAIM_REGISTRY)
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return {}
    ids = sorted(
        item["id"]
        for item in claims
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    return {item_id: f"C{index:02d}" for index, item_id in enumerate(ids, start=1)}


def _run_claim_links(paper_root: Path) -> dict[str, set[str]]:
    payload = _load_yaml(paper_root / CLAIM_REGISTRY)
    claims = payload.get("claims")
    links: dict[str, set[str]] = {}
    if not isinstance(claims, list):
        return links
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("id")
        experiments = claim.get("experiments")
        if not isinstance(claim_id, str) or not isinstance(experiments, list):
            continue
        for run_id in experiments:
            if isinstance(run_id, str) and run_id:
                links.setdefault(run_id, set()).add(claim_id)
    graph = _load_yaml(paper_root / EXPLORATION_GRAPH)
    entries = graph.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            run_ids = entry.get("run_ids", [])
            claim_ids = entry.get("claim_ids", [])
            if not isinstance(run_ids, list) or not isinstance(claim_ids, list):
                continue
            for run_id in run_ids:
                if isinstance(run_id, str):
                    links.setdefault(run_id, set()).update(
                        value
                        for value in claim_ids
                        if isinstance(value, str)
                    )
    return links


def _experiment_map(paper_root: Path) -> dict[str, str]:
    run_ids = set(_run_claim_links(paper_root))
    log_dir = paper_root / RUN_LOG_DIR
    if log_dir.is_dir():
        for path in log_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_id = payload.get("run_id") if isinstance(payload, dict) else None
            if isinstance(run_id, str) and run_id:
                run_ids.add(run_id)
    return {
        run_id: f"E{index:02d}"
        for index, run_id in enumerate(sorted(run_ids), start=1)
    }


def _project_info(paper_root: Path) -> dict:
    payload = _load_yaml(paper_root / "ccfa.yaml")
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    venue = (
        payload.get("target_venue")
        if isinstance(payload.get("target_venue"), dict)
        else {}
    )
    return {
        "title": project.get("title") or project.get("short_name") or "Untitled",
        "venue": venue.get("name") or "Not specified in provided input",
        "year": venue.get("year") or "Not specified in provided input",
    }


def _render_paper(paper_root: Path) -> str:
    info = _project_info(paper_root)
    frontmatter = {
        "title": info["title"],
        "authors": [],
        "year": info["year"],
        "venue": info["venue"],
        "doi": "",
        "ara_version": "1.0",
        "domain": "Not specified in provided input",
        "keywords": [],
        "claims_summary": [],
        "abstract": "Not available from provided input.",
        "compile_status": "draft",
    }
    body = f"""---
{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()}
---

# {info['title']}

## Overview

This is a draft ARA generated from local ledgers. Semantic sections that cannot
be recovered from structured inputs are marked as draft gaps and are not
claimed to pass Seal Level 1.

## Layer Index

### Cognitive Layer (`/logic`)

| File | Description |
| --- | --- |
| [problem.md](logic/problem.md) | Observations, gaps, insight |
| [claims.md](logic/claims.md) | Claims mapped from claim registry |
| [concepts.md](logic/concepts.md) | Concepts |
| [experiments.md](logic/experiments.md) | Experiment plans |
| [related_work.md](logic/related_work.md) | Related work |

### Physical Layer (`/src`)

| File | Description |
| --- | --- |
| [environment.md](src/environment.md) | Environment |
| [configs/training.md](src/configs/training.md) | Training config |
| [configs/model.md](src/configs/model.md) | Model config |

### Exploration Graph (`/trace`)

| File | Description |
| --- | --- |
| [exploration_tree.yaml](trace/exploration_tree.yaml) | Reconstructed research DAG |

### Evidence (`/evidence`)

| File | Description |
| --- | --- |
| [README.md](evidence/README.md) | Evidence index |
"""
    return body


def _render_claims(paper_root: Path) -> str:
    payload = _load_yaml(paper_root / CLAIM_REGISTRY)
    claims = payload.get("claims")
    claim_map = _claim_map(paper_root)
    experiment_map = _experiment_map(paper_root)
    lines = ["# Claims", ""]
    if not isinstance(claims, list) or not claims:
        lines.append("No claims available from provided input.")
        return "\n".join(lines) + "\n"
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        source_id = claim.get("id")
        if source_id not in claim_map:
            continue
        claim_id = claim_map[source_id]
        statement = claim.get("statement") or "Not specified in provided input."
        status = claim.get("status")
        mapped_status = {
            "supported": "supported",
            "provisional": "hypothesis",
            "pending-human-review": "hypothesis",
            "dropped": "refuted",
        }.get(status, "hypothesis")
        proof = [
            experiment_map[run_id]
            for run_id in claim.get("experiments", [])
            if run_id in experiment_map
        ]
        evidence_parts = []
        if proposal := claim.get("figures"):
            evidence_parts.append("Figures: " + ", ".join(str(v) for v in proposal))
        if citations := claim.get("citations"):
            evidence_parts.append("Citations: " + ", ".join(str(v) for v in citations))
        lines.extend(
            [
                f"## {claim_id}: {statement}",
                f"- **Statement**: {statement}",
                f"- **Status**: {mapped_status}",
                "- **Falsification criteria**: Not specified in provided input.",
                f"- **Proof**: [{', '.join(proof)}]",
                "- **Evidence basis**: "
                + ("; ".join(evidence_parts) or "Not specified in provided input."),
                "- **Interpretation**: Draft: semantic interpretation not extracted.",
                "- **Dependencies**: "
                + ", ".join(
                    str(value)
                    for value in [
                        *claim.get("assumptions", []),
                        *claim.get("limitations", []),
                    ]
                )
                or "none",
                f"- **Tags**: {claim.get('type', 'unspecified')}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_experiments(paper_root: Path) -> str:
    claim_map = _claim_map(paper_root)
    links = _run_claim_links(paper_root)
    experiment_map = _experiment_map(paper_root)
    lines = ["# Experiments", ""]
    if not experiment_map:
        lines.append("No experiments available from provided input.")
        return "\n".join(lines) + "\n"
    for run_id, experiment_id in experiment_map.items():
        verifies = sorted(
            claim_map[value]
            for value in links.get(run_id, set())
            if value in claim_map
        )
        lines.extend(
            [
                f"## {experiment_id}: {run_id}",
                f"- **Verifies**: [{', '.join(verifies)}]",
                "- **Setup**: Not specified in provided input.",
                "- **Procedure**: Not specified in provided input.",
                "- **Metrics**: Not specified in provided input.",
                "- **Expected outcome**: Not specified in provided input.",
                "- **Baselines**: Not specified in provided input.",
                "- **Dependencies**: none",
                "",
            ]
        )
    return "\n".join(lines)


def _mapped_claim_id(value: object, claim_map: dict[str, str]) -> str | None:
    if isinstance(value, str) and value in claim_map:
        return claim_map[value]
    return None


def _render_tree(paper_root: Path) -> str:
    graph = _load_yaml(paper_root / EXPLORATION_GRAPH)
    entries = graph.get("entries")
    entries = entries if isinstance(entries, list) else []
    claim_map = _claim_map(paper_root)
    children = []
    counter = 2
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        node_id = f"N{counter:02d}"
        counter += 1
        kind = entry.get("kind")
        summary = entry.get("summary") or "Not specified in provided input."
        rationale = entry.get("rationale") or "Not specified in provided input."
        evidence = [
            claim_map[value]
            for value in entry.get("claim_ids", [])
            if isinstance(value, str) and value in claim_map
        ]
        if kind in {"dead-end", "rejected"}:
            node = {
                "id": node_id,
                "type": "dead_end",
                "support_level": "inferred",
                "title": summary,
                "hypothesis": summary,
                "failure_mode": rationale,
                "lesson": "See linked runs and claims for the recorded failure mode.",
            }
        elif kind == "pivot":
            node = {
                "id": node_id,
                "type": "pivot",
                "support_level": "inferred",
                "title": summary,
                "from": "previous trajectory",
                "to": summary,
                "trigger": rationale,
            }
        else:
            node = {
                "id": node_id,
                "type": "experiment",
                "support_level": "inferred",
                "title": summary,
                "result": summary,
                "evidence": evidence,
            }
        children.append(node)
    tree = [
        {
            "id": "N01",
            "type": "question",
            "support_level": "inferred",
            "title": "Research trajectory reconstructed from exploration-graph.yaml",
            "description": "Reconstruct the research DAG from recorded local exploration entries.",
            "children": children,
        }
    ]
    return yaml.safe_dump(
        {"tree": tree},
        sort_keys=False,
        allow_unicode=True,
    )


def _render_evidence_index(paper_root: Path) -> str:
    manifest = _load_yaml(paper_root / FIGURE_MANIFEST)
    figures = manifest.get("figures")
    figures = figures if isinstance(figures, list) else []
    lines = [
        "# Evidence Index",
        "",
        "| Evidence | Type | Source |",
        "| --- | --- | --- |",
    ]
    if figures:
        for figure in figures:
            if not isinstance(figure, dict):
                continue
            figure_id = figure.get("id") or figure.get("name") or "unknown"
            path = figure.get("path", "")
            lines.append(f"| {figure_id} | figure | figures/manifest.yaml `{path}` |")
    else:
        lines.append("| none | none | No evidence available from provided input |")
    return "\n".join(lines) + "\n"


def _render_environment(paper_root: Path) -> str:
    payload = _load_yaml(paper_root / REPRO_ENV)
    if not payload:
        return "# Environment\n\nNot available from provided input.\n"
    lines = [
        "# Environment",
        f"- **Python**: {payload.get('python', 'Not specified')}",
        f"- **Framework**: {payload.get('package_manager', 'Not specified')}",
        f"- **Hardware**: {payload.get('system_tools', 'Not specified')}",
        f"- **Key dependencies**: {payload.get('requirements', 'Not specified')}",
        f"- **Random seeds**: {payload.get('seeds', 'Not specified')}",
    ]
    return "\n".join(lines) + "\n"


def _placeholder(title: str, note: str) -> str:
    return f"# {title}\n\n{note}\n\n**Draft gap**: Not available from provided input.\n"


def _write_out(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _concept_count(text: str) -> int:
    return len(re.findall(r"^##\s+", text, flags=re.MULTILINE))


def _tree_nodes(node: object) -> list[dict]:
    if not isinstance(node, list):
        return []
    found = []
    for item in node:
        if not isinstance(item, dict):
            continue
        found.append(item)
        found.extend(_tree_nodes(item.get("children")))
    return found


def _unmet_requirements(out_dir: Path) -> list[str]:
    unmet: list[str] = []
    concepts = out_dir / "logic" / "concepts.md"
    if not concepts.is_file() or _concept_count(concepts.read_text(encoding="utf-8")) < 5:
        unmet.append("concepts>=5")
    experiments = out_dir / "logic" / "experiments.md"
    experiment_text = experiments.read_text(encoding="utf-8") if experiments.is_file() else ""
    if len(re.findall(r"^## E\\d+", experiment_text, flags=re.MULTILINE)) < 3:
        unmet.append("experiments>=3")
    if not list((out_dir / "src" / "execution").glob("*.py")):
        unmet.append("src/execution/*.py>=1")
    tree_path = out_dir / "trace" / "exploration_tree.yaml"
    try:
        tree_payload = yaml.safe_load(tree_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        tree_payload = {}
    nodes = _tree_nodes(tree_payload.get("tree") if isinstance(tree_payload, dict) else None)
    if len(nodes) < 8:
        unmet.append("trace_nodes>=8")
    if not any(node.get("type") == "dead_end" for node in nodes):
        unmet.append("trace_dead_end>=1")
    if not any(node.get("type") == "decision" for node in nodes):
        unmet.append("trace_decision>=1")
    return unmet


def compile_ara(
    paper_root: Path,
    out_dir: Path,
    *,
    force: bool = False,
) -> dict:
    paper_root = Path(paper_root).resolve()
    out_dir = Path(out_dir)
    if not out_dir.is_absolute():
        out_dir = paper_root / out_dir
    out_dir = out_dir.resolve()
    if out_dir == paper_root.resolve():
        raise ValueError("ARA 输出目录不能是 paper root")
    if out_dir.exists():
        if not force:
            raise ValueError(f"ARA 输出目录已存在，拒绝覆盖: {out_dir}")
        shutil.rmtree(out_dir)
    for relative in ARA_DIRS:
        (out_dir / relative).mkdir(parents=True, exist_ok=True)

    _write_out(out_dir / "PAPER.md", _render_paper(paper_root))
    _write_out(
        out_dir / "logic" / "problem.md",
        _placeholder("Problem Specification", "No observations or gaps were extracted from structured ledgers."),
    )
    _write_out(out_dir / "logic" / "claims.md", _render_claims(paper_root))
    _write_out(
        out_dir / "logic" / "concepts.md",
        _placeholder("Concepts", "No concept extraction source was provided."),
    )
    _write_out(out_dir / "logic" / "experiments.md", _render_experiments(paper_root))
    for name in ("architecture", "algorithm", "constraints", "heuristics"):
        _write_out(
            out_dir / "logic" / "solution" / f"{name}.md",
            _placeholder(name.title(), "No semantic source was provided for this layer."),
        )
    _write_out(
        out_dir / "logic" / "related_work.md",
        _placeholder("Related Work", "No typed related-work extraction was provided."),
    )
    _write_out(
        out_dir / "src" / "configs" / "training.md",
        _placeholder("Training Config", "No training configuration was provided."),
    )
    _write_out(
        out_dir / "src" / "configs" / "model.md",
        _placeholder("Model Config", "No model configuration was provided."),
    )
    _write_out(out_dir / "src" / "environment.md", _render_environment(paper_root))
    _write_out(out_dir / "trace" / "exploration_tree.yaml", _render_tree(paper_root))
    _write_out(out_dir / "evidence" / "README.md", _render_evidence_index(paper_root))
    for figure in _load_yaml(paper_root / FIGURE_MANIFEST).get("figures", []):
        if not isinstance(figure, dict):
            continue
        figure_id = figure.get("id") or figure.get("name")
        if not figure_id:
            continue
        _write_out(
            out_dir / "evidence" / "figures" / f"{figure_id}.md",
            f"""# Figure {figure_id}

**Source**: figures/manifest.yaml
**Extraction type**: derived_subset

| Field | Value |
| --- | --- |
| path | {figure.get('path', '')} |
| sha256 | {figure.get('sha256', '')} |
| source | {figure.get('source', '')} |
""",
        )

    unmet = _unmet_requirements(out_dir)
    report = {
        "status": "draft",
        "seal_level1_ready": not unmet,
        "unmet_requirements": unmet,
        "claim_map": _claim_map(paper_root),
        "experiment_map": _experiment_map(paper_root),
    }
    _write_out(
        out_dir / "compile-report.json",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return report


def validate_ara(out_dir: Path) -> tuple[list[Problem], list[Problem]]:
    out_dir = Path(out_dir)
    problems: list[Problem] = []
    if not out_dir.is_dir():
        return [Problem("ara-missing", str(out_dir), None, "ARA 目录不存在")], []
    for relative in ARA_DIRS:
        if not (out_dir / relative).is_dir():
            problems.append(Problem("ara-missing-dir", str(out_dir / relative), None, "缺少 ARA 目录"))
    for relative in MANDATORY_FILES:
        path = out_dir / relative
        if not path.is_file():
            problems.append(Problem("ara-missing-file", str(path), None, "缺少 ARA 文件"))
        elif path.stat().st_size <= 10:
            problems.append(Problem("ara-empty-file", str(path), None, "ARA 文件为空或过短"))
    for requirement in _unmet_requirements(out_dir):
        problems.append(Problem("ara-seal-unmet", str(out_dir), None, requirement))
    return problems, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从本地台账编译 ARA draft")
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--paper-root", required=True)
    compile_parser.add_argument("--out", required=True)
    compile_parser.add_argument("--force", action="store_true")
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--dir", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "compile":
            report = compile_ara(
                Path(args.paper_root),
                Path(args.out),
                force=args.force,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        problems, advisories = validate_ara(Path(args.dir))
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
