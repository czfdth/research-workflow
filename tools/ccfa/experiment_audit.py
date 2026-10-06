"""Deterministic half of ARIS's ``/experiment-audit`` role.

ARIS runs that role as a model persona. A persona can notice a suspicious
table, but it cannot make a gate that says no, so the four failure modes it
targets are encoded here as checks over ``data/experiment-audit.yaml``:

* **fake ground truth** — labels produced by the system under test, or by a
  model that nobody spot-checked (``ground_truth.source`` /
  ``producer`` / ``verified_by`` / ``n_reviewed`` / ``agreement``);
* **score-normalisation cheating** — normalisation statistics fit on the test
  split, or best-of-N/threshold selection tuned on it (``metrics`` entries);
* **phantom results** — a result bound to a run that does not exist, a run
  that never finished, a build run, or an artifact that is not on disk;
* **scope inflation** — an experiment that lists no limits, or three-seed
  claims backed by one seed (``limits``, ``evaluation.seeds``).

The ledger is empirical-paper-only: ``ccfa.readiness`` runs this gate only when
the file exists, and only requires it in the ``high-assurance`` profile, so a
SoK or a theory paper is unaffected. Model review of the same questions stays
where it belongs — ``ccfa adversarial-review --role experiment-audit`` — which
can produce findings but can never acquit.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, tool_error

AUDIT_LEDGER = Path("data") / "experiment-audit.yaml"
CLAIM_REGISTRY = Path("data") / "claim-registry.yaml"
RUN_LOG_DIR = Path("experiments") / "log"

GROUND_TRUTH_SOURCES = {"dataset", "human", "model", "derived"}
VERIFICATION_SOURCES = {"human", "second-model", "none"}
NORMALIZATIONS = {"none", "per-item", "z-score", "min-max"}
FIT_SOURCES = {"none", "train", "dev", "test"}
SELECTIONS = {"single", "best-of-n", "threshold"}
# Thresholds are deliberately explicit constants: a paper can argue with a
# number it can see, not with "the auditor felt uneasy".
MIN_HUMAN_SPOT_CHECKS = 20
MIN_AGREEMENT = 0.8
MIN_SEEDS = 3


def _load_yaml(path: Path) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return None, f"{path.as_posix()} 无法解析: {type(exc).__name__}"
    if payload is None:
        return None, None
    if not isinstance(payload, dict):
        return None, f"{path.as_posix()} 顶层必须是映射"
    return payload, None


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: object, *, allow_ints: bool = False) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if isinstance(item, str) and item.strip():
            continue
        if allow_ints and isinstance(item, int) and not isinstance(item, bool):
            continue
        return False
    return True


def _run_records(paper_root: Path) -> dict[str, dict]:
    """Index ``experiments/log/*.json`` by run id."""

    directory = paper_root / RUN_LOG_DIR
    records: dict[str, dict] = {}
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        run_id = payload.get("run_id") or path.stem
        if isinstance(run_id, str) and run_id.strip():
            records[run_id] = payload
    return records


def _claim_ids(paper_root: Path) -> set[str] | None:
    payload, error = _load_yaml(paper_root / CLAIM_REGISTRY)
    if error or payload is None:
        return None
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return None
    ids: set[str] = set()
    for item in claims:
        if isinstance(item, dict) and _nonempty_str(item.get("id")):
            ids.add(item["id"].strip())
    return ids


def _check_run(
    run_id: str,
    records: dict[str, dict],
    path: Path,
    where: str,
    problems: list[Problem],
    advisories: list[Problem],
) -> None:
    payload = records.get(run_id)
    if payload is None:
        problems.append(
            Problem(
                "experiment-audit-run-missing",
                str(path),
                None,
                f"{where}: 引用了 run {run_id!r}，但 {RUN_LOG_DIR.as_posix()}/ "
                "里没有这条记录",
            )
        )
        return
    purpose = payload.get("declared_purpose", payload.get("purpose"))
    purpose = purpose.strip().lower() if isinstance(purpose, str) else ""
    if purpose == "build":
        problems.append(
            Problem(
                "experiment-audit-run-is-build",
                str(path),
                None,
                f"{where}: run {run_id!r} 声明为 build，不能支撑实验结果",
            )
        )
    status = payload.get("status")
    exit_code = payload.get("exit_code")
    if status != "completed" or (isinstance(exit_code, int) and exit_code != 0):
        problems.append(
            Problem(
                "experiment-audit-run-failed",
                str(path),
                None,
                f"{where}: run {run_id!r} 的 status={status!r}, "
                f"exit_code={exit_code!r}，失败运行不能产出可信结果",
            )
        )
    if payload.get("git_dirty") and not payload.get("dirty_waiver"):
        advisories.append(
            Problem(
                "experiment-audit-run-dirty",
                str(path),
                None,
                f"{where}: run {run_id!r} 在脏树上执行且没有 dirty_waiver，"
                "结果无法用 commit 复现（advisory）",
            )
        )


def _check_ground_truth(
    ground_truth: object,
    systems: list[str],
    path: Path,
    where: str,
    problems: list[Problem],
    advisories: list[Problem],
) -> None:
    if not isinstance(ground_truth, dict):
        problems.append(
            Problem(
                "experiment-audit-entry-invalid",
                str(path),
                None,
                f"{where}.ground_truth 缺失或不是映射",
            )
        )
        return
    source = ground_truth.get("source")
    if source not in GROUND_TRUTH_SOURCES:
        problems.append(
            Problem(
                "experiment-audit-entry-invalid",
                str(path),
                None,
                f"{where}.ground_truth.source 非法: {source!r}，"
                f"应为 {'/'.join(sorted(GROUND_TRUTH_SOURCES))}",
            )
        )
        return
    producer = ground_truth.get("producer")
    if not _nonempty_str(producer):
        problems.append(
            Problem(
                "experiment-audit-entry-invalid",
                str(path),
                None,
                f"{where}.ground_truth.producer 必须写明标签/答案是谁产出的",
            )
        )
    verification = ground_truth.get("verified_by", "none")
    if verification not in VERIFICATION_SOURCES:
        problems.append(
            Problem(
                "experiment-audit-entry-invalid",
                str(path),
                None,
                f"{where}.ground_truth.verified_by 非法: {verification!r}",
            )
        )
        return
    if source == "model":
        if isinstance(producer, str) and producer.strip().lower() in {
            system.strip().lower() for system in systems
        }:
            problems.append(
                Problem(
                    "experiment-audit-ground-truth-self-generated",
                    str(path),
                    None,
                    f"{where}: ground truth 由被评测系统 {producer!r} 自己产出，"
                    "任何基于它的分数都是自证",
                )
            )
        if verification == "none":
            problems.append(
                Problem(
                    "experiment-audit-ground-truth-unverified",
                    str(path),
                    None,
                    f"{where}: 模型生成的 ground truth 没有任何人工抽检",
                )
            )
            return
        if verification == "second-model":
            advisories.append(
                Problem(
                    "experiment-audit-ground-truth-model-verified",
                    str(path),
                    None,
                    f"{where}: ground truth 由第二个模型复核；模型不能为标签背书，"
                    "只能作为人工抽检的补充（advisory）",
                )
            )
        count = ground_truth.get("n_reviewed")
        agreement = ground_truth.get("agreement")
        count_ok = (
            isinstance(count, int)
            and not isinstance(count, bool)
            and count >= MIN_HUMAN_SPOT_CHECKS
        )
        agreement_ok = (
            isinstance(agreement, (int, float))
            and not isinstance(agreement, bool)
            and math.isfinite(agreement)
            and MIN_AGREEMENT <= float(agreement) <= 1.0
        )
        if not count_ok or not agreement_ok:
            problems.append(
                Problem(
                    "experiment-audit-ground-truth-weak-verification",
                    str(path),
                    None,
                    f"{where}: {verification} 复核需要 n_reviewed >= "
                    f"{MIN_HUMAN_SPOT_CHECKS} 且 {MIN_AGREEMENT} <= agreement <= 1，"
                    f"实际 n_reviewed={count!r}, agreement={agreement!r}",
                )
            )


def _check_metrics(
    metrics: object,
    path: Path,
    where: str,
    problems: list[Problem],
) -> None:
    if not isinstance(metrics, list) or not metrics:
        problems.append(
            Problem(
                "experiment-audit-entry-invalid",
                str(path),
                None,
                f"{where}.metrics 必须是非空列表",
            )
        )
        return
    for index, metric in enumerate(metrics):
        position = f"{where}.metrics[{index}]"
        if not isinstance(metric, dict) or not _nonempty_str(metric.get("name")):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position} 必须是有 name 的映射",
                )
            )
            continue
        normalization = metric.get("normalization", "none")
        fit_on = metric.get("fit_on", "none")
        if normalization not in NORMALIZATIONS:
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position}.normalization 非法: {normalization!r}",
                )
            )
        elif fit_on not in FIT_SOURCES:
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position}.fit_on 非法: {fit_on!r}",
                )
            )
        elif normalization == "none" and fit_on != "none":
            problems.append(
                Problem(
                    "experiment-audit-normalization-inconsistent",
                    str(path),
                    None,
                    f"{position}: normalization=none 却声明 fit_on={fit_on!r}",
                )
            )
        elif normalization != "none" and fit_on == "test":
            problems.append(
                Problem(
                    "experiment-audit-normalization-leak",
                    str(path),
                    None,
                    f"{position}: 归一化统计量在 test 上拟合，测试集信息泄漏进"
                    "报告分数",
                )
            )
        selection = metric.get("selection", "single")
        selection_on = metric.get("selection_on", "none")
        if selection not in SELECTIONS:
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position}.selection 非法: {selection!r}",
                )
            )
        elif selection_on not in FIT_SOURCES:
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position}.selection_on 非法: {selection_on!r}",
                )
            )
        elif selection != "single" and selection_on == "test":
            problems.append(
                Problem(
                    "experiment-audit-selection-leak",
                    str(path),
                    None,
                    f"{position}: 报告值经 {selection} 在 test 上挑选，"
                    "这是挑选而不是结果",
                )
            )
        elif selection != "single" and selection_on == "none":
            problems.append(
                Problem(
                    "experiment-audit-selection-undeclared",
                    str(path),
                    None,
                    f"{position}: selection={selection} 但没有声明 selection_on",
                )
            )


def _check_results(
    entry: dict,
    paper_root: Path,
    records: dict[str, dict],
    claim_ids: set[str] | None,
    path: Path,
    where: str,
    problems: list[Problem],
    advisories: list[Problem],
) -> None:
    results = entry.get("results")
    if not isinstance(results, list):
        problems.append(
            Problem(
                "experiment-audit-entry-invalid",
                str(path),
                None,
                f"{where}.results 必须是列表（可以是空列表）",
            )
        )
        return
    for index, result in enumerate(results):
        position = f"{where}.results[{index}]"
        if not isinstance(result, dict) or not _nonempty_str(result.get("id")):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position} 必须是有 id 的映射",
                )
            )
            continue
        artifact = result.get("artifact")
        if not _nonempty_str(artifact):
            problems.append(
                Problem(
                    "experiment-audit-result-artifact-missing",
                    str(path),
                    None,
                    f"{position} 没有 artifact：结果必须指向一个真实交付物",
                )
            )
        elif not (paper_root / artifact.strip()).is_file():
            problems.append(
                Problem(
                    "experiment-audit-result-artifact-missing",
                    str(path),
                    None,
                    f"{position}: artifact {artifact!r} 在论文里不存在（幽灵结果）",
                )
            )
        bound_runs = result.get("run_ids")
        if not _string_list(bound_runs):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position}.run_ids 必须是非空字符串列表",
                )
            )
        else:
            for run_id in bound_runs:
                _check_run(
                    run_id.strip(),
                    records,
                    path,
                    position,
                    problems,
                    advisories,
                )
        claims = result.get("claims", [])
        if claims and not _string_list(claims):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{position}.claims 必须是字符串列表",
                )
            )
        elif claims and claim_ids is not None:
            for claim_id in claims:
                if claim_id.strip() not in claim_ids:
                    problems.append(
                        Problem(
                            "experiment-audit-claim-unknown",
                            str(path),
                            None,
                            f"{position}: claim {claim_id!r} 不在 "
                            f"{CLAIM_REGISTRY.as_posix()} 里",
                        )
                    )


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Return (problems, advisories) for one paper's experiment audit ledger."""

    paper_root = Path(paper_root)
    path = paper_root / AUDIT_LEDGER
    problems: list[Problem] = []
    advisories: list[Problem] = []
    payload, error = _load_yaml(path)
    if error:
        return [Problem("experiment-audit-invalid", str(path), None, error)], []
    if payload is None:
        return [], [
            Problem(
                "experiment-audit-missing",
                str(path),
                None,
                "没有实验审计台账：实证论文需要它来声明 ground truth 来源、"
                "归一化/选择方式、结果产物与适用范围",
            )
        ]
    version = payload.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        problems.append(
            Problem(
                "experiment-audit-invalid",
                str(path),
                None,
                "version 必须是整数",
            )
        )
    entries = payload.get("experiments")
    if not isinstance(entries, list):
        problems.append(
            Problem(
                "experiment-audit-invalid",
                str(path),
                None,
                "experiments 必须是列表",
            )
        )
        return problems, advisories
    if not entries:
        advisories.append(
            Problem(
                "experiment-audit-empty",
                str(path),
                None,
                "台账存在但没有任何实验条目：确认这篇论文确实不做实证",
            )
        )
    records = _run_records(paper_root)
    claim_ids = _claim_ids(paper_root)
    for index, entry in enumerate(entries):
        where = f"experiments[{index}]"
        if not isinstance(entry, dict):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{where} 必须是映射",
                )
            )
            continue
        if not _nonempty_str(entry.get("id")):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{where}.id 必须是非空字符串",
                )
            )
            continue
        where = f"{where}({entry['id']})"
        run_ids = entry.get("run_ids")
        if not _string_list(run_ids):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{where}.run_ids 必须是非空字符串列表",
                )
            )
        else:
            for run_id in run_ids:
                _check_run(
                    run_id.strip(),
                    records,
                    path,
                    where,
                    problems,
                    advisories,
                )
        evaluation = entry.get("evaluation")
        systems: list[str] = []
        if not isinstance(evaluation, dict):
            problems.append(
                Problem(
                    "experiment-audit-entry-invalid",
                    str(path),
                    None,
                    f"{where}.evaluation 缺失或不是映射",
                )
            )
        else:
            if not _string_list(evaluation.get("systems")):
                problems.append(
                    Problem(
                        "experiment-audit-entry-invalid",
                        str(path),
                        None,
                        f"{where}.evaluation.systems 必须是非空字符串列表",
                    )
                )
            else:
                systems = [item.strip() for item in evaluation["systems"]]
            if not _string_list(evaluation.get("datasets")):
                problems.append(
                    Problem(
                        "experiment-audit-entry-invalid",
                        str(path),
                        None,
                        f"{where}.evaluation.datasets 必须是非空字符串列表",
                    )
                )
            seeds = evaluation.get("seeds")
            if not _string_list(seeds, allow_ints=True):
                problems.append(
                    Problem(
                        "experiment-audit-entry-invalid",
                        str(path),
                        None,
                        f"{where}.evaluation.seeds 必须是非空列表",
                    )
                )
            elif len(seeds) < MIN_SEEDS:
                advisories.append(
                    Problem(
                        "experiment-audit-few-seeds",
                        str(path),
                        None,
                        f"{where}: 只用了 {len(seeds)} 个种子；"
                        f"{MIN_SEEDS} 个以下的结果很难支撑泛化表述（advisory）",
                    )
                )
        _check_ground_truth(
            entry.get("ground_truth"),
            systems,
            path,
            where,
            problems,
            advisories,
        )
        _check_metrics(entry.get("metrics"), path, where, problems)
        _check_results(
            entry,
            paper_root,
            records,
            claim_ids,
            path,
            where,
            problems,
            advisories,
        )
        limits = entry.get("limits")
        if not _nonempty_str(limits):
            problems.append(
                Problem(
                    "experiment-audit-limits-missing",
                    str(path),
                    None,
                    f"{where}.limits 为空：没有边界的实验条目等于在声称无限范围",
                )
            )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="实验审计台账：ground truth、归一化/选择、结果产物与范围边界"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="校验当前论文的实验审计台账")
    check_parser.add_argument("--paper-root", default=".")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check(Path(args.paper_root))
            return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知命令: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
