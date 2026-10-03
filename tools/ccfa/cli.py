"""Shared exit-code and output contract for paper-template tools.

Machine-readable JSON goes to stdout; the human summary goes to stderr.
Exit codes: 0 clean, 1 problems found, 2 tool error. They are never merged.
"""

from __future__ import annotations

import json
import sys
from typing import NamedTuple


class Problem(NamedTuple):
    code: str
    path: str
    line: int | None
    message: str


def _location(problem: Problem) -> str:
    if problem.line is None:
        return f"{problem.path}:"
    return f"{problem.path}:{problem.line}"


def render_report(problems: list[Problem], advisories: list[Problem]) -> dict:
    return {
        "problems": [dict(problem._asdict()) for problem in problems],
        "advisories": [dict(advisory._asdict()) for advisory in advisories],
        "problem_count": len(problems),
    }


def emit(problems: list[Problem], advisories: list[Problem] | None = None) -> int:
    advisories = advisories or []
    print(json.dumps(render_report(problems, advisories), ensure_ascii=False))
    for problem in problems:
        print(f"{_location(problem)} {problem.code}: {problem.message}", file=sys.stderr)
    for advisory in advisories:
        print(f"{_location(advisory)} {advisory.code}: {advisory.message}", file=sys.stderr)
    return 1 if problems else 0


def tool_error(message: str) -> int:
    print(f"工具错误: {message}", file=sys.stderr)
    return 2
