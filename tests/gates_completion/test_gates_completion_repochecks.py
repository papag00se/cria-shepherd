"""Completion fails CLOSED, the repository's own commands win over cria's guess, the judge's tools only read, a checkpoint needs pace evidence."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import completionconfirmation as cc, completionredrive as redrive, execcheck, loop, probegate, verifytools
from cria.probeclassify import ProbeKind, classify_command
from suite import milestones
from gates_completion_helpers import Log, gates_completion_view  # noqa: F401


def reply(text, rounds=0, calls=None):
    msg = {"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})}
    return {"choices": [{"message": msg, "finish_reason": "stop"}], loop.ROUNDS_KEY: rounds}


def confirm(replies, surveyed=True):
    queue = iter(copy.deepcopy(replies))

    def inspect(request):
        comp = next(queue)
        pending = tuple(c["id"] for ch in comp["choices"] for c in ch["message"].get("tool_calls") or [])
        return cc.InspectionReply(comp, loop.inspection_rounds(comp), pending)
    services = cc.Services(cc.Facts(lambda root: surveyed, lambda root: ["a.py"]), inspect,
                           cc.Readers(loop._completion_text, lambda t: t, loop._consistent_word, loop.verdict_from_unclosed),
                           lambda request: "fix the gap")
    source = cc.Input("Write the implementation", "the work is complete", "/workspace", Log(), "satisfaction-confirm")
    return cc.confirm(source, services)


YES, NO = json.dumps({"consistent": True, "why": "saw it"}), json.dumps({"consistent": False, "why": "missing handler"})


@pytest.mark.parametrize("replies,surveyed,status,confirmed", [
    ([reply(YES, rounds=2)], True, cc.Status.CONFIRMED, True),
    ([reply(YES, 0), reply(YES, 0)], True, cc.Status.UNVERIFIED, False),                 # approval without looking, twice
    ([reply(YES, 0), reply(YES, 1)], True, cc.Status.CONFIRMED, True),                   # ...unless the re-ask looked
    ([reply("I think it is probably fine, hard to say", 2)], True, cc.Status.UNVERIFIED, False),    # undecidable judge
    ([reply(YES, 1, calls=[{"id": "t1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}])], True,
     cc.Status.UNVERIFIED, False),                                                        # still reaching for a tool: unfinished
    ([reply(NO, 2)], True, cc.Status.REJECTED, False),
    ([reply(json.dumps({"consistent": False, "why": "the work is complete"}), 2), reply(YES, 0)], True,
     cc.Status.UNVERIFIED, False),                                                        # a restating 'no' re-asked into an unlooked 'yes'
    ([], False, cc.Status.UNCHECKED, True),                                               # the documented bounded exit: nothing to inspect
], ids=["inspected-yes", "never-looked", "looked-on-reask", "undecidable", "pending-calls", "no", "reask-yes-unlooked", "unsurveyed-exit"])
def test_completion_fails_closed_an_undecidable_or_uninspected_judge_is_not_done(replies, surveyed, status, confirmed):
    """Run 20260801T160104 call 0038: 'I cannot see the file ... I default to DONE'. An approval needs a usable terminal
    verdict AND the judge's own inspection; the only open exit is a workspace that could not be surveyed."""
    result = confirm(replies, surveyed)
    assert (result.status, result.confirmed) == (status, confirmed)


def test_the_act_first_redrive_spends_once_per_step_and_stays_silent_when_the_coder_acted():
    """A tool-less step is steered ONCE (the flag is spent before anything can fail); activity or a spent flag is silent."""
    state, log = SimpleNamespace(leg0_nudged=False, verify_fails=3), Log()
    request = redrive.Input(redrive.Authority.STEP, 0, state, log, step=7)
    first = redrive.DEFINITION.execute(request)
    assert first and "used no tools" in first.text and state.verify_fails == 4 and state.leg0_nudged
    assert redrive.DEFINITION.execute(request) is None and [e[0] for e in log.events] == ["loop.step_incomplete"]
    busy = SimpleNamespace(leg0_nudged=False, verify_fails=0)
    assert redrive.DEFINITION.execute(redrive.Input(redrive.Authority.TASK, 3, busy, log)) is None and not busy.leg0_nudged
    spent = SimpleNamespace(leg0_nudged=False, verify_fails=0)
    with patch.object(redrive.prompts, "load", side_effect=RuntimeError("prompt unavailable")):
        with pytest.raises(RuntimeError):
            redrive.DEFINITION.execute(redrive.Input(redrive.Authority.STEP, 0, spent, log))
    assert redrive.DEFINITION.execute(redrive.Input(redrive.Authority.STEP, 0, spent, log)) is None


def test_the_repositorys_own_test_command_is_what_the_gate_runs(tmp_path):
    """package.json declares `test`; cria's own guess (`node --test`) must not replace the project's `npm run test`."""
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"node --test tests/"}}')
    (tmp_path / "index.js").write_text("module.exports = {};\n")
    tests = [c for c in probegate.plan_gate(str(tmp_path)).candidates if c.kind is probegate.probediscovery.ProbeKind.Test]
    assert [c.command for c in tests] == [["npm", "run", "test"]] and tests[0].declared_interface and not tests[0].composed_by_cria


GEM = "#!/usr/bin/env ruby\nif __FILE__ == $0\n  puts 'x'\nend\n"
PROGRAM = 'import sys\ndef go(h): return h\nif __name__ == "__main__":\n    print(go(sys.argv[1]))\n'


@pytest.mark.parametrize("files,expected", [
    ({"tool.py": PROGRAM}, ["tool.py"]),
    ({"tool.py": "def go(h):\n    return h\n"}, []),                                        # a library is not a program
    ({"lib/rates.rb": "module S\nend\n", "vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/complete.rb": GEM}, []),
    ({"src/main.rs": "fn main() {}\n", "vendor/bundle/ruby/3.2.0/gems/rake-13/lib/rake.rb": GEM}, ["src/main.rs"]),
    ({"tool.py": "def f():\n    pass\n", "target/z.py": PROGRAM, "node_modules/y.py": PROGRAM}, []),            # generated trees
    ({"test_tool.py": PROGRAM}, []),                                                          # a test file is not the program
    ({"vendor/mytool/main.go": "package main\n\nfunc main() {}\n"}, ["vendor/mytool/main.go"]),   # `vendor/` alone is a real place
])
def test_a_program_is_the_projects_own_never_a_vendored_or_generated_tree(tmp_path, files, expected):
    """shipping-rates-rb x gemma4 1787037372: cria offered minitest's own source as 'the program this project has'."""
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    assert execcheck.entrypoints(str(tmp_path)) == expected


def test_the_manifest_is_wherever_the_project_is_and_the_readme_commands_are_read(tmp_path):
    """cycle 4 cell 6: `cargo new toml-cli` put Cargo.toml one level down and cria said 'no manifest declares cargo run'."""
    (tmp_path / "toml-cli/src").mkdir(parents=True)
    (tmp_path / "toml-cli/Cargo.toml").write_text('[package]\nname = "toml-cli"\nversion = "0.1.0"\n')
    (tmp_path / "toml-cli/src/main.rs").write_text("fn main() {}\n")
    assert {"cargo run", "cargo test"} <= set(execcheck.manifest_commands(str(tmp_path)))
    (tmp_path / "README.md").write_text("# x\n\n## Run\n\n```bash\nnode lookup.js goose\n```\n")
    assert "node lookup.js goose" in execcheck.readme_commands(str(tmp_path))


@pytest.mark.parametrize("cmd,kind", [
    ("cd app && go test ./...", ProbeKind.TEST), ("cargo clippy", ProbeKind.LINT),
    ("grep -R 'go test' .", ProbeKind.UNKNOWN), ("npm install jest", ProbeKind.UNKNOWN),
])
def test_a_command_is_a_check_only_when_it_runs_one_not_when_it_mentions_one(cmd, kind):
    assert classify_command(cmd).kind is kind
    assert classify_command("pytest -q && pytest --collect-only").probe_quality >= 85      # the chain's BEST probe wins


def test_the_judges_inspection_tools_only_read_inside_the_workspace_and_state_facts(tmp_path):
    """The toolless critic passed 'write README.md' on feasibility; its tools state facts and never write or escape."""
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "escape").symlink_to("/etc")
    run = lambda name, **args: verifytools.execute(name, args, str(tmp_path))                     # noqa: E731
    assert run("read_file", path="a.py") == "def a():\n    return 1\n" and "a.py (" in run("list_dir")
    assert "DIRECTORY" in run("read_file", path="sub") and "does not exist" in run("read_file", path="nope.py")
    assert all("outside the workspace" in run("read_file", path=p) for p in ("/etc/passwd", "escape/passwd"))
    assert "not one of your tools" in run("write_file", path="x", content="y") and not (tmp_path / "x").exists()


VERDICT = dict(usefulness_percent=35, decision="continue", reason="Some useful edits.", material_changes="Worker-local map.",
               evidence=["Current source inspected."])


def test_a_new_checkpoint_accepts_a_requirement_assessment_and_rejects_a_changes_only_judgment(tmp_path, monkeypatch):
    """Small edits cannot stand in for a requirement-completion pace assessment; a legacy checkpoint stays readable."""
    monkeypatch.setattr(milestones, "ROOT", tmp_path / "reviews")
    (tmp_path / "ws").mkdir()
    (tmp_path / "task").mkdir()
    (tmp_path / "task/prompt.txt").write_text("Implement parsing and deterministic workers.")
    cp = milestones.create("run", 45, tmp_path / "ws", tmp_path / "task")
    parse = lambda v: milestones.parse_for_checkpoint(cp, json.dumps(v))                            # noqa: E731
    assert parse(VERDICT) is None
    full = {**VERDICT, "decision": "stalled", "pace_reason": "Only parsing delivered after 45 active minutes; no further interval warranted.",
            "requirements": [dict(requirement="Parsing", status="completed", evidence="Quoted input verified."),
                             dict(requirement="Workers", status="partial", evidence="Row counters race.")]}
    assert parse(full) == full
    weak = dict(requirement="Workers", status="partial", evidence="")
    bad = [{**full, "requirements": [full["requirements"][0], weak]}, {**full, "requirements": []}, {**full, "pace_reason": " "},
           {**full, "requirements": [dict(weak, evidence="x", status="done")]}]
    assert [parse(v) for v in bad] == [None] * 4
    assert milestones.parse_for_checkpoint(tmp_path, json.dumps(VERDICT)) == VERDICT
