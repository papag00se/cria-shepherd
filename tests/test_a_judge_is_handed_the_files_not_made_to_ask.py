"""The judge's inspection was a reasoner doing fact-gathering, one model call per file.

MEASURED across every captured session: **1,511 `loop.verify_inspect` rounds, 87% of them fetching
exactly ONE file.** And the cost is quadratic, because each round re-sends everything the previous
rounds read — one steer's loop grew 47K -> 62K -> 83K -> 102K chars and its final call alone took
**247 seconds**. Deterministic code gathers facts; a reasoner judges them (#8).

Read in the walked run: of six inspection rounds, four fetched a real fact, one asked for the
workspace's PARENT and was refused, and one produced no call at all. A judge handed the files cannot
spend a round asking for them.

BOUNDED BY THE WORK, NOT BY THE REPO. Newest-first is the inventory's own order and dependency trees
are already folded out of it, so a ten-thousand-file monorepo where the session touched three files
yields those three. (Operator, 2026-08-18: "I don't like the 'median 6 files' assertion because we're
only testing with clean repos and small asks.")

WHOLE FILES ONLY. One that does not fit is NAMED, never cut (#5), and the tools stay available.

THE ONE SEAT THAT DOES NOT GET THIS, deliberately: the steer author. `6726b8a` removed inlined
contents from it after a 57K curl'd spec was inlined TWICE under two path spellings — 115K of a 210K
prompt, in a composed two-message call the context floor has no turns to drop from, and the reasoner
died four times. That decision was measured and it stands. What is different here is the bound: the
same 57K spec is skipped and pointed at rather than pasted.
"""

import pathlib
import tempfile
import unittest

from cria import groundtruth, loop


class _WS:
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._d.name)
        for rel, body in self.files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        return str(root)

    def __exit__(self, *a):
        self._d.cleanup()
        return False


class TheFilesArriveWithoutBeingAskedForTests(unittest.TestCase):
    def test_the_contents_are_there(self):
        with _WS({"rates.rb": "module Shipping\n  EXPRESS = 14.99\nend\n"}) as root:
            out = groundtruth.files_for_a_judge(root)
            self.assertIn("EXPRESS = 14.99", out)
            self.assertIn("rates.rb", out)

    def test_an_empty_workspace_says_nothing(self):
        with _WS({}) as root:
            self.assertEqual(groundtruth.files_for_a_judge(root), "")
        self.assertEqual(groundtruth.files_for_a_judge(""), "")
        self.assertEqual(groundtruth.files_for_a_judge("/nonexistent-for-this-test"), "")


class TheBudgetIsBoundedByTheWorkTests(unittest.TestCase):
    def test_a_file_that_does_not_fit_is_NAMED_never_cut(self):
        """#5. The 57K-spec shape that `6726b8a` was written about."""
        big = "x" * (groundtruth.JUDGE_FILE_BUDGET + 5_000)
        with _WS({"small.py": "print(1)\n", "huge_spec.json": big}) as root:
            out = groundtruth.files_for_a_judge(root)
            self.assertIn("huge_spec.json", out)
            self.assertNotIn(big[:2000], out, "the oversized file was pasted in")
            self.assertIn("NOT INCLUDED ABOVE", out)
            self.assertIn("print(1)", out, "the file that DID fit is still there")

    def test_the_whole_block_stays_under_budget(self):
        files = {f"f{i}.py": "y" * 4_000 for i in range(20)}
        with _WS(files) as root:
            out = groundtruth.files_for_a_judge(root)
            body = out[out.index("-----"):]
            self.assertLessEqual(len(body), groundtruth.JUDGE_FILE_BUDGET + 4_000)

    def test_a_big_repo_still_yields_only_what_fits(self):
        """Repo size does not set the cost; the budget does."""
        files = {f"pkg/mod{i}/file{j}.py": "z" * 900 for i in range(40) for j in range(5)}
        with _WS(files) as root:
            out = groundtruth.files_for_a_judge(root)
            self.assertLess(len(out), groundtruth.JUDGE_FILE_BUDGET * 2)

    def test_dependency_trees_are_not_quoted(self):
        with _WS({"app.rb": "puts 1\n",
                  "vendor/bundle/ruby/3.2.0/gems/minitest-6/lib/minitest.rb": "MINITEST_INTERNALS\n",
                  "node_modules/left-pad/index.js": "NODE_MODULES_INTERNALS\n"}) as root:
            out = groundtruth.files_for_a_judge(root)
            self.assertIn("puts 1", out)
            self.assertNotIn("MINITEST_INTERNALS", out)
            self.assertNotIn("NODE_MODULES_INTERNALS", out)

    def test_a_binary_file_is_skipped_rather_than_mangled(self):
        with _WS({"ok.py": "print(1)\n"}) as root:
            pathlib.Path(root, "blob.bin").write_bytes(b"\x00\x01\x02\xff" * 100)
            out = groundtruth.files_for_a_judge(root)
            self.assertIn("print(1)", out)
            self.assertNotIn("blob.bin\n-----", out)


class ItGoesToTheJUDGES_AndNotToTheSteerAuthorTests(unittest.TestCase):
    def test_the_seeding_is_opt_in(self):
        import inspect
        sig = inspect.signature(loop._judge_completion)
        self.assertIn("seed_files", sig.parameters)
        self.assertIs(sig.parameters["seed_files"].default, False)

    def test_the_two_judges_that_inspect_opt_in(self):
        import inspect
        src = inspect.getsource(loop)
        self.assertIn("capped=capped, seed_files=True", src)          # satisfaction verdict
        self.assertIn("seed_files=True, force_think_off=reasoning_off", src)   # completion critic

    def test_the_steer_author_does_not(self):
        """`6726b8a`, and it was measured: 210K -> 89K chars, zero dead reasoner calls. Reverting it
        here would put a 57K spec back into a two-message call the context floor cannot trim."""
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertNotIn("seed_files", src)

    def test_the_question_is_still_the_last_thing_read(self):
        import inspect
        src = inspect.getsource(loop._judge_completion)
        self.assertIn("messages.insert(1,", src)
        self.assertNotIn("messages.append({\"role\": \"user\", \"content\": seeded})", src)


if __name__ == "__main__":
    unittest.main()
