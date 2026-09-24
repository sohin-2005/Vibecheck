"""Edit-matched attribution: which of a commit's added lines did the AI actually write?

A line counts as AI-written when the same text (ignoring surrounding whitespace) appears in
code a linked session's edit tools wrote to that file. Trivial lines such as ``}`` or blank
lines are ignored on both sides, since they would match anything.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

_HEADER = re.compile(r"^([0-9a-f]{40}) \d+ \d+")
_ALNUM = re.compile(r"[A-Za-z0-9]")


def normalize(line: str) -> str | None:
    s = line.strip()
    return s if len("".join(s.split())) >= 3 and _ALNUM.search(s) else None


def pool(texts: Iterable[str]) -> Counter[str]:
    """Multiset of meaningful lines across several pieces of AI-written code."""
    out: Counter[str] = Counter()
    for t in texts:
        out.update(n for line in t.splitlines() if (n := normalize(line)))
    return out


def match_ai(added: Iterable[str], ai_pool: Counter[str]) -> Counter[str]:
    """The added lines (as a multiset) that the AI pool accounts for."""
    added_counts = Counter(n for line in added if (n := normalize(line)))
    return added_counts & ai_pool


def added_lines_from_diff(diff: str) -> list[str]:
    """``+`` lines from ``git show -U0`` output, without the ``+++`` file headers."""
    return [
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    ]


def blame_lines(porcelain: str) -> list[tuple[str, str]]:
    """(commit sha, line content) for every line of ``git blame --porcelain`` output."""
    out = []
    current = None
    for line in porcelain.splitlines():
        if line.startswith("\t"):
            if current:
                out.append((current, line[1:]))
            continue
        m = _HEADER.match(line)
        if m:
            current = m.group(1)
    return out
