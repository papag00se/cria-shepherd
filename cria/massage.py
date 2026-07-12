"""Massages — silent repairs of the local model's OUTPUT so the harness accepts it.

A small model constantly mis-formats its tool calls: it leaks them as text in a
Hermes/XML dialect instead of the tool_calls field, wraps JSON args in ```` ```json ````
fences or breaks the escaping, and emits malformed apply_patch bodies. These
functions repair a completion dict in place-ish (returns a new dict) before cria
hands it back — the model never knows, the harness just sees valid tool calls.

Applied to BUFFERED completions (the loop's coder turns, the buffered proxy),
where the whole completion is in hand. Streaming-path recovery is a refinement.
"""

from __future__ import annotations

import json
import re
import shlex
import uuid

from .jsontext import extract_json_object
from .shelltool import find_shell_tool, shell_args

# Aliases a model reaches for that really mean "run a shell command".
# Command names a model may emit as a TOOL name (instead of calling the shell tool) —
# ported in full from Codex Local's SHELL_COMMAND_ALIASES (tool_aliases.rs). A truncated
# list means e.g. `python`/`pytest`/`cargo`/`npm` as a tool name go unrecognized and the
# harness rejects the call (the seed-class stall). Harness-native tools are matched first.
_SHELL_ALIASES = {
    'ack', 'ag', 'alias', 'ansible', 'ant', 'apt', 'apt-get', 'as', 'ava', 'awk', 'aws', 'az',
    'base64', 'basename', 'bash', 'bazel', 'brew', 'buck', 'buck2', 'buildah', 'bun', 'bundle',
    'bundler', 'bunx', 'bunzip2', 'bzcat', 'bzip2', 'cabal', 'cal', 'cargo', 'cat', 'cc', 'cd',
    'chgrp', 'chmod', 'chown', 'cksum', 'clang', 'clang++', 'clear', 'cmake', 'column', 'comm',
    'command', 'composer', 'conda', 'cp', 'crystal', 'csplit', 'curl', 'cut', 'dart', 'dash',
    'date', 'deno', 'df', 'diff', 'dig', 'dir', 'dirname', 'disown', 'dnf', 'doas', 'docker',
    'doctl', 'dpkg', 'du', 'dune', 'echo', 'egrep', 'env', 'eval', 'exec', 'expand', 'export',
    'false', 'fgrep', 'file', 'find', 'fish', 'flatpak', 'fly', 'fmt', 'fold', 'free', 'fx',
    'g++', 'gcc', 'gcloud', 'gem', 'ghc', 'git', 'go', 'gofmt', 'gpg', 'gradle', 'grep',
    'gunzip', 'gzcat', 'gzip', 'head', 'helm', 'hexdump', 'hg', 'history', 'host', 'hostname',
    'id', 'install', 'java', 'javac', 'jest', 'jobs', 'jq', 'julia', 'just', 'k9s', 'kill',
    'killall', 'kotlin', 'kotlinc', 'kubectl', 'kustomize', 'ld', 'linode', 'ln', 'locate',
    'ls', 'lsblk', 'lscpu', 'lsof', 'lua', 'luac', 'make', 'mamba', 'md5sum', 'meson',
    'minitest', 'mkdir', 'mocha', 'mount', 'mtr', 'mv', 'mvn', 'nc', 'netcat', 'netlify', 'nim',
    'ninja', 'nix', 'nix-build', 'nix-shell', 'nl', 'node', 'nohup', 'npm', 'npx', 'nslookup',
    'nuget', 'ocaml', 'ocamlfind', 'od', 'openssl', 'pacman', 'pants', 'paste', 'patch', 'perl',
    'pest', 'pgrep', 'php', 'phpunit', 'ping', 'pip', 'pip3', 'pipx', 'pkill', 'pnpm', 'podman',
    'poetry', 'printf', 'ps', 'pulumi', 'puppet', 'pwd', 'pytest', 'python', 'python3',
    'railway', 'readlink', 'realpath', 'reset', 'rev', 'rg', 'rm', 'rmdir', 'rpm', 'rspec',
    'rsync', 'ruby', 'rustc', 'salt', 'sam', 'sbt', 'scala', 'scalac', 'scp', 'screen', 'sed',
    'serverless', 'set', 'sftp', 'sh', 'sha1sum', 'sha256sum', 'sha512sum', 'skopeo', 'sleep',
    'snap', 'sort', 'source', 'split', 'ssh', 'ssh-keygen', 'stack', 'stat', 'strings', 'su',
    'sudo', 'svn', 'swift', 'swiftc', 'tac', 'tail', 'tap', 'tar', 'tee', 'telnet', 'terraform',
    'time', 'timeout', 'tmux', 'tomlq', 'touch', 'tox', 'tput', 'tr', 'traceroute', 'trap',
    'tree', 'true', 'truncate', 'type', 'ulimit', 'umask', 'umount', 'uname', 'unexpand',
    'uniq', 'unittest', 'unset', 'unxz', 'unzip', 'unzstd', 'uptime', 'uudecode', 'uuencode',
    'uv', 'v', 'vercel', 'vitest', 'watch', 'wc', 'wget', 'whereis', 'which', 'who', 'whoami',
    'xargs', 'xxd', 'xz', 'xzcat', 'yarn', 'yes', 'yq', 'yum', 'zcat', 'zig', 'zip', 'zsh',
    'zstd',
}

_HERMES = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_XML_FN = re.compile(r"<function=([A-Za-z0-9_.-]+)\s*>(.*?)</function>", re.DOTALL)
_XML_PARAM = re.compile(r"<parameter=([A-Za-z0-9_.-]+)\s*>(.*?)</parameter>", re.DOTALL)
# Gemma's bespoke dialect: <|tool_call>call:NAME{ key:<|"|>value<|"|> }<tool_call|>
_GEMMA = re.compile(r"<\|tool_call\|?>\s*call:\s*([A-Za-z0-9_.-]+)\s*\{(.*?)\}\s*<\|?/?tool_call\|?>", re.DOTALL)
_GEMMA_ARG = re.compile(r'([A-Za-z0-9_.-]+)\s*:\s*<\|"\|>(.*?)<\|"\|>', re.DOTALL)


def apply(completion: dict, tools=None, rlog=None) -> dict:
    """Run all output massages, in order."""
    completion = recover_leaked_tool_calls(completion, tools, rlog)  # text → real tool_calls
    completion = repair_tool_args(completion, rlog)  # fenced / raw-newline args → clean JSON
    completion = normalize_tool_calls(completion, tools, rlog)  # ls/read_file/exec → shell shape
    completion = lower_edit_file(completion, tools, rlog)  # edit_file → apply_patch
    completion = add_file_to_write_file(completion, rlog)  # a pure Add-File patch → write_file
    completion = normalize_apply_patch(completion, rlog)  # unified-diff / headers / envelope
    return completion


def lower_edit_file(completion: dict, tools=None, rlog=None) -> dict:
    """Rewrite an `edit_file`/`str_replace` find-replace as a native `apply_patch`
    Update hunk (old lines `-`, new lines `+`) — so an edit is escaping-proof too.
    Only when the harness doesn't run edit_file itself."""
    if _has_tool("edit_file", tools) or _has_tool("str_replace", tools):
        return completion
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") not in ("edit_file", "str_replace"):
                continue
            args = _args(fn.get("arguments"))
            path = args.get("path") or args.get("file_path") or args.get("file")
            old = args.get("old_string") or args.get("old_str") or args.get("old")
            if not path or old is None:
                continue
            new = args.get("new_string") or args.get("new_str") or args.get("new") or ""
            fn["name"] = "apply_patch"
            fn["arguments"] = json.dumps({"input": _edit_to_patch(str(path), str(old), str(new))})
            _log(rlog, "massage.edit_to_patch", path=path)
    return completion


def _edit_to_patch(path: str, old: str, new: str) -> str:
    lines = ["*** Begin Patch", f"*** Update File: {path}"]
    lines += ["-" + l for l in old.split("\n")]
    lines += ["+" + l for l in new.split("\n")]
    lines.append("*** End Patch")
    return "\n".join(lines)


def _has_tool(name: str, tools) -> bool:
    return any((((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) == name for t in tools or [])


def _args(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments
    try:
        obj = json.loads(arguments)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ---------------------------------------------------- tool-call normalization

_SHELL_CMD_ALIASES = _SHELL_ALIASES  # same full command set (normalize_tool_calls + leaked-call aliasing)
_READ_NAMES = {"read_file", "cat_file", "view_file"}
_EXEC_NAMES = {"exec_command", "exec", "bash_command", "run_command"}
_BASH_HEADS = {"bash", "sh", "/bin/bash", "/bin/sh", "zsh"}


def normalize_tool_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Reshape the model's tool calls to the tools the harness actually advertised: a
    shell-ish NAME (`ls`/`cat`/`git`/…), a read tool, or an exec tool → the harness's
    `shell` with a proper command; a `shell` call with the wrong arg SHAPE (string vs
    argv, double-wrapped) fixed to its schema. No-op when the harness has no shell."""
    shell = find_shell_tool(tools)
    if shell is None:
        return completion
    names = _tool_names(tools)
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            if name == shell["name"]:
                _reshape_shell(fn, shell, rlog)
            elif name in names:
                continue  # the harness runs it natively
            elif name in _SHELL_CMD_ALIASES:
                _to_shell(fn, shell, _alias_command(name, _args(fn.get("arguments"))), "shell_name", rlog)
            elif name in _READ_NAMES and "read_file" not in names:
                _to_shell(fn, shell, _read_command(_args(fn.get("arguments"))), "read_lower", rlog)
            elif name in _EXEC_NAMES:
                a = _args(fn.get("arguments"))
                _to_shell(fn, shell, _command_string(a.get("cmd") if a.get("cmd") is not None else a.get("command")), "exec_command", rlog)
    return completion


def _tool_names(tools) -> set:
    return {(((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) for t in tools or []}


def _to_shell(fn: dict, shell: dict, cmd, why: str, rlog) -> None:
    if not cmd:
        return
    fn["name"] = shell["name"]
    fn["arguments"] = json.dumps(shell_args(shell, cmd))
    _log(rlog, "massage.tool_normalized", why=why)


def _reshape_shell(fn: dict, shell: dict, rlog) -> None:
    args = _args(fn.get("arguments"))
    # The command may sit under `command` OR `cmd` (Codex's exec_command), as a
    # string or an argv array. An array `cmd` left as-is makes the harness exec a
    # program literally named `[` — normalize it to the tool's real field + type.
    raw = args.get("command")
    if raw is None:
        raw = args.get("cmd")
    if raw is None:
        return
    cmd = _command_string(raw)
    if cmd is None:
        return
    fixed = {k: v for k, v in args.items() if k not in ("command", "cmd")}
    fixed.update(shell_args(shell, cmd))
    if fixed != args:
        fn["arguments"] = json.dumps(fixed)
        _log(rlog, "massage.shell_reshaped")


def _command_string(cmd):
    if isinstance(cmd, str):
        return cmd
    if isinstance(cmd, list):
        if len(cmd) == 1 and isinstance(cmd[0], list):
            cmd = cmd[0]  # double-wrapped [["bash","-lc",x]]
        if len(cmd) >= 3 and str(cmd[0]) in _BASH_HEADS and str(cmd[1]) in ("-lc", "-c"):
            return str(cmd[2])
        return " ".join(str(c) for c in cmd)
    return None


def _alias_command(name: str, args: dict) -> str:
    if "command" in args:
        return _command_string(args["command"]) or name
    parts = [name]
    for k in ("flags", "args", "arguments", "pattern", "query", "path", "file", "file_path", "dir"):
        v = args.get(k)
        if isinstance(v, str) and v:
            parts.append(v)
        elif isinstance(v, list):
            parts += [str(x) for x in v]
    return " ".join(parts)


def _read_command(args: dict) -> str:
    path = str(args.get("path") or args.get("file") or args.get("file_path") or "")
    q = shlex.quote(path) if path else ""
    start, end = args.get("start_line") or args.get("start"), args.get("end_line") or args.get("end")
    try:
        if start and end:
            return f"sed -n '{int(start)},{int(end)}p' {q}"
    except (TypeError, ValueError):
        pass
    return f"cat {q}".strip()


# ---------------------------------------------------- truncation + Add→write_file


def is_truncated(completion: dict) -> bool:
    """The model was cut off at the output-token cap (`finish_reason == "length"`) —
    so any file it was writing is incomplete."""
    return any(ch.get("finish_reason") == "length" for ch in completion.get("choices", []))


def is_ruminating(completion: dict) -> bool:
    """The streaming coder path aborted this response as a reasoning loop (rumination detector) —
    `finish_reason == "rumination"`. The caller re-prompts to focus, rather than accept an empty
    turn. See `cria.rumination` + `Upstream.chat_watched`."""
    return any(ch.get("finish_reason") == "rumination" for ch in completion.get("choices", []))


def add_file_to_write_file(completion: dict, rlog=None) -> dict:
    """A pure file-creating apply_patch (`*** Add File:` + only `+` lines) → a robust
    write_file (which the writeproxy then lowers to a byte-exact shell write)."""
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "apply_patch":
                continue
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                continue
            body = args.get("input") or args.get("patch")
            if not isinstance(body, str):
                continue
            add = _pure_add_file(body)
            if add:
                path, content = add
                fn["name"] = "write_file"
                fn["arguments"] = json.dumps({"path": path, "content": content})
                _log(rlog, "massage.add_to_write", path=path)
    return completion


def _pure_add_file(body: str):
    path, content = None, []
    for line in body.splitlines():
        s = line.strip()
        if s in ("*** Begin Patch", "*** End Patch"):
            continue
        if s.startswith("*** Add File:"):
            if path is not None:
                return None  # more than one file — not a pure single add
            path = s[len("*** Add File:"):].strip()
        elif line.startswith("+"):
            content.append(line[1:])
        elif line.startswith("-") or s.startswith("@@") or s.startswith("*** "):
            return None  # a removal / hunk / other op → not a pure add
        else:
            content.append(line)  # bare content line
    return (path, "\n".join(content)) if path is not None else None


def _log(rlog, kind: str, **fields) -> None:
    if rlog is not None:
        rlog.emit(kind, **fields)


# ------------------------------------------------------------------ leaked calls


def recover_leaked_tool_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Promote a tool call the model emitted as TEXT (Hermes `<tool_call>…`, XML
    `<function=…>`) into a real tool_calls entry, and strip it from the content."""
    for choice in completion.get("choices", []):
        msg = choice.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and "<|channel" in content:  # Gemma's thought channel
            content = _strip_channel(content)
            msg["content"] = content or None
        if msg.get("tool_calls"):
            continue  # already has real tool calls; don't double-recover
        if not isinstance(content, str) or "<" not in content:
            continue
        calls, cleaned = _extract_leaked(content)
        if calls:
            msg["tool_calls"] = calls
            msg["content"] = cleaned or None
            if choice.get("finish_reason") in (None, "stop"):
                choice["finish_reason"] = "tool_calls"
            _log(rlog, "massage.leaked_recovered", calls=[c["function"]["name"] for c in calls])
    return completion


_CHANNEL = re.compile(r"<\|channel\|?>.*?<\|message\|?>", re.DOTALL)


def _strip_channel(content: str) -> str:
    """Drop Gemma's `<|channel>thought…<|message>` wrapper, keeping the answer."""
    return _CHANNEL.sub("", content).strip()


def _extract_leaked(content: str) -> tuple[list[dict], str]:
    calls: list[dict] = []
    cleaned = content

    for m in _HERMES.finditer(content):
        obj = extract_json_object(m.group(1))
        if obj and obj.get("name"):
            calls.append(_toolcall(str(obj["name"]), obj.get("arguments", {})))
            cleaned = cleaned.replace(m.group(0), "")

    for m in _XML_FN.finditer(content):
        name, body = m.group(1), m.group(2)
        args = extract_json_object(body)
        if args is None:
            params = {k: v.strip() for k, v in _XML_PARAM.findall(body)}
            args = params if params else {}
        calls.append(_toolcall(_alias(name), args))
        cleaned = cleaned.replace(m.group(0), "")

    for m in _GEMMA.finditer(content):
        name, argblock = m.group(1), m.group(2)
        args = {k: v for k, v in _GEMMA_ARG.findall(argblock)}
        calls.append(_toolcall(_alias(name), args))
        cleaned = cleaned.replace(m.group(0), "")

    return calls, cleaned.strip()


def _alias(name: str) -> str:
    return "shell" if name in _SHELL_ALIASES else name


# ------------------------------------------------------------------ streaming


_LEAK_MARKERS = ("<tool_call", "<function=", "<|tool_call")
_HOLDBACK = 32  # keep this many trailing chars unemitted, so a leak marker start isn't leaked


def massage_stream(chunks, model: str, tools=None, rlog=None, post=None):
    """Massage a streaming completion. Content streams live, lagging by a few chars,
    until a leaked-call marker appears — then cria captures the rest, recovers the
    call, and emits it as real tool_call deltas. No leak → a normal live stream.

    ``post`` (optional) transforms the recovered completion before it's emitted —
    e.g. lowering a recovered write_file to shell (writeproxy)."""
    content = ""
    emitted = 0
    captured = False
    saw_real_tool_call = False
    finish = "stop"

    for raw in chunks:
        if raw.strip() == b"data: [DONE]":
            continue  # skip, don't break — let the upstream generator run to its finally
        choice = _choice(raw)
        if choice is None:
            if not captured:
                yield raw  # blank line / comment / heartbeat
            continue
        if choice.get("finish_reason"):
            finish = choice["finish_reason"]
            continue  # re-emitted at the end
        delta = choice.get("delta") or {}
        if delta.get("tool_calls"):
            saw_real_tool_call = True
            if not captured:
                yield raw
            continue
        dc = delta.get("content")
        if dc is None:
            if not captured:
                yield raw  # role delta
            continue

        content += dc
        if captured:
            continue
        pos = _leak_pos(content)
        if pos >= 0:
            if pos > emitted:
                yield _sse({"content": content[emitted:pos]}, model)
                emitted = pos
            captured = True
            _log(rlog, "massage.stream_leak_detected")
        else:
            safe = len(content) - _HOLDBACK
            if safe > emitted:
                yield _sse({"content": content[emitted:safe]}, model)
                emitted = safe

    if captured:
        completion = apply({"choices": [{"message": {"role": "assistant", "content": content}}]}, tools, rlog)
        if post is not None:
            completion = post(completion)
        msg = completion["choices"][0]["message"]
        cleaned = msg.get("content") or ""
        if len(cleaned) > emitted:
            yield _sse({"content": cleaned[emitted:]}, model)
        for tc in msg.get("tool_calls") or []:
            yield _sse({"tool_calls": [{"index": 0, "id": tc.get("id"), "type": "function", "function": tc["function"]}]}, model)
        finish = "tool_calls" if msg.get("tool_calls") else "stop"
    elif len(content) > emitted:
        yield _sse({"content": content[emitted:]}, model)  # the held-back tail

    yield _sse({}, model, finish=("tool_calls" if saw_real_tool_call and not captured else finish))
    yield b"data: [DONE]\n\n"


def _sse(delta: dict, model: str, finish=None) -> bytes:
    payload = {"object": "chat.completion.chunk", "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


def _choice(raw: bytes):
    if not raw.startswith(b"data:"):
        return None
    payload = raw[5:].strip()
    if not payload or payload == b"[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    choices = obj.get("choices") if isinstance(obj, dict) else None
    return choices[0] if choices else None


def _leak_pos(content: str) -> int:
    found = [content.find(m) for m in _LEAK_MARKERS]
    found = [p for p in found if p >= 0]
    return min(found) if found else -1


def _toolcall(name: str, args) -> dict:
    arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    return {"id": "call_" + uuid.uuid4().hex[:16], "type": "function", "function": {"name": name, "arguments": arguments}}


# ------------------------------------------------------------------ arg repair


def repair_tool_args(completion: dict, rlog=None) -> dict:
    """Ensure every tool call's ``arguments`` is a clean JSON string — unwrap ```` ``` ````
    fences, recover the object out of surrounding noise, else leave it be."""
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function")
            if not isinstance(fn, dict):
                continue
            raw = fn.get("arguments")
            if not isinstance(raw, str):
                fn["arguments"] = json.dumps(raw if raw is not None else {})
                continue
            try:
                json.loads(raw)
                continue  # already valid
            except json.JSONDecodeError:
                obj = extract_json_object(raw)
                if obj is None:
                    obj = _recover_write_args(raw)  # raw newlines / unescaped quotes in content
                if obj is not None:
                    fn["arguments"] = json.dumps(obj, ensure_ascii=False)
                    _log(rlog, "massage.args_repaired", tool=fn.get("name"))
    return completion


_PATH_RE = re.compile(r'"(?:path|file_path|file|filename)"\s*:\s*"([^"\n]*)"')
_CONTENT_RE = re.compile(r'"(?:content|contents|text|body)"\s*:\s*"')


def _recover_write_args(raw: str) -> dict | None:
    """Last-resort recovery of a write_file-style call whose `content` value has
    raw newlines / unescaped quotes that break JSON: pull the path, then take the
    content up to the closing quote before the final `}`."""
    pm = _PATH_RE.search(raw)
    if not pm:
        return None
    args: dict[str, str] = {"path": pm.group(1)}
    cm = _CONTENT_RE.search(raw)
    if cm:
        tail = raw[cm.end():]
        end = tail.rfind('"')  # closing quote of the content value
        body = tail[:end] if end >= 0 else tail
        # undo the escapes that WERE applied; raw newlines/quotes pass through as-is
        body = body.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        args["content"] = body
    return args


# ------------------------------------------------------------------ apply_patch


def normalize_apply_patch(completion: dict, rlog=None) -> dict:
    """Repair an apply_patch body: decode a doubly-escaped `\\n` when there are no
    real newlines (the mixed-escape footgun), and ensure the Begin/End Patch
    envelope. Deeper normalization (unified-diff → native) is a later refinement."""
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "apply_patch":
                continue
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                continue
            key = "input" if "input" in args else ("patch" if "patch" in args else None)
            if key is None or not isinstance(args[key], str):
                continue
            fixed = _normalize_patch_body(args[key])
            if fixed != args[key]:
                args[key] = fixed
                fn["arguments"] = json.dumps(args, ensure_ascii=False)
                _log(rlog, "massage.patch_normalized")
    return completion


_HUNK = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@(.*)$")


def _normalize_patch_body(body: str) -> str:
    # Doubly-escaped newlines with no real ones → decode (the model escaped them).
    if "\\n" in body and "\n" not in body:
        body = body.encode("utf-8").decode("unicode_escape")
    body = _collapse_wrappers(body)  # one Begin/End around everything, not per-file
    body = _unified_to_native(body)  # `--- a/… / +++ b/…` → `*** Update/Add/Delete File:`
    body = _repair_hunk_headers(body)  # drop the miscounted `@@ -L,N +L,N @@` numbers
    body = _fix_hunk_lines(body)  # prefix bare content lines a model forgot to mark (any hunk)
    body = body.strip("\n")
    if "*** Begin Patch" not in body:
        body = "*** Begin Patch\n" + body
    if "*** End Patch" not in body:
        body = body.rstrip("\n") + "\n*** End Patch"
    return body


def _collapse_wrappers(body: str) -> str:
    return "\n".join(l for l in body.splitlines() if l.strip() not in ("*** Begin Patch", "*** End Patch"))


def _strip_ab(path: str) -> str:
    path = path.split("\t")[0].strip()
    return path[2:] if path[:2] in ("a/", "b/") else path


def _unified_to_native(body: str) -> str:
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line, nxt = lines[i], (lines[i + 1] if i + 1 < len(lines) else "")
        if line.startswith("--- ") and nxt.startswith("+++ "):
            old, new = line[4:].strip(), nxt[4:].strip()
            if "/dev/null" in old:
                out.append(f"*** Add File: {_strip_ab(new)}")
            elif "/dev/null" in new:
                out.append(f"*** Delete File: {_strip_ab(old)}")
            else:
                out.append(f"*** Update File: {_strip_ab(new)}")
            i += 2
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _repair_hunk_headers(body: str) -> str:
    out: list[str] = []
    for line in body.splitlines():
        m = _HUNK.match(line)
        if m:
            anchor = m.group(1).strip()
            if anchor:  # keep a useful context anchor, drop the line-number noise
                out.append(f"@@ {anchor}")
        else:
            out.append(line)
    return "\n".join(out)


def _fix_hunk_lines(body: str) -> str:
    """Prefix bare content lines a model forgot to mark. In an Add-File block every
    content line is an addition (context coerced, removals dropped); in an Update
    hunk only a truly bare line (not +/-/space, non-empty, not a `@@` header) becomes
    an addition — matching Codex Local's fix_apply_patch_body (bare → `+` in ANY hunk)."""
    out: list[str] = []
    mode = None  # None | "add" | "update"
    for line in body.splitlines():
        if line.startswith("*** Add File:"):
            mode = "add"
            out.append(line)
        elif line.startswith("*** Update File:"):
            mode = "update"
            out.append(line)
        elif line.startswith("*** "):  # Begin/End/Delete/End-of-File — not a content hunk
            mode = None
            out.append(line)
        elif line.startswith("@@"):  # a hunk header, never content
            out.append(line)
        elif mode == "add":
            if line.startswith("+"):
                out.append(line)  # already an addition
            elif line.startswith("-"):
                continue  # a removal in a new file is nonsense — drop it
            elif line.startswith(" "):
                out.append("+" + line[1:])  # context → addition
            else:
                out.append("+" + line)  # bare content → addition
        elif mode == "update":
            if line == "" or line.startswith(("+", "-", " ")):
                out.append(line)  # already prefixed / blank context line
            else:
                out.append("+" + line)  # bare content the model forgot to prefix → addition
        else:
            out.append(line)
    return "\n".join(out)
