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

import ast
import json
import re
import uuid

from . import bodykeys
from . import jsontext
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
                "<tool_call>", "</tool_call>",
                # nemotron/maple XML-function dialect (fused-call walks 1785946072, 1785956867)
                "<function=", "<parameter=",
                # DeepSeek-style DSML, which maple-preview emits. Walked on 1785994846 call 0055:
                # the steer author produced 2,800 characters of `｜DSML｜invoke name="write_file"`
                # carrying a whole file, the steer-code guard read it and answered DICTATES —
                # correctly — and cria shipped it as the run's final steer with every newline
                # stripped, because that guard is observe-only and NO hard-drop arm knew this
                # dialect. Transcript syntax is not a judgment call; it is self-evidently fiction.
                "DSML｜invoke", "DSML｜tool_calls", "DSML｜parameter")


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
            obj = jsontext.loads(cand)
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
        # Dialect-debris content is NOT a text answer: a `<|tool_call>call:…` blob in content is a
        # mangled leaked call. It used to pass the has-text check untouched — a Codex LOCAL_COMPACT
        # summary came back as that blob (empty reasoning) and went to the harness verbatim, so the
        # post-compaction history carried tool-call junk instead of a continuation summary
        # (run 0729-gemma4 calls 0113/0167).
        has_text = isinstance(content, str) and content.strip() and not has_tool_call_leak(content)
        if has_text and not msg.get("tool_calls"):
            continue  # already a clean text answer
        if msg.get("tool_calls"):
            msg["tool_calls"] = None  # spurious: nothing was there to call
        if not has_text:
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if isinstance(reasoning, str) and reasoning.strip():
                msg["content"] = reasoning.strip()
                _log(rlog, "massage.text_from_reasoning", chars=len(reasoning.strip()))
            elif isinstance(content, str) and has_tool_call_leak(content):
                # No reasoning to promote — the model's real prose is INSIDE the fake call's string
                # payload (`content:<|"|># How to run …`). Salvage the longest delimited span: the
                # model's own words, never invented. Unparseable → leave as-is (the caller's retry
                # path owns it).
                spans = re.findall(re.escape(_GEMMA_STR) + r"(.*?)(?:" + re.escape(_GEMMA_STR) + r"|\Z)",
                                   content, re.DOTALL)
                best = max(spans, key=len).strip() if spans else ""
                if best:
                    msg["content"] = best
                    _log(rlog, "massage.text_from_dialect_payload", chars=len(best))
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
                args = jsontext.loads(fn.get("arguments", "{}"))
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


def _menu_schemas(tools) -> dict:
    """{name: parameters schema} for the tools THIS request offers. The menu is what makes envelope
    recovery safe: a name is only ever an action if the request actually offers it."""
    out = {}
    for t in tools or []:
        fn = t.get("function") if isinstance(t, dict) else None
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            out[fn["name"]] = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
    return out


def coerce_args(name: str, args: dict, schemas: dict) -> dict:
    """Cast recovered arguments to the types the tool's OWN schema declares.

    A dialect recovered out of text arrives all-strings — `<parameter=yield_time_ms>30000` gives
    `"30000"`, not `30000` — because XML has no types. The harness does: Codex answers
    ``invalid type: string "30000", expected u64`` and DISCARDS the call. Measured on the qwen35
    253-call run: 148 rejections of exactly that argument, and the discarded calls were
    disproportionately the live-run attempts — the ones that would have produced ground truth. The
    run finished 4/4 after ~2.5x its usual calls, re-emitting work the harness had thrown away. Zero
    such rejections in that model's 77-call run, 74 in its 121-call run: the exposure scales with how
    often the model drifts into a text dialect, so it grows exactly when a run is already struggling.

    THE SCHEMA IS THE ONLY AUTHORITY. A value is cast only where the tool declares a type and the
    string is an exact, total match for it — `int("30000")`, not `int(float("30000.7"))`. Anything
    the schema does not type, or that does not parse cleanly, is left EXACTLY as it arrived: a wrong
    guess here forges an argument the model never wrote, which is worse than the rejection this
    fixes. Non-string values (a JSON body already parsed) are never touched."""
    schema = schemas.get(name) or {}
    props = schema.get("properties")
    if not isinstance(props, dict) or not isinstance(args, dict):
        return args
    out = dict(args)
    for key, val in args.items():
        if not isinstance(val, str):
            continue                      # already typed — a parsed JSON body, leave it alone
        declared = (props.get(key) or {}).get("type") if isinstance(props.get(key), dict) else None
        types = declared if isinstance(declared, list) else [declared]
        text = val.strip()
        if "integer" in types:
            try:
                out[key] = int(text, 10)
            except ValueError:
                pass                      # not an exact integer → leave the string, refuse to guess
        elif "number" in types:
            # An exact integer stays an INT even under `number`. JSON does not distinguish the two,
            # but the harness's deserializer does: Codex declares `yield_time_ms` as `number` in the
            # schema and parses it as `u64`, so `30000.0` is rejected exactly like `"30000"` was.
            # Emitting `30000` satisfies both readings; only a genuinely fractional value becomes a
            # float.
            try:
                out[key] = int(text, 10)
            except ValueError:
                try:
                    out[key] = float(text)
                except ValueError:
                    pass
        elif "boolean" in types and text.lower() in ("true", "false"):
            out[key] = text.lower() == "true"
    return out


def _sole_required(schema: dict) -> str | None:
    """The one property this tool requires, if there is exactly one — so a bare-string argument
    (`"arguments": "ls -la"`) can be placed by reading the SCHEMA rather than guessing a field name."""
    req = schema.get("required")
    if isinstance(req, list) and len(req) == 1 and isinstance(req[0], str):
        return req[0]
    props = schema.get("properties")
    if isinstance(props, dict) and len(props) == 1:
        return next(iter(props))
    return None


def _envelope_calls(content: str, tools) -> list:
    """Tool calls a model emitted as JSON DATA inside `content` instead of in the `tool_calls` field.

    MEASURED (run 0727-132935): a planner holding exec_command/read_file/web_fetch/web_search answered
    with `{"plan": "…", "commands": [{"name": "web_search", "arguments": {"query": "…"}}]}` — the exact
    OpenAI call shape, one key away from being a call — and its reasoning said "Let's start with
    web_search". cria saw no tool call, spent its one research nudge, and drafted a plan having read
    nothing; the grounding checks then handed that plan back twice.

    Shape-driven, not key-name-driven: ANY top-level value holding `{name, arguments}` entries counts,
    so `commands`/`tool_calls`/`actions` all work without a list of blessed key names. The name must
    be on the menu, which is what keeps prose from becoming an action."""
    schemas = _menu_schemas(tools)
    if not schemas:
        return []
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return []
    calls = []
    for value in obj.values():
        for entry in (value if isinstance(value, list) else [value]):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or name not in schemas or "arguments" not in entry:
                continue
            args = entry["arguments"]
            if isinstance(args, dict):
                text = json.dumps(args, ensure_ascii=False)
            elif isinstance(args, str):
                field = _sole_required(schemas[name])
                if field is None:
                    continue          # can't place it without guessing — leave it alone
                text = json.dumps({field: args.strip()}, ensure_ascii=False)
            else:
                continue
            calls.append({"id": f"env_{len(calls)}", "type": "function",
                          "function": {"name": name, "arguments": text}})
    return calls


# ------------------------------------------- a call written as CALL SYNTAX in `content`
#
# MEASURED 2026-08-03 over every capture in ~/.cria/calls — 11,454 coder/proxy replies. 404 came
# back with NO tool_calls and a JSON object sitting in `content`; 50 of those hold an object whose
# keys are all properties of a tool THIS request advertised; 46 of the 50 also wrote that tool's
# NAME immediately in front of the object, in call syntax:
#
#     edit_file({"path": "test_resolve_handle.py", "old_string": "…", "new_string": "…"})
#
# No recovery reaches them. :func:`_envelope_calls` wants `{name, arguments}` ENTRIES inside one
# object and this shape has the name OUTSIDE it; :func:`_extract_leaked` reads angle-bracket
# dialects only. So the model named a tool on the menu, supplied a complete argument object keyed
# by that tool's own schema, and cria threw the turn away — which reads to the loop as a completion
# claim and buys a critic round-trip.
#
# THE FOUR THAT ARE NOT THIS ARE NOT TOUCHED. Three wrote a name the request never advertised
# (`create_file`, `fix_file`) and one wrote a bare ```json object with no name anywhere. Recovering
# those means choosing a tool for the model — authoring, not reshaping (principle 5b).
#
# WHAT THE GATES BELOW ADMIT, replayed over the whole corpus: 48 replies recovered and 4 refused as
# cut at the output cap, out of 2,537 lost replies holding a JSON object. Of the 46 the population
# was drawn from, 43 recover; the 3 that do not are the bare-name shape (twice) and one reply that
# opened with prose. Eight of the 48 are the steer-diagnose REASONER, whose read-only menu is what
# holds it to `read_file`/`list_dir` — the loop's own inspection round already documents this exact
# recovery as if it existed (see cria/loop.py, "a flaky-dialect model leaks its tool call as TEXT").
#
# WHICH MODELS. Mapping each capture session to the suite row that owns it: mellum2 17 of 779, and
# every other mapped model ZERO (gemma4 0/222, qwythos 0/237, nemotron-elastic 0/85,
# ternary-bonsai 0/47, zaya1 0/10, ornith 0/8, qwopus 0/5). The remaining 31 recoveries are in
# sessions no suite row maps, so "this is a mellum2 shape" is NOT established — a majority of the
# population is unattributed and saying otherwise would be the mistake the sibling parser's comment
# had to be corrected for (rule 23b).
#
# READING THEM (rule 23b) is what set the boundary below, and no count would have. The 46 fall into
# three shapes:
#
#   * 14 are the call and nothing else, sometimes several in a row (one reply is fourteen
#     consecutive `read_file` calls). Whole-reply Python grammar reads these.
#   * ~11 close the call `}}` instead of `})`. The ARGUMENT object is brace-complete and parses;
#     only the terminator is mistyped. So the object is located by :func:`jsontext._balanced_object`
#     rather than by matching a paren, and a run of `)}]` after it is accepted as the terminator
#     however the model spelled it.
#   * ~17 write one well-formed call and then IMPERSONATE THE HARNESS — 1454 continues with
#     "tool: ⟦ctx:edit⟧ … old_string matches 2 places" and a whole fabricated ⟦ctx:checks⟧ block;
#     1002 fabricates a tool result and then a second call, `exec_command`, re-running cria's own
#     gate script. That is a stop-token failure, not a plan. Forwarding the LAST call there would
#     execute the model's fabrication of its own future turn.
#
# Hence the one structural rule: only the LEADING RUN of calls is recovered. Scanning starts at the
# first byte of `content`; between two calls nothing may sit but whitespace and dialect tags; the
# first byte that is neither ends the run, and everything from there stays in `content` untouched.
# That is a prefix of the token stream, not a choice among candidates — cria never picks WHICH call
# the model meant. It also makes the fence gate free: a reply that opens ``` does not begin with a
# call, so a displayed example is never an action.
#
# WHICH WAY IT FAILS: toward more work, never toward a wrong action, and never toward "done".
#   * A refusal is exactly today's behaviour — the turn is lost, the critic runs, the coder retries.
#   * A recovery can only ADD a tool call to a turn that had none. A turn that carries a tool call
#     is not a completion claim, so this can never approve a task; a recovered `task_complete` is
#     forwarded like any other call and meets the same completion gate it always did.
#   * It never runs when the harness already produced tool calls, nor when an earlier recovery in
#     this function did (regression-only, principle 2).
#
# THE GATES, reusing the reasoning-channel parser's rather than writing a second, weaker set:
#   1. the turn is already lost — no tool_calls (checked by the caller, which also refuses a reply
#      cut at the output cap: a truncated generation's last call is a guess).
#   2. the call is COMPLETE — the argument object must be brace-balanced and parse. An unclosed
#      object ends the run; nothing is salvaged from a fragment.
#   3. every argument value is a literal the model wrote. `jsontext.loads` yields JSON values only,
#      so this holds by construction — there is no expression grammar to admit here at all.
#   4. the name is on the menu THIS request advertised, every `required` argument is present and
#      non-null (:func:`_menu_admits`), AND every key the model wrote is a declared property of
#      that tool. The last half is what makes the object unambiguously the ARGUMENTS and not some
#      other structure that happens to follow a name — cria never places a value by guessing.
#   5. terminal-and-unquoted, in the form this channel supports it: the run must START the reply,
#      and it ends at the first byte that is not another call.

_CALL_SYNTAX_OPEN = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(?=\{)")
# How a model closes this call once the argument object is done. `)` is the dialect; `}` and `]`
# are the two mistypes the corpus holds. Accepted as a terminator, never required — the object's
# own closing brace is what ends the call.
_CALL_SYNTAX_TERM = ")}]"


def _skip_between_calls(text: str, pos: int) -> int:
    """Past whitespace and dialect tags — the ONLY things that may sit between two calls of a run.

    Deliberately not "any punctuation": the whole safety of the leading-run rule is that prose
    stops it, and a skipper that steps over prose would step over a fabricated tool result.

    "Dialect tag" is :data:`_TAG_TOKEN`, and it is ANGLE-BRACKET SHAPE, not a list of known tags —
    which is the honest statement of the bound, because `<[^<>\\s][^<>]*>` also matches a sentence a
    model wrapped in angle brackets. Prose stops the run only where prose is UNBRACKETED. Measured
    2026-08-03 over every capture: across the 52 replies this parser reads a call out of, the only
    span it ever stepped over is `</tool_call>`, 17 times, and it stepped over nothing at all before
    a leading call. Widening this to a fixed tag list would be tuning a matcher against imagined
    cases the corpus does not hold (principle 15); the claim is narrowed here instead."""
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _TAG_TOKEN.match(text, pos)
        if not m:
            break
        pos = m.end()
    return pos


def _call_syntax_calls(content: str, tools) -> tuple[list[dict], str]:
    """(the leading run of `NAME({…})` calls in ``content``, what is left of ``content``).

    ``([], content)`` when the reply does not START with such a call — which is the answer for
    every reply that opens with prose, a fence, or a name the menu does not carry. Rationale, the
    measurement and the refusal gates are in the block comment above."""
    schemas = _menu_schemas(tools)
    if not schemas:
        return [], content              # gate 4: no menu → nothing can be an action
    calls: list[dict] = []
    pos = 0
    while True:
        m = _CALL_SYNTAX_OPEN.match(content, _skip_between_calls(content, pos))
        if m is None:
            break
        name = m.group(1)
        if name not in schemas:
            break
        span = jsontext._balanced_object(content, m.end())
        if span is None:
            break                       # gate 2: the arguments never closed — refuse the fragment
        try:
            args = jsontext.loads(span)
        except ValueError:
            break
        if not isinstance(args, dict) or not all(isinstance(k, str) for k in args):
            break
        props = set((schemas[name] or {}).get("properties") or {})
        if not props or not set(args) <= props or not _menu_admits(name, args, schemas):
            break                       # gate 4: this object is not that tool's argument list
        calls.append(_toolcall(name, args))
        pos = m.end() + len(span)
        while pos < len(content) and content[pos] in _CALL_SYNTAX_TERM:
            pos += 1                    # the terminator, however the model spelled it
    if not calls:
        return [], content
    # Nothing but dialect scaffolding left (a stray `</tool_call>` the model closed with, whose
    # opener never came) is not an answer the coder wrote — drop it by the SAME predicate that
    # decides what may sit between two calls, never by a second rule about what looks like debris.
    rest = content[pos:]
    return calls, "" if _skip_between_calls(rest, 0) == len(rest) else rest


def content_text(content) -> str:
    """The TEXT of an assistant/user ``content`` field, whatever shape it arrived in.

    A message's content is a plain string on the classic completions wire and a LIST OF PARTS
    (``[{"type": "text", "text": …}, …]``) on every client that can also send an image — both
    shapes reach cria, and code that tests only ``isinstance(content, str)`` reads a parts-list
    reply as EMPTY. Deliberately inclusive: any dict part carrying a ``text`` counts, typed or
    not, because every caller here uses the result to decide whether the model already SAID
    something, and over-reading text can only make a guard decline to act (rule 13, fail safe)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def turn_text(msg: dict) -> str:
    """What the model actually PRODUCED this turn: ``content`` when it wrote there, else the
    reasoning channel.

    A pure reader, so a loop rebuilding its own transcript can use it without mutating a
    completion — which is the difference between this and ``coerce_text_answer``. Same rule that
    reader already applies to a final answer, and the mirror of ``loop._reasoning_of``'s content
    fallback (principle 19: read a model's reasoning from either channel).

    It exists because cria's judge loop was erasing its own analysis. ``_judge_completion`` rebuilds
    the judge's conversation between inspection rounds, and both write-back sites took ``content``
    alone. For a thinking model calling a tool — ``content`` empty, the analysis in
    ``reasoning_content`` — the turn written back was ``{"content": None, "tool_calls": [...]}``, so
    by the final tools-withdrawn round the judge faced a transcript in which it appeared to have
    said nothing. Measured across one campaign arm: 140 of 329 judgment calls returned empty
    content, 42%. On one run the steer author spent 28,777 characters reaching the correct root
    cause and cria discarded it — found it, then lost it."""
    if not isinstance(msg, dict):
        return ""
    text = content_text(msg.get("content")).strip()
    if text:
        return text
    for key in ("reasoning_content", "reasoning"):
        alt = msg.get(key)
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    return ""


def recover_leaked_tool_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Promote a tool call the model emitted as TEXT (Hermes `<tool_call>…`, XML
    `<function=…>`) into a real tool_calls entry, and strip it from the content.

    Finishes with :func:`recover_reasoning_tool_calls`, which asks the same question of the
    REASONING channel — the one place llama.cpp's own parser never looks. Chained here rather
    than added to :func:`apply` so that every caller gets it from ONE owner, including
    ``planner.py``, which calls this function directly and not ``apply``."""
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
        if not isinstance(content, str) or not content.strip():
            continue
        calls: list[dict] = []
        cleaned = content
        if "<" not in content:
            # No angle-bracket dialect. The call may still be here as JSON DATA — the same leak,
            # a different envelope. Content is dropped whole (the call replaces it): a model that
            # emitted its actions as data has not also written an answer worth keeping.
            env = _envelope_calls(content, tools)
            if env:
                msg["tool_calls"] = env
                msg["content"] = None
                if choice.get("finish_reason") in (None, "stop"):
                    choice["finish_reason"] = "tool_calls"
                _log(rlog, "massage.envelope_recovered",
                     calls=[c["function"]["name"] for c in env])
                continue
        else:
            calls, cleaned = _extract_leaked(content, _menu_schemas(tools))
        event = "massage.leaked_recovered"
        if not calls:
            # Neither dialect above. The call may still be here in CALL SYNTAX — `edit_file({…})` —
            # which is 46 of the 50 replies measured to hold an offered tool's own argument object
            # and no tool call at all. See the block comment on :func:`_call_syntax_calls`.
            #
            # A reply CUT AT THE OUTPUT CAP is refused outright, and this is the gate that earns its
            # keep: replaying the parser over the corpus, one truncated 123 KB reply
            # (20260728T000013 call 0514) parses into 252 `edit_file` calls — a generation that ran
            # away rather than a plan, and forwarding it would have been cria authoring a 252-action
            # turn out of a fragment. Gate 2's rule for one call ("a truncated call is not salvaged")
            # applied to the run: where the reply itself is truncated its LAST call is a guess, and
            # the run has no end the model wrote. The paths above are deliberately left alone — this
            # is regression-only, and it may not change what they already do.
            calls, cleaned = _call_syntax_calls(content, tools)
            if calls and choice.get("finish_reason") == "length":
                _log(rlog, "massage.call_syntax_truncated",
                     calls=[c["function"]["name"] for c in calls], chars=len(content))
                continue
            event = "massage.call_syntax_recovered"
        if calls:
            msg["tool_calls"] = calls
            msg["content"] = cleaned or None
            if choice.get("finish_reason") in (None, "stop"):
                choice["finish_reason"] = "tool_calls"
            _log(rlog, event, calls=[c["function"]["name"] for c in calls])
    return recover_reasoning_tool_calls(completion, tools, rlog)


# ------------------------------------------------- a call left in the REASONING channel
#
# MEASURED 2026-08-03 over every capture in ~/.cria/calls — 127 sessions, 18,770 replies: 80 replies
# came back with `content: null`, NO `tool_calls`, and tool-call dialect sitting in
# `reasoning_content`. Nothing in cria ever looked there.
#
# WHICH MODELS, re-derived at review. The capture's own `model` field is the routing alias "cria" on
# every request, so it cannot attribute anything; the real model comes from the suite row that owns
# the session. Mapping 96 sessions that way:
#
#     fabliq            63 of 1,159   (61 coder + 2 reasoner)
#     nemotron-elastic   9 of   446   (coder)
#     zaya1              5 of    69   (planner)
#     mellum2            2 of 4,593   (coder)
#     gemma4 0/6,768 · qwythos 0/1,241 · ternary-bonsai 0/494 · ornith 0/63 · qwopus 0/39
#     (1 further loss is in a session no suite row maps)
#
# It skews hard by model, but "mellum2 … lost none" — as the commit that landed this said — is FALSE,
# and zaya1 was missing from that table altogether. Corrected here rather than left standing: a
# number in shipped source is not allowed to be approximately right (rule 23b).
#
# It compounds. 65 of the 80 were IMMEDIATELY followed by a critic call, because a turn with no tool
# call reads to cria as a completion claim — so each lost turn also buys a critic and a confirm
# round-trip.
#
# RUN 20260802T195958, corrected at review, because the story first told about it was wrong in the
# way that matters. The claim was "from call 0052 to call 0250 the cycle is coder → critic →
# critic-confirm thirty-five times, with the coder's prompt BYTE-IDENTICAL every cycle — all 33,168
# bytes of it … nothing in cria's loop could change that constant". Read the actual captures: there
# are SEVENTY coder calls in that span and TWO prompts that strictly alternate, 33,168 bytes and
# 33,188 bytes, 35 of each. They differ in one sentence — the ⟦ctx:steer⟧ line — and the two steers
# CONTRADICT each other, one saying the spec was never fetched and the other that it was fetched and
# saved. So cria did change the prompt, every other cycle; the run is a two-state oscillation, not a
# fixed point, and "the loop could not change the constant" is not what happened.
#
# What IS true, and is the whole case for this parser: the 33,168-byte prompt is byte-identical
# across all 35 of its occurrences, and the model answers it with a byte-identical lost turn every
# time — a deterministic function handed a constant. And the 20-byte sibling is NOT fixed here: its
# reply carries a JSON plan blob in `content`, so gate 1 refuses it by design. This recovers half of
# that deadlock. The other half is the same disease in the channel this function does not read, and
# it is still open (55 further turns corpus-wide emit dialect debris into `content` and produce no
# tool call). Naming it here so the next walk does not have to rediscover it.
# See :func:`recover_reasoning_tool_calls` on why the repeats are an argument FOR this, not against.
#
# WHY THE STRIPPER IS NOT THE FIX. :func:`_strip_lfm2_sentinels` deliberately DELETES
# `<|tool_call_start|>…<|tool_call_end|>` rather than parsing it, on the stated grounds that
# "llama.cpp's peg-native parser already handles a well-formed native call". That premise is true of
# `content` and false of `reasoning_content`. Verified on the same corpus: across the 12,406 replies
# where llama.cpp DID produce tool_calls, the sentinels survive in `content` ZERO times (its parser
# consumed them); across the 62 replies where the sentinels sit in `reasoning_content`, it produced a
# call ZERO times. Re-pointing the stripper at the reasoning channel would DELETE these calls, not
# recover them. So this is a PARSER, and it reads the reasoning channel only.
#
# WHAT IT ADMITS. Replaying the gates below over those 80 lost replies recovers 68 and refuses 12
# (reproduced exactly at review, with the split below). Every refusal is SAFE — a refusal is exactly
# today's behaviour — but "every refusal reads correctly on the file", as first written, overstates
# it: one of the twelve (20260802T181318 call 0016-planner) reads as a genuinely intended call the
# model fenced for formatting after writing "Thus, I propose:", not an illustration. EIGHT have no
# complete call at all — a narration
# that writes a whole source file as prose and then closes `</parameter></function></tool_call>`
# with tags that were never opened, a model quoting a previous tool RESPONSE the same way, a
# `<zyphra_tool_call>` with parameters but no `<function=NAME>`, a JSON blob ended by a bare
# `</tool_call>`, an `exec_command(…)]<|tool_call_end|>` whose opening sentinel never came. THREE
# name a tool the request never advertised (a plan-only planner reaching for exec_command; the
# read-only reasoner reaching for update_plan). ONE is a call the model fenced off as an
# illustration. Recovering any of them means inventing the tool name, the argument boundary, or the
# model's intent.
#
# WHICH WAY IT FAILS. Toward more work, never toward a wrong action. A missed recovery is exactly
# today's behaviour — the turn is lost, cria calls the critic, the coder tries again. A WRONG recovery
# would execute something the model did not ask for, so every gate below is a refusal:
#
#   1. the turn must ALREADY be lost — no text content AND no tool_calls. If llama.cpp surfaced the
#      call, or the model wrote prose, nothing here runs (regression-only, principle 2; and it is
#      what makes double-execution structurally impossible rather than merely unlikely). "Text" is
#      read through :func:`content_text`, so a parts-list reply counts as text like any other.
#   2. the call must be SYNTACTICALLY COMPLETE — opening delimiter, name, closing delimiter, and
#      arguments that parse. Unlike :func:`_extract_gemma`, a truncated call is NOT salvaged here:
#      salvage guesses, and guessing on the model's private channel is authoring.
#   3. every argument value must be a LITERAL the model itself wrote. Nothing is inferred, defaulted
#      or placed by schema — that is the line between reshaping a call and authoring one (principle
#      5b; cria guessing an argument is how its own `<keyword>` placeholder reached a live web_fetch).
#      SCOPE, stated exactly: this gate is enforced by :func:`_literal_kwargs` on the LFM2-native arm
#      only. The Hermes arm reads JSON (whose values are literals by construction) and the XML arm
#      reads `<parameter=…>` text, where `_XML_PARAM` is non-greedy — so nine `<parameter=steps>`
#      openers closed by ONE `</parameter>` collapse into a single string carrying the other eight
#      tags verbatim, where the tool's schema declares an array. That is a PRE-EXISTING property of
#      the content path (`recover_leaked_tool_calls` has always had it) which this function now
#      reaches from a second channel, and gate 4 does not catch it because the menu is asked for
#      presence, never for type. Named here because "every argument is a literal the model wrote" is
#      true of one of the three dialects and reads as if it were true of all three.
#   4. the name must be on the menu THIS request advertised, and every argument that menu marks
#      `required` must be present AND carry a value. The menu is what keeps prose from becoming an
#      action — the same gate :func:`_envelope_calls` relies on. A toolless request (a compaction, a
#      critic, a summarizer) advertises no menu, so a call can never be recovered out of one.
#   5. the call must be TERMINAL and UNQUOTED. Terminal: nothing but dialect tags and whitespace may
#      follow it — a call the model EMITTED is where generation stopped, while a call it merely
#      weighed and moved past has its own reasoning after it. Unquoted: an ODD number of ``` fences
#      opens before the call, so the call sits inside a code block the model is DISPLAYING, refuses
#      it. Both are structural facts about the token stream, not lexical guesses about intent.
#
# The reasoning text itself is NEVER modified. Only `tool_calls` is added. The
# rumination detector and `verdict_from_reasoning` all read `reasoning_content`, and rewriting it
# under them would change what they see for no gain (principle 2: the safe class is additive).

# The dialects measured to leak a COMPLETE call into the reasoning channel. Adding one is adding an
# entry here plus its parser; gemma-fable's `<|tool_call>call:NAME{…}` is deliberately absent — it
# produced this shape zero times in the corpus, and its existing parser SALVAGES truncated calls,
# which is the one thing gate 2 forbids (principle 15: don't build a detector for a case you have not
# measured — an unexercised arm is dead weight that can itself misfire).
_REASONING_DIALECTS = ("lfm2-native", "hermes-json", "xml-function")

# A tag-shaped token — any dialect's opener or closer. What may follow a recovered call and still
# leave it TERMINAL is exactly these plus whitespace. NOT backticks: a closing ``` fence after the
# call means the call was inside a fenced block the model was DISPLAYING, and v1 of this fix
# admitted `rm -rf /workspace` out of a reasoning that said "the dialect looks like this, for
# reference:" because a backtick counted as terminal.
_TAG_TOKEN = re.compile(r"<[^<>\s][^<>]*>")
_FENCE = "```"


def _is_terminal(text: str, end: int) -> bool:
    """Nothing but dialect tags and whitespace follows the span that ends at ``end``."""
    return not _TAG_TOKEN.sub("", text[end:]).strip()


def _is_quoted(text: str, start: int) -> bool:
    """The span starting at ``start`` sits inside an OPEN markdown code fence — an odd number of
    ``` delimiters precede it — so the model is displaying the call, not making it."""
    return text.count(_FENCE, 0, start) % 2 == 1


def _literal_kwargs(call) -> dict | None:
    """The keyword arguments of a parsed ``ast.Call``, each evaluated as a LITERAL — or None if any
    one of them is anything else.

    ``ast.literal_eval`` is the whole safety argument for this dialect: it accepts a string, number,
    bool, None, tuple, list, set or dict of literals and rejects every name, call, attribute and
    operator, so a recovered argument can only ever be bytes the model typed. Nothing is executed —
    the tree is parsed, never evaluated.

    …and it is a WIDER grammar than the wire. `literal_eval` also accepts four things JSON has no
    representation for — ``b'x'``, ``{'a', 'b'}``, ``frozenset``, ``1+2j`` — and :func:`_toolcall`
    serialises with ``json.dumps``, which raises ``TypeError`` on every one of them. Left unguarded
    that is not a refusal, it is a CRASH in the response path: on the server route the exception is
    caught by the ``(json.JSONDecodeError, TypeError)`` handler around ``massage.apply`` and reported
    as "upstream returned a non-JSON 200 body", which is a false fact about a reply that was perfectly
    good JSON (principle 5b); on the loop routes it is uncaught. So the encodability of the value is
    part of gate 3, not an afterthought at the encoder: an argument that cannot ride the protocol is
    not an argument the model can have meant on it, and every gate in this file must fail toward
    today's behaviour, never toward a 500."""
    if call.args:
        return None      # a positional argument cannot be placed without guessing which field it is
    args: dict = {}
    for kw in call.keywords:
        if kw.arg is None:
            return None  # `**something` — not a literal argument list
        try:
            args[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return None
    try:
        json.dumps(args)
    except (TypeError, ValueError, RecursionError):
        return None      # a literal the wire cannot carry — refuse, exactly like an unparseable one
    return args


def _lfm2_native_calls(body: str) -> list | None:
    """Parse an LFM2/Fabliq native call body — ``[read_file(path='./spec.json')]`` — with Python's
    OWN parser. Returns [(name, args), …] or None.

    The dialect is not JSON and not XML: it is Python call syntax, verbatim, and the captured bodies
    parse as a `list` of keyword-only calls over Python literals (a `web_fetch(url=…, raw=True)`, an
    `update_plan(plan=[{…}, …])`, a `write_file(path=…, content='…\\n…')` carrying a whole source
    file with its escapes intact). So the right parser is ``ast``, not a regex — a regex over this
    silently drops nested and numeric arguments, which is the mistake the gemma-fable comment above
    records having already made once.

    Using the real grammar is also what makes gate 2 free: a cut-off string or an unclosed paren is a
    ``SyntaxError``, so a truncated call cannot parse and is refused rather than half-recovered."""
    try:
        tree = ast.parse(body.strip(), mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    node = tree.body
    nodes = node.elts if isinstance(node, ast.List) else [node]
    out = []
    for c in nodes:
        if not isinstance(c, ast.Call) or not isinstance(c.func, ast.Name):
            return None  # `mod.fn(…)`, a bare name, an expression → not this dialect, refuse whole
        args = _literal_kwargs(c)
        if args is None:
            return None
        out.append((c.func.id, args))
    return out or None


def _reasoning_call_spans(text: str) -> list:
    """Every (start, end, dialect, [(name, args), …]) a COMPLETE tool call occupies in ``text``.

    Each arm requires both delimiters. The Hermes and XML arms reuse the very regexes the content
    path uses (:data:`_HERMES`, :data:`_XML_FN`, :data:`_XML_PARAM`), so the two channels can never
    drift apart on what those dialects look like."""
    spans = []
    i = 0
    while True:
        o = text.find(_LFM2_TC_OPEN, i)
        if o < 0:
            break
        c = text.find(_LFM2_TC_CLOSE, o + len(_LFM2_TC_OPEN))
        if c < 0:
            break  # an unterminated call — generation was cut off mid-emission; refuse it
        parsed = _lfm2_native_calls(text[o + len(_LFM2_TC_OPEN):c])
        if parsed:
            spans.append((o, c + len(_LFM2_TC_CLOSE), "lfm2-native", parsed))
        i = c + len(_LFM2_TC_CLOSE)
    for m in _HERMES.finditer(text):
        obj = extract_json_object(m.group(1))
        if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
            continue
        args = obj.get("arguments", {})
        if isinstance(args, str):
            args = extract_json_object(args)
        if isinstance(args, dict):
            spans.append((m.start(), m.end(), "hermes-json", [(obj["name"], args)]))
    for m in _XML_FN.finditer(text):
        body = m.group(2)
        args = _xml_args(body)
        # No `<parameter=…>` pair and no JSON body means the arguments never arrived — the nemotron
        # shape where a whole file was narrated as prose and then closed with tags that were never
        # opened. There is nothing to recover, and inventing the payload is the thing this function
        # exists not to do.
        if args:
            spans.append((m.start(), m.end(), "xml-function", [(m.group(1), args)]))
    return _outermost(sorted(spans, key=lambda s: (s[0], s[1])))


# A parameter value ends at the `</parameter>` that BALANCES its opener — matched like brackets,
# because the two shapes that break a naive rule are byte-identical at the start:
#
#   unclosed   <parameter=content><project>…</project></function></tool_call><tool_call>
#              <function=task_complete><parameter=summary>done</parameter>
#   nested     <parameter=content>Call it like this: <parameter=url>http://x</parameter></parameter>
#
# Earliest-closer swallows the next CALL in the first. Own-closer-wins cuts the DOCUMENTATION in the
# second. Only depth tells them apart: the nested one balances, the unclosed one never does. When the
# openers outnumber the closers the value stops at the next structural boundary instead — the sibling
# opener, or the end of the call.
_PARAM_OPEN = re.compile(r"<parameter=([A-Za-z0-9_.-]+)\s*>")
_PARAM_CLOSE = "</parameter>"
# Past these a value cannot possibly extend: they end the call or the turn.
_PARAM_HARD_BOUNDARIES = ("</function>", "</tool_call>")


def _bounded_xml_params(body: str) -> list:
    """`[(name, value)]` for every `<parameter=NAME>` in ``body``, each value ending at the closing
    tag that balances it, or — when it has none — at the next opener or call boundary.

    Replaces a bare non-greedy `findall`, which sounds safe and is not: with no closing tag of its
    own a match runs on to the NEXT one, in another parameter or another CALL. Measured on
    `feed-pipeline-java x nemotron-elastic`: a `write_file` whose `content` swallowed the whole
    `task_complete` that followed it, so `validate-before-lower` refused the `pom.xml` twelve times
    as malformed XML at the line where cria's own junk began. The file's gate-3 note has described
    this shape since it was written and called it pre-existing; it was a defect.

    Returns the shape `_XML_PARAM.findall` did, so the caller is unchanged and both dialect channels
    keep one definition of the syntax."""
    out = []
    for m in _PARAM_OPEN.finditer(body):
        name, start = m.group(1), m.end()
        depth, i, end = 1, start, None
        while i < len(body):
            nxt_open = _PARAM_OPEN.search(body, i)
            nxt_close = body.find(_PARAM_CLOSE, i)
            if nxt_close == -1:
                break                                  # never closed at all
            if nxt_open and nxt_open.start() < nxt_close:
                depth += 1
                i = nxt_open.end()
                continue
            depth -= 1
            if depth == 0:
                end = nxt_close
                break
            i = nxt_close + len(_PARAM_CLOSE)
        if end is None:
            # Unbalanced: stop at the earliest thing that cannot be part of this value.
            end = len(body)
            sib = _PARAM_OPEN.search(body, start)
            if sib:
                end = min(end, sib.start())
            for tag in _PARAM_HARD_BOUNDARIES:
                j = body.find(tag, start)
                if j != -1:
                    end = min(end, j)
        out.append((name, body[start:end]))
    return out


def _xml_args(body: str) -> dict | None:
    """Arguments for one `<function=NAME>…</function>` span.

    `<parameter=…>` tags WIN over a JSON scan of the same text, and the order is the whole point.
    Reading JSON first means any tool call whose payload happens to contain an object literal has
    its arguments replaced by that literal. Measured on the battery's second baseline run
    (qwen35 / shipping-rates-py, 2026-08-10): the model emitted a correct `edit_file` whose
    new_string was the fixed `rates.py`, containing `{"domestic": 0.75, "eu": 1.50, …}` — and the
    parser returned `{domestic, eu, international}` as the call's arguments. `_menu_admits` then
    rightly refused a call with no `path`, the fix was discarded, and the run scored 0/4 having
    touched nothing. Writing a dict literal is ordinary in every language this suite covers, so
    the failure is routine rather than exotic.

    A PARAMETER STOPS AT THE NEXT STRUCTURAL BOUNDARY when its own closing tag is missing.
    `_XML_PARAM` is non-greedy, which sounds safe and is not: with no `</parameter>` of its own, the
    match runs on to the NEXT one — which belongs to a different parameter, or a different CALL.
    The note on gate 3 above has described this since it was written ("nine `<parameter=steps>`
    openers closed by ONE `</parameter>` collapse into a single string carrying the other eight tags
    verbatim") and called it a pre-existing property; it is a defect and this is where it lived.

    Measured, `feed-pipeline-java x nemotron-elastic`, cycle 1: the model emitted a `write_file` and
    a `task_complete` in one turn. The write's `content` had no closing tag, so it swallowed the rest
    of its own call AND the whole next one — the recorded value ends
    `…</project></function></tool_call><tool_call><function=task_complete>`. `validate-before-lower`
    then refused the `pom.xml` twelve times as malformed XML, at "line 34, column 1", which is
    exactly where cria's junk began. Fourteen calls lost; the model escaped only by switching tools.
    The trailing call is always `task_complete`, so a feature added to make completion cleaner was
    corrupting the write in front of it.

    THE REAL CLOSING TAG STILL WINS when it exists, which is what keeps a legitimately nested payload
    intact — a `write_file` whose content is a document ABOUT tool calls really does contain
    `<parameter=` and `</function>` text, and :func:`_outermost` exists because that happens. The
    boundary only applies when there is no `</parameter>` to find before it.

    JSON remains the fallback for the shape that has no parameter tags at all."""
    params = _bounded_xml_params(body)
    if params:
        return {k: v.strip() for k, v in params}
    obj = extract_json_object(body)
    return obj if isinstance(obj, dict) else None


def _outermost(spans: list) -> list:
    """Drop every span that another span ENCLOSES.

    Dialects nest: an XML `write_file` whose `content` parameter shows a hermes `<tool_call>`
    example produces two spans, and the nested one starts LATER — so picking the last span by
    position takes the model's illustration and throws away the write it was illustrating. The
    enclosing span is the call; anything inside it is that call's payload."""
    return [s for s in spans
            if not any(o is not s and o[0] <= s[0] and s[1] <= o[1] for o in spans)]


def _menu_admits(name: str, args: dict, schemas: dict) -> bool:
    """The call names a tool THIS request advertised, and carries every argument that tool's own
    schema marks ``required`` with a value that is not null. Both halves ask the menu, never a
    hardcoded list — and a request with no tools admits nothing at all.

    Present-but-null is refused, not just absent: `write_file(path='x', content=None)` satisfies
    "has the key" and then lowers to a byte-exact write of nothing, truncating a working file while
    reporting success. A required argument the model left empty is a call it did not finish."""
    if name not in schemas:
        return False
    req = (schemas.get(name) or {}).get("required")
    if isinstance(req, list):
        return all(args.get(r) is not None for r in req if isinstance(r, str))
    return True


def recover_reasoning_tool_calls(completion: dict, tools=None, rlog=None) -> dict:
    """Promote a complete tool call the model left in ``reasoning_content`` into a real ``tool_calls``
    entry — the one channel llama.cpp's own parser never reads. Full rationale, the refusal gates
    and the measured prevalence are in the block comment above.

    Additive and idempotent: it only ever ADDS ``tool_calls`` to a choice that had none, never edits
    the reasoning, and a second pass sees the calls it just added and does nothing.

    **Why the identical repeats are NOT deduplicated here.** 41 of the 68 recoveries in the corpus
    are byte-identical to one already recovered in the same session, 35 of them the same
    ``web_fetch('https://api.handle.me/swagger.yml', find='swagger')``, whose own reasoning says the
    previous attempt returned a 404. That looks like a reason to recover only the first of a kind.
    It is the opposite. The repeats are identical because the coder's PROMPT was identical — the
    same 33,168 bytes for thirty-five consecutive cycles — and the reason cria could never change
    that prompt is that :func:`loop.guard_track_repetition`, :func:`loop.guard_track_write_streak`,
    the search-loop matcher and the fetch ledger all iterate FORWARDED TOOL CALLS, and a lost turn
    forwards none. Recovering the call is what lets them see it: the third identical one trips
    ``redirect_due`` (``REPEAT_FINGERPRINT_N``), and a redirect changes the prompt. Suppressing the
    repeat here would starve the guard that ends the loop of the only evidence it runs on, and would
    re-create the deadlock one cycle later — a second, dumber repeat-detector in the massage layer,
    shadowing the real one (principle 4). The loop already owns "the same action, again"; this
    function's only job is to stop losing the action."""
    schemas = _menu_schemas(tools)
    if not schemas:
        return completion  # gate 4: no menu → nothing can be an action
    for choice in completion.get("choices", []):
        msg = choice.get("message")
        if not isinstance(msg, dict):
            continue
        # gate 1. Only a turn that is ALREADY lost. Note this also settles double-execution: if
        # llama.cpp surfaced the call itself, `tool_calls` is set and this returns untouched.
        if msg.get("tool_calls") or content_text(msg.get("content")).strip():
            continue
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if not isinstance(reasoning, str) or not reasoning.strip():
            continue
        spans = _reasoning_call_spans(reasoning)
        if not spans:
            continue
        start, end, dialect, parsed = spans[-1]
        # gate 5. TERMINAL — the generation stopped at this call — and not quoted inside a fence.
        if not _is_terminal(reasoning, end) or _is_quoted(reasoning, start):
            _log(rlog, "massage.reasoning_call_not_terminal", dialect=dialect,
                 calls=[n for n, _a in parsed], trailing=len(reasoning) - end,
                 quoted=_is_quoted(reasoning, start))
            continue
        # gate 4. Every call in the span must be admitted; one stranger refuses the lot, because a
        # partly-forwarded list is an action sequence the model never asked for.
        parsed = [(n, coerce_args(n, a, schemas)) for n, a in parsed]  # XML has no types; the schema does
        if not all(_menu_admits(n, a, schemas) for n, a in parsed):
            _log(rlog, "massage.reasoning_call_off_menu", dialect=dialect,
                 calls=[n for n, _a in parsed])
            # REFUSING TO FORWARD IS RIGHT; SAYING NOTHING IS NOT. The turn now leaves here exactly
            # as it arrived — empty content, no tool_calls — and the model reads that as its action
            # having produced no result. It repeats, or reasons on from memory, while downstream
            # cria reads the same empty turn as the coder FINISHING and runs the gate and the
            # satisfaction judge against a workspace where nothing happened.
            #
            # Measured across the six-language battery: nemotron-elastic's "quits after two calls"
            # signature is this. Run 1786436075 call 0006 is the FIRST action of the run — a
            # complete `str_replace_editor` view call in the reasoning channel — swallowed, and the
            # completion machinery engaged at calls 7-12 after two list_dirs. Calls 0167, 0178 and
            # 0180 are the same swallow again.
            #
            # cria owns the menu, so "that tool does not exist and here is what does" is a fact it
            # can state (#5b, the honest direction). It cannot be said here — this function only
            # reads the model's reply — so the fact rides out as a cria-internal hint and the loop
            # says it, the `cria_output_reserve` pattern (#24: carry the intent, consume it where it
            # belongs).
            completion[LOST_CALL_KEY] = {"tried": sorted({n for n, _a in parsed}),
                                         "menu": sorted(schemas)}
            continue
        msg["tool_calls"] = [_toolcall(n, a) for n, a in parsed]
        if choice.get("finish_reason") in (None, "stop"):
            choice["finish_reason"] = "tool_calls"
        _log(rlog, "massage.reasoning_call_recovered", dialect=dialect,
             calls=[n for n, _a in parsed], at=start, reasoning_chars=len(reasoning))
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


def _extract_leaked(content: str, schemas: dict | None = None) -> tuple[list[dict], str]:
    calls: list[dict] = []
    cleaned = content

    for m in _HERMES.finditer(content):
        obj = extract_json_object(m.group(1))
        if obj and obj.get("name"):
            calls.append(_toolcall(str(obj["name"]), obj.get("arguments", {})))
            cleaned = cleaned.replace(m.group(0), "")

    for m in _XML_FN.finditer(content):
        name, body = m.group(1), m.group(2)
        args = _xml_args(body) or {}
        resolved = _alias(name)
        calls.append(_toolcall(resolved, coerce_args(resolved, args, schemas or {})))
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
    # i64 fidelity: Rust's i64::parse accepts only optional '-' + digits — NOT Python int()'s '1_000'
    # underscores or '+5' leading plus. Gate on the strict shape so a bare token stays a string exactly
    # where the ported dialect would keep it one.
    if re.fullmatch(r"-?[0-9]+", raw):
        return int(raw)  # floats/underscored/plus-prefixed stay strings, quirk preserved
    return raw


def _alias(name: str) -> str:
    return "shell" if name in _SHELL_ALIASES else name


# ------------------------------------------------------------------ streaming


_LEAK_MARKERS = ("<tool_call", "<function=", "<|tool_call", "<|channel")  # <|channel: Gemma's thought channel (buffered path strips it; the stream path must hold it back too)
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
    not the fresh generation, it bricks the whole session and never recovers (observed live 2026-07, retired-model run).

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
    :func:`has_incomplete_tool_args` then flags it so the loop drops the partial write."""
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


def _content_truncated(fn: dict) -> bool:
    """A ``write_file`` whose ARGS parse (valid JSON, normal `tool_calls` finish) but whose CONTENT is a
    provably-truncated source file — the model cut its own file off mid-string, so the JSON-level guard
    above misses it (observed live: a .py written as an opening ``\"\"\"`` docstring + 517 chars, then it
    STOPS — no closing ``\"\"\"``, no code; the syntax floor then flagged "unterminated triple-quoted
    string" 565× while the coder edit-thrashed a file it could never make parse). Signal = an ODD count of
    a triple-quote delimiter, CONFIRMED by the language's own parser failing, so a legit ``\"\"\"`` inside a
    string can't false-positive. Confirmable today for Python (`compile`); other languages fall through to
    the gate. Only a full-file ``write_file`` is checked — an ``edit_file`` new_string may be a partial."""
    if fn.get("name") not in ("write_file", "create_file"):
        return False
    try:
        args = jsontext.loads(fn.get("arguments") or "", strict=False)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(args, dict):
        return False
    content, path = args.get("content"), args.get("path") or ""
    if not isinstance(content, str) or not content.strip():
        return False
    if content.count('"""') % 2 == 0 and content.count("'''") % 2 == 0:
        return False  # balanced triple-quotes → no unterminated-docstring signal
    if str(path).endswith(".py"):
        try:
            compile(content, "<write>", "exec")
            return False  # odd count but it PARSES (a \"\"\" lived inside a string) → not truncated
        except SyntaxError:
            return True   # odd triple-quote AND won't parse → a cut-off write; refuse it
    return False


def has_incomplete_tool_args(completion: dict) -> bool:
    """ANY tool call the model cut off mid-arguments — so forwarding it lowers a broken call. Two cut-off
    shapes: (1) the `arguments` are STILL unparseable after repair (a mid-JSON cut — a normal `tool_calls`
    finish, not `length`; observed live: a self-truncated ``exec_command`` whose inline ``python3 -c "…``
    leaked the model's ``<|tool_call_end|>`` dialect token mid-string, so Codex rejected it with "failed
    to parse function arguments: EOF while parsing a string" 564× in one run); (2) for a content-bearing
    WRITE, the args PARSE but the CONTENT is a provably-truncated source file (:func:`_content_truncated`).
    The parse check is tool-AGNOSTIC (a write, an exec_command, anything) — a broken call must never reach
    the harness. The content check is write-only. The loop refuses either like a length-truncation."""
    for ch in completion.get("choices", []):
        for tc in (ch.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments")
            if not isinstance(raw, str):
                continue
            try:
                json.loads(raw, strict=False)
            except (json.JSONDecodeError, ValueError):
                return True  # repair could not close it → the call was cut off mid-arguments
            if fn.get("name") in _MUTATION_TOOLS and _content_truncated(fn):
                return True  # write args parse but the file content is cut off mid-string → refuse
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
                args = jsontext.loads(fn.get("arguments", "{}"))
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
                # A "removal" is impossible in a NEW file, so a bare '-' line is CONTENT the model forgot
                # to '+'-prefix (a YAML list item, a markdown bullet, CLI-help '-v') — keep it as an
                # addition, don't silently drop it (that destroyed the created file's content).
                out.append("+" + line)
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


# --- strict-template turn alternation (a WIRE normalization) -----------------------------------
#
# The template groups `tool` WITH `user`: a tool result is rendered as a user turn wrapping
# <TOOL_RESPONSE>[…]. So the two sides that must alternate are {user, tool} and {assistant}.
_USER_SIDE = ("user", "tool")

# The cria-internal body hint that turns this on, set by `Role.apply` from the role's
# `merge_consecutive_turns` and consumed + stripped by `Upstream._prep`. Same contract as
# `cria_output_reserve`: a hint cria carries on the body, never a wire field.
MERGE_TURNS_KEY = bodykeys.MERGE_TURNS
# A turn whose only action named a tool that does not exist. cria-internal, consumed and stripped by
# the loop, never on the wire. See the refusal site in recover_reasoning_tool_calls.
LOST_CALL_KEY = bodykeys.LOST_CALL


def merge_for_alternation(messages: list) -> list:
    """Collapse each run of consecutive same-side messages into one, so roles strictly alternate.

    For a Llama-lineage template the sides are {user, tool} and {assistant} — a tool result IS a
    user turn to that template, which is why merging by ROLE alone is not enough: cria commonly
    emits `tool` then a ⟦ctx:…⟧ `user` anchor, and that pair is already a violation.

    Nothing is dropped and nothing is reordered. cria's anchors are self-delimiting blocks — each
    opens with its own ⟦ctx:…⟧ marker — so concatenating them reads exactly as it did when they were
    separate turns. A merged run keeps the role of its FIRST message, which preserves the
    <TOOL_RESPONSE> framing when a tool result leads.

    The system message is left where it is: the template consumes messages[0] as the system prompt
    before the alternation loop ever runs, so it is outside the rule.

    THIS RUNS AT THE WIRE, and that placement is the whole fix. It lived in `Role.apply`, which runs
    mid-pipeline — so every later append defeated it. nemotron-nano run 1786243834 died on exactly
    that: `focustrim` appends its repeat-note as a `user` turn AFTER the role was applied, the body
    went out as `…, tool, user`, and the template answered `Conversation roles must alternate` six
    times until the harness gave up (calls 0075-0081, workspace empty). Four call sites append
    user-side turns after `Role.apply` — the plan-off driver, `guard_rumination`, `guard_truncation`,
    and the streaming proxy, which skips the trim entirely — so ordering them one by one is a
    band-aid per site (#4). At the wire there is no "later": this is the last transform before the
    body is serialized, alongside its assistant-side twin `_merge_consecutive_assistant` and the
    unconditional orphan-`tool` repair, both of which live here for the identical reason."""
    if not isinstance(messages, list) or len(messages) < 2:
        return messages

    def side(m):
        r = m.get("role") if isinstance(m, dict) else None
        return "u" if r in _USER_SIDE else ("a" if r == "assistant" else None)

    head = list(messages[:1]) if isinstance(messages[0], dict) and messages[0].get("role") == "system" else []
    out: list = []
    for m in messages[len(head):]:
        sd = side(m)
        prev = out[-1] if out else None
        # An assistant turn carrying tool_calls is a structured emission — never fold another
        # message into it, and never fold it into one. Only its TEXT siblings merge.
        mergeable = (sd is not None and prev is not None and side(prev) == sd
                     and not (prev.get("tool_calls") or m.get("tool_calls"))
                     and isinstance(prev.get("content"), str) and isinstance(m.get("content"), str))
        if mergeable:
            merged = dict(prev)
            merged["content"] = f"{prev['content']}\n\n{m['content']}".strip()
            out[-1] = merged
        else:
            out.append(dict(m) if isinstance(m, dict) else m)
    return head + out
