"""Draft the README's "What I learned from my own data" section from real numbers.

The draft states facts only (shares, rates, counts) so it can be edited into prose.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session as DB

from vibecheck.config import Config
from vibecheck.db.models import (
    Insight,
    LineSurvival,
    Message,
    Project,
    PromptFeatures,
    Session,
    ToolCall,
)

MIN_SESSIONS = 10
MIN_TOOL_CALLS = 10
SIGNAL_NAMES = {
    "interrupts": "interrupting the AI",
    "corrections": "correcting it",
    "tool_errors": "failed tool calls",
    "repeated_edits": "repeated edits to the same file",
    "turns": "long back-and-forths",
}


def tool_label(name: str) -> str:
    """``mcp__server__tool`` -> ``tool (server MCP)``; other names unchanged."""
    parts = name.split("__")
    if len(parts) >= 3 and parts[0] == "mcp":
        return f"{'__'.join(parts[2:])} ({parts[1]} MCP)"
    return name


def draft_findings(db: DB, cfg: Config) -> str:
    sessions = list(db.scalars(select(Session).where(Session.started_at.is_not(None))))
    head = "## What I learned from my own data\n"
    if not sessions:
        return head + "\nNo sessions yet. Run `vibecheck run` first.\n"
    start = min(s.started_at for s in sessions)  # type: ignore[type-var]
    end = max(s.started_at for s in sessions)  # type: ignore[type-var]
    days = max(1, (end - start).days + 1)  # type: ignore[operator]
    tools = Counter(s.tool for s in sessions)
    lines = [
        head,
        f"_Based on {len(sessions)} sessions over {days} days "
        f"({', '.join(f'{t}: {n}' for t, n in tools.most_common())})._\n",
    ]
    if len(sessions) < MIN_SESSIONS:
        lines.append(
            f"> Early data: fewer than {MIN_SESSIONS} sessions. Treat these as anecdotes and "
            "re-run `vibecheck findings` after a few weeks.\n"
        )
    bullets: list[str] = []

    names = {p.id: p.name for p in db.scalars(select(Project))}
    minutes: dict[str, float] = defaultdict(float)
    for s in sessions:
        minutes[names.get(s.project_id or -1, "no project")] += float(s.active_minutes or 0)
    total_min = sum(minutes.values())
    if total_min:
        top, m = max(minutes.items(), key=lambda kv: kv[1])
        bullets.append(
            f"**Where the time went:** {top} took {100 * m / total_min:.0f}% of my active time "
            f"({m / 60:.1f} of {total_min / 60:.1f} hours)."
        )

    points: Counter[str] = Counter()
    for s in sessions:
        for k, v in (s.struggle_signals or {}).items():
            if k in SIGNAL_NAMES:
                points[k] += v * cfg.weights.get(k, 0)
    total_pts = sum(points.values())
    if total_pts:
        k, v = points.most_common(1)[0]
        bullets.append(
            f"**Biggest source of friction:** {SIGNAL_NAMES[k]}, {100 * v / total_pts:.0f}% of all "
            "struggle points. Everything else was smaller."
        )

    worst_tool = None
    for name, n, errs in db.execute(
        select(
            ToolCall.tool_name,
            func.count(),
            func.sum(case((ToolCall.is_error.is_(True), 1), else_=0)),
        ).group_by(ToolCall.tool_name)
    ):
        if (
            n >= MIN_TOOL_CALLS
            and errs
            and (worst_tool is None or errs / n > worst_tool[1] / worst_tool[2])
        ):
            worst_tool = (name, int(errs), n)
    if worst_tool:
        name, errs, n = worst_tool
        bullets.append(
            f"**Most error-prone tool:** {tool_label(name)} failed "
            f"{100 * errs / n:.0f}% of the time ({errs} of {n} calls)."
        )

    surv = db.execute(
        select(
            func.sum(LineSurvival.ai_lines_surviving),
            func.sum(LineSurvival.ai_lines_total),
            func.sum(LineSurvival.lines_surviving),
            func.sum(LineSurvival.lines_total),
        ).where(LineSurvival.days_after == 7, LineSurvival.status == "ok")
    ).one()
    if surv[1]:
        bullets.append(
            f"**Code survival:** {100 * surv[0] / surv[1]:.0f}% of the lines the AI wrote were "
            f"still there a week later ({surv[0]} of {surv[1]}, edit-matched)."
        )
    elif surv[3]:
        bullets.append(
            f"**Code survival:** {100 * surv[2] / surv[3]:.0f}% of lines in AI-linked commits were "
            "still there a week later (whole-commit)."
        )

    firsts = db.execute(
        select(PromptFeatures.mentions_file, PromptFeatures.char_len)
        .join(Message, Message.id == PromptFeatures.message_id)
        .where(PromptFeatures.is_first_in_session.is_(True))
    ).all()
    if firsts:
        pct = 100 * sum(1 for f, _ in firsts if f) / len(firsts)
        lens = sorted(n for _, n in firsts)
        bullets.append(
            f"**Prompt habits:** {pct:.0f}% of my first prompts named a file; the median first "
            f"prompt was {lens[len(lens) // 2]} characters."
        )

    top_insight = db.scalars(select(Insight).order_by((Insight.n_a + Insight.n_b).desc())).first()
    if top_insight:
        bullets.append(f"**Strongest pattern:** {top_insight.title}")

    costs = [float(s.est_cost_usd) for s in sessions if s.est_cost_usd is not None]
    if costs and sum(costs) > 0:
        bullets.append(
            f"**API-equivalent cost:** ${sum(costs):,.2f} over {days} days "
            f"(${sum(costs) / days:,.2f} a day)."
        )

    lines += [f"- {b}" for b in bullets]
    lines.append("\n_Drafted by `vibecheck findings`. Correlations, not causes; edit freely._\n")
    return "\n".join(lines)
