"""SQLAlchemy models. Portable between PostgreSQL (primary) and SQLite (tests, demo)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# BIGSERIAL on Postgres, INTEGER PRIMARY KEY (autoincrement) on SQLite.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")
JSONType = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator[datetime]):
    """timestamptz that always round-trips as an aware UTC datetime (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class IngestState(Base):
    __tablename__ = "ingest_state"
    file_path: Mapped[str] = mapped_column(Text, primary_key=True)
    file_size: Mapped[int] = mapped_column(BigInteger)
    mtime: Mapped[datetime] = mapped_column(UTCDateTime)
    lines_processed: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cwd: Mapped[str] = mapped_column(Text, unique=True)
    repo_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    tool: Mapped[str] = mapped_column(Text, default="claude-code", server_default="claude-code")
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    git_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    cc_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    models: Mapped[list[str]] = mapped_column(JSONType, default=list)
    human_turns: Mapped[int] = mapped_column(Integer, default=0)
    assistant_turns: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    est_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    active_minutes: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    turns_to_commit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    struggle_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    struggle_signals: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    has_commit: Mapped[bool] = mapped_column(Boolean, default=False)


class RawEvent(Base):
    __tablename__ = "raw_events"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    line_no: Mapped[int] = mapped_column(Integer)
    event_uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)

    __table_args__ = (Index("ux_raw_events_file_line", "file_path", "line_no", unique=True),)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    event_uuid: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[str] = mapped_column(Text)
    is_human_prompt: Mapped[bool] = mapped_column(Boolean, default=False)
    is_interrupt: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sidechain: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_messages_session_ts", "session_id", "timestamp"),)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    tool_use_id: Mapped[str] = mapped_column(Text, unique=True)
    tool_name: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Code the tool wrote (Edit new_string / Write content / patch "+" lines), redacted.
    added_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_error: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_sidechain: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Commit(Base):
    __tablename__ = "commits"
    sha: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    authored_at: Mapped[datetime] = mapped_column(UTCDateTime)
    message: Mapped[str] = mapped_column(Text)
    is_merge: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_coauthored: Mapped[bool] = mapped_column(Boolean, default=False)
    lines_added: Mapped[int] = mapped_column(Integer, default=0)
    lines_deleted: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_commits_project_time", "project_id", "authored_at"),)


class CommitFile(Base):
    __tablename__ = "commit_files"
    commit_sha: Mapped[str] = mapped_column(ForeignKey("commits.sha"), primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, primary_key=True)
    lines_added: Mapped[int] = mapped_column(Integer)
    lines_deleted: Mapped[int] = mapped_column(Integer)


class SessionCommit(Base):
    __tablename__ = "session_commits"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    commit_sha: Mapped[str] = mapped_column(ForeignKey("commits.sha"), primary_key=True)
    link_method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2))


class LineSurvival(Base):
    __tablename__ = "line_survival"
    commit_sha: Mapped[str] = mapped_column(ForeignKey("commits.sha"), primary_key=True)
    days_after: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(Text, default="ok")  # ok | not_merged
    snapshot_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    lines_total: Mapped[int] = mapped_column(Integer, default=0)
    lines_surviving: Mapped[int] = mapped_column(Integer, default=0)
    # Edit-matched: only added lines that match code the AI's edit tools wrote.
    ai_lines_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_lines_surviving: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PromptFeatures(Base):
    __tablename__ = "prompt_features"
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    char_len: Mapped[int] = mapped_column(Integer)
    mentions_file: Mapped[bool] = mapped_column(Boolean)
    has_error_text: Mapped[bool] = mapped_column(Boolean)
    has_code_block: Mapped[bool] = mapped_column(Boolean)
    has_success_criteria: Mapped[bool] = mapped_column(Boolean)
    is_first_in_session: Mapped[bool] = mapped_column(Boolean)


class PromptScore(Base):
    __tablename__ = "prompt_scores"
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    rubric_version: Mapped[str] = mapped_column(Text, primary_key=True)
    model_used: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(Text, index=True)
    specificity: Mapped[int] = mapped_column(Integer)
    has_context: Mapped[bool] = mapped_column(Boolean)
    has_success_criteria: Mapped[bool] = mapped_column(Boolean)
    scope: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PromptRewrite(Base):
    __tablename__ = "prompt_rewrites"
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    method: Mapped[str] = mapped_column(Text)  # llm | template
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    rewrite: Mapped[str] = mapped_column(Text)
    changes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TeamSnapshot(Base):
    """Anonymized weekly aggregates pushed or imported from a teammate's Vibecheck."""

    __tablename__ = "team_snapshots"
    member: Mapped[str] = mapped_column(Text, primary_key=True)
    week: Mapped[str] = mapped_column(Text, primary_key=True)  # ISO week, e.g. 2026-W39
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Insight(Base):
    __tablename__ = "insights"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType)
    n_a: Mapped[int] = mapped_column(Integer)
    n_b: Mapped[int] = mapped_column(Integer)


Index("ix_sessions_started_at", Session.started_at)
