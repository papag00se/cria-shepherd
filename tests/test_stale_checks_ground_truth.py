"""cria may not restate test failures the coder has already cleared.

The coder has its own shell and runs pytest itself; cria's gate cache does not know. So cria kept
asserting failures the disk had cleared, under the word GROUND TRUTH, in prompts that carried the
contradiction:

  1786047359 call 0051 — "⟦ctx:steer⟧ The repo's checks report persistent test failures on lines 44
  and 109" two turns after the same prompt said "no error-class problems" and "6 passed in 0.01s".
  1786047359 call 0057 — three mutually exclusive claims under GROUND TRUTH in one prompt: "executed
  NO tests", "6 passed", and three named failures.
  1786053138 call 0142 — "unchanged since you were last shown them — you have not cleared them yet",
  four calls after the coder's own pytest printed the named test PASSED.

Five independent walkers, both runs. Each one sent the coder back into a loop it had already left.
"""
import json
import unittest

from cria import loop, probegate

GATE = probegate.SECTION_PREFIX + "probe-0" + probegate.SECTION_SUFFIX
STALE_TESTS = ("test_resolve_handle.py:44: AssertionError: None != 'addr1q8w9…'\n"
               "test_resolve_handle.py:109: AssertionError: None != 'addr1q8w9…'")
STALE_LINT = "resolve_handle.py:15:1: 'typing.Optional' imported but unused"


def _tool(text):
    return {"role": "tool", "content": text}


class ACoderRunSupersedesCriasCacheTests(unittest.TestCase):
    def test_a_green_pytest_after_the_gate_clears_stale_test_failures(self):
        msgs = [_tool(GATE + "\n" + STALE_TESTS), _tool("6 passed in 0.01s")]
        self.assertEqual(loop._checks_superseded_by_coder_run(msgs, STALE_TESTS), "0f/6p")

    def test_a_green_unittest_run_counts_too(self):
        msgs = [_tool(GATE + "\n" + STALE_TESTS), _tool("Ran 6 tests in 0.01s\n\nOK\n")]
        self.assertEqual(loop._checks_superseded_by_coder_run(msgs, STALE_TESTS), "6ran/OK")

    def test_a_still_failing_run_supersedes_nothing(self):
        msgs = [_tool(GATE + "\n" + STALE_TESTS), _tool("1 failed, 5 passed in 0.01s")]
        self.assertEqual(loop._checks_superseded_by_coder_run(msgs, STALE_TESTS), "")

    def test_a_run_BEFORE_crias_gate_is_not_newer_information(self):
        msgs = [_tool("6 passed in 0.01s"), _tool(GATE + "\n" + STALE_TESTS)]
        self.assertEqual(loop._checks_superseded_by_coder_run(msgs, STALE_TESTS), "")

    def test_a_lint_finding_is_never_cleared_by_a_passing_test_run(self):
        """A green pytest says nothing about pyflakes. Scoped on purpose."""
        msgs = [_tool(GATE + "\n" + STALE_LINT), _tool("6 passed in 0.01s")]
        self.assertEqual(loop._checks_superseded_by_coder_run(msgs, STALE_LINT), "")

    def test_the_coders_prose_cannot_clear_anything(self):
        said = [_tool(GATE + "\n" + STALE_TESTS),
                {"role": "assistant", "content": "I ran them and 6 passed in 0.01s"}]
        self.assertEqual(loop._checks_superseded_by_coder_run(said, STALE_TESTS), "")

    def test_crias_own_later_gate_is_not_read_as_a_coder_run(self):
        msgs = [_tool(GATE + "\n" + STALE_TESTS), _tool(GATE + "\n6 passed in 0.01s")]
        self.assertEqual(loop._checks_superseded_by_coder_run(msgs, STALE_TESTS), "")

    def test_no_findings_at_all_is_silent(self):
        self.assertEqual(loop._checks_superseded_by_coder_run([_tool("6 passed")], ""), "")


class TheAuthorActuallyDropsItTests(unittest.TestCase):
    """Behavioural, through author_steer: the "you have not cleared them yet" repeat must not fire
    when the coder's own run already cleared them."""

    ON_TRACK = staticmethod(
        lambda b, r: json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode())

    class _Rlog:
        def __init__(self): self.events = []
        def emit(self, name, **kw): self.events.append(name)

    def _body(self, cleared: bool):
        msgs = [{"role": "user", "content": "t"}, _tool(GATE + "\n" + STALE_TESTS)]
        msgs.append(_tool("6 passed in 0.01s" if cleared else "2 failed, 4 passed in 0.01s"))
        return {"messages": msgs, "tools": []}

    def _run(self, cleared):
        from cria.loop import GuardState, author_steer
        gs = GuardState()
        gs.steered_checks_text = STALE_TESTS
        gs.same_checks_relooked = True          # the streak's third ask: repeat/silence territory
        rlog = self._Rlog()
        out = author_steer(self.ON_TRACK, None, None, gs, self._body(cleared), rlog,
                           condition="flail", truth_text=STALE_TESTS)
        return out, rlog.events

    def test_a_cleared_suite_stops_the_you_have_not_cleared_them_repeat(self):
        out, events = self._run(cleared=True)
        self.assertIn("loop.steer_checks_stale", events)
        self.assertNotIn("unchanged since you were last shown", str(out))

    def test_a_still_failing_suite_keeps_the_repeat_exactly_as_before(self):
        out, events = self._run(cleared=False)
        self.assertNotIn("loop.steer_checks_stale", events)
        self.assertTrue(any(k in ("loop.steer_checks_reattached", "loop.steer_same_checks")
                            for k in events), events)


class WiringTests(unittest.TestCase):
    def test_the_author_drops_the_stale_truth_before_using_it(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertIn("_checks_superseded_by_coder_run", src)
        # dropped BEFORE the same-checks branch that says "you have not cleared them yet"
        self.assertLess(src.index("_checks_superseded_by_coder_run"),
                        src.index("steered_checks_text"))

    def test_it_clears_both_the_comparison_key_and_the_truth_text(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        i = src.index("_checks_superseded_by_coder_run")
        self.assertIn('checks_now, truth_text = "", ""', src[i:i + 600])


if __name__ == "__main__":
    unittest.main()
