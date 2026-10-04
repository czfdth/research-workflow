"""Build a one-page readiness report for a paper project.

This report is deliberately conservative. It summarizes state, evidence,
environment and repository posture, but it never infers that a scientific
claim is correct just because deterministic files are present.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from ccfa import (
    argument_audit,
    artifact_badge,
    citation_guard,
    cross_review,
    experiment_loop,
    final_check,
    governance,
    latex_check,
    novelty,
    post_submission,
    proof_orchestrator,
    repro_package,
    repro_env,
    research_ledgers,
    review_loop,
    run_ledger,
    rigor,
    stats_plan,
    trace_claims,
)
from ccfa.cli import Problem, ToolEnvironmentError, save_text_atomically, tool_error
from ccfa.milestones import due_report, stage_report
from ccfa.stages import gate_for
from ccfa.texscan import iter_tex_files
from ccfa.validate import validate_yaml

PROFILES = ("minimal", "standard", "high-assurance")
DEFAULT_PROFILE = "standard"

EVIDENCE_LEDGER_PATHS = {
    "claim-registry": Path("data/claim-registry.yaml"),
    "assumptions-limitations": Path("data/assumptions-limitations.yaml"),
    "venue-checklist": Path("data/venue-checklist.yaml"),
    "artifact-provenance": Path("data/artifact-provenance.yaml"),
    "exploration-graph": Path("data/exploration-graph.yaml"),
    "cost-ledger": Path("data/cost-ledger.yaml"),
    "risk-register": Path("data/risk-register.yaml"),
    "experiment-loop": Path("data/experiment-loop.yaml"),
    "proof": Path("data/proof-audit.yaml"),
    "citation-support": Path("data/citation-support.yaml"),
    "figure-support": Path("data/figure-support.yaml"),
    "governance": Path("data/governance.yaml"),
    "novelty": Path("data/novelty-audit.yaml"),
    "statistics": Path("data/statistics-plan.yaml"),
    "repro-environment": Path("data/repro-environment.yaml"),
    "human-coding": Path("data/human-coding-report.json"),
    "post-submission": Path("data/post-submission.yaml"),
    "rigor-rubric": Path("data/rigor-rubric.yaml"),
    "proof-orchestrator": Path("data/proof-campaign.yaml"),
    "artifact-badge": Path("data/artifact-badge.yaml"),
}

PROFILE_REQUIRED_LEDGERS = {
    "minimal": ("novelty",),
    "standard": (
        "claim-registry",
        "assumptions-limitations",
        "venue-checklist",
        "artifact-provenance",
        "exploration-graph",
        "cost-ledger",
        "risk-register",
        "experiment-loop",
        "rigor-rubric",
        "proof-orchestrator",
        "citation-support",
        "figure-support",
        "novelty",
        "statistics",
        "repro-environment",
    ),
    "high-assurance": tuple(EVIDENCE_LEDGER_PATHS),
}

PENDING_REVIEW_STATUSES = {
    "pending",
    "pending-human-review",
    "pending-human-dual-coding",
    "not-started",
    "not_started",
}

LEDGER_GATE_NAMES = {
    "proof": "argument-audit",
    "citation-support": "argument-audit",
    "figure-support": "argument-audit",
    "governance": "governance",
    "novelty": "novelty",
    "statistics": "statistics",
    "repro-environment": "repro-environment",
    "human-coding": "human-coding",
    "experiment-loop": "experiment-loop",
    "rigor-rubric": "rigor-rubric",
    "proof-orchestrator": "proof-orchestrator",
    "artifact-badge": "artifact-badge",
}


@dataclass(frozen=True)
class GitSummary:
    present: bool
    dirty: bool | None
    commit: str | None
    remotes: list[str]
    workflows_present: bool
    error: str | None = None


def _load_state(paper_root: Path) -> dict:
    path = paper_root / "ccfa.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return payload


def _profile(state: dict, override: str | None) -> str:
    if override:
        value = override
    else:
        workflow = state.get("workflow")
        value = workflow.get("profile") if isinstance(workflow, dict) else None
        if value is None:
            value = DEFAULT_PROFILE
    if value not in PROFILES:
        raise ValueError(
            f"未知 readiness profile: {value!r}，应为 {', '.join(PROFILES)}"
        )
    return value


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        shell=False,
        check=False,
    )


def _git_summary(paper_root: Path) -> GitSummary:
    inside = _git(["rev-parse", "--is-inside-work-tree"], paper_root)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitSummary(False, None, None, [], False, "not a git worktree")
    commit = _git(["rev-parse", "--short", "HEAD"], paper_root)
    status = _git(["status", "--porcelain"], paper_root)
    remotes = _git(["remote"], paper_root)
    workflows_present = (paper_root / ".github" / "workflows").is_dir()
    return GitSummary(
        True,
        bool(status.stdout.strip()) if status.returncode == 0 else None,
        commit.stdout.strip() if commit.returncode == 0 else None,
        [line for line in remotes.stdout.splitlines() if line.strip()]
        if remotes.returncode == 0
        else [],
        workflows_present,
        None,
    )


def _ledger_status(paper_root: Path, profile: str) -> dict:
    required = set(PROFILE_REQUIRED_LEDGERS[profile])
    ledgers = {}
    missing_required = []
    for key, relative in EVIDENCE_LEDGER_PATHS.items():
        exists = (paper_root / relative).is_file()
        ledgers[key] = {
            "path": relative.as_posix(),
            "present": exists,
            "required": key in required,
        }
        if key in required and not exists:
            missing_required.append(key)
    return {"items": ledgers, "missing_required": sorted(missing_required)}


def _problem_dict(problem: Problem) -> dict:
    return {
        "code": problem.code,
        "path": problem.path,
        "line": problem.line,
        "message": problem.message,
    }


def _gate_result(
    name: str,
    problems: list[Problem],
    advisories: list[Problem] | None = None,
) -> dict:
    advisories = advisories or []
    return {
        "name": name,
        "status": "problem" if problems else "pass",
        "problem_count": len(problems),
        "advisory_count": len(advisories),
        "problems": [_problem_dict(problem) for problem in problems],
        "advisories": [_problem_dict(problem) for problem in advisories],
    }


def _run_gate(name: str, runner) -> dict:
    try:
        outcome = runner()
    except ToolEnvironmentError as exc:
        return _gate_result(
            name,
            [Problem("gate-environment-error", name, None, str(exc))],
        )
    except (OSError, ValueError) as exc:
        return _gate_result(
            name,
            [Problem("gate-error", name, None, str(exc))],
        )
    if isinstance(outcome, list):
        problems, advisories = outcome, []
    else:
        problems, advisories = outcome
    return _gate_result(name, list(problems), list(advisories))


def _schema_gate(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    path = paper_root / "ccfa.yaml"
    problems = [
        Problem("schema-invalid", str(path), None, message)
        for message in validate_yaml(path)
    ]
    return problems, []


def _human_coding_gate(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    path = paper_root / "data" / "human-coding-report.json"
    if not path.is_file():
        return [
            Problem(
                "human-coding-report-missing",
                str(path),
                None,
                "缺少真人双编码报告",
            )
        ], []
    payload = _load_structured(path)
    status = payload.get("status") if payload else None
    if (
        not isinstance(status, str)
        or status.strip().casefold() in PENDING_REVIEW_STATUSES
    ):
        return [
            Problem(
                "human-coding-pending",
                str(path),
                None,
                "真人双编码尚未完成",
            )
        ], []
    accepted = {"complete", "completed", "human-attested", "passed"}
    if status.strip().casefold() not in accepted:
        return [
            Problem(
                "human-coding-unknown-status",
                str(path),
                None,
                f"未知真人双编码状态: {status!r}",
            )
        ], []
    return [], []


def _gate_specs(paper_root: Path, profile: str) -> list[tuple[str, object]]:
    specs: dict[str, object] = {
        "schema-valid": lambda: _schema_gate(paper_root),
    }
    runners = {
        "argument-audit": lambda: argument_audit.check(paper_root),
        "governance": lambda: governance.check(paper_root),
        "human-coding": lambda: _human_coding_gate(paper_root),
        "novelty": lambda: novelty.check(paper_root),
        "repro-environment": lambda: repro_env.check(paper_root),
        "statistics": lambda: stats_plan.check(paper_root),
        "experiment-loop": lambda: experiment_loop.check(paper_root),
        "rigor-rubric": lambda: rigor.check(
            paper_root,
            require_complete=profile == "high-assurance",
        ),
        "proof-orchestrator": lambda: proof_orchestrator.check(
            paper_root,
            require_complete=profile == "high-assurance",
        ),
        "artifact-badge": lambda: artifact_badge.check(
            paper_root,
            require_verified=profile == "high-assurance",
        ),
    }
    for ledger in PROFILE_REQUIRED_LEDGERS[profile]:
        if not (paper_root / EVIDENCE_LEDGER_PATHS[ledger]).is_file():
            continue
        gate_name = LEDGER_GATE_NAMES.get(ledger)
        if gate_name is not None:
            specs[gate_name] = runners[gate_name]

    if profile == "minimal":
        return list(specs.items())

    if (paper_root / EVIDENCE_LEDGER_PATHS["post-submission"]).is_file():
        specs["post-submission"] = lambda: post_submission.check(paper_root)
    if (paper_root / "experiments" / "log" / "run-ledger.jsonl").is_file():
        specs["run-ledger"] = lambda: run_ledger.check_ledger(paper_root)
    if (paper_root / "reviews" / "review-loop-state.json").is_file():
        specs["review-loop"] = lambda: review_loop.check_loop(paper_root)

    specs["research-ledgers"] = lambda: research_ledgers.check(
        paper_root,
        require_core=True,
    )

    manuscript = paper_root / "manuscript"
    bib = manuscript / "references.bib"
    if manuscript.is_dir():
        specs["latex-structure"] = lambda: latex_check.check(manuscript, bib)
        tex_files = list(iter_tex_files(manuscript))
        if tex_files:
            specs["trace-claims"] = lambda: trace_claims.check(
                tex_files,
                base_dir=paper_root,
            )
    citation_ledger = paper_root / "data" / "citation-ledger.json"
    if manuscript.is_dir() and bib.is_file() and citation_ledger.is_file():
        specs["citation-guard"] = lambda: citation_guard.check(
            manuscript,
            bib,
            citation_ledger,
        )
    pdf = paper_root / "submission" / "final.pdf"
    if pdf.is_file():
        specs["final-check"] = lambda: final_check.check(
            manuscript,
            pdf=pdf,
            paper_root=paper_root,
        )
    if (paper_root / "reviews" / "cross-review.json").is_file():
        specs["cross-review"] = lambda: (
            cross_review.check_review(
                paper_root,
                strict_cross_family=profile == "high-assurance",
            ),
            [],
        )
    if (paper_root / "submission" / "repro" / "MANIFEST.json").is_file():
        specs["repro-package"] = lambda: repro_package.verify_bundle(
            paper_root / "submission" / "repro"
        )
    return list(specs.items())


def _run_gates(paper_root: Path, profile: str) -> list[dict]:
    return [
        _run_gate(name, runner)
        for name, runner in _gate_specs(paper_root, profile)
    ]


def _load_structured(path: Path) -> dict | None:
    try:
        if path.suffix.casefold() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        return None
    return payload if isinstance(payload, dict) else None


def _human_review_status(paper_root: Path, profile: str) -> dict:
    if profile != "high-assurance":
        return {"status": "not-required", "pending": []}
    pending = []
    for key in ("proof", "citation-support", "figure-support", "human-coding"):
        path = paper_root / EVIDENCE_LEDGER_PATHS[key]
        payload = _load_structured(path) if path.is_file() else None
        status = payload.get("status") if payload else None
        if not isinstance(status, str) or status.strip().casefold() in PENDING_REVIEW_STATUSES:
            pending.append(key)
    return {
        "status": "pending-human-review" if pending else "human-attested",
        "pending": pending,
    }


def _scientific_status(paper_root: Path) -> dict:
    path = paper_root / "data" / "scientific-acceptance.yaml"
    if not path.is_file():
        return {
            "status": "not-claimed",
            "path": path.relative_to(paper_root).as_posix(),
            "reason": "脚本不能自动证明结论正确；需要外部人类复核台账。",
        }
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {
            "status": "invalid-attestation",
            "path": path.relative_to(paper_root).as_posix(),
            "reason": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "status": "invalid-attestation",
            "path": path.relative_to(paper_root).as_posix(),
            "reason": "台账顶层必须是映射。",
        }
    reviewer = payload.get("external_human_reviewer")
    verdict = payload.get("verdict")
    if isinstance(reviewer, str) and reviewer.strip() and verdict == "accepted":
        return {
            "status": "human-attested",
            "path": path.relative_to(paper_root).as_posix(),
            "reviewer": reviewer.strip(),
        }
    return {
        "status": "invalid-attestation",
        "path": path.relative_to(paper_root).as_posix(),
        "reason": "需要 external_human_reviewer 与 verdict: accepted。",
    }


def build_report(
    paper_root: Path,
    *,
    profile: str | None = None,
    today: date | None = None,
) -> dict:
    paper_root = Path(paper_root).resolve()
    state = _load_state(paper_root)
    selected_profile = _profile(state, profile)
    state_path = paper_root / "ccfa.yaml"
    schema_problems = validate_yaml(state_path)
    stage = stage_report(paper_root)
    mode = state.get("target_venue", {}).get("mode", "conference")
    gate = gate_for(mode, stage["current"])
    due = due_report(paper_root, today or date.today())
    ledgers = _ledger_status(paper_root, selected_profile)
    human_review = _human_review_status(paper_root, selected_profile)
    git = _git_summary(paper_root)
    scientific = _scientific_status(paper_root)
    gate_results = _run_gates(paper_root, selected_profile)

    blocking = []
    if schema_problems:
        blocking.append("ccfa.yaml schema/state is invalid")
    blocking.extend(
        f"missing required {selected_profile} ledger: {key}"
        for key in ledgers["missing_required"]
    )
    if due.get("problems"):
        blocking.append("deadline or gate milestone problems are present")
    if git.present and git.dirty:
        blocking.append("paper git worktree is dirty")
    for result in gate_results:
        if result["status"] in {"problem", "error"}:
            codes = ", ".join(
                problem["code"] for problem in result["problems"][:5]
            ) or "unknown"
            blocking.append(f"{result['name']} gate failed: {codes}")
    if selected_profile != "minimal":
        if not git.present:
            blocking.append("paper is not a git worktree")
        elif not git.remotes:
            blocking.append("paper git remote is missing")
        if not git.workflows_present:
            blocking.append("GitHub Actions workflows are missing")
    if human_review["status"] == "pending-human-review":
        blocking.append("required human review is incomplete")

    review_status = "independent-evidence-present"
    if selected_profile == "minimal":
        review_status = "not-required"
    elif selected_profile == "high-assurance":
        required_human = {"proof", "human-coding", "citation-support", "figure-support"}
        missing_human = required_human.intersection(ledgers["missing_required"])
        review_status = (
            "missing-human-evidence"
            if missing_human
            else human_review["status"]
        )
    else:
        audit = next(
            (
                result
                for result in gate_results
                if result["name"] == "argument-audit"
            ),
            None,
        )
        if audit is None:
            review_status = "missing-human-evidence"
        elif audit["status"] != "pass":
            review_status = "pending-human-review"

    gate_verified = "pass"
    if any(result["status"] != "pass" for result in gate_results):
        gate_verified = "problem"
    elif ledgers["missing_required"]:
        gate_verified = "not-run"

    collaboration_ready = (
        git.present and bool(git.remotes) and git.workflows_present
    )

    return {
        "paper_root": str(paper_root),
        "profile": selected_profile,
        "stage": {
            **stage,
            "gate_criterion": gate.criterion,
        },
        "dimensions": {
            "schema-valid": "pass" if not schema_problems else "problem",
            "evidence-present": "pass" if not ledgers["missing_required"] else "problem",
            "gate-verified": gate_verified,
            "independently-reviewed": review_status,
            "scientifically-accepted": scientific["status"],
            "collaboration-ready": "pass" if collaboration_ready else "problem",
        },
        "schema_problems": schema_problems,
        "evidence": ledgers,
        "deadline": {
            "due": due.get("due", []),
            "problems": due.get("problems", []),
            "advisories": due.get("advisories", []),
        },
        "gate_results": gate_results,
        "git": {
            "present": git.present,
            "dirty": git.dirty,
            "commit": git.commit,
            "remotes": git.remotes,
            "workflows_present": git.workflows_present,
            "error": git.error,
        },
        "scientific_acceptance": scientific,
        "human_review": human_review,
        "blocking": blocking,
        "ready": not blocking,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Readiness Report",
        "",
        f"- paper: `{report['paper_root']}`",
        f"- profile: `{report['profile']}`",
        f"- stage: `{report['stage']['current']}` / gate `{report['stage']['gate']}`",
        f"- ready: `{str(report['ready']).lower()}`",
        "",
        "## Dimensions",
        "",
    ]
    for key, value in report["dimensions"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blocking", ""])
    if report["blocking"]:
        lines.extend(f"- {item}" for item in report["blocking"])
    else:
        lines.append("- none")
    lines.extend(["", "## Evidence Ledgers", ""])
    for key, item in report["evidence"]["items"].items():
        marker = "present" if item["present"] else "missing"
        required = "required" if item["required"] else "optional"
        lines.append(f"- `{key}`: `{marker}` ({required}) `{item['path']}`")
    lines.extend(["", "## Gate Verification", ""])
    for result in report["gate_results"]:
        codes = ", ".join(
            problem["code"] for problem in result["problems"]
        ) or "none"
        lines.append(
            f"- `{result['name']}`: `{result['status']}` "
            f"(problems: {result['problem_count']}; codes: {codes})"
        )
    lines.extend(["", "## Git And CI", ""])
    git = report["git"]
    lines.append(f"- git: `{'present' if git['present'] else 'missing'}`")
    lines.append(f"- dirty: `{git['dirty']}`")
    lines.append(f"- commit: `{git['commit']}`")
    lines.append(f"- remotes: `{', '.join(git['remotes']) or 'none'}`")
    lines.append(f"- GitHub Actions workflows: `{git['workflows_present']}`")
    lines.extend(["", "## Scientific Boundary", ""])
    lines.append(
        "- This report does not certify that proofs, statistics, citations, "
        "or claims are scientifically correct."
    )
    status = report["scientific_acceptance"]
    lines.append(f"- scientific acceptance: `{status['status']}`")
    if status.get("reason"):
        lines.append(f"- reason: {status['reason']}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成一页式论文 readiness report")
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--today", help="注入今天日期 YYYY-MM-DD（默认系统日期）")
    parser.add_argument(
        "--out",
        help="可选 Markdown 输出路径；相对路径按 paper-root 解析",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        today = date.fromisoformat(args.today) if args.today else None
        paper_root = Path(args.paper_root)
        report = build_report(paper_root, profile=args.profile, today=today)
        if args.out:
            out = Path(args.out)
            if not out.is_absolute():
                out = paper_root / out
            save_text_atomically(out, render_markdown(report), "readiness report")
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
