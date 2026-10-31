"""K4 — the `unexecuted_write` nudge said "your last message contained the file's contents as text … send
that same content again as a write tool call" about ANY file-length code block, and named no file. phi4 A4
CALL 0079: a plan with a 5-line `<dependency>` excerpt and an 18-line REVIEW.md draft was answered with it, and
CALL 0080 wrote a fabricated whole pom.xml. Census over every captured call-less coder reply with a fenced
block (691): the nudge's test fires on 293; for 141 of them (48%) the model bound the first file-length block
to no file, or to two — the nudge had no file to be talking about; the ones sampled were pseudo-code, a plan's
"final message", a one-function sketch. Now: a block the pasted-file judge ruled `OTHER` draws no nudge; a
block bound to exactly one path names it; anything else is told what is true (a block of code was sent as
text) and no file is claimed.
"""
import json
from pathlib import Path

from cria import loop
from tests.test_loop import _single_loop, _synth
from tests import test_text_write_recovery as tw

R = json.loads((Path(__file__).parent / "fixtures" / "phi4_java_a4" / "k4-pasted-replies.json").read_text())


def _lp(reply=""):
    return _single_loop(lambda b, r: json.dumps({"choices": [{"message": {
        "role": "assistant", "content": reply}, "finish_reason": "stop"}]}).encode(),
        workspace_root="/ws")


def _nudge_for(reply):
    lp, sess, log = _lp(reply), _synth(), tw._Log()
    lp._coder_turn(sess, {"messages": []}, {"messages": []}, step=1, rlog=log)
    return lp._unexecuted_nudge_text(sess)


def test_a_block_bound_to_one_path_names_that_path_and_no_other():
    text = _nudge_for(R["0079"])
    assert "contents of `REVIEW.md`" in text and "write tool call for `REVIEW.md`" in text
    assert "pom.xml" not in text


def test_a_block_bound_to_no_file_claims_no_file():
    reply = R["0118"]
    assert loop.unexecuted_write(reply)                        # the structural test still fires on it
    assert loop._pasted_block_paths(reply) == []
    text = _nudge_for(reply)
    assert "contents" not in text and "that same content" not in text
    assert "no write tool call was made" in text and "names the file" in text
    assert "cria" not in text.lower()


def test_no_reply_does_not_invent_an_unsaved_block():
    assert _nudge_for("") == ""


def _judged(verdict):
    t = tw.TextWriteTests("test_the_a1_pasted_class_becomes_that_files_write_and_the_pom_excerpt_never_does")
    t.setUp()
    try:
        content, tools, fin = tw._reply("a1_0022")
        _ch, calls, _asked, log, sess = t.turn(content, tools, fin, judge=verdict)
        return content, calls, log, sess
    finally:
        t.doCleanups()


def test_a_block_the_judge_ruled_other_draws_no_nudge():
    content, calls, log, sess = _judged("OTHER")
    assert calls == [] and log.get("loop.text_write_refused")["reason"] == "judged_other"
    assert loop.unexecuted_write(content)                      # fired before K4
    # The shared coder turn has already consumed OTHER at redrive admission.
    assert "loop.unexecuted_write" not in log.kinds()
    assert sess.pasted_pending_nudge is None
    assert sess.unexecuted_nudges == 0
    assert _lp()._unexecuted_nudge_text(sess) == ""


def test_an_unruled_or_whole_file_block_still_draws_the_nudge():
    content, calls, log, sess = _judged("")                    # judge gave no answer: no ruling
    assert "loop.unexecuted_write" in log.kinds()
    assert sess.unexecuted_nudges == 1
    text = _lp()._unexecuted_nudge_text(sess)
    assert "contents of `Importer.java`" in text
    assert "write tool call for `Importer.java`" in text


def test_the_other_ruling_does_not_suppress_the_next_unruled_reply():
    _content, _calls, _log, sess = _judged("OTHER")
    t = tw.TextWriteTests("test_the_a1_pasted_class_becomes_that_files_write_and_the_pom_excerpt_never_does")
    t.setUp()
    try:
        _c, tools, fin = tw._reply("a1_0022")
        _ch, calls, _asked, log, sess = t.turn(R["0118"], tools, fin, sess=sess)
        assert calls == []
        assert "loop.unexecuted_write" in log.kinds()
        assert sess.unexecuted_nudges == 1
        assert _lp()._unexecuted_nudge_text(sess) == loop.prompts.load("unexecuted_write_nudge")
    finally:
        t.doCleanups()
