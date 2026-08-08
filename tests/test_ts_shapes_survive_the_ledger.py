"""The TS-fence shape render must survive every reader that consumed the old one-line render.

The 2026-08-07 response-shape format (operator's design: a `returns:` head + a ```ts fence of
`name?: type;` lines) replaced the one-line `GET /x → f1, f2{a,b}` render — and three readers were
still keyed on `→`. From that day until 2026-08-08 the durable fetch ledger carried routes and ZERO
response fields, the judges' sources block promised "response fields it defines:" and delivered
nothing after the colon (walked, mellum2 1786196176 calls 0021/0028 — one judge hallucinated the
missing fields and ruled partially blind), and the phantom-field steer guard was blind.

Four stations, one real spec, end to end: webfetch renders → _marker_block captures → the ledger
anchor and the judges' sources block re-render → _ledger_field_names guards. Fixtures are the REAL
api.handle.me shapes, abbreviated, in both grammars — the old render still has live captures, so
both must parse forever.
"""
import unittest

from cria import loop, research, webfetch

HEADER = (f"{webfetch.SHAPE_MARKER} the fields each endpoint MAY return — `?` marks a field the "
          "spec does NOT guarantee, so read it defensively; use these EXACT names and nesting, "
          "and do not guess:\n")

TS_ENTRIES = (
    "  GET /handles/{handle} (replace in the URL path: {handle} = The Handle name) returns:\n"
    "  ```ts\n"
    "  {\n"
    "    hex?: string;\n"
    "    name: string;                    // e.g. my.handle\n"
    "    holder?: string;                 // Current Holder of the Handle\n"
    "    resolved_addresses?: {\n"
    "      ada?: string;\n"
    "    };\n"
    "  }\n"
    "  ```\n"
    "  GET /holders/{address} (replace in the URL path: {address} = The stake/enterprise/script/"
    "other address of the Holder) returns:\n"
    "  ```ts\n"
    "  {\n"
    "    total_handles?: number;     // Total Handles this Holder holds\n"
    "  }\n"
    "  ```")
OLD_ENTRIES = (
    "  GET /handles/{handle} (replace in the URL path: {handle} = The Handle name) → hex(string), "
    "holder(string), resolved_addresses{ada(string)}\n"
    "  GET /holders/{address} → total_handles(integer)")

TOOL_RESULT_TS = "HTTP 200 · u\n" + HEADER + TS_ENTRIES + "]\n[grep hint]\n"
TOOL_RESULT_OLD = "HTTP 200 · u\n" + HEADER + OLD_ENTRIES + "]\n[grep hint]\n"


def _ledger(captured):
    return {"u": ("HTTP 200", "/handles/{handle}, /holders/{address}", captured, "")}


class CaptureTests(unittest.TestCase):
    def test_ts_fields_survive_capture(self):
        cap = loop._marker_block(TOOL_RESULT_TS, 0, webfetch.SHAPE_MARKER)
        for needle in ("holder?: string", "ada?: string", "total_handles?: number"):
            self.assertIn(needle, cap)

    def test_old_render_still_captures(self):
        cap = loop._marker_block(TOOL_RESULT_OLD, 0, webfetch.SHAPE_MARKER)
        self.assertIn("resolved_addresses{ada(string)}", cap)
        self.assertIn("total_handles(integer)", cap)

    def test_capture_stops_at_the_block_end_not_mid_document(self):
        cap = loop._marker_block(TOOL_RESULT_TS, 0, webfetch.SHAPE_MARKER)
        self.assertNotIn("grep hint", cap)


class ReRenderTests(unittest.TestCase):
    def test_the_ledger_anchor_carries_the_ts_fields(self):
        cap = loop._marker_block(TOOL_RESULT_TS, 0, webfetch.SHAPE_MARKER)
        anchor = loop._format_fetches(_ledger(cap))
        self.assertIn("fields each endpoint returns", anchor)
        self.assertIn("ada?: string", anchor)

    def test_the_judges_sources_block_delivers_what_it_promises(self):
        """The label may not appear without fields after it — the exact walked failure."""
        cap = loop._marker_block(TOOL_RESULT_TS, 0, webfetch.SHAPE_MARKER)
        block = research._sources_block(research.grounded_sources(_ledger(cap)))
        self.assertIn("response fields it defines:", block)
        self.assertIn("resolved_addresses", block)


class GuardTests(unittest.TestCase):
    def test_the_phantom_field_guard_sees_ts_fields(self):
        cap = loop._marker_block(TOOL_RESULT_TS, 0, webfetch.SHAPE_MARKER)
        names = loop._ledger_field_names(_ledger(cap))
        self.assertLessEqual({"holder", "resolved_addresses", "ada", "total_handles"}, names)

    def test_the_guard_still_reads_the_old_render(self):
        cap = loop._marker_block(TOOL_RESULT_OLD, 0, webfetch.SHAPE_MARKER)
        names = loop._ledger_field_names(_ledger(cap))
        self.assertLessEqual({"holder", "resolved_addresses", "ada", "total_handles"}, names)

    def test_param_descriptions_come_from_the_captured_ts_heads(self):
        cap = loop._marker_block(TOOL_RESULT_TS, 0, webfetch.SHAPE_MARKER)
        descs = loop._param_descriptions(_ledger(cap))
        self.assertIn("{address} = The stake/enterprise/script/other address of the Holder",
                      descs.get("/holders/{address}", ""))


if __name__ == "__main__":
    unittest.main()
