"""Deterministic control-flow replay for Ornith feed-pipeline call 0049.

It drives both production ``author_steer`` paths and the wheel-spin guard seam with
captured responses and fake transports.  It neither executes task tools nor infers a
fresh model response, wire fit, task correctness, or usefulness.
"""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path

from cria import loop, wsview
from cria.config import Role


_ARCHIVE = Path(__file__).parent / "fixtures" / "ornith_feed_1789115104"


class _Rlog:
    phase = ""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [kind for kind, _ in self.events]


def _captured(name: str) -> dict:
    return json.loads((_ARCHIVE / name).read_text(encoding="utf-8"))


ACTUAL_0049 = _captured("call-0049-reasoner.response.json")
ACTUAL_0050 = _captured("call-0050-steer-recover.response.json")
ACTUAL_0051 = _captured("call-0051-steer-code.response.json")


def _chat(replies):
    """A real author path transport seam, recording phase and serialized bodies."""
    seen = []

    def chat(body, rlog):
        seen.append((rlog.phase, body))
        return json.dumps(replies[min(len(seen) - 1, len(replies) - 1)]).encode()

    chat.seen = seen
    return chat


def _state():
    # Current diagnostic grounds the existing one-word action verdict.  The test transport
    # returns the captured 0051 SUPPORTED declaration; no substitute classifier exists here.
    return types.SimpleNamespace(
        gate_stall=3,
        recent_writes=[],
        spin_path="",
        steered_checks_text="",
        fetched_pages={},
        last_gate_flag=(
            "Importer.java:77: cannot find symbol\n"
            "Importer.java:173: no suitable method found for invokeAll"
        ),
        refused_names=[],
    )


def _body():
    return {
        "messages": [{"role": "user", "content": "Repair the importer."}],
        "tools": [],
    }


class StructuralAuthorRefusalRecoveryTests(unittest.TestCase):
    """The two production author branches must treat the original response alike."""

    def _author(self, replies, *, tooled: bool):
        chat = _chat(replies)
        rlog = _Rlog()
        role = Role(name="reasoner", backend="local")
        if not tooled:
            steer = loop.author_steer(chat, role, "", _state(), _body(), rlog,
                                      condition="thrash")
            return steer, chat.seen, rlog

        with tempfile.TemporaryDirectory() as root:
            # A delivered, complete survey is the production predicate for the inspection branch;
            # do not fake it with ``os.path.isdir``.  The fake reasoner answers immediately, so
            # no read-only tool is executed.
            view = wsview.View(root)
            view._ingest_tree("F\t0\t0\tImporter.java", complete=True)
            token = wsview.bind(view)
            try:
                steer = loop.author_steer(chat, role, root, _state(), _body(), rlog,
                                          condition="thrash")
            finally:
                wsview.unbind(token)
        return steer, chat.seen, rlog

    def test_captured_structural_refusal_is_not_recovered_on_either_author_path(self):
        """Baseline-compatible incident regression: 0049 must not reach 0050/0051."""
        for tooled in (False, True):
            with self.subTest(tooled=tooled):
                steer, seen, rlog = self._author([ACTUAL_0049, ACTUAL_0050, ACTUAL_0051],
                                                 tooled=tooled)
                # Before the outcome gate this fails with all three real author-path phases
                # (including the existing focused action verdict) and the returned/injectable
                # recovered directive.  It is intentionally checked before the expected null so
                # the baseline failure prints the whole bad sequence.
                self.assertEqual(
                    [phase for phase, _body in seen], ["reasoner"],
                    msg=(f"unexpected recovery/support path: steer={steer!r}; "
                         f"events={rlog.kinds()}"),
                )
                self.assertIsNone(
                    steer,
                    "a structurally refused multi-action answer must not be recast as ON_TRACK",
                )
                self.assertIn("loop.steer_multiple_actions", rlog.kinds())
                self.assertNotIn("loop.steer_answer_contradicted", rlog.kinds())
                self.assertNotIn("loop.steer_from_reasoning", rlog.kinds())
                self.assertNotIn("loop.steer_diagnostic_action", rlog.kinds())
                self.assertNotIn("loop.steer_outcome", rlog.kinds())

    def test_genuine_on_track_contradiction_still_recovers_through_the_same_funnel(self):
        author = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant",
                "content": "ON_TRACK",
                "reasoning_content": "The coder is stuck in a loop and needs help.",
            }}],
        }
        recovered = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant",
                "content": "Read Importer.java and run the current compile check.",
            }}],
        }
        supported = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "SUPPORTED",
            }}],
        }
        for tooled in (False, True):
            with self.subTest(tooled=tooled):
                steer, seen, rlog = self._author([author, recovered, supported], tooled=tooled)
                self.assertEqual(steer, "Read Importer.java and run the current compile check.")
                self.assertEqual([phase for phase, _body in seen],
                                 ["reasoner", "steer-recover", "steer-code"])
                self.assertIn("loop.steer_answer_contradicted", rlog.kinds())
                self.assertIn("loop.steer_from_reasoning", rlog.kinds())
                self.assertIn("loop.steer_diagnostic_action", rlog.kinds())
                self.assertIn("loop.steer_outcome", rlog.kinds())

    def test_an_ordinary_single_action_still_reaches_the_existing_supported_funnel(self):
        ordinary = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant",
                "content": "Read Importer.java and run the current compile check.",
            }}],
        }
        supported = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "SUPPORTED",
            }}],
        }
        for tooled in (False, True):
            with self.subTest(tooled=tooled):
                steer, seen, rlog = self._author([ordinary, supported], tooled=tooled)
                self.assertEqual(steer, "Read Importer.java and run the current compile check.")
                self.assertEqual([phase for phase, _body in seen], ["reasoner", "steer-code"])
                self.assertNotIn("loop.steer_answer_contradicted", rlog.kinds())
                self.assertIn("loop.steer_diagnostic_action", rlog.kinds())
                self.assertIn("loop.steer_outcome", rlog.kinds())

    def test_empty_author_reply_stays_silent_without_a_recovery_or_outcome(self):
        empty = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "",
            }}],
        }
        for tooled in (False, True):
            with self.subTest(tooled=tooled):
                steer, seen, rlog = self._author([empty], tooled=tooled)
                self.assertIsNone(steer)
                self.assertEqual(
                    [phase for phase, _body in seen],
                    ["reasoner"] if tooled else ["reasoner", "reasoner-noreason"],
                )
                self.assertNotIn("loop.steer_answer_contradicted", rlog.kinds())
                self.assertNotIn("loop.steer_outcome", rlog.kinds())

    def test_structural_refusal_keeps_the_factual_guard_fallback_not_the_recovered_steer(self):
        """A fake harness drives the production wheel-spin -> author -> nudge route, no executor."""
        from cria.plan import Plan, PlanItem

        class Planner:
            def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
                return Plan(id="scratch", task="Repair the importer.", created="now",
                            items=[PlanItem("repair the importer")])

        class Writer:
            def __init__(self):
                self.n = 0
                self.bodies = []

            def __call__(self, body, rlog):
                self.bodies.append(body)
                self.n += 1
                call = {
                    "id": "w", "type": "function",
                    "function": {"name": "write_file", "arguments": json.dumps({
                        "path": "Importer.java", "content": f"pass {self.n}",
                    })},
                }
                return json.dumps({"choices": [{"message": {
                    "role": "assistant", "tool_calls": [call],
                }}]}).encode()

        class Reasoner:
            def __call__(self, body, rlog):
                by_phase = {
                    "reasoner": ACTUAL_0049,
                    "steer-recover": ACTUAL_0050,
                    "steer-code": ACTUAL_0051,
                }
                return json.dumps(by_phase[rlog.phase]).encode()

        class Classification:
            engagement = "task"
            task_type = "coding"
            cached = False

        shell = {"type": "function", "function": {
            "name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "array"}}},
        }}
        with tempfile.TemporaryDirectory() as root:
            # Disk is only a fixture for the detector; no command is run against it.
            Path(root, "Importer.java").write_text("class Importer {}\n", encoding="utf-8")
            writer = Writer()
            engine = loop.Loop(loop.LoopContext(
                planner=Planner(), coder_chat=writer, reasoner_chat=Reasoner(), runs_dir="",
                workspace_root=root, reasoner_role=Role(name="reasoner", backend="local"),
                focus_trim=False, self_compact=False,
            ))
            rlog = _Rlog()
            body = {"messages": [{"role": "user", "content": "Repair the importer."}],
                    "tools": [shell], "stream": True}
            for _ in range(loop.WHEEL_SPIN_WRITES):
                engine.drive(body, "scratch-key", Classification(), rlog)
            gate = engine.drive(body, "scratch-key", Classification(), rlog)
            gate_id = gate["choices"][0]["message"]["tool_calls"][0]["id"]
            from cria.probegate import SECTION_PREFIX as P, SECTION_SUFFIX as S
            result = (f"{P}probe-0{S}\nImporter.java:77: cannot find symbol\nEXIT:1\n"
                      f"{P}git{S}\nabc\n")
            probe_body = {**body, "messages": body["messages"] + [
                {"role": "tool", "tool_call_id": gate_id, "content": result},
            ]}
            engine.drive(probe_body, "scratch-key", Classification(), rlog)

        injected = writer.bodies[-1]["messages"][-1]["content"]
        self.assertNotIn("In one edit pass resolve both compile errors", injected)
        # guard_probe_steer owns an existing fact-only fallback for a declined author.  The
        # candidate must not erase it merely to make the recovered model directive disappear.
        self.assertIn(
            "you have rewritten `Importer.java` repeatedly; ground truth from the repo's own checks:",
            injected,
        )
        self.assertIn("found no error-class problems in your current edits", injected)
        self.assertIn("loop.steer_multiple_actions", rlog.kinds())
        self.assertNotIn("loop.steer_answer_contradicted", rlog.kinds())
        self.assertNotIn("loop.steer_outcome", rlog.kinds())
        spin = [kw for kind, kw in rlog.events if kind == "loop.spin_probe_result"]
        self.assertEqual([(e["authored"], e["grounded"]) for e in spin], [(False, True)])

    def test_undecidable_existing_action_verdict_still_withholds_and_records_its_verdict(self):
        ordinary = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant",
                "content": "Read Importer.java and run the current compile check.",
            }}],
        }
        undecidable = {
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "I cannot tell.",
            }}],
        }
        for tooled in (False, True):
            with self.subTest(tooled=tooled):
                steer, seen, rlog = self._author([ordinary, undecidable], tooled=tooled)
                self.assertIsNone(steer)
                self.assertEqual([phase for phase, _body in seen], ["reasoner", "steer-code"])
                verdicts = [kw["verdict"] for kind, kw in rlog.events
                            if kind == "loop.steer_diagnostic_action"]
                self.assertEqual(verdicts, ["UNDECIDABLE"])
                outcomes = [kw for kind, kw in rlog.events if kind == "loop.steer_outcome"]
                self.assertEqual([(o["delivered"], o["refused_by"]) for o in outcomes],
                                 [(False, "diagnostic_undecidable")])


if __name__ == "__main__":
    unittest.main()
