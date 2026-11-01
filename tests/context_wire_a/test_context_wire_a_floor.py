"""The context floor (contextfloor.fit): the one place a request is made to fit the measured window.

Promise: a request over budget is reduced cheapest-first, oldest WHOLE units go with a label naming what
went, protected content (system, task, active turn, anchors, tool menu) survives, nothing is silently
lost and an unfittable request is reported as over budget, never declared fit.
"""
import copy
import json
import math

import pytest

from cria import bodykeys, contextfloor as cf, prompts
from cria.content_reduce import content_reduce, digest_reduce, est_tokens
from cria.loop import BRIEFING_OPEN
from cria.probegate import SECTION_PREFIX, _gate_sentinel


def u(text):
    return {"role": "user", "content": text}


def a(text="", call_id=None, name="read_file", args="{}"):
    m = {"role": "assistant", "content": text}
    if call_id:
        m["tool_calls"] = [{"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}]
    return m


def tool(call_id, content, **hints):
    return {"role": "tool", "tool_call_id": call_id, "content": content, **hints}


def pairs(n, size=600, tag="result"):
    out = []
    for i in range(n):
        out += [a("", f"c{i}", args=json.dumps({"path": f"src/mod{i}.py"})), tool(f"c{i}", f"{tag} {i} " + "r" * size)]
    return out


def menu(n, desc):
    """``desc``: a size (one unbroken run of letters) or a sentence-structured text used as is."""
    return [{"type": "function", "function": {
        "name": f"op_{i}", "description": "D" * desc if isinstance(desc, int) else desc,
        "parameters": {"type": "object", "properties": {"arg": {"type": "string", "description": "P" * desc if isinstance(desc, int) else desc}},
                       "required": ["arg"]}}} for i in range(n)]


def notes(out):
    return [m["content"] for m in out if cf._COMPACTED_MARK in str(m.get("content") or "")]


def test_a_fitting_request_is_returned_unchanged_and_inputs_are_never_mutated():
    """No pressure -> identity; under pressure the caller's lists/dicts are still untouched (pure)."""
    small = [{"role": "system", "content": "sys"}, u("hi")]
    out, _, rep = cf.fit(small, None, window=49152, reserve=4096)
    assert out == small and not rep.applied and not rep.over_budget
    exact = [u("task")] + pairs(3, 2000) + [u("now")]
    est = cf.est_total(exact, None)                      # a request whose estimate IS the budget fits: the floor is not engaged at all
    out, _, rep = cf.fit(exact, None, window=est + 100, reserve=100, safety=1.0)
    assert out == exact and not rep.applied and cf.fit(exact, None, window=est + 99, reserve=100, safety=1.0)[2].applied
    big, tools = [u("task"), a("Z" * 12000), u("now")], menu(40, 500)
    snap = json.dumps((big, tools))
    cf.fit(big, tools, window=3000, reserve=500)
    assert json.dumps((big, tools)) == snap


def test_overflow_drops_oldest_whole_turns_keeps_system_and_active_turn_and_names_every_dropped_turn():
    """Old turns go with a label; protected ends survive; one huge turn cannot starve the others' lines
    (gemma4 / shipping-rates-rb: one dropped write_file payload took the whole note and every older turn was
    counted away as 'could not be summarized'); the note costs less than what it replaces and the result fits."""
    history = [a(f"step {i}: I will now check the {i}th thing carefully") for i in range(19)]
    history += [a("here is the whole file\n" + "x = 1\n" * 200)]    # newest dropped: it asks for the whole note first
    msgs = [{"role": "system", "content": "SYSTEM PRELUDE"}, u("the task")] + history + [u("y" * 24000)]
    out, _, rep = cf.fit(msgs, None, window=12000, reserve=500, pinned_task="the task")
    assert rep.turns_dropped >= 15 and not rep.over_budget
    assert out[0]["content"] == "SYSTEM PRELUDE" and out[-1]["content"] == "y" * 24000
    assert "the task" in [m["content"] for m in out]
    (note,) = notes(out)
    assert all(f"step {i}:" in note for i in range(19))   # every dropped turn is named
    assert "could not be summarized" not in note
    assert est_tokens(note) < est_tokens("".join(cf._msg_text(m) for m in history))
    assert (rep.msg_tokens_after + rep.tool_tokens) * cf.SAFETY_FACTOR <= 12000 - rep.reserve < 12000


def _write_note(results, paths=("pkg/target.py",)):
    msgs = [{"role": "system", "content": "sys"}]
    for i, (path, result) in enumerate(zip(paths, results)):
        msgs += [a("", f"w{i}", "write_file", json.dumps({"path": path, "content": "x"})), result(f"w{i}")]
    msgs.append(u("y" * 6000))
    out, _, rep = cf.fit(msgs, None, window=1500, reserve=200)
    assert rep.turns_dropped >= 2 * len(paths)
    return notes(out)[0]


@pytest.mark.parametrize("outcome", [None, "unknown", "uncertain", "refused", "unapplied"])
def test_the_note_never_claims_a_modification_cria_did_not_prove(outcome):
    """A path is named as MODIFIED only when the write's own typed receipt says landed (quoted
    confirmations, unknown/uncertain/refused/unapplied results are not facts)."""
    hint = {bodykeys.RESULT_OUTCOME: outcome} if outcome else {}
    claim = prompts.render("compacted_modified_paths", files="pkg/target.py")
    assert claim not in _write_note([lambda cid: tool(cid, "Wrote pkg/target.py", **hint)])
    landed = {bodykeys.RESULT_OUTCOME: "landed"}
    assert claim in _write_note([lambda cid: tool(cid, "Wrote pkg/target.py", **landed)])


def test_every_proven_modified_file_is_listed_without_a_cap():
    paths = [f"pkg/mod_{i}.py" for i in range(40)]
    note = _write_note([lambda cid: tool(cid, "ok", **{bodykeys.RESULT_OUTCOME: "landed"})] * 40, paths)
    assert all(p in note.split("Everything above")[0] for p in paths)


def test_a_note_about_dropped_reads_still_says_it_describes_the_past():
    """shipping-rates-rb / ternary-bonsai: the note handed the STARTING rates.rb back as current; the caveat
    only fired when the dropped span contained a write, but staleness does not depend on that."""
    msgs = [{"role": "system", "content": "sys"}] + pairs(8) + [u("y" * 6000)]
    out, _, _ = cf.fit(msgs, None, window=1500, reserve=200)
    (note,) = notes(out)
    assert prompts.load("compacted_history_provenance").strip() in note
    assert "read_file" in note and note.index("read_file") < note.index("src/mod")   # name precedes its arguments


def test_anchors_and_the_steer_before_the_last_user_turn_survive_the_drop_in_order():
    """A1 call 0032: [.., ⟦ctx:steer⟧, ⟦ctx:facts⟧] over budget protected only 'the last user message
    onward', so the steer was a droppable middle turn folded into the past-tense digest. Anchors (briefing,
    gate output) are likewise the last thing sacrificed."""
    briefing = f"{BRIEFING_OPEN} prior work: built the resolver ⟦/ctx:briefing⟧"
    gate = f"{SECTION_PREFIX}probe-0___\n" + "mcp_client.py:14: SyntaxError\n" * 30
    steer = "⟦ctx:steer⟧ The repo's automated checks pass; the task is not finished."
    facts = "⟦ctx:facts⟧ FILES YOU HAVE ALREADY READ " + "f" * 3000
    msgs = ([{"role": "system", "content": "sys"}, u("Fix the importer"), u(briefing),
             a("", "g", "shell", json.dumps({"cmd": _gate_sentinel(["pytest -q"]) + "\ncd /ws && pytest -q"})), tool("g", gate)]
            + pairs(12, 900, "step") + [u(steer), u(facts)])
    out, _, rep = cf.fit(msgs, None, window=2200, reserve=300, pinned_task="Fix the importer")
    texts = [m.get("content") for m in out]
    assert rep.turns_dropped >= 10
    assert briefing in texts and gate in texts and "Fix the importer" in texts
    assert texts[-2:] == [steer, facts]
    assert not any("automated checks pass" in t for t in notes(out))


@pytest.mark.parametrize("quoted", [f"{SECTION_PREFIX}probe-0___\nEXIT:0", "see ⟦ctx:facts⟧ in the docs", "⟦ctx:rollup⟧ all done", "⟦ctx:briefing⟧ x ⟦/ctx:briefing⟧"])
def test_a_marker_quoted_inside_a_tool_result_or_a_written_file_protects_nothing(quoted):
    """RED1, wave 10b: an anchor is cria's by provenance (role + position), not because its bytes appear anywhere in a message. A read of
    any file that quotes a marker (cria's own sources do) was un-reducible and un-droppable, so the floor reported over budget for
    a conversation that was only large. Control: the same marker OPENING a user message is still an anchor."""
    big = "line of tool output\n" * 400
    quoting = [{"role": "system", "content": "perm"}, u("root task"), a("", "c1", "read_file"), tool("c1", big + quoted + "\n" + big),
               a("", "c2", "write_file", json.dumps({"content": quoted})), tool("c2", "Wrote x"), u("now what")]
    out, _, rep = cf.fit(copy.deepcopy(quoting), None, window=1500, reserve=200, safety=1.0, pinned_task="root task")
    assert not rep.over_budget and sum(len(m.get("content") or "") for m in out) < 3000
    anchored = [{"role": "system", "content": "perm"}, u("root task"), u(quoted + "\n" + big), u("now what")]
    out, _, rep = cf.fit(anchored, None, window=1500, reserve=200, safety=1.0, pinned_task="root task")
    assert any(quoted in (m.get("content") or "") for m in out)


def test_protected_overflow_drops_oldest_of_the_active_span_and_leaves_no_orphan_results():
    """Observed live: 259 messages, the last user message near the top, guaranteed 400 retried forever.
    The span can shrink from its old end; system, request and the newest tail stay, pairs stay whole."""
    msgs = [{"role": "system", "content": "sys"}, u("THE TASK: build the thing")] + pairs(80, 600)
    out, _, rep = cf.fit(msgs, None, window=8000, reserve=1000, safety=1.8)
    assert not rep.over_budget and rep.protected_dropped > 0
    assert out[0]["role"] == "system" and out[1]["content"] == "THE TASK: build the thing"
    assert out[-1]["tool_call_id"] == "c79"
    ids = {c["id"] for m in out for c in m.get("tool_calls") or []}
    assert all(m["tool_call_id"] in ids for m in out if m["role"] == "tool")


def test_an_irreducible_core_is_sent_but_reported_over_budget():
    """Nothing droppable remains: surfaced as over_budget, content intact (never declared fit)."""
    out, _, rep = cf.fit([{"role": "system", "content": "s" * 40000}, u("task")], None,
                         window=8000, reserve=1000, safety=1.8)
    assert rep.over_budget and out[1]["content"] == "task"
    anchor = u("⟦ctx:rollup⟧ the rolling summary " + "s" * 400)
    kept, _, rep = cf.fit([{"role": "system", "content": "sys"}, u("request"), anchor]
                          + [a("a" * 900) for _ in range(8)], None, window=300, reserve=100)
    assert anchor in kept   # sacrificing an anchor to a fit that is still unreachable buys nothing


def _cat(result, extra=()):
    return [{"role": "system", "content": "sys"}, u("count the ERROR lines in app.log"), *extra,
            a("", "c1", "exec_command", '{"cmd":"cat app.log"}'),
            tool("c1", result, **{bodykeys.READ_OBSERVATION: (len(result), "d" * 64)})]


LOG = "\n".join(f"12:00:{i % 60:02d} worker-{i % 7} batch {i}" + (" ERROR" if i % 50 == 0 else "") for i in range(3000))


def test_a_tool_result_no_lever_can_shrink_is_withheld_with_a_sized_note_not_left_to_end_the_session():
    """wave 10 OVFL (real Codex, rc 0 after one call): the active tool result alone exceeded the window, plain text is never
    clipped by content_reduce, and the floor reported over_budget; the final answer to that was a stop message. Now the result is
    swapped for a not-delivered note carrying what was measured and a next step sized from it, the call stays, the read-claim
    hint is gone (nothing in it was seen), and fitting the note's own output again changes nothing (stateless: the harness
    resends the oversized result on every later turn)."""
    msgs = _cat(LOG)
    out, _, rep = cf.fit(msgs, None, window=6000, reserve=1000, safety=1.5)
    note = out[-1]["content"]
    assert rep.results_withheld == 1 and not rep.over_budget and cf.est_total(out, None) * 1.5 <= 5000
    assert note.startswith("⟦ctx:result-not-delivered⟧") and f"{len(LOG):,} bytes in 3,000 line(s)" in note
    assert "6,000-token context window" in note and "Do not repeat the same call" in note
    piece = int(note.split("about ")[1].split(" lines")[0].replace(",", ""))
    cost = cf.est_tokens("\n".join(LOG.split("\n")[:piece])) * 1.5                # one suggested piece, at the density in force
    assert 0.8 * 1250 <= cost <= 1250                                                # about a quarter of the 5,000 tokens of room
    # the exact one-step reruns, built from the call that produced THIS result (a shell command) and its measured size
    assert f"`( cat app.log ) 2>&1 | tail -n {piece}`" in note and f"`( cat app.log ) 2>&1 | head -n {piece}`" in note and "| grep -n WORD" in note and "cria" not in note.lower()
    assert out[-2] == msgs[-2] and out[-1]["tool_call_id"] == "c1" and bodykeys.READ_OBSERVATION not in out[-1]
    assert cf.fit(out, None, window=6000, reserve=1000, safety=1.5)[0] == out
    assert msgs[-1]["content"] == LOG                                            # the caller's list is untouched


def test_withholding_is_the_last_resort_and_touches_only_what_it_must():
    """A fitting request is byte-identical; the largest result goes first and alone when that is enough; a result the producer
    named protected, a user message and a lone very long line are each handled by their own rule, never by this one."""
    out, _, rep = cf.fit(_cat(LOG[:2000]), None, window=49152, reserve=4096)
    assert out == _cat(LOG[:2000]) and not rep.applied and rep.results_withheld == 0
    small = ["x" * 700]
    two = _cat(LOG, extra=[a("", "c0", "exec_command", "{}"), tool("c0", small[0])])
    out, _, rep = cf.fit(two, None, window=6000, reserve=1000, safety=1.5)
    assert rep.results_withheld == 1 and out[-1]["content"].startswith("⟦ctx:result-not-delivered⟧") and out[3]["content"] == small[0]
    out, _, rep = cf.fit(_cat(LOG), None, window=6000, reserve=1000, safety=1.5, protected_call_ids=("c1",))
    assert rep.results_withheld == 0 and rep.over_budget and out[-1]["content"] == LOG
    user = [{"role": "system", "content": "sys"}, u("summarise:\n" + LOG)]
    out, _, rep = cf.fit(user, None, window=6000, reserve=1000, safety=1.5)
    assert rep.results_withheld == 0 and rep.over_budget and out[-1]["content"] == user[-1]["content"]
    blob = "A" * 30000
    note = cf.fit(_cat(blob), None, window=6000, reserve=1000, safety=1.5)[0][-1]["content"]
    assert "30,000 bytes in 1 line(s)" in note and "Line 1, the longest, is 30,000 bytes" in note and "head -c 4000" in note


def test_the_note_names_the_exact_narrower_call_for_the_kind_of_result_it_replaces():
    """wave 10 OVFL follow-up: a long test run's tail matters, and a note that only said "read it in pieces" cost one rerun
    of guesswork. From typed facts alone (the call that produced the result, the tool's declared fields, the measured size) a
    shell result gets its own command piped through tail/head/grep, a read tool that declares a line window gets the exact
    arguments for the first and the LAST piece, and a result with no usable call keeps the generic route; a command too long
    to quote is not quoted."""
    menu_ = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}}}},
        {"type": "function", "function": {"name": "view", "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}}}}]
    def note(call_name, args, tools=menu_, window=6000):
        msgs = [{"role": "system", "content": "sys"}, u("task"), a("", "c1", call_name, json.dumps(args)), tool("c1", LOG)]
        return cf.fit(msgs, tools, window=window, reserve=1000, safety=1.5)[0][-1]["content"]
    piece = int(note("exec_command", {"cmd": "pytest -q"}).split("about ")[1].split(" lines")[0])
    assert f"`( pytest -q ) 2>&1 | tail -n {piece}`" in note("exec_command", {"cmd": "pytest -q"})
    assert f"`( cd /ws && make test ) 2>&1 | tail -n {piece}`" in note("shell", {"command": ["bash", "-lc", "cd /ws && make test"]})
    read = note("read_file", {"path": "src/app.py"})
    assert f'read_file {{"path": "src/app.py", "offset": 1, "limit": {piece}}} returns the first {piece} lines' in read
    assert f'{{"path": "src/app.py", "offset": {3000 - piece + 1}, "limit": {piece}}}' in read and "the last" in read
    view = note("view", {"file_path": "src/app.py"})
    assert f'"start_line": 1, "end_line": {piece}}}' in view and f'"start_line": {3000 - piece + 1}, "end_line": 3000}}' in view
    for generic in (note("exec_command", {"cmd": "x" * 700}), note("web_fetch", {"url": "http://x"}), note("read_file", {"path": "p"}, tools=[])):
        assert f"about {piece} lines at a time: a line range on a read tool" in generic and "( " not in generic and '"offset"' not in generic


def test_a_last_result_too_big_for_any_window_keeps_the_history_that_cannot_help():
    """wave 10 OVFL follow-up (lever order): a session of 30 earlier call/result pairs whose NEWEST result alone cannot fit
    used to lose the older turns first (lever 5), a futile, labelled loss. The result is withheld first, and when that is
    enough every older turn is still there; a result that merely competes with history is still left to the drop levers."""
    history = pairs(30, 300)
    out, _, rep = cf.fit(_cat(LOG, extra=history), None, window=6000, reserve=1000, safety=1.5)
    assert rep.results_withheld == 1 and rep.turns_dropped == 0 and rep.protected_dropped == 0 and not rep.over_budget
    assert out[2:2 + len(history)] == history and out[-1]["content"].startswith("⟦ctx:result-not-delivered⟧")
    modest = pairs(30, 300) + [a("", "m1", "exec_command", "{}"), tool("m1", "m" * 3000)]
    out, _, rep = cf.fit([{"role": "system", "content": "sys"}, u("task"), *modest], None, window=6000, reserve=1000, safety=1.5)
    assert rep.results_withheld == 0 and rep.protected_dropped > 0 and out[-1]["content"] == "m" * 3000


def test_a_frame_the_eight_newest_messages_overflow_keeps_only_the_newest_call_and_its_result():
    """wave 10 OVFL follow-up (frame): when even the last eight messages do not fit beside the fixed frame and no result is
    big enough to withhold, lever 7 keeps the newest call and its result (labelled by the compacted note) instead of ending
    the turn; system text, the task and the newest pair survive. A protected read keeps its own overflow route."""
    msgs = [{"role": "system", "content": "sys " + "s" * 2000}, u("task " + "t" * 2000),
            *[a("w" * 1600) for _ in range(6)], a("", "c0", "read_file", '{"path": "p"}'), tool("c0", "r" * 200)]
    out, _, rep = cf.fit(msgs, None, window=3600, reserve=600, safety=1.5)
    assert not rep.over_budget and rep.protected_dropped > 0 and rep.results_withheld == 0
    assert out[0] == msgs[0] and out[1] == msgs[1] and out[-2:] == msgs[-2:] and notes(out)
    assert sum(1 for m in out if m["role"] == "assistant") == 1                 # the six long assistant turns went
    out, _, rep = cf.fit(msgs, None, window=3600, reserve=600, safety=1.5, protected_call_ids=("c0",))
    assert rep.over_budget and rep.protected_dropped == 0 and out[-2:] == msgs[-2:]    # a protected read: lever 7 does not run


def test_a_note_this_fit_wrote_is_never_withheld_again_and_the_event_counts_what_the_body_carries():
    """audit AUD3 (lever 6 after 3b): a request still over after lever 3b's note re-ran the withholding over the note itself, and the
    note-about-a-note said "626 bytes" for a 20,000-byte result: the one number the coder needs to size its next read was gone
    and the event counted two withholdings for one result. Cross-store: the label's byte count is the result's, the event's
    count is the notes in the body, and a result that merely QUOTES the marker is still withheld (provenance is identity, not text)."""
    def one(size, text=None):
        msgs = [{"role": "system", "content": "s" * 3344}, u("task"), a("", "c1", "exec_command", '{"cmd": "cat app.log"}'), tool("c1", text or "A" * size)]
        out, _, rep = cf.fit(msgs, None, window=1000, reserve=100, safety=1.0)
        return out[-1]["content"], rep
    note, rep = one(20000)
    assert rep.results_withheld == 1 and "it is 20,000 bytes in 1 line(s)" in note
    quoted = "⟦ctx:result-not-delivered⟧ already\n" + "B" * 20000
    note, rep = one(0, quoted)
    assert rep.results_withheld == 1 and f"it is {len(quoted.encode()):,} bytes in 2 line(s)" in note


def test_the_piece_a_withheld_result_suggests_is_sized_beside_the_frame_so_it_is_delivered():
    """audit AUD3: the suggested piece was a quarter of the window's room whatever the frame (system text, the request) already took;
    with a frame past three quarters of the room the piece the note told the coder to read overran the room (the reply reserve was then squeezed from 1,000 to ~500
    tokens to admit it). The invariant: the piece the note names, delivered as the result of the same call, is not withheld and leaves the reply room whole."""
    window, reserve, safety = 6000, 1000, 1.5
    for frame_chars in (400, 11333):                           # a small frame, and one that takes 85% of the room
        msgs = [{"role": "system", "content": "s" * frame_chars}, u("task"), a("", "c1", "exec_command", '{"cmd": "cat app.log"}'), tool("c1", LOG)]
        out, _, rep = cf.fit(msgs, None, window=window, reserve=reserve, safety=safety)
        piece = int(out[-1]["content"].split("about ")[1].split(" lines")[0].replace(",", ""))
        assert rep.results_withheld == 1 and piece >= 1
        again, _, rep2 = cf.fit(msgs[:3] + [tool("c1", "\n".join(LOG.split("\n")[-piece:]))], None, window=window, reserve=reserve, safety=safety)
        assert rep2.results_withheld == 0 and not rep2.over_budget and rep2.reserve == reserve and again[-1]["content"].endswith("batch 2999"), frame_chars


@pytest.mark.parametrize("room_left,withheld", [(300, True), (578, True), (1500, True), (2100, False), (2600, False)])
def test_a_result_that_would_leave_the_reply_a_few_hundred_tokens_is_withheld_not_delivered(room_left, withheld):
    """wave 12 CLAMP: real 16K/24K/32K servers delivered a read that left 82 / 363 / 578 tokens of the window for the reply (the floor's
    last resort squeezed the reserve), and 34% of 16,120 captured coder replies to a tool result are longer than 363 tokens. Below the
    floor's default reply room (2,048 at this window) the result is withheld with its labelled re-read; at or above it the squeeze is
    accepted as before. Never by dropping the older turns or the live tail, and a protected read keeps its own path."""
    window, reserve, safety = 20000, 8000, 1.5
    history = [a("", "c0", "exec_command", '{"cmd":"ls"}'), tool("c0", "a.py\nb.py")]
    def request(lines):
        return _cat("\n".join(LOG.split("\n")[:lines]), extra=history)
    lines = max(n for n in range(1, 3000) if cf.est_total(request(n), None) * safety <= window - room_left)
    msgs = request(lines)
    out, _, rep = cf.fit(msgs, None, window=window, reserve=reserve, safety=safety)
    assert rep.turns_dropped == 0 and rep.protected_dropped == 0 and out[3]["content"] == "a.py\nb.py" and not rep.over_budget
    if withheld:
        assert rep.results_withheld == 1 and out[-1]["content"].startswith("⟦ctx:result-not-delivered⟧") and rep.reserve >= 2048
    else:
        assert rep.results_withheld == 0 and out == msgs and rep.reserve == window - math.ceil(cf.est_total(msgs, None) * safety)
    kept, _, rep = cf.fit(msgs, None, window=window, reserve=reserve, safety=safety, protected_call_ids=("c1",))
    assert rep.results_withheld == 0 and kept[-1]["content"] == msgs[-1]["content"]


def test_lever_seven_keeps_every_result_of_the_newest_parallel_call_with_its_call():
    """audit AUD3 (lever 7): the live tail was the newest two MESSAGES, so for one assistant turn that issued three parallel calls
    the tail was two of the three results; the call itself was droppable, and the orphan strip then deleted the results the tail was
    meant to keep (window 3,600: every result the coder was answering gone, though 600 bytes of them fit easily). The tail is closed
    over call/result pairs in both directions, so the newest call and ALL its results survive and the request is paired."""
    def call(i):
        return {"id": i, "type": "function", "function": {"name": "read_file", "arguments": '{"path": "p"}'}}
    live = [{"role": "assistant", "content": "", "tool_calls": [call("c0"), call("c1"), call("c2")]},
            *[tool(f"c{n}", "rqz"[n] * 200) for n in range(3)]]
    msgs = [{"role": "system", "content": "sys " + "s" * 2000}, u("task " + "t" * 2000), *[a("w" * 1600) for _ in range(6)], *live]
    for window in (3600, 2600):
        out, _, rep = cf.fit(msgs, None, window=window, reserve=600, safety=1.5)
        assert not rep.over_budget and rep.protected_dropped > 0 and notes(out), window
        assert out[-4:] == live, window                                             # the call and all three results, in order
        assert out[0] == msgs[0] and out[1] == msgs[1] and rep.orphans_removed == 0


@pytest.mark.parametrize("count,desc,window,fits", [(60, 600, 20000, True), (120, 900, 49152, True), (100, 200, 512, False), (3, "Word " * 30 + "end. " + "tail " * 600, 4000, True)],
                         ids=["60-tools", "120-tools-big-system", "cannot-fit", "sentence-descriptions"])
def test_a_fat_tool_menu_is_compressed_never_deleted(count, desc, window, fits):
    """qwopus-9: 34K tokens of connector tools overflowed because the schema was irreducible. Descriptions
    shrink; every tool keeps its name/params; an impossible menu is reported, not silently crippled."""
    tools = menu(count, desc)
    original = copy.deepcopy(tools)
    msgs = [{"role": "system", "content": "S" * 40000 if count == 120 else "s"}, u("do a coding task")]
    _, new, rep = cf.fit(msgs, tools, window=window, reserve=min(4096, window // 2))
    assert [t["function"]["name"] for t in new] == [t["function"]["name"] for t in tools]
    assert "arg" in new[0]["function"]["parameters"]["properties"] and rep.tools_dropped == 0
    assert rep.tool_tokens < rep.tool_tokens_before and rep.over_budget is (not fits)
    assert tools == original and rep.tools_compressed == count                    # the caller's menu is untouched; every description was shortened ...
    assert all(t["function"]["description"].endswith(" […more]") and t["function"]["parameters"]["properties"]["arg"]["description"].endswith(" […more]")
               for t in new)                                                       # ... with a visible mark, on the tool and on its parameters
    if isinstance(desc, str):                                                      # a description with a sentence is cut where the writer ended it, not mid-run
        assert all(t["function"]["description"].endswith(" end. […more]") for t in new)


def test_a_reserve_as_large_as_the_window_is_clamped_not_zeroing_the_prompt():
    """A harness sending max_tokens >= window made reserve >= window: everything trimmed, still over budget.
    The small conversation, the task and the whole menu must survive with real room left for the prompt."""
    task = "Fix the repository and verify the result."
    msgs = [{"role": "system", "content": "Instructions. " * 1900}, u("Current directory: /w")]
    msgs += [a(f"earlier turn {i} " + "w" * 1500) for i in range(3)] + [u(task)]
    tools = menu(10, 10)
    out, kept_tools, rep = cf.fit(msgs, tools, window=16384, reserve=16384, safety=1.64, pinned_task=task)
    assert out == msgs and len(kept_tools) == 10 and not rep.over_budget
    assert 0 < rep.reserve < 16384 and rep.as_event()["reserve_requested"] == 16384


def test_structured_output_is_reduced_oldest_first_before_any_turn_is_dropped_and_the_freshest_is_spared():
    """Shrinking one output is cheaper than deleting an exchange, but the freshest result is the file the
    current step edits: it stays byte-intact while the stale larger-than-needed one shrinks."""
    def rows(msg, n):
        return '{"rows": [' + ",".join('{"m": "%s"}' % msg for _ in range(n)) + "]}"
    stale, fresh = rows("the item is in the list and on the page", 120), rows("this describes the current file", 200)
    msgs = [u("task"), a("", "c1", "web_fetch"), tool("c1", stale), a("", "c2", "read_file"), tool("c2", fresh), u("go")]
    out, _, rep = cf.fit(msgs, None, window=3000, reserve=300, safety=1.0)
    assert rep.outputs_reduced == 1 and rep.turns_dropped == 0
    results = [m["content"] for m in out if m["role"] == "tool"]
    assert results[-1] == fresh and est_tokens(results[0]) < est_tokens(stale)


def test_the_floor_reduces_the_harness_persona_before_conversation_evidence_and_labels_it():
    """phi4 / Java A5: Codex's 19 KB persona rode whole in the protected system message, so the floor dropped
    26 turns instead (file reads became stubs; the coder never saw the file again). The author-supplied span is
    reduced first, labelled; the harness's configured constraints and the evidence stay."""
    persona, configured = "PERSONA " * 1500, "sandbox_mode is workspace-write"
    head = "coder frame\n\n"
    system = {"role": "system", "content": head + persona + "\n\n" + configured,
              bodykeys.CALLER_SPAN: {"start": len(head), "text": persona}}
    msgs = [system, u("the task")] + pairs(6, 400, "EVIDENCE") + [u("go")]
    out, _, rep = cf.fit(msgs, None, window=2500, reserve=300, safety=1.0, pinned_task="the task")
    assert rep.caller_reduced == 1 and rep.turns_dropped == 0 and not rep.over_budget
    assert persona not in out[0]["content"] and cf._REDUCED_MARK in out[0]["content"]
    assert configured in out[0]["content"] and out[0]["content"].startswith("coder frame")
    assert sum("EVIDENCE" in str(m.get("content")) for m in out) == 6


def test_a_standin_for_a_removed_file_text_block_is_not_shed_with_the_oldest_turns():
    """phi4 / Java A10: the floor swapped the restored-file-text block for a labelled stand-in, then dropped
    the stand-in as the 'oldest droppable middle message', so the coder was never told it held no copy."""
    restore = {"role": "user", "content": "⟦ctx:current⟧ current text of src/Importer.java:\n" + "code line\n" * 3000,
               bodykeys.RESTORED_FILES: {"offered": {"src/Importer.java": "sha"}, "named": ["src/Importer.java"]}}
    history = [a(f"plan {i}: " + "we should rewrite the importer. " * 120) if i % 2 == 0 else u(f"⟦ctx:steer⟧ not done {i} " + "fix. " * 120)
               for i in range(28)]
    msgs = [{"role": "system", "content": "sys"}, u("the task")] + history + [restore, u("files listing"), u("⟦ctx:facts⟧ x")]
    out, _, rep = cf.fit(msgs, None, window=6000, reserve=1500, safety=1.05, pinned_task="the task")
    assert rep.restored_reduced == 1 and rep.turns_dropped > 0
    standins = [m for m in out if str(m.get("content") or "").startswith("⟦ctx:current⟧")]
    assert len(standins) == 1 and "src/Importer.java" in standins[0]["content"] and "code line\n" * 20 not in standins[0]["content"]


def test_tool_integrity_converts_an_orphan_result_to_user_text_and_prunes_a_dangling_call():
    """Live 400: self-compaction folded the assistant call but kept the anchored result, so a strict template
    rejected an orphan `tool` every turn. Its content survives as user text; a call without result is pruned;
    a valid pair is untouched."""
    orphan = [u("⟦ctx:rollup⟧ earlier work"), tool("gone", "⟦ctx:checks⟧ foo undefined"), u("next")]
    out, n = cf.ensure_tool_integrity(orphan)
    assert n == 1 and out[1]["role"] == "user" and "⟦ctx:checks⟧ foo undefined" in out[1]["content"]
    dangling = [a("here", "c2"), u("next")]
    out, n = cf.ensure_tool_integrity(dangling)
    assert n == 1 and "tool_calls" not in out[0] and out[0]["content"] == "here"
    valid = [a("", "c1"), tool("c1", "ok")]
    assert cf.ensure_tool_integrity(valid) == (valid, 0)


@pytest.mark.parametrize("body,expected", [
    ({"max_tokens": 2048}, 2048), ({}, cf.DEFAULT_GEN_RESERVE), ({"max_tokens": 0}, cf.DEFAULT_GEN_RESERVE),
    ({bodykeys.OUTPUT_RESERVE: 8192, "max_tokens": 256}, 8192), ({bodykeys.OUTPUT_RESERVE: 8192, "max_tokens": None}, 8192),
    ({bodykeys.OUTPUT_RESERVE: 0, "max_tokens": 2048}, 2048)])
def test_reserve_comes_from_the_roles_output_reserve_then_max_tokens_then_the_default(body, expected):
    """The role's reserve is independent of the (usually unset) hard cap; a bad value falls through."""
    assert cf.reserve_for(body) == expected


def test_a_denser_measurement_trims_harder():
    msgs = [u("task"), a("A" * 16000), u("more"), a("B" * 16000), u("current")]
    _, _, lo = cf.fit(copy.deepcopy(msgs), None, window=8000, reserve=500, safety=1.3)
    _, _, hi = cf.fit(copy.deepcopy(msgs), None, window=8000, reserve=500, safety=2.6)
    assert hi.turns_dropped > lo.turns_dropped and hi.msg_tokens_after < lo.msg_tokens_after


def test_a_compaction_digest_never_rewrites_prose():
    """zaya1 / ada-handles 0/4: the digest word-stripped a dropped turn - the user's task lost its function
    words and cria's own 'could BE READ FROM it' became 'could read it', a claim INVERTED. Prose is kept whole
    or disclosed, never reworded; only structured content is reduced structurally."""
    negation = "no endpoints or field names could be read from it"
    task = "I would like you to write a Python script that accepts an Ada Handle as input and resolves it. " * 3
    assert digest_reduce(negation, None, 10) == negation and digest_reduce(task, None, 10) == task
    assert content_reduce(task * 100, None, 20) == task * 100
    big = '{"a": "' + "x" * 4000 + '"}'
    assert len(digest_reduce(big, "application/json", 50)) < len(big)


def test_a_responses_instructions_persona_is_reduced_before_conversation_evidence_on_a_proxied_turn():
    """Relay path (no coder frame): the Responses translation itself anchors the span, so the floor spares the
    conversation and the developer constraint exactly as it does behind the coder frame."""
    from cria import responses
    persona, configured = "PERSONA " * 1500, "sandbox_mode is workspace-write"
    items = [{"type": "message", "role": "developer", "content": [{"type": "input_text", "text": configured}]},
             {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "the task"}]}]
    for i in range(6):
        items += [{"type": "function_call", "call_id": f"c{i}", "name": "read_file", "arguments": "{}"},
                  {"type": "function_call_output", "call_id": f"c{i}", "output": "EVIDENCE " + "x " * 400}]
    items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "go"}]})
    msgs = responses.to_chat_body({"model": "m", "instructions": persona, "input": items})["messages"]
    out, _, rep = cf.fit(msgs, None, window=2500, reserve=300, safety=1.0, pinned_task="the task")
    assert rep.caller_reduced == 1 and rep.turns_dropped == 0 and not rep.over_budget
    assert persona not in out[0]["content"] and cf._REDUCED_MARK in out[0]["content"]
    assert out[0]["content"].endswith(configured)
    assert sum("EVIDENCE" in str(m.get("content")) for m in out) == 6
