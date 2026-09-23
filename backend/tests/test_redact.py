import pytest

from promptlens.ingest.redact import Redactor

R = Redactor()


@pytest.mark.parametrize(
    ("text", "kind", "secret"),
    [
        ("key AKIAABCDEFGHIJKLMNOP here", "aws_key", "AKIAABCDEFGHIJKLMNOP"),
        (
            "use sk-proj-abcdefghijklmnopqrstuvwx1234",
            "api_key",
            "sk-proj-abcdefghijklmnopqrstuvwx1234",
        ),
        (
            "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA",
            "api_key",
            "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA",
        ),
        (
            "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "api_key",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        ),
        (
            "gho_abcdefghijklmnopqrstuvwxyz0123456789",
            "api_key",
            "gho_abcdefghijklmnopqrstuvwxyz0123456789",
        ),
        ("xoxb-123456789012-abcdefABCDEF", "api_key", "xoxb-123456789012-abcdefABCDEF"),
        (
            "AIzaSyA1234567890abcdefghijklmnopqrstu",
            "api_key",
            "AIzaSyA1234567890abcdefghijklmnopqrstu",
        ),
        (
            "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "jwt",
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
        ),
        ("DB_PASSWORD=hunter2", "assignment", "hunter2"),
        ("export API_KEY='abc123def'", "assignment", "abc123def"),
        ('SECRET: "s3cr3t-value"', "assignment", "s3cr3t-value"),
        ("GITHUB_TOKEN=ghx_notreallyatoken", "assignment", "ghx_notreallyatoken"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----",
            "private_key",
            "MIIEow",
        ),
        ("postgres://admin:pa55word@db.example.com:5432/x", "conn_string", "pa55word"),
        ("mongodb+srv://u:secret@cluster0.x.net", "conn_string", "secret"),
    ],
)
def test_default_patterns(text, kind, secret):
    out = R.redact(text)
    assert secret not in out
    assert f"[REDACTED:{kind}]" in out


@pytest.mark.parametrize(
    "text",
    [
        "Fix the login bug in src/auth.py",
        "the key point is that sk is short",
        "password field should be required",
        "PASSWORD_MIN_LENGTH is 8",
        "set token expiry to 30 minutes",
        "https://github.com/obra/superpowers",
        "postgresql+psycopg://localhost:5432/promptlens",
        "desk-lamp and task-runner are fine",
        "AKIA is a prefix but AKIA123 is too short",
        "eyJ alone is not a jwt",
        "if (password === confirm) {",
    ],
)
def test_no_false_positives(text):
    assert R.redact(text) == text


def test_keeps_variable_name_in_assignment():
    assert R.redact("DB_PASSWORD=hunter2") == "DB_PASSWORD=[REDACTED:assignment]"


def test_connection_string_keeps_host():
    out = R.redact("postgres://admin:pa55word@db.example.com/x")
    assert out == "postgres://admin:[REDACTED:conn_string]@db.example.com/x"


def test_extra_patterns():
    r = Redactor(extra_patterns=[r"ACME-\d{6}"])
    assert r.redact("id ACME-123456 ok") == "id [REDACTED:custom] ok"


def test_disabled_is_noop():
    assert Redactor(enabled=False).redact("AKIAABCDEFGHIJKLMNOP") == "AKIAABCDEFGHIJKLMNOP"


def test_none_passthrough():
    assert R.redact(None) is None


def test_redact_json_walks_nested_values():
    data = {"a": ["x AKIAABCDEFGHIJKLMNOP"], "b": {"c": "PASSWORD=zzz"}, "n": 3}
    out = R.redact_json(data)
    assert out == {
        "a": ["x [REDACTED:aws_key]"],
        "b": {"c": "PASSWORD=[REDACTED:assignment]"},
        "n": 3,
    }
    assert data["a"] == ["x AKIAABCDEFGHIJKLMNOP"]  # input not mutated
