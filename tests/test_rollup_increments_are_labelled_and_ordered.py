"""The coder-visible rollup carries each accepted increment as its own ordered, labelled entry.

Run07 (ornith1.5_9b / Java, until75-77073c56): increment 0063 said the quoted CSV row "parses to 5
fields" (the probe printed `[4] [SKU-0007, widget, blue, 2, 12.50]`); increment 0067 said it parses
"into a single field". Rolling memory appends, so from coder call 0070 on the one rollup message held
both sentences 3,400 characters apart with nothing saying which was written later — an earlier false
claim and its correction were indistinguishable. The labels state only what is known for certain: the
order and count of the entries, and how many entries a refold condensed. Fake upstreams throughout.
"""
import copy
import json

from cria import prompts, selfcompact
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore
from tests.test_selfcompact_wiring import _Rlog, _synth, _validation_reply

FIRST = "The probe parsed the quoted row SKU-0007 into 5 fields."
SECOND = "The quoted row SKU-0007 parsed into 4 fields: the quoted comma stayed inside one field."
TASK = "Handle quoted descriptions containing commas."
REFOLD_SYSTEM = prompts.load("selfcompact_refold")[:80]


def make_loop(writer_replies, refold_reply="Condensed: SKU-0007 parsed into 4 fields."):
    replies = iter(writer_replies)

    def chat(body, rlog):
        system = body["messages"][0]["content"]
        answer = _validation_reply(system)
        if answer is None:
            answer = refold_reply if REFOLD_SYSTEM in system else next(replies)
        return json.dumps({"choices": [{"message": {"content": answer}}]}).encode()

    ctx = LoopContext(planner=None, coder_chat=chat, reasoner_chat=chat, compactor_chat=chat,
                      compactor_role=Role(name="compactor", backend="local"),
                      planner_enabled=False, runs_dir="", self_compact=True, trigger_compaction=100)
    return Loop(ctx, LoopStore())


def band(start, n):
    return [{"role": "assistant", "content": f"Work step {i}: " + "x" * 800} for i in range(start, start + n)]


def rollup_of(view):
    found = [m for m in view if selfcompact.SUMMARY_MARKER in str(m.get("content"))]
    assert len(found) == 1, view
    return found[0]["content"]


def two_increments(first=FIRST, second=SECOND, **kw):
    driver = make_loop([first, second], **kw)
    sess = _synth()
    history = [{"role": "system", "content": "system"}] + band(0, 80)
    driver._self_compact(history, sess, 1, _Rlog(), pinned_task=TASK)
    assert sess.compact_state.summary.strip()
    history = history + band(80, 80)
    view = driver._self_compact(history, sess, 1, _Rlog(), pinned_task=TASK)
    return driver, sess, history, view


def test_two_increments_reach_the_coder_as_ordered_labelled_entries():
    _, sess, _, view = two_increments()
    text = rollup_of(view)
    lines = prompts.load_map("selfcompact_rollup")
    first = prompts.fill(lines["first"], count=2)
    second = prompts.fill(lines["next"], n=2, count=2, prev=1)
    # Fails before: the increments were joined by a blank line with no entry labels at all.
    assert first in text and second in text, text
    assert text.index(first) < text.index(FIRST) < text.index(second) < text.index(SECOND)
    assert prompts.fill(lines["order"], count=2) in text
    # The marker stays first: it is what makes the rollup an anchor and protects it at the floor.
    assert text.startswith(selfcompact.SUMMARY_MARKER)
    assert selfcompact.has_anchor({"role": "user", "content": text})
    # The stored summary every writer, refold and size check reads is unchanged: the plain join.
    assert sess.compact_state.summary == FIRST + "\n\n" + SECOND
    assert sess.compact_state.parts == (FIRST, SECOND)


def test_a_refold_reaches_the_coder_as_one_labelled_condensation():
    big1, big2 = FIRST + " " + "a" * 13000, SECOND + " " + "b" * 13000
    _, sess, _, view = two_increments(big1, big2)
    text = rollup_of(view)
    lines = prompts.load_map("selfcompact_rollup")
    # Fails before: one unlabelled block.
    assert prompts.fill(lines["condensed"], count=1, folded=2) in text, text
    assert "Condensed: SKU-0007 parsed into 4 fields." in text
    assert big1 not in text and big2 not in text
    assert prompts.fill(lines["order"], count=1) not in text      # one entry: no ordering sentence
    assert sess.compact_state.summary == "Condensed: SKU-0007 parsed into 4 fields."


def test_an_unchanged_state_rerenders_the_same_rollup_and_no_internal_name_reaches_the_model():
    driver, sess, history, view = two_increments()
    again = driver._self_compact(history, sess, 1, _Rlog(), pinned_task=TASK)
    assert rollup_of(again) == rollup_of(view)                       # deterministic, nothing re-labelled
    assert "cria" not in rollup_of(view).lower()


def test_a_state_without_segmentation_renders_its_summary_as_one_entry():
    # A state built directly from text (older callers, tests) is one entry, never an invented split.
    state = selfcompact.CompactState(summary="Earlier work.\n\nMore earlier work.", covered=3, attempted=3)
    text = selfcompact._summary_msg(state)["content"]
    lines = prompts.load_map("selfcompact_rollup")
    assert prompts.fill(lines["first"], count=1) in text
    assert prompts.fill(lines["next"], n=2, count=2, prev=1) not in text
    assert text.endswith("Earlier work.\n\nMore earlier work.")
