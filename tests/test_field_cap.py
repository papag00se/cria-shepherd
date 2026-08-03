"""The per-endpoint field cap was 30. MEASURED across the whole capture corpus on 2026-08-03: a
capped list appears in 12,599 prompts, and the number of fields it hides is only ever 4 or 6 —
those are the only two values that occur.

So cria was paying "the coder cannot tell whether this field exists" across 12,599 prompts to save
at most six field names. On the Ada Handles spec the whole difference is 80 characters.

The cap's own comment states the cost: "a coder looking for a field that exists but sits past the
cap concludes the API doesn't return it — and guesses."

Second cost, uncounted until now: absence from a TRUNCATED list is not evidence a field is missing,
so cria's own ledger-contradiction check must abstain on every capped endpoint.
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
