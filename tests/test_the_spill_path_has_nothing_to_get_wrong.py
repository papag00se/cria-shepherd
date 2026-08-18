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


class TheNameIsSpelledOnceTests(unittest.TestCase):
    """#23. Four copies is four things to forget, and a prompt naming a dead directory is this same
    bug wearing a different word."""

    def _functional_strings(self, path):
        """Every string literal in a module that is NOT a docstring — docstrings quote real past
        output and must keep saying what that output said (#5b)."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                d = ast.get_docstring(n, clean=False)
                if d is not None:
                    docs.add(d)
        return [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docs]

    def test_no_module_but_webfetch_spells_the_directory(self):
        leaf = webfetch.SPILL_DIR.rstrip("/").rsplit("/", 1)[-1]
        for f in sorted(ROOT.joinpath("cria").rglob("*.py")):
            if f.name == "webfetch.py":
                continue
            for s in self._functional_strings(f):
                with self.subTest(module=f.name, text=s[:60]):
                    self.assertNotIn(f"tmp/{leaf}", s)

    def test_the_consumers_derive_it(self):
        self.assertEqual(execcheck._SPILL_MARK, webfetch.SPILL_DIR.lstrip("./").rstrip("/") + "/")
        self.assertIn(webfetch.SPILL_DIR.lstrip("./"), loop._SEARCH_FILE_RE.pattern.replace("\\", ""))

    def test_the_prompt_carries_a_token_not_a_typed_path(self):
        """Typed into the prompt, the path drifts silently at the next rename — and cria then sends
        the coder to a directory that is not there, which is the whole incident above."""
        raw = prompts.load_map("tool_descs")
        self.assertIn("{{SPILL_DIR}}", raw["web_fetch"])
        self.assertIn("{{SPILL_DIR}}", raw["web_search"])

    def test_what_reaches_the_model_is_filled(self):
        """A token that ships unfilled is worse than a typed path: the coder is told to grep
        `{{SPILL_DIR}}/x`."""
        desc = writeproxy._synthetic_tools()["web_fetch"]["function"]["description"]
        self.assertNotIn("{{", desc)
        self.assertIn(webfetch.SPILL_DIR, desc)


class TheMachineryStillWorksTests(unittest.TestCase):
    def test_a_spilled_search_file_is_still_recognised(self):
        p = f"{webfetch.SPILL_DIR}/search-ruby_gem_check_if_country_is_in_eu.txt"
        self.assertEqual(loop._SEARCH_FILE_RE.search(p).group(0), p)

    def test_the_pointer_the_guard_prints_is_the_path_the_regex_reads(self):
        """The refusal's own sentence must round-trip, or cria is again naming a file nobody can
        open — the two are written in different modules."""
        target = webfetch.search_spill_name("ruby gem check if country is in eu")
        self.assertIsNotNone(loop._SEARCH_FILE_RE.search(target), target)

    def test_the_probe_still_excludes_crias_own_reference_material(self):
        """It listed the spill dir as the coder's workspace once, and the probe reported cria's 96 KB
        fetched spec as the deliverable."""
        self.assertIn(execcheck._SPILL_MARK, f"a/{webfetch.SPILL_DIR.lstrip('./')}/doc.txt")


if __name__ == "__main__":
    unittest.main()
