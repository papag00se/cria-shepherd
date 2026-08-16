"""When cria refuses a cut-off call that was not a write, it does not tell the model its write failed.

`guard_truncation` has two closing messages, and both assert a WRITE: "[YOUR LAST WRITE WAS REFUSED]
… partway through writing the file". They are chosen by whether the response hit the output cap or
stopped itself — never by whether there was a write at all.

But the retry loop breaks at `path is None`, which is cria's own finding that `_truncated_write_path`
saw no write in the cut-off call. It then fell straight into the write wording.

Measured over five days: **all 17 truncations had `path is None`**, so 17 of 17 told the model its
last write was refused, and that it had stopped partway through writing a file it never wrote. A
false fact in cria's voice about the model's own turn (#5b) — and an actively misleading one, since
a model told it hit a limit shrinks its content, and a call that ended early is not fixed by being
shorter.
"""

import json
import unittest

from cria import prompts


class TheThreeWordingsAreDistinctTests(unittest.TestCase):
    def setUp(self):
        self.m = prompts.load_map("call_refused")

    def test_the_non_write_refusal_exists_and_says_so(self):
        t = self.m["truncated_call"]
        self.assertIn("TOOL CALL WAS REFUSED", t)
        self.assertIn("not a file write", t)
        self.assertNotIn("writing the file", t)

    def test_the_two_write_refusals_still_say_write(self):
        for key in ("truncated_write", "selfcut_write"):
            self.assertIn("WRITE WAS REFUSED", self.m[key], key)

    def test_the_cap_and_selfcut_wordings_still_differ(self):
        """A model told it hit a limit shrinks its content; one that ended early must not be."""
        self.assertIn("hit the output limit", self.m["truncated_write"])
        self.assertIn("did NOT hit any limit", self.m["selfcut_write"])

    def test_none_of_them_names_cria(self):
        for key, text in self.m.items():
            self.assertNotIn("cria", text.lower(), key)


class TheSelectionIsDrivenByWhetherThereWasAWriteTests(unittest.TestCase):
    def test_the_guard_consults_the_write_path_before_choosing(self):
        import inspect
        from cria import loop
        src = inspect.getsource(loop.guard_truncation)
        self.assertIn("was_write", src)
        self.assertIn('"truncated_call"', src)
        # the write wordings must be reachable only through was_write
        after = src[src.index("was_write ="):]
        self.assertIn('if was_write else "truncated_call"', after)

    def test_a_mid_write_cut_seen_on_any_pass_still_counts_as_a_write(self):
        """The retry can succeed at finding the path on pass 1 and lose it on pass 2 — the closing
        message must still describe what actually happened."""
        import inspect
        from cria import loop
        src = inspect.getsource(loop.guard_truncation)
        self.assertIn("_last_write_path_seen = _last_write_path_seen or path is not None", src)


if __name__ == "__main__":
    unittest.main()
