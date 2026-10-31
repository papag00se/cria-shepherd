"""C38b / independent review #5b: a session-cached body must not survive a SAME-SIZE edit cria
never observed.

C38's cross-request cache (``_BODY_CACHE``) decided staleness by comparing the fresh survey's
declared SIZE against the cached body's length (``_drop_stale_bodies``, ``_reconcile_cache_candidates``).
That catches a body cut in transit or a length-changing edit, but not `go get pkg@v1.5.0` rewriting
`go.mod`'s ``v1.4.0`` to ``v1.5.0`` (same width), `cargo update` pinning a same-length version, or a
same-length Rakefile edit landing through the coder's own shell — a command cria never lowered, so
`note_changed` (which purges the cache on an edit cria DID watch land) never runs. C40 reads a
manifest through exactly this seam to state a dependency's API surface under an exact version's
wording; a stale same-size body would deliver the WRONG version's API as fact.

The survey listing already carries mtime (``self._files[rel] = (size, mtime)``, ``wsview.py``'s own
``_ingest_tree``); this fix makes cache reconciliation require BOTH size and mtime to agree with the
listing that originally confirmed the cached body, not size alone.
"""

import base64
import unittest

from cria import wsview
from tests.wsfixture import survey

ROOT = "/workspace"
SESSION = "01a0d5d1-c38b"

GO_MOD_OLD = 'module example.com/thing\n\nrequire other.com/pkg v1.4.0\n'
GO_MOD_NEW = 'module example.com/thing\n\nrequire other.com/pkg v1.5.0\n'


def _blob_for(rel: str, body: str) -> str:
    raw = body.encode()
    return "@" + base64.b64encode(rel.encode()).decode() + "\n" + base64.b64encode(raw).decode()


def _tree(mtime, size) -> str:
    return "\n".join([f"F\t{mtime}\t{size}\tgo.mod", "F\t1\t10\tmain.go"])


class ASameSizeUnobservedEditEndsTheCachedBodyTests(unittest.TestCase):
    def setUp(self):
        getattr(wsview, "_BODY_CACHE", {}).clear()
        wsview._BODY_MISSES.clear()

    def test_a_same_size_shell_edit_between_requests_is_not_read_as_the_old_body(self):
        self.assertEqual(len(GO_MOD_OLD), len(GO_MOD_NEW))
        self.assertNotEqual(GO_MOD_OLD, GO_MOD_NEW)

        # Request 1: go.mod's body is delivered at mtime "1000" and cached for the session.
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.assertTrue(wsview.apply_survey(
            view, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT, blob=_blob_for("go.mod", GO_MOD_OLD))))
        self.assertEqual(view.read("go.mod"), GO_MOD_OLD)
        wsview.unbind(tok)

        # Between requests, `go get pkg@v1.5.0` runs through the coder's own shell — cria never lowers
        # this edit, so `note_changed` never fires and the session cache is never told to forget.
        # The next survey reports the SAME size, a NEWER mtime: exactly what the shell's own write
        # left on disk, and exactly what a size-only staleness check cannot see.
        fresh = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(fresh)
        self.addCleanup(wsview.unbind, tok2)
        self.assertTrue(wsview.apply_survey(fresh, survey(_tree(2000, len(GO_MOD_NEW)), root=ROOT)))

        got = fresh.read("go.mod")
        self.assertNotEqual(got, GO_MOD_OLD, "the pre-bump version string must not be read back")
        self.assertIsNone(got, "an unobserved same-size edit leaves the body unknown, not stale-trusted")
        bodies, _progs, _outside = wsview.pending(SESSION)
        self.assertIn("go.mod", bodies, "the dropped body must be RE-ASKED")

    def test_an_unchanged_file_across_requests_is_still_reused(self):
        """C38's actual benefit must survive this fix: same size AND same mtime still promotes."""
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.assertTrue(wsview.apply_survey(
            view, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT, blob=_blob_for("go.mod", GO_MOD_OLD))))
        wsview.unbind(tok)

        fresh = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(fresh)
        self.addCleanup(wsview.unbind, tok2)
        self.assertTrue(wsview.apply_survey(fresh, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT)))
        self.assertEqual(fresh.read("go.mod"), GO_MOD_OLD, "an unchanged file must still be reused")

    def test_a_zero_mtime_listing_is_never_trusted_across_requests(self):
        """`_ingest_tree`'s own fallback for an unparseable timestamp is `0.0` — not a real moment
        in time, and must not be treated as agreeing with anything, including another `0.0`."""
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.assertTrue(wsview.apply_survey(
            view, survey(_tree(0, len(GO_MOD_OLD)), root=ROOT, blob=_blob_for("go.mod", GO_MOD_OLD))))
        wsview.unbind(tok)

        fresh = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(fresh)
        self.addCleanup(wsview.unbind, tok2)
        self.assertTrue(wsview.apply_survey(fresh, survey(_tree(0, len(GO_MOD_OLD)), root=ROOT)))
        self.assertIsNone(fresh.read("go.mod"), "an unparseable mtime must never be treated as known")

    def test_an_uncorroborated_write_is_not_cross_request_trusted(self):
        """A write to a path NO tree has ever mentioned has nothing to corroborate its mtime with
        (see `note_written`'s own comment) — cria's own clock guess, never survey-confirmed — and the
        cache candidate it leaves behind must not auto-promote in a later request."""
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.assertTrue(wsview.apply_survey(view, survey("F\t1\t10\tmain.go", root=ROOT)))  # no go.mod yet
        view.note_written("go.mod", GO_MOD_OLD)
        self.assertEqual(view.read("go.mod"), GO_MOD_OLD)  # trusted THIS request — cria watched it land
        wsview.unbind(tok)

        fresh = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(fresh)
        self.addCleanup(wsview.unbind, tok2)
        self.assertTrue(wsview.apply_survey(fresh, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT)))
        self.assertIsNone(fresh.read("go.mod"),
                          "a write's local-clock mtime must not be trusted as a real survey confirmation")

    def test_a_write_corroborated_by_a_same_turn_survey_is_cross_request_trusted(self):
        """C38b follow-up: when a write's OWN turn also carries a survey reporting the same size for
        the path (the harness runs the write and the survey in the same shell script), that survey
        really has vouched for these exact bytes — no different from a blob delivery — and the write
        is legitimately promotable in a later request, PROVIDED that survey's mtime still agrees."""
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.assertTrue(wsview.apply_survey(view, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT)))
        view.note_written("go.mod", GO_MOD_OLD)
        wsview.unbind(tok)

        fresh = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(fresh)
        self.addCleanup(wsview.unbind, tok2)
        self.assertTrue(wsview.apply_survey(fresh, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT)))
        self.assertEqual(fresh.read("go.mod"), GO_MOD_OLD,
                         "a write real survey evidence backs must still be reused, unchanged")


if __name__ == "__main__":
    unittest.main()
