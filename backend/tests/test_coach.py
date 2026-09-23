import json
from datetime import UTC, datetime

import httpx
import pytest

from promptlens.coach.features import compute_features, extract_features
from promptlens.coach.providers import CloudNotConfirmedError, get_provider
from promptlens.coach.providers.ollama import OllamaProvider
from promptlens.coach.rubric import RUBRIC_VERSION
from promptlens.coach.scorer import score_prompts
from promptlens.config import Config
from promptlens.db.models import Message, Project, PromptFeatures, PromptScore, Session


@pytest.mark.parametrize(
    ("text", "key", "expected"),
    [
        ("fix the bug in src/auth/login.py please", "mentions_file", True),
        ("look at @README.md", "mentions_file", True),
        ("make it faster", "mentions_file", False),
        ("Traceback (most recent call last):\n  File x", "has_error_text", True),
        ("I get TypeError: x is undefined", "has_error_text", True),
        ("npm ERR! Exit code 1", "has_error_text", True),
        ("add an error message to the form", "has_error_text", False),
        ("```python\nprint(1)\n```", "has_code_block", True),
        ("no code here", "has_code_block", False),
        ("it should return 404 for missing users", "has_success_criteria", True),
        ("make sure the tests pass", "has_success_criteria", True),
        ("refactor this", "has_success_criteria", False),
    ],
)
def test_extract_features(text, key, expected):
    assert extract_features(text, is_first=False)[key] is expected


def seed(db, texts):
    db.add(Project(id=1, cwd="/p", name="p"))
    db.flush()
    db.add(Session(id="s", project_id=1, models=[]))
    db.flush()
    for i, t in enumerate(texts):
        db.add(
            Message(
                session_id="s",
                event_uuid=f"m{i}",
                role="user",
                is_human_prompt=True,
                text=t,
                timestamp=datetime(2026, 1, 1, 0, i, tzinfo=UTC),
            )
        )
    db.add(Message(session_id="s", event_uuid="a", role="assistant", text="assistant text"))
    db.commit()


def test_compute_features_marks_first_prompt(db):
    seed(db, ["first prompt about app.py", "second"])
    assert compute_features(db) == 2
    rows = {r.char_len: r for r in db.query(PromptFeatures)}
    assert rows[len("first prompt about app.py")].is_first_in_session
    assert rows[len("first prompt about app.py")].mentions_file
    assert not rows[len("second")].is_first_in_session


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def complete_json(self, system, user, schema):
        self.calls.append(json.loads(user))
        if self.responses:
            r = self.responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return {"results": [good(p["id"]) for p in json.loads(user)["prompts"]]}


def good(pid, spec=4):
    return {
        "id": pid,
        "specificity": spec,
        "has_context": True,
        "has_success_criteria": False,
        "scope": "small",
        "category": "bugfix",
        "suggestion": "Say what done looks like.",
    }


LONG = [f"Please fix the failing login test number {i} in auth.py" for i in range(5)]


def test_scores_in_batches_and_caches(db):
    seed(db, LONG + ["short"])
    cfg = Config(llm_batch_size=2, min_prompt_chars=20)
    p = FakeProvider()
    res = score_prompts(db, cfg, p)
    assert res.scored == 5 and res.llm_calls == 3 and res.failed == 0
    assert len(p.calls[0]["prompts"]) == 2
    s = db.query(PromptScore).first()
    assert s.rubric_version == RUBRIC_VERSION and s.model_used == "fake-1" and s.specificity == 4
    p2 = FakeProvider()
    res2 = score_prompts(db, cfg, p2)
    assert res2.scored == 0 and p2.calls == []


def test_identical_text_is_scored_once(db):
    seed(db, [LONG[0], LONG[0]])
    p = FakeProvider()
    res = score_prompts(db, Config(), p)
    assert res.scored == 2 and res.cached == 1 and len(p.calls) == 1


def test_retry_then_single_fallback(db):
    seed(db, LONG[:2])
    p = FakeProvider(
        [
            {"results": [{"id": "0", "specificity": 9}]},  # invalid
            ValueError("not json"),  # retry fails too
            {"results": [good("0", 2)]},  # one-at-a-time
            {"results": [good("0", 5)]},
        ]
    )
    res = score_prompts(db, Config(), p)
    assert res.scored == 2 and res.failed == 0
    assert len(p.calls) == 4
    assert "error" in p.calls[1]  # retry includes the validation error
    assert sorted(s.specificity for s in db.query(PromptScore)) == [2, 5]


def test_limit(db):
    seed(db, LONG)
    res = score_prompts(db, Config(), FakeProvider(), limit=2)
    assert res.scored == 2


def test_cloud_providers_require_confirmation(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    with pytest.raises(CloudNotConfirmedError):
        get_provider(Config(llm_provider="groq"))
    assert get_provider(Config(llm_provider="groq", send_to_cloud_confirmed=True)).name == "groq"


def test_cloud_provider_needs_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        get_provider(Config(llm_provider="gemini", send_to_cloud_confirmed=True))


def test_ollama_provider_parses_response():
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "m" and body["stream"] is False
        return httpx.Response(200, json={"message": {"content": '{"results": []}'}})

    p = OllamaProvider("http://x", "m", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert p.complete_json("sys", "user", {}) == {"results": []}
