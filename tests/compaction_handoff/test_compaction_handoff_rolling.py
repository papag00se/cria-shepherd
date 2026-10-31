"""The rolling engine (selfcompact.rolling): when it fires, what it folds, and what it never loses."""
import json

import pytest

from cria import contextfloor, denial, prompts, resultnotes, selfcompact as sc
from cria.content_reduce import est_tokens
from cria.memoryeffects import Effect
from compaction_handoff_helpers import asst, call, history, result, write

FACTS = "⟦ctx:facts⟧ cria-derived dependency surface"

def run(msgs, writer="BRIEFING", state=None, **kw):
    seen = []

    def summarize(mm, **k):
        seen.append(mm)
        return writer(mm, **k) if callable(writer) else writer
    kw = {"room_tokens": 100, "keep_tail_tokens": 300, "recompact_tokens": 100, **kw}
    return sc.rolling(sc.RollingInput(msgs, summarize, **kw), state or sc.CompactState()), seen

text = lambda m: m.get("content") or ""

@pytest.mark.parametrize("extra,room,fires", [
    (0, 2100, False), (0, 2099, True),        # 20 turns x 100 tok: fires the moment one more 100-tok turn will not fit
    (250, 2599, True),                        # the newest turn read 350 tok: the same rule at the measured, larger growth
    (0, 2599, False)])                        # ...and a quiet history is NOT compacted at the room a bursty one is
def test_compaction_fires_exactly_when_one_more_turn_of_measured_growth_would_not_fit(extra, room, fires):
    """Fires iff view + largest recent turn growth > room - measured, never a configured size trigger."""
    msgs = history(19) + [asst(50 + extra // 2), {"role": "tool", "tool_call_id": "c", "content": "y" * 200 + "z" * 2 * extra}]
    assert sum(est_tokens(m["content"]) for m in msgs) == 2000 + extra
    assert run(msgs, room_tokens=room)[0].applied is fires

def test_without_a_measured_window_only_floor_pressure_or_unreadable_evidence_compacts():
    """Without a measured coder window only floor pressure compacts; an unmeasured-evidence-room view compacts only when the rendered evidence would not fit."""
    huge = history(200, 400)
    assert not run(huge, room_tokens=None)[0].applied            # no window, no prediction: size alone never compacts
    assert run(huge, room_tokens=None, floor_pressure=lambda view: True)[0].applied
    assert not run(huge, room_tokens=None, floor_pressure=lambda view: False)[0].applied
    msgs = history(20)                                            # the writer/validators read the RENDERED evidence whole
    assert run(msgs, room_tokens=10 ** 6, evidence_room_tokens=1000)[0].applied
    assert not run(msgs, room_tokens=10 ** 6, evidence_room_tokens=10 ** 6)[0].applied

def test_the_old_middle_rolls_into_a_labelled_rollup_and_the_newest_turn_stays_verbatim():
    """The old middle folds into one labelled rollup behind the pinned task; the newest turn, order and caller's list are untouched."""
    stale = {"role": "user", "content": f"{sc.FILES_MARKER} stale list"}
    msgs = history(20)[:-2] + [stale] + history(20)[-2:]
    before = json.dumps(msgs)
    res, seen = run(msgs, pinned_task="ORIGINAL TASK", files_list=f"{sc.FILES_MARKER} FRESH a.py (10 B)")
    out = res.messages
    assert res.effect is Effect.REDUCED and json.dumps(msgs) == before
    assert out[0] == msgs[0] and text(out[1]).startswith(sc.TASK_MARKER) and text(out[1]).endswith("ORIGINAL TASK")
    rollup = next(m for m in out if sc.SUMMARY_MARKER in text(m))
    assert text(rollup).endswith("[increment 1 of 1]\nBRIEFING") and "cria" not in text(rollup).lower()
    assert [text(m) for m in out if text(m).startswith(sc.FILES_MARKER)] == [f"{sc.FILES_MARKER} FRESH a.py (10 B)"]
    tail = out[out.index(rollup) + 1:]
    assert tail and tail[-1] == msgs[-1] and tail == [m for m in msgs[-len(tail) - 1:] if m is not stale]      # newest turn verbatim, in order, minus the stale list
    folded = seen[0]
    assert folded == msgs[1:1 + len(folded)] and len(folded) == res.state.covered - 1 and stale not in folded     # the writer read exactly the replaced span
    assert len(out) < len(msgs) and res.state.covered == len(msgs) - len(tail) - 1

def test_a_step_boundary_folds_all_work_and_leaves_a_view_that_fits_the_tail_alone():
    """A step boundary keeps no verbatim work tail, but never folds a view that fits the tail."""
    msgs = history(10)
    res, _ = run(msgs, force=True, pinned_task="T")
    assert [m["role"] for m in res.messages] == ["system", "user", "user"]        # system + task + rollup, no work tail
    assert sc.SUMMARY_MARKER in text(res.messages[-1])
    small = history(1, 20)                                                         # fits a 30-token boundary tail
    res, seen = run(small, force=True, boundary_keep_tail_tokens=30)
    assert res.messages is small and not seen

@pytest.mark.parametrize("force,answer", [(True, "   "), (False, "tool: Chunk ID: x\nassistant: did things")])
def test_an_empty_or_all_echo_briefing_folds_nothing_and_leaves_history_verbatim(force, answer):
    """A reasoning model that burns its budget emits "" (6/6 on one capture); adopting it would replace the whole step's work with a header over nothing."""
    msgs = history(30)
    res, seen = run(msgs, answer, force=force, keep_tail_tokens=120)
    assert len(seen) == 1 and res.effect is Effect.WITHHELD and res.messages == msgs and res.state.summary == ""

def test_a_rejected_increment_keeps_the_standing_rollup_and_is_not_asked_again_until_a_new_band_grows():
    """ornith1.5_9b / Java run07: a rejected writer made coder call 0077 carry 47 raw messages and no rollup."""
    msgs = history(30)
    first, _ = run(msgs)
    covered = first.state.covered
    grown = msgs + history(12)[1:]
    rejected, seen = run(grown, "", state=first.state)
    assert rejected.effect is Effect.WITHHELD and len(seen) == 1
    assert (rejected.state.summary, rejected.state.covered) == (first.state.summary, covered)
    kept = rejected.messages
    assert sc.SUMMARY_MARKER in text(kept[1]) and kept[2:] == grown[covered:]          # rollup + verbatim band, never the raw history
    again, seen = run(grown, "", state=rejected.state)
    assert not seen and again.messages == kept                                       # same evidence: not paid for twice

def test_later_increments_summarize_only_the_new_band_in_order_and_lost_state_falls_back_to_the_whole_middle():
    """Later increments summarize only the new band and are labelled in order; lost coverage state falls back to the whole middle."""
    msgs = history(30)
    one, _ = run(msgs, "FIRST")
    grown = msgs + history(30)[1:]
    two, seen = run(grown, "SECOND", state=one.state)
    covered = one.state.covered
    assert seen[0] == grown[covered:covered + len(seen[0])]                    # starts exactly where the rollup ends
    body = text(two.messages[1])
    assert body.index("[increment 1 of 2]") < body.index("FIRST") < body.index("[increment 2 of 2, written after increment 1]") < body.index("SECOND")
    assert two.state.summary == "FIRST\n\nSECOND" and two.state.parts == ("FIRST", "SECOND")
    lost, seen = run(msgs[:20], "WHOLE", state=sc.CompactState("FIRST", covered=999, attempted=999))
    assert seen and seen[0][0] == msgs[1] and lost.state.summary == "WHOLE"

def test_a_summary_past_the_refold_threshold_is_condensed_once_and_a_failed_refold_keeps_the_increment():
    """A summary past the refold threshold is condensed once and labelled; a failed refold keeps the un-refolded text."""
    big, folded = "a" * 13000, "CONDENSED"
    refolds = []
    out, _ = run(history(30), big, refold=lambda s, **k: (refolds.append(s), folded)[1], refold_tokens=2000)
    assert refolds == [big] and out.refold_effect is Effect.REDUCED and out.state.summary == folded
    assert "a condensation of 1 earlier increments" in text(out.messages[1])
    out, _ = run(history(30), big, refold=lambda s, **k: "", refold_tokens=2000)
    assert out.refold_effect is Effect.WITHHELD and out.state.summary == big          # too long beats gone

def test_a_middle_made_only_of_anchors_ships_no_rollup_header_and_asks_nothing():
    """A middle made only of anchors asks no writer and ships no rollup header over nothing."""
    anchors = [{"role": "user", "content": f"⟦ctx:briefing⟧ prior {i}"} for i in range(6)]
    res, seen = run([{"role": "system", "content": "s"}] + anchors + history(10)[1:][-2:], keep_tail_tokens=200)
    assert not seen and not any(sc.SUMMARY_MARKER in text(m) for m in res.messages)

def test_the_tail_never_starts_inside_an_exchange():
    """60 of 315 real self-compactions shipped a tool result whose call was folded - the coder read "Wrote Importer.java" in the user's voice."""
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}]
    for i in range(6):
        msgs += [call(f"c{i}", "read_file", path=f"f{i}"), result(f"c{i}", f"r{i} " + "y" * 560)]
    res, seen = run(msgs, keep_tail_tokens=145)               # an exchange is ~140 tok: the budget cuts between call and result
    calls = lambda ms: {tc["id"] for m in ms for tc in m.get("tool_calls") or []}
    answers = lambda ms: {m["tool_call_id"] for m in ms if m["role"] == "tool"}
    assert res.applied and answers(res.messages) and calls(res.messages) == answers(res.messages)
    assert calls(seen[0]) == answers(seen[0]) and contextfloor.ensure_tool_integrity(res.messages)[1] == 0
    lone = [msgs[0], call("only", "read_file"), result("only", "z" * 600)]
    assert run(lone, room_tokens=10, keep_tail_tokens=40, recompact_tokens=5)[0].messages is lone     # a tail spanning everything folds nothing

def test_anchors_survive_verbatim_identical_copies_collapse_and_an_anchored_result_keeps_its_call():
    """Anchors survive verbatim; byte-identical exchanges collapse (counted) but copies differing in their tool call both stay; an anchored result keeps its call."""
    digest = "[API endpoints (33): /, /handles/{handle}]\n[response shape — fields]\n" + "x" * 400
    denial_text = "⟦ctx:denied⟧ spec.json is a large reference document\n" + digest
    msgs = ([{"role": "system", "content": "s"}, {"role": "user", "content": "task"}, asst(300, "work")]
            + [m for i in range(6) for m in (call(f"d{i}", "read_file", path="spec.json"), result(f"d{i}", denial_text), asst(300))])
    msgs.insert(4, {"role": "user", "content": denial_text.replace("spec.json", "openapi.yaml")})   # a distinct anchor
    twins = [{"role": "assistant", "content": digest, "tool_calls": [{"id": f"t{i}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": p})}}]}
             for i, p in enumerate(("a.py", "b.py"))]                                                    # identical text, different CALL: both must survive
    msgs[3:3] = [twins[0], asst(300), twins[1]]
    events = []
    res, seen = run(msgs, force=True, rlog=type("R", (), {"emit": lambda self, k, **kw: events.append((k, kw))})())
    kept = [text(m) for m in res.messages]
    assert kept.count(denial_text) == 1 and any("openapi.yaml" in k for k in kept)          # nothing paraphrased, nothing trimmed
    assert not any("large reference document" in text(m) for ms in seen for m in ms)        # anchors never reach the writer
    paired = [m for m in res.messages if m.get("role") == "tool"]
    assert len(paired) == 1 and any(tc["id"] == paired[0]["tool_call_id"] for m in res.messages for tc in m.get("tool_calls") or [])
    assert [t["function"]["arguments"] for m in res.messages for t in m.get("tool_calls") or [] if t["id"].startswith("t")] == [json.dumps({"path": "a.py"}), json.dumps({"path": "b.py"})]
    assert events == [("context.anchor_dedup", {"reshape": "dedup", "dropped": 10})]      # 5 repeated exchanges, call + result each, counted

def test_a_note_cria_appended_to_a_tool_result_rides_on_verbatim_and_its_host_folds_with_its_call():
    """ornith1.5_9b / Java run07 0075: a ⟦ctx:facts⟧ note on `Wrote pom.xml` made the host an anchor - the writer saw the edit with no result, and the host rode on alone re-roled as a user turn."""
    pair = [call("c1", "edit_file", path="pom.xml", old_string="a", new_string="b"), result("c1", "Wrote pom.xml")]
    resultnotes.append_note(pair[1], FACTS)
    assert sc.has_anchor(pair[1]) is False
    res, seen = run([{"role": "system", "content": "s"}] + [asst(200)] + pair + [asst(200)] * 5, force=True)
    writer_view = " ".join(text(m) for m in seen[0])
    assert "pom.xml" in writer_view and "Wrote pom.xml" in writer_view and FACTS not in writer_view
    assert [text(m) for m in res.messages].count(FACTS) == 1
    assert contextfloor.ensure_tool_integrity(res.messages)[1] == 0

def _w(cid, path, body):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": path, "content": body})}}]}

@pytest.mark.parametrize("first,second,first_keeps_content,claim", [
    (denial.LANDED, denial.LANDED, False, "an EARLIER version of a.py, replaced by a later write"),
    (denial.REFUSED, denial.LANDED, True, "this write was REFUSED"),
    (denial.LANDED, denial.UNCERTAIN, True, ""),                # the later attempt is unproven: no claim about these bytes either way, and they stay
    (None, denial.LANDED, True, "")])                           # no result at all: any claim would be invented
def test_an_older_write_payload_is_stubbed_only_to_what_later_evidence_proves(first, second, first_keeps_content, claim):
    """A refused write's bytes exist nowhere else (mellum2 1786196176: a REFUSED edit was called landed for ~30 calls); orders-api-py: a timer-fired gate call once stubbed every write, so the briefer invented behaviour from the task text."""
    body = "x = 1\n" * 200
    msgs = [_w("w1", "a.py", body)] + ([result("w1", "Wrote", first)] if first else []) + [_w("w2", "a.py", body), result("w2", "Wrote", second)]
    out = sc.stub_old_write_args(msgs + [call("g", "exec_command", cmd="pytest"), result("g")])      # a trailing gate probe is not the working set
    args = json.loads(out[0]["tool_calls"][0]["function"]["arguments"])
    assert ("content" in args) is first_keeps_content and ("[elided" in text(out[0])) is bool(claim) and claim in text(out[0])
    assert json.loads(out[-4]["tool_calls"][0]["function"]["arguments"])["content"] == body      # the newest WRITE stays whole
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == json.dumps({"path": "a.py", "content": body})     # input never mutated

def test_grounding_is_passed_as_a_separate_read_only_scope_and_never_advances_coverage():
    """Newer-turn grounding reaches the writer as a separate read-only scope and never advances coverage; one-argument callbacks still work."""
    msgs = history(30)
    scopes = []
    res, _ = run(msgs, lambda mm, newer_messages=None: scopes.append(newer_messages) or "B", with_grounding=True)
    tail = res.messages[res.messages.index(next(m for m in res.messages if sc.SUMMARY_MARKER in text(m))) + 1:]
    assert scopes == [msgs[res.state.covered:]] and msgs[res.state.covered:] == tail
    plain, _ = run(msgs, lambda mm: "B")                      # one-argument callbacks keep working by default
    assert plain.state == res.state

def test_the_briefing_ask_echoed_back_is_stripped_per_call_site_and_a_real_briefing_is_untouched():
    """mellum2 0/4: cria's ask quoted at itself ('Do not emit a tool/function call' x145) filled 79% of the coder's next prompt."""
    ask, refold_ask = prompts.load("selfcompact_summary"), prompts.load("selfcompact_refold")
    echo, real = sc._ask_sentences(ask)[0], "The coder fetched the spec and found GET /handles/{handle}."
    assert sc.strip_frame_echo("\n".join([echo] * 145 + [real]), ask) == real
    assert sc.strip_frame_echo(echo, ask) == "" and sc.strip_frame_echo(sc._ask_sentences(refold_ask)[0], refold_ask) == ""
    assert sc.strip_frame_echo("You have NO tools", ask) == "You have NO tools"          # a short heading can collide by chance
    res, _ = run(history(30), echo + "\n" + real)
    assert res.state.summary == real
    refolded, _ = run(history(30), "n" * 9000, refold=lambda s, **k: sc._ask_sentences(refold_ask)[0] + "\nCONDENSED", refold_tokens=100)
    assert refolded.state.summary == "CONDENSED"
