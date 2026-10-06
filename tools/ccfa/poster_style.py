"""The static style gate for a poster's HTML source.

The reference implementation (ARIS ``paper-poster-html/scripts/style_check.py``)
splits its 12 design rules into a **source gate** (rules 1, 2, 3, 5, 6, 7, 8, 9,
10, 11 — pure static analysis, runnable with no browser) and a **render gate**
(rules 4 and 12, which need computed style from Playwright). The split exists so
scaffolding stays cheap: ``--no-render`` keeps the source gate live and prints a
notice that two rules were not evaluated. Exit codes are 0 pass / 1 hard failure
/ 2 usage or environment error, and a WARN never fails the gate.

This module implements the source gate for the posters this repository
generates, with the reference's rule numbering, severities, result shape and
exit codes. Implemented: 1 (colour literals only in the token block), 2 (no
inline ``style=``), 3 (component colours via ``var(--…)``), 6/7 (font pairing
and whitelist), 8 (font-size only from the ``--fs-*`` scale), 9 (token count),
and 5 (radial-tint alpha bound). Reported as SKIP with a reason: 4 and 12 (need
computed style), and 10/11 (the reference's component-library data-attribute and
inline-SVG contracts, which these generated posters do not use).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ccfa.cli import tool_error

RULE_SEVERITY = {
    1: "hard",
    2: "hard",
    3: "hard",
    4: "hard",
    5: "hard",
    6: "hard",
    7: "hard",
    8: "hard",
    9: "soft",
    10: "hard",
    11: "hard",
    12: "hard",
}
RULE_NAMES = {
    1: "colour literals only in the token block",
    2: "no inline style=",
    3: "component colours use var(--…)",
    4: "hue clustering (needs computed style)",
    5: "radial tint alpha bound",
    6: "font pairing: serif body / sans heading",
    7: "font-family whitelist",
    8: "font-size comes from the --fs-* scale",
    9: "--fs-* token count",
    10: "component data-attribute contract",
    11: "inline-SVG contract",
    12: "large dark area (needs computed style)",
}
SERIF_WHITELIST = {
    "charter", "source serif pro", "georgia", "times new roman", "serif",
}
SANS_WHITELIST = {"inter", "aptos", "helvetica neue", "arial", "sans-serif"}
MONO_WHITELIST = {"menlo", "consolas", "monospace"}
FS_TOKEN_RE = re.compile(r"--fs-(\d+)\b")
FS_VAR_REF_RE = re.compile(r"var\(\s*--fs-\d+\s*\)")
VARIANT_SUFFIX_RE = re.compile(r"\.[A-Za-z][\w-]*--[A-Za-z][\w-]*")
CALC_FS_RE = re.compile(r"calc\([^)]*var\(\s*--fs-\d+\s*\)[^)]*\)")
COLOR_LITERAL_RE = re.compile(
    r"(?:\#[0-9a-fA-F]{3,8}\b)"
    r"|(?:\brgba?\s*\([^)]*\))"
    r"|(?:\bhsla?\s*\([^)]*\))"
)
FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;{}]+)", re.IGNORECASE)
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;{}]+)", re.IGNORECASE)
COLOR_PROPERTY_RE = re.compile(
    r"(?:^|[;{\s])(?:color|background|background-color|border-color)"
    r"\s*:\s*([^;{}]+)",
    re.IGNORECASE,
)
STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
INLINE_STYLE_RE = re.compile(r"<[a-zA-Z][^>]*\sstyle\s*=", re.IGNORECASE)
RADIAL_RE = re.compile(r"radial-gradient\s*\(([^;{}]*?)\)", re.IGNORECASE)
ALPHA_RE = re.compile(r"rgba?\(\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,"
                      r"\s*([\d.]+)\s*\)", re.IGNORECASE)
TOKEN_START = "/* ===== DESIGN TOKENS ===== */"
TOKEN_END = "/* ===== END DESIGN TOKENS ===== */"
MAX_FS_TOKENS = 9
RADIAL_ALPHA_MAX = 0.06


@dataclass
class RuleResult:
    rule: int
    severity: str
    name: str
    status: str = "pass"
    detail: str = ""
    offenders: list[str] = field(default_factory=list)

    def fail(self, detail: str, offenders: list[str] | None = None) -> None:
        self.status = "fail"
        self.detail = detail
        self.offenders = offenders or []

    def warn(self, detail: str) -> None:
        self.status = "warn"
        self.detail = detail

    def skip(self, detail: str) -> None:
        self.status = "skip"
        self.detail = detail

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "offenders": self.offenders,
        }


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _iter_css_rules(css: str):
    """Yield ``(selector, body)`` for top-level rules, recursing into at-rules."""
    index = 0
    while index < len(css):
        brace = css.find("{", index)
        if brace < 0:
            return
        selector = css[index:brace].strip()
        depth = 1
        cursor = brace + 1
        while cursor < len(css) and depth:
            if css[cursor] == "{":
                depth += 1
            elif css[cursor] == "}":
                depth -= 1
            cursor += 1
        body = css[brace + 1 : cursor - 1]
        if selector.startswith("@"):
            yield from _iter_css_rules(body)
        else:
            yield selector, body
        index = cursor


def _families(value: str) -> list[str]:
    out = []
    for raw in value.split(","):
        family = raw.strip().strip('"').strip("'").lower()
        if family:
            out.append(family)
    return out


def run_source_rules(html_text: str) -> list[RuleResult]:
    """Run the static rules; render-only rules come back as SKIP."""
    results: dict[int, RuleResult] = {
        rule: RuleResult(rule, RULE_SEVERITY[rule], RULE_NAMES[rule])
        for rule in RULE_SEVERITY
    }
    styles = STYLE_BLOCK_RE.findall(html_text)
    raw_css = "\n".join(styles)
    start = raw_css.find(TOKEN_START)
    end = raw_css.find(TOKEN_END)
    token_block = None
    if start >= 0 and end > start:
        token_block = raw_css[start + len(TOKEN_START) : end]

    # Rule 1 — colour literals only inside the token block.
    r1 = results[1]
    if token_block is None:
        r1.fail(
            "找不到 design-token 块：需要注释对 "
            f"{TOKEN_START} … {TOKEN_END}；否则无法判断颜色字面量该放哪里"
        )
        css_scan = raw_css
    else:
        css_scan = raw_css[:start] + " " * (end + len(TOKEN_END) - start) + raw_css[
            end + len(TOKEN_END) :
        ]
        css_scan = _strip_css_comments(css_scan)
        offenders = sorted(set(m.group(0) for m in COLOR_LITERAL_RE.finditer(css_scan)))
        if offenders:
            r1.fail(
                f"token 块之外出现颜色字面量: {', '.join(offenders[:8])}",
                offenders,
            )

    # Rule 2 — no inline style=.
    r2 = results[2]
    inline = INLINE_STYLE_RE.findall(html_text)
    if inline:
        r2.fail(f"发现 {len(inline)} 处内联 style=；请改用类")

    # Rule 3 — component colours must use var(--…).
    r3 = results[3]
    offenders3 = []
    for selector, body in _iter_css_rules(_strip_css_comments(raw_css)):
        if selector.strip().startswith(":root"):
            continue
        for match in COLOR_PROPERTY_RE.finditer(body):
            if COLOR_LITERAL_RE.search(match.group(1)):
                offenders3.append(f"{selector.strip()} {{ {match.group(0).strip()} }}")
    if offenders3:
        r3.fail(
            f"{len(offenders3)} 处组件颜色用了字面量；应引用 var(--…)",
            offenders3,
        )

    # Rule 5 — radial tint alpha bound.
    r5 = results[5]
    for match in RADIAL_RE.finditer(raw_css):
        for alpha in ALPHA_RE.findall(match.group(1)):
            if float(alpha) > RADIAL_ALPHA_MAX:
                r5.fail(
                    f"radial-gradient 的 alpha {alpha} 超过上限 "
                    f"{RADIAL_ALPHA_MAX}"
                )
                break

    # Rules 6 and 7 — font pairing and whitelist, read from the token block.
    scope = token_block if token_block is not None else raw_css
    definitions = {}
    for key in ("serif", "sans", "mono"):
        match = re.search(rf"--font-{key}\s*:\s*([^;{{}}]+)", scope, re.IGNORECASE)
        definitions[key] = _families(match.group(1)) if match else None
    whitelists = {
        "serif": SERIF_WHITELIST,
        "sans": SANS_WHITELIST,
        "mono": MONO_WHITELIST,
    }
    problems7 = []
    for key, families in definitions.items():
        if families is None:
            continue
        bad = [family for family in families if family not in whitelists[key]]
        if bad:
            problems7.append(f"--font-{key} 含非白名单字体: {', '.join(bad)}")
    if problems7:
        results[7].fail("；".join(problems7))
    if definitions["serif"] is None or definitions["sans"] is None:
        results[6].warn("token 块里没有同时定义 --font-serif 与 --font-sans")

    # Rule 8 — font-size must come from the scale.
    r8 = results[8]
    offenders8 = []
    for selector, body in _iter_css_rules(_strip_css_comments(raw_css)):
        match = FONT_SIZE_RE.search(body)
        if not match:
            continue
        value = match.group(1).strip()
        if FS_VAR_REF_RE.fullmatch(value):
            continue
        if CALC_FS_RE.fullmatch(value) and VARIANT_SUFFIX_RE.search(selector):
            continue
        offenders8.append(f"{selector.strip()} {{ font-size: {value} }}")
    if offenders8:
        r8.fail(
            f"{len(offenders8)} 处 font-size 不在 --fs-* 尺度上",
            offenders8,
        )

    # Rule 9 — token count.
    tokens = {match.group(1) for match in FS_TOKEN_RE.finditer(scope)}
    if len(tokens) > MAX_FS_TOKENS:
        results[9].warn(
            f"定义了 {len(tokens)} 个 --fs-* token，超过 {MAX_FS_TOKENS} 个档位"
        )

    # Render-only and component-contract rules are reported, not pretended.
    results[4].skip("需要 computed style（Playwright/CDP）；本机无此链路")
    results[12].skip("需要 computed style（Playwright/CDP）；本机无此链路")
    results[10].skip("本仓库生成的 poster 不使用参考实现的组件 data-attribute 契约")
    results[11].skip("本仓库生成的 poster 不含内联 SVG")
    return [results[rule] for rule in sorted(results)]


def check(path: Path) -> tuple[list[RuleResult], dict]:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"找不到 poster HTML: {path}")
    text = path.read_text(encoding="utf-8")
    results = run_source_rules(text)
    hard = [r for r in results if r.status == "fail" and r.severity == "hard"]
    report = {
        "schema_version": 1,
        "skill": "poster-style",
        "source": path.as_posix(),
        "overall": "fail" if hard else "pass",
        "hard_failures": len(hard),
        "warnings": sum(1 for r in results if r.status == "warn"),
        "skipped_rules": [r.rule for r in results if r.status == "skip"],
        "rules": [r.as_dict() for r in results],
    }
    return results, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "poster HTML 的静态风格门（参考实现 12 条规则里的源码子集）："
            "颜色字面量只能在 token 块、不许内联 style、组件颜色走 var(--…)、"
            "字体白名单、font-size 走 --fs-* 尺度、token 档位数；"
            "需要 computed style 的规则明确标记为 skip。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="检查 poster.html")
    run.add_argument("--html", required=True)
    run.add_argument("--json", default=None, help="把完整报告写到这个路径")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        results, report = check(Path(args.html))
        if args.json:
            Path(args.json).write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(
            json.dumps(
                {
                    "overall": report["overall"],
                    "hard_failures": report["hard_failures"],
                    "warnings": report["warnings"],
                    "skipped_rules": report["skipped_rules"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        for result in results:
            if result.status in ("fail", "warn"):
                print(
                    f"rule {result.rule} [{result.status}] "
                    f"{result.name}: {result.detail}",
                    file=sys.stderr,
                )
        for rule in report["skipped_rules"]:
            detail = next(r.detail for r in results if r.rule == rule)
            print(f"rule {rule} [skip] {detail}", file=sys.stderr)
        return 1 if report["hard_failures"] else 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
