"""Adversarial review roles: producers that can never acquit a gate.

Two roles, both borrowed from ARIS's separation of "drive" from "acquit":

* ``claim-audit`` -- recompute the manuscript's numbers from raw data with the
  author's derivations removed from the input set. The removal is mechanical
  (``_zero_context_inputs``) and recorded, so a later reader can see exactly
  what the auditor was *not* allowed to read.
* ``kill-argument`` -- two independent model calls: one writes the strongest
  rejection memo, one writes the point-by-point defence. They are separate
  subprocesses with separate prompts, so neither can see the other.

Neither role can clear anything. Findings are written to
``reviews/adversarial-review.json`` and ``check`` reports every unresolved
finding as a problem, so a finding cannot be dismissed by not reading it. A
finding is only closed by a human writing a resolution on it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.cross_review import (
    _default_runner,
    _family_judgement,
    _input_hashes,
    _load_model_provenance,
    _relative_input,
    _resolve_codex_executable,
    _review_tier,
    _sha256_text,
)

ARTIFACT = Path("reviews") / "adversarial-review.json"
ROLES = ("claim-audit", "kill-argument")
FINDING_KINDS = ("mismatch", "concern", "unverifiable")
# Files that carry the author's own reasoning. A claim audit that reads them is
# no longer context-free, so they are dropped from its input set.
DERIVATION_MARKERS = ("proof", "derivation", "appendix-proofs")
VERSION = 1
MICRO = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zero_context_inputs(relative: list[str]) -> tuple[list[str], list[str]]:
    """Split inputs into the auditable set and the excluded derivations."""

    kept: list[str] = []
    excluded: list[str] = []
    for path in relative:
        lowered = path.casefold()
        if any(marker in lowered for marker in DERIVATION_MARKERS):
            excluded.append(path)
        else:
            kept.append(path)
    return sorted(set(kept)), sorted(set(excluded))


def build_prompt(
    role: str,
    *,
    stage: str,
    relative_paths: list[str],
    excluded: list[str],
) -> str:
    if role not in ROLES:
        raise ValueError(f"未知角色: {role!r}，应为 {' / '.join(ROLES)}")
    lines = [
        f"角色: {role}",
        f"当前 stage: {stage}",
        "",
    ]
    if role == "claim-audit":
        lines.extend(
            [
                "你是独立数值复核者。正文里出现的每一个数字，你都要从原始数据"
                "自己重算一遍。",
                "你没有被给予作者的推导、证明或解释，也不得推测它们；只依据下面"
                "列出的原始数据文件。",
                "对每个数字输出一条 finding：位置、正文原值、你重算的值、"
                "结论(mismatch|unverifiable|concern)、以及你据以重算的文件名与"
                "该文件中的原文片段。",
                "重算不出来就写 unverifiable，不要放过，也不要猜。",
            ]
        )
    else:
        lines.extend(
            [
                "你在一次独立轮次中被要求给出一个立场，只输出这个立场，"
                "不要试图平衡。",
                "立场取决于本次调用的 role 参数，见下方 '你的立场' 一节。",
            ]
        )
    lines.append("")
    lines.append("待评审文件:")
    lines.extend(f"- {path}" for path in relative_paths)
    if excluded:
        lines.extend(
            [
                "",
                "本次刻意排除（含作者推导，故不提供给你）:",
            ]
        )
        lines.extend(f"- {path}" for path in excluded)
    lines.extend(
        [
            "",
            "输出契约: 只返回 JSON 对象，字段为 "
            "findings[{kind,statement,evidence}]、summary。",
            "kind 必须是 mismatch / unverifiable / concern 之一。",
            "statement 说明你主张什么；evidence 必须是待评审文件里的原文片段"
            "或该文件的 sha256。",
            "禁止修改任何文件；你只有只读权限。",
            "你只能产出发言，不能宣布任何 gate 通过。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_stance_prompt(base: str, stance: str) -> str:
    """Wrap a kill-argument prompt with one stance and nothing from the other."""

    if stance == "reject":
        ask = (
            "你的立场: 写出这篇工作最强的拒稿备忘。给出审稿人会用来拒它的"
            "最致命理由，每条都要有可核对 evidence。"
        )
    elif stance == "defend":
        ask = (
            "你的立场: 写出逐点辩护。逐条回应可能被质疑的地方，每条都要有"
            "可核对 evidence。"
        )
    else:
        raise ValueError(f"未知立场: {stance!r}")
    return base + "\n" + ask + "\n"


def _parse_payload(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise ValueError("评审模型没有返回内容")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("评审输出不是 JSON 对象") from None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"评审输出不是 JSON 对象: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("评审输出必须是 JSON 对象")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ValueError("评审输出缺少 findings 数组")
    clean: list[dict] = []
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            raise ValueError(f"findings[{index}] 必须是对象")
        kind = item.get("kind")
        if kind not in FINDING_KINDS:
            raise ValueError(f"findings[{index}].kind 非法: {kind!r}")
        statement = item.get("statement")
        evidence = item.get("evidence")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"findings[{index}] 缺少 statement")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"findings[{index}] 缺少 evidence")
        clean.append(
            {
                "kind": kind,
                "statement": statement.strip(),
                "evidence": evidence.strip(),
                "resolved": False,
                "resolution": "",
            }
        )
    summary = payload.get("summary")
    return {
        "findings": clean,
        "summary": summary.strip() if isinstance(summary, str) else "",
    }


def _call(
    *,
    paper_root: Path,
    cwd: Path,
    prompt: str,
    model: str,
    provider: str | None,
    reasoning_effort: str | None,
    runner,
    timeout: float,
    codex_config: Path,
) -> tuple[dict, dict]:
    schema_path = paper_root / "reviews" / "adversarial-review.schema.json"
    last_message = paper_root / "reviews" / "adversarial-review-last-message.json"
    save_text_atomically(
        schema_path,
        json.dumps(_schema(), ensure_ascii=False, indent=2) + "\n",
        description="对抗评审 schema",
    )
    last_message.unlink(missing_ok=True)
    argv = [
        _resolve_codex_executable(),
        "exec",
        *(["-c", f"model_provider={provider}"] if provider else []),
        *(
            ["-c", f"model_reasoning_effort={reasoning_effort}"]
            if reasoning_effort
            else []
        ),
        "-m",
        model,
        "-s",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        str(cwd),
        "--output-schema",
        str(schema_path),
        "-o",
        str(last_message),
        "-",
    ]
    run = runner or _default_runner
    exit_code, stderr = run(argv, cwd, timeout, prompt)
    if exit_code != 0:
        raise ValueError(
            f"评审模型调用失败 (exit {exit_code}): "
            f"{str(stderr[-600:]) or 'no stderr'}"
        )
    raw = (
        last_message.read_text(encoding="utf-8")
        if last_message.is_file()
        else ""
    )
    return _parse_payload(raw), {
        "exit_code": exit_code,
        "prompt_sha256": _sha256_text(prompt),
        "stderr": str(stderr)[-2000:],
    }


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": list(FINDING_KINDS),
                        },
                        "statement": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["kind", "statement", "evidence"],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["findings", "summary"],
        "additionalProperties": False,
    }


def run_review(
    paper_root: Path,
    *,
    role: str,
    model: str,
    stage: str,
    paths: list[Path],
    provider: str | None = None,
    reasoning_effort: str | None = None,
    runner=None,
    timeout: float = 900,
    codex_config: Path | None = None,
) -> dict:
    """Run one adversarial role and write ``reviews/adversarial-review.json``."""

    paper_root = Path(paper_root).resolve()
    if role not in ROLES:
        raise ValueError(f"未知角色: {role!r}，应为 {' / '.join(ROLES)}")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("必须显式提供 --model")
    model = model.strip()
    if not paths:
        raise ValueError("评审输入不能为空：至少要有一个 --path")
    relative = [_relative_input(paper_root, Path(path))[1] for path in paths]
    kept, excluded = (
        _zero_context_inputs(relative)
        if role == "claim-audit"
        else (sorted(set(relative)), [])
    )
    if not kept:
        raise ValueError("本次输入全部被排除，claim-audit 没有可审计的文件")
    provenance = _load_model_provenance(
        codex_config or (Path.home() / ".codex" / "config.toml"),
        provider,
    )
    effective_provider = provenance["provider"]
    execution_model = provenance["execution_model"]
    family = _family_judgement(model, execution_model)
    tier = _review_tier(model, effective_provider)
    base = build_prompt(
        role,
        stage=stage,
        relative_paths=kept,
        excluded=excluded,
    )
    # The reviewer is pointed at a staging tree that holds only the permitted
    # inputs, so an excluded derivation is absent from the working tree rather
    # than merely unlisted. This reduces access; it is not a hard sandbox.
    staging = Path(tempfile.mkdtemp(prefix="ccfa-adversarial-"))
    try:
        for relative in kept:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paper_root / relative, target)
        lines: dict[str, dict] = {}
        raw: dict[str, dict] = {}
        if role == "kill-argument":
            for stance in ("reject", "defend"):
                payload, meta = _call(
                    paper_root=paper_root,
                    cwd=staging,
                    prompt=build_stance_prompt(base, stance),
                    model=model,
                    provider=provider,
                    reasoning_effort=reasoning_effort,
                    runner=runner,
                    timeout=timeout,
                    codex_config=codex_config
                    or (Path.home() / ".codex" / "config.toml"),
                )
                lines[stance] = payload
                raw[stance] = meta
            findings = [
                {**item, "stance": stance}
                for stance in ("reject", "defend")
                for item in lines[stance]["findings"]
            ]
            summary = " / ".join(
                f"{stance}: {lines[stance]['summary']}"
                for stance in ("reject", "defend")
            )
        else:
            payload, meta = _call(
                paper_root=paper_root,
                cwd=staging,
                prompt=base,
                model=model,
                provider=provider,
                reasoning_effort=reasoning_effort,
                runner=runner,
                timeout=timeout,
                codex_config=codex_config
                or (Path.home() / ".codex" / "config.toml"),
            )
            lines["audit"] = payload
            raw["audit"] = meta
            findings = list(payload["findings"])
            summary = payload["summary"]
        record = {
            "version": VERSION,
            "role": role,
            "stage": stage,
            "model": model,
            "provider": effective_provider,
            **provenance,
            "execution_model": execution_model,
            "family_judgement": family,
            "review_tier": tier,
            "generated_at": _now_iso(),
            "inputs": kept,
            "excluded_inputs": excluded,
            "input_hashes": _input_hashes(
                paper_root,
                [paper_root / path for path in kept],
            ),
            "calls": raw,
            "summary": summary,
            "findings": findings,
        }
        save_text_atomically(
            paper_root / ARTIFACT,
            json.dumps(
                record, ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n",
            description="对抗评审记录",
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return record


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Validate the artifact and report every unresolved finding."""

    paper_root = Path(paper_root).resolve()
    path = paper_root / ARTIFACT
    if not path.is_file():
        return [], [
            Problem(
                "adversarial-review-not-configured",
                str(path),
                None,
                "尚未运行对抗评审（claim-audit / kill-argument）",
            )
        ]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [
            Problem(
                "adversarial-review-invalid",
                str(path),
                None,
                f"无法读取对抗评审记录: {exc}",
            )
        ], []
    if not isinstance(record, dict):
        return [
            Problem(
                "adversarial-review-invalid",
                str(path),
                None,
                "顶层必须是对象",
            )
        ], []
    problems: list[Problem] = []
    if record.get("role") not in ROLES:
        problems.append(
            Problem(
                "adversarial-review-invalid",
                str(path),
                None,
                "role 非法",
            )
        )
    if record.get("review_tier") == "advisory-only":
        problems.append(
            Problem(
                "adversarial-review-advisory-only",
                str(path),
                None,
                "对抗评审由 advisory-only 模型出具，只能作为线索，"
                "不能据此收尾",
            )
        )
    findings = record.get("findings")
    if not isinstance(findings, list):
        return problems + [
            Problem(
                "adversarial-review-invalid",
                str(path),
                None,
                "findings 必须是数组",
            )
        ], []
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            problems.append(
                Problem(
                    "adversarial-review-invalid",
                    str(path),
                    None,
                    f"findings[{index}] 必须是对象",
                )
            )
            continue
        if item.get("resolved") is True:
            resolution = item.get("resolution")
            if not isinstance(resolution, str) or len(resolution.strip()) < MICRO:
                problems.append(
                    Problem(
                        "adversarial-review-resolution-thin",
                        str(path),
                        None,
                        f"findings[{index}] 标为已解决，但 resolution "
                        f"不足 {MICRO} 字符",
                    )
                )
            continue
        problems.append(
            Problem(
                "adversarial-review-unresolved",
                str(path),
                None,
                f"findings[{index}] 未解决: {str(item.get('statement'))[:120]}",
            )
        )
    return problems, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对抗评审：零上下文数值复核与双线 kill-argument（只产出）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--paper-root", required=True)
    run.add_argument("--role", required=True, choices=ROLES)
    run.add_argument("--stage", required=True)
    run.add_argument("--path", action="append", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--provider", default=None)
    run.add_argument("--reasoning-effort", default=None)
    run.add_argument("--timeout", type=float, default=900)
    run.add_argument("--codex-config", default=None)
    check = sub.add_parser("check")
    check.add_argument("--paper-root", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check(Path(args.paper_root))
            return emit(problems, advisories)
        record = run_review(
            Path(args.paper_root),
            role=args.role,
            model=args.model,
            stage=args.stage,
            paths=[Path(item) for item in args.path],
            provider=args.provider,
            reasoning_effort=args.reasoning_effort,
            timeout=args.timeout,
            codex_config=(
                Path(args.codex_config) if args.codex_config else None
            ),
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    print(
        json.dumps(
            {
                "role": record["role"],
                "model": record["model"],
                "family_judgement": record["family_judgement"],
                "review_tier": record["review_tier"],
                "findings": len(record["findings"]),
                "excluded_inputs": len(record["excluded_inputs"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
