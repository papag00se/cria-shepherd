"""The gate script cria hands the harness must contain NOTHING destructive.

Two incidents, two modules, same cause. The Codex sandbox rejects an exec whose script contains a
destructive verb — "rm -f style commands are not permitted" — and rejects the WHOLE script, not the
offending line. writeproxy hit it first: an `rm -f` clearing a spill file broke every web_search, and
the model read the refusal as an API-permissions problem and hallucinated an endpoint. probegate hit
it second: an `rm -rf` cleaning up after the probes killed EVERY gate, in every language, for a whole
24-cell battery arm — silently, because a refused exec returns no section markers and that is
indistinguishable from "no gate was composed".

So: no destructive shell verb may make the sandbox reject the whole gate. Owned reclamation is a
bounded Python program run by the HARNESS inside that same gate, never server-side deletion or a
hidden mutation on the next coder tool. Refusals must remain visible, not disable a subsystem silently.
"""

import os

import pytest

from cria import probegate
from test_gate_cleanup_finishes_before_coder_resumes import allocated_resource, private_aux, finish_cleanup


# The verbs the sandbox rejects. Matched as whole words so `format!` / `performance` can't trip it.
DESTRUCTIVE = ("rm", "rmdir", "shred", "unlink", "mkfs", "dd")


def _destructive_lines(script: str) -> list[str]:
    import re
    pat = re.compile(r"(?:^|[\s;&|(`])(" + "|".join(DESTRUCTIVE) + r")(?=\s)")
    return [ln for ln in script.splitlines() if pat.search(ln)]


def _workspace(tmp_path, files: dict) -> str:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return str(tmp_path)


@pytest.mark.parametrize("files", [
    {"lib/shipping/rates.rb": "module Shipping\nend\n", "test/test_rates.rb": "require 'minitest/autorun'\n",
     "Rakefile": "task :test\n"},
    {"app.py": "x = 1\n", "tests/test_app.py": "def test_x():\n    assert True\n",
     "pyproject.toml": "[project]\nname='x'\nversion='0'\n"},
    {"pom.xml": "<project><artifactId>x</artifactId></project>", "src/main/java/A.java": "class A {}"},
    {"Cargo.toml": "[package]\nname='x'\nversion='0.1.0'\n", "src/main.rs": "fn main() {}"},
    {"go.mod": "module x\n", "main.go": "package main\nfunc main() {}"},
    {"package.json": '{"name":"x"}', "index.js": "console.log(1)"},
])
def test_no_destructive_verb_in_any_composed_gate(tmp_path, files):
    script = probegate.plan_gate(_workspace(tmp_path, files)).script
    assert script, "the gate composed nothing at all"
    assert not _destructive_lines(script), (
        "cria composed a destructive command for the harness — the Codex sandbox rejects the WHOLE "
        f"script and the gate then abstains silently:\n" + "\n".join(_destructive_lines(script)))


def test_the_minimal_gate_is_read_only_too():
    """Unknown workspace → a git-only gate. It has no cleanup to do and must still carry no verb."""
    assert not _destructive_lines(probegate.plan_gate("").script)


def test_litter_bookkeeping_never_reaches_the_model(tmp_path):
    """Positive resource allocation is private plumbing, never the coder's work."""
    plan = probegate.plan_gate(_workspace(tmp_path, {"app.py": "x = 1\n"}))
    assert f'gate launch {plan.transport_id}' in plan.script
    shown = probegate._strip_gate_plumbing(plan.script)
    for value in (plan.transport_id, '__cria_launch_error', '_gate_aux_cleanup', 'namespace_identity_changed'):
        assert value not in shown


def test_a_refused_gate_is_loud_not_silent():
    """No markers + a refusal phrase → ran=False AND the harness's reason, so it can be logged."""
    refused = (
        'error=exec_command failed for `/bin/bash -lc \'cd /tmp/ws || exit 97 ...\'`: CreateProcess '
        '{ message: "Rejected(\\"... rejected: rm -f style commands are not permitted. '
        'Use a safer approach\\")" }'
    )
    out = probegate.interpret_gate(probegate.GatePlan(workspace="/tmp/ws"), refused)
    assert out.ran is False
    assert out.refused, "a sandbox rejection must carry its reason, not vanish"
    assert "not permitted" in out.refused


def test_an_ordinary_empty_result_is_not_called_a_refusal():
    """Silence over noise: a gate that simply returned nothing is not a policy rejection."""
    for text in ("", "   ", "Process exited with code 0"):
        out = probegate.interpret_gate(probegate.GatePlan(workspace="/tmp/ws"), text)
        assert out.ran is False
        assert out.refused == "", f"invented a refusal from {text!r}"


def test_a_gate_that_ran_and_failed_is_not_a_refusal(tmp_path):
    """`ran` is decided by the sections, and refusal is only consulted when nothing came back."""
    ws = _workspace(tmp_path, {"app.py": "x = 1\n"})
    plan = probegate.plan_gate(ws)
    body = f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nboom: permission denied\nEXIT:1\n"
    out = probegate.interpret_gate(plan, body)
    assert out.ran is True
    assert out.refused == ""


def _litter_sections(paths):
    return {probegate.LITTER_SECTION: "\n".join(paths)}


def _sweep_and_remove(resource):
    """The actual harness cleanup consumes an allocated capability, never names."""
    (removed, failed), _ = finish_cleanup(resource)
    assert failed == []
    return removed


def test_sweep_removes_exactly_what_the_probes_created(tmp_path):
    ws = tmp_path
    (ws / "kept.py").write_text("x = 1\n")
    (ws / 'orders.db').write_text('project data')
    resource = allocated_resource(tmp_path)
    aux = private_aux(resource)
    (aux / 'orders.db').write_text('owned scratch')
    (aux / 'artifacts').mkdir()
    (aux / 'artifacts/out.bin').write_text('owned scratch')
    removed = _sweep_and_remove(resource)
    assert set(removed) == {'aux/orders.db', 'aux/artifacts/out.bin', 'aux/artifacts/', 'aux/'}
    assert not aux.exists()
    assert (ws / 'orders.db').read_text() == 'project data'
    assert (ws / 'kept.py').exists()


def test_sweep_cannot_escape_the_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "precious.txt"
    outside.write_text("do not delete")
    paths = ['../precious.txt', str(outside), 'sub/../../precious.txt']
    assert probegate.sweep_litter(probegate.GatePlan(workspace=str(ws)), _litter_sections(paths)) == []
    resource = allocated_resource(ws)
    assert _sweep_and_remove(resource) == ['aux/']
    assert outside.read_text() == 'do not delete'


def test_sweep_unlinks_a_symlink_rather_than_following_it(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "target.txt"
    outside.write_text("keep me")
    resource = allocated_resource(ws)
    link = private_aux(resource) / 'link.txt'
    project_link = ws / 'link.txt'
    try:
        os.symlink(outside, link)
        os.symlink(outside, project_link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    removed = _sweep_and_remove(resource)
    assert set(removed) == {'aux/link.txt', 'aux/'}
    assert not link.exists() and not link.is_symlink()
    assert project_link.is_symlink()
    assert outside.read_text() == 'keep me'


def test_sweep_abstains_without_a_workspace_or_a_section(tmp_path):
    assert probegate.sweep_litter(probegate.GatePlan(workspace=""), _litter_sections(["x"])) == []
    assert probegate.sweep_litter(probegate.GatePlan(workspace=str(tmp_path)), {}) == []
    assert probegate.sweep_litter(probegate.GatePlan(workspace=str(tmp_path)),
                                  _litter_sections([""])) == []
