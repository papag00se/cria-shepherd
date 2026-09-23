"""One copy of cria's own injected ground truth per outbound view (cria/dedup.py).

Walked on ada-handles_maple-preview_codex_poff_1785956867: the ~2.4KB fetched-spec field block
rode THREE ways in single prompts — the per-call ⟦ctx:facts⟧ anchor, a byte-identical appendix
baked into the compaction summary (the ⟦ctx:continuation⟧ root), and the identical field lines
inside the original fetched-page tool result. Steer/judge prompts doubled it again (session copy
+ the labeled fetch-record block). The dedup is byte-exact and aggregate-lossless: every byte
stays present exactly once, in the block labeled as the authority; each removed copy becomes a
one-line pointer. Nothing fuzzy, nothing paraphrased, identity when there is nothing to do."""

import unittest
from unittest import mock

from cria import dedup, loop

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


class _Rlog:
    def emit(self, kind, **kw):
        pass


class _StopAfterCoderTurn(Exception):
    """Raised from a patched ``_coder_turn`` once the framed view is captured — short-circuits the
    driver before it needs a real coder/reasoner endpoint, gate, or verify machinery."""


class WiringTests(unittest.TestCase):
    """The helper must guard both places the ledger is duplicated: the coder's outbound view (at
    BOTH driver halves — the multi-item plan-on path and the single-item plan-off/synthetic path,
    which route-unify made a second real caller of the SAME anchor-then-dedup shape) and the steer
    author's serialized session vs its fetch block.

    Driven end to end with a REAL duplicated ledger unit in the transcript, rather than counted in
    the module's source text — a count can't tell two real call sites from one call site and a
    comment that happens to repeat the helper's name (and the sibling test that used to strip
    comments out of `author_steer`'s source for exactly this reason was the tell)."""

    def _sess_with_ledger(self, **plan_kw):
        item = loop.PlanItem("step 1")
        plan = loop.Plan(id="20260101T000000-abcd1234", task="build it",
                         created="2026-01-01T00:00:00+00:00", items=[item])
        sess = loop.PlanSession(plan=plan, **plan_kw)
        sess.fetched_pages = {
            "https://api.handle.me/openapi.json":
                ("HTTP 200", "/handles, /handles/{handle}, /stats", _FIELD_LINE, ""),
        }
        return sess, item

    def _dup_unit(self, sess):
        ledger = loop._fetch_ground_truth([], sess, header="PAGES YOU HAVE ALREADY FETCHED")
        units = [u for u in dedup.ledger_units(ledger) if u == _FIELD_LINE]
        self.assertTrue(units, "fixture must reproduce a real, dedup-able ledger unit")
        return units[0]

    def _dup_body(self, unit):
        return {"messages": [{"role": "user", "content": "resolve a handle"},
                             {"role": "tool", "content": "[response shape:\n" + unit + "\n]"}],
               "tools": []}

    def _framed_messages_for(self, drive_call):
        captured = {}

        def _fake_coder_turn(self_loop, sess_, framed, body_, *, step, rlog):
            captured["messages"] = framed["messages"]
            raise _StopAfterCoderTurn()

        with mock.patch.object(loop.Loop, "_coder_turn", _fake_coder_turn):
            try:
                drive_call()
            except _StopAfterCoderTurn:
                pass
        self.assertIn("messages", captured, "never reached the coder turn — a guard fired first")
        return captured["messages"]

    def test_the_multi_item_driver_dedups_the_anchor(self):
        sess, item = self._sess_with_ledger()
        unit = self._dup_unit(sess)
        drv = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir=""))
        body = self._dup_body(unit)
        msgs = self._framed_messages_for(
            lambda: drv._work_item(sess, "k", body, _Rlog(), item, 1))
        whole = "\n".join(m.get("content", "") for m in msgs)
        self.assertIn(unit, whole)                    # the anchor keeps ONE copy
        self.assertEqual(whole.count(unit), 1)         # the tool-result duplicate collapsed

    def test_the_single_item_driver_dedups_the_anchor(self):
        sess, _item = self._sess_with_ledger(synthetic=True)
        unit = self._dup_unit(sess)
        drv = loop.Loop(loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir=""))
        body = self._dup_body(unit)
        msgs = self._framed_messages_for(
            lambda: drv._drive_single_item(sess, body, "k", _Rlog()))
        whole = "\n".join(m.get("content", "") for m in msgs)
        self.assertIn(unit, whole)
        self.assertEqual(whole.count(unit), 1)

    def test_the_steer_author_dedups_its_session_against_fetch_truth(self):
        """The steer author's SESSION transcript (the coder's own history) may still carry the
        original fetched-page result with the same field lines the labeled fetch-truth block
        re-states — that block is byte-identical because both are built from the SAME durable
        ledger. Drive the real author end to end and read what it actually sent the reasoner: the
        unit must appear exactly ONCE (from the labeled block), not the two copies it would carry
        with no dedup."""
        sess, _item = self._sess_with_ledger()
        unit = self._dup_unit(sess)
        sess.repeat_count, sess.repeat_action = 3, "exec_command {}"

        sent = []

        def reasoner(body, rlog):
            sent.append(" ".join(str(m.get("content") or "") for m in body["messages"]))
            return b'{"choices": [{"message": {"content": "ON_TRACK"}}]}'

        # A "tool" turn, matching the real shape (the original fetched-page RESULT) — a defanged
        # assistant/user turn collapses internal whitespace on the way in, which would break a
        # byte-exact match on a unit that carries its own indentation, unrelated to dedup.
        body = {"messages": [{"role": "user", "content": "build it"},
                             {"role": "tool", "content": "Output:\n" + unit + "\n"}],
               "tools": []}
        loop.author_steer(reasoner, None, "", sess, body, _Rlog(), condition="refusal")
        self.assertTrue(sent, "the steer author was never called")
        self.assertEqual(sent[0].count(unit), 1,
                        "the session's own copy must collapse against the labeled fetch-truth block")


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

    def test_every_runner_in_the_suite_has_its_duration_read(self):
        """The first cut matched pytest's `in 0.36s` phrasing — a python rule wearing a general
        name. Two runs of one passing Go suite print `ok\ttick\t0.003s` then `0.002s`, which it
        could not see, leaving the identical bug live on every non-python family in the suite."""
        from cria import dedup
        pairs = {
            "go":     ("ok  \ttick\t0.003s", "ok  \ttick\t0.002s"),
            "cargo":  ("test result: ok. 4 passed; 0 failed; finished in 0.00s",
                       "test result: ok. 4 passed; 0 failed; finished in 0.01s"),
            "pytest": ("3 failed, 1 passed in 0.36s", "3 failed, 1 passed in 0.28s"),
            "junit":  ("Tests run: 4, Failures: 0, Time elapsed: 0.031 s",
                       "Tests run: 4, Failures: 0, Time elapsed: 0.044 s"),
            "rspec":  ("Finished in 0.0123 seconds", "Finished in 0.0456 seconds"),
            "jest":   ("Time:        1.234 s", "Time:        1.567 s"),
            "mocha":  ("  4 passing (123ms)", "  4 passing (98ms)"),
        }
        for runner, (a, b) in pairs.items():
            self.assertEqual(dedup.volatile_key(a), dedup.volatile_key(b), runner)

    def test_every_spelling_of_an_object_address_is_noise(self):
        """Printed from the real runtimes on this box, not recalled. python's mock is the one that
        does NOT use 0x — `<MagicMock id='125997213614208'>` — and it is the most common address in
        these suites, since every mocked test that fails prints one."""
        from cria import dedup
        pairs = {
            "python repr": ("<urllib.request.Request object at 0x729803290080>",
                            "<urllib.request.Request object at 0x7cd31c34ac60>"),
            "python mock": ("<MagicMock id='125997213614208'>", "<MagicMock id='125997213999999'>"),
            "ruby":        ("#<Foo:0x000070a6e6366980>", "#<Foo:0x000070a6e63667a0>"),
            "java object": ("java.lang.Object@2a139a55", "java.lang.Object@5f2050f6"),
            "java array":  ("[I@14ae5a5", "[I@7f31245a"),
            "java nested": ("java.util.HashMap$KeyIterator@7f31245a",
                            "java.util.HashMap$KeyIterator@14ae5a5"),
            "go":          ("&S{} at 0xc000124010", "&S{} at 0xc000999888"),
            "rust":        ("0x61d3af242d60", "0x7f0011223344"),
            "c":           ("0x7ffd01400414", "0x7ffd01400999"),
        }
        for lang, (a, b) in pairs.items():
            self.assertEqual(dedup.volatile_key(a), dedup.volatile_key(b), lang)

    def test_an_at_hex_that_is_not_a_jvm_address_survives(self):
        """A miss is safer than a false merge. `user@abcdef.com` is six hex digits on a word
        boundary; the unguarded rule turned it into `user.com`."""
        from cria import dedup
        for s in ("contact user@abcdef.com for help", "npm i @babel/core",
                  "see release@fedcba for the tag", "docker pull img@sha256:9f2c"):
            self.assertEqual(dedup.volatile_key(s), s, s)

    def test_a_long_number_that_is_not_an_identity_survives(self):
        from cria import dedup
        for s in ("total_handles: 1000000000", "amount=125997213614208",
                  "expected id=42 got id=43"):
            self.assertEqual(dedup.volatile_key(s), s, s)

    def test_a_bare_integer_with_an_s_is_left_alone(self):
        # a duration needs a decimal point (or a sub-second unit); `30s` in a finding is content
        from cria import dedup
        self.assertNotEqual(dedup.volatile_key("AssertionError: expected 30s"),
                            dedup.volatile_key("AssertionError: expected 45s"))

    def test_a_line_number_is_never_treated_as_noise(self):
        from cria import dedup
        self.assertNotEqual(dedup.volatile_key("x.py:92: boom"), dedup.volatile_key("x.py:93: boom"))

    def test_focustrim_and_probegate_share_the_one_owner(self):
        from cria import dedup, focustrim
        self.assertIs(focustrim._result_key, dedup.volatile_key)

    def test_probegate_preserves_two_volatile_renderings_of_one_finding(self):
        """Unstamped checker results are ground truth even when `volatile_key` considers their
        per-run addresses and durations equivalent."""
        from cria import probegate

        def _checks(text):
            return {"role": "tool", "content": probegate.CHECKS_MARKER + " " + text}

        a = _checks("x.py:92: undefined name 'pytest'\n"
                   "url = <urllib.request.Request object at 0x7cd31c34ac60>, args = ()\n"
                   "3 failed, 1 passed in 0.36s")
        b = _checks("x.py:92: undefined name 'pytest'\n"
                   "url = <urllib.request.Request object at 0x740a465deed0>, args = ()\n"
                   "3 failed, 1 passed in 0.28s")
        self.assertNotEqual(a["content"], b["content"])   # byte-different renderings...
        self.assertEqual(probegate.clean_gate_results([a, b]), [a, b])


class ARepeatedTestRunIsARepeatTests(unittest.TestCase):
    """`volatile_key` scrubbed wall-clock and object identities but not a runner's SEED or its
    throughput banner, so two byte-equivalent `rake test` runs keyed differently and the repeat guard
    never fired.

    Walked on shipping-rates-rb x nemotron-elastic 1787432916: four identical green runs — `7 runs,
    7 assertions, 0 failures` every time — each landed in its own group, and the coder was never told
    it had already run this. Generalises to RSpec, `go test -shuffle` and pytest-randomly."""

    def _minitest(self, seed, secs, rate, failures=0):
        return (f"Run options: --seed {seed}\n\n# Running:\n\n.......\n\n"
                f"Finished in {secs}s, {rate} runs/s, {rate} assertions/s.\n\n"
                f"7 runs, 7 assertions, {failures} failures, 0 errors, 0 skips\n")

    def test_two_runs_of_one_green_suite_are_one_result(self):
        self.assertEqual(dedup.volatile_key(self._minitest(33602, "0.008369", "836.4139")),
                         dedup.volatile_key(self._minitest(62, "0.011790", "593.5075")))

    def test_a_run_whose_result_changed_is_not(self):
        self.assertNotEqual(dedup.volatile_key(self._minitest(1, "0.01", "800.0", failures=0)),
                            dedup.volatile_key(self._minitest(2, "0.02", "700.0", failures=1)))

    def test_the_seed_spellings_other_runners_use(self):
        for line in ("Run options: --seed 33602", "rspec --seed 1234",
                     "Using --randomly-seed=99887766"):
            with self.subTest(line=line):
                a = dedup.volatile_key(line)
                b = dedup.volatile_key(line.replace("33602", "1").replace("1234", "5")
                                           .replace("99887766", "7"))
                self.assertEqual(a, b)

    def test_a_number_that_is_content_survives(self):
        """The scrub may not eat a count, an amount or an id the reader needs."""
        key = dedup.volatile_key("7 runs, 7 assertions, 1 failures — expected 30s got 12")
        self.assertIn("7 runs", key)
        self.assertIn("1 failures", key)




class AProgramsOwnClockIsNotRunnerNoiseTests(unittest.TestCase):
    """`volatile_key` erases a clock reading so two runs of the same test suite key alike. It did so
    for ANY decimal followed by a time unit, anywhere — including a program's own measured output.

    A task that says "make it 4x faster" (principle 25c names that shape) prints `elapsed: 12.50 s`
    and later `elapsed: 3.10 s`. Both keyed to the same string, so `focustrim` folded them into one
    duplicate group and deleted the earlier call and its result from the model's view — two
    genuinely different answers merged, which is truncation with extra steps.

    The scrub is now scoped to a line that is a RUNNER talking about itself: one carrying a count of
    what ran, or its own duration announcement."""

    def test_two_different_benchmark_results_stay_different(self):
        a = "Benchmark complete.\nelapsed: 12.50 s\nrows: 40000\n"
        b = "Benchmark complete.\nelapsed: 3.10 s\nrows: 40000\n"
        self.assertNotEqual(dedup.volatile_key(a), dedup.volatile_key(b))

    def test_a_bare_took_line_is_not_scrubbed_either(self):
        self.assertNotEqual(dedup.volatile_key("import took 4.20 s"),
                            dedup.volatile_key("import took 1.05 s"))

    def test_the_same_suite_run_twice_still_folds(self):
        for a, b in (("== 7 passed in 0.36s ==", "== 7 passed in 1.94s =="),
                     ("ok  \tcartsvc\t0.003s", "ok  \tcartsvc\t0.921s"),
                     ("7 runs, 7 assertions\nFinished in 0.010147s",
                      "7 runs, 7 assertions\nFinished in 0.884s"),
                     ("Tests run: 4\nTime elapsed: 0.031 s",
                      "Tests run: 4\nTime elapsed: 0.912 s")):
            with self.subTest(a):
                self.assertEqual(dedup.volatile_key(a), dedup.volatile_key(b))


if __name__ == "__main__":
    unittest.main()
