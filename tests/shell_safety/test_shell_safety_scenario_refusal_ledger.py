"""A session's dependency refusals: parsed from each manager's own output, superseded only by an
observable exact success, serialised with provenance, rendered to the model, and used as a trigger
(never a veto) against a directive. Rows are the old refusal-event matrix (one line per manager)."""
import json
import random
import time

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

# the comparison fields (package, version) a refusal is judged by; every other row is a bare name with no version
PARTS = {"left-pad@99.0.0": ("left-pad", "99.0.0"), "berry-missing@npm:9.9.9": ("berry-missing", "9.9.9"), "requests==99.0": ("requests", "99.0"),
         "example.com/acme/mod@v9.9.9": ("example.com/acme/mod", "9.9.9"), "org.example:missing:jar:9.9.9": ("org.example:missing:jar", "9.9.9"),
         "org.example:gradle-missing:9.9.9": ("org.example:gradle-missing", "9.9.9"), "countries (= 99.0)": ("countries", "99.0"),
         "missing_hex ~> 1.0": ("missing_hex", "~>1.0")}

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
    assert (event.package, event.version) == PARTS.get(coordinate, (coordinate, ""))     # what a later success is compared against
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


# Four of the 59 patterns begin with a bare coordinate (a character-class run before the resolver's sentence). A regex
# engine tries every start position, and each try runs to the end of the run: one 8,000-character base64 gate-transport
# result in a real captured request cost 1.5 s of CPU, every request, because the ledger re-reads the whole history.
RUN_PATTERNS = [p for p in rl._REFUSALS if p.starts is not None]


def _cpu(fn, repeats=3):
    """The least CPU seconds of ``repeats`` runs (the minimum is the run the machine did not disturb)."""
    best = float("inf")
    for _ in range(repeats):
        start = time.process_time()
        fn()
        best = min(best, time.process_time() - start)
    return best


@pytest.mark.parametrize("alphabet", ["abcdefghijklmnopqrstuvwxyz0123456789", "ab.", "ab-_"])
def test_a_long_run_of_name_characters_costs_linear_not_quadratic_cpu(alphabet):
    """The same text four times longer must cost about four times the CPU, never sixteen (ornith1.5_9b / Java overnight:
    the 8,520-byte base64 result of a gate transport took 1.5 s per request in ``refusalledger._events``)."""
    rng = random.Random(14)
    short, long_ = (("".join(rng.choice(alphabet) for _ in range(n))) for n in (3000, 12000))
    cost_short = _cpu(lambda: rl.refusal_events(short) + rl.success_events(short))
    cost_long = _cpu(lambda: rl.refusal_events(long_) + rl.success_events(long_))
    assert cost_long < 8 * max(cost_short, 0.002), (cost_short, cost_long)       # linear ~4x; quadratic ~16x


JOINED = (
    ("_x is not in npm registry-_x is not in npm registry", ["_x", "_x"]),                 # the next one starts after a "-" the run began with
    ("foo is not in npm registryfoo is not in npm registry", ["foo", "foo"]),             # a resumption that begins mid-run, right after the last match
    ("a: Package not found-b: Package not found", ["a", "b"]),
    ("x/y@v1: unknown revisiona/b@v2: unknown revision", ["x/y@v1", "a/b@v2"]),
    ("g:a:jar:1 was not foundh:b:jar:2 was not found", ["g:a:jar:1", "h:b:jar:2"]),
    ("...-.foo is not in the npm registry", ["foo"]),                                      # leading punctuation is not part of a name
    ("see xyz@types/node is not in npm registry", ["@types/node"]),                        # a scoped name begins at its "@", mid-run
    ("@@@@ is not in npm registry", []),
)


@pytest.mark.parametrize("text,coordinates", JOINED)
def test_skipping_start_positions_never_changes_what_the_resolver_sentences_yield(text, coordinates):
    assert [e.raw_coordinate for e in rl.refusal_events(text)] == coordinates


def test_the_linear_scan_returns_exactly_what_the_plain_regex_scan_returns():
    """The independent oracle is ``re``'s own ``finditer``: same spans and same groups on random texts made of the
    pieces these sentences are made of, joined with and without separators."""
    rng = random.Random(7)
    pieces = ["foo", "a", "Bar9", "_x", "a.b", "1.2.3", ".", "-", "--", "@", "@scope", "/", ":", " ", "\n", "é",
              " is not in the npm registry", ": Package not found", " was not found", "unknown revision", ":jar:",
              "v1.2", "@v1.2", "@npm:", "g:a:jar:1.0", "x/y@v1.0.0", "IS NOT IN NPM REGISTRY"]
    texts = ["".join(rng.choice(pieces) for _ in range(rng.randint(1, 14))) for _ in range(2500)]
    hits = 0
    for text in texts:
        for pattern in RUN_PATTERNS:
            plain = [(m.start(), m.end(), m.groupdict()) for m in pattern.regex.finditer(text)]
            assert plain == [(m.start(), m.end(), m.groupdict()) for m in rl._finditer(pattern, text)], (text, pattern.regex.pattern)
            hits += bool(plain)
    assert hits > 150        # the generator reaches real matches, not only misses


def test_reading_the_same_transcript_again_never_retires_a_refusal_newer_than_an_old_success():
    """The ledger re-reads the whole history on every request. A run of a command that SUCCEEDED early, then the same command
    REFUSED a coordinate later: the second read applied the early success marker to the newer refusal (a success copy gets the
    newest sequence), so the refusal of the newest run vanished from the ledger one request after it was recorded."""
    history = [call("pip install -r req.txt", "a"), result("Successfully installed foo-1.0", "a"),
               call("pip install -r req.txt", "b"), result("ERROR: No matching distribution found for y==2", "b")]
    ledger = rl.RefusalLedger()
    for _ in range(3):
        ledger.observe(history)
        assert ledger.active_names() == {"y==2"}
    ledger.observe(history + [call("pip install -r req.txt", "c"), result("Successfully installed y-2.0", "c")])
    assert ledger.active_names() == set()            # a success AFTER the refusal still retires it


def _growing_transcript():
    """An append-only history as the loop re-sends it: refusals, a rerun that retires one, an anonymous result, a repeat."""
    refusal = "ERROR: No matching distribution found for y==2"
    anon = {"role": "tool", "content": "No matching version found for left-pad@99.0.0"}
    steps = [
        [call("pip install -r req.txt", "a"), result("Successfully installed foo-1.0", "a")],
        [call("pip install -r req.txt", "b"), result(refusal, "b")],
        [anon, {"role": "assistant", "content": "thinking"}],
        [call("npm i left-pad@99.0.0", "c"), result("No matching version found for left-pad@99.0.0", "c")],
        [call("pip install -r req.txt", "d"), result("Successfully installed y-2.0", "d")],
        [call("pip install -r req.txt", "e"), result(refusal, "e")],
    ]
    history = []
    for step in steps:
        history = history + step
        yield list(history)


def test_a_memoised_re_read_gives_exactly_the_ledger_a_full_re_parse_gives_and_scans_nothing_again(monkeypatch):
    """Every request re-reads the whole history (about 44 ms of regex per 45 tool results, ~90% of the re-read); the parse of a
    result is a pure function of (id, command, text), so only a NEW result may be scanned. The ledger must stay byte-identical."""
    scans = []
    real = rl._events
    monkeypatch.setattr(rl, "_events", lambda *a, **k: scans.append(a[0]) or real(*a, **k))
    memoised, fresh = rl.RefusalLedger(), rl.RefusalLedger()
    for history in _growing_transcript():
        fresh._parsed = {}                                  # force the full parse the old code did every time
        memoised.observe(history)
        fresh.observe(history)
        assert json.dumps(memoised.to_dict(), sort_keys=True) == json.dumps(fresh.to_dict(), sort_keys=True)
        assert memoised.active_names() == fresh.active_names()
    scans.clear()
    before = json.dumps(memoised.to_dict(), sort_keys=True)
    memoised.observe(history)                                # the same request again: nothing is scanned
    assert scans == [] and json.dumps(memoised.to_dict(), sort_keys=True) == before
    assert memoised.active_names() == {"y==2", "left-pad@99.0.0"}
    # a result whose text changed (a rewritten stub under the same id) is parsed afresh; a dropped prefix is forgotten
    edited = [m if m.get("tool_call_id") != "c" else result("rewritten, no refusal here", "c") for m in history]
    memoised.observe(edited)
    assert scans and all("rewritten" in t for t in scans)
    assert len(memoised._parsed) == sum(1 for m in edited if m.get("role") == "tool")
    memoised.observe(history[-2:])
    assert len(memoised._parsed) == 1
