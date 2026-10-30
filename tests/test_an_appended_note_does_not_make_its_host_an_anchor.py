"""A note cria appends to a tool result does not turn the tool's output into a compaction anchor.

ornith1.5_9b / Java run07 (session 01a17e45), writer call 0075: the coder's ``edit_file(pom.xml)`` was
in the middle being summarized, and its result -- ``Wrote pom.xml`` plus the dependency-surface
``⟦ctx:facts⟧`` note ``returnedpolicies._note_dependency_surface`` had appended to it -- was classified
as an anchor because the marker appeared ANYWHERE in its text. The writer (and the validators, which
read the same blocks) got the edit with no result. When such a fold was accepted (20261012T044734,
0047 -> coder 0051) the host result rode on without its call and reached the coder re-roled as a user
turn: "Wrote pom.xml ..." in the user's voice.

The anchor is the note cria placed, not the host. Driven from the real producer
(``writeproxy.represent_inbound`` appending a real dependency-surface note) through the production
compaction owner ``Loop._self_compact`` (real rolling engine, real validators); only model replies are
fake. Controls: cria's own standalone anchors stay excluded and verbatim, the harness compaction path,
dedup of identical anchors, and an unverifiable boundary keeping the old whole-message rule.
"""
import json
import os
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace

from cria import contextfloor, depsurface, memoryhandoff, resultnotes, selfcompact, tokenratio, writeproxy
from cria.config import Role
from cria.loop import Loop, LoopContext, PlanSession
from cria.plan import Plan, PlanItem

MODEL = "appended-note-test-model"
BIG = "w" * 4_000                      # ~1,000 est. tokens per old turn
NOTE_HEAD = "⟦ctx:facts⟧ THE VERSION OF"
LEDGER = "⟦ctx:facts⟧ THESE FETCHES FAILED. https://example.invalid/spec -> 404"
WROTE = "Wrote go.mod\ngo.mod now has 5 lines."
EDIT_ARGS = {"path": "go.mod", "old_string": "go 1.21\n", "new_string": "go 1.21\n\nrequire example.invalid/nonexistent v1.4.0\n"}


def _reply(text: str) -> bytes:
    return json.dumps({"choices": [{"finish_reason": "stop",
                                    "message": {"role": "assistant", "content": text}}]}).encode()


class _Reasoner:
    """The briefing writer and its three validation lenses; records what each was shown."""

    def __init__(self):
        self.writer, self.fidelity = [], []

    def __call__(self, body, rlog):
        system = body["messages"][0]["content"]
        shown = "\n".join(m.get("content") or "" for m in body["messages"][1:])
        if "PLAN or RETROSPECTIVE" in system:
            return _reply("RETROSPECTIVE")
        if "NARROWS or PRESERVES" in system:
            return _reply("PRESERVES")
        if "CHANGED or NOT CHANGED" in system:
            return _reply("NONE")      # the change-claim lens: nothing here to list
        if "UNFAITHFUL or FAITHFUL" in system:
            self.fidelity.append(shown)
            return _reply("FAITHFUL")
        self.writer.append(shown)
        return _reply("The coder edited go.mod to declare the dependency.")


def _loop(reasoner) -> Loop:
    def coder(body, rlog):
        return _reply("")
    coder.upstream = SimpleNamespace(_resolve_window=lambda rlog: 10_000_000, _window_guessed=False,
                                     loaded_model=lambda rlog: MODEL)
    ctx = LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner,
                      reasoner_role=Role(name="reasoner", backend="local"), runs_dir="")
    return Loop(replace(ctx, trigger_compaction=100, coder_role=Role(name="coder", backend="local")))


def _session() -> PlanSession:
    return PlanSession(plan=Plan(id="20261027T0000-abcd1234", task="fix the cart",
                                 created="2026-10-27T00:00:00+00:00", items=[PlanItem("step 1")]))


def _edit_pair(call_id="c1"):
    return [{"role": "assistant", "content": "Declare the dependency.", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": "edit_file", "arguments": json.dumps(EDIT_ARGS)}}]},
        {"role": "tool", "tool_call_id": call_id, "content": WROTE}]


def _turns(n, tag):
    return [{"role": "user" if i % 2 else "assistant", "content": f"{tag} {i} " + BIG} for i in range(n)]


class _Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


class AppendedNoteIsNotAHostAnchor(unittest.TestCase):
    def setUp(self):
        tokenratio.reset()
        self.addCleanup(tokenratio.reset)
        home, ws = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.addCleanup(ws.cleanup)
        self.home, self.ws = home.name, ws.name
        real = os.path.expanduser
        os.path.expanduser = lambda p: (self.home if p == "~" else
                                        os.path.join(self.home, p[2:]) if p.startswith("~/") else real(p))
        self.addCleanup(setattr, os.path, "expanduser", real)
        for state in (depsurface._ANCHOR, depsurface._WITHHELD, depsurface._ABSTAINED):
            state.clear()
            self.addCleanup(state.clear)
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write("module example.com/cart\n\ngo 1.21\n\nrequire example.invalid/nonexistent v1.4.0\n")
        mod = os.path.join(self.home, "go", "pkg", "mod", "example.invalid", "nonexistent@v1.4.0")
        os.makedirs(mod)
        with open(os.path.join(mod, "decimal.go"), "w") as fh:
            fh.write("package decimal\n\nfunc NewFromString(value string) (Decimal, error) {\n"
                     "\treturn Decimal{}, nil\n}\n")

    def _represented(self):
        """The coder's history as the real producer annotates it: the edit's result is the newest tool
        result, so the dependency-surface note is appended to it."""
        raw = ([{"role": "system", "content": "sys"}, {"role": "user", "content": "fix the cart"}]
               + _turns(6, "old") + _edit_pair() + [{"role": "user", "content": LEDGER}]
               + _turns(6, "mid") + _turns(7, "tail"))
        out = writeproxy.represent_inbound(raw, workspace_root=self.ws, sess_key="s-appended-note",
                                           tools_present=True)
        host = next(m for m in out if m.get("tool_call_id") == "c1")
        self.assertTrue(host["content"].startswith(WROTE), "fixture: the tool's own output leads")
        self.assertIn(NOTE_HEAD, host["content"], "fixture: the real producer appended its note")
        return out, host

    def test_the_writer_reads_the_edit_with_its_result_and_the_note_rides_on_verbatim(self):
        msgs, host = self._represented()
        note = host["content"][len(WROTE):].lstrip("\n")
        reasoner = _Reasoner()
        view = _loop(reasoner)._self_compact(msgs, _session(), None, _Log(), pinned_task="fix the cart")

        self.assertEqual(len(reasoner.writer), 1)
        for seen in (reasoner.writer[0], reasoner.fidelity[0]):
            self.assertIn('edit_file({"path": "go.mod"', seen)
            self.assertIn("tool: " + WROTE, seen, "the edit's result is evidence, not an anchor")
            self.assertNotIn(NOTE_HEAD, seen, "the anchored note is not summarized")
            self.assertNotIn(LEDGER, seen, "cria's own facts anchor is still excluded")

        sent = [m.get("content") for m in view]
        self.assertIn(note, sent, "the note itself survives the fold verbatim")
        self.assertIn(LEDGER, sent, "cria's standalone facts anchor survives verbatim")
        self.assertFalse(any(WROTE in (c or "") for c in sent), "the folded host is summarized, not kept")
        self.assertEqual(contextfloor.ensure_tool_integrity(view)[1], 0,
                         "no result rides on without its call")

    def test_the_harness_compaction_writer_keeps_the_pair_and_still_excludes_cria_anchors(self):
        msgs, host = self._represented()
        rollup = {"role": "user", "content": selfcompact.SUMMARY_MARKER + " an earlier briefing"}
        evidence = memoryhandoff.evidence_messages(
            msgs[1:] + [rollup, {"role": "user", "content": "summarize"}],
            SimpleNamespace(drop_harness_frame=lambda mm: mm))
        # The host's result is evidence WITHOUT the note, as the rolling writer reads it (the assertion
        # here used to accept the host whole, note included: the harness writer then summarized cria's
        # note as part of the tool's output). The note is carried verbatim in the reply instead; see
        # tests/test_a_harness_compaction_carries_an_appended_note.py.
        result = next(m for m in evidence if m.get("tool_call_id") == "c1")
        self.assertEqual(result["content"], WROTE)
        self.assertFalse(any(NOTE_HEAD in str(m.get("content") or "") for m in evidence))
        self.assertIn(NOTE_HEAD, memoryhandoff.carried_notes(
            msgs[1:] + [rollup, {"role": "user", "content": "summarize"}]))
        self.assertTrue(any(c.get("id") == "c1" for m in evidence for c in m.get("tool_calls") or []))
        self.assertNotIn(rollup, evidence)
        self.assertFalse(any(m.get("content") == LEDGER for m in evidence))

    def test_the_producer_stamp_reaches_the_rolling_engine_through_the_driver(self):
        """The payload boundary the producer stamps must survive every transform between
        ``represent_inbound`` and the rolling engine (common preparation: scrub, build-location notes,
        gate cleaning, root framing). A transform that dropped or broke it would silently restore the
        old whole-message rule. Driven through ``Loop.drive``; the engine itself is a recorder here."""
        from cria import assistruntime, loop as loopmod, wsview
        from cria.memoryeffects import Effect
        from tests.test_generation_driver_policy import setup_driver
        from tests.test_loop import _Rlog
        msgs, _host = self._represented()
        driver, sess, body = setup_driver()
        body["messages"], sess.workspace_root = msgs, self.ws
        seen = []

        def rolling(source, state, enabled=True):
            seen.append(source.messages)
            return selfcompact.RollingResult(source.messages, state, Effect.NO_OP)
        runtime = assistruntime.AssistRuntime.select(level=5)
        runtime = replace(runtime, ordered_stages=tuple(
            replace(selfcompact.DEFINITION, execute=rolling) if d.policy.id == selfcompact.DEFINITION.policy.id
            else d for d in runtime.ordered_stages))
        driver._ctx.pilot_runtime, driver._ctx.self_compact = runtime, True
        driver._coder_turn = lambda *a, **k: loopmod._completion_toolcalls([{"id": "n", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"go.mod"}'}}])
        token = wsview.bind(wsview.DirectView(self.ws))
        try:
            with assistruntime.bound(runtime):
                driver.drive(body, "driver-fixture", None, _Rlog())
        finally:
            wsview.unbind(token)
        self.assertTrue(seen, "fixture: the driver reached the rolling engine")
        got = next(m for m in seen[0] if m.get("tool_call_id") == "c1")
        self.assertEqual(resultnotes.payload_of(got, got["content"]), WROTE)
        self.assertFalse(selfcompact.has_anchor(got))
        self.assertIn(NOTE_HEAD, selfcompact.appended_anchor(got)["content"])


class AnchorIdentityControls(unittest.TestCase):
    KW = dict(trigger_tokens=100, keep_tail_tokens=6_000, recompact_tokens=20)
    NOTE = "⟦ctx:facts⟧ THE VERSION OF example.invalid/nonexistent v1.4.0 DECLARED IN go.mod — func NewFromString"

    def _host(self, call_id, output):
        pair = _edit_pair(call_id)
        pair[1]["content"] = output
        resultnotes.append_note(pair[1], self.NOTE)
        return pair

    def test_identical_appended_notes_collapse_to_one_verbatim_copy(self):
        msgs = ([{"role": "system", "content": "sys"}] + self._host("c1", "Wrote go.mod")
                + _turns(4, "a") + self._host("c2", "Wrote go.sum") + _turns(4, "b") + _turns(7, "tail"))
        log = _Log()
        out, _, applied = selfcompact.compact(msgs, lambda mm: "ROLLUP", selfcompact.CompactState(),
                                              rlog=log, **self.KW)
        self.assertTrue(applied)
        self.assertEqual([m.get("content") for m in out].count(self.NOTE), 1)
        self.assertIn(("context.anchor_dedup", {"reshape": "dedup", "dropped": 1}), log.events)

    def test_a_boundary_that_no_longer_verifies_keeps_the_whole_message_verbatim(self):
        pair = self._host("c1", "Wrote go.mod")
        pair[1]["content"] = "rewritten " + pair[1]["content"]       # the stamped payload no longer matches
        msgs = [{"role": "system", "content": "sys"}] + pair + _turns(6, "a") + _turns(7, "tail")
        fed = []
        out, _, applied = selfcompact.compact(msgs, lambda mm: fed.extend(mm) or "ROLLUP",
                                              selfcompact.CompactState(), **self.KW)
        self.assertTrue(applied)
        self.assertIn(pair[1]["content"], [m.get("content") for m in out])
        self.assertNotIn(pair[1], fed)

    def test_a_marker_in_the_tools_own_payload_still_anchors_it(self):
        spec = "HTTP 200 · https://example.invalid/openapi.json\n[response shape — GET /h → holder, resolved_addresses]"
        pair = self._host("c1", spec)
        msgs = [{"role": "system", "content": "sys"}] + pair + _turns(6, "a") + _turns(7, "tail")
        fed = []
        out, _, _ = selfcompact.compact(msgs, lambda mm: fed.extend(mm) or "ROLLUP",
                                        selfcompact.CompactState(), **self.KW)
        self.assertIn(pair[1]["content"], [m.get("content") for m in out])
        self.assertFalse(any("resolved_addresses" in selfcompact._text(m) for m in fed))


if __name__ == "__main__":
    unittest.main()
