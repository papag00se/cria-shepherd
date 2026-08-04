"""The per-endpoint TOP-LEVEL field cap was 30. MEASURED across the whole capture corpus on
2026-08-03: a capped list appears in 12,599 prompt captures, and the number of fields hidden is only
ever 4 or 6 — those are the only two values that occur.

So cria was paying "the coder cannot tell whether this field exists" to save at most six field
names. On the Ada Handles spec the whole difference is 80 characters.

WHAT THIS CLEARS. The `+4` occurrences are this cap, on `GET /handles/{handle}` — the endpoint
whose missing tail cost a run — and raising it to 40 clears them. The `+6` occurrences came from a
SEPARATE hardcoded nested cap of 8 in `_schema_field_summary`'s `_depth == 0` recursion, on
`stats{…}` inside `GET /health`. That one was first left alone, on the ground that the six fields
it hid were node-sync internals no task had needed — a judgement about one api and one task family,
which is not a test cria is entitled to apply. The nested list now shares `FIELD_CAP`: one cap, one
rule, both levels, and the real spec renders with no elision anywhere for 137 characters.

The cap's own comment states the cost: "a coder looking for a field that exists but sits past the
cap concludes the API doesn't return it — and guesses."

Second cost: absence from a TRUNCATED list is not evidence a field is missing, so any
ledger-contradiction check must abstain on every capped endpoint.
"""
import json
import os
import unittest

from cria import webfetch as wf

SPEC = ("/home/jesse/.cria/suite/ada-handles_gemma4_codex_poff_1785390466"
        "/workspace/tmp/read-only/api.handle.me_openapi.json")


class FieldCapTests(unittest.TestCase):
    def test_the_cap_is_a_named_constant(self):
        self.assertGreaterEqual(wf.FIELD_CAP, 40)

    def test_the_cap_still_exists_and_still_discloses(self):
        # A pathological spec must still be bounded, and a SILENT slice is what is forbidden.
        sch = {"type": "object",
               "properties": {f"f{i}": {"type": "string"} for i in range(wf.FIELD_CAP + 5)}}
        out = wf._schema_field_summary(sch, {}, wf.FIELD_CAP)
        self.assertTrue(out[-1].startswith("…+"))
        self.assertIn("more field(s)", out[-1])

    @unittest.skipUnless(os.path.exists(SPEC), "captured spec not present")
    def test_the_endpoint_that_cost_a_run_now_renders_complete(self):
        lines = wf._endpoint_response_fields(json.load(open(SPEC)))
        handles = next(l for l in lines if l.startswith("GET /handles/{handle}"))
        self.assertNotIn("more field(s)", handles)
        # …and the absence is now trustworthy: cria can say this endpoint does NOT return it.
        self.assertNotIn("total_handles", handles)

    @unittest.skipUnless(os.path.exists(SPEC), "captured spec not present")
    def test_the_cost_of_raising_it_is_negligible(self):
        spec = json.load(open(SPEC))
        wide = "\n".join(wf._endpoint_response_fields(spec))
        narrow = "\n".join(wf._endpoint_response_fields(spec, max_fields=30))
        self.assertLess(len(wide) - len(narrow), 400)

    def _health_spec(self, n_nested):
        return {"openapi": "3.0.0", "paths": {"/health": {"get": {"responses": {"200": {"content": {
            "application/json": {"schema": {"type": "object", "properties": {
                "status": {"type": "string"},
                "stats": {"type": "object",
                          "properties": {f"n{i}": {"type": "integer"} for i in range(n_nested)}},
            }}}}}}}}}}

    def test_a_NESTED_object_obeys_the_SAME_cap(self):
        """The nested list used a hardcoded `8` while the top level used `FIELD_CAP`, so the very
        defect this constant exists to prevent stayed live one level down.

        It was left that way on a measurement that turned out to be the wrong test: across the whole
        capture corpus exactly one object is ever nested-capped — `stats` inside `GET /health` — and
        the six fields it hides are node-sync internals (`current_block_hash`, `tip_block_hash`,
        `utxo_schema_version`, `index_schema_version`, `lock_lambdas`, `estimated_sync_time`) that
        no deliverable has needed. But "no task needed these particular fields" is a judgement about
        ONE api and ONE task family, and cria is meant to be agnostic to both. The rule the cap's
        own comment states does not mention relevance: a field that exists must never read as
        absent. One cap, one rule, both levels."""
        line = wf._endpoint_response_fields(self._health_spec(14))[0]
        self.assertNotIn("more field(s)", line)
        self.assertIn("n13(integer)", line)          # the last field the old `8` hid
        self.assertIn("stats{", line)
        self.assertTrue(line.rstrip().endswith("}"), line)

    def test_a_NESTED_object_is_still_BOUNDED_and_still_discloses(self):
        """Sharing the cap is not removing it. A pathological nested object is still cut at
        FIELD_CAP, and the cut is still disclosed — inside the braces, where it describes the
        object it applies to rather than the endpoint."""
        line = wf._endpoint_response_fields(self._health_spec(wf.FIELD_CAP + 3))[0]
        self.assertIn("…+3 more field(s)}", line)
        self.assertIn("stats{", line)

    @unittest.skipUnless(os.path.exists(SPEC), "captured spec not present")
    def test_the_real_spec_now_renders_with_no_elision_at_all(self):
        """The end state on the document that cost a run: not one `…+N more field(s)` anywhere,
        at either level. Measured cost of the nested half: 137 characters."""
        text = "\n".join(wf._endpoint_response_fields(json.load(open(SPEC))))
        self.assertNotIn("more field(s)", text)
