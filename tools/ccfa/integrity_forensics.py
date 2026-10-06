"""Pinned launcher for the repo ARIS's ``/integrity-forensics`` points at.

ARIS does not implement integrity forensics. Its ``skills/integrity-forensics``
says so itself: *"This skill is a thin launcher: it pins an upstream commit,
validates the pin with the upstream eval gate, delegates execution unchanged,
and post-processes the verdict into ARIS's policy vocabulary. It vendors
nothing and forks nothing."* The detector lives in
``wanshuiyin/Anti-Autoresearch`` (MIT), pinned there at
``b47af6f983b38347b6d2110379e266400597cf66``.

This module is the same shape, in our vocabulary:

* **Pin, never HEAD.** The commit is a constant. ``verify`` fails closed when
  the checkout is not exactly at the pin, and can additionally run upstream's
  own calibration gate (``eval/run_eval.py``) before a sweep is believed.
* **Delegate unchanged.** The deterministic chain is driven as-is:
  ``build_claim_ledger.py`` → ``check_numeric_consistency.py`` /
  ``check_stat_consistency.py`` → ``adjudicate_findings.py``. Every one of
  those is stdlib-only, so nothing is installed beyond the checkout.
* **Never acquit.** Upstream's verdict vocabulary is preserved verbatim and
  mapped to policy, not re-labelled: ``CLEAN_GIVEN_EVIDENCE`` means "no flag
  found in the evidence at hand", never "the paper is honest". ``HARD_FLAGS``
  and ``REVIEW_UNAVAILABLE`` block; ``SOFT_FLAGS`` warns. The AI-style
  impressions carry zero verdict weight upstream and keep zero here.
* **Obligations are append-only.** A finding becomes an obligation; a later
  run that no longer reports it NEVER auto-closes it (an LLM asked to "make
  the flag go away" learns to reword the span faster than to fix the number).
  Closing needs an explicit ``resolve`` with hashed evidence, or a human
  ``waive``. This is ARIS's ``tools/forensics_gate.py`` doctrine, ported.

The checkout is never downloaded implicitly: ``run`` requires an existing
checkout at the pin and fails closed otherwise, so a missing tool can never be
mistaken for a clean paper.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error

SCHEMA_VERSION = 1
PIN_REPO = "https://github.com/wanshuiyin/Anti-Autoresearch.git"
# The same commit ARIS pins. Bumping this is a reviewed change, never a fetch of
# whatever upstream HEAD happens to be.
PIN_COMMIT = "b47af6f983b38347b6d2110379e266400597cf66"
DEFAULT_CHECKOUT = Path.home() / ".ccfa" / "anti-autoresearch"

REPORT_RELATIVE = Path("data") / "integrity-forensics.json"
OBLIGATIONS_RELATIVE = Path("data") / "integrity-obligations.jsonl"
WORKFILES = Path("ccfa-workfiles") / "integrity-forensics"

VERDICT_CLEAN = "CLEAN_GIVEN_EVIDENCE"
VERDICT_SOFT = "SOFT_FLAGS"
VERDICT_HARD = "HARD_FLAGS"
VERDICT_UNAVAILABLE = "REVIEW_UNAVAILABLE"
VERDICTS = (VERDICT_CLEAN, VERDICT_SOFT, VERDICT_HARD, VERDICT_UNAVAILABLE)
BLOCKING_VERDICTS = (VERDICT_HARD, VERDICT_UNAVAILABLE)

SEVERITY_RANK = {"minor": 1, "major": 2, "critical": 3}
CRITICAL = "critical"

PIPELINE = (
    "build_claim_ledger.py",
    "check_numeric_consistency.py",
    "check_stat_consistency.py",
    "adjudicate_findings.py",
)


def _problem(code: str, path: Path | str, message: str) -> Problem:
    return Problem(code, str(path), None, message)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Pin resolution and verification.
# --------------------------------------------------------------------------


def resolve_checkout(explicit: Path | None = None) -> Path:
    """Where the pinned checkout lives (explicit > env > default)."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("CCFA_ANTI_AUTORESEARCH", "").strip()
    if env:
        return Path(env)
    return DEFAULT_CHECKOUT


def checkout_commit(checkout: Path) -> str | None:
    """The checkout's HEAD commit, or None when it is not a git work tree."""
    if not (Path(checkout) / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def verify_checkout(
    checkout: Path,
    *,
    pin: str = PIN_COMMIT,
) -> tuple[list[Problem], list[Problem]]:
    """Fail closed unless the checkout is present and exactly at the pin."""
    checkout = Path(checkout)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not checkout.is_dir():
        return [
            _problem(
                "integrity-forensics-not-installed",
                checkout,
                f"没有 pinned checkout：{checkout}。运行 "
                f"`git clone {PIN_REPO} {checkout}` 并 "
                f"`git -C {checkout} checkout {pin[:12]}`；"
                "本工具不会自动下载，缺工具绝不能被当成「论文干净」",
            )
        ], advisories
    head = checkout_commit(checkout)
    if head is None:
        return [
            _problem(
                "integrity-forensics-not-a-git-checkout",
                checkout,
                "checkout 不是一个 git 工作树；无法核对 pin",
            )
        ], advisories
    if head != pin:
        problems.append(
            _problem(
                "integrity-forensics-pin-mismatch",
                checkout,
                f"checkout 在 {head[:12]}，pin 要求 {pin[:12]}；"
                "上游 HEAD 不追踪，换 pin 是受审阅的改动",
            )
        )
    missing = [
        name for name in PIPELINE if not (checkout / "tools" / name).is_file()
    ]
    if missing:
        problems.append(
            _problem(
                "integrity-forensics-incomplete",
                checkout,
                "checkout 缺少上游工具: " + ", ".join(missing),
            )
        )
    return problems, advisories


def run_upstream_eval(
    checkout: Path, *, timeout: float = 900.0
) -> tuple[bool, str]:
    """Run upstream's own calibration gate (their `eval/run_eval.py`)."""
    script = Path(checkout) / "eval" / "run_eval.py"
    if not script.is_file():
        return False, "上游没有 eval/run_eval.py"
    try:
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(checkout),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    tail = (completed.stdout or completed.stderr or "").strip()[-400:]
    return completed.returncode == 0, tail


# --------------------------------------------------------------------------
# The deterministic sweep.
# --------------------------------------------------------------------------


def collect_latex(paper_root: Path) -> list[Path]:
    manuscript = Path(paper_root) / "manuscript"
    if not manuscript.is_dir():
        return []
    return sorted(manuscript.rglob("*.tex"))


def _run_tool(checkout: Path, script: str, argv: list[str], *, timeout: float) -> str:
    command = [sys.executable, str(Path(checkout) / "tools" / script), *argv]
    completed = subprocess.run(
        command,
        cwd=str(checkout),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"{script} 失败 (exit {completed.returncode}): "
            f"{(completed.stderr or completed.stdout or '').strip()[-300:]}"
        )
    return completed.stdout or ""


def run_sweep(
    paper_root: Path,
    checkout: Path,
    *,
    paper_id: str,
    observability: int = 1,
    timeout: float = 900.0,
) -> dict:
    """Drive upstream's stdlib-only deterministic chain and return its report."""
    # Upstream tools run with cwd=checkout, so every path we hand them must be
    # absolute or it resolves against the wrong tree.
    paper_root = Path(paper_root).resolve()
    checkout = Path(checkout).resolve()
    latex = collect_latex(paper_root)
    if not latex:
        raise ValueError(f"找不到 manuscript/*.tex: {paper_root / 'manuscript'}")
    out_dir = paper_root / WORKFILES
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "claims.json"
    numeric = out_dir / "numeric.findings.json"
    stats = out_dir / "stat.findings.json"
    report_path = out_dir / "report.json"
    latex_args = [str(path) for path in latex]
    _run_tool(
        checkout,
        "build_claim_ledger.py",
        [
            "--paper-id",
            paper_id,
            "--latex",
            *latex_args,
            "--observability-level",
            str(observability),
            "--out",
            str(ledger),
        ],
        timeout=timeout,
    )
    _run_tool(
        checkout,
        "check_numeric_consistency.py",
        ["--ledger", str(ledger), "--out", str(numeric)],
        timeout=timeout,
    )
    _run_tool(
        checkout,
        "check_stat_consistency.py",
        ["--ledger", str(ledger), "--out", str(stats)],
        timeout=timeout,
    )
    findings = [str(path) for path in (numeric, stats) if path.is_file()]
    if not findings:
        raise ValueError("上游确定性检查没有产出 findings 文件")
    _run_tool(
        checkout,
        "adjudicate_findings.py",
        [
            "--findings",
            *findings,
            "--ledger",
            str(ledger),
            "--paper-id",
            paper_id,
            "--observability-level",
            str(observability),
            "--out",
            str(report_path),
        ],
        timeout=timeout,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("上游 report.json 不是 JSON 对象")
    return payload


# --------------------------------------------------------------------------
# Normalisation + append-only obligations.
# --------------------------------------------------------------------------


def input_hashes(paper_root: Path) -> dict[str, str]:
    """sha256 of every manuscript source the sweep read.

    A sweep only speaks for the text it actually read: if the manuscript moves
    afterwards the report is stale and must not keep passing the gate.
    """
    hashes: dict[str, str] = {}
    root = Path(paper_root).resolve()
    for path in collect_latex(root):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        hashes[path.relative_to(root).as_posix()] = (
            "sha256:" + hashlib.sha256(data).hexdigest()
        )
    return hashes


def normalise_report(
    report: dict,
    *,
    checkout: Path,
    pin: str,
    sources: dict[str, str] | None = None,
) -> dict:
    """Our view of an upstream report; upstream's words are preserved."""
    findings = report.get("findings") or []
    kept: list[dict] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        kept.append(
            {
                "id": finding.get("id") or finding.get("pattern_id"),
                "pattern_id": finding.get("pattern_id"),
                "family": finding.get("family"),
                "severity": str(finding.get("severity", "")).casefold(),
                "span": finding.get("span"),
                "summary": finding.get("summary") or finding.get("detail"),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "upstream": {
            "repo": PIN_REPO,
            "commit": pin,
            "checkout": str(checkout),
            "report_version": report.get("report_version"),
            "taxonomy_version": report.get("taxonomy_version"),
            "adjudicator": report.get("adjudicator"),
        },
        "paper_id": report.get("paper_id"),
        "observability_level": report.get("observability_level"),
        "verdict": report.get("overall_verdict"),
        "counts": report.get("counts"),
        "human_review_required": report.get("human_review_required"),
        "findings": kept,
        "input_hashes": sources or {},
        "report_sha256": _sha256(
            json.dumps(report, ensure_ascii=False, sort_keys=True)
        ),
    }


def _fingerprint(finding: dict) -> str:
    """Stable identity for an obligation across re-runs."""
    basis = "|".join(
        str(finding.get(key) or "")
        for key in ("pattern_id", "family", "summary")
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def load_obligations(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    entries: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def obligation_state(entries: list[dict]) -> dict[str, dict]:
    """Fold the append-only log into current state per fingerprint."""
    state: dict[str, dict] = {}
    for entry in entries:
        fingerprint = entry.get("fingerprint")
        if not fingerprint:
            continue
        kind = entry.get("kind")
        if kind == "open":
            state.setdefault(fingerprint, {**entry, "status": "open"})
        elif kind == "resolve":
            if fingerprint in state:
                state[fingerprint] = {
                    **state[fingerprint],
                    "status": "resolved",
                    "resolution": entry.get("evidence"),
                    "resolved_by": entry.get("by"),
                    "resolved_at": entry.get("at"),
                }
        elif kind == "waive":
            if fingerprint in state:
                state[fingerprint] = {
                    **state[fingerprint],
                    "status": "waived",
                    "waiver": entry.get("reason"),
                    "waived_by": entry.get("by"),
                    "waived_at": entry.get("at"),
                }
        elif kind == "unresolved-disappearance":
            if fingerprint in state and state[fingerprint]["status"] == "open":
                state[fingerprint]["status"] = "unresolved-disappearance"
    return state


def update_obligations(
    paper_root: Path,
    report: dict,
) -> tuple[list[dict], list[dict]]:
    """Append new obligations; never auto-close one that stopped appearing."""
    paper_root = Path(paper_root)
    path = paper_root / OBLIGATIONS_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = load_obligations(path)
    state = obligation_state(entries)
    now = _now_iso()
    current = {
        _fingerprint(finding): finding for finding in report.get("findings", [])
    }
    appended: list[dict] = []
    if not state and not current:
        return [], []
    for fingerprint, finding in sorted(current.items()):
        if fingerprint in state:
            continue
        appended.append(
            {
                "kind": "open",
                "fingerprint": fingerprint,
                "at": now,
                "verdict": report.get("verdict"),
                "finding": finding,
                "report_sha256": report.get("report_sha256"),
            }
        )
    for fingerprint, item in sorted(state.items()):
        if item.get("status") != "open" or fingerprint in current:
            continue
        appended.append(
            {
                "kind": "unresolved-disappearance",
                "fingerprint": fingerprint,
                "at": now,
                "report_sha256": report.get("report_sha256"),
            }
        )
    if appended:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for entry in appended:
                handle.write(
                    json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
                )
    merged = obligation_state(entries + appended)
    open_items = [
        item for item in merged.values() if item["status"] != "resolved"
        and item["status"] != "waived"
    ]
    return appended, open_items


def close_obligation(
    paper_root: Path,
    fingerprint: str,
    *,
    kind: str,
    by: str,
    detail: str,
    evidence_path: Path | None = None,
) -> dict:
    """Record an explicit resolution or waiver; a waiver is not a resolution."""
    if kind not in ("resolve", "waive"):
        raise ValueError("kind 必须是 resolve 或 waive")
    if not by or not by.strip():
        raise ValueError("必须写明 by（谁做的这个判断）")
    if not detail or not detail.strip():
        raise ValueError("必须写明理由/证据说明")
    entries = load_obligations(Path(paper_root) / OBLIGATIONS_RELATIVE)
    state = obligation_state(entries)
    if fingerprint not in state:
        raise ValueError(f"没有这个 obligation: {fingerprint}")
    entry = {
        "kind": kind,
        "fingerprint": fingerprint,
        "at": _now_iso(),
        "by": by.strip(),
    }
    if kind == "resolve":
        if evidence_path is None or not Path(evidence_path).is_file():
            raise ValueError("resolve 必须给一个存在的 --evidence 文件")
        data = Path(evidence_path).read_bytes()
        entry["evidence"] = detail.strip()
        entry["evidence_path"] = str(evidence_path)
        entry["evidence_sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    else:
        entry["reason"] = detail.strip()
    path = Path(paper_root) / OBLIGATIONS_RELATIVE
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


# --------------------------------------------------------------------------
# The gate.
# --------------------------------------------------------------------------


def _critical_findings(report: dict) -> list[dict]:
    return [
        finding
        for finding in report.get("findings", [])
        if finding.get("severity") == CRITICAL
    ]


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Gate over an existing sweep: verdict, criticals, open obligations."""
    paper_root = Path(paper_root)
    report_path = paper_root / REPORT_RELATIVE
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not report_path.is_file():
        return [], [
            _problem(
                "integrity-forensics-not-run",
                report_path,
                "尚未跑过 integrity forensics（data/integrity-forensics.json 不存在）",
            )
        ]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            _problem("integrity-forensics-invalid", report_path, f"无法解析: {exc}")
        ], advisories
    verdict = report.get("verdict")
    if verdict not in VERDICTS:
        problems.append(
            _problem(
                "integrity-forensics-invalid",
                report_path,
                f"verdict 非法: {verdict!r}",
            )
        )
    elif verdict in BLOCKING_VERDICTS:
        problems.append(
            _problem(
                "integrity-forensics-blocking",
                report_path,
                f"上游判定 {verdict}；"
                + (
                    "取证扫描没有跑完，不能当作通过"
                    if verdict == VERDICT_UNAVAILABLE
                    else "存在 span-anchored 的 critical 不一致，必须由人处置"
                ),
            )
        )
    elif verdict == VERDICT_SOFT:
        advisories.append(
            _problem(
                "integrity-forensics-soft",
                report_path,
                "上游判定 SOFT_FLAGS：有中低置信差异，需要人工追问",
            )
        )
    criticals = _critical_findings(report)
    recorded = report.get("input_hashes") or {}
    current = input_hashes(paper_root)
    changed = sorted(
        path
        for path in set(recorded) | set(current)
        if recorded.get(path) != current.get(path)
    )
    if recorded and changed:
        problems.append(
            _problem(
                "integrity-forensics-stale",
                report_path,
                "扫描之后稿件变了，报告已失效（"
                + ", ".join(changed[:4])
                + ("…" if len(changed) > 4 else "")
                + "）：必须重跑",
            )
        )
    if criticals:
        advisories.append(
            _problem(
                "integrity-forensics-criticals",
                report_path,
                f"{len(criticals)} 条 critical finding 已进入 obligations",
            )
        )
    entries = load_obligations(paper_root / OBLIGATIONS_RELATIVE)
    state = obligation_state(entries)
    open_items = [
        item
        for item in state.values()
        if item.get("status") not in ("resolved", "waived")
    ]
    for item in sorted(open_items, key=lambda entry: entry["fingerprint"]):
        finding = item.get("finding") or {}
        severity = finding.get("severity", "unknown")
        message = (
            f"obligation {item['fingerprint']} 未关闭"
            f"（{finding.get('pattern_id') or '?'} / {severity}"
            f" / {item.get('status')}）"
        )
        if item.get("status") == "unresolved-disappearance":
            message += "：新报告不再出现该 finding，但从未被 resolve/waive"
        if SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK[CRITICAL]:
            problems.append(
                _problem("integrity-forensics-obligation", report_path, message)
            )
        else:
            advisories.append(
                _problem("integrity-forensics-obligation", report_path, message)
            )
    return problems, advisories


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "ARIS /integrity-forensics 指向的上游仓库的 pinned launcher："
            "按固定 commit 校验 checkout，驱动上游确定性链，"
            "把 verdict 映射成我们的 gate，并维护 append-only obligations"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pin = sub.add_parser("pin", help="打印 pin 与 checkout 状态")
    pin.add_argument("--checkout", default=None)

    verify = sub.add_parser("verify", help="校验 checkout 是否正好在 pin 上")
    verify.add_argument("--checkout", default=None)
    verify.add_argument(
        "--run-eval",
        action="store_true",
        help="额外跑上游自己的 eval/run_eval.py 校准门",
    )

    run = sub.add_parser("run", help="跑一次确定性取证扫描")
    run.add_argument("--paper-root", required=True)
    run.add_argument("--checkout", default=None)
    run.add_argument("--paper-id", default=None)
    run.add_argument("--observability-level", type=int, default=1, choices=[0, 1, 2, 3])
    run.add_argument("--timeout", type=float, default=900)
    run.add_argument("--out", default=None, help="归一化报告输出路径")

    check_parser = sub.add_parser("check", help="按已有报告做 gate 判定")
    check_parser.add_argument("--paper-root", default=".")

    obligations = sub.add_parser("obligations", help="列出 obligations 当前状态")
    obligations.add_argument("--paper-root", default=".")
    obligations.add_argument("--json", default=None)

    resolve = sub.add_parser("resolve", help="用带哈希的证据关闭一条 obligation")
    resolve.add_argument("--paper-root", default=".")
    resolve.add_argument("--fingerprint", required=True)
    resolve.add_argument("--evidence", required=True)
    resolve.add_argument("--by", required=True)
    resolve.add_argument("--detail", required=True)

    waive = sub.add_parser("waive", help="人工签核豁免（不是 resolve）")
    waive.add_argument("--paper-root", default=".")
    waive.add_argument("--fingerprint", required=True)
    waive.add_argument("--by", required=True)
    waive.add_argument("--reason", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "pin":
            checkout = resolve_checkout(Path(args.checkout) if args.checkout else None)
            head = checkout_commit(checkout)
            print(
                json.dumps(
                    {
                        "repo": PIN_REPO,
                        "commit": PIN_COMMIT,
                        "checkout": str(checkout),
                        "present": checkout.is_dir(),
                        "head": head,
                        "at_pin": head == PIN_COMMIT,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "verify":
            checkout = resolve_checkout(Path(args.checkout) if args.checkout else None)
            problems, advisories = verify_checkout(checkout)
            if args.run_eval and not problems:
                ok, detail = run_upstream_eval(checkout)
                if not ok:
                    problems.append(
                        _problem(
                            "integrity-forensics-eval-failed",
                            checkout,
                            f"上游校准门失败: {detail}",
                        )
                    )
            return emit(problems, advisories)
        if args.command == "run":
            paper_root = Path(args.paper_root)
            checkout = resolve_checkout(Path(args.checkout) if args.checkout else None)
            problems, _advisories = verify_checkout(checkout)
            if problems:
                return emit(problems, [])
            paper_id = args.paper_id or paper_root.name
            upstream = run_sweep(
                paper_root,
                checkout,
                paper_id=paper_id,
                observability=args.observability_level,
                timeout=args.timeout,
            )
            report = normalise_report(
                upstream,
                checkout=checkout,
                pin=PIN_COMMIT,
                sources=input_hashes(paper_root),
            )
            out = Path(args.out) if args.out else paper_root / REPORT_RELATIVE
            save_text_atomically(
                out,
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                description="取证报告",
            )
            appended, open_items = update_obligations(paper_root, report)
            gate_problems, gate_advisories = check(paper_root)
            print(
                json.dumps(
                    {
                        "verdict": report["verdict"],
                        "findings": len(report["findings"]),
                        "counts": report["counts"],
                        "appended_obligations": len(appended),
                        "open_obligations": len(open_items),
                        "report": str(out),
                        "report_sha256": report["report_sha256"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return emit(gate_problems, gate_advisories)
        if args.command == "check":
            problems, advisories = check(Path(args.paper_root))
            return emit(problems, advisories)
        if args.command == "obligations":
            state = obligation_state(
                load_obligations(Path(args.paper_root) / OBLIGATIONS_RELATIVE)
            )
            payload = sorted(state.values(), key=lambda item: item["fingerprint"])
            if args.json:
                save_text_atomically(
                    Path(args.json),
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    description="obligations 状态",
                )
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "resolve":
            entry = close_obligation(
                Path(args.paper_root),
                args.fingerprint,
                kind="resolve",
                by=args.by,
                detail=args.detail,
                evidence_path=Path(args.evidence),
            )
            print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            return 0
        entry = close_obligation(
            Path(args.paper_root),
            args.fingerprint,
            kind="waive",
            by=args.by,
            detail=args.reason,
        )
        print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
