"""The harness's 'another language model' compaction turn, re-presented as the coder's own: what a recorded hardener output (known origin)
changes — the dropped-prose arms — versus a copy anyone could have typed, and the small helpers around the preamble and the step frame."""
import pytest

from cria import loop, wsview

MARKER, BOUNDARY, DROPPED = loop._COMPACTION_MARKER, loop._COMPACTION_BOUNDARY, loop._PROSE_DROPPED_MARKER


def turn(summary):
    return [{"role": "user", "content": "task"}, {"role": "user", "content": f"{MARKER} and left a handoff.\n{BOUNDARY}\n{summary}"}]


@pytest.mark.parametrize("reply,known,needle,absent", [
    (f"{DROPPED}\nFILES: a.py (3 B)", True, "re-derived AT THE TIME", "ungrounded account"),     # no prose survived, only the appendices
    (DROPPED, True, "No prior-session account is available", "re-derived AT THE TIME"),           # nothing survived at all
    (f"{DROPPED}\nFILES: a.py (3 B)", False, "ungrounded account", "re-derived AT THE TIME"),     # a copy cria never produced is no authority
    ("Built a.py.", True, "ungrounded account", "did not survive"),
])
def test_only_a_handoff_cria_produced_can_say_its_prose_was_dropped(reply, known, needle, absent):
    origin = loop._HandoffOrigin(reply, "", reply.startswith(DROPPED))
    out, hit = loop.reframe_compaction(turn(reply), origin=origin if known else None)
    content = out[-1]["content"]
    assert hit and content.startswith(loop.CONTINUATION_MARKER) and needle in content and absent not in content
    assert DROPPED not in content and "Another language model" not in content
    assert (origin.continuation == content) is known


def test_an_empty_workspace_inverts_the_reframe_and_a_boundary_less_marker_line_is_still_removed(tmp_path):
    env = {"role": "user", "content": f"<environment_context><cwd>{tmp_path}</cwd></environment_context>"}
    msgs = [env, {"role": "user", "content": f"{MARKER}, then:\nSummary body"}]
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        out, hit = loop.reframe_compaction(msgs)
    finally:
        wsview.unbind(token)
    assert hit and "Summary body" in out[-1]["content"] and "is EMPTY right now" in out[-1]["content"]
    assert "Another language model" not in out[-1]["content"]
    bare = loop.reframe_compaction([{"role": "user", "content": MARKER}])[0][0]["content"]       # no newline at all: no summary
    assert "did not survive" in bare


def test_small_preamble_and_step_helpers(tmp_path):
    assert loop._tag_body("<cwd>/w</cwd><cwd>x</cwd>", "cwd") == "/w" and loop._tag_body("<cwd>/w", "cwd") is None
    assert loop._tag_body("</cwd>a<cwd>", "cwd") is None and loop._tag_body("none", "cwd") is None
    assert loop._squash("  a \n b\t c ") == "a b c"
    assert loop._msg_text_content({"content": [{"text": "a"}, {"text": "b"}, "junk"]}) == "a b"
    assert loop._caller_span_hint(-1, "p") == {}
    hint = list(loop._caller_span_hint(5, "persona").values())[0]
    assert hint["text"] == "persona" and hint["start"] == len(loop.prompts.load("coder_system")) + 2 + 5
    assert loop.step_artifacts_on_disk("", str(tmp_path)) == [] and loop.step_artifacts_on_disk("edit a.py", None) == []
    (tmp_path / "a.py").write_text("x")
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        got = loop.step_artifacts_on_disk(f"edit a.py then a.py again, create b.py, read ../../etc/x.py", str(tmp_path))
    finally:
        wsview.unbind(token)
    assert got == ["a.py"]
    assert loop._reframe_preamble_text("just a user message") is None
