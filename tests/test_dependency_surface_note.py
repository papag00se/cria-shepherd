"""writeproxy._note_dependency_surface — Candidate C40's delivery half.

Fails-before/passes-after plan (see ~/.cria/walk-findings/2026-09-24/invented-api-cross-cell.md
§3), driven against real capture shapes: a `go get`/`go: added` tool result, the exact shape
CALL0214 of the real cart capture (20260924T180052-01a0d614) carries. Hermetic: the module cache
gather() reads from is a throwaway temp HOME, never the real box's ~/go.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria import writeproxy


def tool(content: str, call_id: str = "c1") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


GO_SUCCESS = "go: added github.com/shopspring/decimal v1.4.0"


class _HomeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self._real_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: (self.home if p == "~" else
                                        os.path.join(self.home, p[2:]) if p.startswith("~/") else
                                        self._real_expanduser(p))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, os.path, "expanduser", self._real_expanduser)

    def _write_decimal_module(self, body=None):
        d = os.path.join(self.home, "go", "pkg", "mod",
                         "github.com", "shopspring", "decimal@v1.4.0")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "decimal.go"), "w") as fh:
            fh.write(body or (
                "package decimal\n\n"
                "func NewFromString(value string) (Decimal, error) {\n\treturn Decimal{}, nil\n}\n\n"
                "func (d Decimal) Round(places int32) Decimal {\n\treturn d\n}\n\n"
                "func (d Decimal) RoundCeil(places int32) Decimal {\n\treturn d\n}\n"))


class FailsBeforeTests(_HomeCase):
    """The precondition this candidate closes: today, nothing follows a SUCCEEDED dependency event
    with the real exported surface, even when it is sitting right there on disk."""

    def test_no_cache_present_yields_no_note_at_all(self):
        # No module written — the exact fails-before state before this candidate existed everywhere.
        out = writeproxy.represent_inbound([tool(GO_SUCCESS)])
        self.assertEqual(out[0]["content"], GO_SUCCESS)
        self.assertNotIn("THE PACKAGE MANAGER JUST RESOLVED", out[0]["content"])


class PassesAfterTests(_HomeCase):
    def test_the_real_success_line_triggers_a_real_surface_note(self):
        self._write_decimal_module()
        out = writeproxy.represent_inbound([tool(GO_SUCCESS)])
        content = out[0]["content"]
        self.assertIn(GO_SUCCESS, content)   # the resolver's own line is untouched, still present
        self.assertIn("THE PACKAGE MANAGER JUST RESOLVED github.com/shopspring/decimal v1.4.0", content)
        self.assertIn("func NewFromString(value string) (Decimal, error) {", content)
        self.assertIn("func (d Decimal) Round(places int32) Decimal {", content)

    def test_exact_resolved_coordinate_only_not_other_versions(self):
        self._write_decimal_module()
        out = writeproxy.represent_inbound([
            tool("go: added github.com/shopspring/decimal v1.3.0", call_id="c0"),
            tool(GO_SUCCESS, call_id="c1"),
        ])
        # v1.3.0 has no cache dir written -> abstains for that coordinate specifically: its own
        # resolver line is untouched, but no surface note is appended beside it.
        self.assertEqual(out[0]["content"], "go: added github.com/shopspring/decimal v1.3.0")
        self.assertIn("THE PACKAGE MANAGER JUST RESOLVED github.com/shopspring/decimal v1.4.0",
                     out[1]["content"])

    def test_no_paraphrase_every_added_line_is_a_real_source_line(self):
        body = ("package decimal\n\nfunc NewFromString(value string) (Decimal, error) {\n"
                "\treturn Decimal{}, nil\n}\n")
        self._write_decimal_module(body=body)
        out = writeproxy.represent_inbound([tool(GO_SUCCESS)])
        added = out[0]["content"][len(GO_SUCCESS):]
        for line in body.splitlines():
            stripped = line.rstrip()
            if stripped.startswith("func "):
                self.assertIn(stripped, added)
        # cria's own wording is allowed, but nothing masquerading as a decimal.go line that isn't one.
        self.assertNotIn("Quantize", added)
        self.assertNotIn("RoundingModeCeiling", added)


class AbstainTests(_HomeCase):
    def test_cache_absent_never_blocks_or_alters_the_real_result(self):
        out = writeproxy.represent_inbound([tool(GO_SUCCESS)])
        self.assertEqual(out[0]["content"], GO_SUCCESS)

    def test_unsupported_ecosystem_jvm_never_fires(self):
        d = os.path.join(self.home, ".m2", "repository", "org", "apache", "commons",
                         "commons-csv", "1.10.0")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "commons-csv-1.10.0.jar"), "w").close()
        # jvm has no _SUCCESSES pattern in refusalledger, so this line never even parses as an event
        # -- but assert the end-to-end behaviour (no note) regardless of why.
        out = writeproxy.represent_inbound([tool("BUILD SUCCESS")])
        self.assertNotIn("THE PACKAGE MANAGER JUST RESOLVED", out[0]["content"])


class IdempotencyTests(_HomeCase):
    def test_a_second_request_replaying_the_same_annotated_history_does_not_double_append(self):
        self._write_decimal_module()
        first = writeproxy.represent_inbound([tool(GO_SUCCESS)])
        annotated = first[0]["content"]
        # The harness echoes cria's own annotated content back on the next request, verbatim.
        second = writeproxy.represent_inbound([tool(annotated)])
        self.assertEqual(second[0]["content"], annotated)
        self.assertEqual(second[0]["content"].count("THE PACKAGE MANAGER JUST RESOLVED"), 1)

    def test_a_second_distinct_success_message_for_the_same_coordinate_is_not_re_annotated(self):
        self._write_decimal_module()
        first = writeproxy.represent_inbound([tool(GO_SUCCESS, call_id="c1")])
        annotated = first[0]["content"]
        combined = writeproxy.represent_inbound([
            tool(annotated, call_id="c1"),
            tool(GO_SUCCESS, call_id="c2"),   # a distinct later tool result naming the SAME coordinate
        ])
        self.assertEqual(combined[1]["content"], GO_SUCCESS)   # second occurrence: no note added


class OverflowTests(_HomeCase):
    def test_a_surface_too_large_to_inline_spills_to_the_real_path_not_a_silent_cut(self):
        # Many real exported functions -> exceeds the inline budget.
        lines = "\n\n".join(
            f"func Member{i}(x int) int {{\n\treturn x\n}}" for i in range(400))
        self._write_decimal_module(body="package decimal\n\n" + lines + "\n")
        out = writeproxy.represent_inbound([tool(GO_SUCCESS)])
        content = out[0]["content"]
        self.assertIn("is larger than fits here", content)
        self.assertIn("members found", content)
        # The real path is named so the coder can read the rest itself -- never a claim of "no more".
        self.assertIn(os.path.join(self.home, "go", "pkg", "mod", "github.com", "shopspring",
                                   "decimal@v1.4.0"), content)


if __name__ == "__main__":
    unittest.main()
