"""The response-shape render must survive every reader that consumed the old one-line render — fed by the REAL fact producer.

The 2026-08-07 response-shape format (operator's design: a `returns:` head + a ```ts fence of `name?: type;` lines) replaced the
one-line `GET /x → f1, f2{a,b}` render — and three readers were still keyed on `→`. From that day until 2026-08-08 the durable
fetch ledger carried routes and ZERO response fields, the judges' sources block promised "response fields it defines:" and
delivered nothing after the colon (walked, mellum2 1786196176 calls 0021/0028 — one judge hallucinated the missing fields and ruled
partially blind), and the phantom-field steer guard was blind.

The facts are now typed at the producer (`fetchfacts.Shape`: head, route, parameter notes, generated body, field names), so no reader
scans a rendered grammar at all. Four stations, one real spec, end to end with only the network replaced: real parse and render →
typed `rep.fx` → the ledger anchor and the judges' sources block → the phantom-field guard. The spec is the real api.handle.me
shape, abbreviated. (The arrow grammar of a discovery entry has its own genuine case in test_fetch_facts_come_from_the_parsed_structure.)
"""
import unittest

from cria import loop, research
from tests.resultshape import genuine_fetch

URL = "https://api.handle.me/openapi.json"
HANDLE = {"type": "object", "properties": {
    "holder": {"type": "string"}, "name": {"type": "string"},
    "resolved_addresses": {"type": "object", "properties": {"ada": {"type": "string"}, "eth": {"type": "string"}}}}}
HOLDER = {"type": "object", "properties": {"total_handles": {"type": "integer"}, "address": {"type": "string"}}}


def _op(schema, param=None, description=""):
    op = {"responses": {"200": {"content": {"application/json": {"schema": schema}}}}}
    if param:
        op["parameters"] = [{"name": param, "in": "path", "description": description}]
    return {"get": op}


SPEC = {"openapi": "3.0.0", "paths": {
    "/handles/{handle}": _op(HANDLE, "handle", "The Handle name"),
    "/holders/{address}": _op(HOLDER, "address", "The stake/enterprise/script/other address of the Holder")}}


def _ledger():
    return loop._extract_fetches(genuine_fetch(URL, SPEC))


class ProducerToConsumersTests(unittest.TestCase):
    def test_the_ledger_anchor_carries_the_ts_fields(self):
        anchor = loop._format_fetches(_ledger())
        self.assertIn("fields each endpoint returns", anchor)
        for needle in ("holder?: string", "ada?: string", "total_handles?: number"):
            self.assertIn(needle, anchor)

    def test_the_judges_sources_block_delivers_what_it_promises(self):
        """The label may not appear without fields after it — the exact walked failure."""
        block = research._sources_block(research.grounded_sources(_ledger()))
        self.assertIn("response fields it defines:", block)
        self.assertIn("resolved_addresses", block)
        self.assertIn("total_handles", block)

    def test_the_phantom_field_guard_sees_the_declared_fields(self):
        names = loop._ledger_field_names(_ledger())
        self.assertLessEqual({"holder", "resolved_addresses", "ada", "total_handles"}, names)

    def test_param_descriptions_come_from_the_typed_entries(self):
        descs = loop._param_descriptions(_ledger())
        self.assertIn("{address} = The stake/enterprise/script/other address of the Holder", descs.get("/holders/{address}", ""))

    def test_the_block_ends_with_the_shape_not_the_page_around_it(self):
        anchor = loop._format_fetches(_ledger())
        self.assertNotIn("grep", anchor)


if __name__ == "__main__":
    unittest.main()
