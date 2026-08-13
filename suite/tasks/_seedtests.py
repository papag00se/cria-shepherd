"""Seeded-test integrity, per test function, for every language in the battery.

THE ANTI-CHEAT. A task that ships a failing test and asks for it to be fixed has one obvious way to
go green that is not a fix: delete the test, or weaken what it asserts. Every seeded suite must
therefore survive the run intact.

THE FAULT THIS MODULE EXISTS TO PREVENT. Expressing that as "the seed file must be byte-identical"
breaks the task's own instructions. `shipping-rates-py` says *"Don't change what the tests assert"*
and, two paragraphs later, *"Add it, with tests"*; `cart-billing-go` says *"add a test so it can't
come back"*. The obvious place to add a test is the file that already has tests — so the honest
solution and the cheat produce the same verdict, and the honest one is the more likely.

Both were measured on real baseline runs, in two different languages, by two different models:

  shipping-rates-py   gemma4 appended three correct express tests, deleted nothing, weakened
                      nothing, left the suite green at 10 passed. Scored 3/4. True score 4/4.
  cart-billing-go     gemma4 inserted exactly the regression test the prompt asked for, an 18-line
                      pure insertion with all three seeded tests untouched. Scored 3/4. True 4/4.

The rule that is actually wanted: **every seeded test still exists, and its body is unchanged.
Additions are free.** A deleted test is missing; a weakened one has different source. Both are
still caught, and a model that does what it was told is not punished for it.

Blank lines and trailing whitespace are ignored, so a reformat is not read as a contract change.
Anything that alters an assertion alters the text.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

# Ruby: `def test_x` … `end` at the SAME indent — the shape minitest mandates.
RUBY_DEF = re.compile(r"^([ \t]*)def\s+(test_\w+)", re.M)
# Go: `func TestX(` … a closing brace in column 0, which gofmt guarantees for a top-level func.
GO_FUNC = re.compile(r"^func\s+(Test\w+)\s*\(", re.M)


# A line that is ENTIRELY a comment, in every language the battery seeds. Not trailing comments —
# stripping those means parsing string literals, and `//` inside a URL in an assertion would be
# mangled by a regex that tried.
COMMENT_ONLY = re.compile(r"^\s*(#|//)")


def _norm(lines) -> str:
    """Normalise a test body for comparison: drop blank lines, trailing whitespace, and
    comment-only lines.

    Comments are dropped because they cannot change what a test asserts, and a model explaining an
    existing test is doing something good. Measured: gemma4 added one line —
    `// 10 * 0.9 = 9.0; 9.0 * 1.08 = 9.72` — inside a seeded Go test while changing no assertion,
    and was scored as having rewritten the contract. That was the fourth instrument fault of the
    day and, like the other three, it punished a defensible answer.

    The limit is deliberate: a trailing comment appended to an assertion line still reads as a
    change. Removing those requires distinguishing a comment from a `//` inside a string literal,
    which is a parser, and the failure mode of getting it wrong is silently accepting a weakened
    assertion — the exact thing this function exists to catch."""
    return "\n".join(l.rstrip() for l in lines
                     if l.strip() and not COMMENT_ONLY.match(l))


def python_tests(src: str) -> dict[str, str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            out[node.name] = _norm((ast.get_source_segment(src, node) or "").splitlines())
    return out


def ruby_tests(src: str) -> dict[str, str]:
    out, lines = {}, src.splitlines()
    for m in RUBY_DEF.finditer(src):
        indent, name = m.group(1), m.group(2)
        start = src[: m.start()].count("\n")
        body = [lines[start]]
        for line in lines[start + 1:]:
            body.append(line)
            if line.rstrip() == f"{indent}end":
                break
        out[name] = _norm(body)
    return out


def go_tests(src: str) -> dict[str, str]:
    out, lines = {}, src.splitlines()
    for m in GO_FUNC.finditer(src):
        start = src[: m.start()].count("\n")
        body = [lines[start]]
        for line in lines[start + 1:]:
            body.append(line)
            if line.rstrip() == "}":
                break
        out[m.group(1)] = _norm(body)
    return out


EXTRACT = {"python": (python_tests, "*.py"), "ruby": (ruby_tests, "*.rb"), "go": (go_tests, "*.go")}


# The VALUES a test asserts: numbers and quoted strings, in order. This is the contract — what the
# test says must be true. How it says it is syntax, and syntax is sometimes forced to change by the
# task itself.
#
# cart-billing-go seeds `func (c *Cart) Subtotal() float64` and a test reading `got != 15.00`, then
# asks the model to stop doing money arithmetic in floating point. Return a decimal, as the task
# plainly implies, and that seeded line NO LONGER COMPILES — so the model rewrites it as
# `got.StringFixed(2) != "15.00"` and this module failed the run for editing a seeded test.
# 7 of 19 attempts lost that check to exactly this, three models, both arms.
#
# The literals decide it. `15.00` surviving means the contract survives; `14.00`, or the literal
# vanishing, means it does not. A weakened assertion still changes a number or drops one, so the
# anti-cheat this module exists for is intact — the seeded test must still exist, must still be run,
# and must still demand the same values. Only the spelling is forgiven (operator ruling: a check may
# only fail a run over the property the task actually asks for).
_LITERALS = re.compile(r'"[^"]*"|\'[^\']*\'|`[^`]*`|\b\d+(?:\.\d+)?\b')


def asserted_values(body: str) -> list[str]:
    """The numbers and strings a test body asserts, in order, ignoring how they are compared."""
    out = []
    for tok in _LITERALS.findall(body):
        s = tok.strip("\"'`")
        if not s:
            continue
        try:                       # 15 and 15.00 are the same contract
            out.append(f"{float(s):g}")
        except ValueError:
            out.append(s)
    return out


def unchanged(seed_dir: Path, ws: Path, lang: str, glob: str | None = None) -> tuple[bool, str]:
    """Every seeded test still present in the workspace with its body intact. Additions are free.

    `seed_dir` is where the task's own seeded test files live; the workspace is searched whole, so
    moving a test to another file is not a failure — only losing or editing it is.
    """
    extract, pattern = EXTRACT[lang]
    seeded: dict[str, tuple[str, str]] = {}
    for f in sorted(seed_dir.rglob(glob or pattern)):
        for name, body in extract(f.read_text(errors="replace")).items():
            seeded[name] = (f.name, body)
    if not seeded:
        return True, "no seeded tests to protect"
    live: dict[str, str] = {}
    for p in ws.rglob(pattern):
        if ".git" in p.parts or "vendor" in p.parts or "node_modules" in p.parts:
            continue
        live.update(extract(p.read_text(errors="replace")))
    adapted: list[str] = []
    for name, (fname, body) in sorted(seeded.items()):
        if name not in live:
            return False, f"seeded test {name} from {fname} was deleted"
        if live[name] != body:
            # Same values asserted → the model adapted the syntax, which the task can force. A real
            # weakening changes a number or drops one, and still fails here.
            # CONTAINMENT, not equality. Adapting the syntax ADDS literals — `StringFixed(2)` puts a
            # 2 in the body that asserts nothing. What must not happen is a seeded value going
            # missing: 15.00 becoming 14.00 drops a 15, and is caught.
            want, have = Counter(asserted_values(body)), Counter(asserted_values(live[name]))
            missing = want - have
            if missing:
                return False, (f"seeded test {name} was weakened — it no longer asserts "
                               f"{sorted(missing.elements())}")
            adapted.append(name)
    added = len(live) - len(seeded)
    note = f"all {len(seeded)} seeded tests intact"
    if adapted:
        note += f", {len(adapted)} rewritten but asserting the same values ({', '.join(adapted)})"
    return True, note + (f", {added} added" if added > 0 else "")
