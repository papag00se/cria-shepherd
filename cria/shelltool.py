"""Finding and shaping the harness's `shell` tool — the one primitive every harness
has, and cria's agnostic target for file writes and its own file ops."""

from __future__ import annotations

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
