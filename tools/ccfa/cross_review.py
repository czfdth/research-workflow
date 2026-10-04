"""Run and audit an independent-model gate review."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.stages import gate_for

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "blocking"]},
        "blocking": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["title", "evidence"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["verdict", "blocking", "summary"],
    "additionalProperties": False,
}

DEFAULT_MODEL = "deepseek-v4-pro"
_SAME_FAMILY_MODELS = {"deepseek-v4-pro", "deepseek-v4-flash"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STDERR_LIMIT = 4000
_RAW_LAST_MESSAGE_LIMIT = 10000
_STDERR_TRUNCATION_MARKER = "...[truncated]"
_BLOCKING_QUOTE_MIN_LENGTH = 20
_TEXT_SUFFIXES = frozenset(
    {
        ".bib",
        ".cfg",
        ".csv",
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".md",
        ".ps1",
        ".py",
        ".rst",
        ".schema",
        ".sh",
        ".tex",
        ".toml",
        ".ts",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _family_judgement(model: str) -> str:
    if model in _SAME_FAMILY_MODELS:
        return "same-family"
    if model.startswith(("gpt-", "claude-", "glm-")):
        return "cross-family"
    return "unknown"


def _bounded_text(value: object, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + _STDERR_TRUNCATION_MARKER


def _bounded_stderr(stderr: object) -> str:
    return _bounded_text(stderr, _STDERR_LIMIT)


def _load_mode(paper_root: Path) -> str:
    path = paper_root / "ccfa.yaml"
    try:
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    venue = state.get("target_venue")
    if not isinstance(venue, dict):
        raise ValueError(f"{path} 的 target_venue 必须是映射")
    mode = venue.get("mode", "conference")
    if mode not in ("conference", "journal"):
        raise ValueError(f"未知 mode: {mode!r}")
    return mode


def _relative_input(paper_root: Path, path: Path) -> tuple[Path, str]:
    root = paper_root.resolve()
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"评审输入逃出 paper_root: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"评审输入不存在: {relative}")
    return resolved, relative


def _sha256(path: Path) -> str:
    data = path.read_bytes()
    # Only known text suffixes are normalized, so an arbitrary binary file
    # without NUL bytes keeps its exact digest.
    if path.suffix.casefold() in _TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}"


def _input_hashes(paper_root: Path, paths: list[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        resolved, relative = _relative_input(paper_root, Path(path))
        hashes[relative] = _sha256(resolved)
    return hashes


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _input_corpus(paper_root: Path, hashes: object) -> str:
    """Return the whitespace-normalized text of the recorded review inputs."""
    if not isinstance(hashes, dict):
        return ""
    texts: list[str] = []
    for relative in sorted(key for key in hashes if isinstance(key, str)):
        try:
            resolved, _relative = _relative_input(paper_root, Path(relative))
            raw = resolved.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        texts.append(_normalize_whitespace(raw))
    return "\n\n".join(texts)


def _longest_quote_length(evidence: str, corpus: str) -> int:
    """Length of the longest substring of *evidence* found in *corpus*."""
    if not evidence or not corpus:
        return 0
    matcher = difflib.SequenceMatcher(
        None,
        evidence,
        corpus,
        autojunk=False,
    )
    match = matcher.find_longest_match(0, len(evidence), 0, len(corpus))
    return match.size


def _quote_is_cited(evidence: str, corpus: str) -> bool:
    """Return True when *evidence* contains a verifiable quoted fragment.

    The common case is the normalized evidence itself appearing in the
    corpus; that is a cheap substring test. Only when the evidence carries
    extra text (for example a file prefix) do we pay for the longest common
    substring search.
    """
    if (
        len(evidence) >= _BLOCKING_QUOTE_MIN_LENGTH
        and evidence in corpus
    ):
        return True
    return (
        _longest_quote_length(evidence, corpus)
        >= _BLOCKING_QUOTE_MIN_LENGTH
    )


def build_prompt(paper_root: Path, stage: str, paths: list[Path]) -> str:
    """Build the independent-review prompt."""
    paper_root = Path(paper_root)
    mode = _load_mode(paper_root)
    try:
        gate = gate_for(mode, stage)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"未知 stage: {stage!r}") from exc
    relative_paths = [
        _relative_input(paper_root, Path(path))[1]
        for path in paths
    ]
    lines = [
        "你是独立评审模型，只评审 gate 是否满足，不替作者改稿。",
        f"目标模式: {mode}",
        f"当前 stage: {stage}",
        f"Gate: {gate.id}",
        f"判据: {gate.criterion}",
        "",
        "待评审文件:",
    ]
    lines.extend(f"- {path}" for path in relative_paths)
    if stage == "internal-review":
        lines.extend(
            [
                "",
                "本次运行就是在生成当前有效的跨模型评审报告。"
                "不要因为 reviews/cross-review.json 尚不存在，或因为历史轮次存在 "
                "blocking 记录，而把这一事实本身判为 blocking。"
                "请只依据给定的稿件和核验报告，独立判断引用、数字、图表三项核验"
                "是否通过，以及稿件是否存在实质性的科学或完整性问题。",
            ]
        )
    lines.extend(
        [
            "",
            "输出契约: 只返回 JSON 对象，字段为 verdict(pass|blocking)、"
            "blocking[{title,evidence}]、summary。",
            "blocking 中每条必须给可核对的 evidence，不得凭印象断言。",
            "禁止修改任何文件；你只有只读权限，不得创建、删除或写入文件。",
        ]
    )
    return "\n".join(lines) + "\n"


def _schema_text() -> str:
    return json.dumps(REVIEW_SCHEMA, ensure_ascii=False, indent=2) + "\n"


def _validate_payload(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    verdict = payload.get("verdict")
    blocking = payload.get("blocking")
    summary = payload.get("summary")
    if verdict not in ("pass", "blocking"):
        return None
    if not isinstance(blocking, list) or not isinstance(summary, str):
        return None
    if verdict == "pass" and blocking:
        return None
    normalized: list[dict] = []
    for item in blocking:
        if not isinstance(item, dict):
            return None
        title = item.get("title")
        evidence = item.get("evidence")
        if not isinstance(title, str) or not isinstance(evidence, str):
            return None
        normalized.append({"title": title, "evidence": evidence})
    return {
        "verdict": verdict,
        "blocking": normalized,
        "summary": summary,
    }


def _record_paths(out_dir: Path) -> tuple[Path, Path, Path, Path]:
    return (
        out_dir / "cross-review.json",
        out_dir / "cross-review.md",
        out_dir / "cross-review.schema.json",
        out_dir / "cross-review-last-message.json",
    )


def _resolve_out_dir(paper_root: Path, out_dir: Path | None) -> Path:
    output_dir = Path(out_dir) if out_dir else paper_root / "reviews"
    if not output_dir.is_absolute():
        output_dir = paper_root / output_dir
    return output_dir


def _render_markdown(record: dict) -> str:
    lines = [
        "# 跨模型评审记录",
        "",
        f"- model: {record['model']}",
        f"- family_judgement: {record['family_judgement']}",
        f"- verdict: {record['verdict']}",
        f"- started_at: {record['started_at']}",
        f"- duration_s: {record['duration_s']}",
        "",
        "## Summary",
        "",
        str(record.get("summary", "")),
        "",
        "## Blocking",
        "",
    ]
    blocking = record.get("blocking", [])
    if not blocking:
        lines.append("- none")
    else:
        for item in blocking:
            lines.append(f"- {item['title']}: {item['evidence']}")
    lines.extend(["", "## Inputs", ""])
    for path, digest in sorted(record.get("input_hashes", {}).items()):
        lines.append(f"- {path}: {digest}")
    return "\n".join(lines) + "\n"


def _write_records(
    record: dict,
    json_path: Path,
    markdown_path: Path,
) -> None:
    record["record_path"] = str(json_path)
    save_text_atomically(
        json_path,
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="评审记录",
    )
    save_text_atomically(
        markdown_path,
        _render_markdown(record),
        description="评审记录",
    )


def _default_runner(argv, cwd, timeout, prompt):
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"codex exec 超时: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"无法运行 codex exec: {exc}") from exc
    return int(completed.returncode), completed.stderr or ""


def run_review(
    paper_root: Path,
    *,
    model: str = DEFAULT_MODEL,
    stage: str,
    paths: list[Path],
    runner=None,
    timeout: float = 600,
    out_dir: Path | None = None,
    force: bool = False,
) -> dict:
    """Run codex exec and write a structured review record."""
    paper_root = Path(paper_root)
    output_dir = _resolve_out_dir(paper_root, out_dir)
    json_path, markdown_path, schema_path, last_message_path = _record_paths(
        output_dir
    )
    if not force and (json_path.exists() or markdown_path.exists()):
        raise ValueError(f"评审记录已存在，拒绝覆盖: {json_path}")

    input_hashes = _input_hashes(paper_root, paths)
    prompt = build_prompt(paper_root, stage, paths)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    save_text_atomically(
        schema_path,
        _schema_text(),
        description="评审 schema",
    )
    last_message_path.unlink(missing_ok=True)

    argv = [
        "codex",
        "exec",
        "-m",
        model,
        "-s",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        str(paper_root),
        "--output-schema",
        str(schema_path),
        "-o",
        str(last_message_path),
        "-",
    ]
    run = runner or _default_runner
    started_at = _now_iso()
    started = time.monotonic()
    try:
        exit_code, stderr = run(argv, paper_root, timeout, prompt)
    except OSError as exc:
        raise ValueError(f"无法运行 codex exec: {exc}") from exc
    duration_s = round(time.monotonic() - started, 6)
    family = _family_judgement(model)

    if exit_code != 0:
        failure = {
            "status": "failed",
            "model": model,
            "family_judgement": family,
            "verdict": None,
            "blocking": [],
            "summary": "codex exec failed",
            "input_hashes": input_hashes,
            "started_at": started_at,
            "duration_s": duration_s,
            "stage": stage,
            "exit_code": int(exit_code),
            "stderr": _bounded_stderr(stderr),
        }
        _write_records(failure, json_path, markdown_path)
        raise ValueError(
            f"codex exec 失败 (exit {exit_code}): {str(stderr)[:500]}"
        )

    raw_last_message = ""
    if last_message_path.is_file():
        raw_last_message = last_message_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    try:
        payload = json.loads(raw_last_message) if raw_last_message else None
    except json.JSONDecodeError:
        payload = None
    normalized = _validate_payload(payload)
    if normalized is None:
        malformed = {
            "status": "malformed",
            "model": model,
            "family_judgement": family,
            "verdict": "malformed",
            "blocking": [],
            "summary": "review output missing or malformed",
            "input_hashes": input_hashes,
            "started_at": started_at,
            "duration_s": duration_s,
            "stage": stage,
            "exit_code": 0,
            "stderr": _bounded_stderr(stderr),
            "raw_last_message": _bounded_text(
                raw_last_message,
                _RAW_LAST_MESSAGE_LIMIT,
            ),
        }
        _write_records(malformed, json_path, markdown_path)
        return malformed

    record = {
        "status": "complete",
        "model": model,
        "family_judgement": family,
        "verdict": normalized["verdict"],
        "blocking": normalized["blocking"],
        "summary": normalized["summary"],
        "input_hashes": input_hashes,
        "started_at": started_at,
        "duration_s": duration_s,
        "stage": stage,
        "exit_code": 0,
        "stderr": _bounded_stderr(stderr),
    }
    _write_records(record, json_path, markdown_path)
    return record


def _review_record_path(paper_root: Path, out_dir: Path | None = None) -> Path:
    return _resolve_out_dir(Path(paper_root), out_dir) / "cross-review.json"


def check_review(
    paper_root: Path,
    out_dir: Path | None = None,
) -> list[Problem]:
    """Audit the stored review record against current inputs."""
    paper_root = Path(paper_root)
    path = _review_record_path(paper_root, out_dir)
    if not path.is_file():
        return [
            Problem(
                "review-missing",
                str(path),
                None,
                "缺少跨模型评审记录",
            )
        ]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [
            Problem(
                "review-malformed",
                str(path),
                None,
                f"评审记录不可读: {exc}",
            )
        ]
    if not isinstance(record, dict):
        return [
            Problem(
                "review-malformed",
                str(path),
                None,
                "评审记录顶层必须是对象",
            )
        ]
    try:
        payload = _validate_payload(record)
    except (KeyError, TypeError):
        payload = None
    if payload is None or record.get("status") != "complete":
        return [
            Problem(
                "review-malformed",
                str(path),
                None,
                "评审记录 verdict/blocking/summary 不合 schema",
            )
        ]

    problems: list[Problem] = []
    hashes = record.get("input_hashes")
    if not isinstance(hashes, dict):
        problems.append(
            Problem(
                "review-malformed",
                str(path),
                None,
                "评审记录缺少 input_hashes",
            )
        )
    else:
        for relative, expected in hashes.items():
            if not isinstance(relative, str) or not relative:
                problems.append(
                    Problem(
                        "review-record-invalid",
                        str(path),
                        None,
                        f"评审输入路径非法: {relative!r}",
                    )
                )
                continue
            root = paper_root.resolve()
            input_path = (paper_root / relative).resolve()
            try:
                input_path.relative_to(root)
            except ValueError:
                problems.append(
                    Problem(
                        "review-record-invalid",
                        str(path),
                        None,
                        f"评审输入路径逃出 paper_root: {relative!r}",
                    )
                )
                continue
            try:
                actual = _sha256(input_path)
            except OSError:
                problems.append(
                    Problem(
                        "review-stale",
                        str(path),
                        None,
                        f"评审输入不存在: {relative}",
                    )
                )
                continue
            if actual != expected:
                problems.append(
                    Problem(
                        "review-stale",
                        str(path),
                        None,
                        f"评审输入已变化: {relative}",
                    )
                )
    if payload["verdict"] == "blocking":
        problems.append(
            Problem(
                "review-blocking",
                str(path),
                None,
                payload["summary"] or "评审报告包含 blocking 项",
            )
        )
        corpus = _input_corpus(paper_root, hashes)
        for index, item in enumerate(payload["blocking"]):
            evidence = _normalize_whitespace(item["evidence"])
            if not _quote_is_cited(evidence, corpus):
                problems.append(
                    Problem(
                        "review-uncited-blocking",
                        str(path),
                        None,
                        f"blocking[{index}] {item['title']!r} 的 evidence "
                        f"没有 ≥{_BLOCKING_QUOTE_MIN_LENGTH} 字符的引文"
                        "逐字出现在评审输入文件中",
                    )
                )
    return problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "用独立模型执行 gate 评审。默认 deepseek-v4-pro 与执行模型 "
            "deepseek-v4-flash 同族不同规模，非跨族。"
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="运行一次独立模型评审")
    run.add_argument("--paper-root", default=".")
    run.add_argument("--stage", required=True)
    run.add_argument("--path", action="append", required=True)
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--timeout", type=float, default=600)
    run.add_argument("--out-dir")
    run.add_argument("--force", action="store_true")

    check = subparsers.add_parser("check", help="审计已有评审记录")
    check.add_argument("--paper-root", default=".")
    check.add_argument("--out-dir", default="reviews")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            return emit(
                check_review(
                    Path(args.paper_root),
                    out_dir=Path(args.out_dir),
                )
            )
        record = run_review(
            Path(args.paper_root),
            model=args.model,
            stage=args.stage,
            paths=[Path(item) for item in args.path],
            timeout=args.timeout,
            out_dir=Path(args.out_dir) if args.out_dir else None,
            force=args.force,
        )
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        if record.get("verdict") == "pass":
            return 0
        return 1
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
