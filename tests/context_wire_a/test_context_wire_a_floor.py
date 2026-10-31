"""The context floor (contextfloor.fit): the one place a request is made to fit the measured window.

Promise: a request over budget is reduced cheapest-first, oldest WHOLE units go with a label naming what
went, protected content (system, task, active turn, anchors, tool menu) survives, nothing is silently
lost and an unfittable request is reported as over budget, never declared fit.
"""
import copy
import json

import pytest

from cria import bodykeys, contextfloor as cf, prompts
from cria.content_reduce import content_reduce, digest_reduce, est_tokens
from cria.loop import BRIEFING_OPEN
from cria.probegate import SECTION_PREFIX


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
    return [{"type": "function", "function": {
        "name": f"op_{i}", "description": "D" * desc,
        "parameters": {"type": "object", "properties": {"arg": {"type": "string", "description": "P" * desc}},
                       "required": ["arg"]}}} for i in range(n)]


def notes(out):
    return [m["content"] for m in out if cf._COMPACTED_MARK in str(m.get("content") or "")]


def test_a_fitting_request_is_returned_unchanged_and_inputs_are_never_mutated():
    """No pressure -> identity; under pressure the caller's lists/dicts are still untouched (pure)."""
    small = [{"role": "system", "content": "sys"}, u("hi")]
    out, _, rep = cf.fit(small, None, window=49152, reserve=4096)
    assert out == small and not rep.applied and not rep.over_budget
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
             a("", "g", "shell"), tool("g", gate)] + pairs(12, 900, "step") + [u(steer), u(facts)])
    out, _, rep = cf.fit(msgs, None, window=2200, reserve=300, pinned_task="Fix the importer")
    texts = [m.get("content") for m in out]
    assert rep.turns_dropped >= 10
    assert briefing in texts and gate in texts and "Fix the importer" in texts
    assert texts[-2:] == [steer, facts]
    assert not any("automated checks pass" in t for t in notes(out))


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


@pytest.mark.parametrize("count,desc,window,fits", [(60, 600, 20000, True), (120, 900, 49152, True), (100, 200, 512, False)])
def test_a_fat_tool_menu_is_compressed_never_deleted(count, desc, window, fits):
    """qwopus-9: 34K tokens of connector tools overflowed because the schema was irreducible. Descriptions
    shrink; every tool keeps its name/params; an impossible menu is reported, not silently crippled."""
    tools = menu(count, desc)
    msgs = [{"role": "system", "content": "S" * 40000 if count == 120 else "s"}, u("do a coding task")]
    _, new, rep = cf.fit(msgs, tools, window=window, reserve=min(4096, window // 2))
    assert [t["function"]["name"] for t in new] == [t["function"]["name"] for t in tools]
    assert "arg" in new[0]["function"]["parameters"]["properties"] and rep.tools_dropped == 0
    assert rep.tool_tokens < rep.tool_tokens_before and rep.over_budget is (not fits)


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


def test_the_task_survives_steers_injected_after_it():
    """53 of 1,475 coder prompts shipped with no task: cria's own steer/notes made the task the OLDEST
    droppable turn. It is protected structurally (no marker needed), with unproven earlier user context."""
    banner = "Working environment - cwd: /tmp/ws"
    task = "Fix the rounding bug causing totals to be one cent low."
    msgs = [{"role": "system", "content": "sys"}, u(banner), u(task)]
    for i in range(40):
        msgs += [a("filler " * 200), u(f"⟦ctx:steer⟧ note {i}")]
    out, _, rep = cf.fit(msgs, None, window=1500, reserve=300, pinned_task=task)
    assert rep.turns_dropped > 0
    texts = [m.get("content") for m in out]
    assert task in texts and banner in texts


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
