from datetime import UTC, datetime, timedelta

from vibecheck.coach.rewrite import (
    RewriteContext,
    get_or_create_rewrite,
    session_context,
    template_rewrite,
)
from vibecheck.config import Config
from vibecheck.db.models import Message, Project, PromptRewrite, Session, ToolCall

T = datetime(2026, 9, 20, 10, tzinfo=UTC)


def test_template_fills_in_what_actually_happened():
    ctx = RewriteContext(files=["src/auth.py"], failing_command="npm test", category="bugfix")
    rewrite, changes = template_rewrite("fix it", ctx)
    assert "src/auth.py" in rewrite
    assert "npm test" in rewrite
    assert "Expected:" in rewrite
    assert any("file" in c.lower() for c in changes)
    assert any("done" in c.lower() for c in changes)


def test_template_uses_placeholders_without_context():
    rewrite, changes = template_rewrite("make the dashboard better", RewriteContext())
    assert "[file" in rewrite and "Done when:" in rewrite
    assert changes


def test_template_splits_overloaded_requests():
    rewrite, changes = template_rewrite(
        "add auth and payments and an admin panel and email notifications", RewriteContext()
    )
    assert rewrite.lower().startswith("in [file") or "add auth" in rewrite.lower()
    assert "payments" in rewrite  # kept for a follow-up, not dropped
    assert any("split" in c.lower() for c in changes)


def test_good_prompt_needs_no_rewrite():
    good = "In api/orders.py, orders without an address raise TypeError: 'NoneType'. It should return 422; tests should pass."
    rewrite, changes = template_rewrite(good, RewriteContext())
    assert changes == [] and rewrite == good


def seed(db):
    db.add(Project(id=1, cwd="/work/app", repo_root="/work/app", name="app"))
    db.flush()
    db.add(Session(id="s", project_id=1, models=[]))
    db.flush()
    db.add(
        Message(
            id=1,
            session_id="s",
            event_uuid="m1",
            role="user",
            is_human_prompt=True,
            text="fix it",
            timestamp=T,
        )
    )
    db.add(
        Message(
            id=2,
            session_id="s",
            event_uuid="m2",
            role="user",
            is_human_prompt=True,
            text="thanks",
            timestamp=T + timedelta(minutes=9),
        )
    )
    db.add(
        ToolCall(
            session_id="s",
            tool_use_id="e1",
            tool_name="Edit",
            file_path="/work/app/src/auth.py",
            timestamp=T + timedelta(minutes=1),
        )
    )
    db.add(
        ToolCall(
            session_id="s",
            tool_use_id="b1",
            tool_name="Bash",
            command="pytest -q",
            is_error=True,
            timestamp=T + timedelta(minutes=2),
        )
    )
    db.add(
        ToolCall(
            session_id="s",
            tool_use_id="e2",
            tool_name="Edit",
            file_path="/work/app/other.py",
            timestamp=T + timedelta(minutes=10),
        )
    )
    db.commit()


def test_session_context_only_looks_until_the_next_prompt(db):
    seed(db)
    ctx = session_context(db, db.get(Message, 1))
    assert ctx.files == ["src/auth.py"]
    assert ctx.failing_command == "pytest -q"


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, response):
        self.response = response
        self.calls = 0

    def complete_json(self, system, user, schema):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_llm_rewrite_is_cached(db):
    seed(db)
    p = FakeProvider(
        {
            "rewrite": "In src/auth.py, fix the login check. Done when pytest passes.",
            "changes": ["Named the file"],
        }
    )
    r = get_or_create_rewrite(db, Config(), 1, p)
    assert r.method == "llm" and "src/auth.py" in r.rewrite and r.model_used == "fake-1"
    again = get_or_create_rewrite(db, Config(), 1, p)
    assert again.rewrite == r.rewrite and p.calls == 1
    assert db.query(PromptRewrite).count() == 1


def test_llm_failure_falls_back_to_template(db):
    seed(db)
    r = get_or_create_rewrite(db, Config(), 1, FakeProvider(ValueError("no model")))
    assert r.method == "template" and "src/auth.py" in r.rewrite and "pytest -q" in r.rewrite


def test_without_provider_uses_template(db):
    seed(db)
    r = get_or_create_rewrite(db, Config(), 1, None)
    assert r.method == "template"


def test_rewrite_weakest_skips_good_prompts(db):
    from vibecheck.coach.rewrite import rewrite_weakest

    seed(db)
    db.add(
        Message(
            id=3,
            session_id="s",
            event_uuid="m3",
            role="user",
            is_human_prompt=True,
            text="In api/orders.py, return 422 when address is missing; tests should pass.",
            timestamp=T + timedelta(minutes=20),
        )
    )
    db.commit()
    assert rewrite_weakest(db, Config(), None) == 2  # "fix it" and "thanks"-style short prompts
    assert db.get(PromptRewrite, 3) is None


def test_template_avoids_misleading_specifics():
    ctx = RewriteContext(
        files=["a.py", "b.py", "c.py", "d.py", "e.py"],
        failing_command="python -m uv run ruff check . --fix -q; python -m uv run ruff format -q .",
    )
    rewrite, _ = template_rewrite("start building this entire project\n\nuse the new skill", ctx)
    assert "a.py" not in rewrite  # too many files to name honestly
    assert "ruff" not in rewrite  # compound command is not a useful "done when"
    assert "\n\n" not in rewrite.split("\n")[0]
    assert "instead" not in rewrite  # a feature request, not a bugfix
