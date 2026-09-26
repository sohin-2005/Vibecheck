"""Struggle signals for the session in progress, read straight from its log file."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from vibecheck.ingest.parser import EDIT_TOOLS, Event, ToolUse, strip_pasted
from vibecheck.mcp.render import basename, bullets, short
from vibecheck.metrics.struggle import EDIT_ALLOWANCE, compute_signals, correction_text, raw_score

STRUGGLE_SCORE = 6.0  # weighted raw score that counts as "signs of struggle"
HOT_FILE_EDITS = 5  # more edits than this to one file always counts as struggling
LONG_SESSION = 8  # prompts; matches the digest's "long back-and-forth"
SHELL_TOOLS = {"Bash", "PowerShell"}


@dataclass
class LiveSession:
    prompts: list[str] = field(default_factory=list)
    interrupts: int = 0
    failures: list[tuple[str, str | None]] = field(default_factory=list)  # (tool, what)
    edit_paths: list[str] = field(default_factory=list)


@dataclass
class Health:
    struggling: bool
    signals: dict[str, int]
    findings: list[str]
    nudges: list[str]


def _what(tu: ToolUse | None) -> str | None:
    if tu is None:
        return None
    return tu.command or (basename(tu.file_path) if tu.file_path else None)


def read_session(events: Iterable[Event]) -> LiveSession:
    s = LiveSession()
    uses: dict[str, ToolUse] = {}
    for ev in events:
        if ev.kind == "human":
            s.prompts.append(ev.text or "")
        elif ev.kind == "interrupt":
            s.interrupts += 1
        elif ev.kind == "assistant":
            for tu in ev.tool_uses:
                uses.setdefault(tu.id, tu)
        elif ev.kind == "tool_result":
            for r in ev.tool_results:
                if r.is_error:
                    tu = uses.get(r.tool_use_id)
                    s.failures.append((tu.name if tu else "unknown", _what(tu)))
    s.edit_paths = [t.file_path for t in uses.values() if t.name in EDIT_TOOLS and t.file_path]
    return s


def _top_failed_tool(s: LiveSession) -> tuple[str, int]:
    return Counter(t for t, _ in s.failures).most_common(1)[0]


def _findings(
    s: LiveSession, signals: dict[str, int], hot: tuple[str, int], patterns: list[str]
) -> list[str]:
    out: list[str] = []
    if hot[1] > EDIT_ALLOWANCE:
        out.append(f"{basename(hot[0])} edited {hot[1]} times")
    if s.failures:
        tool, n = _top_failed_tool(s)
        line = f"{n} failed {tool} call(s)"
        example = next((w for t, w in s.failures if t == tool and w), None)
        if example:
            line += f", e.g. `{short(example, 80)}`"
        out.append(line)
    if signals["corrections"]:
        regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
        first = next(
            (p for p in s.prompts if any(r.search(correction_text(p)) for r in regexes)), ""
        )
        out.append(
            f"{signals['corrections']} correction(s) from the user, "
            f'first: "{short(strip_pasted(first), 100)}"'
        )
    if s.interrupts:
        out.append(f"The user interrupted {s.interrupts} time(s)")
    if signals["turns"] >= LONG_SESSION:
        out.append(f"{signals['turns']} prompts so far; long sessions tend to drift")
    return out[:4]


def _nudges(s: LiveSession, signals: dict[str, int], hot: tuple[str, int]) -> list[str]:
    out: list[str] = []
    if hot[1] > EDIT_ALLOWANCE:
        out.append(
            f"Stop editing {basename(hot[0])} for a moment: re-read the latest error and "
            "state the root cause before the next edit."
        )
    if s.failures:
        if _top_failed_tool(s)[0] in SHELL_TOOLS:
            out.append("Ask the user for the exact build or test command instead of guessing.")
        else:
            out.append("Check the tool's inputs (paths, arguments) before retrying the call.")
    if signals["corrections"] or s.interrupts:
        out.append("Summarise your plan back to the user and get a yes before more edits.")
    if signals["turns"] >= LONG_SESSION:
        out.append("Suggest a fresh session that starts from a short summary of where you are.")
    return out[:3]


def assess(s: LiveSession, weights: dict[str, float], correction_patterns: list[str]) -> Health:
    signals = compute_signals(
        s.prompts, s.interrupts, len(s.failures), s.edit_paths, correction_patterns
    )
    hot = Counter(s.edit_paths).most_common(1)[0] if s.edit_paths else ("", 0)
    struggling = raw_score(signals, weights) >= STRUGGLE_SCORE or hot[1] > HOT_FILE_EDITS
    return Health(
        struggling,
        signals,
        _findings(s, signals, hot, correction_patterns),
        _nudges(s, signals, hot),
    )


def render_health(h: Health) -> str:
    if not h.signals["turns"]:
        return "## Session health\nNo prompts in this session yet."
    head = "Signs of struggle" if h.struggling else "Looks healthy"
    lines = [f"## Session health: {head}", f"{h.signals['turns']} prompt(s) so far."]
    if h.findings:
        lines += ["", "What stands out:", *bullets(h.findings)]
    if h.nudges:
        lines += ["", "Try next:", *bullets(h.nudges)]
    return "\n".join(lines)
