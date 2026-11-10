"""What a reasoner or a post-compaction coder is handed about earlier work: the harness summary wherever the harness put it, the action log with
refused calls labelled and unattributable results counted, and the fenced text the coder was shown."""
import json

import pytest

from cria import bodykeys, denial, loop, prompts, wsview
from cria.fetchfacts import Shape


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def call(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def res(cid, text, outcome=None):
    m = {"role": "tool", "content": text}
    if cid:
        m["tool_call_id"] = cid
    if outcome:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


def test_the_summary_is_the_reanchored_user_turn_when_the_harness_kept_the_task_else_the_root():
    summary = {"role": "user", "content": f"{loop.CONTINUATION_MARKER} earlier work"}
    msgs = [{"role": "user", "content": "the task"}, {"role": "assistant", "content": "x"}, summary, {"role": "user", "content": "go on"}]
    assert loop._rewrite_summary_text(msgs, "ROOT") == f"{loop.CONTINUATION_MARKER} earlier work"
    assert loop._rewrite_summary_text(msgs[:2], "ROOT") == "ROOT"
    parts = {"role": "user", "content": [{"type": "text", "text": f"{loop.CONTINUATION_MARKER} in parts"}]}
    assert loop._rewrite_summary_text([parts], "ROOT") == f"{loop.CONTINUATION_MARKER} in parts"


def test_the_action_log_labels_only_calls_cria_refused_and_counts_results_it_cannot_attribute():
    refused_call = call("c2", "write_file", path="b.py", content="2")
    msgs = [call("c1", "write_file", path="a.py", content="1"), res("c1", "Wrote a.py"),
            refused_call, res("c2", "not allowed", denial.REFUSED),
            res(None, f"quoting {denial.DENIED_MARKER} with no call id")]
    log = Log()
    text = loop._work_log(msgs, rlog=log)
    lines = text.splitlines()
    assert any(l.startswith("$ write_file {") and "a.py" in l and prompts.load("work_log_denied") not in l for l in lines)
    assert any(l.startswith("$ write_file") and "b.py" in l and l.endswith(prompts.load("work_log_denied")) for l in lines)
    assert "  -> Wrote a.py" in lines and "  -> not allowed" in lines
    assert log.events == [("loop.work_log_denied", {"level": "info", "labelled": 1, "unpaired": 1})]
    quiet = Log()
    loop._work_log(msgs[:2], rlog=quiet)
    assert quiet.events == []                                                                   # nothing refused, nothing unattributable: no event


def test_everything_the_coder_was_shown_includes_fetched_response_shapes_and_every_tool_result():
    shapes = {"https://api.x/openapi.json": ("HTTP 200", (), (Shape("GET /h", route="/h", fields=("hex",)),), ())}
    sess = type("S", (), {"fetched_pages": shapes})()
    shown = loop._injected_fence_texts(sess, [res("t", "a file body"), res("u", "  "), {"role": "user", "content": "not a result"}])
    assert shown == ["GET /h", "a file body"]
    assert loop._injected_fence_texts(type("S", (), {"fetched_pages": {"u": ("HTTP 200", (), (), ())}})(), []) == []
    assert loop._injected_fence_texts(None, None) == []


@pytest.mark.parametrize("reply,pasted", [
    ("```\n" + "\n".join(f"line {i} of a bare-fenced file" for i in range(14)) + "\n```", True),   # a fence with no language tag still opens a file
    ("```\nshort\n```", False)])
def test_a_bare_fence_with_nothing_open_is_read_as_an_opening_fence(reply, pasted):
    assert loop.unexecuted_write(reply) is pasted


def test_the_first_survey_is_remembered_once_and_only_when_a_survey_has_landed(tmp_path):
    (tmp_path / "a.py").write_text("x")
    root, sess = str(tmp_path), type("S", (), {})()
    for note in (loop._note_survey_baseline, loop._note_first_survey_files):
        token = wsview.bind(wsview.View(root, "s"))                                                # nothing surveyed yet
        try:
            note(sess, root)
            note(sess, "")
        finally:
            wsview.unbind(token)
    assert not hasattr(sess, "survey_baseline") and not hasattr(sess, "first_survey_files")
    sess.survey_baseline, sess.first_survey_files = {"kept": (1, 1.0)}, {"kept"}
    token = wsview.bind(wsview.DirectView(root))
    try:
        loop._note_survey_baseline(sess, root)
        loop._note_first_survey_files(sess, root)
    finally:
        wsview.unbind(token)
    assert sess.survey_baseline == {"kept": (1, 1.0)} and sess.first_survey_files == {"kept"}       # once per session
