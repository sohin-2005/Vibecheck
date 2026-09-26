"""Rule-based check of one prompt, with a template rewrite (no LLM, no database)."""

from __future__ import annotations

from vibecheck.coach.features import extract_features
from vibecheck.coach.rewrite import FIX_RE, RewriteContext, template_rewrite
from vibecheck.ingest.parser import strip_pasted
from vibecheck.mcp.render import bullets

PASTED_MARKER = "[pasted text]"  # what strip_pasted leaves in place of a pasted block


def critique_prompt(text: str) -> str:
    typed = strip_pasted(text).strip()
    if not typed.replace(PASTED_MARKER, "").strip():
        return "## Prompt check\nNothing to check: the prompt is empty (or only pasted content)."
    f = extract_features(typed, is_first=True)
    missing: list[str] = []
    if not f["mentions_file"]:
        missing.append("which file(s) or folder the change is in")
    if FIX_RE.search(typed) and not f["has_error_text"]:
        missing.append("the error message or what happens now")
    if not f["has_success_criteria"]:
        missing.append('what "done" looks like (expected behaviour, or a test that should pass)')
    if not missing:
        return "## Prompt check: specific enough\nIt says where to work and what done looks like."
    rewrite, _ = template_rewrite(typed, RewriteContext())
    return "\n".join(
        [
            "## Prompt check",
            "Missing:",
            *bullets(missing),
            "",
            "Could be:",
            "```",
            rewrite,
            "```",
            "",
            "Fill in the [placeholders] by asking the user, not by guessing.",
        ]
    )
