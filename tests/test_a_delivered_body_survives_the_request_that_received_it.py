"""C38: the survey delivers a manifest body and the plan that wanted it is already gone.

``server._bind_workspace_view`` builds a brand-new, empty ``wsview.View`` on every incoming HTTP
request — correct for the TREE, which is cheap to re-survey, and wrong for a manifest BODY: a
builder (``build_ruby``) asks for the Rakefile once, misses, and the harness answers the SAME round
trip with the file's real bytes — but the fact of having been told died with the request that
received it. The next ``View``, same session, started from ``_bodies = {}`` again, ``build_ruby``
missed on ``Rakefile`` a second time, and ``rake test`` never composed.

Reproduced here exactly as it happened in p27 shipping-rates-rb (session ``01a0d5d1``): the
workspace's own Rakefile declares ``Rake::TestTask.new(:test)`` — decoded byte for byte from the
capture's transport spool — and the harness handed it over, more than once, to a plan that had
already moved on.
"""

import base64
import unittest
from pathlib import Path

from cria import probediscovery, wsview
from tests.wsfixture import survey

RAKEFILE = (
    'require "rake/testtask"\n\n'
    'Rake::TestTask.new(:test) do |t|\n'
    '  t.libs << "lib" << "test"\n'
    '  t.test_files = FileList["test/**/test_*.rb"]\n'
    '  t.warning = false\n'
    'end\n\n'
    'task default: :test\n'
)

ROOT = "/workspace"
SESSION = "01a0d5d1-c38"


def _tree_lines() -> list[str]:
    return [
        f"F\t1\t{len(RAKEFILE)}\tRakefile",
        "F\t1\t10\tlib/shipping/rates.rb",
        "F\t1\t10\ttest/test_rates.rb",
        "D\tlib", "D\tlib/shipping", "D\ttest",
    ]


def _blob_for(rel: str, body: str) -> str:
    raw = body.encode()
    return "@" + base64.b64encode(rel.encode()).decode() + "\n" + base64.b64encode(raw).decode()


class ADeliveredManifestBodySurvivesTheRequestTests(unittest.TestCase):
    def setUp(self):
        wsview._BODY_CACHE.clear()
        wsview._BODY_MISSES.clear()

    def test_the_first_plan_misses_the_body_and_queues_it(self):
        """The by-design transient miss (wsview.py's own docstring): correct in both worlds."""
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        self.assertTrue(wsview.apply_survey(view, survey("\n".join(_tree_lines()), root=ROOT)))
        cands = probediscovery.discover(Path(ROOT))
        self.assertFalse(any(c.kind is probediscovery.ProbeKind.Test for c in cands))
        bodies, _progs, _outside = wsview.pending(SESSION)
        self.assertIn("Rakefile", bodies)

    def test_a_body_the_harness_delivers_reaches_the_very_next_requests_plan(self):
        # Request 1: the tree is known; build_ruby misses the Rakefile body and queues it, and the
        # SAME request's survey — composed with the queued WANT — comes back carrying the real
        # bytes, exactly the p27 capture's shape (WANT=['Rakefile'], answered same round trip).
        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.assertTrue(wsview.apply_survey(view, survey("\n".join(_tree_lines()), root=ROOT)))
        probediscovery.discover(Path(ROOT))  # misses Rakefile's body, queues want_body
        self.assertTrue(wsview.apply_survey(
            view, survey("\n".join(_tree_lines()), root=ROOT, blob=_blob_for("Rakefile", RAKEFILE))))
        self.assertEqual(view.read("Rakefile"), RAKEFILE)
        wsview.unbind(tok)

        # Request 2: a BRAND NEW View, same session — exactly what `_bind_workspace_view` builds on
        # every incoming request (server.py). Nothing about request 1's survey is replayed here; this
        # is the loss the diagnosis traced to `server.py:1000`.
        fresh = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(fresh)
        self.addCleanup(wsview.unbind, tok2)
        self.assertTrue(wsview.apply_survey(fresh, survey("\n".join(_tree_lines()), root=ROOT)))

        cands = probediscovery.discover(Path(ROOT))
        test_cands = [c for c in cands if c.kind is probediscovery.ProbeKind.Test]
        self.assertTrue(test_cands, "the Rakefile's body, delivered last request, must reach this plan")
        self.assertEqual(test_cands[0].command, ["rake", "test"])
        self.assertIn("Rakefile", test_cands[0].reason)

    def test_an_edit_between_requests_is_never_read_as_the_old_body(self):
        """The cached body must not survive an edit landing in between (never read stale).

        The edited Rakefile is deliberately the SAME byte length as the original (swap `:test` for
        `:lint`, both 4 letters) so a size-only staleness check — which `_drop_stale_bodies` already
        does for the next SURVEY that lands — could not by itself catch the change. This isolates
        the OTHER half of the invalidation: an edit the conversation replay watched land must purge
        the session cache itself, not merely wait for a fresh survey's size to disagree.
        """
        edited = RAKEFILE.replace("task default: :test\n", "task default: :lint\n")
        self.assertEqual(len(edited), len(RAKEFILE))
        self.assertNotEqual(edited, RAKEFILE)

        view = wsview.View(ROOT, SESSION)
        tok = wsview.bind(view)
        self.assertTrue(wsview.apply_survey(view, survey("\n".join(_tree_lines()), root=ROOT)))
        probediscovery.discover(Path(ROOT))
        self.assertTrue(wsview.apply_survey(
            view, survey("\n".join(_tree_lines()), root=ROOT, blob=_blob_for("Rakefile", RAKEFILE))))
        # The coder edits the Rakefile — cria watches the edit land (the same seam
        # `writeproxy.represent_inbound` uses) and no longer knows the new body.
        view.note_changed("Rakefile")
        wsview.unbind(tok)

        # Request 2: a fresh View, same session, same-sized Rakefile, no blob delivered yet this
        # round. Without the edit purging the session cache, this would silently hand back the STALE
        # pre-edit bytes — same size, so the survey-size check alone would not have caught it.
        fresh = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(fresh)
        self.addCleanup(wsview.unbind, tok2)
        self.assertTrue(wsview.apply_survey(fresh, survey("\n".join(_tree_lines()), root=ROOT)))
        got = fresh.read("Rakefile")
        self.assertNotEqual(got, RAKEFILE, "the stale, pre-edit body must not be handed back")
        self.assertIsNone(got, "an edited body cria has not been re-told is unknown, not the old one")

if __name__ == "__main__":
    unittest.main()
