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
# A VERB ONLY COUNTS IN COMMAND POSITION. Reading the word anywhere in the line is the same defect
# the walks kept finding in cria's own matchers: `grep -n "install" README.md`, `grep -rn touch src/`,
# `go doc cp` and `echo "do not rm anything"` are all read-only, and all four matched a bare `\b(mv|
# cp|install|…)\b`. Anchored to the start of the line or to what follows `;`, `&&`, `||`, `|` or `(`,
# none of them do — and every real invocation still does, because that is where a command goes.
_CMD_POS = r"(?:^|[;&|(\n]|&&|\|\|)\s*(?:sudo\s+|env\s+\S+=\S+\s+)*"
_SHELL_WRITE = re.compile(
    r"""(?xm)
    (?<![0-9&])>>?\s*[^\s&|;]                 # > file / >> file, but not 2>&1 or >&2
  | \b(?:sed|perl|ruby)\b[^|;&]*\s-i\b        # in-place edit
  | """ + _CMD_POS + r"""(?:tee|mv|cp|install|ln|touch|mkdir|rmdir|rm|unlink|truncate|dd|chmod|chown|patch)\b
  | """ + _CMD_POS + r"""git\s+(?:apply|checkout|restore|stash|reset|clean|mv|rm)\b
    # A package manager's SUBCOMMAND, by shape rather than by a list of managers: `gem install`,
    # `npm add`, `pip uninstall`, `cargo add`, `apt remove`, `go get`. Every one of them changes
    # state — a global install writes outside the project, a local one populates it.
    #
    # The second row is the same verb family for the managers that POPULATE from a lockfile rather
    # than adding to it: `go mod download`, `go mod vendor`, `npm ci`, `dotnet restore`, `uv sync`.
    # Missing them cost a go cell eleven calls — `go mod download` created go.sum, cria's staleness
    # ledger saw no change, and the gate went on reporting `missing go.sum entry` as a current fact.
    #
    # The optional middle token carries the managers that put the verb third — `go mod download`,
    # `go mod vendor`, `git submodule update`. It may not begin with `-`, which is what keeps
    # `grep -n install README.md` and `grep -rn touch src/` out: a FLAG there means the word after it
    # is an argument, not a subcommand.
  | """ + _CMD_POS + r"""\S+\s+(?:[^-\s]\S*\s+)?(?:install|uninstall|add|remove|update|upgrade|get
                                                 |download|fetch|restore|sync|vendor|ci)\b
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


# A tool that READS the workspace — the other half of the file-op family. Same part-prefix rule.
_READ_TOOL_PARTS = ("read", "cat", "view", "open", "show", "list", "ls", "dir", "glob", "find",
                    "search", "grep")


def is_read_tool_name(name: str | None) -> bool:
    """The tool's NAME says it inspects the workspace without changing it."""
    for part in re.split(r"[_\-. ]+", (name or "").lower()):
        if any(part.startswith(p) for p in _READ_TOOL_PARTS):
            return True
    return False


# …AND NOT ABOUT SOMETHING THAT IS NOT THE WORKSPACE. `create`, `list` and `read` are also how a
# harness names its goal store, its MCP registry and its memory — `create_goal`, `list_mcp_resources`,
# `read_mcp_resource`, `save_memory` — which is the exact firehose the focus menu exists to drop.
# The shape rule says "this verb touches something"; this says which somethings are not files.
_NOT_WORKSPACE_PARTS = ("goal", "mcp", "resource", "resources", "memory", "plugin", "connector",
                        "todo", "browser", "notification")


def is_file_tool_name(name: str | None) -> bool:
    """A file operation of either kind — the family the focus menu must never drop.

    `toolmenu` kept a six-name LITERAL set for this (`write_file`, `create_file`, `edit_file`,
    `str_replace`, `read_file`, `list_dir`) under a comment calling them "FAMILIES", while the shell
    beside them was matched by shape. Simulated through the real gate: Gemini CLI's menu lost
    `replace`, `list_directory`, `glob` and `search_file_content`, and Cline's lost `search_files`
    and `list_code_definition_names` — every one a file operation the coder needs."""
    parts = re.split(r"[_\-. ]+", (name or "").lower())
    if any(p in _NOT_WORKSPACE_PARTS for p in parts):
        return False
    return is_write_tool_name(name) or is_read_tool_name(name)


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
    return bool(command and _SHELL_WRITE.search(_without_quoted(command)))


def _without_quoted(command: str) -> str:
    """The command with quoted spans blanked out, so a verb inside a STRING is not a verb.

    `grep -n "install" README.md` and `echo "do not rm anything"` read as writes otherwise — the same
    "a match is not a meaning" defect (#23b) the walks kept finding in cria's other matchers. Blanked
    rather than removed, so every offset in the line still lines up."""
    out, quote = [], ""
    for ch in command or "":
        if quote:
            out.append(" " if ch != quote else ch)
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        else:
            out.append(ch)
    return "".join(out)
