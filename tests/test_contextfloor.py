"""The harness-agnostic context floor: cria guarantees the request fits the window,
whatever the connected harness sends."""
import json
import unittest

from cria import contextfloor
from cria.content_reduce import est_tokens


def _u(text):
    return {"role": "user", "content": text}


def _a(text="", tool_calls=None):
    m = {"role": "assistant", "content": text}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def _tool(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _fat_tools(n, desc_len):
    return [{"type": "function", "function": {
        "name": f"connector_tool_{i}", "description": "D" * desc_len,
        "parameters": {"type": "object", "properties": {
            "arg": {"type": "string", "description": "P" * desc_len}}, "required": ["arg"]}}}
        for i in range(n)]


class TestAnchorProtection(unittest.TestCase):
    def test_markers_stay_in_sync_with_their_sources(self):
        from cria.loop import BRIEFING_OPEN, CONTINUATION_MARKER
        from cria.probegate import SECTION_PREFIX
        from cria.selfcompact import SUMMARY_MARKER, TASK_MARKER, FACTS_MARKER
        self.assertIn(BRIEFING_OPEN, contextfloor._PROTECT_MARKERS)
        self.assertIn(SECTION_PREFIX, contextfloor._PROTECT_MARKERS)
        # selfcompact's OWN preservation anchors must be floor-protected too — else the floor drops the
        # pinned task + rolling summary selfcompact ran to preserve (the confirmed north-star loss).
        self.assertIn(SUMMARY_MARKER, contextfloor._PROTECT_MARKERS)
        self.assertIn(TASK_MARKER, contextfloor._PROTECT_MARKERS)
        # the durable fetch-ledger anchor the loop re-injects must survive the floor too, or the coder
        # loses the real endpoints again exactly when the window is tightest.
        self.assertIn(FACTS_MARKER, contextfloor._PROTECT_MARKERS)
        self.assertIn(CONTINUATION_MARKER, contextfloor._PROTECT_MARKERS)

    def test_briefing_survives_drop_oldest(self):
        # a huge history over budget: the ⟦ctx:briefing⟧ anchor must NOT be dropped, so a follow-up
        # can still re-read it (else replanning from scratch).
        from cria.loop import BRIEFING_OPEN
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": f"{BRIEFING_OPEN} prior work: built the resolver ⟦/ctx:briefing⟧"}]
        msgs += [_a("x" * 4000, [{"id": f"c{i}", "type": "function", "function": {"name": "s", "arguments": "{}"}}]) for i in range(40)]
        msgs += [_u("the current request")]
        kept, _ = contextfloor._drop_oldest(msgs, msg_budget=500)
        self.assertTrue(any(BRIEFING_OPEN in str(m.get("content") or "") for m in kept))  # anchor kept
        self.assertLess(len(kept), len(msgs))                                              # but it DID drop others

    def test_gate_result_not_reduced(self):
        from cria.probegate import SECTION_PREFIX
        gate = f"{SECTION_PREFIX}probe-0___\n" + "mcp_client.py:14: SyntaxError bad\n" * 200  # bulky ground truth
        msgs = [{"role": "system", "content": "s"}, _a("", [{"id": "g", "type": "function", "function": {"name": "s", "arguments": "{}"}}]),
                _tool("g", gate), _u("go")]
        out, _ = contextfloor._reduce_tool_outputs(msgs, msg_budget=50)  # force pressure
        kept_gate = next(m for m in out if m.get("role") == "tool")
        self.assertEqual(kept_gate["content"], gate)   # the ground truth is preserved verbatim


class TestFits(unittest.TestCase):
    def test_noop_when_it_already_fits(self):
        msgs = [{"role": "system", "content": "sys"}, _u("hi")]
        out, tools, rep = contextfloor.fit(msgs, None, window=49152, reserve=4096)
        self.assertEqual(out, msgs)
        self.assertFalse(rep.applied)
        self.assertEqual(rep.turns_dropped, 0)
        self.assertFalse(rep.over_budget)

    def test_drops_oldest_and_preserves_system_and_active_turn(self):
        msgs = [
            {"role": "system", "content": "SYSTEM PRELUDE"},
            _u("old task"),
            _a("X" * 12000),  # ~3000 est — the bulk
            _u("current task"),  # last user → the active turn, protected
        ]
        out, tools, rep = contextfloor.fit(msgs, None, window=4000, reserve=500)
        self.assertTrue(rep.applied)
        self.assertGreaterEqual(rep.turns_dropped, 1)
        roles = [m["role"] for m in out]
        self.assertIn("system", roles)  # system preserved
        self.assertEqual(out[-1]["content"], "current task")  # active turn preserved
        self.assertNotIn("X" * 12000, [m.get("content") for m in out])  # bulk dropped
        target = int((4000 - 500) / contextfloor.SAFETY_FACTOR)
        self.assertLessEqual(rep.msg_tokens_after, target)

    def test_compresses_fat_tool_schema_keeping_tools_callable(self):
        # 60 verbose connector tools (~big schema) must be compressed, not allowed to eat
        # the window — but every tool stays present and callable.
        tools = _fat_tools(60, 600)
        before = est_tokens(json.dumps(tools))
        msgs = [{"role": "system", "content": "s"}, _u("do a coding task")]
        out, new_tools, rep = contextfloor.fit(msgs, tools, window=20000, reserve=2000)
        self.assertGreater(rep.tools_compressed, 0)
        self.assertLess(rep.tool_tokens, rep.tool_tokens_before)
        self.assertEqual(rep.tool_tokens_before, before)
        # all 60 tools still there, names intact, params intact
        self.assertEqual(len(new_tools), 60)
        names = [t["function"]["name"] for t in new_tools]
        self.assertEqual(names, [f"connector_tool_{i}" for i in range(60)])
        self.assertIn("arg", new_tools[0]["function"]["parameters"]["properties"])
        # and the whole thing now fits the window
        self.assertFalse(rep.over_budget)

    def test_fat_tools_plus_big_protected_turn_still_fits(self):
        # The qwopus-9 failure: 34K-ish tools + a big protected system/active turn overflowed
        # because the schema was irreducible. With tool-schema bounding it must fit.
        tools = _fat_tools(120, 900)
        msgs = [
            {"role": "system", "content": "S" * 40000},  # ~10K est protected system prompt
            _u("resolve an Ada handle and write tests"),  # active turn, protected
        ]
        out, new_tools, rep = contextfloor.fit(msgs, tools, window=49152, reserve=4096)
        self.assertGreater(rep.tools_compressed, 0)
        final_est = (rep.msg_tokens_after + rep.tool_tokens) * contextfloor.SAFETY_FACTOR
        self.assertLessEqual(final_est, 49152 - 4096)
        self.assertFalse(rep.over_budget)
        self.assertEqual(len(new_tools), 120)

    def test_reduces_oversized_tool_output_before_dropping_turns(self):
        big = ("This is a long sentence of prose that repeats. " * 400)
        msgs = [
            _u("task"),
            _a("", [{"id": "c1", "function": {"name": "web_fetch", "arguments": "{}"}}]),
            _tool("c1", big),
        ]
        before = est_tokens(big)
        out, tools, rep = contextfloor.fit(msgs, None, window=3000, reserve=500)
        self.assertEqual(rep.outputs_reduced, 1)
        self.assertEqual(rep.turns_dropped, 0)
        reduced = [m for m in out if m.get("role") == "tool"][0]["content"]
        self.assertLess(est_tokens(reduced), before)

    def test_reduction_spares_the_freshest_tool_output(self):
        # Two reducible tool outputs; the budget only needs ONE reduced to fit. The freshest one
        # (highest index) is the file the current step edits — it must be spared, so the STALE one
        # is reduced. Pre-fix reduction ran largest-first and (fresh being larger) gutted it.
        dense = "the item is in the list and it is on the page with the note for the row of the set " * 40
        fresh = "This sentence describes the current file contents that the model edits. " * 60
        self.assertGreater(est_tokens(fresh), est_tokens(dense))  # fresh is the LARGER of the two
        msgs = [
            _a("", [{"id": "c1", "function": {"name": "web_fetch", "arguments": "{}"}}]),
            _tool("c1", dense),   # OLDER tool output
            _a("", [{"id": "c2", "function": {"name": "read_file", "arguments": "{}"}}]),
            _tool("c2", fresh),   # FRESHEST — the file the current step depends on
        ]
        out, reduced = contextfloor._reduce_tool_outputs(msgs, 1700)
        self.assertGreaterEqual(reduced, 1)
        tool_msgs = [m for m in out if m.get("role") == "tool"]
        self.assertEqual(tool_msgs[-1]["content"], fresh)  # freshest byte-intact
        self.assertLess(est_tokens(tool_msgs[0]["content"]), est_tokens(dense))  # stale shrank

    def test_oversized_reserve_is_clamped_not_zeroing_prompt(self):
        # A harness sending max_tokens >= window drives reserve >= window (reserve_for falls back to
        # max_tokens) → prompt budget <= 0, everything trimmed to the floor and STILL over budget.
        # The clamp keeps real room for the prompt so a tiny conversation just fits.
        msgs = [{"role": "system", "content": "sys"}, _u("do the thing"), _a("ok")]
        out, _tools, rep = contextfloor.fit(msgs, None, window=8192, reserve=999999, safety=1.0)
        self.assertLessEqual(rep.reserve, 8192 - 1)   # reserve bounded below the window
        self.assertFalse(rep.over_budget)             # pre-fix: doomed/over-budget despite fitting
        self.assertEqual([m.get("content") for m in out], ["sys", "do the thing", "ok"])  # intact

    def test_orphan_tool_result_removed_when_assistant_dropped(self):
        msgs = [
            _a("Y" * 12000, [{"id": "c1", "function": {"name": "n", "arguments": "{}"}}]),
            _u("current"),
            _tool("c1", "r"),
        ]
        out, tools, rep = contextfloor.fit(msgs, None, window=3000, reserve=500)
        self.assertGreaterEqual(rep.turns_dropped, 1)
        self.assertEqual(rep.orphans_removed, 1)
        self.assertFalse(any(m.get("role") == "tool" for m in out))
        self.assertEqual(out[-1]["content"], "current")

    def test_marker_protected_result_protects_its_issuing_call(self):
        # M18: a gate RESULT carries the protect marker but its assistant CALL does not, and the pair is
        # OLD (a newer user turn follows). Without pair-protection the call is dropped and the "protected"
        # result then orphaned. Its issuing call must be protected too.
        from cria.contextfloor import _protected_mask
        msgs = [
            {"role": "assistant", "content": "x",
             "tool_calls": [{"id": "g1", "function": {"name": "shell", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "g1", "content": "___CRIA_GATE_probe-0___\nEXIT:0"},  # marker result
            {"role": "user", "content": "a newer turn"},   # makes the pair OLD (not the active turn)
            {"role": "assistant", "content": "done"},
        ]
        prot = _protected_mask(msgs)
        self.assertTrue(prot[1])   # the marker-protected result
        self.assertTrue(prot[0])   # M18: its issuing call is now protected too (pair kept intact)

    def test_strip_orphan_tools_prunes_a_dangling_call(self):
        # M18 (reverse): an assistant tool_call whose RESULT was dropped is a DANGLING call — strict
        # templates reject it just as they reject an orphan result. It must be pruned.
        from cria.contextfloor import _strip_orphan_tools
        msgs = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "function": {"name": "n", "arguments": "{}"}}]},  # result was dropped
            {"role": "user", "content": "hi"},
        ]
        out, removed = _strip_orphan_tools(msgs)
        self.assertEqual(removed, 1)
        self.assertFalse(any(m.get("tool_calls") for m in out))   # no dangling call survives

    def test_ensure_tool_integrity_converts_orphan_to_user_unconditionally(self):
        # LIVE 400: self-compaction folds an assistant tool_call into the ⟦ctx:rollup⟧ but KEEPS the
        # anchored gate result (a `tool` message) — so a request that FITS the window still ships an orphan
        # `tool` that a strict template rejects EVERY turn. The floor's orphan strip runs only inside the
        # over-budget reduction, so a fitting request never gets it. The unconditional pass CONVERTS the
        # orphan to `user` (ground-truth content preserved), never dropping it.
        from cria.contextfloor import ensure_tool_integrity
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "⟦ctx:rollup⟧ earlier work summarized (the assistant call was folded)"},
            {"role": "tool", "tool_call_id": "call_x", "content": "⟦ctx:checks⟧ the repo's checks: foo undefined"},
            {"role": "user", "content": "do the next step"},
        ]
        out, n = ensure_tool_integrity(msgs)
        self.assertEqual(n, 1)
        self.assertEqual(out[2]["role"], "user")                      # converted — no orphan tool on the wire
        self.assertIn("⟦ctx:checks⟧", out[2]["content"])              # the ground-truth content survives
        self.assertFalse(any(m.get("role") == "tool" for m in out))

    def test_ensure_tool_integrity_keeps_valid_pairs_and_prunes_dangling(self):
        from cria.contextfloor import ensure_tool_integrity
        valid = [
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "function": {"name": "r", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ]
        out, n = ensure_tool_integrity(valid)
        self.assertEqual(n, 0)                                        # a valid pair is untouched
        self.assertEqual(out[1]["role"], "tool")
        dangling = [
            {"role": "assistant", "content": "here",
             "tool_calls": [{"id": "c2", "function": {"name": "r", "arguments": "{}"}}]},
            {"role": "user", "content": "next"},                      # c2's result is absent
        ]
        out2, n2 = ensure_tool_integrity(dangling)
        self.assertEqual(n2, 1)
        self.assertNotIn("tool_calls", out2[0])                       # dangling call pruned, content kept
        self.assertEqual(out2[0]["content"], "here")

    def test_over_budget_when_protected_turn_alone_exceeds_window(self):
        # A single giant active turn that can't be dropped and can't be tool-compressed away.
        msgs = [_u("Z" * 40000)]  # ~10K est, protected, only message
        out, tools, rep = contextfloor.fit(msgs, None, window=4000, reserve=500)
        self.assertTrue(rep.over_budget)  # surfaced, not hidden
        self.assertEqual(out[-1]["content"], "Z" * 40000)  # still sent

    def test_higher_safety_trims_harder(self):
        # When the caller measures a dense request (real >> chars/4) and passes a bigger safety
        # factor, the floor must trim more aggressively so the REAL prompt still fits.
        msgs = [_u("task"), _a("A" * 16000), _u("more"), _a("B" * 16000), _u("current")]
        _, _, lo = contextfloor.fit([dict(m) for m in msgs], None, window=8000, reserve=500, safety=1.3)
        _, _, hi = contextfloor.fit([dict(m) for m in msgs], None, window=8000, reserve=500, safety=2.6)
        self.assertGreater(hi.turns_dropped, lo.turns_dropped)
        self.assertLess(hi.msg_tokens_after, lo.msg_tokens_after)

    def test_est_total_and_content_text(self):
        msgs = [_u("hello world"), _a("more text here")]
        self.assertGreater(contextfloor.est_total(msgs, None), 0)
        self.assertIn("hello world", contextfloor.content_text(msgs, None))

    def test_reserve_for(self):
        self.assertEqual(contextfloor.reserve_for({"max_tokens": 2048}), 2048)
        self.assertEqual(contextfloor.reserve_for({}), contextfloor.DEFAULT_GEN_RESERVE)
        self.assertEqual(contextfloor.reserve_for({"max_tokens": 0}), contextfloor.DEFAULT_GEN_RESERVE)
        self.assertEqual(contextfloor.reserve_for({"max_tokens": None}), contextfloor.DEFAULT_GEN_RESERVE)

    def test_reserve_for_output_reserve_wins_over_max_tokens(self):
        # The two-knob split: the role's output_reserve is the input-side reserve and takes
        # precedence — so the reserve is generous and INDEPENDENT of the (usually unset) hard cap.
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 8192}), 8192)
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 8192, "max_tokens": 256}), 8192)
        # The subtlety: with output_reserve set, a tiny/unset max_tokens can't collapse the reserve
        # (which is what re-truncated codex-local on the overflow retry). Uncapped coder → 8192.
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 8192, "max_tokens": None}), 8192)
        # A bad/zero output_reserve falls through to the existing max_tokens/default behavior.
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": 0, "max_tokens": 2048}), 2048)
        self.assertEqual(contextfloor.reserve_for({"cria_output_reserve": None}), contextfloor.DEFAULT_GEN_RESERVE)

    def test_pure_does_not_mutate_inputs(self):
        msgs = [_u("task"), _a("Z" * 12000), _u("current")]
        tools = _fat_tools(40, 500)
        msnap, tsnap = json.dumps(msgs), json.dumps(tools)
        contextfloor.fit(msgs, tools, window=8000, reserve=500)
        self.assertEqual(json.dumps(msgs), msnap)   # messages untouched
        self.assertEqual(json.dumps(tools), tsnap)  # tools untouched


if __name__ == "__main__":
    unittest.main()


class ProtectedOverflowTests(unittest.TestCase):
    """Lever 5: when the PROTECTED span alone is over budget (last user message near the top of
    a long agentic conversation), drop its oldest turns rather than send a known-doomed request
    (observed live: 259 messages, 171 trimmable tokens, guaranteed llama 400 retried forever)."""

    def _long_convo(self, turns=80):
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "THE TASK: build the thing"}]
        for i in range(turns):
            msgs.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": "shell", "arguments": json.dumps({"command": ["x" * 300]})}}]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 600})
        return msgs

    def test_drops_inside_protected_span_instead_of_sending_doomed(self):
        msgs = self._long_convo()
        out, tools, rep = contextfloor.fit(msgs, None, window=8000, reserve=1000, safety=1.8)
        self.assertFalse(rep.over_budget)                 # fits now
        self.assertGreater(rep.protected_dropped, 0)      # lever 5 did the work
        self.assertEqual(out[0]["role"], "system")        # system survives
        self.assertEqual(out[1]["content"], "THE TASK: build the thing")  # the request survives
        # the newest tail survives (active work)
        self.assertEqual(out[-1]["role"], "tool")
        self.assertEqual(out[-1]["tool_call_id"], "c79")
        # no orphaned tool results
        ids = {tc["id"] for m in out for tc in (m.get("tool_calls") or [])}
        for m in out:
            if m.get("role") == "tool":
                self.assertIn(m["tool_call_id"], ids)

    def test_irreducible_core_still_reports_over_budget(self):
        msgs = [{"role": "system", "content": "s" * 40000},
                {"role": "user", "content": "task"}]
        out, tools, rep = contextfloor.fit(msgs, None, window=8000, reserve=1000, safety=1.8)
        self.assertTrue(rep.over_budget)                  # honest: nothing droppable remained

    def test_lever5_sacrifices_protect_marked_last(self):
        # A protect-marked anchor (the compacted-note summary / briefing / gate anchor) sitting in
        # the droppable active span is dropped LAST — unmarked neighbors go first. It is the summary
        # standing in for everything already gone, so losing it is the worst loss.
        anchor = {"role": "tool", "tool_call_id": "gate",
                  "content": "___CRIA_GATE_ the ground-truth check output " + "g" * 600}
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "request"}]     # last_user = 1
        for i in range(40):
            msgs.append({"role": "assistant", "content": "a" * 600})
        msgs.insert(5, anchor)                              # protect-marked, near the OLDEST droppable
        out, dropped = contextfloor._drop_protected_overflow(msgs, msg_budget=1500)
        self.assertGreater(dropped, 10)                    # lots of unmarked turns dropped
        self.assertIn(anchor, out)                         # ...but the anchor survived them all


class FloorSynthesisTests(unittest.TestCase):
    """Dropping old turns SYNTHESIZES their durable state (files modified) instead of deleting it."""

    def test_drop_oldest_synthesizes_modified_files(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "writing",
             "tool_calls": [{"id": "c1", "function": {"name": "write_file",
                             "arguments": '{"path": "app/resolver.py", "content": "x"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "wrote"},
            {"role": "user", "content": "x" * 4000},
        ]
        out, dropped = contextfloor._drop_oldest(msgs, msg_budget=50)
        self.assertGreater(dropped, 0)
        joined = " ".join(str(m.get("content")) for m in out)
        self.assertIn(contextfloor._COMPACTED_MARK, joined)   # dropped turns synthesized, not vanished
        self.assertIn("app/resolver.py", joined)              # the modified file survives the drop
        self.assertEqual(out[0]["role"], "system")            # system stays at the front

    def test_drop_oldest_digests_dropped_output_that_compresses(self):
        # A dropped tool output must survive as a content_reduce()d SUMMARY in the stand-in note —
        # not vanish, and not be carried whole. This is the core enrichment.
        blob = ("<html><body>" + "".join(
            f"<div class='row r{i}'><p>Failure {i}: the resolver returned None</p></div>"
            for i in range(60)) + "</body></html>")
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "fetch the page",
             "tool_calls": [{"id": "c1", "function": {"name": "web_fetch", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": blob},
            {"role": "user", "content": "x" * 12000},
        ]
        out, dropped = contextfloor._drop_oldest(msgs, msg_budget=2400)
        self.assertGreater(dropped, 0)
        note = next(m for m in out if contextfloor._COMPACTED_MARK in str(m.get("content") or ""))
        self.assertIn("resolver returned None", note["content"])         # the substance survives
        self.assertLess(est_tokens(note["content"]), est_tokens(blob))   # summarized, not carried whole

    def test_output_that_will_not_compress_is_disclosed_not_carried_whole(self):
        # WHAT THIS PINS CHANGED, 2026-08-01. The goal is unchanged and still asserted below: the note
        # must cost far less than the turns it replaces (g16: 1,215 tokens dropped, 1,244-token note
        # inserted — a net-zero drop). What changed is HOW that is achieved.
        #
        # It used to be achieved by accident: content_reduce returned prose near its original size, the
        # oversized digest failed the budget check, and the turn was disclosed as unsummarizable. The
        # model got a count and nothing else.
        #
        # The digest now uses digest_reduce, which CUTS prose to the cap and states the cut, so it fits
        # honestly rather than being discarded. Either outcome is acceptable and both are disclosed —
        # what must never happen is the third one, which is what actually shipped: content_reduce's
        # prose tier deleting function words throughout, silently, turning "no field names could BE
        # READ FROM it" into "could read it". See tests/test_digest_never_word_strips.py.
        prose = ("The test suite failed because the resolver returned None for the Ada handle "
                 "and the assertion did not hold on the second row. ") * 30
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "run tests",
             "tool_calls": [{"id": "c1", "function": {"name": "shell", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": prose},
            {"role": "user", "content": "x" * 4000},
        ]
        out, dropped = contextfloor._drop_oldest(msgs, msg_budget=400)
        self.assertGreater(dropped, 0)
        note = next(m for m in out if contextfloor._COMPACTED_MARK in str(m.get("content") or ""))
        # Disclosed either way — as unsummarizable, or as carried-and-cut. Never silently reworded.
        self.assertTrue("could not be summarized" in note["content"]
                        or "characters of this turn omitted" in note["content"],
                        "a compacted turn must say what happened to it")
        self.assertLess(est_tokens(note["content"]), est_tokens(prose) * 0.5)   # the original goal
        # And whatever IS carried must be the real words, not a reworded version of them.
        if "characters of this turn omitted" in note["content"]:
            kept = note["content"].split("[…")[0]
            tail = kept.strip().split("\n")[-1].lstrip("• ").strip()   # the note bullets each digest
            self.assertIn(tail[:40], prose, "the carried text must be verbatim")

    def test_drop_oldest_lists_all_modified_files_no_cap(self):
        # No 30-file cap: every file the dropped turns modified is listed, however many.
        writes = [{"role": "assistant", "content": "",
                   "tool_calls": [{"id": f"c{i}", "function": {"name": "write_file",
                                   "arguments": json.dumps({"path": f"pkg/mod_{i}.py", "content": "x"})}}]}
                  for i in range(40)]
        msgs = [{"role": "system", "content": "sys"}] + writes + [{"role": "user", "content": "y" * 4000}]
        out, dropped = contextfloor._drop_oldest(msgs, msg_budget=200)
        self.assertEqual(dropped, 40)
        note = next(m for m in out if contextfloor._COMPACTED_MARK in str(m.get("content") or ""))
        for i in range(40):
            self.assertIn(f"pkg/mod_{i}.py", note["content"])   # all 40 listed, no silent omission


class NoteCostsLessThanItReplacesTests(unittest.TestCase):
    """g16 (gemma4, ada-handles): the floor dropped to exactly the budget and THEN appended a note
    worth up to 25% of that budget — and a turn small enough to fit the per-turn allowance was carried
    into it VERBATIM, so the drop saved nothing. Measured on that run: a 1,215-token turn dropped, a
    1,244-token note inserted; floor events with msg_after ABOVE msg_before; 350 turns and 736
    protected messages destroyed across 30 minutes, over_budget declared 60 times."""

    BIG = ("Project instructions (from the repo — follow these): keep the resolver in one module "
           "and do not add fallbacks. ") * 60

    def test_a_drop_always_shrinks_the_transcript(self):
        note = contextfloor._compacted_note([{"role": "user", "content": self.BIG}], 1, 16000)
        self.assertLess(est_tokens(note["content"]), est_tokens(self.BIG) * 0.5)

    def test_drop_oldest_leaves_room_for_its_own_note(self):
        msgs = ([{"role": "system", "content": "sys"}]
                + [{"role": "assistant", "content": f"turn {i} " + "x " * 400} for i in range(20)]
                + [{"role": "user", "content": "do the thing"}])
        kept, dropped = contextfloor._drop_oldest(msgs, msg_budget=2000)
        self.assertGreater(dropped, 0)
        self.assertLessEqual(contextfloor._msgs_tokens(kept), 2000)   # note INCLUDED, not discovered after

    def test_lever5_leaves_room_for_its_own_note(self):
        msgs = ([{"role": "system", "content": "sys"}, {"role": "user", "content": "request"}]
                + [{"role": "assistant", "content": "a " * 300} for _ in range(30)])
        out, dropped = contextfloor._drop_protected_overflow(msgs, msg_budget=3000)
        self.assertGreater(dropped, 0)
        self.assertLessEqual(contextfloor._msgs_tokens(out), 3000)

    def test_an_anchor_is_not_sacrificed_when_the_fit_is_unreachable(self):
        # Sacrificing a protect-marked turn is the worst loss there is; paying it and STILL landing
        # over budget buys nothing at all.
        anchor = {"role": "user", "content": "⟦ctx:rollup⟧ the rolling summary " + "s" * 400}
        msgs = ([{"role": "system", "content": "sys"}, {"role": "user", "content": "request"}, anchor]
                + [{"role": "assistant", "content": "a" * 900} for _ in range(8)])
        out, _ = contextfloor._drop_protected_overflow(msgs, msg_budget=100)   # unreachable
        self.assertIn(anchor, out)
