"""Wave 9 coverage: `editrecovery.recover` over hand-built fact-reports (the shapes the lowered edit program can print).

A report that is cut, corrupt, or not an object is said in words (never shipped as base64); a miss with an anchor but no
line number makes no claim about a line; the harness's order note is rewritten in cria's words above the directive; the
escalation event is logged once per turn for count-driven and blind-touch escalations but not for self-resolving modes.
"""
import base64
import json

import pytest

from cria import editrecovery as er


def token(report, packed=False):
    raw = json.dumps(report).encode()
    return er.EDITFAIL + (er.PACKED_PREFIX + base64.b64encode(__import__("zlib").compress(raw)).decode() if packed else base64.b64encode(raw).decode())


def steered(path, n):
    return [{"role": "tool", "content": f"{er.EDIT_MARK} {path} — failed"} for _ in range(n)]


class Log:
    def __init__(self): self.events = []
    def emit(self, kind, **f): self.events.append((kind, f))


@pytest.mark.parametrize("bad", [er.EDITFAIL + base64.b64encode(b"[1, 2]").decode(), er.EDITFAIL + "!!not-base64!!",
                                 er.EDITFAIL + er.PACKED_PREFIX + base64.b64encode(b"not zlib").decode()])
def test_a_report_that_is_cut_corrupt_or_not_an_object_is_said_in_words_and_the_base64_never_ships(bad):
    out = er.recover("Warning: truncated output\n" + bad, [])
    assert out.startswith("Warning: truncated output\n") and "report naming the exact mismatch was cut" in out
    assert "base64" not in out and bad[len(er.EDITFAIL):][:12] not in out


def test_an_anchor_without_a_line_makes_no_claim_about_a_line_and_a_packed_report_reads_the_same():
    msgs = [{"role": "tool", "content": "read f.txt"}, {"role": "assistant", "content": "ok", "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path": "f.txt"}'}}]}]
    for line in (None, 0, ""):
        out = er.recover(token({"path": "f.txt", "anchor": "real text", "line": line}, packed=bool(line == 0)), msgs)
        assert "real text" in out and "at LINE" not in out and "LINE ?" not in out
    with_line = er.recover(token({"path": "f.txt", "anchor": "real text", "line": 7}), msgs)
    assert "LINE 7" in with_line


def test_the_order_note_is_rewritten_above_the_directive_and_escalation_is_logged_once_per_turn_unless_self_resolving():
    log = Log()
    out = er.recover(f"{er.ORDER_LATE}\n" + token({"path": "/w/f.txt", "anchor": "a", "line": 3, "current": "FULL"}), [], log)
    assert er.ORDER_LATE not in out and out.startswith("This call ran before one or more calls you sent ahead")
    assert log.events == [("editrecovery.escalated", {"path": "f.txt", "fails": 1, "blind": True})]       # never read: the blind first miss escalates
    log.events.clear()
    er.recover(token({"path": "/w/f.txt", "mode": "phantom", "anchor": "a"}), [], log)                    # self-resolving: no event
    er.recover(token({"path": "/w/f.txt", "anchor": "a", "line": 3}), [], log)
    assert [k for k, _ in log.events] == ["editrecovery.escalated"]
    log.events.clear()
    er.recover(token({"path": "", "anchor": "a", "line": 3}), steered("f.txt", 2), log)                   # no identifiable file: not blind, 1st miss: surgical
    assert log.events == []


@pytest.mark.parametrize("fail", [{"mode": "phantom", "path": "a.py", "anchor": "x"}, {"mode": "would_break", "path": "a.py"},
                                  {"mode": "multi", "path": "a.py", "n": 3}, {"mode": "multi_flex", "path": "a.py"},
                                  {"mode": "identical", "path": "a.py"}])
def test_a_self_resolving_miss_is_answered_the_same_however_many_times_the_file_already_failed(fail):
    """MUT2 (editrecovery survivor): old_string==new_string, a phantom anchor, an ambiguous match ... are complete facts on their own;
    only the can't-pin-the-text family escalates with the clock, and then it says STOP."""
    assert er.compose(fail, 0) == er.compose(fail, er.ESCALATE_AFTER + 6) and "STOP editing it." not in er.compose(fail, 9)
    assert "STOP editing it." in er.compose({"mode": "anchor", "path": "a.py", "current": "c"}, 9)


def test_a_file_the_coder_wrote_is_grounded_without_ever_being_read_and_an_untouched_one_is_blind():
    from cria import prompts
    wrote = [{"role": "tool", "content": prompts.render("write_confirm", path="src/a.py").strip()}]
    assert er._is_grounded_in(wrote, "a.py") and not er._is_grounded_in(wrote, "b.py") and not er._is_grounded_in([], "a.py")
