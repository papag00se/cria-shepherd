"""cria's own readers must see the gate text it shows the coder.

`clean_gate_output` derives the stranded-test sentence and the disk-quoted findings from the GATE
PLAN — it needs the workspace and the `untested` list. Without workspace discovery facts, native
zero-collected evidence remains visible but the authored default-convention observation cannot name
the file. Historically the same gate result instead rendered as a bare "no error-class problems".

The coder path passed the plan. The reasoner path, the work log and the compactor did not. Measured
on maple-preview 1786138747: 8 of 8 CODER-side gate blocks carried "Test code in
testAdaHandleResolver.py will not run: pytest only runs tests named test_*.py or *_test.py"; 0 of 8
reasoner-side ones did. That quoted historical wording overstated default discovery as universal
inability to execute a file; the current observation preserves the file/convention fact without
ruling out explicit-file or configured execution. cria then asked those reasoners what the coder
should do next, and got
"implement the API calls and fix the parsing logic" — the rename the coder had decided on one call
earlier was dropped and never came back. Zero tests ran for the rest of the run.
"""
import json
import os
import tempfile
import unittest

from cria import probegate
from tests.gatefixture import gate_page, completed

P, S = probegate.SECTION_PREFIX, probegate.SECTION_SUFFIX
RAW = f"{P}probe-0{S}\nno tests ran in 0.00s\nEXIT:5\n{P}git{S}\nabc123\n"


def _ws():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "testFooBar.py"), "w").write("def test_a():\n    assert 1\n")
    open(os.path.join(d, "foo.py"), "w").write("x = 1\n")
    return d


class _Rlog:
    def emit(self, *a, **k):
        pass


class TheStrandedSentenceNeedsThePlanTests(unittest.TestCase):

    def test_with_the_plan_the_file_outside_default_discovery_is_named(self):
        out = probegate.clean_gate_output(RAW, completed(probegate.plan_gate(_ws()), RAW)) or ""
        self.assertIn("testFooBar.py", out)
        native, separator, metadata = out.partition(
            "Automatic discovery observations (authored metadata, not checker output):")
        self.assertTrue(separator)
        self.assertIn("exit 5\nno tests ran in 0.00s", native)
        self.assertNotIn("testFooBar.py", native)
        self.assertIn("testFooBar.py", metadata)
        self.assertIn("outside default automatic discovery conventions for pytest", metadata)
        self.assertIn("named test_*.py or *_test.py", metadata)
        self.assertIn("does not establish whether an explicit-file invocation or a configured runner executes it", metadata)
        self.assertNotIn("report these error-class problems", out)
        self.assertNotIn("will not run", out)

    def test_without_it_the_same_gate_lacks_the_stranded_file_fact(self):
        """Pinned so the regression is visible if a call site ever drops the plan again."""
        out = probegate.clean_gate_output(RAW, completed(probegate.GatePlan(''), RAW)) or ""
        self.assertIn("exit 5", out)
        self.assertIn("no tests ran in 0.00s", out)
        self.assertNotIn("report these error-class problems", out)
        self.assertNotIn("testFooBar.py", out)


class EveryReaderGetsThePlanTests(unittest.TestCase):

    def test_no_clean_gate_results_call_omits_the_plan(self):
        import inspect
        from cria import loop, selfcompact
        for mod in (loop, selfcompact):
            src = inspect.getsource(mod)
            for line in src.splitlines():
                if "clean_gate_results(" not in line or "def clean_gate_results" in line:
                    continue
                # a one-argument call is the bug; the arg may be on the next line, so allow an
                # unclosed call and check the closing form only when it is on this line
                if line.rstrip().endswith("))") and line.count("(") == line.count(")"):
                    self.assertIn(",", line.split("clean_gate_results(", 1)[1],
                                  f"{mod.__name__}: {line.strip()}")

    def test_the_work_log_and_the_steer_author_both_take_one(self):
        import inspect
        from cria import loop
        self.assertIn("gate_plan", inspect.signature(loop._work_log).parameters)
        self.assertIn("gate_plan", inspect.signature(loop._satisfaction_evidence).parameters)

    def test_the_steer_author_reads_the_sessions_own_plan_too(self):
        """author_steer has no `gate_plan` PARAMETER — it reads `gs.gate_plan` off the session it's
        already given, so a signature check can't see this one. Drive it instead: the same
        deny(warnings) blob whose plan-aware wording this file's sibling class already proves
        (`stranded sentence needs the plan`) must reach the steer author's own composed prompt only
        when its session carries the plan."""
        from cria.loop import GuardState, author_steer

        def _run(gate_plan):
            calls = []

            def reasoner_chat(b, r):
                calls.append(b)
                return json.dumps({"choices": [{"message": {"content": "some steer"}}]}).encode()

            gs = GuardState()
            if gate_plan is not None:
                completed(gate_plan, RAW)              # the session's gate transport has arrived
            gs.gate_plan = gate_plan
            page = gate_page(gate_plan if gate_plan is not None else probegate.GatePlan(''), RAW)   # delivered by the plan's own transport
            msgs = [{"role": "user", "content": "t"}, {"role": "tool", "content": page}]
            author_steer(reasoner_chat, None, None, gs, {"messages": msgs, "tools": []},
                        _Rlog(), condition="wheel_spin")
            return json.dumps(calls[-1].get("messages", calls[-1]))

        with_plan = _run(probegate.plan_gate(_ws()))
        without_plan = _run(None)
        self.assertIn("testFooBar.py", with_plan)      # only reachable via gs.gate_plan
        self.assertNotIn("testFooBar.py", without_plan)


if __name__ == "__main__":
    unittest.main()
