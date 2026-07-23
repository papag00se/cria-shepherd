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
import uuid

from .jsontext import extract_json_object
from .shelltool import find_shell_tool, shell_args
from .toolargs import parse_args as _parse_tool_args, tool_path as _tool_path
from .writeproxy import _decode_backslash_escapes, _read_command as _wp_read_command

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
# Gemma-fable dialect (ported from codex-local tool_aliases.rs): a bespoke syntax, NOT JSON —
#   <|tool_call>call:NAME{key:<|"|>string val<|"|>,key2:123,key3:[<|"|>a<|"|>]}<tool_call|>
# STRING values are delimited by the `<|"|>` token (so a value may contain `}`, `,`, quotes —
# anything but the delimiter); bare tokens are bools/ints; `{}`/`[]` nest; a TRUNCATED call
# (generation cut off) is parsed as far as it goes so earlier args still recover. A regex cannot
# parse this (the old one here silently dropped nested/numeric args) — recursive descent only.
_GEMMA_TC_OPEN = "<|tool_call>"
_GEMMA_TC_CLOSE = "<tool_call|>"
_GEMMA_STR = '<|"|>'
# LFM2/Fabliq NATIVE delimiters. llama.cpp's peg-native parser already RECOVERS a well-formed
# native call, so we do NOT recover these — we only STRIP the sentinels from content: whole pairs,
# then any orphan start/end token a MALFORMED call leaked (a stray `<|tool_call_end|>` poisons the
# pinned plan/redirect). Ported from tool_aliases.rs (LFM2_TC_OPEN/CLOSE + strip_leaked_tool_calls).
_LFM2_TC_OPEN = "<|tool_call_start|>"
_LFM2_TC_CLOSE = "<|tool_call_end|>"

# Tool-call-dialect sentinels that NEVER appear in legitimate prose. When any survives into a text
# answer, that "answer" is a MANGLED leaked call the recover/strip pass couldn't clean (a truncated
# `<|tool_call>call:Gemma4__…` blob with no proper close), not real content.
_LEAK_DEBRIS = (_GEMMA_TC_OPEN, _GEMMA_TC_CLOSE, _GEMMA_STR, _LFM2_TC_OPEN, _LFM2_TC_CLOSE,
                "<tool_call>", "</tool_call>")


def has_tool_call_leak(text: str) -> bool:
    """True when ``text`` still carries tool-call-dialect debris — a leaked/mangled call, not prose.
    A caller that requires real prose (the summarizer) treats such a pass as failed and retries, so a
    ⟦ctx:rollup⟧ can't become a wall of `<|tool_call>call:Gemma4__…` hex that briefs the coder on
    nothing."""
    return bool(text) and any(mk in text for mk in _LEAK_DEBRIS)


# A weak model routinely FUSES a second tool call (often + a line of commentary) onto a valid first one,
# so the first call's ``arguments`` carry trailing tool-call / reasoning-channel sentinels:
#   {"command":["pip","install","pytest"]}<tool_call|>I've written…<|tool_call>call:shell{command:[…
# The REAL first call is recoverable — cut at the first sentinel and parse the head. RECOVER it (a
# massage: the command just runs, no wasted turn) rather than refusing (which offloads the fix to the
# same weak model). Only the genuinely-mangled residual (mixed quoting, hallucinated paths) can't be
# parsed here — that falls to the writeproxy refusal floor. Measured 83% recoverable on real captures.
_FUSED_SENTINELS = _LEAK_DEBRIS + ("<|channel>", "<channel|>")


def _recover_fused_call(raw: str) -> dict | None:
    """Recover the real first call from a fused/leaked ``arguments`` string: cut at the first tool-call/
    channel sentinel, then parse the head — first as-is, then undoing the over-escaped quotes (``\\"``→
    ``"``, ``\\'``→``'``) the model routinely emits inside the array. Returns the parsed args dict, or
    None when the head is still not valid JSON (genuinely mangled → the writeproxy refusal is the floor)."""
    cut = min([i for i in (raw.find(t) for t in _FUSED_SENTINELS) if i >= 0], default=-1)
    if cut < 0:
        return None
    head = raw[:cut].strip()
    for cand in (head, head.replace('\\"', '"').replace("\\'", "'")):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def apply(completion: dict, tools=None, rlog=None) -> dict:
    """Run all output massages, in order."""
    completion = recover_leaked_tool_calls(completion, tools, rlog)  # text → real tool_calls
    completion = normalize_tool_names(completion, tools, rlog)  # EditFile/edit-file → edit_file (case/sep)
    completion = repair_tool_args(completion, rlog)  # fenced / raw-newline args → clean JSON
    completion = normalize_tool_calls(completion, tools, rlog)  # ls/read_file/exec → shell shape
    completion = lower_edit_file(completion, tools, rlog)  # edit_file → apply_patch
    completion = add_file_to_write_file(completion, rlog)  # a pure Add-File patch → write_file
    completion = normalize_apply_patch(completion, rlog)  # unified-diff / headers / envelope
    return completion


def coerce_text_answer(completion: dict, rlog=None) -> dict:
    """A TEXT answer was expected — the request offered no tools (a compaction/summary, a reasoner
    or critic call, a plain question) — but the model answered with a TOOL CALL instead: a native
    one, or a dialect leak already promoted to ``tool_calls`` by ``recover_leaked_tool_calls``.
    A tool call can't be the answer here, so recover the text: drop the spurious tool_calls and,
    if that leaves no content, promote the model's reasoning — where the answer was actually
    drafted (observed live: a gemma4 compaction reasoned out a full summary, then emitted a
    hallucinated ``<|tool_call>call:Gemma4__Try{…}`` as its 'answer', losing the summary). Dialect-
    agnostic and idempotent — it keys off 'has a tool call but no text', not any one syntax."""
    for choice in completion.get("choices", []):
        msg = choice.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        has_text = isinstance(content, str) and content.strip()
        if has_text and not msg.get("tool_calls"):
            continue  # already a clean text answer
        if msg.get("tool_calls"):
            msg["tool_calls"] = None  # spurious: nothing was there to call
        if not has_text:
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if isinstance(reasoning, str) and reasoning.strip():
                msg["content"] = reasoning.strip()
                _log(rlog, "massage.text_from_reasoning", chars=len(reasoning.strip()))
        if choice.get("finish_reason") == "tool_calls":
            choice["finish_reason"] = "stop"
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
            path = _tool_path(args)
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
    return _parse_tool_args(arguments)  # the one shared tool-arg parser


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


def _canon_key(name: str) -> str:
    """Fold case + separators only (EditFile / edit-file / Edit_File → 'editfile'). Deliberately NOT
    fuzzy — no edit-distance/plurals — so only a near-identical spelling collapses, never a different
    intent (bare `edit` stays `edit`)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _canonical_name_map(tools) -> dict:
    """canon-key → the ONE advertised tool with that key; a key shared by ≥2 advertised tools is
    poisoned to None (ambiguous → never guess a rename)."""
    out: dict = {}
    for nm in _tool_names(tools):
        if not nm:
            continue
        k = _canon_key(nm)
        out[k] = None if k in out else nm
    return out


def normalize_tool_names(completion: dict, tools=None, rlog=None) -> dict:
    """A ~12B model spells an advertised tool with the wrong CASE/separators (``EditFile`` / ``edit-file``
    for ``edit_file``). The exact-string dispatch downstream (normalize_tool_calls, writeproxy's
    ``name in _EDIT_NAMES``) then can't route it, so the call SILENTLY FAILS and the model believes it
    edited when it didn't — the exact churn seen live. Fold a mis-spelled name back to the one advertised
    tool with the same canonical key. Safety: matches ONLY tools actually advertised this request (can't
    invent a tool off the menu), only on an EXACT canonical-key hit, skips a name that is already valid
    (idempotent), and refuses when two advertised tools share a key. No-op when there are no tools."""
    cmap = _canonical_name_map(tools)
    if not cmap:
        return completion
    advertised = _tool_names(tools)
    for choice in completion.get("choices", []):
        for tc in (choice.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if not name or name in advertised:      # empty, or already a real tool → leave it
                continue
            canon = cmap.get(_canon_key(name))
            if canon and canon != name:
                fn["name"] = canon
                _log(rlog, "massage.tool_renamed", was=name, now=canon)
    return completion


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
    """Lower a read ALIAS (cat_file/view_file, or read_file when the harness has no native one) to the
    SAME guarded shell read the writeproxy synthetic-read path builds — size-guarded (never hands the
    harness a truncatable blob) and past-EOF-signalled. ONE read-lowering, not two divergent ones (this
    used to be a bare cat/sed with no guards — the exact truncation footgun the writeproxy path fixes).
    Normalizes the ``start``/``end`` aliases to ``start_line``/``end_line`` and int-coerces them first."""
    a = dict(args) if isinstance(args, dict) else {}
    for src, dst in (("start", "start_line"), ("end", "end_line")):
        if a.get(dst) is None and a.get(src) is not None:
            a[dst] = a[src]
    for k in ("start_line", "end_line"):   # writeproxy guards on int; coerce a stringy line number
        if a.get(k) is not None:
            try:
                a[k] = int(a[k])
            except (TypeError, ValueError):
                a.pop(k, None)
    return _wp_read_command(a) or ""


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
        if isinstance(content, str) and (_LFM2_TC_OPEN in content or _LFM2_TC_CLOSE in content):
            content = _strip_lfm2_sentinels(content)  # llama.cpp recovered the call; strip its leaked text
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
_CHANNEL_FABLE = re.compile(r"<\|channel>.*?(?:<channel\|>|$)", re.DOTALL)


def _strip_channel(content: str) -> str:
    """Drop Gemma's thinking wrappers, keeping the answer: the `<|channel>…<|message>` harmony
    variant AND the gemma-fable `<|channel>thought…<channel|>` variant (an unterminated open —
    truncated thinking — drops to the end, as upstream)."""
    return _CHANNEL_FABLE.sub("", _CHANNEL.sub("", content)).strip()


def _strip_delimited(content: str, open_: str, close_: str) -> str:
    """Remove every ``open…close`` block; an unterminated final ``open`` (truncated generation)
    drops to the end. Port of tool_aliases.rs::strip_delimited."""
    out: list[str] = []
    rest = content
    while True:
        o = rest.find(open_)
        if o < 0:
            out.append(rest)
            break
        out.append(rest[:o])
        after = rest[o + len(open_):]
        c = after.find(close_)
        rest = after[c + len(close_):] if c >= 0 else ""
    return "".join(out)


def _strip_lfm2_sentinels(content: str) -> str:
    """LFM2/Fabliq native ``<|tool_call_start|>…<|tool_call_end|>``: strip whole pairs, then any
    orphan start/end token a MALFORMED call left behind (a stray ``<|tool_call_end|>`` poisons the
    pinned plan/redirect). STRIP, not RECOVER — llama.cpp's peg-native parser already handles a
    well-formed native call. Port of tool_aliases.rs::strip_leaked_tool_calls (LFM2 arm)."""
    out = _strip_delimited(content, _LFM2_TC_OPEN, _LFM2_TC_CLOSE)
    return out.replace(_LFM2_TC_OPEN, "").replace(_LFM2_TC_CLOSE, "").strip()


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

    gemma_calls, cleaned = _extract_gemma(cleaned)
    calls.extend(gemma_calls)

    return calls, cleaned.replace(_GEMMA_STR, "").strip()


def _extract_gemma(content: str) -> tuple[list[dict], str]:
    """Every `<|tool_call>call:NAME{…}<tool_call|>` block → a recovered tool call; blocks are
    stripped from the returned content. A block with no close token (truncated generation) is
    parsed to the end and stripped to the end."""
    calls: list[dict] = []
    out: list[str] = []
    rest = content
    while True:
        open_at = rest.find(_GEMMA_TC_OPEN)
        if open_at < 0:
            out.append(rest)
            break
        out.append(rest[:open_at])
        after = rest[open_at + len(_GEMMA_TC_OPEN):]
        close_at = after.find(_GEMMA_TC_CLOSE)
        inner, rest = (after[:close_at], after[close_at + len(_GEMMA_TC_CLOSE):]) \
            if close_at >= 0 else (after, "")
        call = _parse_gemma_call(inner.strip())
        if call is not None:
            calls.append(call)
        if not rest:
            break
    return calls, "".join(out)


def _parse_gemma_call(inner: str) -> dict | None:
    body = inner[5:].lstrip() if inner.startswith("call:") else inner
    brace = body.find("{")
    if brace < 0:
        return None
    name = body[:brace].strip()
    if not name:
        return None
    parsed = _gemma_object(body[brace:])
    if parsed is None:
        return None
    return _toolcall(_alias(name), parsed[0])


def _gemma_object(s: str):
    """Parse `{key:value,…}` at s[0]=='{' → (dict, chars consumed incl. '}'). An unterminated
    object (truncation) returns what was recovered so far — never drops the whole call."""
    if not s.startswith("{"):
        return None
    obj: dict = {}
    i = 1
    while True:
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            break
        if s[i] == "}":
            return obj, i + 1
        colon = s.find(":", i)
        if colon < 0:
            break
        key = s[i:colon].strip()
        i = colon + 1
        val = _gemma_value(s[i:])
        if val is None:  # unparseable value (junk/truncation) → keep what we have
            break
        v, consumed = val
        i += consumed
        if key:
            obj[key] = v
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            break
        if s[i] == ",":
            i += 1
        elif s[i] == "}":
            return obj, i + 1
        else:
            break
    return obj, len(s)


def _gemma_array(s: str):
    if not s.startswith("["):
        return None
    arr: list = []
    i = 1
    while True:
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            break
        if s[i] == "]":
            return arr, i + 1
        val = _gemma_value(s[i:])
        if val is None:
            break
        v, consumed = val
        i += consumed
        arr.append(v)
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            break
        if s[i] == ",":
            i += 1
        elif s[i] == "]":
            return arr, i + 1
        else:
            break
    return arr, len(s)


def _gemma_value(s: str):
    """ONE value: a `<|"|>…<|"|>` string (opaque — any char but the delimiter), a nested
    `{}`/`[]`, or a bare bool/int/scalar up to the next `,`/`}`/`]`. → (value, chars consumed)."""
    ws = len(s) - len(s.lstrip())
    t = s[ws:]
    if t.startswith(_GEMMA_STR):
        after = t[len(_GEMMA_STR):]
        end = after.find(_GEMMA_STR)
        if end >= 0:
            return after[:end], ws + len(_GEMMA_STR) * 2 + end
        # truncated string (cut off mid-value) — take the remainder so earlier args survive
        return after, ws + len(_GEMMA_STR) + len(after)
    if t.startswith("{"):
        r = _gemma_object(t)
        return (r[0], ws + r[1]) if r else None
    if t.startswith("["):
        r = _gemma_array(t)
        return (r[0], ws + r[1]) if r else None
    end = len(t)
    for ch in (",", "}", "]"):
        pos = t.find(ch)
        if 0 <= pos < end:
            end = pos
    return _gemma_scalar(t[:end].strip()), ws + end


def _gemma_scalar(raw: str):
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        return int(raw)  # upstream parses i64 only — floats stay strings, quirk preserved
    except ValueError:
        return raw


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
        for i, tc in enumerate(msg.get("tool_calls") or []):
            yield _sse({"tool_calls": [{"index": i, "id": tc.get("id"), "type": "function", "function": tc["function"]}]}, model)
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
            # A fused 2nd call trailing the real one comes FIRST — before the valid-JSON short-circuit —
            # because the leaked debris often parses as VALID-but-wrong JSON (it gets swallowed into a
            # string value), which `json.loads` would wave through unrecovered. Recover the real first
            # call (cut + unescape); if it can't be reconstructed, leave the debris for the writeproxy
            # refusal floor rather than mangling it further.
            if any(t in raw for t in _FUSED_SENTINELS):
                obj = _recover_fused_call(raw)
                if obj is not None:
                    fn["arguments"] = json.dumps(obj, ensure_ascii=False)
                    _log(rlog, "massage.fused_call_recovered", tool=fn.get("name"))
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


def repair_history_tool_args(messages: list, rlog=None) -> list:
    """Ensure every tool_call in the REPLAYED HISTORY has valid-JSON ``arguments``, so ONE malformed
    call can't 500 a strict chat template on EVERY subsequent turn.

    A weak model can emit a tool_call whose arguments aren't valid JSON — e.g. a `python3 -c "..."`
    shell command where it backslash-escaped a quote inside an f-string (`{handle}\'`), which is a
    valid shell/Python escape but a FORBIDDEN JSON one. llama.cpp records the call, then on every later
    turn re-parses each historical tool_call's arguments as JSON while rendering the chat template —
    the one bad call throws and the server returns HTTP 500. Because the poison lives in the HISTORY,
    not the fresh generation, it bricks the whole session and never recovers (observed on Fabliq).

    :func:`repair_tool_args` fixes the model's FRESH response but never touched the history cria
    forwards. Repair each malformed historical call with the same primitives; if it can't be
    reconstructed, neutralize it to a valid stub that preserves the original text under ``_unparsed``
    (the call already happened — this is context, not a re-execution — so a faithful stub is enough).
    Valid arguments are left untouched, so the common path is a no-op."""
    repaired = 0
    out = []
    for m in messages:
        tcs = m.get("tool_calls") if isinstance(m, dict) else None
        if not isinstance(tcs, list) or not tcs:
            out.append(m)
            continue
        new_tcs = []
        for tc in tcs:
            fn = tc.get("function") if isinstance(tc, dict) else None
            raw = fn.get("arguments") if isinstance(fn, dict) else None
            if isinstance(raw, str):
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    obj = extract_json_object(raw) or _recover_write_args(raw)
                    fixed = json.dumps(obj if obj is not None else {"_unparsed": raw}, ensure_ascii=False)
                    tc = {**tc, "function": {**fn, "arguments": fixed}}
                    repaired += 1
            new_tcs.append(tc)
        out.append({**m, "tool_calls": new_tcs})
    if repaired:
        _log(rlog, "massage.history_args_repaired", count=repaired)
    return out


_PATH_RE = re.compile(r'"(?:path|file_path|file|filename)"\s*:\s*"([^"\n]*)"')
_CONTENT_RE = re.compile(r'"(?:content|contents|text|body)"\s*:\s*"')


def _json_structurally_complete(s: str) -> bool:
    """True iff ``s`` is a structurally closed JSON value: every `{`/`[` balanced by its `}`/`]`
    and no string left open. Tolerant scan — a backslash escapes the next char regardless of JSON
    validity, so an invalid `\\'` (the real cut-off write) is followed correctly and only an actual
    truncation ends inside a string or at depth > 0. NOT a validator: it decides completeness, not
    well-formedness, and can't resolve a genuinely unescaped `"` in a string value (unresolvable by
    any scan — the caller refuses on that ambiguity)."""
    depth = 0
    in_str = False
    esc = False
    saw = False
    for ch in s:
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
            saw = True
        elif ch in "}]":
            depth -= 1
            if depth < 0:  # a stray closer → not a well-nested value
                return False
    return saw and depth == 0 and not in_str


def _recover_write_args(raw: str) -> dict | None:
    """Last-resort recovery of a write_file-style call whose `content` value has
    raw newlines / unescaped quotes that break JSON: pull the path, then take the
    content up to the closing quote before the final `}`.

    Recovers ONLY a structurally COMPLETE call. A call whose `content` string was cut
    off mid-value (the model self-truncated its own generation — a normal `tool_calls`
    finish, not `length`, so `is_truncated` never sees it) must NOT be salvaged: the
    recovered body would be a partial file, and lowering it to disk writes a broken file
    that reports success. Refuse (→ None) when the content value isn't properly closed;
    :func:`has_incomplete_write_args` then flags it so the loop drops the partial write."""
    pm = _PATH_RE.search(raw)
    if not pm:
        return None
    # Structural completeness, not a string heuristic: `endswith("}")` proves nothing (a `}` can
    # close a NESTED object, or be literal content, while the outer object is still open). Scan the
    # raw as JSON — string state + backslash-escapes-next-char (so an invalid `\'` is handled) +
    # brace/bracket depth. A cut-off call ends inside a string or at depth > 0. The one case this
    # can't decide is a GENUINELY unescaped `"` in content (the same ambiguity that broke json.loads);
    # there the scan may read the wrong boundary, and refusing on the safe side is the right default.
    if not _json_structurally_complete(raw):
        return None
    args: dict[str, str] = {"path": pm.group(1)}
    cm = _CONTENT_RE.search(raw)
    if cm:
        tail = raw[cm.end():]
        end = tail.rfind('"')  # closing quote of the content value (object is known-complete)
        if end < 0:
            return None
        body = tail[:end]
        # undo the escapes that WERE applied; raw newlines/quotes pass through as-is
        body = body.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        args["content"] = body
    return args


# Content-bearing file mutations. A cut-off call to one of these must never be lowered to disk
# (the content rides verbatim into the byte-exact write) — kept in sync with writeproxy's names.
_MUTATION_TOOLS = ("write_file", "create_file", "edit_file", "str_replace", "apply_patch")


def has_incomplete_write_args(completion: dict) -> bool:
    """A content-bearing file-mutation call whose `arguments` are STILL unparseable after repair —
    the model cut the call off mid-content (a normal `tool_calls` finish, not `length`), so
    :func:`_recover_write_args` refused to salvage a partial. Shipping it would lower a broken,
    half-written file to disk and report success. The loop refuses it like a length-truncation."""
    for ch in completion.get("choices", []):
        for tc in (ch.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") not in _MUTATION_TOOLS:
                continue
            raw = fn.get("arguments")
            if not isinstance(raw, str):
                continue
            try:
                json.loads(raw, strict=False)
            except (json.JSONDecodeError, ValueError):
                return True  # repair could not close it → incomplete/malformed mutation
    return False


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
    # Doubly-escaped newlines with no real ones → decode (the model escaped them). Use the SAME
    # byte-safe char decoder as the write_file path (only \n\t\r\\ and quotes): a `unicode_escape`
    # round-trip reinterprets UTF-8 as latin-1 → mojibake on any accented/CJK/emoji byte, and
    # over-decodes every other escape (\t, \\, \uXXXX) in the patch content.
    if "\\n" in body and "\n" not in body:
        body = _decode_backslash_escapes(body)
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
