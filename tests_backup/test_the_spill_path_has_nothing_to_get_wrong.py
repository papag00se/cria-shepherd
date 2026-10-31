"""cria refused a search, pointed at the file holding the answer, and named it with a hyphen.

`shipping-rates-rb x gemma4`, retest 2026-08-17, 1/5 against 4/5 unassisted. The task requires a
third-party gem ("Do not hardcode EU membership"), so the coder searched for one. cria's
near-duplicate search guard refused eight of its thirteen searches, and every refusal said where the
earlier results already were:

    You already ran web_search "…european union members", which is near-identical to "…european
    union". Its results were saved to ./tmp/read-only/search-….txt — they are NOT repeated here, so
    READ THAT FILE rather than searching again: grep -n "<keyword>" ./tmp/read-only/search-….txt

The coder did as it was told and typed `./tmp/read_only/…`. `grep: No such file or directory`. With
no results it searched again, cria refused again with the same pointer, and that loop ran for roughly
twenty of the run's 148 calls. It had already fetched both correct answers — rubygems `countries` at
call 26 and `europe.rb` at call 52 — and could not read either one back.

MEASURED over every captured call on this box, which is what decides the shape of the fix:

    read_file      68/68 correct        list_dir  1/1
    exec_command   50/59 correct        9 wrong, all of them read-only -> read_only  (15%)

The path is perfect when it is a TOOL ARGUMENT and wrong one time in seven when the model retypes it
inside a shell string. cria's generated FILENAMES — far longer, and mixed case and punctuation — came
back byte-exact every time. Length was never the problem. The hyphen was, sitting in a name every
other path around it writes with an underscore.

So this is not a corrector for the typo and not a heuristic; those would be assists over a mistake
cria caused (#1, #16). cria owns this directory's name and had no reason to put a separator in it.
`reference` also says what the directory holds, which `read-only` never did — and nothing depended on
the name to stop the coder writing there, `writeproxy.is_spill_path` does that.

The name is now spelled ONCE (#23). It used to be typed again in an execcheck constant, two loop.py
regexes and the model-facing tool descriptions, which is four places to forget on exactly the day
somebody renames it — and a prompt that points at a directory that no longer exists is this same bug
with a new spelling.
"""

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.


import ast
import pathlib
import re
import unittest

from cria import execcheck, loop, prompts, webfetch, writeproxy

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TheNameHasNoAmbiguityTests(unittest.TestCase):
    def test_the_directory_is_one_word(self):
        """A separator is a coin flip the model has to win every time it retypes the path."""
        leaf = webfetch.SPILL_DIR.rstrip("/").rsplit("/", 1)[-1]
        self.assertTrue(leaf.isalnum(), f"{leaf!r} contains a separator the model must guess")

    def test_the_old_name_is_gone_from_everything_the_model_reads(self):
        for name in ("tool_descs", "cheatsheet"):
            with self.subTest(prompt=name):
                filled = "\n".join(prompts.fill(v, spill_dir=webfetch.SPILL_DIR)
                                   for v in prompts.load_map(name).values())
                self.assertNotIn("read-only/", filled)


if __name__ == "__main__":
    unittest.main()
