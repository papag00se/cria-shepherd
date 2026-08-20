"""Does this text contain a SHELL COMMAND? One owner, with a confidence score.

WHY THIS EXISTS. cria already answered this question in three places, differently, and they
disagreed:

  * ``loop._CODE_LINE`` — a line-start alternation used to decide whether an authored steer
    DICTATES code. It knows ``sudo``, ``pip install``, ``sed -i``, ``cat ``, ``grep -n``, ``pytest``
    and nothing else.
  * ``loop._shell_write_target`` — a redirect/heredoc/``tee`` scan used by the wheel-spin guard. It
    answers "which FILE does this write", not "is this a command".
  * ``dirguard`` — install/kill/destructive patterns, scoped to safety refusals.

The gap between the first two cost a run. Walked on `feed-pipeline-java x qwen35` (2026-08-19) call
0270: the flail steer told the coder ``Run `cat > REVIEW.md << 'EOF'` with file name and line
numbers``. That heredoc appears nowhere the coder had written — the reasoner invented it — but
``_CODE_LINE`` matched nothing in it, so ``_strip_invented_code`` reported zero spans, so the
restate path (gated on that count) never ran, and the command shipped byte-identical.

A SCORE, NOT A BOOLEAN, because the callers want different bars. Refusing to deliver a steer is
expensive and wants near-certainty; deciding to spend one reasoner call on a restatement is cheap
and wants a low bar. A single predicate forces one threshold on both, and the last time that
happened the strict caller set the bar and the cheap caller inherited its blindness.

WHAT THIS IS NOT. It does not parse shell, and it must not: the input is prose that may CONTAIN a
command, not a script. It scores the shapes a command has and prose does not, and it is deliberately
conservative about words that are also English — `cat`, `find`, `make`, `test`, `touch` and `less`
score nothing on their own, because "find the bug", "make it work" and "cat the file" are sentences
someone writes about code as often as commands they run.
"""
from __future__ import annotations

import re

# ---- the signals -------------------------------------------------------------------------------
#
# Each is a (regex, weight, name). Weights are the odds cria is willing to act on, not probabilities:
# a redirect into a filename is nearly conclusive on its own; a bare binary name is barely a hint.

# A heredoc — `<<EOF`, `<< 'EOF'`, `<<-EOF`. Nothing in prose has this shape.
_HEREDOC = re.compile(r"<<-?\s*['\"]?\w+")
# A redirect into a target that is not /dev/null and not a comparison (`>` after a word, then a path
# or filename). `a > b` in prose is a comparison; `> REVIEW.md` is a redirect.
# A BARE NUMBER after `>` is a comparison, not a target: "if v > 0", "rows > 100". A redirect writes
# somewhere nameable.
_REDIRECT = re.compile(r"(?<![-=<>\d\s])\s*>{1,2}\s*(?!/dev/|&|=|\d+\b)['\"]?[\w./~$-]*\.?\w+")
# A pipe into a known filter. Prose does not pipe.
_PIPE = re.compile(r"\|\s*(?:head|tail|grep|rg|wc|sort|uniq|awk|sed|jq|less|xargs|tee|cut|tr)\b")
# Command chaining.
_CHAIN = re.compile(r"(?:&&|\|\||;\s*(?=\w+\s))")
# A short flag or a long flag attached to a word: `-la`, `--no-fail-fast`, `-Dexec.mainClass=`.
_FLAG = re.compile(r"(?:^|\s)-{1,2}[A-Za-z][\w.-]*(?:=\S+)?")
# A binary that is never an English word in ordinary prose.
_HARD_BINARY = re.compile(
    r"(?:^|[\s;&|(`$])(?:npm|npx|pnpm|yarn|pip3?|pytest|cargo|mvn|gradle|go|rustc|javac|"
    r"tsc|node|deno|bundle|gem|composer|dotnet|git|docker|kubectl|systemctl|curl|wget|"
    r"chmod|chown|mkdir|rmdir|ln|scp|rsync|ssh|tar|unzip|gunzip|sudo|apt|apt-get|brew|"
    r"yum|dnf|pacman|pkill|lsof|netstat|xargs)\b")
# `source`, `go`, `env`, `export`, `read`, `kill`, `test`, `ps`, `ss`, `df` and `du` were here and
# came out: every one is ordinary English ("set it in the source", "go to the file", "kill the
# process that owns it"), and each fired on a steer that was prose.
# A binary that IS an English word — only counted when something else already looks like a command.
# ORDINARY ENGLISH IS NOT ON THIS LIST. `find`, `make`, `test`, `time`, `read`, `which`, `sort`,
# `diff`, `patch`, `touch`, `less` and `more` were tried here and every one of them fired on a real
# steer that was plain prose ("find the bug", "make it work", "decide which is larger"). What is left
# is words that appear in prose rarely enough to be worth a hint — and a hint is all they are, since
# nothing here can carry a verdict on its own.
_SOFT_BINARY = re.compile(
    r"(?:^|[\s;&|(`$])(?:cat|ls|cp|mv|rm|head|tail|grep|sed|awk|echo|wc|tee|"
    r"python3?|ruby|java|sh|bash)\b")
# A shell prompt or fence the model wrote around it.
_FENCE = re.compile(r"```(?:bash|sh|shell|zsh|console|terminal)?\b|^\s*\$\s+\S", re.M)
# An assignment-then-command, `FOO=bar cmd` — a shape prose never has.
_ENV_PREFIX = re.compile(r"(?:^|\s)[A-Z_][A-Z0-9_]*=\S+\s+\w")
# THE LINE OPENS WITH A BINARY. This is what separates `sed -i 's/a/b/' main.rs` from "use sed -i to
# fix it", and `pip install x` from "(cargo run)" in a sentence about the README. A command is
# something you would paste; prose mentions the same word in passing, mid-clause.
_LINE_START_BINARY = re.compile(
    r"^\s*(?:\$\s*)?(?:npm|npx|pnpm|yarn|pip3?|pytest|cargo|mvn|gradle|go|rustc|javac|tsc|node|"
    r"deno|bundle|gem|composer|dotnet|git|docker|kubectl|systemctl|curl|wget|chmod|chown|mkdir|"
    r"rmdir|ln|scp|rsync|ssh|tar|unzip|sudo|apt|apt-get|brew|yum|dnf|pacman|ps|kill|pkill|lsof|"
    r"ss|netstat|df|du|env|export|source|xargs|cat|ls|cd|cp|mv|rm|touch|make|test|less|more|head|"
    r"tail|grep|sed|awk|echo|sort|uniq|wc|tee|diff|patch|which|time|find|python3?|ruby|java|sh|"
    r"bash)\b"
    # ...AND WHAT FOLLOWS IT IS NOT AN ENGLISH FUNCTION WORD. "cat the file", "ls of the directory"
    # and "echo of that" all open with a binary and are all sentences. A command's next token is a
    # flag, a path, a subcommand or a redirect — never "the". (`for`/`while`/`if` were in the binary
    # list above and came out for the same reason: "if v > 0" is not a shell loop.)
    r"(?!\s+(?:the|a|an|of|that|this|it|its|and|or|to|in|on|at|for|with|is|was|were|from|"
    r"there|these|those|all|any|each|both|when|while|if|so|but)\b)", re.M)

_SIGNALS = (
    (_HEREDOC,     0.70, "heredoc"),
    (_LINE_START_BINARY, 0.45, "line-start"),
    (_REDIRECT,    0.55, "redirect"),
    (_PIPE,        0.50, "pipe"),
    (_FENCE,       0.45, "fence"),
    (_ENV_PREFIX,  0.40, "env-prefix"),
    (_HARD_BINARY, 0.40, "binary"),
    (_CHAIN,       0.30, "chain"),
    (_FLAG,        0.25, "flag"),
    (_SOFT_BINARY, 0.15, "word-binary"),
)

# NEITHER OF THESE CARRIES A VERDICT ALONE. An English-word binary is prose more often than not, and
# a lone `>` is a comparison at least as often as a redirect ("a.b > c.d", "if v > 0"). Together they
# are a command: `echo done > out.txt` is both, and is not a sentence anyone writes.
_NEEDS_CORROBORATION = {"word-binary", "redirect"}

# The bar a caller should use when the consequence is REFUSING to deliver something. High, because
# a false positive here costs the coder a real message.
REFUSE_BAR = 0.75
# The bar when the consequence is spending one reasoner call to restate. Low, because a false
# positive costs a call and the restater can only say less, never something different.
RESTATE_BAR = 0.45


def signals(text: str) -> list[str]:
    """Which command-shapes ``text`` carries, strongest first — [] for prose.

    Exposed because a score with no account of itself is a number cria cannot defend (#12), and
    because the caller that refuses something should be able to log WHY."""
    if not text:
        return []
    hits = [(w, name) for pat, w, name in _SIGNALS if pat.search(text)]
    weak = [n for _w, n in hits if n in _NEEDS_CORROBORATION]
    strong = [n for _w, n in hits if n not in _NEEDS_CORROBORATION]
    # One strong signal stands alone. Two weak ones corroborate each other. One weak one is prose.
    if not strong and len(weak) < 2:
        return []
    return [name for _w, name in sorted(hits, reverse=True)]


# A COMMAND IS SHORT AND DENSE; PROSE IS LONG AND SPARSE. Scoring a whole block lets signals
# ACCUMULATE with length, so a long enough paragraph crosses any bar on scattered evidence. Measured
# on a real re-orientation note (20260819T133948 call 0110): 976 characters of correct prose about
# what had been built scored 0.73 — a `gem` here, a flag there, a dotted path somewhere else — and
# the caller replaced the entire paragraph with a marker. The command that actually cost a run,
# `cat > REVIEW.md << 'EOF'`, is 24 characters carrying three signals.
#
# So the unit of scoring is a SEGMENT: a line, or a sentence within a line. The score of a block is
# the score of its strongest segment, never the sum of its parts.
_SEGMENT = re.compile(r"[^\n.;!?]+(?:[.;!?]+|$)")


def segments(text: str) -> list[str]:
    """``text`` split into scorable units — lines, and sentences within a line.

    A fenced block is kept whole: everything between ``` fences is one segment, because a script's
    lines are a command each and splitting them hides that they arrived together."""
    out: list[str] = []
    for block in re.split(r"(```[\s\S]*?```)", text or ""):
        if block.startswith("```"):
            out.append(block)
            continue
        for line in block.splitlines():
            out.extend(m.group(0).strip() for m in _SEGMENT.finditer(line) if m.group(0).strip())
    return out


def _score_one(text: str) -> float:
    """The raw score of a single segment — no splitting."""
    names = set(signals(text))
    if not names:
        return 0.0
    p = 1.0
    for _pat, w, name in _SIGNALS:
        if name in names:
            p *= (1.0 - w)
    return round(1.0 - p, 3)


def confidence(text: str) -> float:
    """How strongly ``text`` looks like it contains a shell command, 0.0–1.0.

    Within a segment, signals combine as independent evidence — ``1 - Π(1 - w)`` — rather than
    summed, so three weak signals raise confidence without exceeding certainty, and adding a new
    signal can never lower an existing score. ACROSS segments the score is the MAXIMUM, never the
    combination: a command mentioned in one sentence does not make the paragraph around it a
    command, and a paragraph is not more command-like for being long."""
    if not text:
        return 0.0
    return max((_score_one(seg) for seg in segments(text)), default=0.0)


def looks_like_command(text: str, bar: float = RESTATE_BAR) -> bool:
    """``confidence(text) >= bar``. The bar is the caller's, deliberately — see the module docstring."""
    return confidence(text) >= bar


def command_lines(text: str, bar: float = RESTATE_BAR) -> list[str]:
    """The individual LINES of ``text`` that carry a command, for a caller that wants to act on one.

    Scored per line, because a directive is mostly prose with a command in it, and the prose is the
    part worth keeping."""
    return [ln for ln in (text or "").splitlines() if confidence(ln) >= bar]
