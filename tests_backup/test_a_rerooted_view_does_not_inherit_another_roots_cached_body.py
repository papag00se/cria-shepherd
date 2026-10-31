"""Independent-review B2: the session body cache leaked across workspace roots.

``View.reroot`` promises an EMPTY view for a directory nobody surveyed — "answering a question
about a directory nobody looked at from a survey of a different tree is a false fact, not a
convenience." The C38 landing (6eda89eb) keyed ``_BODY_CACHE`` by SESSION alone, so a fresh
``View`` built for any root under that session pulled in whatever the session had ever cached —
including a Rakefile delivered for a completely different workspace. Reproduced with the exact
shape ``wsview.current(root)`` uses: a request whose bound view is one root, asked about another.
"""

import base64
import unittest

from cria import wsview
from tests.wsfixture import survey

SESSION = "sess-c38-b2"
HOME = "/w"
OTHER = "/elsewhere"
BODY = "Rake::TestTask.new(:test)\n"


def _deliver(root: str, sess: str) -> None:
    view = wsview.View(root, sess)
    tok = wsview.bind(view)
    blob = "@" + base64.b64encode(b"Rakefile").decode() + "\n" + base64.b64encode(BODY.encode()).decode()
    assert wsview.apply_survey(view, survey(f"F\t1\t{len(BODY)}\tRakefile", root=root, blob=blob))
    wsview.unbind(tok)


class ARerootedViewStaysEmptyOfAnotherRootsCacheTests(unittest.TestCase):
    def setUp(self):
        getattr(wsview, "_BODY_CACHE", {}).clear()

    def test_current_asked_about_a_different_root_does_not_return_this_roots_bytes(self):
        _deliver(HOME, SESSION)
        view = wsview.View(HOME, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        other = wsview.current(OTHER)
        self.assertEqual(other.root, OTHER)
        self.assertFalse(other.surveyed)
        self.assertIsNone(other.read("Rakefile"),
                           "a view of a directory nobody surveyed must not answer from /w's cache")

    def test_a_view_constructed_directly_for_a_different_root_gets_nothing(self):
        _deliver(HOME, SESSION)
        elsewhere = wsview.View(OTHER, SESSION)
        tok = wsview.bind(elsewhere)
        self.addCleanup(wsview.unbind, tok)
        self.assertIsNone(elsewhere.read("Rakefile"))

    def test_the_same_root_still_gets_its_own_cached_body(self):
        """The fix must not throw the baby out: same session, same root, still works."""
        _deliver(HOME, SESSION)
        view = wsview.View(HOME, SESSION)
        tok = wsview.bind(view)
        self.addCleanup(wsview.unbind, tok)
        self.assertTrue(wsview.apply_survey(view, survey(f"F\t1\t{len(BODY)}\tRakefile", root=HOME)))
        self.assertEqual(view.read("Rakefile"), BODY)


if __name__ == "__main__":
    unittest.main()
