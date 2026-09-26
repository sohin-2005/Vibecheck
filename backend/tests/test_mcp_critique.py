from vibecheck.mcp.critique import critique_prompt


def test_vague_prompt_gets_missing_items_and_rewrite():
    out = critique_prompt("fix the login bug")
    assert "which file(s) or folder" in out
    assert "the error message or what happens now" in out
    assert 'what "done" looks like' in out
    assert "In [file or folder], fix the login bug." in out
    assert "Done when: [the test or check that proves it works]." in out
    assert "asking the user" in out


def test_specific_prompt_passes():
    out = critique_prompt("In src/cli.py, add a --json flag; tests/test_cli.py should pass")
    assert "specific enough" in out
    assert "Could be" not in out


def test_empty_and_pasted_only_prompts():
    assert "empty" in critique_prompt("   ")
    assert "empty" in critique_prompt("<pasted_content>big log</pasted_content>")
