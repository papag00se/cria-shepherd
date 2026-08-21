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

A -> B -> C. **A** is the pointer: `web_search` has two of them, and only the SPILL form carried the
query in the sentence `_SEARCH_POINTER_RE` matches. The INLINE form said only "(each result's full
description is in <file>)". So the query never reached `q_of`. **B** is the judge ruling on
"(none)". **C** is the denial. The host veto that exists to stop exactly this cannot fire, because
this task names no host.

Both halves are fixed: the pointers now say the same sentence, and a judgement with no query is not
made at all.
"""

import unittest

from cria import loop, prompts


class BothPointersCarryTheirQueryTests(unittest.TestCase):
    """One regex reads both, so a second pointer shape cannot silently bypass it (#23)."""

    def test_the_inline_pointer_is_readable(self):
        note = prompts.fill(prompts.load("search_inline_note"),
                            target="./tmp/reference/search-x.txt", query="ruby gem eu membership")
        m = loop._SEARCH_POINTER_RE.search(note)
        self.assertIsNotNone(m, "the inline pointer must name its query")
        self.assertEqual(m.group(1), "ruby gem eu membership")
        self.assertEqual(m.group(2), "./tmp/reference/search-x.txt")

    def test_the_spill_pointer_still_is(self):
        note = prompts.fill(prompts.load_map("webfetch_guards")["search_spill"],
                            query="ruby gem eu membership", target="./tmp/reference/search-x.txt")
        m = loop._SEARCH_POINTER_RE.search(note)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "ruby gem eu membership")

    def test_the_inline_pointer_names_the_real_file(self):
        """It once ended 'in the file named above' on a branch where nothing above named a file."""
        note = prompts.fill(prompts.load("search_inline_note"),
                            target="./tmp/reference/search-x.txt", query="q")
        self.assertIn("./tmp/reference/search-x.txt", note)


class NoQueryMeansNoVerdictTests(unittest.TestCase):
    """The floor under the fix: a pointer shape cria cannot read must cost the model nothing."""

    def test_the_judge_is_not_asked_when_the_query_was_lost(self):
        import inspect
        src = inspect.getsource(loop.Loop._judge_search_reads)
        self.assertIn("if not query:", src)
        i, j = src.index("if not query:"), src.index("judge_search(")
        self.assertLess(i, j, "the skip must come BEFORE the judge is called")
        self.assertIn("loop.search_judge_skipped", src)

    def test_the_skip_leaves_the_read_untouched(self):
        import inspect
        src = inspect.getsource(loop.Loop._judge_search_reads)
        block = src[src.index("if not query:"):src.index("judge_search(")]
        self.assertIn("out.append(m)", block)
        self.assertIn("continue", block)


if __name__ == "__main__":
    unittest.main()
