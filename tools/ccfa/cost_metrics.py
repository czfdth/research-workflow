"""Derive attempt economics from artifacts instead of from hand-written prose.

``data/cost-ledger.yaml`` carries two metrics — ``time_to_first_attempt`` and
``cost_per_attempt`` — and the top-venue evaluation is blunt about why they
exist: if the distance from a frozen plan to the first scorable attempt is
days, the workflow is drifting into auditing. A hand-written ``0.0`` cannot
show that, so this module recomputes both from what the paper actually wrote:

* plan freeze: the ``ccfa.yaml`` ``stage.history`` entry that reaches
  ``grounded``, or a ``Frozen at:`` / ``frozen_at:`` line in the plan
  artifact. The timestamp has to carry a time; a bare date cannot measure an
  interval and is reported as such.
* first attempt: the earliest ``experiments/log/*.json`` whose purpose is not
  ``build``.
* attempts and spend: ``experiments/log/compute-ledger.jsonl`` (written by
  ``ccfa.experiment_loop`` and ``ccfa compute run``) priced with the optional
  ``pricing`` block from ``data/compute.yaml``.

Nothing is estimated. When an input is missing, the metric is reported
``not-applicable`` with the exact reason and the file that would have to
change, and ``check`` fails when the recorded ledger disagrees with the
derivation in either direction.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error

STATE_FILE = Path("ccfa.yaml")
PLAN_ARTIFACT = Path("ccfa-workfiles") / "idea" / "idea-selection.md"
RUN_LOG_DIR = Path("experiments") / "log"
COMPUTE_LEDGER = RUN_LOG_DIR / "compute-ledger.jsonl"
COMPUTE_CONFIG = Path("data") / "compute.yaml"
COST_LEDGER = Path("data") / "cost-ledger.yaml"

BUILD_PURPOSE = "build"
LOCAL_BACKEND = "local"
FREEZE_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:frozen(?:\s+at)?|plan[_ -]frozen(?:_at)?)\s*[:：]\s*(\S.*)$",
    re.IGNORECASE | re.MULTILINE,
)
METRIC_NAMES = ("time_to_first_attempt", "cost_per_attempt")
METRICS_BLOCK = re.compile(r"^metrics:[^\n]*\n(?:[ \t][^\n]*\n|\n)*", re.MULTILINE)


@dataclass(frozen=True)
class Verdict:
    name: str
    status: str
    value: float | None
    unit: str | None
    currency: str | None
    source: str
    reason: str

    def as_metric(self) -> dict:
        if self.status == "recorded":
            payload: dict = {"status": "recorded", "value": self.value}
            if self.unit is not None:
                payload["unit"] = self.unit
            if self.currency is not None:
                payload["currency"] = self.currency
            payload["source"] = self.source
            return payload
        return {"status": "not-applicable", "reason": self.reason}

    def as_report(self) -> dict:
        return {
            "status": self.status,
            "value": self.value,
            "unit": self.unit,
            "currency": self.currency,
            "source": self.source,
            "reason": self.reason,
        }


def _parse_stamp(raw: object) -> tuple[datetime, bool] | None:
    """Parse an ISO-8601 stamp into UTC; the flag says whether it had a time."""

    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    has_time = "T" in text or " " in text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), has_time


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


def _plan_freeze(paper_root: Path) -> dict:
    """Find the timestamped plan freeze, or say exactly why there is none."""

    state_path = paper_root / STATE_FILE
    payload, error = _load_yaml(state_path)
    if error:
        return {"status": "missing", "source": "", "note": error}
    history = payload.get("stage", {}).get("history") if payload else None
    date_only = ""
    if isinstance(history, list):
        candidates = []
        for entry in history:
            if not isinstance(entry, dict) or entry.get("to") != "grounded":
                continue
            parsed = _parse_stamp(entry.get("at"))
            if parsed is None:
                continue
            stamp, has_time = parsed
            if has_time:
                candidates.append((stamp, entry.get("at")))
            elif not date_only:
                date_only = str(entry.get("at"))
        if candidates:
            candidates.sort(key=lambda item: item[0])
            stamp, raw = candidates[0]
            return {
                "status": "recorded",
                "when": stamp,
                "source": (
                    f"{state_path.as_posix()} stage.history 到 grounded 的时间戳 {raw}"
                ),
                "note": "",
            }

    artifact = paper_root / PLAN_ARTIFACT
    if artifact.is_file():
        try:
            text = artifact.read_text(encoding="utf-8")
        except OSError:
            text = ""
        match = FREEZE_LINE.search(text)
        if match:
            parsed = _parse_stamp(match.group(1))
            if parsed is not None and parsed[1]:
                return {
                    "status": "recorded",
                    "when": parsed[0],
                    "source": (
                        f"{artifact.as_posix()} 的 Frozen at 行 {match.group(1).strip()}"
                    ),
                    "note": "",
                }
            if parsed is not None and not date_only:
                date_only = match.group(1).strip()

    if date_only:
        note = (
            f"计划冻结只有日期（{date_only}），没有时刻，算不出到首次尝试的间隔；"
            f"把 {STATE_FILE.as_posix()} 的 stage.history 时间戳（或 "
            f"{PLAN_ARTIFACT.as_posix()} 的 Frozen at 行）写成带时刻的 "
            "ISO-8601（如 2026-10-06T09:30:00Z）后重跑 derive"
        )
    else:
        note = (
            f"没有找到带时刻的计划冻结记录：{state_path.as_posix()} 的 "
            f"stage.history 里没有到 grounded 的时间戳，"
            f"{artifact.as_posix()} 里也没有 Frozen at 行"
        )
    return {"status": "missing", "source": "", "note": note}


def _run_entries(paper_root: Path) -> tuple[list[dict], int]:
    """Non-build run-log entries plus how many build runs were skipped."""

    directory = paper_root / RUN_LOG_DIR
    attempts: list[dict] = []
    builds = 0
    if not directory.is_dir():
        return attempts, builds
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        raw_purpose = payload.get("declared_purpose", payload.get("purpose"))
        purpose = raw_purpose.strip().lower() if isinstance(raw_purpose, str) else ""
        if purpose == BUILD_PURPOSE:
            builds += 1
            continue
        stamp = _parse_stamp(payload.get("started_at") or payload.get("finished_at"))
        attempts.append(
            {
                "path": path,
                "run_id": payload.get("run_id") or path.stem,
                "purpose": purpose or "(未声明)",
                "stamp": stamp[0] if stamp else None,
            }
        )
    attempts.sort(
        key=lambda item: item["stamp"] or datetime.max.replace(tzinfo=timezone.utc)
    )
    return attempts, builds


def _compute_entries(paper_root: Path) -> tuple[list[dict], int]:
    path = paper_root / COMPUTE_LEDGER
    entries: list[dict] = []
    malformed = 0
    if not path.is_file():
        return entries, malformed
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return entries, malformed
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(payload, dict):
            entries.append(payload)
        else:
            malformed += 1
    return entries, malformed


def _pricing(paper_root: Path) -> tuple[dict | None, str | None]:
    """Read the optional pricing block from ``data/compute.yaml``."""

    payload, error = _load_yaml(paper_root / COMPUTE_CONFIG)
    if error:
        return None, error
    pricing = payload.get("pricing") if payload else None
    if pricing is None:
        return None, None
    if not isinstance(pricing, dict):
        return None, f"{COMPUTE_CONFIG.as_posix()} 的 pricing 必须是映射"
    clean: dict = {}
    currency = pricing.get("currency", "USD")
    if not isinstance(currency, str) or not currency.strip():
        return None, f"{COMPUTE_CONFIG.as_posix()} pricing.currency 必须是非空字符串"
    clean["currency"] = currency.strip()
    for field in ("cpu_hour_usd", "gpu_hour_usd"):
        raw = pricing.get(field)
        if raw is None:
            continue
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(raw)
            or raw < 0
        ):
            return None, f"{COMPUTE_CONFIG.as_posix()} pricing.{field} 必须是有限非负数"
        clean[field] = float(raw)
    return clean, None


def _number(payload: dict, field: str) -> float | None:
    raw = payload.get(field)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if not math.isfinite(raw) or raw < 0:
        return None
    return float(raw)


def derive_time_to_first_attempt(paper_root: Path) -> Verdict:
    name = "time_to_first_attempt"
    freeze = _plan_freeze(paper_root)
    attempts, builds = _run_entries(paper_root)
    if freeze["status"] != "recorded":
        return Verdict(name, "not-applicable", None, "hours", None, "", freeze["note"])
    if not attempts:
        return Verdict(
            name,
            "not-applicable",
            None,
            "hours",
            None,
            "",
            f"没有非 build 运行记录（{builds} 条 build 运行被跳过），"
            "首次可评分尝试还不存在，间隔没有测量对象",
        )
    first = attempts[0]
    if first["stamp"] is None:
        return Verdict(
            name,
            "not-applicable",
            None,
            "hours",
            None,
            "",
            f"{first['path'].relative_to(paper_root).as_posix()} 没有可解析的 "
            "started_at/finished_at，首次尝试的时刻不可知",
        )
    frozen_at = freeze["when"]
    if first["stamp"] < frozen_at:
        return Verdict(
            name,
            "not-applicable",
            None,
            "hours",
            None,
            "",
            f"首次尝试 {first['run_id']}（{first['stamp'].isoformat()}）早于"
            f"计划冻结（{frozen_at.isoformat()}，来源 {freeze['source']}），"
            "顺序不成立，间隔不能计算",
        )
    hours = (first["stamp"] - frozen_at).total_seconds() / 3600.0
    return Verdict(
        name,
        "recorded",
        round(hours, 4),
        "hours",
        None,
        (
            f"计划冻结 {frozen_at.isoformat()}（{freeze['source']}）→ "
            f"首次非 build 尝试 {first['run_id']} "
            f"{first['stamp'].isoformat()} "
            f"（{first['path'].relative_to(paper_root).as_posix()}，"
            f"purpose={first['purpose']}）"
        ),
        "",
    )


def derive_cost_per_attempt(paper_root: Path) -> Verdict:
    name = "cost_per_attempt"
    attempts, builds = _run_entries(paper_root)
    entries, malformed = _compute_entries(paper_root)
    counted = len(entries) if entries else len(attempts)
    if counted == 0:
        return Verdict(
            name,
            "not-applicable",
            None,
            None,
            None,
            "",
            f"没有非 build 尝试（{builds} 条 build 运行被跳过），"
            f"{COMPUTE_LEDGER.as_posix()} 也没有条目，"
            "单次尝试成本没有可测对象——0.0 在这里不是测量，是不适用",
        )

    pricing, pricing_error = _pricing(paper_root)
    if pricing_error:
        return Verdict(name, "not-applicable", None, None, None, "", pricing_error)

    currency = (pricing or {}).get("currency", "USD")
    total = 0.0
    unpriced: list[str] = []
    covered = 0
    for index, entry in enumerate(entries, start=1):
        backend = entry.get("backend")
        backend = (
            backend.strip()
            if isinstance(backend, str) and backend.strip()
            else "unknown"
        )
        wall_hours = (_number(entry, "wall_seconds") or 0.0) / 3600.0
        gpus = _number(entry, "gpus_used") or 0.0
        if gpus > 0:
            rate = (pricing or {}).get("gpu_hour_usd")
            field = "gpu_hour_usd"
            hours = wall_hours * gpus
        else:
            rate = (pricing or {}).get("cpu_hour_usd")
            field = "cpu_hour_usd"
            hours = wall_hours
        if rate is None:
            if backend != LOCAL_BACKEND:
                unpriced.append(f"条目 {index}（backend={backend}）缺 pricing.{field}")
            continue
        covered += 1
        total += hours * rate

    if unpriced:
        return Verdict(
            name,
            "not-applicable",
            None,
            None,
            None,
            "",
            (
                "有尝试用了非本机后端但 "
                f"{COMPUTE_CONFIG.as_posix()} 没有声明对应定价："
                + "；".join(unpriced)
                + "。声明 pricing.cpu_hour_usd / pricing.gpu_hour_usd 后重跑 derive"
            ),
        )

    unmetered = max(0, len(attempts) - len(entries))
    value = round(total / counted, 6)
    source = (
        f"{COMPUTE_LEDGER.as_posix()} 的 {len(entries)} 条记录"
        f"（{covered} 条按 {COMPUTE_CONFIG.as_posix()} 的 pricing 计价，"
        f"{len(entries) - covered} 条本机记录按 0 计）"
        f"除以 {counted} 次尝试；run-log 另有 {unmetered} 次尝试没有"
        "compute-ledger 记录，按 0 计但不代表免费"
    )
    if malformed:
        source += f"；{malformed} 行 compute-ledger 无法解析，已跳过"
    return Verdict(name, "recorded", value, None, currency, source, "")


def derive(paper_root: Path) -> dict:
    paper_root = Path(paper_root)
    metrics = {
        "time_to_first_attempt": derive_time_to_first_attempt(paper_root),
        "cost_per_attempt": derive_cost_per_attempt(paper_root),
    }
    attempts, builds = _run_entries(paper_root)
    entries, malformed = _compute_entries(paper_root)
    freeze = _plan_freeze(paper_root)
    return {
        "paper_root": str(paper_root),
        "metrics": {name: verdict.as_report() for name, verdict in metrics.items()},
        "evidence": {
            "plan_freeze": {
                "status": freeze["status"],
                "source": freeze["source"],
                "note": freeze["note"],
            },
            "non_build_attempts": [item["run_id"] for item in attempts],
            "build_runs_skipped": builds,
            "compute_ledger_entries": len(entries),
            "compute_ledger_malformed": malformed,
        },
    }


def _load_ledger_metrics(paper_root: Path) -> tuple[dict | None, str | None]:
    payload, error = _load_yaml(paper_root / COST_LEDGER)
    if error:
        return None, error
    if payload is None:
        return None, f"{COST_LEDGER.as_posix()} 不存在"
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return None, f"{COST_LEDGER.as_posix()} 缺少 metrics 映射"
    return metrics, None


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Fail when the recorded ledger disagrees with the derivation."""

    paper_root = Path(paper_root)
    path = paper_root / COST_LEDGER
    problems: list[Problem] = []
    advisories: list[Problem] = []
    ledger, error = _load_ledger_metrics(paper_root)
    if ledger is None:
        return [Problem("cost-ledger-unreadable", str(path), None, error or "")], []

    derived = {
        "time_to_first_attempt": derive_time_to_first_attempt(paper_root),
        "cost_per_attempt": derive_cost_per_attempt(paper_root),
    }
    for name in METRIC_NAMES:
        verdict = derived[name]
        item = ledger.get(name)
        if not isinstance(item, dict):
            problems.append(
                Problem(
                    "cost-metrics-missing",
                    str(path),
                    None,
                    f"metrics.{name} 缺失，derive 已给出可用结论",
                )
            )
            continue
        status = item.get("status")
        if status == "recorded":
            value = item.get("value")
            if verdict.status != "recorded":
                problems.append(
                    Problem(
                        "cost-ledger-drift",
                        str(path),
                        None,
                        f"metrics.{name} 记为 recorded={value}，但产物推不出这个值："
                        f"{verdict.reason}",
                    )
                )
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or abs(float(value) - float(verdict.value)) > 1e-9
            ):
                problems.append(
                    Problem(
                        "cost-ledger-drift",
                        str(path),
                        None,
                        f"metrics.{name} 记为 {value}，derive 得到 {verdict.value}；"
                        "跑 derive --write 同步",
                    )
                )
                continue
            continue
        if verdict.status == "recorded":
            problems.append(
                Problem(
                    "cost-ledger-drift",
                    str(path),
                    None,
                    f"metrics.{name} 记为 {status}，但产物已经能推出 "
                    f"{verdict.value}（{verdict.source}）；跑 derive --write 同步",
                )
            )
            continue
        advisories.append(
            Problem(
                "cost-metrics-not-applicable",
                str(path),
                None,
                f"metrics.{name} 不适用：{verdict.reason}",
            )
        )
    return problems, advisories


def write_metrics(paper_root: Path) -> Path:
    """Rewrite only the ``metrics:`` block; every other byte stays put."""

    import yaml

    paper_root = Path(paper_root)
    path = paper_root / COST_LEDGER
    if not path.is_file():
        raise ValueError(f"{COST_LEDGER.as_posix()} 不存在，先写成本台账骨架")
    text = path.read_text(encoding="utf-8")
    metrics = {
        "time_to_first_attempt": derive_time_to_first_attempt(paper_root).as_metric(),
        "cost_per_attempt": derive_cost_per_attempt(paper_root).as_metric(),
    }
    block = yaml.safe_dump(
        {"metrics": metrics},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=88,
    )
    updated, count = METRICS_BLOCK.subn(block, text, count=1)
    if count == 0:
        updated = text.rstrip("\n") + "\n" + block
    save_text_atomically(path, updated, description=COST_LEDGER.as_posix())
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从产物推导 time_to_first_attempt 与 cost_per_attempt"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    derive_parser = sub.add_parser("derive", help="重算两个指标并打印推导依据")
    derive_parser.add_argument("--paper-root", default=".")
    derive_parser.add_argument(
        "--write",
        action="store_true",
        help="把结果写回 data/cost-ledger.yaml 的 metrics 块",
    )
    check_parser = sub.add_parser("check", help="校验台账与推导是否一致")
    check_parser.add_argument("--paper-root", default=".")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        paper_root = Path(args.paper_root)
        if args.command == "derive":
            report = derive(paper_root)
            if args.write:
                path = write_metrics(paper_root)
                report["wrote"] = str(path)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "check":
            problems, advisories = check(paper_root)
            return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return tool_error(f"未知命令: {args.command}")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
