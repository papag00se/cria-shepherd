"""cria's saved copy of a fetched page may not be the one file it deletes from the session's memory.

`_workspace_listing` builds the file list handed to the compactor — the reply that becomes the
harness's entire remembered past. It skipped the whole of `tmp`, on the reasonable grounds that a
package manager's tree is not the coder's work. `webfetch.SPILL_DIR` is `./tmp/reference`, so the
one artifact cria creates to hold an answer was the one artifact the listing removed, under a
docstring reading "THE LISTING THAT BECOMES THE SESSION'S MEMORY MAY NOT LIE BY OMISSION."

Walked on the sub-40 pass: cart-billing-go x nemotron-elastic, scored 32. cria had fetched
shopspring/decimal's README to `./tmp/reference/`; lines 84-93 of it name `NewFromFloat`, the
constructor the run then spent 42 consecutive calls failing to guess. The re-orientation author at
call 0049 was handed this listing — four files, no reference directory — and its own system prompt
forbids naming a file the listing does not name. It stayed quiet.

The rule was already written down twice, in `_label_spill_entries` and in `workspace_inventory`'s
`spill_note`: spill entries are LABELLED, never removed. This listing was the one place that
removed.
"""

import unittest

from cria import server, webfetch, wsview


def _survey(root, rels):
    P, S = wsview._SEC_PREFIX, wsview._SEC_SUFFIX
    tree = "".join(f"D\t{r}\n" if r.endswith("/") else f"F\t0\t3\t{r}\n" for r in rels)
    tree = tree.replace("/\n", "\n")
    return (f"{wsview.SURVEY_OPEN}\n{P}meta{S}\nroot\t{root}\n"
            f"{P}tree{S}\n{tree}{P}done{S}\nentries\t{len(rels)}\ncomplete\t1\n"
            f"{wsview.SURVEY_CLOSE}\n")


class TheReferenceDirectorySurvivesTests(unittest.TestCase):
    ROOT = "/w"
    FILES = ["cart.go", "go.mod", "tmp/", "tmp/reference/",
             "tmp/reference/github.com_shopspring_decimal.txt", "tmp/build/", "tmp/build/junk.o"]

    def setUp(self):
        self.view = wsview.View(root=self.ROOT)
        self.assertTrue(wsview.apply_survey(self.view, _survey(self.ROOT, self.FILES)))
        self.token = wsview.bind(self.view)
        self.addCleanup(wsview.unbind, self.token)

    def test_the_saved_page_is_named(self):
        out = server._workspace_listing(self.ROOT)
        self.assertIn("github.com_shopspring_decimal.txt", out)

    def test_it_is_labelled_as_reference_not_as_the_coders_work(self):
        """The entry stays so the listing keeps its completeness; the label is what stops it reading
        as file activity — the same fix `_label_spill_entries` makes on the steer author's section."""
        out = server._workspace_listing(self.ROOT)
        note = server.prompts.load_map("workspace_inventory")["spill_note"].strip()
        self.assertIn(note, out)

    def test_the_rest_of_the_scratch_root_stays_out(self):
        """Only the reference directory is rescued. `tmp` is where installs and builds land, and a
        package manager's tree is not something the coder wrote."""
        out = server._workspace_listing(self.ROOT)
        self.assertNotIn("junk.o", out)
        self.assertNotIn("tmp/build", out)

    def test_the_workspaces_own_files_are_untouched(self):
        out = server._workspace_listing(self.ROOT)
        for name in ("cart.go", "go.mod"):
            self.assertIn(name, out)

    def test_an_empty_reference_directory_adds_no_line(self):
        """Silence over noise: nothing was spilled, so there is nothing to say about it."""
        view = wsview.View(root=self.ROOT)
        wsview.apply_survey(view, _survey(self.ROOT, ["cart.go", "tmp/", "tmp/build/"]))
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        self.assertNotIn(webfetch.SPILL_DIR.strip("./"), server._workspace_listing(self.ROOT))


if __name__ == "__main__":
    unittest.main()
