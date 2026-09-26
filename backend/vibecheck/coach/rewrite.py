"""Side-by-side rewrites of weak prompts: "here's how this could have been phrased".

Rewrites use hindsight: the files the AI ended up editing and the command that failed after
the prompt are known from the session, so they can be written into the better version. An
LLM does the rewrite when one is configured; otherwise a template does, with
[square-bracket] placeholders for anything the logs can't tell us.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from vibecheck.coach.features import extract_features
from vibecheck.coach.providers.base import LLMProvider
from vibecheck.coach.rubric import RUBRIC_VERSION
from vibecheck.config import Config
from vibecheck.db.models import Message, Project, PromptRewrite, PromptScore, Session, ToolCall
from vibecheck.ingest.parser import EDIT_TOOLS, strip_pasted

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You improve prompts a developer gave to an AI coding assistant.
Rewrite the prompt so it says where the change goes (files), what is wrong or wanted, the
expected behaviour, and how to check it is done. Keep the developer's intent and keep it short
(under 80 words). Use facts from the context (files the assistant ended up editing, a command
that failed). Never invent details: write [square-bracket placeholders] for anything unknown.
Return only JSON: {"rewrite": "...", "changes": ["short phrase per improvement", ...]}"""

MAX_NAMED_FILES = 3  # beyond this the prompt was broad; naming files would mislead
FIX_RE = re.compile(r"\b(fix|bug|broken|error|fails?|failing|crash|wrong|doesn'?t work)\b", re.I)


@dataclass
class RewriteContext:
    files: list[str] = field(default_factory=list)
    failing_command: str | None = None
    category: str | None = None


class RewriteOut(BaseModel):
    rewrite: str = Field(min_length=10)
    changes: list[str] = []


def _relative(path: str, root: str | None) -> str:
    p = path.replace("\\", "/")
    if root:
        r = root.replace("\\", "/").rstrip("/") + "/"
        if p.lower().startswith(r.lower()):
            return p[len(r) :]
    return p


def session_context(db: DB, msg: Message) -> RewriteContext:
    """What happened between this prompt and the next one in the same session."""
    ctx = RewriteContext()
    if msg.timestamp is None:
        return ctx
    nxt = db.scalar(
        select(Message.timestamp)
        .where(
            Message.session_id == msg.session_id,
            Message.is_human_prompt.is_(True),
            Message.timestamp > msg.timestamp,
        )
        .order_by(Message.timestamp)
        .limit(1)
    )
    q = select(ToolCall).where(
        ToolCall.session_id == msg.session_id, ToolCall.timestamp >= msg.timestamp
    )
    if nxt is not None:
        q = q.where(ToolCall.timestamp < nxt)
    session = db.get(Session, msg.session_id)
    project = db.get(Project, session.project_id) if session and session.project_id else None
    root = project.repo_root or project.cwd if project else None
    for t in db.scalars(q.order_by(ToolCall.timestamp)):
        if t.tool_name in EDIT_TOOLS and t.file_path:
            rel = _relative(t.file_path, root)
            if rel not in ctx.files:
                ctx.files.append(rel)
        if t.is_error and t.command and ctx.failing_command is None:
            ctx.failing_command = " ".join(t.command.split())[:120]
    score = db.scalar(
        select(PromptScore.category).where(
            PromptScore.message_id == msg.id, PromptScore.rubric_version == RUBRIC_VERSION
        )
    )
    ctx.category = score
    return ctx


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


def template_rewrite(text: str, ctx: RewriteContext) -> tuple[str, list[str]]:
    typed = strip_pasted(text).strip()
    f = extract_features(typed, is_first=False)
    changes: list[str] = []
    task = " ".join(typed.split()).rstrip(" .")
    rest: list[str] = []
    if len(re.findall(r"\band\b", task, re.I)) >= 2:
        parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", task) if p.strip()]
        if len(parts) >= 3:
            task, rest = parts[0], parts[1:]
            changes.append("Split into one task per request; the rest can follow once this works")

    lines = []
    if f["mentions_file"]:
        lines.append(f"{task}.")
    else:
        named = 0 < len(ctx.files) <= MAX_NAMED_FILES
        where = ", ".join(ctx.files) if named else "[file or folder]"
        lines.append(f"In {where}, {_lower_first(task)}.")
        changes.append(
            "Named the file(s) the AI ended up editing" if named else "Said where the change goes"
        )
    is_fix = ctx.category == "bugfix" or bool(FIX_RE.search(typed))
    if is_fix and not f["has_error_text"]:
        lines.append("Current behaviour: [what happens now, or paste the error]")
        changes.append("Described what's wrong now")
    if not f["has_success_criteria"]:
        lines.append(
            "Expected: [what should happen instead]"
            if is_fix
            else "Expected result: [what it should do when finished]"
        )
        cmd = ctx.failing_command
        usable = cmd and len(cmd) <= 60 and not re.search(r"[;|&]", cmd)
        done = f"`{cmd}` passes" if usable else "[the test or check that proves it works]"
        lines.append(f"Done when: {done}.")
        changes.append("Stated the expected behaviour")
        changes.append("Said how to check it's done")
    if rest:
        lines.append("Later, as separate requests: " + "; ".join(rest) + ".")
    if not changes:
        return text, []
    return "\n".join(lines), changes


def _llm_rewrite(provider: LLMProvider, text: str, ctx: RewriteContext) -> RewriteOut:
    payload = {
        "prompt": strip_pasted(text)[:1500],
        "context": {
            "files_the_assistant_edited": ctx.files[:5],
            "command_that_failed": ctx.failing_command,
            "category": ctx.category,
        },
    }
    raw = provider.complete_json(SYSTEM_PROMPT, json.dumps(payload), RewriteOut.model_json_schema())
    return RewriteOut.model_validate(raw)


def get_or_create_rewrite(
    db: DB, cfg: Config, message_id: int, provider: LLMProvider | None, force: bool = False
) -> PromptRewrite:
    existing = db.get(PromptRewrite, message_id)
    if existing is not None and not force:
        return existing
    msg = db.get(Message, message_id)
    if msg is None or not msg.is_human_prompt:
        raise LookupError(f"prompt {message_id} not found")
    ctx = session_context(db, msg)
    method, model = "template", None
    rewrite, changes = template_rewrite(msg.text or "", ctx)
    if provider is not None:
        try:
            out = _llm_rewrite(provider, msg.text or "", ctx)
            rewrite, changes, method, model = out.rewrite, out.changes, "llm", provider.model
        except Exception as e:  # noqa: BLE001 - any provider failure falls back to the template
            log.warning("LLM rewrite failed, using template: %s", e)
    row = existing or PromptRewrite(message_id=message_id)
    row.method, row.model_used, row.rewrite, row.changes = method, model, rewrite, changes
    row.created_at = datetime.now(UTC)
    db.add(row)
    db.commit()
    return row


def rewrite_weakest(db: DB, cfg: Config, provider: LLMProvider | None, limit: int = 20) -> int:
    """Rewrite the weakest prompts that don't have a rewrite yet (low scores first)."""
    done = set(db.scalars(select(PromptRewrite.message_id)))
    scored = {
        mid: spec
        for mid, spec in db.execute(
            select(PromptScore.message_id, PromptScore.specificity).where(
                PromptScore.rubric_version == RUBRIC_VERSION
            )
        )
    }
    candidates = []
    for mid, text in db.execute(
        select(Message.id, Message.text).where(Message.is_human_prompt.is_(True))
    ):
        if mid in done or not text or len(text) < cfg.min_prompt_chars // 4:
            continue
        spec = scored.get(mid)
        if spec is not None and spec > 2:
            continue
        if spec is None and not template_rewrite(text, RewriteContext())[1]:
            continue  # unscored and already specific by the rules
        candidates.append((spec if spec is not None else 3, mid))
    candidates.sort()
    for _, mid in candidates[:limit]:
        get_or_create_rewrite(db, cfg, mid, provider)
    return min(limit, len(candidates))
