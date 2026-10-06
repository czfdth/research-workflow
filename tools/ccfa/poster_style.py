"""The style gate for a poster's HTML source, split into a source and a render half.

The reference implementation (ARIS ``paper-poster-html/scripts/style_check.py``)
splits its 12 design rules across two gates:

* **Source gate** (rules 1, 2, 3, 5, 6, 7, 8, 9, 10, 11) — pure static analysis.
  Cheap, deterministic, runnable with no browser; this is what scaffolding relies
  on. Implemented here: 1 (colour literals only in the token block), 2 (no inline
  ``style=``), 3 (component colours via ``var(--…)``), 5 (radial tint alpha
  bound), 6/7 (font pairing and whitelist), 8 (font-size only from the ``--fs-*``
  scale), 9 (token-count warning). Reported as SKIP with a reason: 10 and 11 (the
  reference's component-library ``data-*`` and inline-SVG contracts, which these
  generated posters do not use).
* **Render gate** (rules 4 and 12) — needs computed style, so it print-emulates
  the poster with Playwright at the poster's own ``@page`` viewport and reads
  every element's computed colours. Rule 4 fails when more than two non-neutral
  hue clusters appear, or when a cluster drifts away from the ``--accent`` /
  ``--gold`` palette centres; rule 12 warns when dark backgrounds cover more
  than 8% of the poster.

``--no-render`` keeps the source gate live and marks rules 4 and 12 SKIPPED with
a printed notice. Exit codes are 0 pass / 1 hard failure / 2 usage or environment
error, and a WARN never fails the gate — matching the reference.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ccfa.cli import tool_error
from ccfa.talk_gates import canvas_from_html

RULE_SEVERITY = {
    1: "hard",
    2: "hard",
    3: "hard",
    4: "hard",
    5: "hard",
    6: "hard",
    7: "hard",
    8: "hard",
    9: "warn",
    10: "hard",
    11: "hard",
    12: "warn",
}
RULE_NAMES = {
    1: "colour literals only in the token block",
    2: "no inline style=",
    3: "component colours use var(--…)",
    4: "at most 2 non-neutral hue clusters on the palette (rendered)",
    5: "radial tint alpha bound",
    6: "font pairing: serif body / sans heading",
    7: "font-family whitelist",
    8: "font-size comes from the --fs-* scale",
    9: "--fs-* token count",
    10: "component data-attribute contract",
    11: "inline-SVG contract",
    12: "large dark area (rendered)",
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

# Render-gate constants, transcribed from the reference style_check.py.
CSS_PX_PER_IN = 96.0
CLUSTER_RADIUS_DEG = 18.0
CENTER_TOL_DEG = 22.0
NONNEUTRAL_ALPHA = 0.10
NONNEUTRAL_SAT = 0.18
CHROMA_FLOOR = NONNEUTRAL_SAT * 0.56  # ~0.10: near-white/near-black stay neutral
DARK_LIGHTNESS = 0.18
DARK_ALPHA_MIN = 0.5
DARK_AREA_FRAC = 0.08
DEFAULT_TIMEOUT_MS = 15000
# Edge and Chrome ship with Windows and are already installed on the CI runner,
# so the gate drives an existing browser instead of downloading Chromium.
BROWSER_CHANNELS = ("msedge", "chrome")


class RenderUnavailable(RuntimeError):
    """The render gate cannot run here (no Playwright, no browser, no @page).

    Raised instead of silently passing: an environment that cannot evaluate
    rules 4 and 12 must be reported as a usage/environment error (exit 2), the
    same contract the reference follows.
    """


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


def token_block_of(html_text: str) -> str | None:
    """Return the text between the canonical DESIGN TOKENS comment pair.

    The token block is the one place colour literals are allowed, so both the
    source gate (rule 1) and rule 4's palette-centre fallback need to find it
    through the same markers.
    """
    raw_css = "\n".join(STYLE_BLOCK_RE.findall(html_text))
    start = raw_css.find(TOKEN_START)
    end = raw_css.find(TOKEN_END)
    if start < 0 or end <= start:
        return None
    return raw_css[start + len(TOKEN_START) : end]


def run_source_rules(html_text: str) -> list[RuleResult]:
    """Run the static rules; render-only rules come back as SKIP."""
    results: dict[int, RuleResult] = {
        rule: RuleResult(rule, RULE_SEVERITY[rule], RULE_NAMES[rule])
        for rule in RULE_SEVERITY
    }
    raw_css = "\n".join(STYLE_BLOCK_RE.findall(html_text))
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
    results[4].skip("需要 computed style：用 Playwright 渲染（默认）或加 --no-render 跳过")
    results[12].skip("需要 computed style：用 Playwright 渲染（默认）或加 --no-render 跳过")
    results[10].skip("本仓库生成的 poster 不使用参考实现的组件 data-attribute 契约")
    results[11].skip("本仓库生成的 poster 不含内联 SVG")
    return [results[rule] for rule in sorted(results)]


# ---------------------------------------------------------------------------
# Hue-cluster helpers (rule 4) — pure functions, unit-testable without a browser.
# ---------------------------------------------------------------------------


def _hue_of_rgb(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Return (hue_deg, saturation, lightness).

    ``colorsys.rgb_to_hls`` returns ``(h, l, s)`` — the order matters, so the
    return is unpacked as H, L, S and reordered here.
    """
    hue, light, sat = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return hue * 360.0, sat, light


def _hue_dist(a: float, b: float) -> float:
    """Circular distance between two hue angles in degrees (0..180)."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _circular_mean(angles: list[float]) -> float:
    """Mean of angles on the unit circle, returned in [0,360)."""
    x = sum(math.cos(math.radians(a)) for a in angles)
    y = sum(math.sin(math.radians(a)) for a in angles)
    return math.degrees(math.atan2(y, x)) % 360.0


def cluster_hues(hues: list[float], radius_deg: float = CLUSTER_RADIUS_DEG) -> list[float]:
    """Greedy 1-D circular clustering of hue angles.

    Sort, sweep once, and start a new cluster whenever the next hue is more
    than ``radius_deg`` (circular) from the current cluster's *seed*; then merge
    the wrap-around case (350 deg and 5 deg are one hue family). Seeding on the
    first member keeps a long slow drift from collapsing into one giant cluster.
    """
    if not hues:
        return []
    ordered = sorted(hues)
    clusters: list[list[float]] = [[ordered[0]]]
    for hue in ordered[1:]:
        seed = clusters[-1][0]
        if _hue_dist(hue, seed) <= radius_deg:
            clusters[-1].append(hue)
        else:
            clusters.append([hue])
    if len(clusters) > 1:
        if _hue_dist(clusters[-1][-1], clusters[0][0]) <= radius_deg:
            clusters[0] = clusters[-1] + clusters[0]
            clusters.pop()
    return [_circular_mean(cluster) for cluster in clusters]


def _hue_from_hex(hex_str: str | None) -> float | None:
    """Hue (degrees) of a ``#RGB`` / ``#RRGGBB`` literal, or None if unparsable."""
    if not hex_str or not hex_str.startswith("#"):
        return None
    digits = hex_str[1:]
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    if len(digits) not in (6, 8):
        return None
    try:
        r, g, b = int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    except ValueError:
        return None
    hue, _sat, _light = _hue_of_rgb(r, g, b)
    return hue


def _parse_rgba_str(value: str) -> tuple[int, int, int, float] | None:
    """Parse a computed ``rgb()/rgba()`` string into (r, g, b, a).

    ``transparent`` resolves to ``rgba(0, 0, 0, 0)``, which parses to alpha 0 and
    is then dropped by the caller's alpha floor — so this only returns None for
    genuinely unexpected formats.
    """
    match = re.search(
        r"rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)"
        r"(?:[ ,/]+([\d.]+%?))?\s*\)",
        value or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    red, green, blue = (
        int(float(match.group(1))),
        int(float(match.group(2))),
        int(float(match.group(3))),
    )
    raw_alpha = match.group(4)
    if raw_alpha is None:
        alpha = 1.0
    elif raw_alpha.endswith("%"):
        alpha = float(raw_alpha[:-1]) / 100.0
    else:
        alpha = float(raw_alpha)
    return red, green, blue, alpha


def resolve_hue_centers(
    tokens_path: Path | None = None, token_block_text: str | None = None
) -> dict[str, float]:
    """Resolve the accent/gold hue centres rule 4 checks against.

    Priority: a ``--tokens`` JSON ``hue_centers`` block, then its ``accent`` /
    ``gold`` base hexes, then ``--accent`` / ``--gold`` literals parsed out of
    the poster's own :root token block (which ``ccfa.poster_html`` always emits).
    """
    centers: dict[str, float] = {}
    if tokens_path is not None:
        try:
            doc = json.loads(Path(tokens_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = {}
        if not isinstance(doc, dict):
            doc = {}
        declared = doc.get("hue_centers") or {}
        if isinstance(declared, dict):
            for key in ("accent", "gold"):
                if key in declared:
                    try:
                        centers[key] = float(declared[key]) % 360.0
                    except (TypeError, ValueError):
                        pass
        for key in ("accent", "gold"):
            if key in centers:
                continue
            base = doc.get(key)
            base = base.get("base") if isinstance(base, dict) else None
            hue = _hue_from_hex(base) if isinstance(base, str) else None
            if hue is not None:
                centers[key] = hue
    if token_block_text:
        for key, var in (("accent", "--accent"), ("gold", "--gold")):
            if key in centers:
                continue
            match = re.search(
                re.escape(var) + r"\s*:\s*(#[0-9a-fA-F]{3,8})", token_block_text
            )
            if match:
                hue = _hue_from_hex(match.group(1))
                if hue is not None:
                    centers[key] = hue
    return centers


# ---------------------------------------------------------------------------
# The render gate (rules 4 and 12).
# ---------------------------------------------------------------------------

# JS that collects computed colours for every element outside an exempt subtree,
# plus its on-screen area and background lightness (rule 12). Ported from the
# reference style_check.py; exempt subtrees are <img>, [data-color-exempt],
# [data-source="paper"], and QR blocks ([data-component="qr"] / .qr-block).
_RENDER_JS = r"""
() => {
  const isExempt = (el) => {
    let n = el;
    while (n && n.nodeType === 1) {
      const tag = n.tagName ? n.tagName.toLowerCase() : '';
      if (tag === 'img') return true;
      if (n.hasAttribute && n.hasAttribute('data-color-exempt')) return true;
      if (n.getAttribute && n.getAttribute('data-source') === 'paper')
        return true;
      const comp = n.getAttribute && n.getAttribute('data-component');
      if (comp === 'qr') return true;
      if (n.classList && n.classList.contains('qr-block')) return true;
      n = n.parentElement;
    }
    return false;
  };

  const poster = document.querySelector('[data-measure-role="poster"]')
               || document.querySelector('.poster')
               || document.body;
  const pr = poster.getBoundingClientRect();
  const posterArea = Math.max(1, pr.width * pr.height);

  const colors = [];
  let darkArea = 0;

  function parseRGBA(s) {
    const mm = /rgba?\(([^)]+)\)/i.exec(s || '');
    if (!mm) return null;
    const p = mm[1].split(/[ ,\/]+/).filter(Boolean);
    if (p.length < 3) return null;
    return {
      r: parseFloat(p[0]), g: parseFloat(p[1]), b: parseFloat(p[2]),
      a: p.length >= 4 ? parseFloat(p[3]) : 1,
    };
  }
  function bgLightness(s) {
    const m = parseRGBA(s);
    if (!m || m.a < 0.5) return null;
    const r = m.r / 255, g = m.g / 255, b = m.b / 255;
    return (Math.max(r, g, b) + Math.min(r, g, b)) / 2;
  }

  const all = Array.from(document.querySelectorAll('*'));
  for (const el of all) {
    const cs = window.getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const onscreen = r.width > 0 && r.height > 0;

    if (onscreen) {
      const L = bgLightness(cs.backgroundColor);
      if (L !== null && L < 0.18) {
        const w = Math.max(0, Math.min(r.right, pr.right)
                              - Math.max(r.left, pr.left));
        const h = Math.max(0, Math.min(r.bottom, pr.bottom)
                              - Math.max(r.top, pr.top));
        darkArea += w * h;
      }
    }

    if (isExempt(el)) continue;
    colors.push({prop: 'color', rgba: cs.color});
    colors.push({prop: 'background-color', rgba: cs.backgroundColor});
    colors.push({prop: 'border-top-color', rgba: cs.borderTopColor});
    colors.push({prop: 'border-right-color', rgba: cs.borderRightColor});
    colors.push({prop: 'border-bottom-color', rgba: cs.borderBottomColor});
    colors.push({prop: 'border-left-color', rgba: cs.borderLeftColor});
    colors.push({prop: 'fill', rgba: cs.fill});
    colors.push({prop: 'stroke', rgba: cs.stroke});
  }

  return {colors, posterArea, darkArea};
}
"""


def evaluate_render_metrics(
    metrics: dict,
    hue_centers: dict[str, float],
    *,
    cluster_radius_deg: float = CLUSTER_RADIUS_DEG,
    center_tol_deg: float = CENTER_TOL_DEG,
    nonneutral_alpha: float = NONNEUTRAL_ALPHA,
    nonneutral_sat: float = NONNEUTRAL_SAT,
    dark_area_frac: float = DARK_AREA_FRAC,
) -> list[RuleResult]:
    """Turn a rendered-colour payload into the rule 4 and rule 12 verdicts.

    Pure, so the treshold logic is unit-testable without a browser. Rule 4 is
    hard (three hue families, or a cluster off the palette, is a real design
    break); rule 12 is a warning, matching the reference.
    """
    r4 = RuleResult(4, RULE_SEVERITY[4], RULE_NAMES[4])
    hues: list[float] = []
    for entry in metrics.get("colors") or []:
        parsed = _parse_rgba_str(entry.get("rgba", ""))
        if parsed is None:
            continue
        red, green, blue, alpha = parsed
        if alpha < nonneutral_alpha:
            continue
        hue, sat, light = _hue_of_rgb(red, green, blue)
        # Perceptual chroma, not raw HSL saturation: saturation blows up near
        # white/black (a warm paper tone reads S=0.25 at L=0.95 yet is visually
        # neutral). Discounting by lightness extremity keeps those neutral.
        chroma = sat * (1.0 - abs(2.0 * light - 1.0))
        if chroma < nonneutral_sat * 0.56:
            continue
        hues.append(hue)

    centers = cluster_hues(hues, radius_deg=cluster_radius_deg)
    targets = [
        hue
        for hue in (hue_centers.get("accent"), hue_centers.get("gold"))
        if hue is not None
    ]
    problems: list[str] = []
    if len(centers) > 2:
        problems.append(
            f"{len(centers)} 个非中性色相聚类 "
            f"({', '.join('%.0f°' % c for c in centers)})；最多允许 2 个"
            "（accent + gold）"
        )
    if targets:
        for center in centers:
            nearest = min(_hue_dist(center, target) for target in targets)
            if nearest > center_tol_deg:
                problems.append(
                    f"{center:.0f}° 的色相聚类偏离最近的调色板中心 "
                    f"{nearest:.0f}°（中心 "
                    f"{'/'.join('%.0f°' % t for t in targets)}，"
                    f"容差 {center_tol_deg:.0f}°）"
                )
    else:
        problems.append(
            "拿不到 accent/gold 色相中心（在 :root 里定义 --accent/--gold，"
            "或用 --tokens 传 hue_centers）；无法核对色相是否落在调色板上"
        )
    if problems:
        r4.fail("；".join(problems[:4]))
    else:
        r4.detail = (
            f"{len(centers)} 个色相聚类，全部落在调色板 "
            f"{center_tol_deg:.0f}° 容差内"
        )

    r12 = RuleResult(12, RULE_SEVERITY[12], RULE_NAMES[12])
    poster_area = float(metrics.get("posterArea") or 0.0)
    dark_area = float(metrics.get("darkArea") or 0.0)
    frac = dark_area / poster_area if poster_area else 0.0
    if frac > dark_area_frac:
        # Nested boxes (html + body with the same background) are summed, so the
        # fraction can exceed 100%; the reference does the same.
        overlap = "；嵌套/重叠的深色盒子会被累加，所以可能 >100%" if frac > 1.0 else ""
        r12.warn(
            f"深色（L<{DARK_LIGHTNESS}）背景覆盖了海报的 {frac * 100:.1f}%"
            f"（超过 {dark_area_frac * 100:.0f}% 阈值）；大块深色读起来像"
            f"“花哨海报”，建议调亮或缩小{overlap}"
        )
    else:
        r12.detail = (
            f"深色面积 = 海报的 {frac * 100:.1f}%（<= {dark_area_frac * 100:.0f}%）"
        )
    return [r4, r12]


def _launch_browser(playwright, channels=BROWSER_CHANNELS):
    """Launch the first usable browser: an installed channel, then the bundle."""
    errors: list[str] = []
    for channel in channels:
        try:
            browser = playwright.chromium.launch(
                channel=channel, headless=True, args=["--no-sandbox", "--disable-gpu"]
            )
            return browser, channel
        except Exception as exc:  # playwright raises its own Error subclasses
            errors.append(f"{channel}: {type(exc).__name__}")
    try:
        browser = playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-gpu"]
        )
        return browser, "chromium"
    except Exception as exc:
        errors.append(f"chromium: {type(exc).__name__}")
    raise RenderUnavailable(
        "无法启动无头浏览器（" + "；".join(errors) + "）。装一个 Edge/Chrome，"
        "或运行 `python -m playwright install chromium`；"
        "也可以加 --no-render 只跑源码 gate（规则 4/12 会被标为 skip）。"
    )


def collect_render_metrics(
    html_path: Path,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    channels=BROWSER_CHANNELS,
) -> dict:
    """Print-emulate the poster and read computed colours; raises on no browser."""
    html_path = Path(html_path)
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderUnavailable(
            "没有安装 playwright，跑不了渲染 gate（规则 4/12）。"
            "装：`pip install playwright` + `playwright install chromium`；"
            "或加 --no-render。"
        ) from exc
    try:
        width_in, height_in = canvas_from_html(html_path)
    except ValueError as exc:
        raise RenderUnavailable(
            f"渲染 gate 需要 poster HTML 自带 @page size：{exc}；"
            "加 --no-render 可只跑源码 gate"
        ) from exc
    viewport = {
        "width": max(1, int(round(width_in * CSS_PX_PER_IN))),
        "height": max(1, int(round(height_in * CSS_PX_PER_IN))),
    }
    uri = html_path.resolve().as_uri()
    with sync_playwright() as playwright:
        browser, engine = _launch_browser(playwright, channels)
        try:
            context = browser.new_context(viewport=viewport)
            page = context.new_page()
            page.emulate_media(media="print")
            page.set_viewport_size(viewport)
            try:
                page.goto(uri, wait_until="networkidle", timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise RenderUnavailable(
                    f"页面在 {timeout_ms} ms 内没到 network-idle；通常是有"
                    "外部资源被拦截。把资源内联后重试，或加 --no-render。"
                ) from exc
            metrics = page.evaluate(_RENDER_JS)
        finally:
            browser.close()
    if not isinstance(metrics, dict):
        raise RenderUnavailable("渲染 gate：页面脚本没有返回度量数据")
    metrics["engine"] = engine
    metrics["viewport_px"] = [viewport["width"], viewport["height"]]
    return metrics


def run_render_gate(
    html_path: Path,
    hue_centers: dict[str, float],
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    channels=BROWSER_CHANNELS,
) -> tuple[list[RuleResult], dict]:
    """Run rules 4 and 12 against a real render; returns (results, metrics)."""
    metrics = collect_render_metrics(
        html_path, timeout_ms=timeout_ms, channels=channels
    )
    return evaluate_render_metrics(metrics, hue_centers), metrics


def check(
    path: Path,
    *,
    render: bool = False,
    tokens: Path | None = None,
    hue_centers: dict[str, float] | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> tuple[list[RuleResult], dict]:
    """Run the source gate, and (when ``render``) the render gate for rules 4/12.

    ``render=False`` is the programmatic default so callers must opt in to the
    browser; the CLI defaults to rendering and uses ``--no-render`` to opt out.
    Raises :class:`RenderUnavailable` if the render gate cannot run.
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"找不到 poster HTML: {path}")
    text = path.read_text(encoding="utf-8")
    results = run_source_rules(text)
    if not render:
        render_state: dict = {
            "requested": False,
            "evaluated": False,
            "engine": None,
            "reason": "--no-render：规则 4 与 12 未评估",
        }
    else:
        centers = (
            hue_centers
            if hue_centers is not None
            else resolve_hue_centers(tokens, token_block_of(text))
        )
        rendered, metrics = run_render_gate(
            path, centers, timeout_ms=timeout_ms
        )
        by_rule = {item.rule: item for item in results}
        for item in rendered:
            by_rule[item.rule] = item
        results = [by_rule[rule] for rule in sorted(by_rule)]
        render_state = {
            "requested": True,
            "evaluated": True,
            "engine": metrics.get("engine"),
            "viewport_px": metrics.get("viewport_px"),
            "hue_centers": centers,
            "reason": "",
        }
    hard = [r for r in results if r.status == "fail" and r.severity == "hard"]
    report = {
        "schema_version": 1,
        "skill": "poster-style",
        "source": path.as_posix(),
        "overall": "fail" if hard else "pass",
        "hard_failures": len(hard),
        "warnings": sum(1 for r in results if r.status == "warn"),
        "skipped_rules": [r.rule for r in results if r.status == "skip"],
        "render": render_state,
        "rules": [r.as_dict() for r in results],
    }
    return results, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "poster HTML 的风格门（参考实现 12 条规则）：源码 gate 检查颜色字面量"
            "只能在 token 块、不许内联 style、组件颜色走 var(--…)、字体白名单、"
            "font-size 走 --fs-* 尺度、token 档位数；渲染 gate 用 Playwright 取"
            "computed style 后跑规则 4（色相聚类）与 12（大面积深色）。"
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="检查 poster.html")
    run.add_argument("--html", required=True)
    run.add_argument(
        "--tokens",
        default=None,
        help="tokens JSON；其中的 hue_centers/accent/gold 驱动规则 4（默认从 token 块解析）",
    )
    run.add_argument("--json", default=None, help="把完整报告写到这个路径")
    run.add_argument(
        "--no-render",
        action="store_true",
        help="跳过渲染 gate；规则 4 与 12 标为 skip，源码 gate 仍然独立判定",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        results, report = check(
            Path(args.html),
            render=not args.no_render,
            tokens=Path(args.tokens) if args.tokens else None,
        )
    except RenderUnavailable as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
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
                "render": report["render"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.no_render:
        print(
            "[poster-style] 注意：--no-render 只跑源码 gate；"
            "规则 4（非中性色相聚类）与规则 12（大面积深色）未评估。",
            file=sys.stderr,
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


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
