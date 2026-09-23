"""Rule-based prompt features (free, run on every human prompt)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from promptlens.db.models import Message, PromptFeatures
from promptlens.db.upsert import upsert

_EXT = (
    "py|pyi|ts|tsx|js|jsx|mjs|cjs|json|md|mdx|toml|ya?ml|css|scss|html|sql|go|rs|java|kt|rb|"
    "sh|ps1|txt|cfg|ini|c|cc|cpp|h|hpp|cs|php|swift|vue|svelte|ipynb|env|lock|xml|gradle"
)
FILE_RE = re.compile(rf"(?:@[\w./\\-]+|(?<![\w/])[\w./\\-]*[\w-]\.(?:{_EXT})\b)", re.IGNORECASE)
ERROR_RE = re.compile(
    r"Traceback|\b\w*(?:Error|Exception)\b[:(]|\bException\b|\bexit code \d+|\bERR!|"
    r"\bFAILED\b|\bpanic:|^\s+at .+:\d+",
    re.IGNORECASE | re.MULTILINE,
)
CODE_RE = re.compile(r"```|^(?: {4}|\t)\S", re.MULTILINE)
SUCCESS_RE = re.compile(
    r"\b(should|expected?|so that|make sure|ensure|tests? (?:should )?pass|must|until|"
    r"acceptance|done when)\b",
    re.IGNORECASE,
)


def extract_features(text: str, is_first: bool) -> dict[str, int | bool]:
    return {
        "char_len": len(text),
        "mentions_file": bool(FILE_RE.search(text)),
        "has_error_text": bool(ERROR_RE.search(text)),
        "has_code_block": bool(CODE_RE.search(text)),
        "has_success_criteria": bool(SUCCESS_RE.search(text)),
        "is_first_in_session": is_first,
    }


def compute_features(db: DB) -> int:
    rows = db.execute(
        select(Message.id, Message.session_id, Message.text)
        .where(Message.is_human_prompt.is_(True))
        .order_by(Message.session_id, Message.timestamp, Message.id)
    ).all()
    seen: set[str] = set()
    out = []
    for mid, sid, text in rows:
        first = sid not in seen
        seen.add(sid)
        out.append({"message_id": mid, **extract_features(text or "", first)})
    cols = [c for c in out[0] if c != "message_id"] if out else []
    upsert(db, PromptFeatures, out, keys=["message_id"], update=cols)
    db.commit()
    return len(out)
