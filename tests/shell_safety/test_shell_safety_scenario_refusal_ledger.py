"""A session's dependency refusals: parsed from each manager's own output, superseded only by an
observable exact success, serialised with provenance, rendered to the model, and used as a trigger
(never a veto) against a directive. Rows are the old refusal-event matrix (one line per manager)."""
import json

import pytest

from cria import refusalledger as rl

REFUSALS = (
    ("npm ERR! notarget No matching version found for left-pad@99.0.0.", "node", "left-pad@99.0.0"),
    ("ERR_PNPM_FETCH_404 GET https://registry.npmjs.org/no-such: no-such is not in the npm registry", "node", "no-such"),
    ("error Couldn't find package \"tiny-left-pad\" on the \"npm\" registry.", "node", "tiny-left-pad"),
    ("YN0035: │ berry-missing@npm:9.9.9: Package not found", "node", "berry-missing@npm:9.9.9"),
    ("error: package \"bun-missing\" not found", "node", "bun-missing"),
    ("ERROR: No matching distribution found for requests==99.0", "python", "requests==99.0"),
    ("Because uv-missing was not found in the package registry and your project depends on it", "python", "uv-missing"),
    ("Could not find a matching version of package poetry-missing", "python", "poetry-missing"),
    ("Because demo depends on poetry-bare which doesn't match any versions, version solving failed.",
     "python", "poetry-bare"),
    ("error: no matching package named `serde_magic` found", "rust", "serde_magic"),
    ("go: example.com/acme/mod@v9.9.9: unknown revision v9.9.9", "go", "example.com/acme/mod@v9.9.9"),
    ("module example.com/acme/mod@latest found (v1.2.3), but does not contain package example.com/acme/mod/missing",
     "go", "example.com/acme/mod/missing"),
    ("Could not find artifact org.example:missing:jar:9.9.9 in central", "jvm", "org.example:missing:jar:9.9.9"),
    ("Could not find org.example:gradle-missing:9.9.9.", "jvm", "org.example:gradle-missing:9.9.9"),
    ("error NU1101: Unable to find package Missing.Json. No packages exist with this id", "dotnet", "Missing.Json"),
    ("Could not find a matching version of package acme/missing.", "php", "acme/missing"),
    ("ERROR:  Could not find a valid gem 'countries' (= 99.0) in any repository", "ruby", "countries (= 99.0)"),
    ("Could not find gem 'eu_countries' in locally installed gems.", "ruby", "eu_countries"),
    ("** (Mix) No package with name decimal in registry (from: mix.exs)", "elixir", "decimal"),
    ("Because demo depends on missing_hex ~> 1.0 which doesn't exist, version solving failed.",
     "elixir", "missing_hex ~> 1.0"),
)

# (command, refusal text, success text, coordinate): a later exact success retires the refusal.
SUPERSEDED = (
    ("bun add left-pad@1.3.0", "No matching version found for left-pad@1.3.0", "installed left-pad@1.3.0", "left-pad@1.3.0"),
    ("pip install requests==2.32.0", "No matching distribution found for requests==2.32.0",
     "Successfully installed requests-2.32.0", "requests==2.32.0"),
    ("cargo add serde@1.0.0", "failed to select a version for the requirement `serde = \"1.0.0\"`",
     "Downloaded serde v1.0.0", "serde = \"1.0.0\""),
    ("go get example.com/acme/mod@v1.2.3", "example.com/acme/mod@v1.2.3: unknown revision v1.2.3",
     "go: added example.com/acme/mod v1.2.3", "example.com/acme/mod@v1.2.3"),
    ("dotnet add package Example.Json --version 1.2.3",
     "Package 'Example.Json 1.2.3' is not found on source(s): nuget.org", "Installed Example.Json 1.2.3", "Example.Json 1.2.3"),
    ("composer require acme/library:1.2.3", "Could not find a matching version of package acme/library.",
     "- Installing acme/library (1.2.3): Extracting archive", "acme/library"),
    ("bundle add countries --version 8.1.0", "Could not find gem 'countries'",
     "Installing countries 8.1.0\nBundle complete!", "countries"),
    ("mix deps.get", "No package with name decimal in registry", "Resolution completed in 0.02s\nNew:\n  decimal 2.1.1", "decimal"),
    ("mvn test", "Could not find artifact org.example:missing:jar:1.0 in central", "[INFO] BUILD SUCCESS", None),
    ("./gradlew test", "Could not find org.example:missing:1.0.", "BUILD SUCCESSFUL", None),
)


def result(text, cid="r1"):
    return {"role": "tool", "tool_call_id": cid, "content": text}


def call(command, cid="r1"):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function",
            "function": {"name": "exec_command", "arguments": json.dumps({"cmd": command})}}]}


@pytest.mark.parametrize("text,ecosystem,coordinate", REFUSALS)
def test_every_manager_keeps_its_raw_coordinate_and_provenance(text, ecosystem, coordinate):
    event = next(e for e in rl.refusal_events(text, source_id="c1") if e.raw_coordinate == coordinate)
    assert (event.ecosystem, event.source_id, event.outcome) == (ecosystem, "c1", rl.REFUSED)
    assert coordinate.split()[0] in event.evidence
    assert coordinate in rl.refused_names(text)


@pytest.mark.parametrize("command,refused,succeeded,coordinate", SUPERSEDED)
def test_a_later_observable_success_supersedes_the_refusal(command, refused, succeeded, coordinate):
    ledger = rl.RefusalLedger()
    ledger.observe([call(command, "f"), result(refused, "f")])
    if coordinate:
        assert coordinate in ledger.active_names()
    assert len(ledger.active()) == 1
    ledger.observe([call(command, "s"), result(succeeded, "s")])
    assert ledger.active() == []
    assert [e.outcome for e in ledger.events][-1] == rl.SUCCEEDED


def test_ledger_lifecycle_dedupe_merge_roundtrip_and_render():
    msgs = [{"role": "assistant", "content": "No matching version found for invented@9.9.9"},
            call("npm i left-pad@99.0.0", "f1"), result("No matching version found for left-pad@99.0.0", "f1"),
            {"type": "function_call", "call_id": "f2", "arguments": '{"command": ["pip", "install", "x==1"]}'},
            {"type": "function_call_output", "call_id": "f2", "output": "No matching distribution found for x==1"},
            result(""), {"role": "tool", "content": None}, "junk"]
    ledger = rl.RefusalLedger()
    ledger.observe(msgs)
    ledger.observe(msgs)                                     # a repeated transcript adds nothing
    assert ledger.active_names() == {"left-pad@99.0.0", "x==1"}     # model prose is no refusal
    assert [e.sequence for e in ledger.events] == [1, 2]
    assert ledger.events[1].command == "pip install x==1"
    # a different version does not retire an exact refusal; the same one does, a re-refusal revives it
    ledger.observe([result("installed left-pad@1.3.0", "s1")])
    assert "left-pad@99.0.0" in ledger.active_names()
    ledger.observe([result("installed left-pad@99.0.0", "s2")])
    assert ledger.active_names() == {"x==1"}
    ledger.observe([result("No matching version found for left-pad@99.0.0", "f3")])
    assert ledger.active()[-1].source_id == "f3"
    ledger.observe([result("No matching distribution found for Requests==9.0", "c1"), result("Successfully installed requests-9.0", "c2")])
    assert "Requests==9.0" not in ledger.active_names()          # package names compare case-insensitively for python
    # merge appends newer observations after the old history; serialisation keeps provenance
    newer = rl.RefusalLedger()
    newer.observe([result("Successfully installed x-1", "n1"), result("installed left-pad@99.0.0", "n2")])
    merged = ledger.merged(newer)
    assert merged.active() == [] and ledger.active() and ledger.merged(None).events == ledger.events
    back = rl.RefusalLedger.from_dict(json.loads(json.dumps(ledger.to_dict())))
    assert back.events == ledger.events
    assert rl.RefusalLedger.from_dict({"events": [{"bad": 1}]}).events == [] and rl.RefusalLedger.from_dict(None).events == []
    text = rl.render_active(ledger)
    assert "raw coordinate: x==1" in text and "tool result f2" in text and "No matching distribution found" in text
    assert rl.render_active(rl.RefusalLedger()) == ""
    assert rl.scan_messages(msgs) == {"left-pad@99.0.0", "x==1"}


def test_legacy_names_and_the_prescription_trigger():
    legacy = rl.RefusalLedger.from_legacy(["barecrate", "left-pad@1.0.0"])
    assert legacy.active_names() == {"barecrate", "left-pad@1.0.0"}
    assert "legacy compatibility record" in rl.render_active(legacy)
    assert "legacy compatibility record" in rl.render_active({"b-name"})
    assert rl.render_active(set()) == ""
    # only a trigger: bare name matched at a boundary, the longest spelling reported
    assert rl.prescribed("Remove barecrate and use the local one.", {"barecrate"}) == "barecrate"
    assert rl.prescribed("Use barecrate_extra instead", legacy) is None
    assert rl.prescribed("Install left-pad@1.0.0 now", legacy) == "left-pad@1.0.0"
    assert rl.prescribed("anything", rl.RefusalLedger()) is None and rl.prescribed("", legacy) is None
    assert rl.prescribed("Install left-pad@1.0.0", legacy.events) == "left-pad@1.0.0"
    git = rl.RefusalLedger()
    git.observe([result("fatal: repository 'https://github.com/acme/missing.git' not found", "g")])
    assert git.active()[0].coordinate == "github.com/acme/missing"
    assert rl.prescribed("clone github.com/acme/missing", git) == "github.com/acme/missing"
    assert rl.prescribed("pin x", []) is None
