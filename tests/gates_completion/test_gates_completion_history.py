"""The coder's history carries cria's gate only as the probes it could retype and the checker's findings - never the script, never a call it did not make."""
import json

import pytest

from cria import probegate
from gates_completion_helpers import gates_completion_view, coder_call, gate_turn, page, sec, text_of  # noqa: F401

TREES = {
    "rust": {"Cargo.toml": '[package]\nname = "toml-cli"\nversion = "0.1.0"\n', "src/main.rs": "fn main() {}\n"},
    "java": {"pom.xml": "<project><artifactId>x</artifactId></project>", "src/main/java/App.java": "class App {}\n"},
    "node": {"package.json": '{"name":"x","scripts":{"test":"jest"}}', "index.js": "module.exports = {};\n"},
    "python": {"pyproject.toml": "[project]\nname='x'\nversion='0'\n", "test_orders.py": "def test_a():\n    assert True\n"},
}


@pytest.mark.parametrize("lang", TREES)
def test_the_coder_re_reads_only_the_probe_commands_never_cria_composed_programs_or_plumbing(tmp_path, lang):
    """rust-toml-cli x nemotron-elastic 1787160046: cria's own `python3 -c ... import tomli` manifest check rode into the coder's
    context; it put `tomli` in Cargo.toml and scored 0/4. Only the stamped retypable probes are shown, never programs or plumbing."""
    for rel, body in TREES[lang].items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    plan = probegate.plan_gate(str(tmp_path))
    msgs = [{"role": "user", "content": "build it"}, *coder_call("g", plan.script, page(plan, sec(0, "no problems reported")))]
    call = probegate.clean_gate_results(msgs)[1]["tool_calls"][0]["function"]["arguments"]
    shown = json.loads(call)["cmd"]
    assert shown.strip() == "\n".join(" ".join(c.command) for c in plan.candidates if not c.composed_by_cria)
    for leak in ("python3 -c", "tomli", "ElementTree", "json.load", "<<", "cria", plan.transport_id, "__cria_", "$"):
        assert leak not in shown


def test_a_gate_cria_composed_whole_leaves_its_result_as_a_plain_message_not_an_answer_to_an_empty_call():
    """188 prompts showed an empty `exec_command` with cria's answer under it (every probe a cria-composed `node --check`): the
    call is dropped and the result kept whole as a user message (no orphan `tool`); a retypable probe keeps its true pair."""
    roles = lambda probes: [m.get("role") for m in probegate.clean_gate_results(  # noqa: E731
        [{"role": "user", "content": "build"}, *gate_turn("g1", sec(0, "ok"), probes=probes)])]
    assert roles(()) == ["user", "user"]
    assert roles(("pytest -q",)) == ["user", "assistant", "tool"]
    out = probegate.clean_gate_results([{"role": "user", "content": "build"}, *gate_turn("g1", sec(0, "ok"), probes=())])
    assert probegate.CHECKS_MARKER in out[-1]["content"]


def test_unstamped_or_coder_authored_marker_text_is_never_rewritten_and_an_unstamped_gate_shows_nothing():
    """A coder may print or quote internal marker text without losing a byte; a command with no (or a cut) stamp is
    treated as not-the-coder's (silence), never guessed."""
    quoted = f"quoted {probegate.SECTION_PREFIX}probe-0___ and {probegate.CHECKS_MARKER} literally"
    msgs = [{"role": "user", "content": "x"}, *coder_call("c1", "echo ordinary", quoted), *coder_call("c2", "echo ordinary", quoted)]
    assert probegate.clean_gate_results(msgs, linked_only=True) == msgs
    assert probegate.gate_probes_of("cd /ws && pytest -q") is None and probegate.gate_probes_of(probegate._gate_sentinel(["pytest"])[:-6]) is None


def test_automatic_checks_reach_a_reasoner_as_observations_never_as_the_coders_actions():
    """ornith1.5_9b / Java run1792297428/0055: a steer credited the synthetic gate's green `mvn` as the coder's progress after
    its inspections were refused. Gate call/result become labelled observations; the coder's own identical command stays its own."""
    msgs = [{"role": "user", "content": "Repair the processor."},
            *coder_call("refused", "inspect dependency", "Not run: inspection was refused."),
            *gate_turn("auto", sec(0, "checker exact evidence"), probes=("mvn -q compile",)),
            *coder_call("mine", "mvn -q compile", "The coder chosen check returned this.")]
    out = probegate.check_evidence_messages(msgs)
    seen = text_of(out)
    assert [m["content"] for m in out if m["role"] == "observation"][0].startswith("Automatic check requested (not an action chosen by the coder)")
    assert "Automatic check result (not an action chosen by the coder)" in seen and "checker exact evidence" in seen
    own = [m for m in out if m.get("tool_calls") and m["tool_calls"][0]["id"] == "mine"]
    assert len(own) == 1 and "The coder chosen check returned this." in seen
    assert "___CRIA_GATE_" not in seen and "__cria_" not in seen
