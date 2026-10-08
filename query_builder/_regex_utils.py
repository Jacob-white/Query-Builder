"""Linear-time helpers that replace regexes with polynomial backtracking.

Each helper reproduces the match semantics of the regular expression named in its
docstring exactly (verified by differential tests in ``tests/test_regex_linear_*.py``)
while scanning the input a bounded number of times.
"""

from __future__ import annotations


def strip_block_comments(text: str) -> str:
    """Equivalent of ``re.sub(r"/\\*[\\s\\S]*?\\*/", "", text)`` in linear time.

    The regex retries from every ``/*`` when no ``*/`` follows, which is quadratic on
    inputs such as ``"/*" * n``.  Once one ``/*`` has no closing ``*/`` no later one can.
    """
    parts: list[str] = []
    pos = 0
    while True:
        start = text.find("/*", pos)
        if start < 0:
            break
        end = text.find("*/", start + 2)
        if end < 0:
            break
        parts.append(text[pos:start])
        pos = end + 2
    parts.append(text[pos:])
    return "".join(parts)


def strip_trailing_semicolons(text: str) -> str:
    """Equivalent of ``re.sub(r";+\\s*$", "", text)`` in linear time.

    The regex is quadratic on ``";" * n + "x"`` because every ``;`` is a retry start.
    """
    stripped = text.rstrip()
    without = stripped.rstrip(";")
    if len(without) == len(stripped):
        return text
    return without
