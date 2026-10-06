"""The single privileged landing point for the workflow's own guidance corpus.

``meta_optimize`` is the read-only producer: it groups friction and gate
failures into candidate changes and never edits anything. This module is the
other half of that pair, and the only tool allowed to land such a change, and
only after a model jury has seen the *staged diff*:

* ``stage`` materialises the change under ``ccfa-workfiles/meta-apply/<id>/``
  with before/after hashes and a unified diff. The working tree is untouched.
* ``review`` runs one independent model per ``--model`` over that diff and
  records each verdict, its family and its capability tier.
* ``apply`` refuses unless the staged bytes, the live target and the reviewed
  diff all still hash to what was recorded, at least two gate-capable reviewers
  passed, they span at least two families, and at least one of them is outside
  the executor's family. It writes a byte-identical backup before landing.
* ``check`` verifies the append-only ledger still matches its backups.

The default allowlist is the guidance corpus (``docs/``, ``checklists/``,
``automation/``, ``skills/``, ``library/``). Touching ``tools/``, ``scripts/``
or ``app/`` additionally requires ``--allow-code``, and that escalation is
recorded in the ledger.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.cross_review import (
    HARNESS_MCP_OFF,
    _default_runner,
    _family_judgement,
    _load_model_provenance,
    _model_family,
    _resolve_codex_executable,
    _review_tier,
    _sha256_text,
)

WORKFILES = Path("ccfa-workfiles") / "meta-apply"
LEDGER_NAME = "ledger.jsonl"
PLAN_NAME = "plan.json"
STAGED_DIR = "staged"
BACKUP_DIR = "backup"
VERSION = 1

GUIDANCE_PREFIXES = (
    "docs/",
    "checklists/",
    "automation/",
    "skills/",
    "library/",
)
GUIDANCE_FILES = ("README.md",)
CODE_PREFIXES = (
    "tools/",
    "scripts/",
    "app/",
)
# Even with --allow-code these stay off limits: they hold other repositories,
# the applier's own audit trail, or generated state that is not source.
DENIED_PREFIXES = (
    "papers/",
    "ccfa-workfiles/",
    "tools/.venv/",
    "app/.venv/",
    "build/",
    "dist/",
    ".git/",
    ".github/",
)
_PROPOSAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MIN_PASSING_REVIEWERS = 2
MIN_DISTINCT_FAMILIES = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_sha256(path: Path) -> str:
    """Raw-byte digest; CRLF is significant because apply must be exact."""
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_bytes_atomically(path: Path, data: bytes, description: str) -> None:
    """Write bytes without letting the platform rewrite line endings."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise ValueError(f"无法写入 {description} {path}: {exc}") from exc


def _validate_proposal(proposal: str) -> str:
    if not isinstance(proposal, str) or not _PROPOSAL_RE.match(proposal):
        raise ValueError(
            "proposal 必须是 1..64 位的字母/数字/._-，且以字母或数字开头"
        )
    return proposal


def _validate_target(target: str, *, allow_code: bool) -> str:
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target 必须是非空仓库相对路径")
    normalized = target.strip().replace("\\", "/")
    path = Path(normalized)
    if (
        path.is_absolute()
        or path.drive
        or path.root
        or ".." in path.parts
        or normalized.startswith("/")
    ):
        raise ValueError(f"target 必须是仓库内相对路径: {target!r}")
    if any(
        normalized == prefix.rstrip("/")
        or normalized.startswith(prefix)
        for prefix in DENIED_PREFIXES
    ):
        raise ValueError(f"target 落在禁写区: {normalized}")
    if normalized in GUIDANCE_FILES or normalized.startswith(GUIDANCE_PREFIXES):
        return normalized
    if normalized.startswith(CODE_PREFIXES):
        if not allow_code:
            raise ValueError(
                f"target {normalized} 属于代码区，需显式 --allow-code "
                "（该升级会写进 ledger）"
            )
        return normalized
    allowed = " / ".join(
        [*GUIDANCE_PREFIXES, *GUIDANCE_FILES, *CODE_PREFIXES]
    )
    raise ValueError(f"target 不在允许落地区域（{allowed}）: {normalized}")


def _proposal_dir(root: Path, proposal: str) -> Path:
    return Path(root) / WORKFILES / proposal


def _plan_path(root: Path, proposal: str) -> Path:
    return _proposal_dir(root, proposal) / PLAN_NAME


def _ledger_path(root: Path) -> Path:
    return Path(root) / WORKFILES / LEDGER_NAME


def _read_target(root: Path, target: str) -> tuple[Path, bytes]:
    path = Path(root) / target
    if path.is_symlink():
        raise ValueError(f"target 是符号链接，拒绝改写: {target}")
    if not path.is_file():
        raise ValueError(f"target 不存在或不是普通文件: {target}")
    try:
        return path, path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取 target {target}: {exc}") from exc


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{what} 不是 UTF-8 文本，不适合本工具: {exc}") from exc


def _unified_diff(target: str, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{target}",
        tofile=f"b/{target}",
        lineterm="",
    )
    return "\n".join(diff) + "\n"


def load_plan(root: Path, proposal: str) -> dict:
    path = _plan_path(root, proposal)
    if not path.is_file():
        raise ValueError(f"没有 staged 计划: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"计划不可读 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"计划顶层必须是对象: {path}")
    if payload.get("version") != VERSION:
        raise ValueError(f"计划 version 必须是 {VERSION}: {payload.get('version')!r}")
    for key in ("target", "before_sha256", "after_sha256", "diff"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ValueError(f"计划缺少 {key}: {path}")
    return payload


def stage(
    root: Path,
    *,
    proposal: str,
    target: str,
    content: str,
    allow_code: bool = False,
) -> dict:
    """Write the proposed change to a staging area; touch nothing else."""
    root = Path(root).resolve()
    proposal = _validate_proposal(proposal)
    target = _validate_target(target, allow_code=allow_code)
    plan_path = _plan_path(root, proposal)
    if plan_path.exists():
        raise ValueError(
            f"proposal {proposal!r} 已有计划 {plan_path}；"
            "一次落地用一个 proposal id，不覆盖历史"
        )
    path, before = _read_target(root, target)
    if not isinstance(content, bytes):
        raise ValueError("content 必须是字节")
    if content == before:
        raise ValueError("staged 内容与当前文件相同，没有可落地的改动")
    staged_path = _proposal_dir(root, proposal) / STAGED_DIR / target
    _write_bytes_atomically(staged_path, content, "staged 变更")
    plan = {
        "version": VERSION,
        "proposal": proposal,
        "target": target,
        "allow_code": bool(allow_code),
        "before_sha256": _file_sha256(path),
        "after_sha256": _file_sha256(staged_path),
        "diff": _unified_diff(
            target,
            _decode(before, "target"),
            _decode(content, "source"),
        ),
        "staged_at": _now_iso(),
        "reviews": [],
        "reviewed_diff_sha256": None,
    }
    save_text_atomically(
        plan_path,
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="meta-apply 计划",
    )
    return plan


def _review_prompt(plan: dict) -> str:
    escalated = "是（--allow-code）" if plan.get("allow_code") else "否"
    return "\n".join(
        [
            "你是工作流自改动的独立评审。下面是一条已经 staged、尚未落地的 diff。",
            f"proposal: {plan['proposal']}",
            f"target: {plan['target']}",
            f"是否已显式升级到代码区: {escalated}",
            "",
            "请只回答一个问题：这条改动是否可以按原样落地。",
            "关心点：是否削弱任何 gate 或证据要求、是否引入未验证的声明、",
            "是否越出 target 声明的范围、是否与 diff 描述不符。",
            "不要重写 diff，不要给出替代实现。",
            "",
            "diff 开始",
            plan["diff"].rstrip("\n"),
            "diff 结束",
            "",
            "输出契约: 只返回 JSON 对象，字段为 verdict(pass|block)、",
            "findings[{kind,statement,evidence}]。",
            "kind 必须是 risk / unclear / scope 之一。",
            "verdict=block 时必须至少给出一条有 evidence 的 finding；",
            "evidence 必须是上面 diff 里的原文片段。",
            "你只能产出发言，不能落地任何文件。",
        ]
    ) + "\n"


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["pass", "block"]},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["risk", "unclear", "scope"],
                        },
                        "statement": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["kind", "statement", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["verdict", "findings"],
        "additionalProperties": False,
    }


def _parse_payload(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise ValueError("评审模型没有返回内容")
    payload = _extract_object(text)
    if payload is None:
        raise ValueError(
            "评审输出不符合契约（不是含 verdict 的 JSON 对象）；"
            f"原始输出前 200 字符: {text[:200]!r}"
        )
    if not isinstance(payload, dict):
        raise ValueError("评审输出必须是 JSON 对象")
    verdict = payload.get("verdict")
    if verdict not in {"pass", "block"}:
        raise ValueError(
            f"评审输出不符合契约（verdict 非法: {verdict!r}）；"
            f"原始输出前 200 字符: {text[:200]!r}"
        )
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ValueError("评审输出缺少 findings 数组")
    clean: list[dict] = []
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            raise ValueError(f"findings[{index}] 必须是对象")
        kind = item.get("kind")
        if kind not in {"risk", "unclear", "scope"}:
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
            }
        )
    if verdict == "block" and not clean:
        raise ValueError("verdict=block 但没有任何 finding")
    return {"verdict": verdict, "findings": clean}


def _extract_object(text: str) -> dict | None:
    """Return the review object, or None when the model broke the contract.

    A model that answers ``verdict=block`` plus a bare findings array must not
    be half-parsed into the nested finding, which is what would let a broken
    contract look like a real verdict.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict) or "verdict" not in payload:
        return None
    return payload


def _call(
    *,
    root: Path,
    model: str,
    provider: str | None,
    reasoning_effort: str | None,
    runner,
    timeout: float,
    codex_config: Path,
    prompt: str,
) -> tuple[dict, dict]:
    reviews_dir = Path(root) / WORKFILES
    schema_path = reviews_dir / "meta-apply-review.schema.json"
    last_message = reviews_dir / "meta-apply-last-message.json"
    save_text_atomically(
        schema_path,
        json.dumps(_schema(), ensure_ascii=False, indent=2) + "\n",
        description="meta-apply 评审 schema",
    )
    last_message.unlink(missing_ok=True)
    argv = [
        _resolve_codex_executable(),
        "exec",
        *HARNESS_MCP_OFF,
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
        str(root),
        "--output-schema",
        str(schema_path),
        "-o",
        str(last_message),
        "-",
    ]
    run = runner or _default_runner
    exit_code, stderr = run(argv, root, timeout, prompt)
    if exit_code != 0:
        raise ValueError(
            f"评审模型调用失败 (exit {exit_code}): "
            f"{str(stderr[-600:]) or 'no stderr'}"
        )
    raw = last_message.read_text(encoding="utf-8") if last_message.is_file() else ""
    return _parse_payload(raw), {
        "exit_code": exit_code,
        "prompt_sha256": _sha256_text(prompt),
    }


def review(
    root: Path,
    *,
    proposal: str,
    models: list[str],
    provider: str | None = None,
    model_providers: dict[str, str] | None = None,
    reasoning_effort: str | None = None,
    runner=None,
    timeout: float = 900,
    codex_config: Path | None = None,
) -> dict:
    """Run one model per entry in *models* over the staged diff."""
    root = Path(root).resolve()
    proposal = _validate_proposal(proposal)
    if not models:
        raise ValueError("至少需要一个 --model")
    plan = load_plan(root, proposal)
    staged_path = _proposal_dir(root, proposal) / STAGED_DIR / plan["target"]
    if not staged_path.is_file():
        raise ValueError(f"staged 文件缺失: {staged_path}")
    if _file_sha256(staged_path) != plan["after_sha256"]:
        raise ValueError("staged 文件已变化，重新 stage 后再评审")
    config_path = codex_config or (Path.home() / ".codex" / "config.toml")
    execution_model = _load_model_provenance(config_path, provider)[
        "execution_model"
    ]
    overrides = model_providers or {}
    prompt = _review_prompt(plan)
    reviews: list[dict] = []
    for model in models:
        # A cross-provider jury needs a provider per model, because the free
        # reviewers live behind different aggregators.
        payload, meta = _call(
            root=root,
            model=model,
            provider=overrides.get(model) or provider,
            reasoning_effort=reasoning_effort,
            runner=runner,
            timeout=timeout,
            codex_config=config_path,
            prompt=prompt,
        )
        resolved = overrides.get(model) or provider
        provenance = _load_model_provenance(config_path, resolved)
        reviews.append(
            {
                "model": model,
                "provider": provenance["provider"],
                "provider_endpoint_sha256": provenance[
                    "provider_endpoint_sha256"
                ],
                "family": _model_family(model),
                "family_judgement": _family_judgement(model, execution_model),
                "review_tier": _review_tier(model, provenance["provider"]),
                "verdict": payload["verdict"],
                "findings": payload["findings"],
                **meta,
            }
        )
    plan["reviews"] = reviews
    plan["reviewed_diff_sha256"] = _sha256_text(plan["diff"])
    plan["reviewed_at"] = _now_iso()
    save_text_atomically(
        _plan_path(root, proposal),
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="meta-apply 计划",
    )
    return plan


def _quorum(plan: dict) -> tuple[list[dict], list[str]]:
    """Return the passing reviewers and the reasons apply must refuse."""
    reviews = plan.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        return [], ["还没有任何评审记录"]
    blockers = [
        review
        for review in reviews
        if review.get("review_tier") == "gate-capable"
        and review.get("verdict") != "pass"
    ]
    passers = [
        review
        for review in reviews
        if review.get("review_tier") == "gate-capable"
        and review.get("verdict") == "pass"
    ]
    reasons: list[str] = []
    if blockers:
        names = ", ".join(str(review.get("model")) for review in blockers)
        reasons.append(f"gate-capable 评审给出 block: {names}")
    if len(passers) < MIN_PASSING_REVIEWERS:
        reasons.append(
            f"gate-capable 通过的评审只有 {len(passers)} 个，"
            f"至少需要 {MIN_PASSING_REVIEWERS} 个"
        )
    families = {review.get("family") for review in passers}
    families.discard("unknown")
    if len(families) < MIN_DISTINCT_FAMILIES:
        reasons.append(
            f"通过的评审只覆盖 {len(families)} 个模型族，"
            f"至少需要 {MIN_DISTINCT_FAMILIES} 个"
        )
    if not any(
        review.get("family_judgement") == "cross-family" for review in passers
    ):
        reasons.append("通过的评审里没有相对执行模型的跨族评审")
    return passers, reasons


def apply_change(root: Path, *, proposal: str) -> dict:
    """Land a staged change, or refuse with every reason it cannot."""
    root = Path(root).resolve()
    proposal = _validate_proposal(proposal)
    plan = load_plan(root, proposal)
    target = _validate_target(
        plan["target"],
        allow_code=bool(plan.get("allow_code")),
    )
    staged_path = _proposal_dir(root, proposal) / STAGED_DIR / target
    path = root / target
    reasons: list[str] = []
    if not staged_path.is_file():
        reasons.append(f"staged 文件缺失: {staged_path}")
    elif _file_sha256(staged_path) != plan["after_sha256"]:
        reasons.append("staged 文件哈希与计划不一致")
    if path.is_symlink() or not path.is_file():
        reasons.append(f"target 已不是普通文件: {target}")
    elif _file_sha256(path) != plan["before_sha256"]:
        reasons.append("target 在 stage 之后被改动，哈希不再匹配")
    reviewed_diff = plan.get("reviewed_diff_sha256")
    if reviewed_diff is not None and reviewed_diff != _sha256_text(plan["diff"]):
        reasons.append("评审覆盖的 diff 与当前计划不一致")
    passers, quorum_reasons = _quorum(plan)
    reasons.extend(quorum_reasons)
    if reasons:
        raise ValueError("拒绝落地: " + "；".join(reasons))

    backup_path = _proposal_dir(root, proposal) / BACKUP_DIR / target
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, backup_path)
    if _file_sha256(backup_path) != plan["before_sha256"]:
        raise ValueError("备份哈希与 stage 时的目标不一致，拒绝落地")
    _write_bytes_atomically(path, staged_path.read_bytes(), "meta-apply 落地")
    applied = {
        "version": VERSION,
        "proposal": proposal,
        "target": target,
        "allow_code": bool(plan.get("allow_code")),
        "before_sha256": plan["before_sha256"],
        "after_sha256": plan["after_sha256"],
        "applied_sha256": _file_sha256(path),
        "backup": backup_path.relative_to(root).as_posix(),
        "reviewers": [
            {
                "model": review.get("model"),
                "family": review.get("family"),
                "family_judgement": review.get("family_judgement"),
                "review_tier": review.get("review_tier"),
                "verdict": review.get("verdict"),
            }
            for review in plan["reviews"]
        ],
        "passing_reviewers": [review.get("model") for review in passers],
        "applied_at": _now_iso(),
    }
    ledger = _ledger_path(root)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(applied, ensure_ascii=False, sort_keys=True) + "\n")
    return applied


def check(root: Path) -> tuple[list[Problem], list[Problem]]:
    """Verify the ledger is readable and still matches its backups."""
    root = Path(root).resolve()
    ledger = _ledger_path(root)
    if not ledger.is_file():
        return [], [
            Problem(
                "meta-apply-no-ledger",
                str(ledger),
                None,
                "还没有任何 meta-apply 落地记录",
            )
        ]
    problems: list[Problem] = []
    advisories: list[Problem] = []
    for line_number, raw in enumerate(
        ledger.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(
                Problem(
                    "meta-apply-ledger-malformed",
                    str(ledger),
                    line_number,
                    f"ledger 行不可解析: {exc}",
                )
            )
            continue
        if not isinstance(record, dict):
            problems.append(
                Problem(
                    "meta-apply-ledger-malformed",
                    str(ledger),
                    line_number,
                    "ledger 行必须是对象",
                )
            )
            continue
        backup = record.get("backup")
        expected = record.get("before_sha256")
        if not isinstance(backup, str) or not isinstance(expected, str):
            problems.append(
                Problem(
                    "meta-apply-ledger-malformed",
                    str(ledger),
                    line_number,
                    "ledger 行缺少 backup / before_sha256",
                )
            )
            continue
        backup_path = root / backup
        if not backup_path.is_file():
            problems.append(
                Problem(
                    "meta-apply-backup-missing",
                    str(ledger),
                    line_number,
                    f"备份不存在: {backup}",
                )
            )
            continue
        if _file_sha256(backup_path) != expected:
            problems.append(
                Problem(
                    "meta-apply-backup-drift",
                    str(ledger),
                    line_number,
                    f"备份哈希与记录不一致: {backup}",
                )
            )
        if record.get("applied_sha256") != record.get("after_sha256"):
            advisories.append(
                Problem(
                    "meta-apply-applied-drift",
                    str(ledger),
                    line_number,
                    "落地后的哈希与计划不同——之后可能又被人改过",
                )
            )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "工作流自改动唯一落地口：stage → 跨族 jury 评审 staged diff → apply。"
            "默认只允许改文档/指导语料；改代码需 --allow-code 并记入 ledger。"
        )
    )
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    stage_parser = sub.add_parser("stage", help="把候选改动写入 staging 区")
    stage_parser.add_argument("--proposal", required=True)
    stage_parser.add_argument("--target", required=True)
    stage_parser.add_argument("--source", required=True, help="新内容的文件")
    stage_parser.add_argument("--allow-code", action="store_true")

    review_parser = sub.add_parser("review", help="对 staged diff 跑模型 jury")
    review_parser.add_argument("--proposal", required=True)
    review_parser.add_argument("--model", action="append", required=True)
    review_parser.add_argument("--provider", default=None)
    review_parser.add_argument(
        "--model-provider",
        action="append",
        default=[],
        metavar="MODEL=PROVIDER",
        help="为某个模型单独指定 provider；可重复",
    )
    review_parser.add_argument("--reasoning-effort", default=None)
    review_parser.add_argument("--timeout", type=float, default=900)
    review_parser.add_argument("--codex-config", default=None)

    apply_parser = sub.add_parser("apply", help="通过全部检查后落地")
    apply_parser.add_argument("--proposal", required=True)

    sub.add_parser("check", help="校验 ledger 与其备份是否仍然一致")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    root = Path(args.root)
    try:
        if args.command == "stage":
            source = Path(args.source)
            if not source.is_file():
                return tool_error(f"source 不存在: {source}")
            plan = stage(
                root,
                proposal=args.proposal,
                target=args.target,
                content=source.read_bytes(),
                allow_code=args.allow_code,
            )
            print(
                json.dumps(
                    {
                        "proposal": plan["proposal"],
                        "target": plan["target"],
                        "allow_code": plan["allow_code"],
                        "after_sha256": plan["after_sha256"],
                        "diff_lines": plan["diff"].count("\n"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "review":
            overrides: dict[str, str] = {}
            for item in args.model_provider:
                model_name, separator, provider_name = item.partition("=")
                if not separator or not model_name or not provider_name:
                    return tool_error(
                        f"--model-provider 必须写成 MODEL=PROVIDER: {item!r}"
                    )
                overrides[model_name] = provider_name
            plan = review(
                root,
                proposal=args.proposal,
                models=args.model,
                provider=args.provider,
                model_providers=overrides,
                reasoning_effort=args.reasoning_effort,
                timeout=args.timeout,
                codex_config=(
                    Path(args.codex_config) if args.codex_config else None
                ),
            )
            print(
                json.dumps(
                    {
                        "proposal": plan["proposal"],
                        "reviewers": len(plan["reviews"]),
                        "verdicts": [
                            {
                                "model": item["model"],
                                "tier": item["review_tier"],
                                "family": item["family"],
                                "verdict": item["verdict"],
                            }
                            for item in plan["reviews"]
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "apply":
            applied = apply_change(root, proposal=args.proposal)
            print(json.dumps(applied, ensure_ascii=False, sort_keys=True))
            return 0
        problems, advisories = check(root)
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
