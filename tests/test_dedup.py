"""One copy of cria's own injected ground truth per outbound view (cria/dedup.py).

Walked on ada-handles_maple-preview_codex_poff_1785956867: the ~2.4KB fetched-spec field block
rode THREE ways in single prompts — the per-call ⟦ctx:facts⟧ anchor, a byte-identical appendix
baked into the compaction summary (the ⟦ctx:continuation⟧ root), and the identical field lines
inside the original fetched-page tool result. Steer/judge prompts doubled it again (session copy
+ the labeled fetch-record block). The dedup is byte-exact and aggregate-lossless: every byte
stays present exactly once, in the block labeled as the authority; each removed copy becomes a
one-line pointer. Nothing fuzzy, nothing paraphrased, identity when there is nothing to do."""

import unittest

from cria import dedup

_FIELD_LINE = ("  GET /handles/{handle} (replace in the URL path: {handle} = The Handle name) → "
               "hex(string), name(string, e.g. my.handle), handle_type(string), holder(string, "
               "e.g. stake1uxxxxxxxx…xxxx), holder_type(string, e.g. wallet), rarity(string), "
               "resolved_addresses{ada(string, e.g. addr1e000000000…0001)}, lovelace(integer), "
               "has_datum(boolean), created_slot_number(integer), updated_slot_number(integer)")

_LEDGER = ("PAGES YOU HAVE ALREADY FETCHED — these SUCCEEDED:\n"
           "- https://api.handle.me/openapi.json → HTTP 200; endpoints: /handles, /handles/{handle}, /stats\n"
           "  fields each endpoint returns (use these EXACT names and nesting; do not guess):\n"
           + _FIELD_LINE + "\n"
           "  GET /stats → total_handles(integer), total_holders(integer)\n")

_NOTE = "(shown in full once in the fetch-record block of this prompt — not repeated here)"


class LedgerUnitTests(unittest.TestCase):

    def test_units_are_entry_blocks_and_long_lines_only(self):
        units = dedup.ledger_units(_LEDGER)
        self.assertTrue(any(u.startswith("- https://api.handle.me") for u in units))
        self.assertIn(_FIELD_LINE, units)
        for u in units:
            self.assertGreaterEqual(len(u), dedup.MIN_UNIT_CHARS)
        # the header is never a unit — a pointer must not replace the block's own label
        self.assertFalse(any(u.startswith("PAGES YOU") for u in units))

    def test_empty_ledger_yields_no_units(self):
        self.assertEqual(dedup.ledger_units(""), [])
        self.assertEqual(dedup.ledger_units("PAGES YOU HAVE ALREADY FETCHED:\n- x → 404\n"), [])


class ElideTextTests(unittest.TestCase):

    def test_an_identical_appendix_collapses_to_header_plus_note(self):
        continuation = ("⟦ctx:continuation⟧ Earlier in THIS session you worked on this task…\n\n"
                        "Your summary of the work so far: fixed the tests.\n\n" + _LEDGER)
        out, n = dedup.elide_text(continuation, dedup.ledger_units(_LEDGER), _NOTE)
        self.assertGreater(n, 0)
        self.assertNotIn(_FIELD_LINE, out)
        self.assertNotIn("- https://api.handle.me/openapi.json → HTTP 200", out)
        self.assertEqual(out.count(_NOTE), 1)                      # ONE pointer per message
        self.assertIn("PAGES YOU HAVE ALREADY FETCHED", out)       # the label survives
        self.assertIn("fixed the tests.", out)                     # unrelated prose untouched

    def test_an_identical_line_inside_a_different_wrapper_is_excised(self):
        rep = ("HTTP 200 OK · https://api.handle.me/openapi.json\n"
               "[response shape — the fields each endpoint RETURNS:\n" + _FIELD_LINE + "\n]\n")
        out, n = dedup.elide_text(rep, dedup.ledger_units(_LEDGER), _NOTE)
        self.assertEqual(n, 1)
        self.assertNotIn(_FIELD_LINE, out)
        self.assertIn(_NOTE, out)

    def test_no_match_is_identity(self):
        out, n = dedup.elide_text("nothing here overlaps", dedup.ledger_units(_LEDGER), _NOTE)
        self.assertEqual((out, n), ("nothing here overlaps", 0))


class ElideMessagesTests(unittest.TestCase):

    def _msgs(self):
        return [
            {"role": "system", "content": "sys " + _FIELD_LINE},              # never touched
            {"role": "user", "content": "⟦ctx:facts⟧ " + _LEDGER},            # the OWNER — never touched
            {"role": "user", "content": "⟦ctx:continuation⟧ briefing…\n\n" + _LEDGER},
            {"role": "tool", "content": "[response shape:\n" + _FIELD_LINE + "\n]"},
            {"role": "assistant", "content": _FIELD_LINE},                    # the model's own words — never touched
        ]

    def test_only_user_and_tool_copies_are_elided_and_the_owner_kept(self):
        msgs = self._msgs()
        out, n = dedup.elide_from_messages(msgs, dedup.ledger_units(_LEDGER), _NOTE,
                                           skip_prefix="⟦ctx:facts⟧")
        self.assertGreater(n, 0)
        self.assertIn(_FIELD_LINE, out[0]["content"])   # system untouched
        self.assertIn(_FIELD_LINE, out[1]["content"])   # the anchor keeps the full copy
        self.assertNotIn(_FIELD_LINE, out[2]["content"])
        self.assertNotIn(_FIELD_LINE, out[3]["content"])
        self.assertIn(_FIELD_LINE, out[4]["content"])   # assistant untouched
        # aggregate-lossless: the full view still holds the content exactly once
        whole = "\n".join(m["content"] for m in out if m["role"] in ("user", "tool"))
        self.assertEqual(whole.count(_FIELD_LINE), 1)

    def test_copy_on_write_never_mutates_the_inbound_dicts(self):
        msgs = self._msgs()
        before = [dict(m) for m in msgs]
        dedup.elide_from_messages(msgs, dedup.ledger_units(_LEDGER), _NOTE,
                                  skip_prefix="⟦ctx:facts⟧")
        self.assertEqual(msgs, before)

    def test_no_units_is_identity_same_object(self):
        msgs = self._msgs()
        out, n = dedup.elide_from_messages(msgs, [], _NOTE, skip_prefix="⟦ctx:facts⟧")
        self.assertIs(out, msgs)
        self.assertEqual(n, 0)


class WiringTests(unittest.TestCase):
    """The helper must guard both places the ledger is duplicated: the coder's outbound view (at
    both anchor-injection sites) and the steer author's serialized session vs its fetch block."""

    def test_the_coder_path_dedups_at_both_anchor_sites(self):
        import inspect
        from cria import loop
        src = inspect.getsource(loop)
        self.assertGreaterEqual(src.count("_elide_ledger_copies("), 2)

    def test_the_steer_author_dedups_its_session_against_fetch_truth(self):
        import inspect
        from cria import loop
        self.assertIn("dedup.elide_text", inspect.getsource(loop.author_steer))


class VolatileKeyTests(unittest.TestCase):
    """ONE answer to "is this the same payload again?".

    Everything in the table was MEASURED as the sole difference between near-identical payloads —
    10 such pairs across 2 of the 12 most recent captured sessions, every one of them an object
    address or a runner duration. A wrong entry here silently MERGES two different findings, so the
    table stays measured, never suspected."""

    def test_two_renderings_of_one_finding_share_a_key(self):
        from cria import dedup
        a = ("x.py:92: undefined name 'pytest'\n"
             "url = <urllib.request.Request object at 0x7cd31c34ac60>, args = ()\n"
             "3 failed, 1 passed in 0.36s")
        b = ("x.py:92: undefined name 'pytest'\n"
             "url = <urllib.request.Request object at 0x740a465deed0>, args = ()\n"
             "3 failed, 1 passed in 0.28s")
        self.assertNotEqual(a, b)
        self.assertEqual(dedup.volatile_key(a), dedup.volatile_key(b))

    def test_the_exec_envelopes_per_run_fields_still_go(self):
        from cria import dedup
        a = "Chunk ID: 939a6a\nWall time: 0.13 seconds\nOriginal token count: 69\nOutput:\nhi"
        b = "Chunk ID: aaaaaa\nWall time: 9.90 seconds\nOriginal token count: 71\nOutput:\nhi"
        self.assertEqual(dedup.volatile_key(a), dedup.volatile_key(b))

    def test_two_DIFFERENT_findings_keep_different_keys(self):
        from cria import dedup
        self.assertNotEqual(dedup.volatile_key("x.py:92: undefined name 'pytest'"),
                            dedup.volatile_key("x.py:92: undefined name 'json'"))
        self.assertNotEqual(dedup.volatile_key("1 failed, 3 passed in 0.10s"),
                            dedup.volatile_key("2 failed, 2 passed in 0.10s"))

    def test_a_line_number_is_never_treated_as_noise(self):
        from cria import dedup
        self.assertNotEqual(dedup.volatile_key("x.py:92: boom"), dedup.volatile_key("x.py:93: boom"))

    def test_focustrim_and_probegate_share_the_one_owner(self):
        from cria import dedup, focustrim
        self.assertIs(focustrim._result_key, dedup.volatile_key)
        import inspect
        from cria import probegate
        self.assertIn("dedup.volatile_key", inspect.getsource(probegate.clean_gate_results))


if __name__ == "__main__":
    unittest.main()
