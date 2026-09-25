"""C40 / independent review round 3, R1: a same-length version bump must withdraw the old note and
deliver the new one — through the REAL session ``wsview.View`` + C38(+C38b) cross-request body cache +
``apply_survey``, not the test-only ``DirectView``.

Root cause (as diagnosed by independent review, confirmed here): C40's own delivery logic already
withdraws a coordinate correctly the moment ``declared_coordinates`` stops reporting it (an anchored
coordinate's cached text is only ever re-rendered by iterating the CURRENT
``declared_coordinates()`` result — an entry no longer returned is never touched again). The bug lived
one layer down, in ``wsview``'s cross-request ``_BODY_CACHE``: staleness was decided by SIZE alone
(C38), so `go get pkg@v1.5.0` rewriting `go.mod`'s `v1.4.0` to `v1.5.0` (identical byte length) left
the OLD body being served back as if it were still current. C38b (merged into this branch) requires
BOTH size AND mtime to agree before a cached body is trusted across requests. This test proves the
whole path end to end: C40 through `writeproxy.represent_inbound`, `wsview`'s real cache, and a real
survey shape.
"""
import base64
import os
import tempfile
import unittest

from cria import depsurface, wsview, writeproxy
from tests.wsfixture import survey

ROOT = "/workspace"
SESSION = "c40-version-bump-session"

GO_MOD_OLD = "module example.com/thing\n\ngo 1.21\n\nrequire other.com/pkg v1.4.0\n"
GO_MOD_NEW = "module example.com/thing\n\ngo 1.21\n\nrequire other.com/pkg v1.5.0\n"


def _blob_for(rel: str, body: str) -> str:
    raw = body.encode()
    return "@" + base64.b64encode(rel.encode()).decode() + "\n" + base64.b64encode(raw).decode()


def _tree(mtime, size) -> str:
    return "\n".join([f"F\t{mtime}\t{size}\tgo.mod", "F\t1\t10\tmain.go"])


def tool(content, call_id="c1"):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


class VersionBumpWithdrawalTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(len(GO_MOD_OLD), len(GO_MOD_NEW), "fixture must be a same-length edit")
        self.assertNotEqual(GO_MOD_OLD, GO_MOD_NEW)
        wsview._BODY_CACHE.clear()
        wsview._BODY_MISSES.clear()
        depsurface._ANCHOR.clear()
        self.addCleanup(wsview._BODY_CACHE.clear)
        self.addCleanup(wsview._BODY_MISSES.clear)
        self.addCleanup(depsurface._ANCHOR.clear)

        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self._real_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: (self.home if p == "~" else
                                        os.path.join(self.home, p[2:]) if p.startswith("~/") else
                                        self._real_expanduser(p))
        self.addCleanup(setattr, os.path, "expanduser", self._real_expanduser)
        # Local module cache present for BOTH versions, so the test can tell WHICH one, if either,
        # C40 actually delivers -- never inferred from "a note appeared", always from its real content.
        for ver, marker in (("v1.4.0", "VersionOneFour"), ("v1.5.0", "VersionOneFive")):
            d = os.path.join(self.home, "go", "pkg", "mod", f"other.com/pkg@{ver}")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "pkg.go"), "w") as fh:
                fh.write(f"package pkg\nfunc {marker}() string {{ return \"{ver}\" }}\n")

    def test_a_same_length_version_bump_withdraws_the_old_note_and_delivers_the_new_one(self):
        # Request 1: go.mod at v1.4.0, mtime 1000, body delivered this survey.
        view1 = wsview.View(ROOT, SESSION)
        tok1 = wsview.bind(view1)
        self.assertTrue(wsview.apply_survey(
            view1, survey(_tree(1000, len(GO_MOD_OLD)), root=ROOT,
                          blob=_blob_for("go.mod", GO_MOD_OLD))))
        out1 = writeproxy.represent_inbound([tool("go build ok", call_id="c1")],
                                            workspace_root=ROOT, sess_key=SESSION)
        wsview.unbind(tok1)
        self.assertIn("v1.4.0", out1[0]["content"])
        self.assertIn("VersionOneFour", out1[0]["content"])
        self.assertNotIn("VersionOneFive", out1[0]["content"])

        # Request 2: the coder ran `go get other.com/pkg@v1.5.0` through its OWN shell -- cria never
        # lowered this write, so `note_changed` never fired. go.mod is now v1.5.0 on real disk: SAME
        # byte length as before, a NEWER mtime. This survey reports the new (mtime, size) but has NOT
        # yet re-delivered the body (the harness answers a queued miss on a LATER survey) -- exactly
        # the shape C38b exists for. The harness's own unmodified turn-1 history (never cria's
        # rewrite) plus one new tool result make up this request.
        view2 = wsview.View(ROOT, SESSION)
        tok2 = wsview.bind(view2)
        self.assertTrue(wsview.apply_survey(view2, survey(_tree(2000, len(GO_MOD_NEW)), root=ROOT)))
        out2 = writeproxy.represent_inbound(
            [tool("go build ok", call_id="c1"), tool("go vet clean", call_id="c2")],
            workspace_root=ROOT, sess_key=SESSION)
        wsview.unbind(tok2)
        combined2 = "".join(m["content"] for m in out2)
        self.assertNotIn("v1.4.0", combined2, "the stale version must not be freshly reasserted")
        self.assertNotIn("VersionOneFour", combined2)
        self.assertNotIn("THE VERSION OF", combined2, "nothing claims v1.5.0 either -- body unknown")

        # Request 3: the harness finally answers the queued miss with the real v1.5.0 body.
        view3 = wsview.View(ROOT, SESSION)
        tok3 = wsview.bind(view3)
        self.addCleanup(wsview.unbind, tok3)
        self.assertTrue(wsview.apply_survey(
            view3, survey(_tree(2000, len(GO_MOD_NEW)), root=ROOT,
                          blob=_blob_for("go.mod", GO_MOD_NEW))))
        out3 = writeproxy.represent_inbound(
            [tool("go build ok", call_id="c1"), tool("go vet clean", call_id="c2"),
             tool("go test ok", call_id="c3")],
            workspace_root=ROOT, sess_key=SESSION)
        combined3 = "".join(m["content"] for m in out3)
        self.assertIn("v1.5.0", combined3)
        self.assertIn("VersionOneFive", combined3)
        self.assertNotIn("v1.4.0", combined3, "the withdrawn version must never resurface")
        self.assertNotIn("VersionOneFour", combined3)


if __name__ == "__main__":
    unittest.main()
