"""A reasoned steer is optional; it must not contradict or be unrelated to the check that triggered it.

Walked on the 2026-09-04 L5 reruns: the Java steer repeatedly imported classes whose package was
itself reporting they do not exist, while the Go steer prescribed dependency downloads for a
malformed go.mod and later restored a version the resolver had rejected.  The old shared-token
question classified incidental locations such as ``go.mod:5`` and treated every missing name as a
request to supply it.  Neither asks the judgment that matters: can this action address this exact
diagnostic without relying on something the evidence disproves?
"""
import json
import unittest
from types import SimpleNamespace

from cria import loop, probegate, prompts


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, name, **kw):
        self.events.append((name, kw))


JAVA_REJECTS_TYPE = (
    "$ mvn test — Importer.java:[12,28] cannot find symbol\n"
    "  symbol: class ConcurrentSet\n"
    "  location: package java.util.concurrent"
)
GO_PARSE_ERROR = "$ go test ./... — go.mod:5: usage: require module/path v1.2.3"
GO_REJECTS_VERSION = (
    '$ go test ./... — go.mod:5: require github.com/shopspring/decimal: '
    'version "1.10.0" invalid: unknown revision 1.10.0'
)


class TheWholeActionIsJudgedTests(unittest.TestCase):
    def judged(self, directive, findings, answer):
        seen = []
        verdict = loop._diagnostic_action_verdict(
            directive, findings, set(), _Rlog(),
            lambda prompt: seen.append(prompt) or answer)
        self.assertEqual(len(seen), 1)
        return verdict, seen[0]

    def test_java_nonexistent_import_is_contradicted(self):
        verdict, prompt = self.judged(
            "Add imports for java.util.concurrent.ConcurrentSet and ConcurrentHashSet now.",
            JAVA_REJECTS_TYPE, "CONTRADICTED")
        self.assertEqual(verdict, "CONTRADICTED")
        self.assertIn("location: package java.util.concurrent", prompt)

    def test_a_real_missing_import_can_be_supported(self):
        findings = ("Importer.java:28: error: cannot find symbol\n"
                    "  symbol: class AtomicInteger\n"
                    "  location: class pipeline.Importer")
        verdict, _ = self.judged(
            "Add import java.util.concurrent.atomic.AtomicInteger.", findings, "SUPPORTED")
        self.assertEqual(verdict, "SUPPORTED")

    def test_a_download_cannot_repair_manifest_syntax(self):
        verdict, _ = self.judged(
            "Run go mod download github.com/shopspring/decimal now.",
            GO_PARSE_ERROR, "UNRELATED")
        self.assertEqual(verdict, "UNRELATED")

    def test_a_rejected_version_is_contradicted(self):
        verdict, _ = self.judged(
            "Replace the line with require github.com/shopspring/decimal v1.10.0.",
            GO_REJECTS_VERSION, "CONTRADICTED")
        self.assertEqual(verdict, "CONTRADICTED")

    def test_an_unreadable_judgment_is_not_permission_to_speak(self):
        verdict, _ = self.judged("Fix it.", GO_PARSE_ERROR, "maybe")
        self.assertEqual(verdict, "UNDECIDABLE")

    def test_without_current_findings_there_is_nothing_for_this_guard_to_judge(self):
        asked = []
        verdict = loop._diagnostic_action_verdict(
            "Write REVIEW.md.", "", set(), _Rlog(),
            lambda prompt: asked.append(prompt) or "UNRELATED")
        self.assertEqual(verdict, "SUPPORTED")
        self.assertEqual(asked, [])

    def test_the_prompt_is_a_positive_closed_judgment(self):
        text = prompts.render("steer_diagnostic_action", directive="d", findings="f",
                              refusals="(none)")
        for answer in ("SUPPORTED", "CONTRADICTED", "UNSUPPORTED", "UNRELATED"):
            self.assertIn(answer, text)
        self.assertIn("ONE word", text)
        self.assertNotIn("cria", text.lower())


class RejectedProviderNamesGetTheirOwnFocusedJudgmentsTests(unittest.TestCase):
    def test_a_provider_rejection_is_not_mistaken_for_a_missing_source_import(self):
        answers = iter(["PROVIDER_REJECTS", "PRESCRIBES"])
        got = loop._provider_rejected_name_the_steer_relies_on(
            "Add import java.util.concurrent.ConcurrentSet.", JAVA_REJECTS_TYPE,
            _Rlog(), lambda prompt: next(answers))
        self.assertEqual(got, "ConcurrentSet")

    def test_a_source_scope_gap_does_not_reject_a_real_import(self):
        findings = ("Importer.java:28: error: cannot find symbol\n"
                    "  symbol: class AtomicInteger\n"
                    "  location: class pipeline.Importer")
        calls = []
        got = loop._provider_rejected_name_the_steer_relies_on(
            "Add import java.util.concurrent.atomic.AtomicInteger.", findings,
            _Rlog(), lambda prompt: calls.append(prompt) or "SOURCE_GAP")
        self.assertEqual(got, "")
        self.assertEqual(len(calls), 1, "a source gap must not reach the relies-on-rejected question")

    def test_removing_a_rejected_name_is_allowed(self):
        answers = iter(["PROVIDER_REJECTS", "QUOTES"])
        got = loop._provider_rejected_name_the_steer_relies_on(
            "Remove java.util.concurrent.ConcurrentSet.", JAVA_REJECTS_TYPE,
            _Rlog(), lambda prompt: next(answers))
        self.assertEqual(got, "")


class TheSharedSteerGateOwnsTheJudgmentTests(unittest.TestCase):
    def session(self):
        return SimpleNamespace(last_gate_flag=GO_PARSE_ERROR, refused_names=set(),
                               fetched_pages={}, plan=None)

    def test_an_unsupported_verdict_withholds_the_whole_steer(self):
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(
            "Run go mod download github.com/shopspring/decimal now.", GO_PARSE_ERROR, rlog,
            ask=lambda system, user="": "UNRELATED", sess=self.session(), messages=[])
        self.assertIsNone(out)
        outcomes = [kw for name, kw in rlog.events if name == "loop.steer_outcome"]
        self.assertEqual(outcomes[-1]["refused_by"], "diagnostic_unrelated")

    def test_a_supported_whole_action_still_cannot_rely_on_a_provider_rejection(self):
        sess = self.session()
        sess.last_gate_flag = JAVA_REJECTS_TYPE
        def ask(system, user=""):
            if "PROVIDER_REJECTS" in system:
                return "PROVIDER_REJECTS"
            if "PRESCRIBES" in system:
                return "PRESCRIBES"
            return "SUPPORTED"
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(
            "Add import java.util.concurrent.ConcurrentSet.", JAVA_REJECTS_TYPE, rlog,
            ask=ask, sess=sess, messages=[])
        self.assertIsNone(out)
        outcomes = [kw for name, kw in rlog.events if name == "loop.steer_outcome"]
        self.assertEqual(outcomes[-1]["refused_by"], "rejected_provider")

    def test_a_write_after_the_gate_withholds_without_asking_a_judge(self):
        gate = (f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n"
                "go.mod:5: usage: require module/path v1.2.3")
        messages = [
            {"role": "tool", "content": gate},
            {"role": "assistant", "tool_calls": [{"id": "w", "type": "function",
             "function": {"name": "write_file", "arguments": json.dumps(
                 {"path": "go.mod", "content": "module x"})}}]},
        ]
        asked = []
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(
            "Run go mod download now.", GO_PARSE_ERROR, rlog,
            ask=lambda system, user="": asked.append(system) or "SUPPORTED",
            sess=self.session(), messages=messages)
        self.assertIsNone(out)
        self.assertEqual(asked, [])
        self.assertTrue(any(name == "loop.steer_diagnostic_stale" for name, _ in rlog.events))


if __name__ == "__main__":
    unittest.main()
