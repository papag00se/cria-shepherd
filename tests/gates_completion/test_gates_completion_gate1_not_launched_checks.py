"""A check that never started (the tool is not installed) is named as a fact and never erases the checks that did run.

Fixture: the REAL gate a ling3.0_tiny cell produced for the `handles-cli-node` task (captured 2026-10-09, session 20261009T104436, call
inbound-003e0202: three syntax probes clean, `eslint` exit 127, the project's own `npm run test` exit 127 because jest is not
installed). Only the section prefix is the current one (the capture predates it); every other byte is the capture's."""
import subprocess

import pytest

from cria import probediscovery, probegate, proberun, wsview
from cria.probediscovery import ProbeKind as K
from gates_completion_helpers import P, S, cand, clean, deliver, new_plan, sec  # noqa: F401  (autouse view fixture)

REAL_NODE_GATE = (
    f"{P}probe-0{S}\n\nEXIT:0\n{P}probe-1{S}\n\nEXIT:0\n{P}probe-2{S}\n\nEXIT:0\n"
    f"{P}probe-3{S}\ntimeout: failed to run command \u2018eslint\u2019: No such file or directory\n\nEXIT:127\n"
    f"{P}probe-4{S}\n\n> handle-lookup@0.1.0 test\n> jest\n\nsh: line 1: jest: command not found\n\nEXIT:127\n"
    f"{P}offline{S}\n{P}litter{S}\n\n")


def node_plan(workspace="/ws"):
    direct = lambda c: setattr(c, "composed_by_cria", True) or c       # noqa: E731  (the floor probes are launched directly)
    eslint = ["eslint", "--no-eslintrc", "--no-ignore", "--format", "compact", f"{workspace}/lookup.js"]
    return new_plan(workspace=workspace, candidates=[
        direct(cand(["node", "--check", f"{workspace}/lookup.js"], K.SyntaxCheck)),
        direct(cand(["node", "--check", f"{workspace}/test/lookup.test.js"], K.SyntaxCheck)),
        direct(cand(["python3", "-c", "import json", f"{workspace}/package.json"], K.SyntaxCheck)),
        direct(cand(eslint, K.Lint)),
        cand(["npm", "run", "test"], K.Test)])


def test_the_real_node_gate_keeps_its_clean_syntax_results_and_names_what_did_not_run():
    out = clean(REAL_NODE_GATE, node_plan())
    assert "no usable result" not in out and out.startswith("⟦ctx:checks⟧ Recorded checker results")
    assert out.count("— exit 0") == 3 and "node --check /ws/lookup.js — exit 0" in out
    assert "`eslint` is not installed (the shell could not find it, exit 127)" in out
    # a declared script that exits 127 because a tool INSIDE it is missing is not an uninstalled `npm`; its own words ride instead
    assert "`npm` is not installed" not in out
    assert "`npm run test` did not run to a result (exit 127" in out and "sh: line 1: jest: command not found" in out


@pytest.mark.parametrize("raw,cands", [
    (sec(0, "sh: pytest: not found", 127), [cand(["pytest"])]),
    (sec(0, "", 126) + sec(1, "", 127), [cand(["./gradlew", "test"]), cand(["eslint"], K.Lint)]),
], ids=["only-a-missing-test-runner", "nothing-started"])
def test_when_nothing_ran_to_a_result_only_the_neutral_placeholder_is_said_and_history_still_drops_it(raw, cands):
    """Nothing was lost, so nothing is named: the placeholder alone is what `_is_no_signal_check` removes from history with its call."""
    out = clean(raw, new_plan(candidates=cands))
    assert probegate._is_no_signal_check(out) and "not installed" not in out and "Recorded checker results" not in out


def test_a_real_finding_beside_a_missing_tool_is_not_buried_by_it():
    out = clean(sec(0, "a.py:3: NameError: name 'q' is not defined", 1) + sec(1, "", 127),
                new_plan(candidates=[cand(["pyflakes"], K.Lint), cand(["eslint"], K.Lint)]))
    assert "a.py:3: NameError" in out and "did not run to a result (exit 127" in out


def _surveyed_view(root, sess):
    view = wsview.View(str(root), sess)
    out = subprocess.run(["bash", "-c", wsview.survey_command(sess, cd=str(root))], capture_output=True, text=True, timeout=60).stdout
    assert wsview.apply_survey(view, wsview.strip_survey(out)[1])
    return view


def test_the_gates_own_exit_127_of_a_direct_tool_is_remembered_by_the_next_request_and_rechecked_by_its_survey(tmp_path):
    """Every request builds a fresh view and a gate's result is read once, so what one request learned of the coder's shell
    used to be gone for the next: the same absent eslint was composed (and failed) at every gate."""
    sess = "gate1-127"
    (tmp_path / "lookup.js").write_text("console.log(1)\n")
    (tmp_path / "package.json").write_text('{"scripts": {"test": "node --test"}}\n')
    argv = lambda: [c.command[0] for c in proberun.select_completion_probes(str(tmp_path))]    # noqa: E731
    token = wsview.bind(_surveyed_view(tmp_path, sess))     # the tree only: no program has been asked about yet
    try:
        assert wsview.current().program("eslint") is None and "eslint" in argv()    # unsure keeps the probe
        probegate.interpret_gate(deliver(node_plan(str(tmp_path)), REAL_NODE_GATE), "")
        view = wsview.current()
        assert view.program("eslint") == "" and view.program("npm") is None and view.program("node") is None
        assert "eslint" not in argv()
        wsview.unbind(token)
        wsview._PROG_MISSES.pop(sess, None)                  # (this survey must not ask the real machine: the test owns the answers)
        token = wsview.bind(_surveyed_view(tmp_path, sess))  # the NEXT request: a brand-new view
        assert wsview.current().program("eslint") == "" and "eslint" not in argv()
        assert "eslint" in wsview.pending(sess)[1]            # ...and its next survey checks again: the coder may have installed it
    finally:
        wsview.unbind(token)
        wsview._PROG_CACHE.pop(sess, None), wsview._PROG_MISSES.pop(sess, None)


def test_a_declared_node_test_script_is_a_gate_probe_once_its_body_is_known(tmp_path):
    """The project's own `npm test` (`node --test`) rides the periodic and the completion gate through the ordinary ecosystem
    discovery; it is only absent while package.json's body has not reached the view."""
    sess = "gate1-npm"
    (tmp_path / "lookup.js").write_text("console.log(1)\n")
    (tmp_path / "package.json").write_text('{"scripts": {"test": "node --test"}}\n')
    token = wsview.bind(_surveyed_view(tmp_path, sess))
    try:
        argv = lambda: [c.command[:3] for c in proberun.select_completion_probes(str(tmp_path))]    # noqa: E731
        assert ["npm", "run", "test"] not in argv()                   # asked for, not delivered yet
        assert wsview.pending(sess)[0] == [str(tmp_path / "package.json")] or "package.json" in str(wsview.pending(sess)[0])
        wsview.unbind(token)
        token = wsview.bind(_surveyed_view(tmp_path, sess))           # the next survey carried the body
        assert ["npm", "run", "test"] in argv()
    finally:
        wsview.unbind(token)
        for store in (wsview._BODY_CACHE, wsview._BODY_MISSES):
            store.clear()


def test_a_survey_the_tree_refuses_still_answers_the_programs_nobody_had_answered():
    def survey(progs):
        return (f"{wsview._SEC_PREFIX}meta{wsview._SEC_SUFFIX}\nroot\t/ws\n{wsview._SEC_PREFIX}tree{wsview._SEC_SUFFIX}\nF\t1\t2\ta.js\n"
                f"{wsview._SEC_PREFIX}progs{wsview._SEC_SUFFIX}\n{progs}\n{wsview._SEC_PREFIX}done{wsview._SEC_SUFFIX}\nentries\t1\ncomplete\t1\n"
                f"{wsview.SURVEY_CLOSE}\n")
    import base64
    b64 = lambda t: base64.b64encode(t.encode()).decode()                                # noqa: E731
    v = wsview.View("/ws", "gate1")
    first, later = v.begin_observation(), v.begin_observation()
    assert wsview.from_observation(later, wsview.apply_survey, v, survey(f"{b64('eslint')}\t\n{b64('node')}\t{b64('node')}"))
    assert v.program("eslint") == "" and v.program("node") == "node"
    # the older survey rides a later-overtaken call: its TREE is refused, its newer-than-nothing answers are kept, an answered name is not replaced
    assert not wsview.from_observation(first, wsview.apply_survey, v, survey(f"{b64('node')}\t\n{b64('npm')}\t{b64('npm')}"))
    assert wsview.last_reject()["reason"] == "overtaken-observation"
    assert v.program("npm") == "npm" and v.program("node") == "node"
    v.observation_pending(True)                                   # a write is still open: the tree is refused the same way, the programs are not
    assert not wsview.apply_survey(v, survey(f"{b64('cargo')}\t")) and wsview.last_reject()["reason"] == "unresolved-observation"
    assert v.program("cargo") == ""
