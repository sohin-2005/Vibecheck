"""Secret redaction. Applied to every piece of text before it reaches the database."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_NOT_REDACTED = r"(?!\[REDACTED)"

# (kind, pattern, replacement). Order matters: whole blocks first, then specific
# token formats, then generic NAME=value assignments.
_DEFAULTS: list[tuple[str, str, str]] = [
    (
        "private_key",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED:private_key]",
    ),
    (
        "conn_string",
        r"\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)" + _NOT_REDACTED + r"([^\s@/]+)(@)",
        r"\1[REDACTED:conn_string]\3",
    ),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+", "[REDACTED:jwt]"),
    ("aws_key", r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED:aws_key]"),
    (
        "api_key",
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})",
        "[REDACTED:api_key]",
    ),
    (
        "assignment",
        r"\b([A-Z0-9_]*(?:KEY|SECRET|PASSWORD|PASSWD|TOKEN)[A-Z0-9_]*)(\s*[=:]\s*)"
        + r"([\"']?)"
        + _NOT_REDACTED
        + r"([^\s\"']+)\3",
        r"\1\2\3[REDACTED:assignment]\3",
    ),
]


class Redactor:
    def __init__(self, enabled: bool = True, extra_patterns: Iterable[str] = ()) -> None:
        self.enabled = enabled
        self._rules = [(re.compile(p), repl) for _, p, repl in _DEFAULTS]
        self._rules += [(re.compile(p), "[REDACTED:custom]") for p in extra_patterns]

    def redact(self, text: str | None) -> str | None:
        if not self.enabled or not text:
            return text
        for rx, repl in self._rules:
            text = rx.sub(repl, text)
        return text

    def redact_json(self, value: Any) -> Any:
        """Return a copy of a JSON-like structure with every string redacted."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {k: self.redact_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact_json(v) for v in value]
        return value
