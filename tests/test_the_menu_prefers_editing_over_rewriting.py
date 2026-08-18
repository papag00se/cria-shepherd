"""cria told the coder to prefer whole-file rewrites, and it obeyed into a five-rewrite spiral.

The cheatsheet is introduced to the model as *"Tools available this turn, listed in the order you
should PREFER them"* — and it led with `write_file — {"content": "<full file text>"}`, with
`edit_file` beneath it.

Measured on the targeted post-fix re-run of `rust-toml-cli × ternary-bonsai`, the cell that scores
100% unassisted:

    under cria    write_file 7   edit_file 0   read_file 1   exec_command 4
    unassisted    write_file 2   edit_file 3   read_file 4   exec_command 8

It rewrote a 6.6 KB `main.rs` WHOLE, five times, each version 99.1–99.9% identical to the one before,
until a regeneration introduced the type error the run died on — `.get(key)` had been correct at
three earlier rewrites and became `.get(key.to_string())` at the last. The same model, on the same
task, with the harness's own menu, wrote the file once and made three ~285-byte patches: 20 calls,
4 of 4.

**IT DID WHAT IT WAS TOLD.** That is the whole finding. Changing part of a file that exists is what
`edit_file` is for; a whole-file rewrite regenerates every line that was already right, and each
regeneration is a fresh chance to break one.

This is the A fix. Folding the superseded copies out of the prompt
(`focustrim._stub_superseded_writes`) is the B — worth keeping on its own terms, because a stale copy
of a file is not what is on disk and #5 allows carrying repeated content once as a pointer — but it
treats the bloat, and this treats the rewriting.
"""

import unittest

from cria import toolmenu


def tool(name, **props):
    return {"type": "function",
            "function": {"name": name,
                         "parameters": {"type": "object",
                                        "properties": props or {"path": {"type": "string"}}}}}


FULL = [tool("write_file"), tool("edit_file"), tool("read_file"), tool("list_dir"),
        tool("exec_command", command={"type": "string"})]


class EditComesFirstTests(unittest.TestCase):
    def setUp(self):
        self.sheet = toolmenu.cheatsheet(FULL)

    def test_the_order_the_model_is_told_to_prefer(self):
        """The header calls this an order of preference, so the order IS the instruction."""
        self.assertIn("order you should PREFER them", self.sheet)
        self.assertLess(self.sheet.index("- edit_file"), self.sheet.index("- write_file"))

    def test_the_lead_sentence_names_edit_first_too(self):
        lead = [ln for ln in self.sheet.splitlines() if ln.startswith("CRITICAL")][0]
        self.assertLess(lead.index("edit_file"), lead.index("write_file"))
        self.assertIn("PREFER this", lead)

    def test_each_one_says_what_it_is_for(self):
        self.assertIn("change PART of an existing file", self.sheet)
        self.assertIn("for a NEW file, or to replace one wholesale", self.sheet)

    def test_it_says_why_rewriting_is_expensive(self):
        """Not a style note — the reason is the measured failure."""
        self.assertIn("regenerates every line that was already right", self.sheet)


class TheMenuStillOnlyNamesWhatExistsTests(unittest.TestCase):
    def test_a_menu_without_edit_file_never_mentions_it(self):
        sheet = toolmenu.cheatsheet([tool("write_file"), tool("read_file")])
        self.assertNotIn("edit_file", sheet)
        self.assertIn("write_file", sheet)

    def test_a_menu_without_write_file_never_mentions_it(self):
        sheet = toolmenu.cheatsheet([tool("edit_file"), tool("read_file")])
        self.assertNotIn("write_file", sheet)
        self.assertIn("edit_file", sheet)

    def test_the_shell_still_trails_the_purpose_built_tools(self):
        sheet = toolmenu.cheatsheet(FULL)
        self.assertLess(sheet.index("- edit_file"), sheet.index("exec_command"))

    def test_shelling_out_to_write_is_still_refused(self):
        self.assertIn("Do NOT write files by shelling out", toolmenu.cheatsheet(FULL))


if __name__ == "__main__":
    unittest.main()
