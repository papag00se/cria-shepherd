"""Refuse to replace a file that parses with content that does not (docs/harness-primitives.md 8.2): the table, decided in cria.

``None`` means "no known fault": the content parses, or cria cannot judge it (no checker for the extension, the tool is not installed
where the files are, a timeout, text that is not UTF-8). UNKNOWN STAYS SAFE: it never refuses, so the guard stays regression-only -
it may only refuse replacing a file that currently parses.

The extension table was once missing rows: cria's own write path corrupted a ``pom.xml`` with nothing detecting it (without rows for
``.rb/.go/.java/.rs/.js`` it let cria replace parsing files with non-parsing ones, and an unreadable Ruby refusal made a coder discard
a correct implementation). Per-language entries are correct here - every language gets its equivalent check; the defect was the missing
rows, not the table.

Where each check runs: ``.py .pyi .json .xml .toml`` in this process; ``.rb .js .mjs .cjs .php .go`` only where the tool is, through the
harness ``run`` stub (a fixed script: the checker's own command line on a copy of the candidate in the run's own private directory).
The copy keeps the extension - node reads ``.mjs`` as a module and ``.js`` as CommonJS by extension, which a script on standard input
cannot say - and the checker's own file name is replaced by the file's by cria.
"""
import base64
import hashlib
import re

XML_MAX = 1 << 20          # a larger document is not checked here: UNKNOWN
TIMEOUT = 20               # seconds the harness gives a checker before it is killed (UNKNOWN)
# Checkers do not load ambient interpreter hooks from the harness environment.
BLOCKED_ENV = ("NODE_OPTIONS", "NODE_PATH", "RUBYOPT", "RUBYLIB", "RUBYGEMS_GEMDEPS", "PHPRC", "PHP_INI_SCAN_DIR")
# extension -> the checker's command line (`$f` is the candidate's copy); `gofmt` prints the formatted source on success, which is not wanted
HARNESS = {".rb": "ruby -c", ".js": "node --check", ".mjs": "node --check", ".cjs": "node --check", ".php": "php -l", ".go": "gofmt -e"}
LOCAL = (".py", ".pyi", ".json", ".xml", ".toml")
CAND = "cand"


def extension(path: str) -> str:
    low = path.lower()
    dot = low.rfind(".")
    return low[dot:] if dot >= 0 else ""


def kind(path: str) -> str:
    """``local`` (checked in this process), ``harness`` (checked by the tool where the files are) or ``none``."""
    ext = extension(path)
    return "local" if ext in LOCAL else "harness" if ext in HARNESS else "none"


def check_local(path: str, text: str) -> str | None:
    """The parser's own message for ``text`` as the file ``path``, or None (parses, or cannot be judged here)."""
    ext = extension(path)
    try:
        if ext in (".py", ".pyi"):
            compile(text, path, "exec")
        elif ext == ".json":
            import json
            json.loads(text)
        elif ext == ".xml":
            if len(text) > XML_MAX:
                return None
            from xml.etree import ElementTree
            ElementTree.fromstring(text)
        elif ext == ".toml":
            import tomllib
            tomllib.loads(text)
    except Exception as exc:         # the checker's own words, whatever it raised
        return str(exc)
    return None


def candidate_text(raw: "bytes | str") -> "str | None":
    """The text a check judges: UTF-8, else None (UNKNOWN)."""
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return None


def script(path: str, data: bytes, budget: int | None = None) -> str | None:
    """The shell script the ``run`` stub runs to check ``data`` as the file ``path`` (None: no harness checker for it, or it would
    not fit one command, which is UNKNOWN). The candidate travels as one line of base64 (exact bytes: CRLF and NUL survive), is
    written under the extension to a file beside the script - the run's own private directory, removed when the script ends - and
    the checker's command line runs on it. No temporary file is made anywhere else."""
    ext = extension(path)
    argv = HARNESS.get(ext)
    if argv is None:
        return None
    body = base64.b64encode(data).decode()
    if budget is not None and len(body) > budget:
        return None
    unset = " ".join(f"-u {name}" for name in BLOCKED_ENV)
    quiet = " >/dev/null" if ext == ".go" else ""
    terminator = "CTX_IN_" + hashlib.sha256(body.encode()).hexdigest()[:12]      # base64 has no underscore: it can never be a line of the body
    return (f'cd "$(dirname "$0")" || exit 127\nf={CAND}{ext}\ntrap \'rm -f "$f"\' EXIT\n'
            f"/usr/bin/base64 -d > \"$f\" <<'{terminator}'\n{body}\n{terminator}\n"
            f'/usr/bin/env {unset} {argv} "$f"{quiet}\n')


# The run's private directory as a checker may print it: under the harness's temporary directory as given or as the checker resolved it
# (a symlinked TMPDIR: node prints the real path), in front of the copy's name.
_RUN_DIR = re.compile(r"[^\s'\"(:]*\.ctx-run-[0-9a-f]+/")


def interpret(path: str, exit_code, timed_out, output: bytes) -> str | None:
    """The checker's verdict from its run: None when it parsed or could not be run (not installed: 126/127, killed at the timeout),
    else its own words with the copy's name replaced by the file's (the path is the one part of this that carries no information:
    the coder knows which file it tried to write; a message cut to a length budget used to be all path)."""
    if exit_code in (0, 126, 127) or timed_out or exit_code is None:
        return None
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    message = output.decode("utf-8", "replace").strip()
    ext = extension(path)
    message = _RUN_DIR.sub("", message)                    # node prints the copy's absolute path
    message = message.replace(f"./{CAND}{ext}:", base + ":").replace(f"{CAND}{ext}:", base + ":").replace(f"{CAND}{ext}", base)
    message = message.replace(base + ": " + base + ":", base + ":")
    return message if message else "does not parse"


_LINE = re.compile(r"line\s+(\d+)"), re.compile(r"[\w./\-]+\.\w+:(\d+)\b")


def at(content: "bytes | str", message: str) -> str:
    """The line of the content the coordinate in ``message`` points at.

    The refusal used to carry only the parser's message - "not well-formed (invalid token): line 34, column 1" - into content the coder
    cannot re-read (a rejected payload is elided from the history). A line number into an invisible document points at nothing.
    Walked on cycle 4 cell 22 (`feed-pipeline-java x nemotron-elastic`, 5% useful): eight refusals of pom.xml, every one at line 34, and
    line 34 of the content the model sent was `</function>` - a tool-call terminator that had been swallowed into the file body. Across
    all eight the model's reasoning never once mentions line 34. The sibling EDIT path has done this right for months: it quotes the
    file's real text around the divergence.

    BOTH SHAPES A CHECKER EMITS. This matched `line\\s+(\\d+)` only - Python's compile() and an XML parser say "line 34, column 1", which
    is the run this helper was written for. Ruby says `rates.rb:36:`, and so do `node --check`, `php -l` and `gofmt -e`. A matcher keyed
    to one tool's phrasing is inert on every other tool. `node --check` prints `f.js:3` with NO trailing colon, `gofmt -e` prints
    `f.go:3:5`, ruby and php print `f.rb:36:`. Requiring a filename-shaped token before the number keeps a port or a timestamp in the
    message from being read as a line."""
    try:
        text = candidate_text(content)
        found = _LINE[0].search(message or "") or _LINE[1].search(message or "")
        if text is None or not found:
            return ""
        n = int(found.group(1))
        lines = text.splitlines()
        if not 1 <= n <= len(lines):
            return ""
        # The line goes whole - a cap here cuts exactly the long line most likely to be the fault.
        return " Line %d of the content you sent is: %s" % (n, lines[n - 1].strip())
    except Exception:
        return ""
