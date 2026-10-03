"""Strip LaTeX line comments, respecting escaped percent signs.

A percent begins a comment only when the backslashes immediately before it
are even in number: an odd count means the last backslash escapes it.
Checking only the previous character is wrong for a line containing a
literal backslash, where the percent that follows is a real comment.
"""

from __future__ import annotations


def strip_comment(line: str) -> str:
    for index, char in enumerate(line):
        if char != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line
