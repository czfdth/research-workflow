"""The patent track: a deterministic gate plus jurisdiction formatter.

The reference (ARIS) runs patents as a nine-skill chain —
``prior-art-search → patent-novelty-check → invention-structuring →
claims-drafting → specification-writing → patent-review →
jurisdiction-format`` with ``figure-description`` / ``embodiment-description``
feeding the specification. Every one of those is prose the agent re-reads each
run, and the failure mode is that a filing looks complete while a claim has no
antecedent basis, the EP two-part form is missing, or the Chinese abstract
blows the 300-character cap.

This module turns the *checkable* half of that chain into a gate over a
``patent/`` directory and implements the ``jurisdiction-format`` compile step:

* state — ``patent/PATENT_STATE.json`` phase/status/jurisdiction/type;
* invention — the disclosure must decompose into core/supporting/optional
  features (the structuring contract);
* claims — sequential numbering without gaps, at least the required number of
  independent claims, dependent claims referencing an earlier claim, the
  jurisdiction's characterising phrase on every independent claim, and the
  utility-model restriction (CN only, no method claims);
* prior art / novelty — a report with enough located references, plus a novelty
  assessment that names suggested amendments;
* examiner review — every recorded objection resolved;
* compiled output — for each generated jurisdiction, all claims present,
  abstract within the jurisdiction's limit, language matching the jurisdiction,
  and reference numerals shared between claims and description.

The formatter **does not translate**. It reorders and re-headers the canonical
sections into each jurisdiction's required order and then runs the same checks
over its own output; a CN claim pasted into a US filing is rejected, not
silently translated. That mirrors the reference rule "the jurisdiction-format
skill does NOT modify claim content".
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error

SCHEMA_VERSION = 1
JURISDICTIONS = ("CN", "US", "EP")
PATENT_TYPES = ("invention", "utility_model")
STATUSES = ("in_progress", "completed")
MIN_INDEPENDENT_CLAIMS = {"invention": 2, "utility_model": 1}
MAX_TOTAL_CLAIMS = 20
MIN_PRIOR_ART_REFS = 3
CN_ABSTRACT_LIMIT = 300
EN_ABSTRACT_WORD_LIMIT = 150
STATE_STALE_HOURS = 24

CLAIM_RE = re.compile(r"^(\d+)\.\s+(.*)$", re.MULTILINE)
DEPENDENCY_RE = re.compile(
    r"(?:(?:according to claim|of claim|claim)\s*(\d+)|权利要求\s*(\d+))",
    re.IGNORECASE,
)
METHOD_RE = re.compile(r"(?:方法|method)", re.IGNORECASE)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
URL_OR_DOI_RE = re.compile(r"(https?://\S+|doi:\S+|10\.\d{4,9}/\S+)", re.IGNORECASE)
NUMERAL_RE = re.compile(r"\b(\d{1,3})\b")
CN_CHARACTERISING = "其特征在于"
EN_CHARACTERISING = ("characterised in that", "characterized in that")

SPEC_SECTIONS = (
    "title",
    "technical_field",
    "background",
    "summary",
    "drawings_description",
    "detailed_description",
    "abstract",
)

# Output section order per jurisdiction, from the reference
# `jurisdiction-format` phase descriptions (CNIPA / USPTO / EPO Rule 42).
JURISDICTION_ORDER = {
    "CN": (
        ("title", "发明名称"),
        ("technical_field", "技术领域"),
        ("background", "背景技术"),
        ("summary", "发明内容"),
        ("drawings_description", "附图说明"),
        ("detailed_description", "具体实施方式"),
    ),
    "US": (
        ("title", "Title"),
        ("technical_field", "Field of the Invention"),
        ("background", "Background of the Invention"),
        ("summary", "Brief Summary of the Invention"),
        ("drawings_description", "Brief Description of the Drawings"),
        ("detailed_description", "Detailed Description of Preferred Embodiments"),
    ),
    "EP": (
        ("title", "Title of the Invention"),
        ("technical_field", "Technical Field"),
        ("background", "Background Art"),
        ("summary", "Disclosure of the Invention"),
        ("detailed_description", "Description of Embodiments"),
        ("drawings_description", "Brief Description of the Drawings"),
    ),
}


def _problem(code: str, path: Path | str, message: str, line: int | None = None) -> Problem:
    return Problem(code, str(path), line, message)


def read_state(patent_root: Path) -> dict | None:
    path = Path(patent_root) / "PATENT_STATE.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def check_state(
    patent_root: Path,
    *,
    now: dt.datetime | None = None,
) -> tuple[list[Problem], list[Problem]]:
    """Validate the resumable state file, including the 24h staleness rule."""
    root = Path(patent_root)
    path = root / "PATENT_STATE.json"
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not path.is_file():
        return [
            _problem(
                "patent-state-missing",
                path,
                "缺少 PATENT_STATE.json；链式流程靠它做 compaction 恢复",
            )
        ], advisories
    state = read_state(root)
    if not state:
        return [_problem("patent-state-invalid", path, "PATENT_STATE.json 不是 JSON 对象")], advisories
    phase = state.get("phase")
    if not isinstance(phase, int) or isinstance(phase, bool) or phase < 0:
        problems.append(_problem("patent-state-invalid", path, "phase 必须是非负整数"))
    status = state.get("status")
    if status not in STATUSES:
        problems.append(
            _problem(
                "patent-state-invalid",
                path,
                f"status 必须是 {' / '.join(STATUSES)}，当前 {status!r}",
            )
        )
    jurisdiction = state.get("jurisdiction")
    if jurisdiction not in (*JURISDICTIONS, "ALL"):
        problems.append(
            _problem(
                "patent-state-invalid",
                path,
                f"jurisdiction 必须是 CN/US/EP/ALL，当前 {jurisdiction!r}",
            )
        )
    patent_type = state.get("patent_type")
    if patent_type not in PATENT_TYPES:
        problems.append(
            _problem(
                "patent-state-invalid",
                path,
                f"patent_type 必须是 {' / '.join(PATENT_TYPES)}，当前 {patent_type!r}",
            )
        )
    elif patent_type == "utility_model" and jurisdiction not in ("CN", None):
        problems.append(
            _problem(
                "patent-type-jurisdiction-mismatch",
                path,
                "实用新型只能是 CN（CNIPA）申请",
            )
        )
    timestamp = state.get("timestamp")
    if status == "in_progress":
        parsed = None
        if isinstance(timestamp, str):
            try:
                parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
        if parsed is None:
            problems.append(
                _problem(
                    "patent-state-invalid",
                    path,
                    "in_progress 状态必须带可解析的 ISO timestamp",
                )
            )
        else:
            reference = now or dt.datetime.now(parsed.tzinfo or dt.timezone.utc)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=reference.tzinfo)
            age = reference - parsed
            if age.total_seconds() > STATE_STALE_HOURS * 3600:
                advisories.append(
                    _problem(
                        "patent-state-stale",
                        path,
                        f"state 已过期 {age.total_seconds() / 3600:.1f}h "
                        f"(> {STATE_STALE_HOURS}h)；应重新开始而不是续跑旧上下文",
                    )
                )
    return problems, advisories


def write_state(
    patent_root: Path,
    *,
    phase: int,
    status: str,
    jurisdiction: str,
    patent_type: str,
    invention_title: str = "",
    claims_count: int | None = None,
) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status 必须是 {' / '.join(STATUSES)}")
    if jurisdiction not in (*JURISDICTIONS, "ALL"):
        raise ValueError("jurisdiction 必须是 CN/US/EP/ALL")
    if patent_type not in PATENT_TYPES:
        raise ValueError(f"patent_type 必须是 {' / '.join(PATENT_TYPES)}")
    if patent_type == "utility_model" and jurisdiction != "CN":
        raise ValueError("实用新型只能是 CN")
    state = {
        "phase": int(phase),
        "jurisdiction": jurisdiction,
        "patent_type": patent_type,
        "status": status,
        "timestamp": dt.datetime.now(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "invention_title": invention_title,
        "schema_version": SCHEMA_VERSION,
    }
    if claims_count is not None:
        state["claims_count"] = int(claims_count)
    path = Path(patent_root) / "PATENT_STATE.json"
    save_text_atomically(
        path,
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="专利状态文件",
    )
    return state


def parse_claims(text: str) -> list[dict]:
    """Split claims on ``N. `` and record each one's dependency."""
    matches = list(CLAIM_RE.finditer(text or ""))
    claims: list[dict] = []
    for index, match in enumerate(matches):
        # The claim body starts at the first character after "N. " and runs to
        # the next claim number (so continuation lines are included; slicing
        # after ``match.end()`` would drop the claim's own first line).
        start = match.start(2)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        number = int(match.group(1))
        dependency = None
        reference = DEPENDENCY_RE.search(body)
        if reference is not None:
            number_group = next(
                (group for group in reference.groups() if group), None
            )
            dependency = int(number_group) if number_group else -1
        claims.append(
            {
                "number": number,
                "text": body,
                "dependent_on": dependency,
                "independent": dependency is None,
            }
        )
    return claims


def check_claims(
    patent_root: Path,
    *,
    patent_type: str,
    jurisdictions: tuple[str, ...],
) -> tuple[list[Problem], list[Problem]]:
    """Structural claim rules that apply before any jurisdiction compile."""
    root = Path(patent_root)
    path = root / "CLAIMS.md"
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not path.is_file():
        return [_problem("patent-claims-missing", path, "缺少 CLAIMS.md")], advisories
    text = path.read_text(encoding="utf-8")
    claims = parse_claims(text)
    if not claims:
        return [
            _problem(
                "patent-claims-unparsable",
                path,
                "找不到 `N. ` 形式的权利要求编号",
            )
        ], advisories
    numbers = [claim["number"] for claim in claims]
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        problems.append(
            _problem(
                "patent-claim-numbering",
                path,
                f"权利要求编号必须从 1 连续：得到 {numbers}",
            )
        )
    independent = [claim for claim in claims if claim["independent"]]
    required = MIN_INDEPENDENT_CLAIMS[patent_type]
    if len(independent) < required:
        problems.append(
            _problem(
                "patent-insufficient-independent-claims",
                path,
                f"{patent_type} 至少需要 {required} 条独立权利要求，"
                f"当前 {len(independent)} 条（方法 + 系统/装置）",
            )
        )
    if len(claims) > MAX_TOTAL_CLAIMS:
        advisories.append(
            _problem(
                "patent-too-many-claims",
                path,
                f"共 {len(claims)} 条权利要求，超过 {MAX_TOTAL_CLAIMS} 条"
                "（USPTO 基础费只含 20 条）",
            )
        )
    for claim in claims:
        dependency = claim["dependent_on"]
        if dependency is None:
            continue
        if dependency == -1:
            problems.append(
                _problem(
                    "patent-claim-dependency",
                    path,
                    f"权利要求 {claim['number']} 引用了父项但没有写出编号",
                )
            )
        elif dependency >= claim["number"]:
            problems.append(
                _problem(
                    "patent-claim-dependency",
                    path,
                    f"权利要求 {claim['number']} 引用了不早于自身的 "
                    f"权利要求 {dependency}",
                )
            )
        elif dependency not in numbers:
            problems.append(
                _problem(
                    "patent-claim-dependency",
                    path,
                    f"权利要求 {claim['number']} 引用了不存在的权利要求 "
                    f"{dependency}",
                )
            )
    if patent_type == "utility_model":
        offenders = [
            claim["number"]
            for claim in claims
            if METHOD_RE.search(claim["text"])
        ]
        if offenders:
            problems.append(
                _problem(
                    "patent-utility-model-method-claim",
                    path,
                    "实用新型只能写装置权利要求，不能出现方法权利要求："
                    + ", ".join(str(number) for number in offenders),
                )
            )
    for jurisdiction in jurisdictions:
        for claim in independent:
            lowered = claim["text"].casefold()
            if jurisdiction == "CN" and CN_CHARACTERISING not in claim["text"]:
                problems.append(
                    _problem(
                        "patent-claim-characterising-missing",
                        path,
                        f"CN 独立权利要求 {claim['number']} 缺少「{CN_CHARACTERISING}」"
                        "（两部式写法）",
                    )
                )
            if jurisdiction == "US" and "comprising" not in lowered:
                problems.append(
                    _problem(
                        "patent-claim-characterising-missing",
                        path,
                        f"US 独立权利要求 {claim['number']} 缺少 open transition "
                        "「comprising」",
                    )
                )
            if jurisdiction == "EP" and not any(
                phrase in lowered for phrase in EN_CHARACTERISING
            ):
                problems.append(
                    _problem(
                        "patent-claim-characterising-missing",
                        path,
                        f"EP 独立权利要求 {claim['number']} 缺少 "
                        "「characterised in that」（Rule 43(1) 两部式强制）",
                    )
                )
    return problems, advisories


def check_prior_art(
    patent_root: Path,
) -> tuple[list[Problem], list[Problem]]:
    root = Path(patent_root)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    report = root / "PRIOR_ART_REPORT.md"
    if not report.is_file():
        problems.append(
            _problem("patent-prior-art-missing", report, "缺少 PRIOR_ART_REPORT.md")
        )
    else:
        text = report.read_text(encoding="utf-8")
        refs = {match.group(0) for match in URL_OR_DOI_RE.finditer(text)}
        if len(refs) < MIN_PRIOR_ART_REFS:
            problems.append(
                _problem(
                    "patent-prior-art-thin",
                    report,
                    f"只有 {len(refs)} 条可定位的现有技术（URL/DOI），"
                    f"至少需要 {MIN_PRIOR_ART_REFS} 条",
                )
            )
    novelty = root / "NOVELTY_ASSESSMENT.md"
    if not novelty.is_file():
        problems.append(
            _problem("patent-novelty-missing", novelty, "缺少 NOVELTY_ASSESSMENT.md")
        )
    elif len(novelty.read_text(encoding="utf-8").strip()) < 40:
        advisories.append(
            _problem(
                "patent-novelty-thin",
                novelty,
                "NOVELTY_ASSESSMENT.md 过短，看不出区别与建议修改",
            )
        )
    return problems, advisories


def check_review(patent_root: Path) -> tuple[list[Problem], list[Problem]]:
    root = Path(patent_root)
    path = root / "patent-review.yaml"
    if not path.is_file():
        return [], [
            _problem(
                "patent-review-not-run",
                path,
                "尚未跑审查员式 review（patent-review.yaml 不存在）",
            )
        ]
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [
            _problem("patent-review-invalid", path, f"YAML 非法: {exc}")
        ], []
    if not isinstance(payload, dict):
        return [_problem("patent-review-invalid", path, "顶层必须是映射")], []
    problems: list[Problem] = []
    objections = payload.get("objections")
    if not isinstance(objections, list):
        return [
            _problem("patent-review-invalid", path, "objections 必须是数组")
        ], []
    for index, item in enumerate(objections):
        if not isinstance(item, dict):
            problems.append(
                _problem(
                    "patent-review-invalid",
                    path,
                    f"objections[{index}] 必须是映射",
                )
            )
            continue
        status = item.get("status")
        if status != "resolved":
            problems.append(
                _problem(
                    "patent-review-unresolved",
                    path,
                    f"objections[{index}] 仍未解决（{item.get('id', index)}："
                    f"{status!r}）",
                )
            )
        if status == "resolved" and not str(item.get("resolution", "")).strip():
            problems.append(
                _problem(
                    "patent-review-unresolved",
                    path,
                    f"objections[{index}] 标为 resolved 但没有 resolution",
                )
            )
    return problems, []


def _count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text))


def _count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def check_output(
    patent_root: Path,
) -> tuple[list[Problem], list[Problem]]:
    """Check any compiled `output/<J>/` trees for cross-jurisdiction drift."""
    root = Path(patent_root)
    output_root = root / "output"
    problems: list[Problem] = []
    advisories: list[Problem] = []
    if not output_root.is_dir():
        return [], []
    canonical = parse_claims(
        (root / "CLAIMS.md").read_text(encoding="utf-8")
        if (root / "CLAIMS.md").is_file()
        else ""
    )
    canonical_numbers = {claim["number"] for claim in canonical}
    description_text = " ".join(
        (root / "specification" / f"{key}.md").read_text(encoding="utf-8")
        for key in SPEC_SECTIONS
        if (root / "specification" / f"{key}.md").is_file()
    )
    canonical_numerals = {
        match.group(1) for match in NUMERAL_RE.finditer(description_text)
    }
    for jurisdiction in sorted(
        path.name for path in output_root.iterdir() if path.is_dir()
    ):
        folder = output_root / jurisdiction
        if jurisdiction not in JURISDICTIONS:
            advisories.append(
                _problem(
                    "patent-output-unknown-jurisdiction",
                    folder,
                    f"未知输出目录 {jurisdiction!r}",
                )
            )
            continue
        claims_path = folder / "claims.md"
        abstract_path = folder / "abstract.md"
        description_path = folder / "description.md"
        for required in (claims_path, abstract_path, description_path):
            if not required.is_file():
                problems.append(
                    _problem(
                        "patent-output-missing",
                        required,
                        f"{jurisdiction} 输出缺少 {required.name}",
                    )
                )
        if claims_path.is_file():
            compiled = parse_claims(claims_path.read_text(encoding="utf-8"))
            missing = canonical_numbers - {claim["number"] for claim in compiled}
            if missing:
                problems.append(
                    _problem(
                        "patent-output-claim-drift",
                        claims_path,
                        f"{jurisdiction} 输出漏了权利要求 "
                        + ", ".join(str(number) for number in sorted(missing)),
                    )
                )
        if abstract_path.is_file():
            abstract = abstract_path.read_text(encoding="utf-8")
            if jurisdiction == "CN":
                count = _count_cjk(abstract)
                if count > CN_ABSTRACT_LIMIT:
                    problems.append(
                        _problem(
                            "patent-output-abstract-too-long",
                            abstract_path,
                            f"CN 摘要 {count} 字 > {CN_ABSTRACT_LIMIT} 字",
                        )
                    )
                if not CJK_RE.search(abstract):
                    problems.append(
                        _problem(
                            "patent-output-language",
                            abstract_path,
                            "CN 摘要里没有中文",
                        )
                    )
            else:
                words = _count_words(abstract)
                if words > EN_ABSTRACT_WORD_LIMIT:
                    problems.append(
                        _problem(
                            "patent-output-abstract-too-long",
                            abstract_path,
                            f"{jurisdiction} 摘要 {words} 词 > "
                            f"{EN_ABSTRACT_WORD_LIMIT} 词",
                        )
                    )
                if CJK_RE.search(abstract):
                    problems.append(
                        _problem(
                            "patent-output-language",
                            abstract_path,
                            f"{jurisdiction} 摘要里出现中文",
                        )
                    )
        if description_path.is_file():
            text = description_path.read_text(encoding="utf-8")
            if jurisdiction in ("US", "EP") and CJK_RE.search(text):
                problems.append(
                    _problem(
                        "patent-output-language",
                        description_path,
                        f"{jurisdiction} 说明书里出现中文",
                    )
                )
            used = {
                match.group(1) for match in NUMERAL_RE.finditer(text)
            }
            if canonical_numerals and not (used & canonical_numerals):
                advisories.append(
                    _problem(
                        "patent-output-numerals",
                        description_path,
                        f"{jurisdiction} 说明书没有复用权利要求里的附图标记",
                    )
                )
    return problems, advisories


def check(patent_root: Path) -> tuple[list[Problem], list[Problem]]:
    """Run the whole patent gate over a ``patent/`` directory."""
    root = Path(patent_root)
    if not root.is_dir():
        return [
            _problem("patent-root-missing", root, f"patent 目录不存在: {root}")
        ], []
    problems: list[Problem] = []
    advisories: list[Problem] = []
    state_problems, state_advisories = check_state(root)
    problems.extend(state_problems)
    advisories.extend(state_advisories)
    state = read_state(root) or {}
    patent_type = state.get("patent_type")
    if patent_type not in PATENT_TYPES:
        patent_type = "invention"
    target = state.get("jurisdiction", "CN")
    jurisdictions = (
        JURISDICTIONS if target == "ALL" else (target,)
    )
    jurisdictions = tuple(j for j in jurisdictions if j in JURISDICTIONS) or ("CN",)

    disclosure = root / "INVENTION_DISCLOSURE.md"
    if not disclosure.is_file():
        problems.append(
            _problem(
                "patent-disclosure-missing",
                disclosure,
                "缺少 INVENTION_DISCLOSURE.md",
            )
        )
    else:
        text = disclosure.read_text(encoding="utf-8")
        lowered = text.casefold()
        for marker, label in (
            ("core", "core inventive concept"),
            ("supporting", "supporting features"),
            ("optional", "optional features"),
        ):
            if marker not in lowered:
                problems.append(
                    _problem(
                        "patent-disclosure-unstructured",
                        disclosure,
                        f"发明分解缺少 {label}（{marker}）段落",
                    )
                )
    claims_problems, claims_advisories = check_claims(
        root, patent_type=patent_type, jurisdictions=jurisdictions
    )
    problems.extend(claims_problems)
    advisories.extend(claims_advisories)
    art_problems, art_advisories = check_prior_art(root)
    problems.extend(art_problems)
    advisories.extend(art_advisories)
    review_problems, review_advisories = check_review(root)
    problems.extend(review_problems)
    advisories.extend(review_advisories)
    output_problems, output_advisories = check_output(root)
    problems.extend(output_problems)
    advisories.extend(output_advisories)
    return problems, advisories


def _read_section(patent_root: Path, key: str) -> str:
    path = Path(patent_root) / "specification" / f"{key}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def format_patent(patent_root: Path, jurisdiction: str) -> dict:
    """Compile `output/<J>/` from the canonical claims + specification sections."""
    root = Path(patent_root)
    if jurisdiction not in JURISDICTIONS:
        raise ValueError(
            f"未知 jurisdiction: {jurisdiction!r}，应为 {'/'.join(JURISDICTIONS)}"
        )
    claims_path = root / "CLAIMS.md"
    if not claims_path.is_file():
        raise ValueError(f"缺少 {claims_path}")
    claims_text = claims_path.read_text(encoding="utf-8").strip()
    abstract = _read_section(root, "abstract")
    order = JURISDICTION_ORDER[jurisdiction]
    description_lines: list[str] = []
    missing_sections: list[str] = []
    for key, heading in order:
        body = _read_section(root, key)
        description_lines.append(f"## {heading}")
        description_lines.append("")
        if not body:
            missing_sections.append(key)
            body = f"_TODO: {heading} 尚未撰写._"
        description_lines.append(body)
        description_lines.append("")
    folder = root / "output" / jurisdiction
    folder.mkdir(parents=True, exist_ok=True)
    claims_out = folder / "claims.md"
    description_out = folder / "description.md"
    abstract_out = folder / "abstract.md"
    save_text_atomically(
        claims_out,
        f"# {jurisdiction} Claims\n\n{claims_text}\n",
        description=f"{jurisdiction} 权利要求书",
    )
    save_text_atomically(
        description_out,
        "\n".join(description_lines).rstrip() + "\n",
        description=f"{jurisdiction} 说明书",
    )
    save_text_atomically(
        abstract_out,
        (abstract or "_TODO: 摘要尚未撰写._") + "\n",
        description=f"{jurisdiction} 摘要",
    )
    return {
        "jurisdiction": jurisdiction,
        "files": [
            claims_out.relative_to(root).as_posix(),
            description_out.relative_to(root).as_posix(),
            abstract_out.relative_to(root).as_posix(),
        ],
        "missing_sections": missing_sections,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "专利链路的确定性 gate 与 jurisdiction 编译："
            "state / 发明分解 / 权利要求结构 / 现有技术与新颖性 / "
            "审查意见 / 各司法辖区输出一致性"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check_parser = sub.add_parser("check", help="检查 patent/ 目录")
    check_parser.add_argument("--patent-root", required=True)

    state = sub.add_parser("state", help="读取或写入 PATENT_STATE.json")
    state.add_argument("--patent-root", required=True)
    state.add_argument("--phase", type=int, default=None)
    state.add_argument("--status", default=None)
    state.add_argument("--jurisdiction", default=None)
    state.add_argument("--patent-type", dest="patent_type", default=None)
    state.add_argument("--title", default="")
    state.add_argument("--claims-count", dest="claims_count", type=int, default=None)

    fmt = sub.add_parser("format", help="按司法辖区编译输出文件")
    fmt.add_argument("--patent-root", required=True)
    fmt.add_argument(
        "--jurisdiction", required=True, help="CN / US / EP / ALL"
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "check":
            problems, advisories = check(Path(args.patent_root))
            return emit(problems, advisories)
        if args.command == "state":
            root = Path(args.patent_root)
            if args.phase is None and args.status is None:
                state = read_state(root)
                if state is None:
                    return tool_error(f"没有 PATENT_STATE.json: {root}")
                print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
                return 0
            state = write_state(
                root,
                phase=args.phase or 0,
                status=args.status or "in_progress",
                jurisdiction=args.jurisdiction or "CN",
                patent_type=args.patent_type or "invention",
                invention_title=args.title,
                claims_count=args.claims_count,
            )
            print(json.dumps(state, ensure_ascii=False, sort_keys=True))
            return 0
        requested = (
            list(JURISDICTIONS)
            if args.jurisdiction.upper() == "ALL"
            else [args.jurisdiction.upper()]
        )
        results = [format_patent(Path(args.patent_root), item) for item in requested]
        print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
