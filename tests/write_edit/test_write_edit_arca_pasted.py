"""Pasted-file recovery (cria.pastedfile), the incident contracts the pre-reset suite held and the lifecycle file did not:
which fence of a mixed reply becomes the write, what is remembered of a ruling, who a late result belongs to, what a newer ruling revokes."""
import json
from types import SimpleNamespace

import pytest

from cria import pastedfile as pf
from test_write_edit_cov_lifecycles import BODY, View, source

CODE = "\n".join(BODY)
# phi4 / feed-pipeline-java A1 call 0022: a short pom excerpt, the complete class (block 2), a REVIEW.md claim and a "done" tail in ONE reply.
MIXED = ("Dependencies first:\n```xml\n<dependency>a</dependency>\n```\n2. **Refactor `app.py`**:\n```python\n" + CODE
         + "\n```\nI also created REVIEW.md. Everything passes now.")


def completion(text, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": text}}]}


def with_ask(src, ask):
    return pf.RecoveryInput(**{**src.__dict__, "ask": ask})


def nudge_in(src, budget, **kw):
    return pf.NudgeInput(src.completion, [], src.evidence, budget, src.log, **kw)


@pytest.mark.parametrize("text,promoted", [(MIXED, True), ("The pom needs:\n```xml\n<dependency>a</dependency>\n```\nthat is all.", False)],
                         ids=["mixed-reply", "excerpt-only"])
def test_only_the_named_whole_file_block_of_a_mixed_reply_becomes_the_write_and_the_judge_sees_the_whole_reply(text, promoted):
    """The excerpt and the trailing REVIEW.md claim never become a write; the question names block 2 and quotes the reply whole."""
    asked = []
    src = source(View({"app.py": "old"}), completion=completion(text), asked=asked)
    result = pf.recover(src, pf.State())
    if not promoted:
        assert result.status is pf.Status.UNCHANGED and not asked
        return
    call = result.completion["choices"][0]["message"]["tool_calls"][0]
    assert result.status is pf.Status.PREPARED and json.loads(call["function"]["arguments"]) == {"path": "/w/app.py", "content": CODE + "\n"}
    assert result.completion["choices"][0]["message"]["content"].endswith("2. **Refactor `app.py`**:") and "REVIEW.md" not in result.completion["choices"][0]["message"]["content"]
    assert "fenced block number 2" in asked[0] and MIXED in asked[0] and result.prepared.content == CODE + "\n"
    assert src.log.events[-1][1]["dropped_chars"] == len(MIXED) - len(result.completion["choices"][0]["message"]["content"])


@pytest.mark.parametrize("answer,remembered", [("OTHER", True), ("", False), ("WHOLE_FILE_MAYBE", False), ("The answer is WHOLE_FILE", False)])
def test_only_an_actual_ruling_is_remembered_and_a_standing_other_suppresses_the_unsaved_claim_without_spending_budget(answer, remembered):
    asked, state = [], pf.State()
    src = with_ask(source(View({"app.py": "old"}), completion=completion(MIXED)), lambda q, **k: (asked.append(q), answer)[1])
    for _ in range(2):
        assert pf.recover(src, state).status is pf.Status.WITHHELD
    assert len(asked) == (1 if remembered else 2) and bool(state.judged) is remembered
    budget = SimpleNamespace(unexecuted_nudges=0)
    out = pf.redrive(nudge_in(src, budget), state)
    assert (out.status is pf.Status.UNCHANGED) is remembered and budget.unexecuted_nudges == (0 if remembered else 1) and not state.other


def test_a_changed_byte_key_is_asked_again_and_the_previous_other_is_not_reused():
    state, asked = pf.State(), []
    src = with_ask(source(View({"app.py": "old"}), completion=completion(MIXED)), lambda q, **k: "OTHER")
    pf.recover(src, state)
    changed = with_ask(source(View({"app.py": "old"}), completion=completion(MIXED.replace("value_0", "value_zero", 1))),
                       lambda q, **k: (asked.append(q), "WHOLE_FILE")[1])
    assert pf.recover(changed, state).status is pf.Status.PREPARED and len(asked) == 1 and len(state.judged) == 2 and not state.other


def test_an_unread_files_fact_is_consumed_once_and_the_nudge_carries_the_full_reply():
    src = source(View({"app.py": "old"}), completion=completion(MIXED), seen=False)
    state, budget = pf.State(), SimpleNamespace(unexecuted_nudges=0)
    assert pf.recover(src, state).reason == "unread_existing_file" and state.unread_fact == "UNREAD"
    first = pf.redrive(nudge_in(src, budget), state)
    assert first.nudge.carried_reply == MIXED and "UNREAD" in first.nudge.text and not state.unread_fact
    assert "UNREAD" not in pf.redrive(nudge_in(src, budget), state).nudge.text
    assert budget.unexecuted_nudges == 2 and pf.redrive(nudge_in(src, budget), state).status is pf.Status.UNCHANGED
    cut = source(View(), completion=completion(MIXED, "length"))
    assert pf.redrive(nudge_in(cut, SimpleNamespace(unexecuted_nudges=0)), pf.State()).nudge.carried_reply == ""      # a cut-off reply is not carried as if complete


def test_a_late_result_settles_the_earlier_delivery_it_belongs_to_and_never_twice():
    state, deliveries = pf.State(), []
    for _ in range(2):                                                   # the same bytes recovered twice (the ruling is remembered): two distinct calls
        first = pf.recover(source(View({"app.py": "old"}), completion=completion(MIXED), asked=[]), state)
        deliveries.append(pf.forwarded(state, first.prepared, first.completion).delivery)
    d1, d2 = deliveries
    assert d1.call_ids != d2.call_ids and set(state.deliveries) == {d1.call_ids[0], d2.call_ids[0]}
    done = pf.settle(state, d1, d1.call_ids[0], ran=False, changed=False)
    assert done.settlement.delivery is d1 and state.deliveries.get(d2.call_ids[0]) is d2 and d1.call_ids[0] not in state.deliveries
    assert pf.settle(state, d1, d1.call_ids[0], ran=True, changed=True).status is pf.Status.UNCHANGED
    assert pf.settle(state, d2, d2.call_ids[0], ran=True, changed=True).settlement.delivery is d2
    assert (state.settlements[d1.call_ids[0]].ran, state.settlements[d1.call_ids[0]].changed) == (False, False)


def test_a_newer_other_revokes_the_standing_offer_and_only_the_actual_offer_object_acknowledges_it():
    old = pf.Nudge("old instruction", "old reply", {"role": "user", "content": "old instruction"}, "old unread fact")
    state, budget = pf.State(other=True, unread_fact="old unread fact", pending_nudge=old), SimpleNamespace(unexecuted_nudges=2)
    src = source(View(), completion=completion(MIXED))
    assert pf.redrive(nudge_in(src, budget, defer_unread_consumption=True), state).status is pf.Status.UNCHANGED
    assert state.pending_nudge is None and not state.other and state.unread_fact == "old unread fact" and budget.unexecuted_nudges == 2
    assert pf.nudge_delivered(state, old).status is pf.Status.UNCHANGED and pf.nudge_delivered(state, old, consumed=pf.Nudge(*[getattr(old, f) for f in old.__dataclass_fields__])).status is pf.Status.UNCHANGED
    assert state.delivered_nudge is None and pf.nudge_delivered(state, old, consumed=old).status is pf.Status.FORWARDED
    assert state.delivered_nudge is old and not state.unread_fact
    current = pf.Nudge("new instruction", "new reply", {}, "new unread fact")             # acknowledging the OLD one never clears a newer authorized offer
    state = pf.State(unread_fact="new unread fact", pending_nudge=current)
    assert pf.nudge_delivered(state, old, consumed=old).status is pf.Status.FORWARDED and state.pending_nudge is current and state.unread_fact == "new unread fact"


def test_a_step_cancel_drops_unconsumed_offers_but_keeps_the_rulings_and_the_deliveries_already_made():
    state = pf.State()
    first = pf.recover(source(View({"app.py": "old"}), completion=completion(MIXED), asked=[]), state)
    delivery = pf.forwarded(state, first.prepared, first.completion).delivery
    second = pf.recover(source(View({"app.py": "old"}), completion=completion(MIXED), asked=[]), state)
    state.pending_nudge = state.delivered_nudge = pf.Nudge("n", "r", {}, None)
    assert state.prepared is second.prepared and state.judged
    assert pf.cancel(state).status is pf.Status.UNCHANGED
    assert state.prepared is None and state.pending_nudge is None and state.delivered_nudge is None
    assert state.judged and state.deliveries == {delivery.call_ids[0]: delivery}
