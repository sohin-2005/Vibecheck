import json
import os
from pathlib import Path

from vibecheck.ingest.redact import Redactor
from vibecheck.mcp.locate import encode_project_dir, find_session_file, same_dir
from vibecheck.mcp.render import MAX_CHARS, finish, relative


def _session(folder: Path, name: str, cwd: str, mtime: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{name}.jsonl"
    p.write_text(json.dumps({"type": "user", "cwd": cwd, "sessionId": name}) + "\n", "utf-8")
    os.utime(p, (mtime, mtime))
    return p


def test_encode_windows_and_posix_paths():
    assert (
        encode_project_dir(r"C:\Users\User\Desktop\Vibecheck") == "C--Users-User-Desktop-Vibecheck"
    )
    assert encode_project_dir("/work/my_app.v2") == "-work-my-app-v2"


def test_same_dir_ignores_case_separators_and_trailing_slash():
    assert same_dir(r"C:\Work\App", "c:/work/app/")
    assert not same_dir("", "/work/app")
    assert not same_dir("/work/app2", "/work/app")


def test_picks_newest_file_in_encoded_folder_ignoring_case(tmp_path):
    projects = tmp_path / "projects"
    folder = projects / "c--work-app"  # drive letter case differs on disk
    _session(folder, "old", r"C:\work\app", 1000)
    new = _session(folder, "new", r"C:\work\app", 2000)
    assert find_session_file(projects, Path(r"C:\work\app")) == new


def test_session_id_selects_a_specific_file(tmp_path):
    folder = tmp_path / "projects" / "-work-app"
    old = _session(folder, "old", "/work/app", 1000)
    _session(folder, "new", "/work/app", 2000)
    assert find_session_file(tmp_path / "projects", Path("/work/app"), "old") == old
    assert find_session_file(tmp_path / "projects", Path("/work/app"), "../x") is None


def test_falls_back_to_cwd_match_when_folder_name_differs(tmp_path):
    projects = tmp_path / "projects"
    mine = _session(projects / "renamed", "s1", "/work/app/", 1000)
    _session(projects / "other", "s2", "/work/other", 3000)
    assert find_session_file(projects, Path("/work/app")) == mine


def test_missing_dirs_return_none(tmp_path):
    assert find_session_file(tmp_path / "nope", Path("/work/app")) is None
    (tmp_path / "projects").mkdir()
    assert find_session_file(tmp_path / "projects", Path("/work/app")) is None


def test_relative_paths_never_absolute():
    assert relative("/work/app/src/core.py", Path("/work/app")) == "src/core.py"
    assert relative(r"C:\Work\App\src\core.py", Path("c:/work/app")) == "src/core.py"
    assert relative("/elsewhere/secret/x.py", Path("/work/app")) == "x.py"


def test_finish_redacts_and_caps_length():
    out = finish("key sk-test1234567890abcdefghijkl " + "x" * 5000, Redactor())
    assert "[REDACTED:api_key]" in out and "sk-test" not in out
    assert len(out) <= MAX_CHARS and out.endswith("…")
