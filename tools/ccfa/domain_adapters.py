"""Domain-adaptation packs for the research domains this workflow targets.

The reference (ARIS) carries the domain-specific parts of a research run inside
per-domain skills: ``idea-discovery-robot`` for robotics/embodied AI,
``comm-lit-review`` for communications, and systems/EDA framing elsewhere. That
means the *method* a domain demands ("embodiment", "channel model", "technology
node") lives in prose the agent has to re-read every run.

This module makes the domain contract machine-checkable instead: each pack
declares the venues, the search vocabulary, and the **required elements** a
research plan must cover. ``check`` fails closed when a plan silently omits one
of them, which is exactly the failure mode where a robotics plan never says
which embodiment, or a communications plan never states a channel model.

The packs are deliberately deterministic data, not model calls: a missing
channel model is a fact, not a judgment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error

SCHEMA_VERSION = 1

PLACEHOLDERS = {"", "todo", "tbd", "n/a", "na", "none", "?"}

# The packs mirror ARIS's domain skills but state the contract as data:
# every required element is a (key, what it must describe) pair.
DOMAINS: dict[str, dict] = {
    "robotics": {
        "id": "robotics",
        "label": "Robotics / embodied AI",
        "reference_skill": "idea-discovery-robot",
        "venues": ["CoRL", "RSS", "ICRA", "IROS", "RA-L"],
        "pilot_mode": "sim-first（先仿真或离线日志，真机需显式批准）",
        "search_terms": [
            "embodied AI",
            "sim2real",
            "robot learning",
            "manipulation",
            "locomotion",
            "navigation",
            "humanoid",
            "quadruped",
            "tactile sensing",
        ],
        "required_elements": [
            ("embodiment", "具体本体：机械臂 / 移动操作 / 无人机 / 人形 / 四足 / 自动驾驶"),
            ("task_family", "任务族：抓取 / 插入 / 运动 / 导航 / 操作 / 重排 / 多步规划"),
            (
                "observation_action",
                "观测与动作接口：RGB/RGB-D/触觉/语言；力矩/速度/路点/末端位姿",
            ),
            ("simulator", "仿真器或离线日志来源（sim-first 默认）"),
            ("sim2real_story", "能否留在仿真；需要真机时说明为什么以及如何回退"),
            (
                "evaluation",
                "评测：成功率 + 失败案例 + 安全违规 + 干预次数 + 延迟 + 样本效率",
            ),
        ],
    },
    "communications": {
        "id": "communications",
        "label": "Communications / networking",
        "reference_skill": "comm-lit-review",
        "venues": [
            "SIGCOMM",
            "MobiCom",
            "INFOCOM",
            "NSDI",
            "ICC",
            "GLOBECOM",
            "IEEE TWC",
            "IEEE TCOM",
        ],
        "pilot_mode": "仿真优先（ns-3/OMNeT++/MATLAB），其次 SDR 或实测",
        "search_terms": [
            "NTN",
            "LEO satellite",
            "beamforming",
            "channel estimation",
            "rate adaptation",
            "congestion control",
            "resource allocation",
            "MAC/PHY",
            "V2X",
        ],
        "required_elements": [
            ("system_model", "系统模型：拓扑、节点、链路与假设"),
            ("channel_model", "信道模型：路损 / 衰落 / 干扰 / 噪声"),
            ("protocol_baseline", "对比协议或基线，并给出标准版本"),
            ("traffic_model", "业务/流量模型与到达过程"),
            ("evaluation_stack", "仿真平台或测试床，并说明版本"),
            ("metrics", "吞吐/时延/丢包/能效/公平性，并给出置信区间或重复次数"),
        ],
    },
    "architecture-eda": {
        "id": "architecture-eda",
        "label": "Computer architecture / EDA",
        "reference_skill": "writing-systems-papers",
        "venues": ["ISCA", "MICRO", "ASPLOS", "HPCA", "DAC", "ICCAD", "DATE"],
        "pilot_mode": "仿真优先（gem5/Verilator/综合流程），流片需显式批准",
        "search_terms": [
            "accelerator",
            "RISC-V",
            "chiplet",
            "RTL",
            "placement",
            "routing",
            "power modeling",
            "design space exploration",
        ],
        "required_elements": [
            ("workload", "基准负载套件与版本（避免自选小样本）"),
            ("technology_node", "工艺节点与标准单元库"),
            ("simulator", "体系结构/EDA 仿真或综合工具及版本"),
            ("area_power_model", "面积与功耗估算模型及其标定来源"),
            ("ppa", "面积/功耗/时延指标与测量方法"),
            ("baseline", "对比基线及其配置（含面积/功耗归一化口径）"),
        ],
    },
}


def _problem(code: str, path: Path, message: str) -> Problem:
    return Problem(code, str(path), None, message)


def domain_ids() -> list[str]:
    return sorted(DOMAINS)


def get_domain(domain: str) -> dict:
    key = (domain or "").strip().casefold()
    if key not in DOMAINS:
        raise ValueError(
            f"未知领域: {domain!r}，可选 {' / '.join(domain_ids())}"
        )
    return DOMAINS[key]


def _load_plan(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"找不到 research plan: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"无法解析 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return payload


def check_plan(plan_path: Path, domain: str) -> tuple[list[Problem], list[Problem]]:
    """Fail closed when a plan omits a domain's required elements."""
    pack = get_domain(domain)
    path = Path(plan_path)
    plan = _load_plan(path)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    for key, description in pack["required_elements"]:
        value = plan.get(key)
        if value is None:
            problems.append(
                _problem(
                    "domain-element-missing",
                    path,
                    f"{pack['id']} 计划缺少必需项 {key!r}：{description}",
                )
            )
            continue
        text = str(value).strip().casefold()
        if text in PLACEHOLDERS:
            problems.append(
                _problem(
                    "domain-element-placeholder",
                    path,
                    f"{key!r} 仍是占位值 {value!r}：{description}",
                )
            )
    plan_venues = plan.get("venues")
    if isinstance(plan_venues, list) and plan_venues:
        outside = [
            str(item) for item in plan_venues if str(item) not in pack["venues"]
        ]
        if outside:
            advisories.append(
                _problem(
                    "domain-venue-off-list",
                    path,
                    f"计划里的 venue 不在 {pack['id']} 常见列表: "
                    + ", ".join(outside),
                )
            )
    return problems, advisories


def render_prompt(domain: str) -> str:
    """A deterministic prompt block downstream skills can paste in verbatim."""
    pack = get_domain(domain)
    lines = [
        f"# 领域约束：{pack['label']}（{pack['id']}）",
        "",
        f"- 参考 skill: `{pack['reference_skill']}`",
        f"- 目标 venue: {', '.join(pack['venues'])}",
        f"- pilot 策略: {pack['pilot_mode']}",
        f"- 检索词: {', '.join(pack['search_terms'])}",
        "",
        "计划必须显式覆盖以下要素（缺一即 fail closed）：",
        "",
    ]
    for key, description in pack["required_elements"]:
        lines.append(f"- `{key}`：{description}")
    lines.extend(
        [
            "",
            "不要写“本领域常见做法”这类空话；每一项都要能指到具体对象、"
            "版本或数字，否则 `domain-adapters check` 会拒绝。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="领域适配包：venue、检索词与计划必须覆盖的要素"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出可用领域")

    show = sub.add_parser("show", help="打印一个领域包")
    show.add_argument("--domain", required=True)

    check = sub.add_parser("check", help="检查 research plan 是否覆盖必需要素")
    check.add_argument("--domain", required=True)
    check.add_argument("--plan", required=True)

    prompt = sub.add_parser("prompt", help="输出可粘贴的领域约束块")
    prompt.add_argument("--domain", required=True)
    prompt.add_argument("--out", default=None)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "list":
            print(
                json.dumps(
                    [
                        {"id": key, "label": DOMAINS[key]["label"]}
                        for key in domain_ids()
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "show":
            print(
                json.dumps(
                    {**get_domain(args.domain), "schema_version": SCHEMA_VERSION},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "check":
            problems, advisories = check_plan(Path(args.plan), args.domain)
            return emit(problems, advisories)
        text = render_prompt(args.domain)
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
