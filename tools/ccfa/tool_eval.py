"""Measure whether this workflow's own gates catch injected defects.

The workflow could report that every gate is wired, but nothing measured
whether a gate actually rejects the thing it claims to reject. The only
external yardstick was the human writing more checks. This harness injects a
known defect into a throwaway fixture and records whether the gate noticed,
plus clean fixtures that must NOT be flagged.

Deliberately aligned with ARIS ``tools/meta_opt/trigger_eval.py`` (Apache-2.0),
which measures skill triggering the same way:

* measure-only — it never rewrites a gate; a low rate is evidence for a human,
  not a trigger for automatic change;
* every probe is classified, and a harness ``error`` is graded separately so it
  cannot be mistaken for a detection failure or a clean pass;
* errors are excluded from the rate denominators, so a broken probe cannot
  inflate or deflate a rate;
* rates are rounded to three decimals;
* exit 0 on a completed run whatever the rates say (this is a measurement, not
  a gate), and 2 only when the harness itself cannot run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ccfa import post_submission, stats_plan
from ccfa.cli import save_text_atomically, tool_error
from ccfa.research_ledgers import _cost_ledger

import yaml

VERSION = 1
REJECT = "reject"
ACCEPT = "accept"
CAUGHT = "caught"
MISSED = "missed"
CLEAN = "clean"
FALSE_ALARM = "false-alarm"
ERROR = "error"


@dataclass(frozen=True)
class Case:
    """One labelled probe: build a fixture, then see what the gate says."""

    id: str
    gate: str
    expectation: str
    note: str
    build: object  # Callable[[Path], None]
    check: object  # Callable[[Path], bool] -> True when the gate rejects


# ------------------------------------------------------------------ fixtures


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _statistics_payload(*, null_baseline: object) -> dict:
    return {
        "version": 1,
        "alpha": 0.05,
        "multiple_comparison": "holm-bonferroni",
        "claims": [
            {
                "id": "claim:matrix",
                "endpoint": "descriptive counts in the coded matrix",
                "test": "deterministic recount; no hypothesis test is claimed",
                "effect_size": 0.5,
                "target_power": 0.8,
                "sample_size": 43,
                "seeds": [0],
                "stopping_rule": "frozen corpus",
                "missing_data": "explicit unknown coding",
                "null_baseline": null_baseline,
            }
        ],
    }


RECORDED_BASELINE = {
    "status": "recorded",
    "name": "majority-class coder",
    "value": 0.501661,
    "source": "tables/null-baseline.json",
}


def _build_stats_clean(root: Path) -> None:
    _write_yaml(
        root / "data" / "statistics-plan.yaml",
        _statistics_payload(null_baseline=RECORDED_BASELINE),
    )


def _build_stats_without_baseline(root: Path) -> None:
    payload = _statistics_payload(null_baseline=RECORDED_BASELINE)
    del payload["claims"][0]["null_baseline"]
    _write_yaml(root / "data" / "statistics-plan.yaml", payload)


def _build_stats_baseline_without_reason(root: Path) -> None:
    _write_yaml(
        root / "data" / "statistics-plan.yaml",
        _statistics_payload(null_baseline={"status": "not-applicable"}),
    )


def _cost_payload(*, with_metrics: bool) -> dict:
    payload = {
        "version": 1,
        "currency": "USD",
        "paper": "demo",
        "entries": [{"kind": "gpu", "amount": 0, "unit": "hours"}],
    }
    if with_metrics:
        payload["metrics"] = {
            "time_to_first_attempt": {
                "status": "recorded",
                "value": 4.5,
                "unit": "hours",
                "source": "experiments/log/run-1.json",
            },
            "cost_per_attempt": {
                "status": "recorded",
                "value": 0.0,
                "currency": "USD",
                "source": "experiments/log/compute-ledger.jsonl",
            },
        }
    return payload


def _build_cost_clean(root: Path) -> None:
    _write_yaml(
        root / "data" / "cost-ledger.yaml",
        _cost_payload(with_metrics=True),
    )


def _build_cost_without_metrics(root: Path) -> None:
    _write_yaml(
        root / "data" / "cost-ledger.yaml",
        _cost_payload(with_metrics=False),
    )


def _build_citation_clean(root: Path) -> None:
    (root / "manuscript").mkdir(parents=True, exist_ok=True)
    (root / "manuscript" / "main.tex").write_text(
        "\\cite{alpha}\n",
        encoding="utf-8",
    )
    (root / "manuscript" / "references.bib").write_text(
        "@article{alpha,\n  title = {Alpha},\n  doi = {10.1000/alpha},\n}\n",
        encoding="utf-8",
    )
    ledger = root / "data" / "citation-ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "alpha": {
                        "doi": "10.1000/alpha",
                        "status": "verified",
                        "verified_at": "2026-01-01T00:00:00Z",
                        "source": "crossref",
                        "evidence": {
                            "body_sha256": "sha256:" + "a" * 64,
                            "retrieved_at": "2026-01-01T00:00:00Z",
                            "matched_title": "Alpha",
                            "source": "crossref",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _build_citation_dangling(root: Path) -> None:
    _build_citation_clean(root)
    (root / "manuscript" / "main.tex").write_text(
        "\\cite{ghost}\n",
        encoding="utf-8",
    )


def _build_post_submission(root: Path) -> None:
    (root / "experiments" / "log").mkdir(parents=True, exist_ok=True)
    (root / "experiments" / "log" / "RUN1.json").write_text(
        json.dumps({"run_id": "RUN1"}),
        encoding="utf-8",
    )
    (root / "reviews").mkdir(parents=True, exist_ok=True)
    (root / "reviews" / "revision-ledger.md").write_text(
        "# ledger\n",
        encoding="utf-8",
    )
    (root / "figures").mkdir(parents=True, exist_ok=True)
    _write_yaml(root / "figures" / "manifest.yaml", {"version": 1, "figures": []})
    _write_yaml(
        root / "data" / "claim-registry.yaml",
        {"version": 1, "claims": [{"id": "C1", "statement": "demo"}]},
    )


def _build_post_submission_clean(root: Path) -> None:
    _build_post_submission(root)
    _write_yaml(
        root / "data" / "post-submission.yaml",
        {
            "version": 1,
            "rebuttal": {
                "status": "complete",
                "response_ledger": "reviews/revision-ledger.md",
                "new_evidence_run_ids": ["RUN1"],
                "commitments": ["adding the missing ablation table"],
            },
            "resubmit": {"status": "not-applicable", "reason": "conference"},
            "talk": {"status": "not-started"},
        },
    )


def _build_post_submission_placeholder(root: Path) -> None:
    _build_post_submission(root)
    _write_yaml(
        root / "data" / "post-submission.yaml",
        {
            "version": 1,
            "rebuttal": {
                "status": "complete",
                "response_ledger": "reviews/revision-ledger.md",
                "new_evidence_run_ids": ["RUN1"],
                "commitments": ["TODO"],
            },
            "resubmit": {"status": "not-applicable", "reason": "conference"},
            "talk": {"status": "not-started"},
        },
    )


def _build_post_submission_section_incomplete(root: Path) -> None:
    _build_post_submission_clean(root)
    # A tail stage makes the rebuttal section mandatory; a skeleton must not
    # satisfy it.
    _write_yaml(
        root / "data" / "post-submission.yaml",
        {
            "version": 1,
            "rebuttal": {"status": "not-started"},
            "resubmit": {"status": "not-applicable", "reason": "conference"},
            "talk": {"status": "not-started"},
        },
    )


# ------------------------------------------------------------------- gate IO


def _stats_rejects(root: Path) -> bool:
    problems, _advisories = stats_plan.check(root)
    return bool(problems)


def _cost_rejects(root: Path) -> bool:
    payload = yaml.safe_load(
        (root / "data" / "cost-ledger.yaml").read_text(encoding="utf-8")
    )
    return bool(_cost_ledger(root, payload))


def _citation_rejects(root: Path) -> bool:
    from ccfa import citation_guard

    problems, _advisories = citation_guard.check(
        root / "manuscript",
        root / "manuscript" / "references.bib",
        root / "data" / "citation-ledger.json",
    )
    return bool(problems)


def _post_submission_rejects(root: Path) -> bool:
    problems, _advisories = post_submission.check(
        root,
        require_sections=("rebuttal",),
    )
    return bool(problems)


# --------------------------------------------------------------------- cases

CASES: tuple[Case, ...] = (
    Case(
        "statistics-null-baseline-recorded",
        "stats-plan",
        ACCEPT,
        "a claim that states the zero-skill baseline must pass",
        _build_stats_clean,
        _stats_rejects,
    ),
    Case(
        "statistics-null-baseline-missing",
        "stats-plan",
        REJECT,
        "a claim with no zero-skill baseline must be rejected",
        _build_stats_without_baseline,
        _stats_rejects,
    ),
    Case(
        "statistics-null-baseline-no-reason",
        "stats-plan",
        REJECT,
        "not-applicable without a reason must be rejected",
        _build_stats_baseline_without_reason,
        _stats_rejects,
    ),
    Case(
        "cost-ledger-metrics-present",
        "cost-ledger",
        ACCEPT,
        "attempt economics recorded must pass",
        _build_cost_clean,
        _cost_rejects,
    ),
    Case(
        "cost-ledger-metrics-missing",
        "cost-ledger",
        REJECT,
        "a ledger without attempt metrics must be rejected",
        _build_cost_without_metrics,
        _cost_rejects,
    ),
    Case(
        "citation-clean",
        "citation-guard",
        ACCEPT,
        "a cited, verified entry must pass",
        _build_citation_clean,
        _citation_rejects,
    ),
    Case(
        "citation-dangling-key",
        "citation-guard",
        REJECT,
        "a cite that the bibliography lacks must be rejected",
        _build_citation_dangling,
        _citation_rejects,
    ),
    Case(
        "post-submission-valid-skeleton",
        "post-submission",
        ACCEPT,
        "a well-formed tail ledger must pass",
        _build_post_submission_clean,
        _post_submission_rejects,
    ),
    Case(
        "post-submission-placeholder-commitment",
        "post-submission",
        REJECT,
        "a placeholder commitment must be rejected",
        _build_post_submission_placeholder,
        _post_submission_rejects,
    ),
    Case(
        "post-submission-required-section-missing",
        "post-submission",
        REJECT,
        "a tail stage whose own section is not complete must be rejected",
        _build_post_submission_section_incomplete,
        _post_submission_rejects,
    ),
)


# ------------------------------------------------------------------- running


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _grade(case: Case, rejected: bool) -> tuple[str, str]:
    if rejected and case.expectation == REJECT:
        return CAUGHT, "gate rejected the injected defect"
    if rejected and case.expectation == ACCEPT:
        return FALSE_ALARM, "gate rejected a clean fixture"
    if not rejected and case.expectation == ACCEPT:
        return CLEAN, "gate accepted the clean fixture"
    return MISSED, "gate accepted an injected defect"


def run_cases(cases: tuple[Case, ...] | None = None) -> dict:
    selected = cases if cases is not None else CASES
    results: list[dict] = []
    for case in selected:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                case.build(root)  # type: ignore[operator]
                rejected = bool(case.check(root))  # type: ignore[operator]
            except Exception as exc:  # noqa: BLE001 - graded, never raised
                results.append(
                    {
                        "id": case.id,
                        "gate": case.gate,
                        "expectation": case.expectation,
                        "outcome": ERROR,
                        "detail": f"{type(exc).__name__}: {exc}",
                        "note": case.note,
                    }
                )
                continue
        outcome, detail = _grade(case, rejected)
        results.append(
            {
                "id": case.id,
                "gate": case.gate,
                "expectation": case.expectation,
                "outcome": outcome,
                "detail": detail,
                "note": case.note,
            }
        )
    return {"version": VERSION, "generated_at": _now_iso(), "results": results}


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def summarise(report: dict) -> dict:
    results = report["results"]
    totals = {
        "cases": len(results),
        "errors": sum(1 for r in results if r["outcome"] == ERROR),
        "caught": sum(1 for r in results if r["outcome"] == CAUGHT),
        "missed": sum(1 for r in results if r["outcome"] == MISSED),
        "clean": sum(1 for r in results if r["outcome"] == CLEAN),
        "false_alarms": sum(1 for r in results if r["outcome"] == FALSE_ALARM),
    }
    summary = {
        "version": report["version"],
        "generated_at": report["generated_at"],
        "totals": totals,
        # Errors are excluded from both denominators: a probe that could not
        # run is neither a detection failure nor a clean pass.
        "detection_rate": _rate(totals["caught"], totals["caught"] + totals["missed"]),
        "false_alarm_rate": _rate(
            totals["false_alarms"],
            totals["false_alarms"] + totals["clean"],
        ),
        "gates": {},
        "results": results,
    }
    for name in sorted({r["gate"] for r in results}):
        rows = [r for r in results if r["gate"] == name]
        caught = sum(1 for r in rows if r["outcome"] == CAUGHT)
        missed = sum(1 for r in rows if r["outcome"] == MISSED)
        clean = sum(1 for r in rows if r["outcome"] == CLEAN)
        false_alarms = sum(1 for r in rows if r["outcome"] == FALSE_ALARM)
        summary["gates"][name] = {
            "cases": len(rows),
            "caught": caught,
            "missed": missed,
            "clean": clean,
            "false_alarms": false_alarms,
            "detection_rate": _rate(caught, caught + missed),
            "false_alarm_rate": _rate(false_alarms, false_alarms + clean),
        }
    return summary


def render_markdown(summary: dict) -> str:
    totals = summary["totals"]
    lines = [
        "# 工具自评：gate 检出率",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 用例: {totals['cases']}（错误 {totals['errors']}）",
        f"- 检出率 detection_rate: {summary['detection_rate']}",
        f"- 误报率 false_alarm_rate: {summary['false_alarm_rate']}",
        "",
        "只测量，不改写任何 gate；低分是给人看的证据，不是自动修改的触发器。"
        "错误用例从分母里剔除。",
        "",
        "## 按 gate",
        "",
        "| gate | cases | caught | missed | detection | clean | false-alarm | false-alarm rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, item in summary["gates"].items():
        lines.append(
            f"| `{name}` | {item['cases']} | {item['caught']} | {item['missed']} "
            f"| {item['detection_rate']} | {item['clean']} | {item['false_alarms']} "
            f"| {item['false_alarm_rate']} |"
        )
    lines.extend(["", "## 用例", "", "| id | gate | 期望 | 结果 | 说明 |", "| --- | --- | --- | --- | --- |"])
    for item in summary["results"]:
        lines.append(
            f"| `{item['id']}` | `{item['gate']}` | {item['expectation']} "
            f"| {item['outcome']} | {item['detail']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# External benchmark harness (MLGym-style).
#
# The internal cases above measure this workflow's own gates. They cannot say
# whether the workflow helps on *someone else's* tasks, because every fixture
# is written by the same author. This harness runs an external benchmark spec
# — a list of tasks with a command, a metric source and a threshold — and
# reports per-task outcomes without fabricating anything:
#
# * a task whose command or working directory is missing is `unavailable` and
#   excluded from the pass denominator, exactly like an errored probe;
# * a completed run exits 0 whatever the rate says — this is a measurement;
# * the spec carries a `source` per task so a published score can name where
#   the task came from rather than implying it was invented here.
# ---------------------------------------------------------------------------

BENCH_VERSION = 1
BENCH_PASS = "pass"
BENCH_FAIL = "fail"
BENCH_UNAVAILABLE = "unavailable"
BENCH_PLANNED = "planned"


def load_benchmark(path: Path) -> dict:
    """Validate a benchmark spec before anything is executed."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"找不到 benchmark spec: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"无法解析 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"{path} 需要非空 tasks 列表")
    seen: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"tasks[{index}] 必须是映射")
        for field in ("id", "command"):
            if field not in task:
                raise ValueError(f"tasks[{index}] 缺少 {field}")
        task_id = task["id"]
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"tasks[{index}].id 必须是非空字符串")
        if task_id in seen:
            raise ValueError(f"task id 重复: {task_id!r}")
        seen.add(task_id)
        command = task["command"]
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) for part in command
        ):
            raise ValueError(f"tasks[{index}].command 必须是非空字符串数组")
        metric = task.get("metric")
        if metric is not None and not isinstance(metric, dict):
            raise ValueError(f"tasks[{index}].metric 必须是映射")
        threshold = task.get("threshold")
        if threshold is not None and not isinstance(threshold, (int, float)):
            raise ValueError(f"tasks[{index}].threshold 必须是数字")
    return payload


def _read_metric(workdir: Path, metric: dict | None):
    """Read a numeric metric from ``{path, key}`` inside the task workdir."""
    if not metric:
        return None
    relative = metric.get("path")
    if not isinstance(relative, str) or not relative:
        return None
    candidate = (workdir / relative).resolve()
    try:
        candidate.relative_to(workdir.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    key = metric.get("key")
    if isinstance(key, str) and key:
        for part in key.split("."):
            if isinstance(payload, dict) and part in payload:
                payload = payload[part]
            else:
                return None
    if isinstance(payload, bool) or not isinstance(payload, (int, float)):
        return None
    return float(payload)


def run_benchmark(
    spec: dict,
    *,
    spec_path: Path | None = None,
    timeout: float = 600.0,
    dry_run: bool = False,
) -> dict:
    """Run every task in the spec; never raise for a single task's failure."""
    base = Path(spec_path).parent if spec_path else Path.cwd()
    results: list[dict] = []
    for task in spec.get("tasks", []):
        workdir = (base / str(task.get("workdir", "."))).resolve()
        entry = {
            "id": task["id"],
            "source": task.get("source", ""),
            "note": task.get("note", ""),
            "command": list(task["command"]),
            "workdir": str(workdir),
            "threshold": task.get("threshold"),
        }
        if dry_run:
            entry["outcome"] = BENCH_PLANNED
            entry["detail"] = "dry-run：未执行"
            results.append(entry)
            continue
        if not workdir.is_dir():
            entry["outcome"] = BENCH_UNAVAILABLE
            entry["detail"] = f"workdir 不存在: {workdir}"
            results.append(entry)
            continue
        try:
            completed = subprocess.run(
                task["command"],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            entry["outcome"] = BENCH_UNAVAILABLE
            entry["detail"] = f"命令不可用: {exc}"
            results.append(entry)
            continue
        except subprocess.TimeoutExpired:
            entry["outcome"] = BENCH_FAIL
            entry["detail"] = f"超过 {timeout:.0f}s 未完成"
            results.append(entry)
            continue
        entry["returncode"] = completed.returncode
        metric = _read_metric(workdir, task.get("metric"))
        entry["metric"] = metric
        threshold = task.get("threshold")
        if completed.returncode != 0:
            entry["outcome"] = BENCH_FAIL
            entry["detail"] = f"退出码 {completed.returncode}"
        elif threshold is not None and metric is None:
            entry["outcome"] = BENCH_FAIL
            entry["detail"] = "没有读到度量值"
        elif threshold is not None and metric < float(threshold):
            entry["outcome"] = BENCH_FAIL
            entry["detail"] = f"metric {metric} < threshold {threshold}"
        else:
            entry["outcome"] = BENCH_PASS
            entry["detail"] = (
                f"metric {metric} >= {threshold}"
                if threshold is not None
                else "命令成功"
            )
        entry["stdout_tail"] = (completed.stdout or "").strip()[-400:]
        entry["stderr_tail"] = (completed.stderr or "").strip()[-400:]
        results.append(entry)
    return {
        "version": BENCH_VERSION,
        "generated_at": _now_iso(),
        "name": spec.get("name", "benchmark"),
        "dry_run": dry_run,
        "results": results,
    }


def summarise_benchmark(report: dict) -> dict:
    results = report["results"]
    totals = {
        "tasks": len(results),
        "pass": sum(1 for r in results if r["outcome"] == BENCH_PASS),
        "fail": sum(1 for r in results if r["outcome"] == BENCH_FAIL),
        "unavailable": sum(
            1 for r in results if r["outcome"] == BENCH_UNAVAILABLE
        ),
        "planned": sum(1 for r in results if r["outcome"] == BENCH_PLANNED),
    }
    denominator = totals["pass"] + totals["fail"]
    return {
        "version": report["version"],
        "name": report["name"],
        "generated_at": report["generated_at"],
        "dry_run": report["dry_run"],
        "totals": totals,
        # Unavailable tasks are excluded, exactly like errored probes: a task
        # that could not start is neither a pass nor a failure.
        "pass_rate": _rate(totals["pass"], denominator),
        "results": results,
    }


def render_benchmark_markdown(summary: dict) -> str:
    totals = summary["totals"]
    lines = [
        f"# 外部基准：{summary['name']}",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 任务: {totals['tasks']}（pass {totals['pass']} / fail "
        f"{totals['fail']} / unavailable {totals['unavailable']}）",
        f"- pass_rate: {summary['pass_rate']}",
        "",
        "只测量：跑完退出 0，不可用的任务从分母里剔除，不会把"
        "“没跑起来”算成“通过”。",
        "",
        "| task | source | outcome | metric | threshold | detail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in summary["results"]:
        lines.append(
            f"| `{item['id']}` | {item.get('source', '')} | {item['outcome']} "
            f"| {item.get('metric')} | {item.get('threshold')} "
            f"| {item['detail']} |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="测量工作流自身的 gate 是否能抓住注入的缺陷（只测量）",
    )
    parser.add_argument("--case", action="append", default=None, help="只跑指定 id")
    parser.add_argument("--out", default=None, help="写入 Markdown 报告")
    parser.add_argument("--json", default=None, help="写入 JSON 报告")
    parser.add_argument(
        "--benchmark",
        default=None,
        help="运行外部基准 spec（YAML/JSON），而不是内置注入用例",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="每个外部任务的时间上限（秒）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出外部任务，不执行",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    if args.benchmark:
        try:
            spec_path = Path(args.benchmark)
            spec = load_benchmark(spec_path)
            report = run_benchmark(
                spec,
                spec_path=spec_path,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
            summary = summarise_benchmark(report)
            if args.out:
                save_text_atomically(
                    Path(args.out),
                    render_benchmark_markdown(summary),
                    description="外部基准报告",
                )
            if args.json:
                save_text_atomically(
                    Path(args.json),
                    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    description="外部基准 JSON",
                )
        except (OSError, ValueError) as exc:
            return tool_error(str(exc))
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        totals = summary["totals"]
        print(
            f"tool-eval bench: {totals['tasks']} tasks, {totals['pass']} pass, "
            f"{totals['fail']} fail, {totals['unavailable']} unavailable",
            file=sys.stderr,
        )
        # Measurement, not a gate: a completed benchmark exits 0.
        return 0
    selected = CASES
    if args.case:
        wanted = set(args.case)
        selected = tuple(case for case in CASES if case.id in wanted)
        missing = wanted - {case.id for case in selected}
        if missing:
            return tool_error(f"未知用例: {', '.join(sorted(missing))}")
    try:
        summary = summarise(run_cases(selected))
        if args.out:
            save_text_atomically(
                Path(args.out),
                render_markdown(summary),
                description="工具自评报告",
            )
        if args.json:
            save_text_atomically(
                Path(args.json),
                json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                description="工具自评 JSON",
            )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    totals = summary["totals"]
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        f"tool-eval: {totals['cases']} cases, {totals['caught']} caught, "
        f"{totals['missed']} missed, {totals['false_alarms']} false alarms, "
        f"{totals['errors']} errors",
        file=sys.stderr,
    )
    # Measurement, not a gate: a completed run exits 0 whatever the rates say.
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
