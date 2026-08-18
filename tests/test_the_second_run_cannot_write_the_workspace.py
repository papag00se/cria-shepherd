"""cria ran the coder's test suite a second time, in the coder's own directory, and broke it.

Cycle 4 cell 21, `orders-api-py x nemotron-elastic`. The model's tests share one repo-relative
`orders.db` that nothing deletes, so every extra execution appends a row. Its own run reported

    assert 22.5 < 0.01

where 22.5 = abs(30.0 - 7.5) and **30.0 is four rows of 3 x 2.50** — one from the coder's run and
three from cria's: the gate's online run, the gate's network-off comparison, and `exec-intent`
picking `python3 -m pytest` as the program to observe. The coder never saw the other three and spent
the tail of the run theorising about pytest parameterisation ("might be running multiple times in a
loop within pytest (e.g. `pytest -n auto`)"). `exec-intent` was fixed then; the offline leg was not.

`sweep_litter` cannot reach this. It removes files the probes CREATED; `orders.db` already existed
and was written to again.

TWO DESIGNS WERE TRIED ON PAPER AND BOTH ARE WORSE:

- **Copy the workspace and run there.** Built and driven: 7.0 GB of copied trees before it was
  killed. `cp -a` is not cheap, and `working_dir` is not always the workspace — one leaked mirror
  held 14,262 directories of `/tmp`.
- **Run the offline leg FIRST and skip the online one when it passes.** Reads like a removal; it is
  a false-green generator. `_offline_fact`'s own docstring records the hole — a live test can SKIP
  rather than fail when the service is gone, exit code still 0 — so an offline pass does not imply
  an online pass and the authoritative run must be the unblocked one.

WHAT IS BOUNDED INSTEAD IS WHAT THE SECOND RUN CAN DO. The namespace already exists; `-m` and a
read-only re-bind of the working directory cost one syscall pair and make the whole class
impossible. A suite that genuinely writes inside its own tree now FAILS offline, which `_offline_fact`
reads as say-nothing — it speaks only when both sides are green. Silence, never a manufactured red.

MEASURED against the four seeds in the matrix that have a runnable suite — orders-api-py,
feed-pipeline-py, cart-billing-go, shipping-rates-rb — every one returns the SAME exit code
read-only as writable.
"""

import pathlib
import subprocess
import tempfile
import unittest

from cria import probediscovery, proberun


def _kernel_grants_it(root):
    return subprocess.run(["bash", "-c", proberun._netns_capable(root)],
                          capture_output=True).returncode == 0


class _Workspace:
    def __enter__(self):
        self._d = tempfile.TemporaryDirectory(prefix="suite-offline-")
        self.root = pathlib.Path(self._d.name)
        return self

    def __exit__(self, *a):
        self._d.cleanup()
        return False

    def cand(self, argv):
        return probediscovery.ProbeCandidate(
            kind=probediscovery.ProbeKind.Test, command=argv, working_dir=self.root,
            confidence=1, expected_value=1, cost=probediscovery.ProbeCost.Cheap,
            mutates_code=False, may_hang=False, may_need_services=False, reason="test")

    def run_leg(self, argv, prelude="__cria_test_ec=0; "):
        cmd = proberun.offline_probe_command(self.cand(argv), 60)
        return subprocess.run(["bash", "-c", prelude + cmd],
                              capture_output=True, text=True, timeout=120).stdout


class TheWorkspaceSurvivesTheSecondRunTests(unittest.TestCase):
    def test_the_measured_shape_a_suite_that_appends_to_a_repo_relative_file(self):
        """`orders.db`, in miniature: the 'suite' appends a row every time it runs. Under the old
        leg the file grew by one and the NEXT gate read a number the coder could not explain."""
        with _Workspace() as ws:
            db = ws.root / "orders.db"
            db.write_text("row\n")
            if not _kernel_grants_it(ws.root):
                self.skipTest("this kernel does not grant the read-only namespace")
            out = ws.run_leg(["sh", "-c", "echo row >> orders.db"])
            self.assertIn("EXIT:", out, "the leg did not run at all")
            self.assertEqual(db.read_text(), "row\n", "cria's second run appended to the coder's file")

    def test_nothing_new_is_created_either(self):
        with _Workspace() as ws:
            if not _kernel_grants_it(ws.root):
                self.skipTest("this kernel does not grant the read-only namespace")
            ws.run_leg(["sh", "-c", "echo x > fresh.txt"])
            self.assertEqual(sorted(p.name for p in ws.root.iterdir()), [])

    def test_the_write_failure_is_a_non_zero_exit_which_reads_as_SILENCE(self):
        """The whole safety argument. A write-y suite fails offline; `_offline_fact` speaks only when
        BOTH sides are green, so the outcome is no sentence — not a red the coder has to chase."""
        from cria import probegate
        with _Workspace() as ws:
            if not _kernel_grants_it(ws.root):
                self.skipTest("this kernel does not grant the read-only namespace")
            out = ws.run_leg(["sh", "-c", "echo x > fresh.txt"])
            _, code = proberun.scrape_exit(out)
            self.assertNotEqual(code, 0)
            plan = probegate.GatePlan(workspace=str(ws.root))
            plan.candidates = [ws.cand(["sh", "-c", "echo x > fresh.txt"])]
            self.assertEqual(probegate._offline_fact(
                {"probe-0": "1 passed\nEXIT:0", "offline": out}, plan), "")


class TheReadingItWasBuiltForStillWorksTests(unittest.TestCase):
    def test_a_read_only_suite_still_passes_under_the_block(self):
        with _Workspace() as ws:
            (ws.root / "data.txt").write_text("hello\n")
            if not _kernel_grants_it(ws.root):
                self.skipTest("this kernel does not grant the read-only namespace")
            self.assertIn("EXIT:0", ws.run_leg(["cat", "data.txt"]))

    def test_the_outside_world_is_still_gone(self):
        with _Workspace() as ws:
            if not _kernel_grants_it(ws.root):
                self.skipTest("this kernel does not grant the read-only namespace")
            out = ws.run_leg(["curl", "-s", "-m", "5", "-o", "/dev/null", "https://1.1.1.1"])
            self.assertIn("EXIT:", out)
            self.assertNotIn("EXIT:0", out)

    def test_loopback_is_still_up_so_a_self_hosted_mock_passes(self):
        with _Workspace() as ws:
            if not _kernel_grants_it(ws.root):
                self.skipTest("this kernel does not grant the read-only namespace")
            script = ("import socket;s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1);"
                      "socket.create_connection(s.getsockname(),timeout=4).close()")
            self.assertIn("EXIT:0", ws.run_leg(["python3", "-c", script]))

    def test_tmp_is_still_writable_which_is_where_a_well_behaved_suite_writes(self):
        with _Workspace() as ws:
            if not _kernel_grants_it(ws.root):
                self.skipTest("this kernel does not grant the read-only namespace")
            self.assertIn("EXIT:0", ws.run_leg(
                ["python3", "-c", "import tempfile,os;f=tempfile.mkstemp()[1];open(f,'w').write('x')"]))


class ThereIsNoWritableFallbackTests(unittest.TestCase):
    def test_the_capability_probe_performs_the_same_bind_the_run_performs(self):
        """#4 and #11b: an instrument cria cannot set up is one it does not read. If the probe tested
        something weaker than the run, a refused mount would silently become a writable run."""
        with _Workspace() as ws:
            cmd = proberun.offline_probe_command(ws.cand(["true"]), 60)
            self.assertIn(proberun._netns_capable(ws.root), cmd)
            self.assertIn(proberun._netns_readonly(ws.root), cmd)

    def test_a_refused_bind_prints_nothing_rather_than_running_writable(self):
        """Bare `/tmp` is the one path this kernel will not bind — a free negative case."""
        cand = probediscovery.ProbeCandidate(
            kind=probediscovery.ProbeKind.Test, command=["echo", "RAN_ANYWAY"],
            working_dir=pathlib.Path("/tmp"), confidence=1, expected_value=1,
            cost=probediscovery.ProbeCost.Cheap, mutates_code=False, may_hang=False,
            may_need_services=False, reason="test")
        if _kernel_grants_it("/tmp"):
            self.skipTest("this kernel binds /tmp; the negative case is unavailable here")
        out = subprocess.run(
            ["bash", "-c", "__cria_test_ec=0; " + proberun.offline_probe_command(cand, 30)],
            capture_output=True, text=True, timeout=60).stdout
        self.assertEqual(out.strip(), "")

    def test_a_red_online_run_still_skips_the_leg_entirely(self):
        """Unchanged: after a red run there is nothing to compare, so there is nothing to run."""
        with _Workspace() as ws:
            self.assertEqual(ws.run_leg(["echo", "RAN"], "__cria_test_ec=1; ").strip(), "")


if __name__ == "__main__":
    unittest.main()
