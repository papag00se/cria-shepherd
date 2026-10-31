"""A delivered steer may not state a false disk fact, an invented requirement, or imitate cria's own earlier output."""
from types import SimpleNamespace

import pytest
from cria import loop, selfcompact
from cria.indicators import SENTINEL
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

TASK = "Resolve an Ada Handle to the Cardano address using api.handle.me. Unit tests are required, plus a live test."

@pytest.fixture
def workspace(tmp_path):
    """pyproject.toml at 15 lines and tests/resolve_test.py at 64: the counts the author's prompt carried."""
    (tmp_path / "pyproject.toml").write_text("\n".join(f"# {i}" for i in range(15)))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "resolve_test.py").write_text("\n".join(f"# {i}" for i in range(64)))
    return str(tmp_path)

@pytest.mark.parametrize("steer,refuted", [
    ("Fix it by deleting lines 23-24 from pyproject.toml.", True),                 # steer 0222: the file has 15 lines
    ("Two identical blocks start on lines 30 and 98.", True),                      # steer 0218: no file has 98 lines
    ("Remove them at lines 19-20 and rerun the tests.", False),                    # could be true: silence
    ("Move both keys on lines 40-41 of pyproject.toml.", True),                    # a named file binds tighter...
    ("Move both keys on lines 40-41 of resolve_test.py.", False),                  # ...40 fits its 64 lines
])
def test_a_steer_citing_lines_beyond_the_file_it_names_is_refused(workspace, steer, refuted):
    """ada-handles gemma4 run (1/4): steers cited 'line 245' and 'lines 95-99 in resolve_test.py' (64 lines); only the
    colon form was caught."""
    found = loop._false_line_citation(steer, workspace, ["pyproject.toml", "tests/resolve_test.py"])
    assert (found is not None) is refuted

@pytest.mark.parametrize("task,answer,refuted,asked", [
    (TASK, "REFUTED", True, True),                                  # an invented "your API key" over HTTP 200 fetches
    (TASK, "STANDS", False, True),
    (TASK + " Use the api key I gave you.", "REFUTED", False, False),   # the task names a key: the claim has a source
])
def test_an_auth_requirement_the_evidence_does_not_show_is_asked_about_not_delivered(task, answer, refuted, asked):
    """Steer 0191 told the coder to keep a task-required live test mocked 'without your API key' in a session whose
    every fetch was HTTP 200."""
    sess = SimpleNamespace(plan=SimpleNamespace(task=task), fetched_pages={"https://api.handle.me/x": ("HTTP 200", (), (), (), "")})
    questions = []
    steer = "Don't add live network calls here, they will fail without your API key; keep tests mocked."
    result = loop._steer_auth_refuted(steer, "all fetches clean", sess, lambda system, _u: questions.append(system) or answer, Log())
    assert result is refuted and bool(questions) is asked

SESSION = [{"role": "user", "content": "Resolve an Ada Handle."},
           {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
               "name": "exec_command", "arguments": '{"cmd": "python live_test.py"}'}}]},
           {"role": "tool", "tool_call_id": "c1", "content": "Chunk ID: 368902\nWall time: 0.0000 seconds\n"
            "Process exited with code 127\nOriginal token count: 12\nOutput:\n/bin/bash: python: command not found"}]

def test_the_steer_author_reads_no_imitable_syntax_and_cria_s_own_words_are_labelled_not_evidence():
    """mellum2 run: shown tool-call syntax 50x and the harness envelope 24x, the author answered with a fabricated
    exec_command + invented Chunk ID/address, which cria delivered as a steer. A prior steer re-entering as evidence
    is a feedback loop (a four-way flip-flop cost 83 edits), so cria's own lines are labelled."""
    seen = []
    chat = lambda body, rlog: seen.append(body) or b'{"choices":[{"message":{"content":"some steer"}}]}'
    history = SESSION + [{"role": "user", "content": f"{SENTINEL} steered the coder - flail"}]
    loop.author_steer(chat, None, None, loop.GuardState(), {"messages": history, "tools": []}, Log(), condition="wheel_spin")
    sent = str(seen[-1]["messages"])
    assert "exec_command(" not in sent and "Chunk ID:" not in sent and "Wall time:" not in sent
    for fact in ("exec_command", "python live_test.py", "command not found"):
        assert fact in sent                                   # the shape goes, never the facts
    assert "EARLIER NOTE FROM THIS SYSTEM" in sent
    own = [f"x {m} y" for m in (loop.CONTINUATION_MARKER, selfcompact.SUMMARY_MARKER, SENTINEL, "⟦ctx:steer⟧")]
    assert all("EARLIER NOTE" in loop._mark_own_notes(line) for line in own)
    coders = ["the coder said: the endpoint only supports search_handles", "→ exit 2: ImportError", ""]
    assert [loop._mark_own_notes(line) for line in coders] == coders
