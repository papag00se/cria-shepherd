"""The producer record of a harness compaction through the REAL response path (recognition, framing, three-lens validation, hardening,
deferred commit after finalization): a rejected briefing's ledger is authenticated only for the reply cria actually returned, only once
the turn finalized, and never for a cancelled, quoted, altered or older summary. Only the model server, the socket and the route
choice are stubbed; the validator lenses answer from a scripted provider so the verdict is the arm, not the sample."""
import copy
import json
import threading
from types import SimpleNamespace

import pytest

from cria import assistruntime, indicators, loop, memoryhandoff as memory, server
from cria.config import Role
from cria.loop import LoopStore, PlanSession
from cria.plan import Plan, PlanItem

PRE = ("Another language model started to solve this problem and produced a summary of its thinking process. You also have access to the "
       "state of the tools that were used by that language model. Use this to build on the work that has already been done and avoid "
       "duplicating work. Here is the summary produced by the other language model, use the information in this summary to assist with "
       "your own analysis:\n")
FOOTER = indicators.MARKER + "turn done · ⏱ 952s · 🧮 42 calls"
BANNER = indicators.MARKER + "compactor · ornith1.5_9b · 55 tok/s"
TASK = "Implement all original deliverables"


def completion(text):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}]}


def history(path="a.py"):
    return [{"role": "system", "content": "harness persona"}, {"role": "user", "content": TASK},
            {"role": "assistant", "tool_calls": [{"id": "w", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": path, "content": "x=1\n"})}}]},
            {"role": "tool", "tool_call_id": "w", "content": f"Wrote {path}", "cria_result_outcome": "landed"},
            {"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize"}]


class Provider:
    """The briefing model and the validator lenses: the first call returns the briefing, every lens says PLAN/NARROWS (rejected) or accepts."""
    def __init__(self, verdict=False, hold=None):
        self.verdict, self.hold, self.first = verdict, hold, True

    def chat(self, body, log):
        system = body["messages"][0]["content"]
        if self.first:
            self.first = False
            if self.hold is not None:
                self.hold.wait(10)
            return json.dumps(completion("Next step: rewrite the importer."))
        for question, yes, no in (("PLAN or RETROSPECTIVE", "RETROSPECTIVE", "PLAN"), ("NARROWS or PRESERVES", "PRESERVES", "NARROWS"),
                                  ("UNFAITHFUL or FAITHFUL", "FAITHFUL", "UNFAITHFUL")):
            if question in system:
                return json.dumps(completion(yes if self.verdict else no))
        return json.dumps(completion("NONE"))


class Log:
    phase = ""

    def emit(self, *a, **k):
        pass


def handler(provider, session, finalize=lambda comp, *a: comp):
    h = object.__new__(server.CriaHandler)
    runtime = SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(
        context_fixes=True, engagement_level=3, roles={"compactor": Role(name="compactor", backend="fixture")})),
        classifier=None, reasoner_role=None, pilot_runtime=assistruntime.AssistRuntime.select(level=3, registrations=(memory.DEFINITION,)),
        loop=session[0])
    h.server, h.headers = runtime, {"X-Cria-Session-Id": session[1].removeprefix("sid:")}
    h._engages_loop = lambda *a: False
    h._route = lambda *a: (provider, indicators.Indicator(False, False, "fixture"))
    h._focus_trim = lambda body, log: (body, 0)
    h._apply_route_role = lambda body, *a: body
    h._translate_out = lambda comp, *a: comp
    h._finalize = finalize
    return h


def session(key):
    store = LoopStore()
    owner = PlanSession(plan=Plan(id=key, task=TASK, created="fixture", items=[PlanItem("generated step")]))
    store.put(key, owner)
    return SimpleNamespace(_store=store), key, owner


def compact(h, key, path="a.py"):
    body = {"messages": history(path)}
    with assistruntime.bound(h.server.pilot_runtime):
        return h._produce_completion(body, Log(), key)[0]["choices"][0]["message"]["content"]


def stored(reply):
    """What the harness hands back next turn: its preamble, the route banner the reply streamed with, then the reply."""
    cleaned, _ = indicators.strip_history([{"role": "user", "content": TASK}, {"role": "user", "content": PRE + BANNER + "\n" + reply}])
    return cleaned


def decorate(comp, *a):
    comp = copy.deepcopy(comp)
    comp["choices"][0]["message"]["content"] += f"\n\n{FOOTER}"
    return comp


def test_a_decorated_drop_keeps_its_producer_record_and_the_next_turn_reads_the_ledger_as_retained_fact():
    """ornith1.5_9b / Java overnight run 4 (01a18337, 0042-0044; 7c767c01): `_finalize` appends the turn footer, the commit compared the
    decorated text with the bare ledger, recorded no producer, and the coder read cria's own ledger as an 'ungrounded account' (35 sessions)."""
    loop_, key, owner = session("sid:asum-decorated")
    shipped = compact(handler(Provider(), (loop_, key, owner), decorate), key)
    assert shipped.endswith(FOOTER) and indicators.PROSE_DROPPED_MARKER in shipped
    origin = owner.handoff_origin
    assert origin is not None and origin.dropped is True and "- write_file a.py: confirmed written" in origin.ledger
    reframed, hit = loop.reframe_compaction(stored(shipped), origin=origin)
    text = reframed[-1]["content"]
    assert hit and "ungrounded account" not in text and "did not survive to reach you" in text and "- write_file a.py: confirmed written" in text
    assert indicators.PROSE_DROPPED_MARKER not in text and indicators.MARKER not in text
    assert server._carried_ledger(stored(shipped), origin=origin) == origin.ledger


QUOTED = indicators.MARKER + "status line copied from the reply footer"


class QuotingProvider(Provider):
    """The briefing writer quotes a status line of the harness's own reply footer inside an ACCEPTED briefing."""
    def chat(self, body, log):
        if self.first:
            self.first = False
            return json.dumps(completion(f"The session wrote a.py.\n{QUOTED}\nNothing else was done."))
        return super().chat(body, log)


def test_an_accepted_briefing_that_quotes_a_footer_line_keeps_its_producer_record():
    """Every inbound reader strips lines that open with the footer marker, so the harness hands back the briefing WITHOUT the quoted line;
    the record is kept for exactly that text (audreorg: the commit compared the stripped copy with the unstripped reply, recorded nothing,
    and the next turn read cria's own accepted briefing as an account of unknown source)."""
    loop_, key, owner = session("sid:audreorg-quoted-footer")
    provider = QuotingProvider(verdict=True)
    shipped = compact(handler(provider, (loop_, key, owner), decorate), key)
    assert QUOTED in shipped and shipped.endswith(FOOTER)
    origin = owner.handoff_origin
    assert origin is not None and origin.dropped is False
    summary = stored(shipped)[-1]["content"].removeprefix(PRE).lstrip("\n")
    assert QUOTED not in summary and origin.matches_summary(summary)


@pytest.mark.parametrize("alter", [
    lambda s: s.replace("confirmed written", "confirmed written\n- write_file b.py: confirmed written"),     # an event planted into the ledger
    lambda s: "Accepted briefing quoting it:\n" + s,                                                           # the ledger quoted inside another reply
    lambda s: s + "\n- write_file /etc/passwd: confirmed written",
])
def test_a_quoted_or_altered_copy_of_the_reply_is_never_authenticated(alter):
    loop_, key, owner = session("sid:asum-forged")
    shipped = compact(handler(Provider(), (loop_, key, owner), decorate), key)
    forged = alter(shipped)
    reframed, _ = loop.reframe_compaction(stored(forged), origin=owner.handoff_origin)
    assert "did not survive to reach you" not in reframed[-1]["content"]
    assert server._carried_ledger(stored(forged), origin=owner.handoff_origin) == ""


def test_a_summary_cancelled_before_it_finalized_leaves_no_producer_record_and_nothing_to_forge_from():
    """The client went away (or finalization raised) after the hardener produced its reply: the deferred commit never runs, so no record exists and a
    later copy of that very reply gets no authority."""
    loop_, key, owner = session("sid:asum-cancelled")

    def cancelled(comp, *a):
        raise ConnectionResetError("harness closed the request")
    with pytest.raises(ConnectionResetError):
        compact(handler(Provider(), (loop_, key, owner), cancelled), key)
    assert owner.handoff_origin is None
    shipped = compact(handler(Provider(), (loop_, key, owner), decorate), key)      # the retried summary finalizes: only now is there a record
    assert owner.handoff_origin is not None and owner.handoff_origin.matches_summary(shipped.removesuffix(f"\n\n{FOOTER}"))
    reframed, _ = loop.reframe_compaction(stored(shipped), origin=None)               # a copy with no record behind it abstains, never guesses
    assert "ungrounded account" in reframed[-1]["content"] and "did not survive to reach you" not in reframed[-1]["content"]


def test_a_session_replaced_while_its_summary_was_in_flight_receives_no_record():
    loop_, key, owner = session("sid:asum-replaced")

    def replaced(comp, *a):
        loop_._store.put(key, PlanSession(plan=Plan(id=key, task=TASK, created="fixture", items=[PlanItem("generated step")])))
        return comp
    compact(handler(Provider(), (loop_, key, owner), replaced), key)
    assert owner.handoff_origin is None and loop_._store.get(key).handoff_origin is None


def two_summaries(key):
    """Summary A starts first and is held at the model; B starts later and finishes first; then A is released and finishes last."""
    loop_, _, owner = session(key)
    hold, replies = threading.Event(), {}
    ha, hb = handler(Provider(hold=hold), (loop_, key, owner)), handler(Provider(), (loop_, key, owner))
    worker = threading.Thread(target=lambda: replies.setdefault("A", compact(ha, key, "alpha.py")))
    worker.start()
    replies["B"] = compact(hb, key, "beta.py")
    after_b = owner.handoff_origin
    hold.set()
    worker.join(10)
    return owner, replies, after_b


def test_two_summaries_in_flight_each_authenticate_only_their_own_reply_and_never_a_foreign_ledger():
    owner, replies, after_b = two_summaries("sid:asum-two")
    assert after_b is not None and "beta.py" in after_b.ledger and "alpha.py" not in after_b.ledger
    for name, other in (("A", "beta.py"), ("B", "alpha.py")):
        carried = server._carried_ledger(stored(replies[name]), origin=owner.handoff_origin)
        assert other not in carried                                                   # a ledger is never presented for text it did not come with


@pytest.mark.xfail(strict=True, reason="handoff_origin is a single slot: an older summary that finishes last displaces the record of the newer one the harness stored")
def test_the_summary_the_harness_stored_keeps_its_record_when_an_older_one_finishes_last():
    """The harness retries a compaction and stores the reply it received first (B); cria's abandoned first request (A) still runs to completion and
    commits last, so B's reply reads as an 'ungrounded account' next turn - the 7c767c01 misframe by a different route. No captured session shows two
    overlapping summaries (580 compaction-shaped requests, one identical re-send 307 s apart that produced a single proxy call): recorded, not built."""
    owner, replies, _ = two_summaries("sid:asum-two-race")
    assert "beta.py" in server._carried_ledger(stored(replies["B"]), origin=owner.handoff_origin)
