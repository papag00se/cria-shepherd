"""memoryhandoff.harden (mutation-found gaps): the body of the ONE retry a failed first briefing gets, and what ships when the retry is no better."""
import json
from types import SimpleNamespace

import pytest

from cria import indicators, memoryhandoff as mh
from compaction_handoff_helpers import write

HISTORY = [{"role": "user", "content": "Fix the importer."}, *write("w1", "src/Importer.java"), {"role": "user", "content": mh.LOCAL_COMPACT_MARKER}]
BODY = {"messages": [{"role": "system", "content": "harness frame"}, *HISTORY]}
SUMMARY_ROOM = 4321
LEAK = "partial <tool_call>{}</tool_call>"


def _services(validated):
    return mh.EvidenceServices(
        drop_harness_frame=lambda ms: ms, inventory=lambda root: "", listing=lambda root: "", fetch_facts=lambda ms, location: "",
        disk_truth=lambda text, inv, rlog: text, validate=lambda *a, **k: validated.append(k["task"]) or True,
        proxy_body=lambda b: b, summarize_max_tokens=SUMMARY_ROOM)


def _harden(first, retry, *, finish="stop", retry_finish="stop", frame_hook=None, chat_raises=False):
    sent, events, settled, validated = [], [], [], []

    def chat(body, rlog):
        sent.append(json.loads(json.dumps(body)))
        if chat_raises:
            raise RuntimeError("upstream down")
        return json.dumps({"choices": [{"finish_reason": retry_finish, "message": {"role": "assistant", "content": retry}}]})
    comp = {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": first}}]}
    kw = {"frame_hook": frame_hook} if frame_hook else {}
    out = mh.harden(comp, BODY, mh.SessionFacts(original_task="Fix the importer."), _services(validated), selected=True, chat_fn=chat, role=None,
                    rlog=SimpleNamespace(emit=lambda kind, **f: events.append((kind, f))), settle=lambda *a: settled.append(a), **kw)
    return out, sent, events, settled, validated


def test_the_retry_is_asked_without_the_harness_frame_with_room_and_thinking_off_even_when_the_frame_hook_drops_the_room():
    def bare_hook(body, facts, services, *, selected):
        return {"messages": [*body["messages"], {"role": "user", "content": "ask"}]}          # a hook that supplies no max_tokens of its own
    out, sent, events, settled, _ = _harden("", "Retried briefing.", frame_hook=bare_hook)
    assert len(sent) == 1 and not any(m["role"] == "system" for m in sent[0]["messages"])       # the harness frame is the one thing the retry must not carry
    assert [m["content"] for m in sent[0]["messages"]] == ["Fix the importer.", None, "Wrote", mh.LOCAL_COMPACT_MARKER, "ask"]
    assert sent[0]["max_tokens"] == SUMMARY_ROOM and sent[0]["chat_template_kwargs"]["enable_thinking"] is False
    assert out.effect is mh.Effect.DELIVERED and mh.completion_text(out.completion).startswith("Retried briefing.")
    assert ("route.compaction_retry", {"level": "info", "had_leak": False, "truncated": False, "max_tokens": SUMMARY_ROOM}) in events
    assert settled[0][2] is False
    # a hook that keeps the room it set is not overridden
    _o, sent2, *_ = _harden("", "ok", frame_hook=lambda b, f, s, *, selected: {**b, "max_tokens": 77})
    assert sent2[0]["max_tokens"] == 77


@pytest.mark.parametrize("retry,retry_finish", [
    ("", "stop"),                      # the retry wrote nothing
    ("   \n", "stop"),
    (LEAK, "stop"),                     # a leaked tool call is not a briefing
    ("a cut-off retry", "length"),      # nor is one cut off at the cap, however readable
])
def test_a_retry_that_is_empty_leaked_or_cut_off_ships_no_prose_only_the_dropped_marker_and_the_ledger(retry, retry_finish):
    out, sent, events, settled, validated = _harden("cut off mid-sen", retry, finish="length", retry_finish=retry_finish)
    shipped = mh.completion_text(out.completion)
    assert out.effect is mh.Effect.WITHHELD and out.prose == ""
    assert shipped.startswith(indicators.PROSE_DROPPED_MARKER) and "cut off mid-sen" not in shipped and "a cut-off retry" not in shipped and "src/Importer.java" in shipped
    assert not validated and len(sent) == 1                                                       # a rejected retry is neither judged nor retried again
    assert ("route.compaction_no_briefing", {"level": "warn", "retry_leak": bool(retry.strip())}) in events
    assert settled == [(shipped, out.ledger, True)]


def test_a_failing_retry_request_withholds_the_briefing_instead_of_shipping_the_broken_first_one():
    out, sent, events, settled, validated = _harden("cut off mid-sen", "", finish="length", chat_raises=True)
    assert out.effect is mh.Effect.WITHHELD and "cut off mid-sen" not in mh.completion_text(out.completion) and not validated
    assert [k for k, _ in events if k.startswith("route.compaction")] == ["route.compaction_retry", "route.compaction_retry_failed"]


def test_a_good_first_briefing_is_never_retried():
    out, sent, _events, settled, validated = _harden("A complete briefing.", "unused")
    assert not sent and validated == ["Fix the importer."] and out.effect is mh.Effect.DELIVERED and out.prose == "A complete briefing."
