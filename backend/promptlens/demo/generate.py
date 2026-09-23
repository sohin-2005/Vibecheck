"""Synthetic dataset so anyone can try the dashboard without their own logs.

Everything here is made up: projects, prompts, commits and the "demo-model" prices.
Data is written straight to a separate SQLite database, then the normal metric,
struggle, feature and insight code runs over it.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from promptlens.coach.features import compute_features
from promptlens.coach.rubric import RUBRIC_VERSION
from promptlens.config import Config, ModelPrice
from promptlens.db.models import (
    Base,
    Commit,
    CommitFile,
    LineSurvival,
    Message,
    Project,
    PromptScore,
    Session,
    SessionCommit,
    ToolCall,
)
from promptlens.db.session import get_engine, make_sessionmaker
from promptlens.gitdata.linker import _update_session_commit_fields
from promptlens.insights.analysis import compute_insights
from promptlens.metrics.session_metrics import recompute_session
from promptlens.metrics.struggle import compute_struggle

DEMO_DB_PATH = Path("~/.promptlens/demo.db").expanduser()
DEMO_DB_URL = f"sqlite:///{DEMO_DB_PATH.as_posix()}"
DEMO_MODEL = "demo-model"
# Invented prices so the demo can show cost; not any real model's pricing.
DEMO_PRICES = {DEMO_MODEL: ModelPrice(input=3.0, output=15.0, cache_write=3.75, cache_read=0.3)}

PROJECTS = [
    ("/home/dev/webshop", "webshop", [".tsx", ".ts", ".css"]),
    ("/home/dev/api-server", "api-server", [".py", ".sql"]),
    ("/home/dev/ml-pipeline", "ml-pipeline", [".py", ".ipynb", ".yaml"]),
    ("/home/dev/dotfiles", "dotfiles", [".sh", ".toml"]),
]

GOOD_PROMPTS = [
    (
        "bugfix",
        "The checkout total in src/cart/total.ts is off by one cent when a coupon applies. "
        "Expected 19.99, got 20.00. Make sure the existing tests in cart.test.ts still pass.",
    ),
    (
        "bugfix",
        "Fix the 500 in api/routes/orders.py: TypeError: 'NoneType' object is not subscriptable "
        "at line 88 when the order has no address. It should return 422 instead.",
    ),
    (
        "feature",
        "Add a `--dry-run` flag to scripts/sync.sh that prints the rsync command without "
        "running it. Done when `sync.sh --dry-run` exits 0 and changes nothing.",
    ),
    (
        "test",
        "Write pytest tests for parse_invoice() in billing/parser.py covering empty input, "
        "a missing currency and a negative amount. Tests should pass without network access.",
    ),
    (
        "refactor",
        "Split the 400-line UserSettings.tsx into ProfileForm and NotificationPrefs "
        "components. Behaviour must stay identical; the Playwright settings spec should pass.",
    ),
    (
        "feature",
        "Add pagination to GET /api/products (page, page_size, max 100) in "
        "api/routes/products.py and return total in the response body.",
    ),
]
VAGUE_PROMPTS = [
    ("bugfix", "fix it"),
    ("bugfix", "it's broken again, can you look"),
    ("feature", "make the dashboard better"),
    ("other", "clean up the code"),
    ("feature", "add auth and payments and an admin panel and email notifications"),
    ("refactor", "refactor everything to be more modern"),
    ("explain", "what does this do"),
]
FOLLOWUPS_OK = [
    "looks good, also update the README",
    "great, commit it",
    "nice. run the linter too",
]
FOLLOWUPS_BAD = [
    "no, that's wrong",
    "still broken",
    "that didn't work, try again",
    "no, revert that",
    "still fails with the same error",
]
SUGGESTIONS = {
    True: "",
    False: "Name the file and the exact error, and say what the correct behaviour is.",
}


def _usage(rng: random.Random) -> dict[str, int]:
    return {
        "input_tokens": rng.randint(5, 400),
        "output_tokens": rng.randint(150, 2500),
        "cache_write_tokens": rng.randint(0, 20_000),
        "cache_read_tokens": rng.randint(10_000, 120_000),
    }


def _session(db: DB, rng: random.Random, i: int, now: datetime, pid: int, proj: tuple) -> None:
    cwd, name, exts = proj
    good = rng.random() < 0.5
    category, first = rng.choice(GOOD_PROMPTS if good else VAGUE_PROMPTS)
    days_ago = rng.uniform(0, 60)
    t = (now - timedelta(days=days_ago)).replace(microsecond=0)
    if t.hour < 8:
        t = t.replace(hour=rng.randint(9, 20))
    sid = str(uuid.UUID(int=rng.getrandbits(128)))
    s = Session(
        id=sid,
        project_id=pid,
        title=first[:60].rstrip() + ("…" if len(first) > 60 else ""),
        started_at=t,
        git_branch=rng.choice(["main", "main", f"feat/{name}-{i}"]),
        cc_version="2.1.0",
        models=[],
    )
    db.add(s)
    db.flush()

    rounds = rng.randint(1, 3) if good else rng.randint(3, 9)
    fail_rate = 0.05 if good else 0.25
    n = 0

    def msg(**kw: object) -> None:
        nonlocal n
        n += 1
        db.add(Message(session_id=sid, event_uuid=f"{sid}-{n}", **kw))

    files = [f"src/{name}_{k}{rng.choice(exts)}" for k in range(rng.randint(1, 4))]
    for r in range(rounds):
        if r == 0:
            text = first
        elif good:
            text = rng.choice(FOLLOWUPS_OK)
        else:
            text = rng.choice(FOLLOWUPS_BAD + FOLLOWUPS_OK[:1])
        msg(role="user", is_human_prompt=True, text=text, timestamp=t)
        t += timedelta(seconds=rng.randint(5, 40))
        for _ in range(rng.randint(2, 6)):
            tool = rng.choice(["Read", "Edit", "Edit", "Bash", "Grep", "Write"])
            db.add(
                ToolCall(
                    session_id=sid,
                    tool_use_id=f"{sid}-tool-{n}-{rng.getrandbits(32)}",
                    tool_name=tool,
                    file_path=f"{cwd}/{rng.choice(files)}"
                    if tool in ("Read", "Edit", "Write")
                    else None,
                    command=rng.choice(["npm test", "pytest -q", "ruff check ."])
                    if tool == "Bash"
                    else None,
                    is_error=rng.random() < fail_rate,
                    timestamp=t,
                )
            )
            t += timedelta(seconds=rng.randint(3, 90))
        msg(
            role="assistant",
            text="Done. "
            + rng.choice(["Tests pass.", "Updated the handler.", "Here's what changed."]),
            model=DEMO_MODEL,
            api_message_id=f"msg_{sid}_{r}",
            timestamp=t,
            **_usage(rng),
        )
        if not good and rng.random() < 0.3:
            msg(role="user", is_interrupt=True, text="[Request interrupted by user]", timestamp=t)
        t += timedelta(minutes=rng.uniform(0.5, 6))

    db.add(
        PromptScore(
            message_id=db.query(Message.id).filter_by(event_uuid=f"{sid}-1").scalar(),
            rubric_version=RUBRIC_VERSION,
            model_used="demo",
            text_hash=f"demo-{i}",
            specificity=rng.choice([4, 5]) if good else rng.choice([1, 2, 2, 3]),
            has_context=good,
            has_success_criteria=good and rng.random() < 0.8,
            scope="too_large" if " and " in first and not good else rng.choice(["small", "medium"]),
            category=category,
            suggestion=SUGGESTIONS[good],
            created_at=now,
        )
    )

    commits = rng.random() < (0.85 if good else 0.45)
    if commits:
        sha = f"{rng.getrandbits(160):040x}"
        added = rng.randint(15, 220)
        db.add(
            Commit(
                sha=sha,
                project_id=pid,
                authored_at=t,
                message=f"{category}: {first[:50]}\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                ai_coauthored=True,
                lines_added=added,
                lines_deleted=rng.randint(0, added // 2),
            )
        )
        db.flush()
        remaining = added
        for k, f in enumerate(files):
            share = remaining if k == len(files) - 1 else rng.randint(0, remaining)
            remaining -= share
            if share:
                db.add(CommitFile(commit_sha=sha, file_path=f, lines_added=share, lines_deleted=0))
        db.add(SessionCommit(session_id=sid, commit_sha=sha, link_method="trailer", confidence=0.9))
        keep = rng.uniform(0.8, 0.98) if good else rng.uniform(0.4, 0.85)
        for d in (1, 7, 30):
            if t + timedelta(days=d) > now:
                continue
            decay = keep ** (d / 7)
            db.add(
                LineSurvival(
                    commit_sha=sha,
                    days_after=d,
                    status="ok",
                    snapshot_sha=sha,
                    lines_total=added,
                    lines_surviving=round(added * min(1.0, decay + 0.02)),
                    computed_at=now,
                )
            )


def build_demo(url: str = DEMO_DB_URL, n_sessions: int = 120, seed: int = 42) -> str:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    rng = random.Random(seed)
    now = datetime.now(UTC)
    cfg = Config(database_url=url, pricing=dict(DEMO_PRICES))
    db = make_sessionmaker(url)()
    try:
        pids = []
        for cwd, name, _ in PROJECTS:
            p = Project(cwd=cwd, repo_root=cwd, name=name)
            db.add(p)
            db.flush()
            pids.append(p.id)
        weights = [5, 4, 3, 1]
        for i in range(n_sessions):
            k = rng.choices(range(len(PROJECTS)), weights)[0]
            _session(db, rng, i, now, pids[k], PROJECTS[k])
        db.commit()
        for sid in db.scalars(select(Session.id)).all():
            recompute_session(db, sid, cfg)
            s = db.get(Session, sid)
            if s is not None and s.ended_at is None:
                # demo rows have no raw_events; derive start/end from messages
                ts = [
                    m.timestamp for m in db.query(Message).filter_by(session_id=sid) if m.timestamp
                ]
                s.started_at, s.ended_at = min(ts), max(ts)
        db.commit()
        _update_session_commit_fields(db)
        db.commit()
        compute_struggle(db, cfg)
        compute_features(db)
        found = compute_insights(db)
    finally:
        db.close()
    return f"Demo database with {n_sessions} sessions and {len(found)} insights at {url}"
