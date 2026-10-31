"""Pasted-file lifecycle through the real Loop.drive (plan-off), over a real workspace dir: only the model boundaries are fakes.
What the scenario file does not hold: which result facts settle a delivery, whose result is whose, which transport outcomes deliver,
what an interrupted or competing re-drive costs, and what a restart forgets."""
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, bodykeys, config, denial, generation, loop as loop_mod, wsview
from cria.loop import MAX_UNEXECUTED_NUDGES, LoopStore
from cria.upstream import UpstreamProtocolError

from loop_main_helpers import Chat, Rlog, body, completion, plan_off_loop, synthetic, loop_main_local_view  # noqa: F401
from test_loop_main_scenario_pasted_file import CODING, LINES, SHELL, TASK, WRITE

PASTED = completion("Here is the file `app.py`:\n```python\n" + "\n".join(LINES) + "\n```\nDone.")
ACT = completion(None, ("shell", {"command": ["true"]}))
JUDGE = lambda answer: (lambda b, r: json.dumps(completion(answer)).encode())   # noqa: E731
ROLE = config.Role(name="reasoner", backend="local")


class Coder(Chat):
    """A coder boundary that can also fail: an exception in the script is raised as the provider's own error."""
    def __call__(self, b, rlog):
        self.bodies.append(b)
        step = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(step, BaseException):
            raise step
        return json.dumps(step).encode()


def rig(tmp_path, *script, judge="WHOLE_FILE", store=None):
    coder, store = Coder(*script), store or LoopStore()
    return plan_off_loop(coder, store=store, reasoner=JUDGE(judge), workspace_root=str(tmp_path), reasoner_role=ROLE, assists=True), coder, store


def paste(loop, key, held, tmp_path, admit=True):
    """One drive that recovers the paste; the transport's finalization callback is kept in ``held``. Returns (reply, call, admitted)."""
    out = loop.drive(body(TASK, tools=[WRITE, SHELL]), key, CODING, Rlog(), pasted_delivery=held.append)
    call = out["choices"][0]["message"]["tool_calls"][0]
    content = json.loads(call["function"]["arguments"])["content"]
    return out, call, {call["id"]: SimpleNamespace(path=str(tmp_path / "app.py"), content=content)} if admit else {}


def result_turn(loop, key, call, **message):
    messages = [{"role": "user", "content": TASK}, {"role": "assistant", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": call["id"], "content": "x", **message}]
    return loop.drive({**body(TASK, tools=[WRITE, SHELL]), "messages": messages}, key, CODING, Rlog())


@pytest.mark.parametrize("facts,expected", [({bodykeys.RESULT_OUTCOME: denial.REFUSED}, (False, False)),
                                            ({bodykeys.RESULT_OUTCOME: denial.LANDED}, (True, None)), ({}, (None, None))])
def test_a_deliverys_settlement_carries_only_the_typed_facts_of_its_own_result(tmp_path, facts, expected):
    """A refusal means it did not run and changed nothing; only the write program's landed fact says it ran; ordinary returned text proves neither."""
    loop, _, store = rig(tmp_path, PASTED, ACT)
    held = []
    out, call, admitted = paste(loop, "sid:s", held, tmp_path)
    held[0](out, admitted)
    result_turn(loop, "sid:s", call, **facts)
    settled = store.get("sid:s").pasted_settlements[call["id"]]
    assert (settled.ran, settled.changed) == expected and not store.get("sid:s").pasted_deliveries


def test_a_late_result_stays_with_the_older_delivery_and_a_repeated_result_does_not_settle_twice(tmp_path):
    loop, _, store = rig(tmp_path, PASTED, PASTED, ACT)
    held, calls = [], []
    for _ in range(2):                                           # the same bytes pasted twice: two recovered writes, one judge question
        out, call, admitted = paste(loop, "sid:l", held, tmp_path)
        held[-1](out, admitted)
        calls.append(call)
    sess = store.get("sid:l")
    assert calls[0]["id"] != calls[1]["id"] and set(sess.pasted_deliveries) == {c["id"] for c in calls}
    result_turn(loop, "sid:l", calls[0], **{bodykeys.RESULT_OUTCOME: denial.LANDED})
    assert set(sess.pasted_settlements) == {calls[0]["id"]} and set(sess.pasted_deliveries) == {calls[1]["id"]}
    first = sess.pasted_settlements[calls[0]["id"]]
    result_turn(loop, "sid:l", calls[0], **{bodykeys.RESULT_OUTCOME: denial.REFUSED})
    assert sess.pasted_settlements[calls[0]["id"]] is first and set(sess.pasted_deliveries) == {calls[1]["id"]}


def test_a_write_the_transport_did_not_admit_is_never_delivered_and_a_stale_callback_cannot_touch_a_newer_draft(tmp_path):
    loop, _, store = rig(tmp_path, PASTED, PASTED, PASTED, PASTED, ACT)
    held = []
    out1, call1, admitted1 = paste(loop, "sid:t", held, tmp_path)
    out2, call2, admitted2 = paste(loop, "sid:t", held, tmp_path)     # a newer draft replaces the first before the first was finalized
    sess = store.get("sid:t")
    held[0](out1, admitted1)                                          # the older finalization arrives late, naming its own (admitted) call
    assert call1["id"] != call2["id"] and not sess.pasted_deliveries and sess.pasted_prepared is not None
    held[1](out2, {})                                                 # lowered to something else / removed: not among the offered ids, so no delivery
    assert not sess.pasted_deliveries
    out3, call3, _ = paste(loop, "sid:t", held, tmp_path)
    held[2](None, {})                                                 # finalization cancelled: nothing is forwarded
    out4, call4, admitted4 = paste(loop, "sid:t", held, tmp_path)
    assert not sess.pasted_deliveries
    held[3](out4, admitted4)
    assert set(sess.pasted_deliveries) == {call4["id"]} and len({call1["id"], call2["id"], call3["id"], call4["id"]}) == 4


def test_a_competing_redrive_spends_the_same_budget_so_the_paste_is_not_nudged_past_the_bound(tmp_path):
    """phi4 A1 class: a protocol-refused reply and a pasted file share ONE bounded budget of re-drives."""
    refusal = UpstreamProtocolError("bad", {"type": generation.PROTOCOL_ERROR, "message": "bad"})
    for spent, nudged in ((0, True), (MAX_UNEXECUTED_NUDGES - 1, False)):
        loop, coder, store = rig(tmp_path, refusal, PASTED, ACT, judge="", store=LoopStore())
        store.put("sid:b", synthetic(TASK))
        store.get("sid:b").unexecuted_nudges = spent
        log = Rlog()
        loop.drive(body(TASK, tools=[WRITE, SHELL]), "sid:b", CODING, log)
        assert ("loop.unexecuted_write" in log.kinds()) is nudged and store.get("sid:b").unexecuted_nudges == MAX_UNEXECUTED_NUDGES
        assert log.kinds().count("loop.protocol_refused") == 1


def surveyed(root, *files):
    """The session view of a harness that listed ``files`` (path, size) completely."""
    P, S = wsview._SEC_PREFIX, wsview._SEC_SUFFIX
    tree = "\n".join(f"F\t1\t{size}\t{path}" for path, size in files)
    view = wsview.View(str(root), "arca")
    assert wsview.apply_survey(view, "\n".join([f"{P}meta{S}", f"root\t{root}", f"{P}tree{S}", tree, f"{P}blob{S}", f"{P}outside{S}", f"{P}progs{S}",
                                                f"{P}done{S}", f"entries\t{len(files)}", "complete\t1", wsview.SURVEY_CLOSE]))
    return view


def test_an_offer_whose_reply_never_reached_the_coder_is_retried_without_a_second_spend_or_losing_its_fact(tmp_path):
    """The nudge, and the measured unread-file fact riding on it, are acknowledged only by the reply that consumed them: a provider error between
    offer and consumption leaves both standing, and the retry neither spends the budget again nor repeats the fact."""
    (tmp_path / "app.py").write_text("old\n")                                 # an existing file the coder never read: the paste is held, the fact is measured
    loop, coder, store = rig(tmp_path, PASTED, RuntimeError("provider interrupted"), ACT)
    task = "implement the values module"
    token = wsview.bind(surveyed(tmp_path, ("app.py", 4)))
    try:
        with pytest.raises(RuntimeError, match="provider interrupted"):
            loop.drive(body(task, tools=[WRITE, SHELL]), "sid:i", CODING, Rlog())
        sess = store.get("sid:i")
        offered = sess.pasted_pending_nudge
        assert offered is not None and offered.unread_fact and offered.unread_fact in offered.text and sess.unexecuted_nudges == 1
        assert sess.unread_target_fact == offered.unread_fact and sess.pasted_delivered_nudge is None
        loop.drive(body(task, tools=[WRITE, SHELL]), "sid:i", CODING, Rlog())
    finally:
        wsview.unbind(token)
    assert sess.unexecuted_nudges == 1 and sess.pasted_pending_nudge is None and sess.pasted_delivered_nudge is offered and not sess.unread_target_fact
    assert offered.user_turn in coder.bodies[-1]["messages"] and {"role": "assistant", "content": offered.carried_reply} in coder.bodies[-1]["messages"]


def test_a_deselected_assist_never_asks_the_judge_promotes_a_paste_or_nudges_for_it(tmp_path):
    asked = []
    coder = Coder(PASTED, ACT)
    loop = plan_off_loop(coder, store=LoopStore(), reasoner=lambda b, r: (asked.append(b), json.dumps(completion("WHOLE_FILE")).encode())[1],
                         workspace_root=str(tmp_path), reasoner_role=ROLE, assists=True,
                         pilot_runtime=assistruntime.AssistRuntime.select(level=5, disabled=("pasted-file-recovery",)))
    log = Rlog()
    out = loop.drive(body(TASK, tools=[WRITE, SHELL]), "sid:d", CODING, log)
    assert not asked and not {"massage.text_write_recovered", "loop.unexecuted_write", "loop.text_write_refused"} & set(log.kinds())
    assert "write_file" not in json.dumps(out["choices"][0]["message"].get("tool_calls") or [])


def test_a_restart_forgets_the_rulings_and_every_transient_of_the_paste(tmp_path):
    loop, _, store = rig(tmp_path, PASTED, ACT)
    held = []
    out, call, admitted = paste(loop, "sid:r", held, tmp_path)
    held[0](out, admitted)
    sess = store.get("sid:r")
    assert sess.text_write_judged and sess.pasted_deliveries
    back = loop_mod._session_from_dict(loop_mod._session_to_dict(sess))
    assert back.text_write_judged == {} and not back.pasted_deliveries and not back.pasted_settlements
    assert back.pasted_prepared is None and back.pasted_pending_nudge is None and not back.pasted_block_other
