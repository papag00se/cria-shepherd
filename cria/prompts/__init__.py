"""Prompt templates, kept as plain-text files in THIS folder so every prompt cria sends
a model can be found, read, and tuned without touching Python.

Placeholders are ``{{UPPERCASE}}`` tokens filled at call time. Double braces are used on
purpose: a literal single brace — e.g. the JSON ``{"done": true}`` the critic is told to
emit — passes through untouched. Files are re-read on every call, so editing a ``.txt``
here takes effect on the next request with no restart.

- ``load(name)``         → the whole file ``<name>.txt``, verbatim (trailing newlines trimmed).
- ``render(name, **kw)`` → ``load`` + fill every ``{{TOKEN}}`` from the keyword args.
- ``fill(text, **kw)``   → fill ``{{TOKEN}}``s in an arbitrary string (e.g. a map value).
- ``load_map(name)``     → parse a ``key = value`` file into a dict, for the two prompts
                          assembled from several fragments (the tool cheat-sheet and the
                          critic's user message). ``\\n`` in a value becomes a real newline.
"""

from __future__ import annotations

import re
from pathlib import Path

_DIR = Path(__file__).parent


def fill(text: str, **tokens: object) -> str:
    """Replace every ``{{TOKEN}}`` in ``text`` with the matching keyword arg (the key is
    upper-cased, so ``fill(t, step=x)`` fills ``{{STEP}}``). Tokens with no arg are left
    in place; single braces are never touched."""
    for key, value in tokens.items():
        text = text.replace("{{" + key.upper() + "}}", str(value))
    return text


def load(name: str) -> str:
    """The raw text of ``<name>.txt`` with trailing newlines trimmed (editors add one;
    the prompt strings don't want it). Placeholders are left intact."""
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n")


def render(name: str, **tokens: object) -> str:
    """``load(name)`` then ``fill`` its ``{{TOKEN}}``s from the keyword args.

    A LEFTOVER TOKEN THAT NAMES A PROMPT FILE IS AN INCLUDE. A rule the model must be told in more
    than one place should have ONE owner, and the way to share it is a fragment file — but a token
    every caller has to remember to pass is a token some caller will forget, and what reaches the
    model then is the literal `{{SEEDED_TEST_RULE}}`. That is not hypothetical: the seeded-test rule
    was typed into three carriers, an update reached two of them, and the copy that ships in 3,254
    captured prompts spent a whole cycle telling coders "changing the test is not a fix" without the
    sentence that says which tests it governs.

    So a `{{FOO}}` the caller did not fill is looked up as the prompt file `foo`, and left exactly as
    it was when there is no such file (an unfilled token still fails `no placeholder reaches the
    model`, which is the guard that caught this)."""
    out = fill(load(name), **tokens)
    for tok in set(re.findall(r"\{\{([A-Z][A-Z0-9_]*)\}\}", out)):
        try:
            frag = load(tok.lower()).strip()
        except (FileNotFoundError, OSError):
            continue
        out = out.replace("{{" + tok + "}}", frag)
    return out


def load_map(name: str) -> dict[str, str]:
    """Parse a ``key = value`` prompt file into a dict. Blank lines and ``#`` comments are
    skipped; a literal ``\\n`` in a value becomes a newline."""
    out: dict[str, str] = {}
    for line in load(name).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(" = ")
        if sep:
            out[key.strip()] = value.replace("\\n", "\n")
    return out


_REF_RE = None


def validate_referenced(rlog=None) -> list[str]:
    """BOOT-TIME check: every prompt name the package source references via load()/render()/
    load_map() must exist as a .txt file. A missing prompt otherwise surfaces as a runtime crash on
    first use — measured: a mid-run rename left the live service referencing a deleted file, and
    the first compaction request died with FileNotFoundError six times, killing the whole run (g4).
    Returns the missing names (empty = healthy); the caller decides whether to refuse to start."""
    import re
    pat = re.compile(r"""prompts\.(?:load|render|load_map)\(\s*["']([\w-]+)["']""")
    missing: set[str] = set()
    for py in _DIR.parent.glob("*.py"):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in pat.findall(src):
            if not (_DIR / f"{name}.txt").exists():
                missing.add(name)
    out = sorted(missing)
    if out and rlog is not None:
        rlog.emit("prompts.missing", level="error", names=",".join(out))
    return out


# A BOUNDED LIST OF NAMES, WITH ITS REMAINDER. Seven sites printed `names[:N]` into a model-facing
# sentence with a bare integer literal, no named constant and no marker — and three of them under
# wording that asserts completeness. `focustrim`'s superseded note listed six paths while its own
# count field counted CALLS, so the model was told "9 earlier write(s) removed: a, b, c, d, e, f"
# and had no way to learn which three files the missing bytes belonged to.
#
# This is the only sanctioned way to print a bounded list of names to a model. The remainder is
# derived from the same list that was printed, so the two can never disagree (#5b).
def named_list(items, cap: int = 6, unit: str = "") -> str:
    """``"a, b, c"`` — or ``"a, b, c, and 4 more <unit>"`` when the list was longer than ``cap``."""
    names = [str(x) for x in (items or []) if str(x).strip()]
    if not names:
        return ""
    shown, rest = names[:max(cap, 1)], max(0, len(names) - max(cap, 1))
    out = ", ".join(shown)
    if rest:
        out += f", and {rest} more{(' ' + unit) if unit else ''}"
    return out
