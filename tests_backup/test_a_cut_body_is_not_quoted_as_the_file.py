"""A file body cria cannot verify is not a file body it may quote.

cria remembers file contents from writes, reads and surveys, and hands them to its own reasoners as
ground truth. A survey's bodies arrive base64-encoded on a tool result that passes through the
harness's output cap. A MIDDLE cut inside a base64 line leaves something `b64decode(validate=False)`
still decodes — into soup of the wrong length.

`_drop_stale_bodies` is the check that catches exactly this: it compares every remembered body
against the size the fresh listing declares. It ran at the end of `_ingest_tree`, which is BEFORE
`_ingest_blob`, so the bodies a survey carried were the only ones never tested against the listing
that arrived with them.

Walked three times in the L5 cells scoring under 60:
  * `[binary content: 3,792 bytes]` and "5,734 bytes, 6 lines" for a 7,601-byte, 193-line
    Importer.java — fed to a steer author, which replied "the file is binary/corrupted, rewrite it".
  * `[binary content: 6,225 bytes]` for a test.js the same prompt's own inventory called 7,354 B.
"""
import base64
import unittest

from cria import wsview


def _survey(root, tree, blob):
    P, S = wsview._SEC_PREFIX, wsview._SEC_SUFFIX
    entries = len([ln for ln in tree.splitlines() if ln.strip()])
    return (f"{wsview.SURVEY_OPEN}\n{P}meta{S}\nroot\t{root}\n"
            f"{P}tree{S}\n{tree}{P}blob{S}\n{blob}"
            f"{P}done{S}\nentries\t{entries}\ncomplete\t1\n{wsview.SURVEY_CLOSE}\n")


def _blob(rel, raw_b64):
    return "@" + base64.b64encode(rel.encode()).decode() + "\n" + raw_b64 + "\n"


class ACutBodyIsNotQuotedAsTheFile(unittest.TestCase):

    def test_a_body_cut_in_transit_is_dropped_not_stored(self):
        content = b"hello world, this is the real file\n" * 4
        whole = base64.b64encode(content).decode()
        v = wsview.View(root="/w")
        sv = _survey("/w", f"F\t0\t{len(content)}\thello.py\n", _blob("hello.py", whole[:len(whole) // 2]))
        self.assertTrue(wsview.apply_survey(v, sv), "the survey itself is well-formed")
        self.assertNotIn("hello.py", v._bodies,
                         "a body whose length disagrees with the listing is not the file")

    def test_an_intact_body_still_lands(self):
        content = b"hello world\n"
        v = wsview.View(root="/w")
        sv = _survey("/w", f"F\t0\t{len(content)}\thello.py\n",
                     _blob("hello.py", base64.b64encode(content).decode()))
        self.assertTrue(wsview.apply_survey(v, sv))
        self.assertEqual(v._bodies.get("hello.py"), content)

    def test_an_undecodable_body_does_not_leave_an_older_one_standing(self):
        v = wsview.View(root="/w")
        v._files["hello.py"] = (12, 0)
        v._set_body("hello.py", base64.b64encode(b"first pass!!").decode())
        self.assertIn("hello.py", v._bodies)
        v._set_body("hello.py", "!!!! not base64 at all !!!!")
        self.assertNotIn("hello.py", v._bodies,
                         "a failed decode must forget the file, not silently keep the old contents")


if __name__ == "__main__":
    unittest.main()
