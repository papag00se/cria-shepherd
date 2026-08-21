"""cria shipped the literal `{{EXEC_FINDING}}` to coders for three days.

`remove(execcheck)` (98952c2, 2026-08-18) retired the seat that asked a model whether finishing the
task depended on running a program. It deleted the `exec_finding=` argument from all three callers
and left `{{EXEC_FINDING}}` sitting in `done_incomplete.txt`, one character after `{{REASON}}`. So
every completion re-nudge — the one seat whose whole job is to tell a coder plainly what is still
missing — ended with a piece of cria's own template. Four independent walks reported it.

`prompts.render` cannot catch this. A token it cannot fill is looked up as a FRAGMENT file, which is
how a shared rule gets one owner, and a token that names no fragment is left alone on purpose so
two-stage fills work. Both behaviours are right and neither can tell "filled later" from "filled
never".

WHAT IS CHECKABLE IS REACHABILITY. A token is reachable if something could ever put a value in it: a
fragment file of that name, a keyword argument spelled that way, or — for the install routes, whose
tool names are filled from a discovered binary — a string literal of that name in the code. A token
with none of those has no filler anywhere in the repo, and what reaches the model is the braces.
"""

import os
import re
import unittest

_CRIA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cria")
_PROMPTS = os.path.join(_CRIA, "prompts")


def _source() -> str:
    out = []
    for d, _, files in os.walk(_CRIA):
        if os.path.basename(d) == "prompts":
            continue
        out += [open(os.path.join(d, f), encoding="utf-8").read() for f in files if f.endswith(".py")]
    return "\n".join(out)


class EveryTokenHasSomewhereToComeFromTests(unittest.TestCase):
    def test_no_prompt_token_is_orphaned(self):
        src = _source()
        # `prompts.fill` matches its keyword arguments case-insensitively, and they are written both
        # ways: `reason=` for the ordinary tokens, `PACKAGE=`/`TOOL=` where the value is a binary name
        # cria discovered rather than a phrase it composed.
        kwargs = {m.lower() for m in re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*=", src)}
        literals = {m.lower() for m in re.findall(r"""["']([a-z][a-z0-9_]*)["']""", src)}
        fragments = {f[:-4] for f in os.listdir(_PROMPTS) if f.endswith(".txt")}
        for name in sorted(os.listdir(_PROMPTS)):
            if not name.endswith(".txt"):
                continue
            body = open(os.path.join(_PROMPTS, name), encoding="utf-8").read()
            for tok in sorted(set(re.findall(r"\{\{([A-Z][A-Z0-9_]*)\}\}", body))):
                with self.subTest(prompt=name, token=tok):
                    self.assertTrue(
                        tok.lower() in fragments or tok.lower() in kwargs or tok.lower() in literals,
                        f"{name} declares {{{{{tok}}}}} and nothing in cria/ can fill it — "
                        f"the braces are what the model reads")

    def test_the_completion_re_nudge_is_whole(self):
        """The seat it happened in, by name. This is the message a coder gets when a completion check
        could not confirm the work is done — and it ended in cria's own template."""
        from cria import prompts
        out = prompts.render("done_incomplete", reason="the CLI has no --json flag yet",
                             check_state=prompts.load_map("done_check_state")["never_ran"])
        self.assertNotIn("{{", out)
        self.assertIn("the CLI has no --json flag yet", out)


if __name__ == "__main__":
    unittest.main()
