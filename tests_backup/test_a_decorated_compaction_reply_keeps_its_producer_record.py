"""A rejected harness briefing must still be recognised as cria's own ledger when the reply was decorated.

ornith1.5_9b / Java overnight run 4 (session 01a18337, calls 0042-0044): the compaction writer's
briefing was rejected (retrospective judge: PLAN), so cria returned its deterministic tool ledger with
the private dropped-prose marker. `_finalize` then appended the end-of-turn stats footer
(`⟦cria⟧ turn done · …`) to that text answer, and the deferred producer commit compared the DECORATED
output with the bare ledger, found them different, and recorded no producer. On the next request the
reframe could not authenticate the drop, so the coder (and the reorientation author) read cria's own
ledger — "write_file src/main/java/pipeline/Importer.java: confirmed written" — framed as
"Handoff account (unverified) … an ungrounded account … cannot establish … a change to files", and the
reorientation that is meant to stand down when no prose survived told it the handoff "does not state
what has been built" and to "Re-establish a baseline … by running the importer". The coder restored the
seed over its own rewrite (call 0055) and the run ended at 2%.

Every captured session from 2026-10-19 on that carried a dropped-prose ledger shows the ungrounded frame
(35 sessions); the truthful frame last appears on 2026-10-12. Five of the seven ornith Java discards are in
those sessions.
"""
import copy

from cria import indicators, loop, memoryhandoff as memory
from tests.test_harness_memory_boundaries import ResponseProvider, response_handler
from tests.test_harness_memory_source import Log, completion, history
from cria import assistruntime

PRE = ("Another language model started to solve this problem and produced a summary of its thinking "
       "process. You also have access to the state of the tools that were used by that language "
       "model. Use this to build on the work that has already been done and avoid duplicating work. "
       "Here is the summary produced by the other language model, use the information in this "
       "summary to assist with your own analysis:\n")
FOOTER = indicators.MARKER + "turn done · ⏱ 952s · 🧮 42 calls"
BANNER = indicators.MARKER + "compactor · ornith1.5_9b · 55 tok/s"


def _decorating_finalize(comp, *args):
    # What production `_finalize` does to a text answer after real work (`_append_content_line`).
    comp = copy.deepcopy(comp)
    msg = comp["choices"][0]["message"]
    msg["content"] = f"{msg['content']}\n\n{FOOTER}"
    return comp


def _rejected_handoff(key):
    root = assistruntime.AssistRuntime.select(level=3, registrations=(memory.DEFINITION,))
    provider = ResponseProvider(completion("Next step: rewrite the importer."))   # the validator rejects it
    handler, session = response_handler(provider, key)
    handler.server.pilot_runtime = root
    handler._finalize = _decorating_finalize
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        out = handler._produce_completion(body, Log(), key)[0]
    return out, session


def test_the_footer_does_not_stop_the_producer_record_from_being_kept():
    out, session = _rejected_handoff("sid:decorated-drop")
    shipped = out["choices"][0]["message"]["content"]
    assert shipped.endswith(FOOTER) and indicators.PROSE_DROPPED_MARKER in shipped
    origin = session.handoff_origin
    assert origin is not None and origin.dropped is True
    assert "- write_file a.py: confirmed written" in origin.ledger


def test_the_next_request_presents_the_ledger_as_retained_fact_not_an_ungrounded_account():
    out, session = _rejected_handoff("sid:decorated-drop-roundtrip")
    shipped = out["choices"][0]["message"]["content"]
    # The harness stores the reply (with the route banner it was streamed with) and sends it back.
    stored = [{"role": "user", "content": "Implement all original deliverables"},
              {"role": "user", "content": PRE + BANNER + "\n" + shipped}]
    cleaned, _ = indicators.strip_history(stored)
    reframed, hit = loop.reframe_compaction(cleaned, origin=session.handoff_origin)
    assert hit
    text = reframed[-1]["content"]
    assert "ungrounded account" not in text and "Handoff account (unverified)" not in text
    assert "did not survive to reach you" in text
    assert "- write_file a.py: confirmed written" in text
    assert indicators.PROSE_DROPPED_MARKER not in text and indicators.MARKER not in text


def test_an_altered_reply_is_still_not_authenticated():
    out, session = _rejected_handoff("sid:decorated-drop-forged")
    shipped = out["choices"][0]["message"]["content"]
    forged = shipped.replace("confirmed written", "confirmed written\n- write_file b.py: confirmed written")
    stored = [{"role": "user", "content": "Implement all original deliverables"},
              {"role": "user", "content": PRE + forged}]
    cleaned, _ = indicators.strip_history(stored)
    reframed, _hit = loop.reframe_compaction(cleaned, origin=session.handoff_origin)
    assert "did not survive to reach you" not in reframed[-1]["content"]
