"""write_file ↔ shell/base64 — the portability massage. THE pattern for "owns no
executors".

The local model handles `write_file` reliably (hand it the whole file, no shell
escaping to mangle); the harness-agnostic primitive is `shell`. So when the harness
offers `shell` but not `write_file`, cria:

* **advertises** `write_file` to the MODEL (so it reaches for the reliable tool),
* translates the model's write_file call **outbound** to a base64 shell command the
  harness runs (`printf %s <b64> | base64 -d > path` — byte-exact, escaping-proof),
* **inbound**, re-presents the recorded shell call as write_file so the model only
  ever sees its own tool — the "the shell mangled my file" loop never starts.

Correlated by reusing the model's tool-call id, remembered per session so the swap
survives across the many requests of one task.

Large-file caveat: the base64 rides in one shell command; a very large file could
exceed the arg limit. Chunking is a refinement (flagged in DEFERRALS).
"""

from __future__ import annotations

import base64
import json
import shlex
import threading
import uuid

from .shelltool import SHELL_TOOL_NAMES, shell_args

_WRITE_NAMES = {"write_file", "create_file"}
_READ_NAMES = {"read_file"}
_LIST_NAMES = {"list_dir"}
# Split content larger than this across multiple shell calls — one `bash -lc "…"`
# command can't carry an arbitrarily long base64 (the arg-size limit).
_CHUNK_BYTES = 65536

WRITE_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Create or completely overwrite a file with its FULL content. The most "
            "reliable way to write a file — you supply the whole file, nothing to escape."
        ),
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
}

# The synthetic READ tools (ported from codex-local synthetic_local_read_tools): lean,
# purpose-built alternatives to the raw exec/PTY tool so a small model reads and lists
# through a named tool instead of driving `cat`/`ls` through the heavy shell schema. Like
# write_file, cria advertises them to the model and LOWERS them to the harness's shell
# outbound (owns no executors) — the clean `cat`/`sed`/`ls` form is fine to show as-is.
READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "Read a file's contents (read-only). Optionally pass a 1-based inclusive line "
            "range with start_line/end_line."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
}

LIST_DIR_TOOL = {
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": "List the entries of a directory (read-only). Defaults to the current directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": [],
        },
    },
}


class TranslationStore:
    """Per-session map: shell-call id → the original write_file args, so the inbound
    pass can re-present cria's shell translation as the model's own write_file."""

    def __init__(self) -> None:
        self._m: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def record(self, key: str, call_id: str, path: str, content: str, drop: bool = False) -> None:
        # drop=True marks a chunk CONTINUATION call — hidden from the model inbound,
        # since it made a single write_file, not N.
        with self._lock:
            self._m.setdefault(key, {})[call_id] = {"path": path, "content": content, "drop": drop}

    def get(self, key: str, call_id: str) -> dict | None:
        with self._lock:
            return self._m.get(key, {}).get(call_id)


def needs_translation(tools) -> dict | None:
    """The harness's shell tool when it offers `shell` but NOT `write_file` (so we
    should translate); ``None`` when the harness has write_file natively (passthrough)."""
    shell = None
    for t in tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        name = fn.get("name")
        if name in _WRITE_NAMES:
            return None  # harness runs write_file itself
        if name in SHELL_TOOL_NAMES and shell is None:
            shell = {"name": name, "schema": fn.get("parameters") or {}}
    return shell


def advertise(body: dict, rlog=None) -> set[str]:
    """Add cria's synthetic lean tools (write_file, read_file, list_dir) to what the MODEL
    sees — the reliable named alternatives to driving the raw shell/PTY for every write, read,
    and list. Only adds a tool the harness doesn't already offer natively. Returns the set of
    names cria injected, so the outbound pass lowers ONLY those (a native tool is the harness's
    to run, not cria's to translate)."""
    tools = body.get("tools")
    if not isinstance(tools, list):
        tools = []
        body["tools"] = tools
    present = {(((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) for t in tools}
    injected: set[str] = set()
    if not (present & _WRITE_NAMES):
        tools.append(WRITE_FILE_TOOL)
        injected.add("write_file")
    if "read_file" not in present:
        tools.append(READ_FILE_TOOL)
        injected.add("read_file")
    if "list_dir" not in present:
        tools.append(LIST_DIR_TOOL)
        injected.add("list_dir")
    if injected and rlog is not None:
        rlog.emit("writeproxy.advertised", tools=sorted(injected))
    return injected


def translate_outbound(completion: dict, shell_tool: dict, store: TranslationStore, key: str,
                       rlog=None, injected: set[str] | None = None) -> dict:
    """Lower cria's synthetic tool calls to shell commands the harness runs (cria owns no
    executors). write_file → base64 shell (byte-exact, recorded so the inbound pass re-presents
    it; large files split across append chunks). read_file → ``cat``/``sed -n`` and list_dir →
    ``ls -la`` (read-only, no recording — the clean shell result IS the answer). Only lowers a
    read/list call cria actually INJECTED (``injected``); a harness-native tool of the same name
    is the harness's to run."""
    injected = injected or set()
    for choice in completion.get("choices", []):
        tool_calls = (choice.get("message") or {}).get("tool_calls")
        if not tool_calls:
            continue
        rebuilt: list[dict] = []
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if name in _WRITE_NAMES:
                args = _parse(fn.get("arguments"))
                path = args.get("path") or args.get("file_path") or args.get("file")
                if not path:
                    rebuilt.append(tc)
                    continue
                content = args.get("content") or args.get("contents") or ""
                rebuilt.extend(_lower_write(tc.get("id"), shell_tool, store, key, path, content, rlog))
            elif name in _READ_NAMES and name in injected:
                cmd = _read_command(_parse(fn.get("arguments")))
                rebuilt.append(_lower_readonly(tc, shell_tool, cmd, "read_file", rlog) if cmd else tc)
            elif name in _LIST_NAMES and name in injected:
                cmd = _list_command(_parse(fn.get("arguments")))
                rebuilt.append(_lower_readonly(tc, shell_tool, cmd, "list_dir", rlog) if cmd else tc)
            else:
                rebuilt.append(tc)
        choice["message"]["tool_calls"] = rebuilt
    return completion


def _read_command(args: dict) -> str | None:
    """read_file args → a `cat` (or `sed -n 'A,Bp'` for a 1-based inclusive line range) shell
    command. Byte-safe path quoting; None when no path was given."""
    path = args.get("path") or args.get("file_path") or args.get("file")
    if not path:
        return None
    q = shlex.quote(str(path))
    start, end = args.get("start_line"), args.get("end_line")
    if isinstance(start, int) and isinstance(end, int) and start > 0 and end >= start:
        return f"sed -n '{start},{end}p' {q}"
    return f"cat {q}"


def _list_command(args: dict) -> str:
    """list_dir args → an `ls -la` shell command (defaults to the current directory)."""
    path = args.get("path") or args.get("dir") or args.get("directory") or "."
    return f"ls -la {shlex.quote(str(path))}"


def _lower_readonly(tc: dict, shell_tool: dict, cmd: str, why: str, rlog=None) -> dict:
    """Rewrite a read-only synthetic call (read_file/list_dir) as the harness's shell call.
    Stateless — no store record; the shell result IS what the tool would have returned."""
    if rlog is not None:
        rlog.emit("writeproxy.lowered", tool=why)
    return {"id": tc.get("id"), "type": "function",
            "function": {"name": shell_tool["name"], "arguments": json.dumps(shell_args(shell_tool, cmd))}}


def _lower_write(call_id: str, shell_tool: dict, store: TranslationStore, key: str, path: str, content: str, rlog) -> list[dict]:
    content = _repair_double_escaped(content)  # a model that emits only literal \n → real newlines
    pieces = _split(content, _CHUNK_BYTES)
    calls = []
    for i, piece in enumerate(pieces):
        cid = call_id if i == 0 else "call_" + uuid.uuid4().hex[:16]
        store.record(key, cid, path, content, drop=(i > 0))
        cmd = _write_command(path, piece, append=(i > 0))
        calls.append({"id": cid, "type": "function", "function": {"name": shell_tool["name"], "arguments": json.dumps(shell_args(shell_tool, cmd))}})
    if rlog is not None:
        rlog.emit("writeproxy.lowered", path=path, bytes=len(content), chunks=len(pieces))
    return calls


def represent_inbound(messages: list[dict], store: TranslationStore, key: str, rlog=None) -> list[dict]:
    """Swap cria's shell translations back to write_file in the assistant history, so
    the model sees the tool it actually called. Chunk-continuation calls (and their
    results) are hidden; the primary write's empty shell result is reframed as a
    confirmation (never overriding a real error)."""
    out: list[dict] = []
    swapped = 0
    dropped: set[str] = set()
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            new_calls = []
            for tc in m["tool_calls"]:
                orig = store.get(key, tc.get("id"))
                if orig is not None and (tc.get("function") or {}).get("name") in SHELL_TOOL_NAMES:
                    if orig.get("drop"):
                        dropped.add(tc.get("id"))
                        continue  # a continuation chunk — the model made one write_file
                    tc = {**tc, "function": {"name": "write_file", "arguments": json.dumps({"path": orig["path"], "content": orig["content"]})}}
                    swapped += 1
                new_calls.append(tc)
            out.append({**m, "tool_calls": new_calls})
        elif role == "tool" and m.get("tool_call_id") in dropped:
            continue  # hide the continuation chunk's result too
        elif role == "tool":
            orig = store.get(key, m.get("tool_call_id"))
            if orig is not None and not orig.get("drop") and not str(m.get("content") or "").strip():
                m = {**m, "content": f"Wrote {orig['path']}"}  # reframe the empty success, keep any error
            out.append(m)
        else:
            out.append(m)
    if swapped and rlog is not None:
        rlog.emit("writeproxy.represented", calls=swapped)
    return out


def _split(content: str, n: int) -> list[str]:
    if len(content) <= n:
        return [content]
    return [content[i : i + n] for i in range(0, len(content), n)]


# Ported from Codex Local's tool_aliases.rs. A weak model (e.g. Fabliq) sometimes
# emits a file's whole content with literal `\n` for every newline and NO real
# newlines — which would land the file as one physical line (broken code). If the
# content has no real newline but has a literal `\n`, decode its backslash escapes.
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "0": "\0"}


def _repair_double_escaped(content: str) -> str:
    if "\n" in content or "\\n" not in content:
        return content
    return _decode_backslash_escapes(content)


def _decode_backslash_escapes(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            out.append("\\")
            i += 1
            continue
        nxt = s[i + 1]
        out.append(_ESCAPES[nxt] if nxt in _ESCAPES else "\\" + nxt)
        i += 2
    return "".join(out)


def _write_command(path: str, content: str, append: bool = False) -> str:
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    q = shlex.quote(path)
    redirect = ">>" if append else ">"
    prefix = "" if append else f"mkdir -p \"$(dirname {q})\" && "
    return f"{prefix}printf %s {b64} | base64 -d {redirect} {q}"


def _parse(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments
    try:
        obj = json.loads(arguments)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
