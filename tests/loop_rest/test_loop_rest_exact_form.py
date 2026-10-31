"""A blocked write says exactly what was measured from the CURRENT file; only a confirmed exact-form requirement vetoes
an approval (C13-C nosession 0018: a 29-byte file was approved for a task requiring 30 bytes, a final line break)."""

import json
import re

import pytest

from cria import bodykeys, denial, filefacts, loop, wsview
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401

TASK = 'Create probe.txt containing exactly these lines, including the final newline:\nsnow 雪\n"quoted"\nbackslash \\\n'
C29 = 'snow 雪\n"quoted"\nbackslash \\'
C30 = C29 + "\n"
APPROVE = json.dumps({"satisfied": True, "reason": "matches", "proposed_fix": "", "diagnosis_kind": "",
                      "subject": "", "task_quote": "", "evidence_source": "", "evidence_quote": ""})
FOCUSED, CONFIRM, BYTES = ("QUESTION: does the task fix, in exact terms", "QUESTION: does the quote itself state",
                           "QUESTION: does the quote itself fix the EXACT size")


def call(cid, name, args): return {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}

def result(cid, text, outcome=None):
    return {"role": "tool", "tool_call_id": cid, "content": text, **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}

def write(cid, content, path="probe.txt", refused=False):
    res = result(cid, denial.DENIED_MARKER + " refused", denial.REFUSED) if refused else \
        result(cid, json.dumps({"written": True, "bytes": len(content.encode())}), denial.LANDED)
    return [call(cid, "write_file", {"path": path, "content": content}), res]

def edit(cid="e", path="probe.txt", name="edit_file"):
    return [call(cid, name, {"path": path, "old_string": "a", "new_string": "b"}), result(cid, "ok", denial.LANDED)]

def shell(cmd, cid="s"): return [call(cid, "exec_command", {"cmd": cmd}), result(cid, "")]

def facts(msgs, root=""): return filefacts.extract(loop._satisfaction_evidence(msgs, workspace_root=root))


def test_facts_describe_the_current_content_or_stay_silent(tmp_path):
    """Counts of what was SENT are history; only a file nothing has since touched is stated."""
    rows = [(write("w", C29), "probe.txt (as last written): 29 bytes, 2 line break(s), the content does NOT end"),
            (write("w1", C29) + write("w2", C30), "30 bytes, 3 line break(s), the content ends with"),
            (write("w1", "x", path="./probe.txt") + write("w2", C30), "30 bytes"),       # ./probe.txt and probe.txt are one path
            (write("w", C29) + edit() + edit("e2", name="apply_patch"), ""),            # a later landed edit
            (write("w", C29) + shell("echo >> probe.txt"), ""), (shell("printf 'a' > probe.txt"), ""),
            (write("w", C29, refused=True), "")]                                          # a refused write was never sent
    for msgs, expected in rows:
        got = facts(msgs)
        assert (expected in got) if expected else got == "", expected
    assert facts(rows[2][0]).count("\n- ") == 1 and "29 bytes" not in facts(rows[1][0])
    disk = tmp_path / "probe.txt"
    disk.write_bytes(C30.encode())            # the disk outranks what an old write payload said
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        assert "(on disk): 30 bytes, 3 line break(s)" in facts(write("w", C29, path=str(disk)), str(tmp_path))
    finally:
        wsview.unbind(token)


class Chat:
    """Scripted focused judge (it only EXTRACTS), exact-size confirmer and state confirmer."""

    def __init__(self, focused, states="ends_with_break", exact="same"):
        self.focused, self.states, self.exact, self.asked = focused, states, exact, 0

    def __call__(self, body, _rlog):
        system = body["messages"][0]["content"]
        if BYTES in system:
            fixed = re.findall(r"exactly (\d+) bytes", system)
            content = "no idea" if self.exact == "unreadable" else json.dumps(
                {"exact_bytes": int(fixed[0]) if fixed and self.exact == "same" else self.exact})
        elif CONFIRM in system:
            content = json.dumps({"states": self.states})
        elif FOCUSED in system:
            self.asked += 1
            content = self.focused.pop(0) if isinstance(self.focused, list) else self.focused
        else:
            content = APPROVE
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def extraction(quote="including the final newline", bytes_=None, ends=True, file="probe.txt"):
    return json.dumps({"quote": quote, "file": file, "bytes": bytes_, "ends_with_line_break": ends})


def judge(msgs, focused=None, task=TASK, **kw):
    chat = Chat(focused or extraction(), **kw)
    sat, reason, _ = loop.judge_satisfaction(task, loop._satisfaction_evidence(msgs), chat, None, Rlog(), workspace_root="")
    return sat, reason, chat


def test_the_original_incident_29_bytes_is_blocked_with_the_measured_counts():
    """The approving verdict is put to ONE focused question; the refusal quotes what is on disk."""
    sat, reason, chat = judge(write("w", C29))
    assert not sat and chat.asked == 1
    assert "probe.txt (as last written): 29 bytes, 2 line break(s), the content does NOT end" in reason
    assert judge(write("w1", C29) + write("w2", C30))[0] and judge(write("w", C29) + edit())[0]  # rewritten / edited later: no veto


EXACT16 = ("Create probe.txt of exactly 16 bytes.", extraction("exactly 16 bytes", 16, None))


@pytest.mark.parametrize("task, focused, kw, vetoes", [
    (*EXACT16, {}, True),                                                    # 29 != 16: arithmetic on the counts
    (*EXACT16, {"exact": 17}, False),                                        # a confirmation naming another number
    (*EXACT16, {"exact": "unreadable"}, True),                               # unreadable confirmation fails closed
    ("Keep it under 100 lines.", extraction("under 100 lines", 100, None), {"exact": None}, False),   # a number that is not a size
    ("Add probe.txt describing the risks.", extraction("describing the risks", 30, None), {}, False),   # a mis-copied count
    (TASK, extraction(), {"states": "ends_without_break"}, False),           # a confirmation saying the opposite
    (TASK, extraction("the file must be 3219 bytes"), {}, False),            # a quote the task never made
    (TASK, ["garbage", "still garbage"], {}, True),                          # two unreadable answers: not satisfied
])
def test_only_a_confirmed_exact_form_requirement_vetoes_an_approval(task, focused, kw, vetoes):
    """The judge only EXTRACTS the figure; cria compares. Unconfirmed, mis-copied or unreadable ⇒ no veto /fail closed."""
    sat, reason, chat = judge(write("w", C29), focused, task, **kw)
    assert (not sat) is vetoes
    if isinstance(focused, list):
        assert chat.asked == 2
