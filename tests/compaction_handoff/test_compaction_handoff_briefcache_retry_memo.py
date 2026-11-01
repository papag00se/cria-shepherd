"""Codex retries one failing compaction request up to three times; each retry used to re-run the briefing writer and every validator lens
for ONE identical history (Node cell, captures 0031/0034/0037: three briefings, one accepted, one refused). Through the real response path
(recognition, framing, validation, hardening, finalization), with only the model, the socket and the route choice stubbed: an identical request
of a session is answered with the first reply's exact bytes and no model call; any change of history, evidence or session is produced afresh."""
import copy
import json
import threading

from cria import handoffmemo
from test_compaction_handoff_asum_producer_lifecycle import (Log, Provider, TASK, assistruntime, completion, decorate,
                                                              handler, history, session)


class Counting(Provider):
    """Every model call is counted; the first call after ``arm()`` is the briefing writer, the rest are validator lenses."""
    def __init__(self, verdict=False, empty=False):
        super().__init__(verdict)
        self.calls, self.writes, self.empty = 0, 0, empty
        self.first = False

    def arm(self):
        self.first = True

    def chat(self, body, log):
        self.calls += 1
        self.writes += self.first
        reply = super().chat(body, log)
        if self.empty and not self.first and "NONE" not in reply and '"PLAN"' not in reply:
            return json.dumps(completion(""))
        return reply


def compact(h, key, provider, messages=None, arm=True):
    if arm:
        provider.arm()
    body = {"messages": messages if messages is not None else history()}
    with assistruntime.bound(h.server.pilot_runtime):
        return h._produce_completion(body, Log(), key)[0]


def setup(key, provider, finalize=decorate):
    loop_, key, owner = session(key)
    return handler(provider, (loop_, key, owner), finalize), key, owner


def test_identical_retries_get_one_briefing_and_the_same_reply_bytes_accepted_or_refused():
    for verdict in (True, False):
        provider = Counting(verdict)
        h, key, _ = setup("sid:briefcache-retry", provider)
        first = compact(h, key, provider)
        spent = provider.calls
        assert provider.writes == 1 and spent >= 2           # the writer and at least one validator lens ran once
        retries = [compact(h, key, provider) for _ in range(3)]
        assert (provider.calls, provider.writes) == (spent, 1)
        assert all(json.dumps(r, sort_keys=True) == json.dumps(first, sort_keys=True) for r in retries)
        text = first["choices"][0]["message"]["content"]
        assert ("Next step: rewrite the importer." in text) is verdict   # accepted prose, or a withheld briefing carrying only the ledger


def test_a_reused_reply_is_a_copy_and_a_changed_history_or_evidence_or_session_is_produced_afresh():
    provider = Counting(False)
    h, key, owner = setup("sid:briefcache-changes", provider)
    first = compact(h, key, provider)
    first["choices"][0]["message"]["content"] = "mutated by the caller"
    assert compact(h, key, provider)["choices"][0]["message"]["content"] != "mutated by the caller"
    assert provider.writes == 1
    other, other_key, _ = setup("sid:briefcache-other", provider)      # the identical request in another session of the SAME service shares nothing
    other.server.handoff_memo = handoffmemo.of(h.server)
    compact(other, other_key, provider)
    assert provider.writes == 2
    compact(h, key, provider, history("b.py"))                          # another history: a new briefing
    assert provider.writes == 3
    owner.last_gate_flag = "build FAILED"                              # the same history, other gate evidence: not the old verdict
    compact(h, key, provider)
    assert provider.writes == 4
    compact(h, key, provider)                                          # ... and that one is reusable in turn
    assert provider.writes == 4


def test_a_refusal_that_decided_nothing_is_not_remembered_so_the_retry_asks_again():
    provider = Counting(True, empty=True)                              # every lens answers with nothing: the judge said no word
    h, key, _ = setup("sid:briefcache-undecided", provider)
    compact(h, key, provider)
    compact(h, key, provider)
    assert provider.writes == 2


def test_a_retry_that_arrives_while_the_first_is_still_being_produced_waits_for_it():
    hold = threading.Event()
    provider = Counting(True)
    provider.hold = hold
    provider.arm()
    h, key, _ = setup("sid:briefcache-inflight", provider)
    replies = []
    def run():
        replies.append(compact(h, key, provider, arm=False))
    first = threading.Thread(target=run)
    first.start()
    while provider.writes == 0:
        threading.Event().wait(0.01)
    second = threading.Thread(target=run)
    second.start()
    threading.Event().wait(0.2)
    assert provider.writes == 1 and not replies                          # the retry did not start a second writer
    hold.set()
    first.join(10), second.join(10)
    assert provider.writes == 1 and len(replies) == 2 and replies[0] == replies[1]


def test_the_memo_is_bounded_per_session_and_in_sessions():
    memo = handoffmemo.HandoffMemo(per_session=2, sessions=2)
    for session_, ident in [("a", "1"), ("a", "2"), ("a", "3"), ("b", "1"), ("c", "1")]:
        with memo.claim(session_, ident) as claim:
            claim.remember("e", {"id": ident})
    assert memo.size("a") == 0 and memo.size("b") == 1 and memo.size("c") == 1   # the oldest session went first
    with memo.claim("c", "1") as claim:
        assert claim.recall(lambda: "e") == {"id": "1"} and claim.recall(lambda: "other") is None
