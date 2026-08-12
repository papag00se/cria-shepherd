"""The gate ran the repo's tests in the LIVE workspace and left their artifacts behind.

A test that writes — a database file, a fixture, an output artifact — leaves that behind for the
NEXT gate to trip over, and cria then reports a failure it manufactured itself under the strongest
header it has. Measured on the six-language battery: a leftover `orders.db` from one gate run made
the next run's schema assertions fail, and the coder was sent to debug cria's own litter.

Principle 7 already says cria never pollutes the user's workspace; running the tests there was the
one place it did. The cleanup is bounded and needs no per-language knowledge: record the untracked
files before the probes, delete exactly the ones that appeared during them. Tracked files are never
touched, pre-existing untracked files are never touched, and with no git the whole thing abstains.
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
    """Run the real gate script, with a fake 'test' that creates `writes` partway through."""
    script = probegate.plan_gate(ws).script
    if writes:
        script = script.replace("__cria_post=$(git",
                                "touch " + " ".join(writes) + "\n__cria_post=$(git", 1)
    subprocess.run(["sh", "-c", script], capture_output=True, text=True, cwd=ws)
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


if __name__ == "__main__":
    unittest.main()
