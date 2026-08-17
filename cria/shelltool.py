"""Finding and shaping the harness's `shell` tool — the one primitive every harness
has, and cria's agnostic target for file writes and its own file ops."""

from __future__ import annotations

import re

# The names cria has MET. Kept because they are cheap and certain, not because the set is the rule —
# the rule is `is_shell_tool_name` below.
SHELL_TOOL_NAMES = {"shell", "bash", "exec_command", "local_shell", "run_terminal_cmd", "shell_command"}

# THE FAMILY, by shape (#18: match tools by family, not literal name). A closed list of six names is
# a literal-name rule wearing the word "family": Gemini CLI advertises `run_shell_command` and Cline
# `execute_command`, and on both of those cria answered "this harness has no shell" — which declines
# the plan loop, leaves the writeproxy with no lowering target, AND makes `focus_tools` DELETE the
# tool from the menu, because a tool in none of its three sets is dropped. The shell is the one
# primitive cria assumes every harness has; recognising it must not depend on having met it before.
#
# A word, not a substring soup: each token has to appear as a whole word once the name is split on
# `_`, `-` and `.`, or as the prefix of one (`exec` in `execute_command`). Checked against every tool
# name in the captures — read_file, list_dir, write_file, edit_file, view_image, web_search,
# web_fetch, update_plan, write_stdin, task_complete, verdict — none of which match.
_SHELL_NAME_TOKENS = ("shell", "bash", "exec", "terminal")
_NAME_SPLIT = ("_", "-", ".", " ")


def is_shell_tool_name(name) -> bool:
    """Is this the harness's shell/exec primitive, judged by its name's shape?"""
    n = (name or "").lower()
    if not n:
        return False
    if n in SHELL_TOOL_NAMES:
        return True
    parts = [n]
    for sep in _NAME_SPLIT:
        parts = [p for chunk in parts for p in chunk.split(sep)]
    return any(part.startswith(tok) for part in parts for tok in _SHELL_NAME_TOKENS)


def find_shell_tool(tools) -> dict | None:
    """The first shell-like tool the harness advertised, as ``{name, schema}``."""
    for t in tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        if is_shell_tool_name(fn.get("name")):
            return {"name": fn["name"], "schema": fn.get("parameters") or {}}
    return None


# The field a shell tool carries its command in, in preference order. Harnesses
# disagree: a plain `shell` uses `command`; Codex's `exec_command` uses `cmd`.
_CMD_FIELDS = ("command", "cmd", "shell_command", "input")


def shell_args(tool: dict, cmd: str) -> dict:
    """Shape a shell command to the tool's schema. Harnesses disagree on BOTH the
    field NAME (Codex `exec_command` → `cmd`; a plain `shell` → `command`) and the
    TYPE (a single string like Claude's Bash, or an argv array like Codex's shell).
    Pick the field the tool actually declares — honoring `required` — so the call
    isn't rejected for a missing field (which stalls the loop)."""
    schema = tool.get("schema") or {}
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    field = (
        next((f for f in _CMD_FIELDS if f in required and f in props), None)
        or next((f for f in _CMD_FIELDS if f in props), None)
        or "command"
    )
    if (props.get(field) or {}).get("type") == "array":
        return {field: ["bash", "-lc", cmd]}
    return {field: cmd}


# Milliseconds a composed GATE script may need end-to-end: each probe is bounded by its own
# `timeout -k 5 240` inside the script, and the slowest real gate is floor + lint + a pytest run.
# Without this, a harness's default exec yield (observed: Codex's 10s) cuts the composed script
# mid-pytest — the tail section returns headerless/EXIT-less and the tests silently never finish.
GATE_TIME_BUDGET_MS = 300_000

# Only fields whose NAME carries the unit are safe to set — a bare "timeout" is seconds on some
# harnesses and milliseconds on others, and a 300000-second timeout request is a rejection.
_TIME_BUDGET_FIELDS = ("yield_time_ms", "timeout_ms")


def with_time_budget(tool: dict, args: dict, ms: int = GATE_TIME_BUDGET_MS) -> dict:
    """Add a time budget to shell-tool args via whichever ms-unit field the tool's own schema
    declares (Codex: ``yield_time_ms``). Schema-driven — a tool that declares none is returned
    unchanged, and cria never invents a parameter the harness didn't advertise."""
    props = (tool.get("schema") or {}).get("properties") or {}
    for f in _TIME_BUDGET_FIELDS:
        if f in props:
            return {**args, f: ms}
    return args


# ---------------------------------------------------------------------------
# Does this command CHANGE something, or only report?

# By shape, not by a list of coreutils (#18/#20): a redirect, an in-place edit flag, a copy/move/
# create/remove verb, or a scripting one-liner opening a file for writing. Deliberately generous —
# every consumer so far asks "may I tell the model this call cannot have changed anything", and the
# honest answer to a maybe is no.
_SHELL_WRITE = re.compile(
    r"""(?x)
    (?<![0-9&])>>?\s*[^\s&|;]                 # > file / >> file, but not 2>&1 or >&2
  | \b(?:sed|perl|ruby)\b[^|;&]*\s-i\b        # in-place edit
  | \btee\b
  | \b(?:mv|cp|install|ln|touch|mkdir|rmdir|rm|unlink|truncate|dd|chmod|chown)\b
  | \b(?:patch|git\s+(?:apply|checkout|restore|stash|reset|clean|mv|rm))\b
  | \bopen\s*\([^)]*['"][wax]                 # python/ruby open(path, 'w')
  | \b(?:writeFileSync|writeFile|appendFileSync)\s*\(
  | \bFile\.(?:write|open)\b
  | \bprintf\b[^|;&]*>                        # printf ... > file
    """)

# Tools whose whole purpose is to change the workspace. Matched by name-part like the shell family,
# so an unfamiliar harness's `create_file` / `str_replace_editor` / `apply_patch` is still a write.
_WRITE_TOOL_PARTS = ("write", "edit", "create", "patch", "replace", "insert", "append", "delete",
                     "remove", "rename", "move", "mkdir")


def is_write_tool_name(name: str | None) -> bool:
    """The tool's NAME says it changes something. Same part-prefix rule as `is_shell_tool_name`."""
    for part in re.split(r"[_\-. ]+", (name or "").lower()):
        if any(part.startswith(p) for p in _WRITE_TOOL_PARTS):
            return True
    return False


def writes_something(name: str | None, command: str | None = None) -> bool:
    """Could this tool call have CHANGED the workspace?

    The question cria kept answering wrong. `focustrim` folds repeated identical calls and tells the
    coder *"it has told you everything it can — repeating it will return that same result"*, which is
    true of a reader and false of a writer. Walked on cycle 4 cell 14
    (`cart-billing-go × ternary-bonsai`, 15% useful): the note landed on a repeated `write_file` and
    then on a `sed -i`, and the coder drew the only conclusion the note supports —

        "the write_file tool seems to be caching the old content. Let me try a different approach"
        "the sed command is not working because the file content seems to be cached or something"

    — and from that turn on wrote its Go source through `python3 <<'PYEOF'` heredocs instead. Those
    are the writes cria's syntax floor never sees: a `\\t` swallowed inside the Python string turned
    `taxed` into `axed`, and bash backtick substitution ate the struct tags. The cell's famous typo is
    an artifact of a write the coder was driven to, not something it typed.

    Generous on purpose. Saying "this might have changed something" costs one un-folded pair of
    messages; saying it about a writer costs the run."""
    if is_write_tool_name(name):
        return True
    if not is_shell_tool_name(name):
        return False
    return bool(command and _SHELL_WRITE.search(command))
