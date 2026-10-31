"""A private cleanup allocation is not authority to replace native TMPDIR."""
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest import mock

import pytest

from cria import probediscovery, probegate, proberun
from tests.gatefixture import gate_page, completed


@pytest.mark.parametrize('inherited', [True, False])
def test_gate_keeps_native_tmpdir_and_only_reclaims_its_private_aux(tmp_path, monkeypatch, inherited):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    harness = tmp_path / 'harness'
    harness.mkdir()
    service = socket.socket(socket.AF_UNIX)
    try:
        if inherited:
            service.bind(str(harness / 'service.sock'))
            service.listen(2)
            monkeypatch.setenv('TMPDIR', str(harness))
        else:
            monkeypatch.delenv('TMPDIR', raising=False)
        program = (
            'import os,socket; from pathlib import Path\n'
            + ('s=socket.socket(socket.AF_UNIX); s.connect(os.path.join(os.environ["TMPDIR"],"service.sock")); s.close()\n'
               if inherited else 'assert "TMPDIR" not in os.environ\n')
            + 'assert Path.cwd()==Path(' + repr(str(workspace)) + ')\n'
            + 'Path("native-output.txt").write_text("project owned")\n'
            + 'if "CTX_PROBE_AUX" in os.environ: Path(os.environ["CTX_PROBE_AUX"],"scratch").write_text("private")\n'
            + 'print("native environment preserved")\n'
        )
        native = subprocess.run([sys.executable, '-c', program], cwd=workspace,
                                capture_output=True, text=True)
        assert native.returncode == 0, native.stderr
        candidate = probediscovery.ProbeCandidate(
            probediscovery.ProbeKind.BuildCheck, [sys.executable, '-c', program],
            workspace, 100, 100, probediscovery.ProbeCost.Cheap,
            False, False, False, 'native environment control', composed_by_cria=False)
        with mock.patch.object(proberun, 'select_completion_probes', return_value=[candidate]):
            plan = probegate.plan_gate(str(workspace))
        result = subprocess.run(['sh', '-c', plan.script], cwd=workspace,
                                capture_output=True, text=True, env=dict(os.environ))
        assert probegate.ingest_transport(plan, result.stdout) == 'complete'
        decoded = probegate.transported_result(plan)
        outcome = probegate.interpret_gate(plan, gate_page(plan, decoded))
        assert plan.transport_complete and not outcome.scope_unknown
        assert native.stdout.strip() in decoded, decoded
        assert not (Path(plan.transport_path).parent / 'aux').exists()
        assert (workspace / 'native-output.txt').read_text() == 'project owned'
        if inherited:
            assert (harness / 'service.sock').is_socket()
    finally:
        service.close()
