"""A judge's "Proposed fix" is authored text the coder acts on, and it faced one guard.

An authored steer goes through `_grounded_steer_or_none` — role-play, argument blobs, ungrounded
URLs, phantom filesystem paths, phantom response fields. A judge's `proposed_fix` reaches the coder
through `_verdict_nudge`, which checked exactly one thing: invented `METHOD /path` routes. Same kind
of text, same reader, different bar.

MEASURED over the captures: 134 proposed fixes reached the coder across 41 sessions. Replayed
through the steer guards with no evidence at all, 10 are dropped for naming a URL — including

    Use web_fetch to retrieve the repository URL (https://github.com/guyp/decimal) …

a repository that does not exist, and several docs.rs pages whose shape the judge invented. The
evidence the judge itself was shown is now passed in, so a URL it legitimately READ still goes
through: the check is against what cria composed, exactly, not against a guess.

`ask` is deliberately NOT threaded, so the reasoner-backed arms stay off and this costs no model
call. Only the deterministic guards run.

THE REASON ALWAYS SURVIVES. The step really was not done; only the invented move is dropped. That is
the same shape the route check already had, and #2's line: cria surfaces facts and steers, and does
not author the work.
"""

import unittest

from cria import loop


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


REASON = "the DELETE route is not implemented in orders/api.py"


def nudge(fix, evidence="", **kw):
    return loop._verdict_nudge({"reason": REASON, "proposed_fix": fix}, False,
                               evidence=evidence, rlog=_Rlog(), **kw)


class AnInventedUrlIsDroppedTests(unittest.TestCase):
    def test_the_measured_case(self):
        fix = ("Use web_fetch to retrieve the repository URL (https://github.com/guyp/decimal) "
               "and then read the README.md")
        out = nudge(fix)
        self.assertEqual(out, REASON)
        self.assertNotIn("github.com", out)

    def test_a_url_the_judge_actually_read_survives(self):
        """The evidence cria composed for that judge is the grounding set. A page it really fetched
        is not an invention, and withholding it would be cria destroying a good move."""
        fix = "Read https://docs.rs/toml/latest/toml/ for the Table API"
        evidence = "the coder fetched https://docs.rs/toml/latest/toml/ — HTTP 200"
        out = nudge(fix, evidence=evidence)
        self.assertIn("Proposed fix:", out)
        self.assertIn("docs.rs/toml", out)

    def test_the_reason_always_survives(self):
        for fix in ("see https://example.invalid/spec",
                    "Use https://github.com/nope/nope as reference"):
            with self.subTest(fix=fix):
                self.assertIn(REASON, nudge(fix))


class TheOtherSteerGuardsApplyTooTests(unittest.TestCase):
    def test_a_phantom_system_path_is_dropped(self):
        """The walked incident: a steer cited /home/user1/.cache/api.handle.me/openapi.json, a path
        that has never existed on this box, and the coder spent its next turn trying to read it."""
        fix = "Read the real spec at /home/user1/.cache/api.handle.me/openapi.json first"
        self.assertEqual(nudge(fix), REASON)

    def test_a_workspace_path_is_never_checked(self):
        """Preserved exactly: a path inside the workspace may be a CREATE target, so its absence is
        not evidence of invention."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fix = f"Add the handler to {d}/orders/not_yet.py"
            self.assertIn("Proposed fix:", nudge(fix, workspace_root=d))

    def test_a_system_path_that_exists_is_fine_to_mention(self):
        self.assertIn("Proposed fix:", nudge("check /usr/bin against the PATH"))

    def test_an_ordinary_fix_is_untouched(self):
        fix = "the DELETE /orders/{id} endpoint must remove the row and return 204"
        out = nudge(fix)
        self.assertIn(REASON, out)
        self.assertIn("Proposed fix: " + fix, out)


class WhatDidNotChangeTests(unittest.TestCase):
    def test_a_pass_still_drops_the_fix_entirely(self):
        out = loop._verdict_nudge({"reason": "all good", "proposed_fix": "x" * 50}, True, rlog=_Rlog())
        self.assertEqual(out, "all good")

    def test_the_route_check_still_fires(self):
        """The pre-existing guard, preserved: a METHOD /path the shape ledger never saw."""
        out = loop._verdict_nudge({"reason": REASON, "proposed_fix": "call POST /handles/resolve"},
                                  False, "GET /orders/{id}", rlog=_Rlog())
        self.assertEqual(out, REASON)

    def test_no_rlog_means_no_new_guard_and_no_crash(self):
        """The signature stayed backward-compatible on purpose — an unthreaded caller keeps the old
        behaviour rather than raising."""
        out = loop._verdict_nudge({"reason": REASON, "proposed_fix": "see https://nope.invalid/x"},
                                  False)
        self.assertIn("Proposed fix:", out)

    def test_an_empty_fix_is_just_the_reason(self):
        self.assertEqual(nudge(""), REASON)

    def test_a_fix_with_no_reason_still_ships(self):
        out = loop._verdict_nudge({"reason": "", "proposed_fix": "implement the DELETE route"},
                                  False, rlog=_Rlog())
        self.assertEqual(out, "Proposed fix: implement the DELETE route")


class EveryJudgeSiteIsWiredTests(unittest.TestCase):
    def test_all_four_call_sites_pass_the_evidence(self):
        """Four seats reach the coder with a proposed fix. A guard on three of them is the shape
        this codebase keeps regressing into."""
        import inspect
        src = inspect.getsource(loop)
        calls = [ln for ln in src.splitlines() if "_verdict_nudge(" in ln and "def " not in ln]
        self.assertEqual(len(calls), 4, calls)
        joined = src
        for ln in calls:
            i = joined.index(ln.strip())
            with self.subTest(call=ln.strip()[:60]):
                self.assertIn("evidence=user", joined[i:i + 200])
                self.assertIn("rlog=rlog", joined[i:i + 200])

    def test_no_reasoner_is_spent_on_it(self):
        """Asserted by handing it an `ask` that EXPLODES. The first version searched the source for
        the string `ask=`, which passes the moment the keyword is renamed and says nothing about
        whether a model is called by some other route — and "this costs no model call" is a claim
        about behaviour on a hot path, not about a spelling."""
        def must_not_be_called(*a, **k):
            raise AssertionError("a reasoner was spent on a verdict nudge")

        from unittest import mock
        with mock.patch("cria.loop.summarize", side_effect=must_not_be_called), \
             mock.patch("cria.loop.ask_closed", side_effect=must_not_be_called), \
             mock.patch("cria.loop._judge_completion", side_effect=must_not_be_called):
            out = loop._verdict_nudge(
                {"reason": "the resolver returns nothing",
                 "proposed_fix": "read https://github.com/guyp/decimal and copy its parser"},
                False, evidence="", rlog=_Rlog())
        self.assertIn("the resolver returns nothing", out)   # the REASON always survives
        self.assertNotIn("github.com/guyp/decimal", out)     # ...and the ungrounded URL does not


if __name__ == "__main__":
    unittest.main()
