"""The compaction retry composed its request with less grounding than the pass that had just failed.

TWO FINDINGS HERE, AND THEY ARE NOT THE SAME SIZE.

LIVE — the retry's missing disk inventory. `_harden_compaction_reply` re-asks for the briefing when
the first reply came back empty, truncated, or as a hallucinated tool call. It composed that retry
with NO `files_list`, while the first pass passes `workspace_inventory(...)`. That inventory exists
because a writer shown no workspace invents one (qwen35/rust 0032 briefed "`tests/nested_key_lookup.rs`
exists" over a six-file listing containing no tests/ at all), and the retry is the pass that runs
precisely BECAUSE the model already produced garbage — the one that can least afford to be handed
less than the pass it is replacing. It also re-derived the session key a few lines below its own
first use of it; that is derived once now.

NOT LIVE — the gate plan. `compaction_request` was the one caller of four that dropped the plan when
calling `clean_gate_results`, and the plan is where the hard-failure kind, the workspace root, the
untested list, the delimiter facts and the offline section live. On a deny(warnings) build blob the
difference is real and this module proves it:

    no plan   → "the repo's own checks that ran reported no error-class problems."
    with plan → "one of the repo's own checks FAILED but printed no parseable location"

But a raw gate blob does not reach that call. Both callers strip `selfcompact._ANCHOR_MARKERS` from
the summarizer's input first and `___CRIA_GATE_` is one of them: 0 of 70 real self-compact prompts
carry a raw marker, and the authoritative last-gate state is appended deterministically afterwards
by `server._last_checks_note`. The plan is threaded anyway because one caller of four holding a
different rule about what the cleaner may be told is how these two paths drifted before — but it is
recorded here as inert, not sold as a fix. #11b cuts both ways: a mechanism must reach what it is
asked about, and so must a claim about a mechanism.
"""

import tempfile
import unittest

from cria import probegate, selfcompact
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


def cand(kind: ProbeKind) -> ProbeCandidate:
    return ProbeCandidate(kind=kind, command=["cargo", "build"], working_dir=tempfile.gettempdir(),
                          confidence=90, expected_value=80, cost=ProbeCost.Cheap,
                          mutates_code=False, may_hang=False, may_need_services=False, reason="t")


def gate_blob(body: str, exit_code: int) -> str:
    return ("Chunk ID: abc\nOutput:\n___CRIA_GATE_probe-0___\n"
            + body + f"\nEXIT:{exit_code}\n")


def transcript(raw: str) -> list[dict]:
    return [{"role": "user", "content": "Build the cart library."},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "exec_command", "arguments": '{"cmd": "gate"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": raw}]


WARNINGS_ONLY = ("warning: unused variable `n`\n"
                 "warning: build failed due to 1 warning emitted (deny(warnings))")


class TheRetryIsGroundedLikeTheFirstPassTests(unittest.TestCase):
    """THE LIVE ONE."""

    def test_the_retry_passes_the_disk_and_the_plan(self):
        """The disk half is fully live: a real file on disk shows up in the retry's request, proven
        below. The gate-plan half is threaded too, but a RAW gate blob never survives
        ``_compaction_transcript``'s anchor filter to reach a point where the plan could change the
        retry's OUTPUT (see ``WhyItIsInertTodayTests`` below and this module's own docstring — the
        same "0 of 70" fact). What IS observable, and checked here: the retry actually CALLS
        ``_session_gate_plan`` for this session — the original bug was composing the retry with
        neither fact threaded through at all."""
        import json
        import os
        from types import SimpleNamespace
        from unittest import mock

        from cria import server as srv

        class _Provider:
            calls = []

            @staticmethod
            def chat(pb, rlog):
                _Provider.calls.append(pb)
                return json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": "recovered briefing"}}]})

        class _Srv:
            class cfg:
                class routing:
                    roles = {}

        class _NullRlog:
            def emit(self, *a, **k):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "resolve_handle.py"), "w") as f:
                f.write("x = 1\n")
            plan = probegate.GatePlan(workspace=tmp, candidates=[cand(ProbeKind.BuildCheck)])
            sess = SimpleNamespace(gate_plan=plan, last_gate_flag="")
            _Srv.loop = SimpleNamespace(_store=SimpleNamespace(get=lambda k: sess))

            msgs = transcript(gate_blob(WARNINGS_ONLY, 1))
            msgs[0] = {**msgs[0], "content": msgs[0]["content"]
                      + f"\n<environment_context><cwd>{tmp}</cwd></environment_context>"}
            comp = {"choices": [{"message": {"role": "assistant", "content": ""}}]}  # empty → retry

            gate_plan_calls = []
            real_session_gate_plan = srv._session_gate_plan

            def _spy(server, sk):
                gate_plan_calls.append(sk)
                return real_session_gate_plan(server, sk)

            with mock.patch.object(srv, "_session_gate_plan", _spy):
                srv._harden_compaction_reply(comp, {"messages": msgs}, provider=_Provider,
                                             server=_Srv, rlog=_NullRlog())

            self.assertEqual(len(_Provider.calls), 1)
            retry_text = json.dumps(_Provider.calls[0]["messages"])
            self.assertIn("resolve_handle.py", retry_text)  # the disk inventory reached the retry
            self.assertTrue(gate_plan_calls, "the retry never asked for this session's gate plan")

    def test_the_session_key_is_derived_once(self):
        """It was computed inside the retry branch and again in the appendix branch. Two derivations
        of one fact is how they come to disagree."""
        import inspect

        from cria import server as srv
        src = inspect.getsource(srv._harden_compaction_reply)
        self.assertEqual(src.count("session_key({}"), 1)

    def test_both_halves_use_the_same_workspace(self):
        import inspect

        from cria import server as srv
        src = inspect.getsource(srv._harden_compaction_reply)
        self.assertEqual(src.count("_session_cwd("), 1)
        self.assertIn("_workspace_listing(ws)", src)


class WhatThePlanWouldChangeIfItArrivedTests(unittest.TestCase):
    """Pinned so the difference is a measured fact rather than a claim in a commit message."""

    def setUp(self):
        self.msgs = transcript(gate_blob(WARNINGS_ONLY, 1))
        self.plan = probegate.GatePlan(workspace=tempfile.gettempdir(),
                                       candidates=[cand(ProbeKind.BuildCheck)])

    def test_with_the_plan_a_deny_warnings_build_reads_as_failed(self):
        out = selfcompact.compaction_request(self.msgs, "", self.plan)
        self.assertIn("FAILED", out)
        self.assertNotIn("no error-class problems", out)

    def test_without_it_the_same_bytes_read_as_clean(self):
        self.assertIn("no error-class problems", selfcompact.compaction_request(self.msgs))

    def test_a_lint_probe_keeps_its_advisory_reading(self):
        """Not a blanket "non-zero means failed" — the probe KIND is the grounded distinction, and a
        lint exit on advisory-shaped output must still not send the coder chasing style."""
        lint = probegate.GatePlan(workspace=tempfile.gettempdir(),
                                  candidates=[cand(ProbeKind.Lint)])
        self.assertIn("no error-class problems", selfcompact.compaction_request(self.msgs, "", lint))

    def test_the_untested_qualifier_travels_with_it(self):
        """"the checks reported no problems" is half a sentence when no test could be found."""
        msgs = transcript(gate_blob("all good", 0))
        plan = probegate.GatePlan(workspace=tempfile.gettempdir(),
                                  candidates=[cand(ProbeKind.Lint)],
                                  untested=["no file matching *_test.go exists"])
        self.assertIn("*_test.go", selfcompact.compaction_request(msgs, "", plan))
        self.assertNotIn("*_test.go", selfcompact.compaction_request(msgs))


class WhyItIsInertTodayTests(unittest.TestCase):
    """The honest half. If any of these three ever flips, the threading above stops being inert and
    the finding above becomes live — which is the whole reason to pin them."""

    def test_a_raw_gate_marker_is_an_anchor(self):
        self.assertIn(probegate.SECTION_PREFIX, selfcompact._ANCHOR_MARKERS)

    def test_the_harness_path_drops_the_raw_blob_before_composing(self):
        from cria import server as srv
        body = {"messages": transcript(gate_blob(WARNINGS_ONLY, 1)), "model": "m"}
        text = "".join(m.get("content") or ""
                       for m in srv._compaction_body(body, None, None)["messages"])
        self.assertNotIn("no error-class problems", text)
        self.assertNotIn(probegate.SECTION_PREFIX, text)

    def test_the_gate_state_is_appended_deterministically_instead(self):
        """What actually carries the check truth across a harness compaction: not the model's
        briefing, but the authoritative flag, verbatim, appended after it."""
        from types import SimpleNamespace

        from cria import server as srv

        class _Store:
            def get(self, k):
                return SimpleNamespace(last_gate_flag="⟦ctx:checks⟧ 2 failed")

        note = srv._last_checks_note(SimpleNamespace(loop=SimpleNamespace(_store=_Store())), "s1")
        self.assertIn("2 failed", note)


class TheStoreLookupTests(unittest.TestCase):
    """`_session_gate_plan` mirrors `_last_checks_note`: an unknown session answers None, never a
    guess and never an exception — the compaction still runs, it just runs unplanned."""

    class _Store:
        def __init__(self, mapping):
            self._m = mapping

        def get(self, k):
            return self._m.get(k)

    class _Sess:
        gate_plan = "PLAN"

    def _server(self, mapping):
        from types import SimpleNamespace
        return SimpleNamespace(loop=SimpleNamespace(_store=self._Store(mapping)))

    def test_a_known_session_yields_its_plan(self):
        from cria import server as srv
        self.assertEqual(srv._session_gate_plan(self._server({"s1": self._Sess()}), "s1"), "PLAN")

    def test_an_unknown_session_yields_none(self):
        from cria import server as srv
        self.assertIsNone(srv._session_gate_plan(self._server({}), "s1"))

    def test_no_loop_at_all_yields_none(self):
        from types import SimpleNamespace

        from cria import server as srv
        self.assertIsNone(srv._session_gate_plan(SimpleNamespace(), "s1"))


class TheLoopPathHandsOverItsSessionPlanTests(unittest.TestCase):
    def test_self_compact_passes_it(self):
        """Structural, and deliberately so: driving ``_self_compact`` with a raw gate blob in the
        rolled-up middle (verified by hand, both with and without a large filler transcript around
        it) never lands a trace of it in what reaches the summarizer — ``compact()`` itself strips
        the harness-compaction anchor markers before the messages become ``mm``, the same "0 of 70"
        fact this module's docstring already states for the two documented callers. There is no
        reachable input that makes this line's OUTPUT differ, which is exactly why the module
        docstring calls this half "NOT LIVE": kept for one-owner consistency across the four
        ``clean_gate_results`` callers, not because a fixture could ever observe it firing here."""
        import inspect

        from cria import loop
        src = inspect.getsource(loop.Loop._self_compact)
        i = src.index("compaction_request(")
        self.assertIn('getattr(sess, "gate_plan", None)', src[i:i + 1200])


if __name__ == "__main__":
    unittest.main()
