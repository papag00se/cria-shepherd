"""Probe artifacts once made later database tests fail in the live workspace.

The remote-harness repair moved reclamation to a delayed queue. That in turn
let a Java list_dir silently delete target/ after successful compilation. The
same no-litter contract now settles in the gate, before any coder resumes.
Tracked and preexisting content must survive, and no next gate is required.
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cria import probediscovery, probegate, proberun
from tests.gatefixture import gate_page, completed


def _repo():
    ws = tempfile.mkdtemp()
    subprocess.run(['git', 'init', '-q', ws], check=True)
    pathlib.Path(ws, 'a.py').write_text('x = 1\n')
    subprocess.run(['git', '-C', ws, 'add', '-A'], check=True)
    return ws


def _run(ws, writes=(), *, project_writes=()):
    # Only explicitly private allocations are ours. The same names in the
    # original project remain project-owned, regardless of when they appear.
    program = ('import os; from pathlib import Path\n'
               + f'for name in {writes!r}:\n'
               + " p=Path(os.environ['CTX_PROBE_AUX'])/name; p.parent.mkdir(parents=True,exist_ok=True); p.touch()\n"
               + f'for name in {project_writes!r}: Path(name).touch()\n'
               + "print('native checker output')\n")
    candidate = probediscovery.ProbeCandidate(probediscovery.ProbeKind.BuildCheck,
        [sys.executable, '-c', program], pathlib.Path(ws), 100, 100, probediscovery.ProbeCost.Cheap,
        False, False, False, 'private scratch fixture', composed_by_cria=True)
    with tempfile.TemporaryDirectory() as harness, mock.patch.object(proberun, 'select_completion_probes', return_value=[candidate]):
        plan = probegate.plan_gate(ws)
        out = subprocess.run(['sh', '-c', plan.script], capture_output=True, text=True, cwd=ws,
                             env={**os.environ, 'TMPDIR': harness}, check=True)
        outcome = probegate.interpret_gate(plan, gate_page(plan, out.stdout))
        assert plan.transport_complete and not probegate.gate_is_partial(outcome)
        assert not (pathlib.Path(plan.transport_path).parent / 'aux').exists()
    return sorted(p.name for p in pathlib.Path(ws).iterdir() if p.name != '.git')


class TheGateCleansUpAfterItselfTests(unittest.TestCase):
    def test_files_the_probes_created_are_removed(self):
        left = _run(_repo(), writes=('orders.db', 'scratch.log'))
        self.assertNotIn('orders.db', left)
        self.assertNotIn('scratch.log', left)

    def test_a_tracked_file_is_never_touched(self):
        self.assertIn('a.py', _run(_repo(), writes=('orders.db',)))

    def test_a_pre_existing_untracked_file_is_never_touched(self):
        ws = _repo()
        pathlib.Path(ws, 'draft.rb').write_text('in progress\n')
        left = _run(ws, writes=('orders.db',))
        self.assertIn('draft.rb', left)
        self.assertNotIn('orders.db', left)

    def test_a_clean_run_removes_nothing(self):
        self.assertEqual(_run(_repo()), ['a.py'])


class ItStaysPortableAndAbstainsWithoutGitTests(unittest.TestCase):
    def test_the_script_uses_no_bashisms(self):
        script = probegate.plan_gate(_repo()).script
        self.assertNotIn('<(', script)
        self.assertNotIn('[[', script)

    def test_a_workspaceless_gate_composes_no_cleanup(self):
        self.assertNotIn('__cria_pre', probegate.plan_gate('').script)

    def test_without_git_the_gate_still_runs_and_deletes_nothing(self):
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, 'a.py').write_text('x = 1\n')
        left = _run(ws, writes=('orders.db',), project_writes=('native-output.txt',))
        self.assertIn('a.py', left)
        self.assertNotIn('orders.db', left)  # Private scratch settles even without Git.
        self.assertIn('native-output.txt', left)  # No project output is claimed by the gate.


class CleanupDoesNotWaitForAnotherActionTests(unittest.TestCase):
    def test_the_same_gate_finishes_removal(self):
        ws = _repo()
        self.assertNotIn('orders.db', _run(ws, writes=('orders.db',)))
        # No second gate or lowered write is needed to finish reclamation.
        self.assertFalse(pathlib.Path(ws, 'orders.db').exists())

    def test_the_removal_is_not_an_rm(self):
        cmd = probegate.plan_gate(_repo()).script
        self.assertNotIn('rm ', cmd)
        self.assertNotIn('rm -', cmd)

    def test_a_second_gate_cannot_consume_an_old_deletion(self):
        ws = _repo()
        _run(ws, writes=('orders.db',))
        pathlib.Path(ws, 'orders.db').write_text('now owned by the coder')
        _run(ws)
        self.assertEqual(pathlib.Path(ws, 'orders.db').read_text(), 'now owned by the coder')

    def test_historical_listings_do_not_authorize_new_deletions(self):
        ws = _repo()
        pathlib.Path(ws, 'junk.txt').write_text('coder-owned now')
        plan = probegate.plan_gate(ws)
        probegate.interpret_gate(plan, gate_page(plan, '\n'.join([
            f'{probegate.SECTION_PREFIX}{probegate.LITTER_SECTION}{probegate.SECTION_SUFFIX}',
            'junk.txt', f'{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}'])))
        _run(ws)
        self.assertEqual(pathlib.Path(ws, 'junk.txt').read_text(), 'coder-owned now')


if __name__ == '__main__':
    unittest.main()
