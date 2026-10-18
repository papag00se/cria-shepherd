"""Literal call dialects, schema facts and text readers; no selected execution.

XML readers return raw arguments. Selection, conversion, admission orchestration
and intervention events belong to their Source adapters above this library.
"""
from __future__ import annotations

import ast
import json
import re
import uuid

from . import jsontext
from .jsontext import extract_json_object
from .toolargs import PATH_KEYS, WHOLE_FILE_WRITES

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


_GEMMA_TC_OPEN = "<|tool_call>"


_GEMMA_TC_CLOSE = "<tool_call|>"


_GEMMA_STR = '<|"|>'


_LFM2_TC_OPEN = "<|tool_call_start|>"


_LFM2_TC_CLOSE = "<|tool_call_end|>"


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


def _has_tool(name: str, tools) -> bool:
    return any((((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) == name for t in tools or [])


def _tool_names(tools) -> set:
    return {(((t.get("function") or t) if isinstance(t, dict) else {}).get("name")) for t in tools or []}


def is_truncated(completion: dict) -> bool:
    """The model was cut off at the output-token cap (`finish_reason == "length"`) —
    so any file it was writing is incomplete."""
    return any(ch.get("finish_reason") == "length" for ch in completion.get("choices", []))


def is_ruminating(completion: dict) -> bool:
    """The streaming coder path aborted this response as a reasoning loop (rumination detector) —
    `finish_reason == "rumination"`. The caller re-prompts to focus, rather than accept an empty
    turn. See `cria.rumination` + `Upstream.chat_watched`."""
    return any(ch.get("finish_reason") == "rumination" for ch in completion.get("choices", []))


def _menu_schemas(tools) -> dict:
    """{name: parameters schema} for the tools THIS request offers. The menu is what makes envelope
    recovery safe: a name is only ever an action if the request actually offers it."""
    out = {}
    for t in tools or []:
        fn = t.get("function") if isinstance(t, dict) else None
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            out[fn["name"]] = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
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


_CALL_SYNTAX_OPEN = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(?=\{)")


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


_FENCED_BLOCK = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.S)


def _envelope_pair(obj):
    """``(name, args)`` if ``obj`` is a two-key object holding exactly one STRING and exactly one
    OBJECT — the string is the tool name, the object its arguments — else None.

    NO KEY NAMES. phi4 spells the same call `{name, arguments}` (678 fenced objects),
    `{action, parameters}` (16), `{tool_call, arguments}` (6), `{action, args}` (4) and
    `{action, arguments}` (3), and a list of key names would be retuned for each spelling it has not
    yet used (principle 20). The SHAPE is the invariant: one string (what to call) and one object
    (with what). Whether that string names a tool is the MENU's question and is asked afterwards by
    :func:`_fenced_envelope_call`, exactly as for the original `{name, arguments}` form — so a
    two-key object that is merely data (`{"description": "…", "parameters": {…}}`) parses here and is
    refused there as ``off_menu``. Three or more keys never parse: a tool-schema echo
    (`name`+`description`+`parameters`) and a `package.json` are not calls."""
    if not isinstance(obj, dict) or len(obj) != 2:
        return None
    strs = [k for k, v in obj.items() if isinstance(v, str)]
    objs = [k for k, v in obj.items() if isinstance(v, dict)]
    if len(strs) != 1 or len(objs) != 1:
        return None
    return obj[strs[0]], obj[objs[0]]


def _fenced_envelope(body: str):
    """``(name, args)`` if ``body`` is exactly one call object (see :func:`_envelope_pair`), else None.

    No unwrapping: `{tool_call: {name, arguments}}` and `{tool_calls: […]}` are recovered earlier in the
    chain by :func:`_envelope_calls` (checked against the corpus: it recovers both, the batch whole)."""
    body = body.strip()
    if not body.startswith("{"):
        return None
    try:
        return _envelope_pair(jsontext.loads(body))
    except ValueError:
        return None


def fenced_file_blocks(content: str) -> list[dict]:
    """The TOP-LEVEL fenced blocks of ``content`` in order, each with the one line that precedes it.

    Depth-aware, like `loop.unexecuted_write`: a pasted README is a ```markdown block holding
    ```bash blocks, and a regex pairing fences reads the inner closing fence as the outer close.
    Each entry: ``lang``, ``lines`` (the body, verbatim), ``closed`` (False for a fence the reply ends
    inside — a cut-off file is never whole), ``start`` (char offset of the opening line), and
    ``binding`` (the nearest non-blank line before the fence that lies after the previous block, or
    None). Nothing is clipped, nothing interpreted."""
    lines = content.splitlines(keepends=True)
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)
    out: list[dict] = []
    depth = 0
    cur: dict | None = None
    prev_end = -1
    for i, raw in enumerate(lines):
        t = raw.strip()
        if t.startswith("```"):
            tag = t[3:].strip()
            if tag or depth == 0:                     # an opening fence (a tag always opens)
                if depth == 0:
                    j = i - 1
                    while j > prev_end and not lines[j].strip():
                        j -= 1
                    cur = {"lang": tag.split()[0] if tag else "", "lines": [], "closed": False,
                           "start": offsets[i], "binding": lines[j].strip() if j > prev_end else None}
                else:
                    cur["lines"].append(raw.rstrip("\r\n"))
                depth += 1
            else:                                      # bare ``` with something open → closing
                depth -= 1
                if depth == 0:
                    cur["closed"] = True
                    out.append(cur)
                    cur, prev_end = None, i
                else:
                    cur["lines"].append(raw.rstrip("\r\n"))
        elif depth > 0:
            cur["lines"].append(raw.rstrip("\r\n"))
    if depth > 0 and cur is not None:
        out.append(cur)
    return out


_PATH_TOKEN = re.compile(r"(?<![\w./\\-])((?:[\w.\-]+/)*[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z][A-Za-z0-9]{0,9})(?![\w/])")


_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


def binding_paths(line: str) -> list[str]:
    """The DISTINCT path-shaped tokens a binding line names — backticked ones when it has any (the
    model marked them as names), else bare ones. A token is a dotted name ending in a letter
    extension: `Importer.java`, `src/main/pom.xml`; not a version (`1.9.0`), a URL, or a sentence's
    full stop. Whether a token IS a file is the workspace's question, not this one's."""
    line = _URL.sub(" ", line or "")
    ticked = [m for span in re.findall(r"`([^`]+)`", line) for m in _PATH_TOKEN.findall(span)]
    found = ticked or _PATH_TOKEN.findall(re.sub(r"[*_`]", " ", line))
    return list(dict.fromkeys(found))


def has_call_envelope(content: str) -> bool:
    """Does the reply carry a fenced call object anywhere? Such a reply has already expressed its
    actions as calls — the fenced-envelope recovery's domain, which refused it — and is not a reply
    that merely forgot to call."""
    return any(_fenced_envelope("\n".join(b["lines"])) is not None for b in fenced_file_blocks(content))


def whole_file_write_call(tools, path: str, content: str) -> dict | None:
    """A ``write_file``-family call for THIS request's menu, or None when the menu has no tool that
    takes exactly a path and a text. The tool is the menu's own (a name in
    `toolargs.WHOLE_FILE_WRITES`), and its argument names come from its own schema: required keys
    must be exactly one path alias and one other string property — anything else (a `command`
    discriminator, an `overwrite` flag) is a tool whose call cria would be guessing at."""
    schemas = _menu_schemas(tools)
    for name in WHOLE_FILE_WRITES:
        schema = schemas.get(name)
        if not schema:
            continue
        props = schema.get("properties") or {}
        req = schema.get("required")
        if not isinstance(req, list) or len(req) != 2 or not all(r in props for r in req):
            continue
        path_key = next((k for k in PATH_KEYS if k in req), None)
        text_key = next((k for k in req if k != path_key), None)
        if path_key is None or text_key is None or text_key in PATH_KEYS:
            continue
        if any((props[k] or {}).get("type") != "string" for k in req):
            continue
        if set(props) - set(req):
            continue                                   # optional extras: not a plain path+text write
        return _toolcall(name, {path_key: path, text_key: content})
    return None


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


_WORDS_BETWEEN_CALLS = re.compile(r"<[^>]*>|\|[^|]*\||`{3,}[a-z]*")


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


_PARAM_OPEN = re.compile(r"<parameter=([A-Za-z0-9_.-]+)\s*>")


_PARAM_CLOSE = "</parameter>"


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


_LEAK_MARKERS = ("<tool_call", "<function=", "<|tool_call", "<|channel")  # <|channel: Gemma's thought channel (buffered path strips it; the stream path must hold it back too)


def _toolcall(name: str, args) -> dict:
    arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    return {"id": "call_" + uuid.uuid4().hex[:16], "type": "function", "function": {"name": name, "arguments": arguments}}
