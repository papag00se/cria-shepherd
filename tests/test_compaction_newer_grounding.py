"""Whole-unit acceptance: replacement scope is not grounding scope.

The six Loop integration cases have a preserved real-red before proof and now
exercise the released wiring. Engine/API cases have their separate before proof.
No skip/xfail: missing evidence must fail. All upstreams here are fake.
The interface is behavioral: writer/fidelity get identical labelled newer PUBLIC
turns, while the existing coverage boundary, tail and retry throttle stay untouched.

Engine/API interface implemented after its explicit partial release:
- selfcompact.compact(..., with_grounding=True) calls summarize/refold with
  keyword-only newer_messages=messages[tail_start:], using the existing boundary.
  The default preserves one-argument callbacks and advances no coverage into it.
- selfcompact.compaction_request_parts/messages/request(..., newer_messages=...)
  use one public-content renderer and the per-block middle/newer prompt labels.
  None preserves old request bytes; [] labels only the boundary replacement.
  No private extraction, caps, replacement-slice expansion or ledger changes.
Loop wiring implemented after the parent's final explicit release:
- Loop._self_compact make_summary/refold_summary use the same block producer for
  writer/fidelity, including identical newer public evidence in the rare refold.
  Current files/check facts and the original root retain their existing seats.
- loop._briefing_gate_ground_truth uses existing gate_age/newer_own_run owners
  and the same anchored-age/staleness prompt fragments as the harness.
- Only _self_compact and _briefing_gate_ground_truth changed against the accepted
  O19 Loop snapshot. Only compact and the three compaction-request functions
  changed against the accepted ledger snapshot. No O19 diagnosis, root authority,
  shared inert insertion, validators or work-ledger logic was edited.

Legacy assertions repaired in the separately released legacy phase:
- test_the_briefing_writer_is_shown_the_disk.py: the unconditional fresh heading
  and 'created unless listed' assertions conflict with stale/partial scope.
- test_the_briefing_may_not_invent_a_failure.py: same unconditional listing rule.
- test_briefing_vs_disk.py: retain its every-sentence preservation assertion,
  replace only the old 'DO exist' title expectation with observed-scope evidence.
Those three existing files are not part of this engine phase's edits.
"""
import copy
import json

import pytest

from cria import loop, selfcompact, server
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore
from tests.test_selfcompact_wiring import _Rlog, _synth, _validation_reply

NEWER = "NEWER RETAINED EVIDENCE"
OUTPUT = "imported 0 rows covering 9000 SKUs\nempty4=0\nProcess exited with code 0"
SOURCE = "def import_rows(rows):\n    count = 0\n    for row in rows:\n        store(row)\n    return count\n"
PUBLIC = "The observed row count differs from the baseline."
PRIVATE = "PRIVATE_DIAGNOSIS_NOT_PUBLIC"
TASK = "Preserve row results and record unresolved risks."


def pair(tid, name, args, output):
    return [{"role": "assistant", "content": "", "tool_calls": [
        {"id": tid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        {"role": "tool", "tool_call_id": tid, "content": output}]


def history():
    return ([{"role": "system", "content": "system"}]
            + [{"role": "assistant", "content": f"Older work {i}: " + "x" * 800} for i in range(80)]
            + pair("baseline", "exec_command", {"cmd": "./original-check"},
                   "imported 40000 rows covering 9000 SKUs")
            + pair("zero", "exec_command", {"cmd": "./current-check"}, OUTPUT)
            + [{"role": "assistant", "content": PUBLIC, "reasoning_content": PRIVATE}]
            + pair("source", "read_file", {"path": "importer.py"}, SOURCE))


def make_loop(calls, *, reject=False, enabled=True):
    def chat(body, rlog):
        calls.append(copy.deepcopy(body))
        answer = _validation_reply(body["messages"][0]["content"])
        if reject and answer == "FAITHFUL":
            answer = "UNFAITHFUL"
        answer = answer or "An increment of earlier work was observed."
        return json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
    ctx = LoopContext(planner=None, coder_chat=chat, reasoner_chat=chat, compactor_chat=chat,
                      compactor_role=Role(name="compactor", backend="local"),
                      planner_enabled=False, runs_dir="", self_compact=enabled,
                      trigger_compaction=100)
    return Loop(ctx, LoopStore())


@pytest.mark.parametrize("reject", (False, True))
@pytest.mark.parametrize("incremental", (False, True))
def test_newer_grounding_is_shared_without_advancing_coverage_or_replacing_tail(reject, incremental):
    calls = []
    driver = make_loop(calls, reject=reject)
    sess = _synth()
    if incremental:
        sess.compact_state = selfcompact.CompactState(summary="Earlier accepted increment.", covered=3, attempted=3)
    before_state = copy.deepcopy(sess.compact_state)
    messages = history()
    untouched = copy.deepcopy(messages)
    boundary = selfcompact._tail_start(messages, 1, selfcompact.KEEP_TAIL_TOKENS)
    tail = messages[boundary:]
    out = driver._self_compact(messages, sess, 1, _Rlog(), pinned_task=TASK)
    assert messages == untouched  # rendering cannot mutate the incoming history
    assert sess.compact_state.attempted == boundary
    if reject:
        assert out == messages
        assert sess.compact_state.summary == before_state.summary
        assert sess.compact_state.covered == before_state.covered
    else:
        assert out[-len(tail):] == tail  # paired calls/results and public/private channels remain intact
        assert sess.compact_state.covered == boundary
        if incremental:
            assert sess.compact_state.summary.startswith(before_state.summary + "\n\n")
        assert OUTPUT not in sess.compact_state.summary  # no evidence stuffing
    count = len(calls)
    driver._self_compact(messages, sess, 1, _Rlog(), pinned_task=TASK)
    assert len(calls) == count  # same replacement band does not defeat the retry throttle

    writer = next(c for c in calls if "You are writing a briefing" in c["messages"][0]["content"])
    fidelity = next(c for c in calls if "UNFAITHFUL or FAITHFUL" in c["messages"][0]["content"])
    def newer_blocks(body):
        return [m["content"] for m in body["messages"] if m["content"].startswith(NEWER)]
    w, f = newer_blocks(writer), newer_blocks(fidelity)
    assert w, "the writer still sees only the older replacement middle"
    assert w == f, "writer and fidelity must read one producer's identical newer grounding"
    rendered = "\n".join(w)
    for evidence in (OUTPUT, SOURCE, PUBLIC, "imported 40000 rows covering 9000 SKUs", "./current-check"):
        assert evidence in rendered
    for body in (writer, fidelity):
        assert PRIVATE not in "\n".join(m["content"] for m in body["messages"])
    assert all("read-only grounding" in b and "not extra work to summarize" in b for b in w)


def test_rolling_and_harness_appendices_share_known_age_and_newer_run_provenance():
    from tests.test_a_carried_check_names_the_coders_newer_run import FLAG, _Server
    sess = _synth()
    sess.last_gate_flag = FLAG
    sess.last_gate_red = True
    sess.last_gate_seq = 5
    sess.action_seq = 7
    loop._track_own_checks(sess, pair("rerun", "exec_command", {"cmd": "mvn -q compile"},
                                    "Process exited with code 0\nOutput:\n"))
    sess.action_seq = 8
    rolling = loop._briefing_gate_ground_truth(sess)
    harness = server._last_checks_note(_Server(sess), "k")
    for note in (rolling, harness):
        assert FLAG in note
        assert "3 of your calls before this handoff was written" in note
        assert "`mvn -q compile`" in note
        assert "NEWER than this block" in note and "exited with code 0" in note


def test_rare_refold_uses_the_same_newer_grounding_without_stuffing_the_summary():
    calls = []
    driver = make_loop(calls)
    sess = _synth()
    prior = "Earlier accepted work. " * (selfcompact.REFOLD_TOKENS // 5 + 100)
    assert selfcompact.est_tokens(prior) >= selfcompact.REFOLD_TOKENS
    sess.compact_state = selfcompact.CompactState(summary=prior, covered=3, attempted=3)
    messages = history()
    boundary = selfcompact._tail_start(messages, 1, selfcompact.KEEP_TAIL_TOKENS)
    out = driver._self_compact(messages, sess, 1, _Rlog(), pinned_task=TASK)
    assert out[-len(messages[boundary:]):] == messages[boundary:]
    assert sess.compact_state.covered == boundary
    assert OUTPUT not in sess.compact_state.summary
    writers = [c for c in calls if _validation_reply(c["messages"][0]["content"]) is None]
    fidelities = [c for c in calls if "UNFAITHFUL or FAITHFUL" in c["messages"][0]["content"]]
    assert len(writers) == len(fidelities) == 2, "the real rare-refold path must execute"
    assert "use newer retained evidence only to ground or qualify" in writers[1]["messages"][0]["content"].lower()
    packets = [[m["content"] for m in c["messages"] if m["content"].startswith(NEWER)]
               for c in writers + fidelities]
    assert packets[0], "no newer grounding reached the first writer"
    assert all(p == packets[0] for p in packets)
    assert OUTPUT in "\n".join(packets[0])


def test_boundary_fold_has_no_newer_tail_to_mislabel():
    calls = []
    driver = make_loop(calls)
    sess = _synth()
    messages = history()
    driver._self_compact(messages, sess, 1, _Rlog(), force=True, pinned_task=TASK)
    assert sess.compact_state.covered == len(messages)
    writer = calls[0]
    evidence = "\n".join(m["content"] for m in writer["messages"][1:])
    assert OUTPUT in evidence and SOURCE in evidence
    assert NEWER not in evidence  # every turn is replacement history at this boundary
    assert PRIVATE not in evidence


@pytest.mark.parametrize("reject", (False, True))
@pytest.mark.parametrize("incremental", (False, True))
@pytest.mark.parametrize("force", (False, True))
def test_engine_optional_grounding_preserves_boundary_tail_increment_and_throttle(reject, incremental, force):
    messages = history()
    before = copy.deepcopy(messages)
    state = selfcompact.CompactState(summary="Prior increment." if incremental else "",
                                     covered=3 if incremental else 0,
                                     attempted=3 if incremental else 0)
    calls = []
    def summarize(middle, *, newer_messages):
        calls.append((copy.deepcopy(middle), copy.deepcopy(newer_messages)))
        return "" if reject else "New increment."
    boundary = selfcompact._tail_start(messages, 1, 0 if force else selfcompact.KEEP_TAIL_TOKENS)
    lo = 3 if incremental else 1
    out, after, applied = selfcompact.compact(messages, summarize, state, trigger_tokens=100,
                                              force=force, with_grounding=True)
    assert calls == [(messages[lo:boundary], messages[boundary:])]
    assert messages == before
    assert after.attempted == boundary
    if reject:
        assert out is messages and not applied
        assert after.covered == state.covered and after.summary == state.summary
    else:
        assert applied and after.covered == boundary
        assert after.summary == (("Prior increment.\n\n" if incremental else "") + "New increment.")
        if not force:
            assert out[-len(messages[boundary:]):] == messages[boundary:]
    selfcompact.compact(messages, summarize, after, trigger_tokens=100,
                        force=force, with_grounding=True)
    assert len(calls) == 1


def test_engine_refold_receives_the_same_read_only_grounding():
    messages = history()
    seen = []
    def summarize(middle, *, newer_messages):
        seen.append(("middle", copy.deepcopy(newer_messages)))
        return "An accepted increment."
    def refold(text, *, newer_messages):
        seen.append(("refold", copy.deepcopy(newer_messages)))
        assert text == "An accepted increment."
        return "Condensed earlier work."
    out, state, applied = selfcompact.compact(messages, summarize, selfcompact.CompactState(),
                                              trigger_tokens=100, refold=refold,
                                              refold_tokens=1, with_grounding=True)
    boundary = selfcompact._tail_start(messages, 1, selfcompact.KEEP_TAIL_TOKENS)
    assert seen == [("middle", messages[boundary:]), ("refold", messages[boundary:])]
    assert state.covered == boundary and applied
    assert state.summary == "Condensed earlier work."
    assert out[-len(messages[boundary:]):] == messages[boundary:]


def test_engine_legacy_one_argument_callbacks_stay_compatible():
    seen = []
    def summarize(middle):
        seen.append("middle")
        return "Accepted earlier work."
    def refold(text):
        seen.append("refold")
        return "Condensed earlier work."
    _, state, applied = selfcompact.compact(history(), summarize, selfcompact.CompactState(),
                                            trigger_tokens=100, refold=refold, refold_tokens=1)
    assert seen == ["middle", "refold"] and applied
    assert state.summary == "Condensed earlier work."


def test_rendering_uses_one_public_content_owner_with_two_labelled_scopes():
    from cria import prompts
    middle = pair("old", "exec_command", {"cmd": "./check"}, "old failure at file:12")
    newer = (pair("new", "exec_command", {"cmd": "./check"}, OUTPUT)
             + [{"role": "assistant", "content": PUBLIC, "reasoning_content": PRIVATE}])
    before = copy.deepcopy((middle, newer))
    blocks = selfcompact.compaction_request_parts(middle, newer_messages=newer)
    labels = prompts.load_map("compaction_grounding")
    expected = [prompts.fill(labels[scope], turn=selfcompact.serialize([m]))
                for scope, messages in (("middle", middle), ("newer", newer))
                for m in selfcompact.compaction_evidence_messages(messages)]
    assert blocks == expected
    assert (middle, newer) == before
    assert "old failure at file:12" in "\n".join(blocks)
    assert OUTPUT in "\n".join(blocks) and PRIVATE not in "\n".join(blocks)
    request = selfcompact.compaction_request_messages(middle, newer_messages=newer)
    assert [m["content"] for m in request[1:-1]] == blocks
    assert request[-1]["content"] == selfcompact.compaction_ask()
    text = selfcompact.compaction_request(middle, newer_messages=newer)
    assert text == "\n\n".join(blocks + [selfcompact.compaction_ask()])


def test_rendering_opt_out_keeps_existing_request_bytes_and_boundary_has_no_newer_blocks():
    messages = pair("old", "exec_command", {"cmd": "./check"}, OUTPUT)
    expected = selfcompact.serialize(selfcompact.compaction_evidence_messages(messages))
    assert selfcompact.compaction_request(messages) == expected + "\n\n" + selfcompact.compaction_ask()
    assert selfcompact.compaction_request_parts(messages) == [
        selfcompact.serialize([m]) for m in selfcompact.compaction_evidence_messages(messages)]
    boundary = selfcompact.compaction_request_parts(messages, newer_messages=[])
    assert boundary and all(b.startswith("MIDDLE BEING REPLACED") for b in boundary)
    assert not any(b.startswith(NEWER) for b in boundary)


def test_disabled_compaction_and_short_history_make_no_new_calls():
    for enabled, messages in ((False, history()), (True, [{"role": "user", "content": "short"}])):
        calls = []
        driver = make_loop(calls, enabled=enabled)
        body = {"messages": messages}
        assert driver._self_compact_single(body, _synth(), _Rlog(), root_task=TASK) is body
        assert calls == []
