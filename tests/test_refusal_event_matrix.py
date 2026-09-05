"""Dependency refusals are session facts, not an eternal set of punctuation-shaped names.

The event unit is intentionally package-manager complete.  Each row below is the manager's own
output: deterministic code preserves that exact coordinate and its provenance; only the reasoner
may decide what a later directive means.  A newer, exact success can supersede the refusal when the
tool output makes that success observable.
"""
import json
import unittest
from types import SimpleNamespace

from cria import loop
from cria import refusalledger as rl


REFUSALS = (
    # JavaScript / TypeScript package managers, including bare-name failures.
    ("npm", "npm ERR! notarget No matching version found for left-pad@99.0.0.",
     "node", "left-pad@99.0.0"),
    ("pnpm", "ERR_PNPM_FETCH_404 GET https://registry.npmjs.org/no-such: no-such is not in the npm registry",
     "node", "no-such"),
    ("yarn", "error Couldn't find package \"tiny-left-pad\" on the \"npm\" registry.",
     "node", "tiny-left-pad"),
    ("yarn-berry", "YN0035: │ berry-missing@npm:9.9.9: Package not found",
     "node", "berry-missing@npm:9.9.9"),
    ("bun", "error: package \"bun-missing\" not found", "node", "bun-missing"),

    # Python package managers, including bare-name failures.
    ("pip", "ERROR: No matching distribution found for requests==99.0", "python", "requests==99.0"),
    ("uv", "Because uv-missing was not found in the package registry and your project depends on it",
     "python", "uv-missing"),
    ("poetry", "Could not find a matching version of package poetry-missing", "python", "poetry-missing"),
    ("poetry-solver", "Because demo depends on poetry-bare which doesn't match any versions, "
     "version solving failed.", "python", "poetry-bare"),

    ("cargo", "error: no matching package named `serde_magic` found", "rust", "serde_magic"),
    ("go", "go: example.com/acme/mod@v9.9.9: unknown revision v9.9.9",
     "go", "example.com/acme/mod@v9.9.9"),
    ("go-package", "module example.com/acme/mod@latest found (v1.2.3), but does not contain "
     "package example.com/acme/mod/missing", "go", "example.com/acme/mod/missing"),
    ("maven", "Could not find artifact org.example:missing:jar:9.9.9 in central",
     "jvm", "org.example:missing:jar:9.9.9"),
    ("gradle", "Could not find org.example:gradle-missing:9.9.9.",
     "jvm", "org.example:gradle-missing:9.9.9"),
    ("nuget", "error NU1101: Unable to find package Missing.Json. No packages exist with this id",
     "dotnet", "Missing.Json"),
    ("composer", "Could not find a matching version of package acme/missing.",
     "php", "acme/missing"),
    ("gem", "ERROR:  Could not find a valid gem 'countries' (= 99.0) in any repository",
     "ruby", "countries (= 99.0)"),
    ("bundler", "Could not find gem 'eu_countries' in locally installed gems.",
     "ruby", "eu_countries"),
    ("hex", "** (Mix) No package with name decimal in registry (from: mix.exs)",
     "elixir", "decimal"),
    ("mix-solver", "Because demo depends on missing_hex ~> 1.0 which doesn't exist, "
     "version solving failed.", "elixir", "missing_hex ~> 1.0"),
)


def result(text, call_id="r1"):
    return {"role": "tool", "tool_call_id": call_id, "content": text}


def call(command, call_id="r1"):
    return {"role": "assistant", "tool_calls": [{
        "id": call_id, "type": "function",
        "function": {"name": "exec_command", "arguments": json.dumps({"cmd": command})},
    }]}


class EverySupportedDependencyEcosystemProducesAnEventTests(unittest.TestCase):
    def test_every_manager_preserves_the_raw_coordinate(self):
        for manager, text, ecosystem, coordinate in REFUSALS:
            with self.subTest(manager=manager):
                events = rl.refusal_events(text, source_id=f"call-{manager}")
                self.assertTrue(events)
                event = next(e for e in events if e.raw_coordinate == coordinate)
                self.assertEqual(event.ecosystem, ecosystem)
                self.assertEqual(event.source_id, f"call-{manager}")
                self.assertIn(coordinate.split()[0], event.evidence)

    def test_legacy_name_extraction_includes_bare_names(self):
        for manager, text, _ecosystem, coordinate in REFUSALS:
            with self.subTest(manager=manager):
                self.assertIn(coordinate, rl.refused_names(text))

    def test_prose_is_still_not_ground_truth(self):
        messages = [
            {"role": "assistant", "content": "No matching version found for invented@9.9.9"},
            result("No matching version found for real@9.9.9"),
        ]
        ledger = rl.RefusalLedger()
        ledger.observe(messages)
        self.assertEqual(ledger.active_names(), {"real@9.9.9"})


class RefusalFreshnessAndSupersessionTests(unittest.TestCase):
    CASES = (
        ("bun add left-pad@1.3.0", "No matching version found for left-pad@1.3.0",
         "installed left-pad@1.3.0", "left-pad@1.3.0"),
        ("pip install requests==2.32.0", "No matching distribution found for requests==2.32.0",
         "Successfully installed requests-2.32.0", "requests==2.32.0"),
        ("cargo add serde@1.0.0", "failed to select a version for the requirement `serde = \"1.0.0\"`",
         "Downloaded serde v1.0.0", "serde = \"1.0.0\""),
        ("go get example.com/acme/mod@v1.2.3", "example.com/acme/mod@v1.2.3: unknown revision v1.2.3",
         "go: added example.com/acme/mod v1.2.3", "example.com/acme/mod@v1.2.3"),
        ("dotnet add package Example.Json --version 1.2.3",
         "Package 'Example.Json 1.2.3' is not found on source(s): nuget.org",
         "Installed Example.Json 1.2.3", "Example.Json 1.2.3"),
        ("composer require acme/library:1.2.3", "Could not find a matching version of package acme/library.",
         "- Installing acme/library (1.2.3): Extracting archive", "acme/library"),
        ("bundle add countries --version 8.1.0", "Could not find gem 'countries'",
         "Installing countries 8.1.0\nBundle complete!", "countries"),
        ("mix deps.get", "No package with name decimal in registry",
         "Resolution completed in 0.02s\nNew:\n  decimal 2.1.1", "decimal"),
    )

    def test_a_later_exact_success_supersedes_each_observable_refusal(self):
        for i, (command, refused, succeeded, coordinate) in enumerate(self.CASES):
            with self.subTest(command=command):
                ledger = rl.RefusalLedger()
                ledger.observe([call(command, f"f{i}"), result(refused, f"f{i}")])
                self.assertIn(coordinate, ledger.active_names())
                refusal = ledger.active()[0]
                ledger.observe([call(command, f"s{i}"), result(succeeded, f"s{i}")])
                self.assertEqual(ledger.active(), [])
                self.assertTrue(any(e.outcome == "succeeded" and e.sequence > refusal.sequence
                                    for e in ledger.events))

    def test_a_successful_exact_rerun_supersedes_a_maven_refusal(self):
        command = "mvn test"
        ledger = rl.RefusalLedger()
        ledger.observe([call(command, "m1"), result(
            "Could not find artifact org.example:missing:jar:1.0 in central", "m1")])
        ledger.observe([call(command, "m2"), result("[INFO] BUILD SUCCESS", "m2")])
        self.assertEqual(ledger.active(), [])

    def test_a_successful_gradle_wrapper_rerun_supersedes_its_refusal(self):
        command = "./gradlew test"
        ledger = rl.RefusalLedger()
        ledger.observe([call(command, "g1"), result(
            "Could not find org.example:missing:1.0.", "g1")])
        ledger.observe([call(command, "g2"), result("BUILD SUCCESSFUL", "g2")])
        self.assertEqual(ledger.active(), [])

    def test_a_poetry_install_line_supersedes_its_bare_solver_refusal(self):
        ledger = rl.RefusalLedger()
        ledger.observe([result(
            "Because demo depends on pendulum which doesn't match any versions, version solving failed.",
            "p1")])
        ledger.observe([result("  - Installing pendulum (3.0.0)", "p2")])
        self.assertEqual(ledger.active(), [])

    def test_a_different_version_does_not_supersede_an_exact_refusal(self):
        ledger = rl.RefusalLedger()
        ledger.observe([result("No matching version found for left-pad@99.0.0", "f")])
        ledger.observe([result("installed left-pad@1.3.0", "s")])
        self.assertEqual(ledger.active_names(), {"left-pad@99.0.0"})

    def test_a_new_refusal_after_success_is_current_again(self):
        ledger = rl.RefusalLedger()
        ledger.observe([result("No matching version found for left-pad@1.3.0", "f1")])
        ledger.observe([result("installed left-pad@1.3.0", "s")])
        ledger.observe([result("No matching version found for left-pad@1.3.0", "f2")])
        self.assertEqual(ledger.active_names(), {"left-pad@1.3.0"})
        self.assertEqual(ledger.active()[0].source_id, "f2")


class CompatibilityAndWholeActionWiringTests(unittest.TestCase):
    def test_old_set_callers_still_trigger_but_never_veto(self):
        self.assertEqual(rl.prescribed("Remove barecrate and use the local implementation.", {"barecrate"}),
                         "barecrate")

    def test_session_tracks_structured_events_and_compatibility_names(self):
        sess = loop.GuardState()
        loop._track_refused_names(sess, [result("no matching package named `barecrate` found")])
        self.assertEqual(sess.refused_names, {"barecrate"})
        self.assertIsInstance(sess.refusal_events, rl.RefusalLedger)
        self.assertEqual(sess.refusal_events.active()[0].raw_coordinate, "barecrate")

    def test_session_serialization_retains_raw_provenance_and_freshness(self):
        from cria.plan import Plan, PlanItem

        sess = loop.PlanSession(plan=Plan(id="p", task="t", created="now",
                                         items=[PlanItem("work")]))
        loop._track_refused_names(sess, [result(
            "fatal: repository 'https://github.com/acme/missing.git' not found", "raw-1")])
        encoded = loop._session_to_dict(sess)
        restored = loop._session_from_dict(encoded)
        self.assertIsNotNone(restored)
        event = restored.refusal_events.active()[0]
        self.assertEqual(event.raw_coordinate, "https://github.com/acme/missing.git")
        self.assertEqual(event.coordinate, "github.com/acme/missing")
        self.assertEqual(event.source_id, "raw-1")
        self.assertEqual(event.sequence, 1)

    def test_legacy_serialized_name_sets_still_restore(self):
        from cria.plan import Plan, PlanItem

        sess = loop.PlanSession(plan=Plan(id="p", task="t", created="now",
                                         items=[PlanItem("work")]),
                                refused_names={"legacy.example/pkg"})
        encoded = loop._session_to_dict(sess)
        encoded.pop("refusal_events")
        restored = loop._session_from_dict(encoded)
        self.assertEqual(restored.refused_names, {"legacy.example/pkg"})

    def test_a_stable_session_replacement_keeps_order_and_newer_success(self):
        from cria.plan import Plan, PlanItem

        def session():
            return loop.PlanSession(plan=Plan(id="p", task="t", created="now",
                                              items=[PlanItem("work")]))

        old = session()
        loop._track_refused_names(old, [result("No matching version found for left-pad@1.3.0", "old")])
        newer = session()
        loop._track_refused_names(newer, [result("installed left-pad@1.3.0", "new")])
        store = loop.LoopStore()
        store.put("sid:conversation", old)
        store.put("sid:conversation", newer)
        merged = store.get("sid:conversation")
        self.assertEqual(merged.refused_names, set())
        self.assertEqual([event.outcome for event in merged.refusal_events.events],
                         ["refused", "succeeded"])

    def test_refusal_only_path_asks_once_with_the_normal_two_argument_adapter(self):
        ledger = rl.RefusalLedger()
        ledger.observe([result("No matching version found for left-pad@99.0.0")])
        sess = SimpleNamespace(last_gate_flag="", refused_names=ledger.active_names(),
                               refusal_events=ledger, fetched_pages={}, plan=None)
        calls = []
        out = loop._grounded_steer_or_none(
            "Remove left-pad@99.0.0 and use the existing local helper.", "task evidence", _Rlog(),
            ask=lambda system, user="": calls.append((system, user)) or "SUPPORTED",
            sess=sess, messages=[])
        self.assertEqual(out, "Remove left-pad@99.0.0 and use the existing local helper.")
        self.assertEqual(len(calls), 1)
        self.assertIn("left-pad@99.0.0", calls[0][0])

    def test_refusal_only_contradiction_is_also_exactly_one_whole_action_judgment(self):
        ledger = rl.RefusalLedger()
        ledger.observe([result("No matching version found for left-pad@99.0.0")])
        sess = SimpleNamespace(last_gate_flag="", refused_names=ledger.active_names(),
                               refusal_events=ledger, fetched_pages={}, plan=None)
        calls = []
        out = loop._grounded_steer_or_none(
            "Install left-pad@99.0.0.", "task evidence", _Rlog(),
            ask=lambda system, user="": calls.append((system, user)) or "CONTRADICTED",
            sess=sess, messages=[])
        self.assertIsNone(out)
        self.assertEqual(len(calls), 1)

    def test_legacy_refusal_helper_accepts_the_refusal_only_one_argument_ask(self):
        calls = []
        got = loop._prescribes_a_refused_coordinate(
            "Use left-pad@99.0.0.", {"left-pad@99.0.0"}, _Rlog(),
            ask=lambda system: calls.append(system) or "PRESCRIBES")
        self.assertEqual(got, "left-pad@99.0.0")
        self.assertEqual(len(calls), 1)

    def test_legacy_refusal_helper_does_not_reinterpret_an_internal_type_error(self):
        def ask(_system):
            raise TypeError("provider failed")

        with self.assertRaisesRegex(TypeError, "provider failed"):
            loop._prescribes_a_refused_coordinate(
                "Use left-pad@99.0.0.", {"left-pad@99.0.0"}, _Rlog(), ask=ask)

    def test_exact_matching_is_only_a_trigger_not_a_lexical_veto(self):
        ledger = rl.RefusalLedger()
        ledger.observe([result("No matching version found for left-pad@99.0.0")])
        sess = SimpleNamespace(last_gate_flag="", refused_names=ledger.active_names(),
                               refusal_events=ledger, fetched_pages={}, plan=None)
        directive = "Remove left-pad@99.0.0 and keep the local helper."
        self.assertEqual(loop._grounded_steer_or_none(
            directive, "task evidence", _Rlog(), ask=None, sess=sess, messages=[]), directive)


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


if __name__ == "__main__":
    unittest.main()
