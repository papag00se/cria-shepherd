"""The gate ran the repo's tests in the LIVE workspace and left their artifacts behind.

A test that writes — a database file, a fixture, an output artifact — leaves that behind for the
NEXT gate to trip over, and cria then reports a failure it manufactured itself under the strongest
header it has. Measured on the six-language battery: a leftover `orders.db` from one gate run made
the next run's schema assertions fail, and the coder was sent to debug cria's own litter.

Principle 7 already says cria never pollutes the user's workspace; running the tests there was the
one place it did. The cleanup is bounded and needs no per-language knowledge: record the untracked
files before the probes, remove exactly the ones that appeared during them. Tracked files are never
touched, pre-existing untracked files are never touched, and with no git the whole thing abstains.

The REMOVAL IS NOT AN `rm`, and it is not cria's own unlink either. The Codex sandbox rejects an
exec containing `rm` and rejects the WHOLE script, so a cleanup written that way silently killed
every gate in every language (tests/test_gate_script_is_read_only.py). cria unlinking the files
itself fixed that and introduced a quieter fault: the workspace is on the HARNESS's filesystem, so
off a shared box the unlink is a silent no-op and the litter stays for the next gate to blame on the
coder. So the paths are QUEUED when the gate is interpreted and removed by a bounded `python3` leg
at the head of the NEXT gate script — before its own untracked-file baseline is taken.

These run the whole loop: compose, run it in a real `sh`, interpret, compose again, run the removal.
"""
import pathlib
import subprocess
import tempfile
import unittest

from cria import probegate


def _repo():
    ws = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", ws], check=True)
    pathlib.Path(ws, "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", ws, "add", "-A"], check=True)
    subprocess.run(["git", "-C", ws, "-c", "user.email=a@b", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    return ws


def _run(ws, writes=()):
    """The whole loop: compose → a real shell runs it → cria interprets and queues the litter →
    compose the NEXT gate → a real shell runs its removal leg.

    `writes` fakes a test that leaves artifacts behind, created partway through the script."""
    plan = probegate.plan_gate(ws)
    script = plan.script
    if writes:
        script = script.replace("__cria_post=$(git",
                                "touch " + " ".join(writes) + "\n__cria_post=$(git", 1)
    out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, cwd=ws)
    probegate.interpret_gate(plan, out.stdout)
    removal = probegate.litter_removal_command(ws)
    if removal:
        subprocess.run(["sh", "-c", removal], capture_output=True, text=True, cwd=ws)
    return sorted(p.name for p in pathlib.Path(ws).iterdir() if p.name != ".git")


class TheGateCleansUpAfterItselfTests(unittest.TestCase):
    def test_files_the_probes_created_are_removed(self):
        left = _run(_repo(), writes=("orders.db", "scratch.log"))
        self.assertNotIn("orders.db", left)
        self.assertNotIn("scratch.log", left)

    def test_a_tracked_file_is_never_touched(self):
        self.assertIn("a.py", _run(_repo(), writes=("orders.db",)))

    def test_a_pre_existing_untracked_file_is_never_touched(self):
        """The coder's own work-in-progress is untracked too. Only what the GATE created goes."""
        ws = _repo()
        pathlib.Path(ws, "draft.rb").write_text("in progress\n")
        left = _run(ws, writes=("orders.db",))
        self.assertIn("draft.rb", left)
        self.assertNotIn("orders.db", left)

    def test_a_clean_run_removes_nothing(self):
        self.assertEqual(_run(_repo()), ["a.py"])


class ItStaysPortableAndAbstainsWithoutGitTests(unittest.TestCase):
    def test_the_script_uses_no_bashisms(self):
        """The harness's shell is not guaranteed to be bash; a bashism would fail silently and
        leave the litter behind."""
        script = probegate.plan_gate(_repo()).script
        self.assertNotIn("<(", script)
        self.assertNotIn("[[", script)

    def test_a_workspaceless_gate_composes_no_cleanup(self):
        self.assertNotIn("__cria_pre", probegate.plan_gate("").script)

    def test_without_git_the_gate_still_runs_and_deletes_nothing(self):
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "a.py").write_text("x = 1\n")
        left = _run(ws, writes=("orders.db",))
        self.assertIn("a.py", left)
        self.assertIn("orders.db", left)      # no git → no signal → abstain rather than guess




class TheRemovalRidesOnTheNextGateTests(unittest.TestCase):
    """The queue is only useful if the next composed script actually carries it, at the head — a
    removal after the pre-probe `git status` would put cria's own litter into this gate's baseline
    and hand it back as the coder's."""

    def test_the_next_script_carries_the_removal_before_its_own_baseline(self):
        ws = _repo()
        plan = probegate.plan_gate(ws)
        probegate.interpret_gate(plan, "\n".join([
            f"{probegate.SECTION_PREFIX}{probegate.LITTER_SECTION}{probegate.SECTION_SUFFIX}",
            "orders.db",
            f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}",
        ]))
        script = probegate.plan_gate(ws).script
        self.assertIn("orders.db", script)
        self.assertLess(script.index("orders.db"), script.index("__cria_pre=$(git"))

    def test_the_removal_is_not_an_rm(self):
        """The sandbox rejects the whole exec when it sees one, which killed every gate once."""
        ws = _repo()
        plan = probegate.plan_gate(ws)
        probegate.interpret_gate(plan, "\n".join([
            f"{probegate.SECTION_PREFIX}{probegate.LITTER_SECTION}{probegate.SECTION_SUFFIX}",
            "orders.db",
            f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}",
        ]))
        cmd = probegate.litter_removal_command(ws)
        self.assertTrue(cmd)
        self.assertNotIn("rm ", cmd)
        self.assertNotIn("rm -", cmd)

    def test_the_queue_is_consumed_once(self):
        ws = _repo()
        plan = probegate.plan_gate(ws)
        probegate.interpret_gate(plan, "\n".join([
            f"{probegate.SECTION_PREFIX}{probegate.LITTER_SECTION}{probegate.SECTION_SUFFIX}",
            "orders.db",
            f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}",
        ]))
        self.assertTrue(probegate.litter_removal_command(ws))
        self.assertEqual(probegate.litter_removal_command(ws), "")


class TheLitterGoesOutEvenWithNoNextGateTests(unittest.TestCase):
    """The queue is only safe if something is guaranteed to carry it. A gate is not: a run can end,
    or simply never gate again, and then cria's own probe artifacts sit in the user's repo for good
    — which is principle 7 broken by the mechanism that exists to keep it."""

    def _queue(self, ws):
        plan = probegate.plan_gate(ws)
        probegate.interpret_gate(plan, "\n".join([
            f"{probegate.SECTION_PREFIX}{probegate.LITTER_SECTION}{probegate.SECTION_SUFFIX}",
            "junk.txt",
            f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}",
        ]))

    def test_the_next_lowered_write_carries_it(self):
        import json

        from cria import writeproxy, wsview
        ws = _repo()
        pathlib.Path(ws, "junk.txt").write_text("cria's own probe artifact")
        self._queue(ws)
        self.addCleanup(wsview.unbind, wsview.bind(wsview.View(ws, "s-lit")))
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": "t1", "type": "function",
             "function": {"name": "write_file",
                          "arguments": json.dumps({"path": "a.py", "content": "x = 1\n"})}}]}}]}
        writeproxy.translate_outbound(comp, {"name": "shell", "parameters": {}},
                                      injected={"write_file"}, session="s-lit", workspace_root=ws)
        cmd = json.loads(comp["choices"][0]["message"]["tool_calls"][0]
                         ["function"]["arguments"])["command"]
        subprocess.run(["sh", "-c", cmd], cwd=ws, capture_output=True)
        self.assertFalse(pathlib.Path(ws, "junk.txt").exists())
        self.assertTrue(pathlib.Path(ws, "a.py").exists(), "the coder's own write must still land")


if __name__ == "__main__":
    unittest.main()
