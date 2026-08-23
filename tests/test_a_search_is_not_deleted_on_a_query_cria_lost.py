"""cria deleted the answer to the task because it could not read its own pointer.

`shipping-rates-rb x nemotron-elastic` 1787294328, scored 0/5. At call 0008 the model searched
`ruby gem to determine eu membership`. The results held, verbatim, `European Union Membership ·
c.in_eu? #=> false` and `#in_eu?, #in_eu_vat?` — the exact third-party predicate the task's central
instruction required. cria spilled them to `./tmp/reference/search-…txt` and inlined the titles.

Then cria asked its own judge whether those results were on target, and the judge's prompt said:

    THE SEARCH QUERY THE AGENT USED:
    (none)

It returned `query_on_target: false, results_on_target: false`, and cria told the coder:

    ⟦ctx:denied⟧ Those search results were off-target for this task, so they were removed.
    Search instead for: europe gem. Re-reading …search-ruby_gem_to_determine_eu_membership.txt
    is denied — it will keep returning this.

The model was redirected to the `europe` gem, which has no EU-membership predicate at all, and
never recovered.

A -> B -> C. **C** is the denial. **B** is the judge ruling on "(none)". **A** was that cria went
looking for the query in its OWN PROSE: `web_search` writes two different pointer sentences on
purpose, and the regex knew one of them. The inline form said only "(each result's full description
is in <file>)", so the query never arrived. The host veto that exists to stop exactly this cannot
fire, because this task names no host.

cria wrote that file. It had the query in its hand at that moment and threw it away, then tried to
recover it by reading English. Now it keeps it (`webfetch.spilled_search_files`), and there is no
sentence to match, no second shape to miss, and nothing a reworded prompt can break (#12, #22).

The pointers still name their query — for the CODER, who is told which search a file holds.
"""

import types
import unittest

from cria import loop, prompts, webfetch


class TheQueryComesFromTheRecordNotThePointerTests(unittest.TestCase):
    """The pointer is for the coder to read. cria reads its own record, so a third pointer shape
    could be added tomorrow and nothing here would change (#23)."""

    def test_the_spill_names_the_query_that_produced_it(self):
        webfetch.clear_cache()
        webfetch.note_search_spill("s", "ruby gem to determine eu membership")
        got = webfetch.spilled_search_files("s")
        self.assertEqual(list(got.values()), ["ruby gem to determine eu membership"])
        self.assertIn(webfetch.search_spill_name("ruby gem to determine eu membership").split("/")[-1],
                      list(got)[0])

    def test_both_pointers_still_tell_the_coder_which_search_this_is(self):
        for name, note in (("inline", prompts.fill(prompts.load("search_inline_note"),
                                                   target="./tmp/reference/search-x.txt",
                                                   query="ruby gem eu membership")),
                           ("spill", prompts.fill(prompts.load_map("webfetch_guards")["search_spill"],
                                                  query="ruby gem eu membership",
                                                  target="./tmp/reference/search-x.txt"))):
            with self.subTest(pointer=name):
                self.assertIn("ruby gem eu membership", note)
                self.assertIn("./tmp/reference/search-x.txt", note)

    def test_the_inline_pointer_names_the_real_file(self):
        """It once ended 'in the file named above' on a branch where nothing above named a file."""
        note = prompts.fill(prompts.load("search_inline_note"),
                            target="./tmp/reference/search-x.txt", query="q")
        self.assertIn("./tmp/reference/search-x.txt", note)


class NoQueryMeansNoVerdictTests(unittest.TestCase):
    """The floor under the fix: a file cria has no record of must cost the model nothing. That is also
    what a restart looks like — the file is still on disk and the record is not — and the verdict is
    destructive, so it must fail toward leaving the coder's file alone (#13)."""

    def _drive(self, register):
        """The real `_judge_search_reads` over a coder that read a spilled search file."""
        import json
        import os
        import tempfile
        ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(ws, "tmp", "reference"))
        rel = webfetch.search_spill_name("ruby gem to determine eu membership")
        with open(os.path.join(ws, rel.lstrip("./")), "w") as f:
            f.write("European Union Membership · c.in_eu? #=> false\n#in_eu?, #in_eu_vat?\n")
        webfetch.clear_cache()
        if register:
            webfetch.note_search_spill("s-floor", "ruby gem to determine eu membership")
        calls = {"n": 0}

        def fake_judge_search(chat, role, task, query, results, rlog, coder_tools=""):
            calls["n"] += 1
            return False, False, "europe gem"       # the verdict that deleted the answer

        saved, loop.judge_search = loop.judge_search, fake_judge_search
        try:
            lp = loop.Loop.__new__(loop.Loop)
            lp._ctx = type("C", (), {"reasoner_chat": object(), "reasoner_role": None})()
            sess = loop.PlanSession(plan=None)
            sess.workspace_root, sess.web_session = ws, "s-floor"
            body = {"messages": [
                {"role": "user", "content": "charge EU VAT for member states"},
                {"role": "assistant", "tool_calls": [{"id": "r1", "type": "function", "function": {
                    "name": "read_file", "arguments": json.dumps({"path": rel})}}]},
                {"role": "tool", "tool_call_id": "r1", "content": "in_eu? is defined on Country"},
            ], "tools": []}
            return calls, lp._judge_search_reads(sess, body, type("R", (), {"emit": lambda *a, **k: None})())
        finally:
            loop.judge_search = saved

    def test_the_judge_is_not_asked_for_a_file_cria_has_no_record_of(self):
        calls, out = self._drive(register=False)
        self.assertEqual(calls["n"], 0)
        self.assertEqual(out[-1]["content"], "in_eu? is defined on Country")   # untouched

    def test_it_still_judges_the_file_it_did_spill(self):
        """Otherwise the floor above would pass by never judging anything."""
        calls, out = self._drive(register=True)
        self.assertEqual(calls["n"], 1)
        self.assertIn("off-target", out[-1]["content"])



class TheWebSessionIsRecordedOnEveryDriverTests(unittest.TestCase):
    """Four web mechanisms were keyed on a field only the dead driver ever wrote.

    `sess.web_session` is the key webfetch's per-session gates use. It was assigned inside `_work`,
    the multi-item driver — and `_plan_off_session` has returned `synthetic=True` unconditionally
    since 2026-08-19, so `_drive_locked` dispatches to `_drive_single_item` before `_work` is
    reachable. Every real run left it "".

    Measured over 12 days of logs: `loop.search_judge_skipped why="no query"` fired 11 times, all 11
    in synthetic sessions; `loop.search_rehunt_cleared` fired 10 times, all 10 in the non-synthetic
    sessions that no longer happen, and none since. The "that fetch was not yours — it replaced the
    search you asked for" correction, which needs this key to fire, appears in 0 of 253 captured
    sessions while the wording that blames the coder for cria's own 404 appears in 377.

    Pinned on the DISPATCHER, not on either driver, so a third driver cannot be added without it."""

    class _Rlog:
        phase = ""

        def emit(self, kind, **kw):
            pass

    def _sess(self):
        from cria.plan import Plan, PlanItem
        sess = loop.PlanSession(plan=Plan(id="p", task="do the thing", created="c",
                                          items=[PlanItem(text="do the thing")]))
        sess.synthetic = True
        return sess

    def _loop_with_captured_drivers(self, sess):
        seen = {}
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = types.SimpleNamespace(planner_enabled=False, planner=None, workspace_root="")
        lp._store = types.SimpleNamespace(get=lambda k: sess, put=lambda k, v: None,
                                          clear_rewrite=lambda k: None, shape_done=lambda k: False,
                                          observe_shape=lambda *a, **k: (False, 0))

        def _single(s, body, key, rlog, rewritten=False):
            seen["single"] = s.web_session
            return {"ok": True}

        def _work(s, key, body, rlog, rewritten=False):
            seen["work"] = s.web_session
            return {"ok": True}

        lp._drive_single_item, lp._work = _single, _work
        return lp, seen

    def _body(self):
        return {"messages": [{"role": "user", "content": "do the thing"}],
                "tools": [{"type": "function", "function": {"name": "exec_command",
                                                            "parameters": {"properties": {"cmd": {}}}}}]}

    def test_the_single_item_driver_is_told_which_session_it_is(self):
        sess = self._sess()
        lp, seen = self._loop_with_captured_drivers(sess)
        lp._drive_locked(self._body(), "sid:abc123", None, self._Rlog())
        self.assertEqual(seen.get("single"), "sid:abc123")

    def test_the_multi_item_driver_is_told_too(self):
        sess = self._sess()
        sess.synthetic = False
        lp, seen = self._loop_with_captured_drivers(sess)
        lp._drive_locked(self._body(), "sid:abc123", None, self._Rlog())
        self.assertEqual(seen.get("work"), "sid:abc123")

if __name__ == "__main__":
    unittest.main()
