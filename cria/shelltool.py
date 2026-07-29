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
