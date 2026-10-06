"""One ordered human worklist for a paper, assembled from existing records.

This is a **view**, not a gate. It adds no new check and changes no verdict:
``readiness`` still decides ``ready``, and every item here is a task the
workflow has already decided a human must do. The module exists because that
decision was spread across `readiness` (the blocking list), `e2e_check` (the
checkpoint table), the ledger checkers (what a *finished* entry looks like) and
`ccfa-workfiles/human-review/` (the packets) — so the loop was: run twenty
things, then work out by hand what to do next.

For each pending checkpoint it answers four questions in one place:

* what must be judged (the checkpoint's own question);
* what to read first (the packet files that match it);
* where the answer goes (the ledger beside it);
* what counts as finished (the fields the ledger's own checker requires) —
  quoted from the checker, not invented here.

Ordering is data-driven: everything the current ``readiness`` blocking list
implicates comes first, then the rest in stage order. Nothing is ever marked
done by this module; it reports what the ledgers already say.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ccfa.cli import tool_error
from ccfa.readiness import HUMAN_CHECKPOINT_SPECS, build_report

SCHEMA_VERSION = 1
HUMAN_REVIEW_DIR = Path("ccfa-workfiles") / "human-review"
OBLIGATIONS_RELATIVE = Path("data") / "integrity-obligations.jsonl"

# What a finished ledger entry looks like, quoted from the module that will
# reject it otherwise. Keep these in step with the checkers.
FINISHED_CRITERIA: dict[str, dict[str, str]] = {
    "proof": {
        "checker": "tools/ccfa/argument_audit.py",
        "requires": (
            "每条 review 需要 id / reviewer / reviewed_at / method / status；"
            "status 取 pending|verified|refuted|uncertain；"
            "status=verified 时还必须写 audited_inputs 并包含该定理所在文件；"
            "reviewer 必须是人类姓名（模型名会被判为无效复核）"
        ),
    },
    "citation-support": {
        "checker": "tools/ccfa/argument_audit.py",
        "requires": (
            "supports[] 每条需要 id / claim_text / citations / reviewer / "
            "reviewed_at / verdict / support_quote；"
            "verdict 取 supports|partial|contradicts|irrelevant"
        ),
    },
    "figure-support": {
        "checker": "tools/ccfa/argument_audit.py",
        "requires": (
            "figures[] 每条需要 verdict / reviewer / reviewed_at；"
            "verdict 取 supports|partial|contradicts|irrelevant|not-applicable"
        ),
    },
    "cross-review": {
        "checker": "tools/ccfa/cross_review.py",
        "artifact": "reviews/cross-review.json",
        "requires": (
            "reviews/cross-review.json 无 blocking 项，且 review_tier=gate-capable、"
            "family_judgement=cross-family、prompt/provenance 与当前配置一致"
        ),
    },
    "adversarial-review": {
        "checker": "tools/ccfa/adversarial_review.py",
        "artifact": "reviews/adversarial-review.json",
        "requires": (
            "reviews/adversarial-review.json 里每条 finding 有处置与不少于 20 字的"
            " resolution，且没有未解决的 finding"
        ),
    },
    "claim-candidates": {
        "checker": "tools/ccfa/claim_extract.py",
        "requires": "逐条 promote/reject，接受项写进 data/claim-registry.yaml",
    },
    "research-plans": {
        "checker": "tools/ccfa/autoresearch.py",
        "requires": (
            "逐条审阅 problem/gap/hypothesis/实验设计/kill criteria，"
            "接受项写进实验循环台账"
        ),
    },
    "optimization-proposals": {
        "checker": "tools/ccfa/experiment_optimizer.py",
        "requires": "逐条审阅 best trial、objective 与预算，接受项写进 data/experiment-loop.yaml",
    },
    "code-mutations": {
        "checker": "tools/ccfa/autoresearch.py",
        "requires": "逐条审阅 diff、sandbox_status 与输出，再决定是否应用 patch",
    },
    "human-coding": {
        "checker": "tools/ccfa/human_coding.py",
        "requires": "写 coders、agreement、kappa 与分歧裁决；必须是第二位人类编码者盲法完成",
    },
}

# Which blocking entries implicate which checkpoints. Derived from the gate
# that raised them, not from a priority we invented.
BLOCKING_HINTS = {
    "argument-audit": ("proof", "citation-support", "figure-support"),
    "cross-review": ("cross-review",),
    "adversarial-review": ("adversarial-review",),
    "human-coding": ("human-coding",),
    "governance": (),
}

STAGE_ORDER = (
    "idea",
    "grounded",
    "data-ready",
    "experiment-design",
    "experiments-running",
    "results-ready",
    "writing",
    "internal-review",
    "submission-check",
)


def _packets(paper_root: Path, checkpoint_id: str) -> list[str]:
    """Packet files in ccfa-workfiles/human-review that match a checkpoint."""
    directory = Path(paper_root) / HUMAN_REVIEW_DIR
    if not directory.is_dir():
        return []
    tokens = [part for part in checkpoint_id.split("-") if len(part) > 2]
    found: list[Path] = []
    for path in sorted(directory.glob("*.md")):
        stem = path.stem.casefold()
        if path.name.casefold() == "readme.md":
            continue
        # Every token must appear: "support" alone would otherwise pull the
        # figure packet into the citation task and vice versa.
        if tokens and all(token in stem for token in tokens):
            found.append(path)
    return [path.relative_to(paper_root).as_posix() for path in found]


def _problem_rank(paper_root: Path, report: dict) -> dict[str, int]:
    """Rank checkpoints by where their problems appear in the gate reports.

    The order inside a gate's problem list is the workflow's own statement of
    what it found first, so it is a better priority signal than an order we
    invent here.
    """
    ranks: dict[str, int] = {}
    index = 0
    for gate in report.get("gate_results", []):
        for problem in gate.get("problems", []):
            code = str(problem.get("code", ""))
            for checkpoint_id in HUMAN_CHECKPOINT_SPECS:
                tokens = [
                    part for part in checkpoint_id.split("-") if len(part) > 3
                ]
                if not tokens or any(token not in code for token in tokens):
                    continue
                ranks.setdefault(checkpoint_id, index)
            index += 1
    return ranks


def _coverage(paper_root: Path) -> dict[str, str]:
    """Current progress lines, read from the gate reports the paper already has."""
    report = build_report(paper_root)
    counts: dict[str, str] = {}
    for gate in report.get("gate_results", []):
        for advisory in gate.get("advisories", []):
            if advisory.get("code", "").endswith("-coverage"):
                counts[advisory["code"].removesuffix("-coverage")] = advisory.get(
                    "message", ""
                )
    return counts


def _obligations_open(paper_root: Path) -> int:
    path = Path(paper_root) / OBLIGATIONS_RELATIVE
    if not path.is_file():
        return 0
    from ccfa.integrity_forensics import load_obligations, obligation_state

    state = obligation_state(load_obligations(path))
    return sum(
        1
        for item in state.values()
        if item.get("status") not in ("resolved", "waived")
    )


def collect(paper_root: Path) -> dict:
    """Assemble the ordered worklist from existing records only."""
    paper_root = Path(paper_root).resolve()
    report = build_report(paper_root)
    checkpoints = report.get("human_review", {}).get("checkpoints", [])
    blocking = [str(item) for item in report.get("blocking", [])]
    coverage = _coverage(paper_root)

    implicated: set[str] = set()
    for entry in blocking:
        for gate, ids in BLOCKING_HINTS.items():
            if gate in entry:
                implicated.update(ids)
    ranks = _problem_rank(paper_root, report)
    # Problem ranks are positions inside the gate reports, so the fallback for
    # an implicated checkpoint with no problem of its own (cross-review blocks
    # through a review verdict, not a per-item problem) must sit past all of
    # them rather than at len(ranks), which would beat a real rank.
    after_ranks = max(ranks.values(), default=-1) + 1

    def sort_key(item: dict) -> tuple[int, int, int, str]:
        checkpoint_id = str(item.get("id", ""))
        stage = str(item.get("stage", ""))
        stage_index = (
            STAGE_ORDER.index(stage) if stage in STAGE_ORDER else len(STAGE_ORDER)
        )
        return (
            # Everything the blocking list implicates leads, ordered by where
            # the workflow found it; everything else follows in stage order.
            0 if checkpoint_id in implicated else 1,
            ranks.get(checkpoint_id, after_ranks),
            stage_index,
            checkpoint_id,
        )

    items: list[dict] = []
    for checkpoint in sorted(checkpoints, key=sort_key):
        checkpoint_id = str(checkpoint.get("id", ""))
        spec = HUMAN_CHECKPOINT_SPECS.get(checkpoint_id, {})
        criteria = FINISHED_CRITERIA.get(checkpoint_id, {})
        items.append(
            {
                "order": len(items) + 1,
                "id": checkpoint_id,
                "type": checkpoint.get("type") or spec.get("type"),
                "stage": checkpoint.get("stage") or spec.get("stage"),
                "question": checkpoint.get("question") or spec.get("question"),
                "read_first": _packets(paper_root, checkpoint_id),
                "write_into": checkpoint.get("ledger") or criteria.get("artifact"),
                "answer_with": spec.get("answer_with"),
                "finished_when": criteria.get("requires"),
                "checked_by": criteria.get("checker"),
                "progress": coverage.get(checkpoint_id)
                or coverage.get(f"{checkpoint_id}-audit"),
                "implicated_by_blocking": checkpoint_id in implicated,
            }
        )
    open_obligations = _obligations_open(paper_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "paper_root": str(paper_root),
        "stage": report.get("stage", {}).get("current"),
        "gate": report.get("stage", {}).get("gate"),
        "ready": report.get("ready"),
        "blocking": blocking,
        "deadline": report.get("deadline", {}),
        "pending_count": len(items),
        "open_integrity_obligations": open_obligations,
        "items": items,
    }


def render_markdown(payload: dict) -> str:
    deadline = payload.get("deadline") or {}
    days = deadline.get("days_left")
    lines = [
        "# 人工待办（有序）",
        "",
        f"- 论文: `{Path(payload['paper_root']).name}`",
        f"- stage: `{payload.get('stage')}` / gate `{payload.get('gate')}`",
        f"- ready: `{payload.get('ready')}`",
        f"- 截至: {deadline.get('deadline')}（还有 {days} 天）"
        if days is not None
        else f"- 截至: {deadline.get('deadline')}",
        f"- 待人工复核: {payload.get('pending_count')} 项"
        f"，其中 {sum(1 for item in payload['items'] if item['implicated_by_blocking'])}"
        " 项与当前阻塞直接相关",
        "",
        "这份清单只是**视图**：它不校验任何东西，也不改变任何 gate 结论。"
        "每一项的完成判据来自对应的 ledger 校验器，最终仍由 `readiness` 判定。",
        "",
    ]
    if payload.get("open_integrity_obligations"):
        lines.append(
            f"- 另有 {payload['open_integrity_obligations']} 条 integrity obligations "
            "未关闭（见 `data/integrity-obligations.jsonl`）"
        )
        lines.append("")
    for item in payload["items"]:
        marker = " **[阻塞]**" if item["implicated_by_blocking"] else ""
        lines.append(f"## {item['order']}. `{item['id']}`{marker}")
        lines.append("")
        lines.append(f"- 要判断什么：{item.get('question')}")
        if item.get("progress"):
            lines.append(f"- 当前进度：{item['progress']}")
        if item.get("read_first"):
            lines.append(
                "- 先读："
                + "、".join(f"`{path}`" for path in item["read_first"])
            )
        lines.append(f"- 写进：`{item.get('write_into')}`" if item.get("write_into") else "- 写进：—")
        if item.get("answer_with"):
            lines.append(f"- 记录方式：{item['answer_with']}")
        if item.get("finished_when"):
            lines.append(f"- 完成判据：{item['finished_when']}")
        if item.get("checked_by"):
            lines.append(f"- 谁校验：`{item['checked_by']}`")
        lines.append("")
    lines.extend(
        [
            "## 边界",
            "",
            "- 这份清单不证明任何结论正确，也不替代复核本身；",
            "- 所有条目仍然需要真人签字，机器只能核对台账字段是否齐备；",
            "- 清单会随 `readiness` 的阻塞项自动重排，不需要手工维护。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "把 readiness 的待人工复核项、对应 packet 与 ledger 完成判据"
            "合成一份有序清单（只读，不新增 gate）"
        )
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是 Markdown")
    parser.add_argument("--next", action="store_true", help="只输出第一条")
    parser.add_argument("--out", default=None, help="写入文件")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        payload = collect(Path(args.paper_root))
        if args.next and payload["items"]:
            first = payload["items"][0]
            print(
                json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True)
            )
            return 0
        if args.next:
            print(json.dumps({"items": []}, ensure_ascii=False))
            return 0
        text = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.json
            else render_markdown(payload)
        )
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(text, end="")
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
