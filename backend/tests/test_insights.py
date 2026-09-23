from datetime import UTC, date, datetime, timedelta

from promptlens.db.models import (
    Commit,
    Insight,
    LineSurvival,
    Message,
    Project,
    PromptFeatures,
    PromptScore,
    Session,
    SessionCommit,
)
from promptlens.insights.analysis import (
    SessionRow,
    compare_groups,
    compute_insights,
    median_diff_ci,
)
from promptlens.insights.report import write_weekly_report


def row(i, **kw):
    base = dict(
        session_id=f"s{i}",
        mentions_file=False,
        has_context=None,
        has_error_text=False,
        category=None,
        scope=None,
        specificity=None,
        turns_to_commit=None,
        struggle_score=None,
        survival_7d=None,
        has_commit=False,
    )
    base.update(kw)
    return SessionRow(**base)


def test_compare_groups_reports_medians_with_sizes():
    rows = [row(i, mentions_file=True, turns_to_commit=3 + i % 3) for i in range(12)]
    rows += [row(100 + i, mentions_file=False, turns_to_commit=8 + i % 3) for i in range(15)]
    found = compare_groups(rows)
    ins = next(x for x in found if x.kind == "mentions_file:turns_to_commit")
    assert ins.detail["median_a"] == 4 and ins.detail["median_b"] == 9
    assert (ins.n_a, ins.n_b) == (12, 15)
    assert "referenced a specific file" in ins.title
    assert "(n=12 vs n=15)" in ins.title


def test_min_group_size_rule():
    rows = [row(i, mentions_file=True, turns_to_commit=3) for i in range(9)]
    rows += [row(100 + i, mentions_file=False, turns_to_commit=8) for i in range(30)]
    assert not [x for x in compare_groups(rows) if x.kind == "mentions_file:turns_to_commit"]


def test_has_commit_uses_rates():
    rows = [row(i, specificity=5, has_commit=i < 8) for i in range(10)]
    rows += [row(100 + i, specificity=1, has_commit=i < 2) for i in range(10)]
    ins = next(x for x in compare_groups(rows) if x.kind == "specificity:has_commit")
    assert ins.detail["rate_a"] == 80.0 and ins.detail["rate_b"] == 20.0


def test_error_text_only_for_bugfix():
    rows = [row(i, has_error_text=True, category="feature", struggle_score=10) for i in range(20)]
    rows += [
        row(100 + i, has_error_text=False, category="feature", struggle_score=50) for i in range(20)
    ]
    assert not [x for x in compare_groups(rows) if x.kind.startswith("has_error_text")]


def test_bootstrap_ci_contains_true_difference():
    lo, hi = median_diff_ci([1, 2, 3, 4, 5] * 4, [6, 7, 8, 9, 10] * 4)
    assert lo <= -5 <= hi


T = datetime(2026, 9, 16, 10, tzinfo=UTC)  # Wednesday of ISO week 38


def seed(db, n=12):
    db.add(Project(id=1, cwd="/p", repo_root="/p", name="proj"))
    db.flush()
    for i in range(2 * n):
        mention = i < n
        db.add(
            Session(
                id=f"s{i}",
                project_id=1,
                started_at=T - timedelta(hours=i),
                ended_at=T - timedelta(hours=i) + timedelta(minutes=30),
                active_minutes=30,
                input_tokens=100,
                output_tokens=50,
                models=["m"],
                est_cost_usd=1,
                struggle_score=10 if mention else 60,
                turns_to_commit=2 if mention else 6,
                has_commit=True,
                struggle_signals={
                    "interrupts": 0 if mention else 2,
                    "corrections": 1,
                    "tool_errors": 0,
                    "repeated_edits": 0,
                    "turns": 3,
                    "raw_score": 1,
                },
            )
        )
        db.flush()
        db.add(
            Message(
                id=i + 1,
                session_id=f"s{i}",
                event_uuid=f"m{i}",
                role="user",
                is_human_prompt=True,
                text="fix app.py" if mention else "fix it",
                timestamp=T - timedelta(hours=i),
            )
        )
        db.flush()
        db.add(
            PromptFeatures(
                message_id=i + 1,
                char_len=10,
                mentions_file=mention,
                has_error_text=False,
                has_code_block=False,
                has_success_criteria=False,
                is_first_in_session=True,
            )
        )
        db.add(
            PromptScore(
                message_id=i + 1,
                rubric_version="v1",
                model_used="m",
                text_hash=str(i),
                specificity=4 if mention else 2,
                has_context=mention,
                has_success_criteria=False,
                scope="small",
                category="bugfix",
                suggestion="",
                created_at=T,
            )
        )
    db.add(
        Commit(
            sha="c1",
            project_id=1,
            authored_at=T - timedelta(days=7),
            message="x",
            ai_coauthored=True,
            lines_added=10,
        )
    )
    db.flush()
    db.add(
        LineSurvival(
            commit_sha="c1",
            days_after=7,
            status="ok",
            lines_total=10,
            lines_surviving=8,
            computed_at=T,
        )
    )
    db.add(SessionCommit(session_id="s0", commit_sha="c1", link_method="trailer", confidence=0.9))
    db.commit()


def test_compute_insights_persists(db):
    seed(db)
    found = compute_insights(db)
    assert found
    assert db.query(Insight).count() == len(found)
    compute_insights(db)
    assert db.query(Insight).count() == len(found)  # replaced, not appended


def test_weekly_report(db, tmp_path):
    seed(db)
    compute_insights(db)
    path = write_weekly_report(db, tmp_path, today=date(2026, 9, 18))
    assert path.name == "2026-W38.md"
    text = path.read_text(encoding="utf-8")
    assert "# PromptLens weekly report: 2026-W38" in text
    assert "| Sessions | 24 |" in text
    assert "## Highest-struggle sessions" in text
    assert "80.0%" in text  # 7-day survival of last week's AI commit
    assert "## Prompt habits" in text
    assert "Average specificity" in text
