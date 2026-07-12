"""Finding and shaping the harness's `shell` tool — the one primitive every harness
has, and cria's agnostic target for file writes and its own file ops."""

from __future__ import annotations

SHELL_TOOL_NAMES = {"shell", "bash", "exec_command", "local_shell", "run_terminal_cmd", "shell_command"}


def find_shell_tool(tools) -> dict | None:
    """The first shell-like tool the harness advertised, as ``{name, schema}``."""
    for t in tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        if fn.get("name") in SHELL_TOOL_NAMES:
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
