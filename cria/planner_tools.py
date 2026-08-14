"""Read-only tools for the planner's GATHER phase + the repeated-search guard.

Ported from codex-local's ``reasoned_guidance`` + ``local_web_search``. Before it
plans, the planner (a local model) is given a READ-ONLY tool subset so it can LOOK
first — fetch an API's docs, read existing files, inspect the workspace — then emit
a plan grounded in what it found instead of guessing (the stub problem). Read-only
BY CONSTRUCTION: a write/mutate shell command is refused; building is the coder's job.

The repeated-search guard is the "hard nudge": a web_search that essentially repeats
one already made this gather is refused as an **HTTP 400** — the native "bad request,
don't repeat" idiom an HTTP tool speaks — so a small model can't burn the whole gather
re-searching the same terms. Search results don't change turn to turn, so a repeat is
pure wasted inference. When the repeated query names a domain, the refusal steers it to
FETCH the domain directly instead.

Stdlib only: ``urllib`` for web_fetch + Brave search, ``subprocess`` for the read-only
shell.
"""

from __future__ import annotations

import json
import hashlib
import os

from . import dirguard
from . import content_reduce
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import brave, prompts, webfetch
from .searchloop import first_domain_in, normalize_search, searches_match

# The four READ-ONLY tools offered to the planner (inline schemas — local models are lenient). No
# write/patch/exec-mutate tools: planning is not building. The model-facing DESCRIPTIONS live in
# prompts/planner_tool_descs.txt (loaded at import; restart re-tunes); the schemas stay here.
_TD = prompts.load_map("planner_tool_descs")
PLANNER_TOOLS = [
    {"type": "function", "function": {"name": "exec_command", "description": _TD["exec_command"], "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "description": "the command line"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {"name": "read_file", "description": _TD["read_file"], "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": _TD["web_fetch"], "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "web_search", "description": _TD["web_search"], "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

# Match the coder-side cap (webfetch.MAX_BODY_BYTES). This path was left at the old 512 KiB and,
# unlike its sibling, never detected the cut: it read exactly the cap and decoded whatever came back,
# so a spec whose `paths` block sits past 512 KiB arrived as valid-looking front matter with the
# endpoints missing. Worse, the truncated bytes then went through `_record_fetch` → `_structure_of`,
# where broken JSON simply fails to parse, so the durable ledger handed the CODER a 2xx with no
# routes — indistinguishable from "this page isn't a spec".
_FETCH_MAX_BYTES = webfetch.MAX_BODY_BYTES
# Ask Brave for as many results as it will return (its API clamps to 20 in brave.query_url), so a
# planner's gather sees the fuller result set rather than an arbitrary 5. The count is disclosed in
# format_results so the model knows how many landed.
_SEARCH_COUNT = 20
# Above this, a result list goes to the scratchpad instead of the context. Titles+URLs
# still ride inline; it is the snippet bodies that carry the unrelated vocabulary.
_SEARCH_INLINE_CHARS = 1500
# Wall-clock for ONE read-only gather command. Was 20 s, which a recursive grep/find or `git log -p`
# over a real repo exceeds routinely on a contended box — and a timeout with no partial output feeds
# the research floor as "this call taught it nothing", the exact input that makes the planner draft
# from memory.
GATHER_EXEC_TIMEOUT_S = 90


@dataclass(frozen=True)
class ToolResult:
    """One gather tool call: the text the planner sees, and whether the call actually RETURNED
    something to learn from.

    ``learned`` is stated by the code that ran the tool — it knows whether the command printed
    anything, whether the file opened, whether the fetch answered — so the caller never has to
    re-derive it by reading the text. That distinction is load-bearing: measured (run 0727-090143),
    an empty workspace answered `ls -la` and `find` with nothing, the gather counted two calls as
    having researched, and the planner drafted from memory and invented an endpoint the coder then
    built. A refusal, an error, and a command that printed nothing are all calls that taught it
    nothing."""
    text: str
    learned: bool


def _nothing(text: str) -> ToolResult:
    return ToolResult(text, False)


def execute_tool(name: str, args: dict, cwd: str, search_key: str, recent_searches: list, rlog,
                 scratch: str | None = None, facts: dict | None = None) -> ToolResult:
    """Run ONE planner tool call → the text for the gather loop to feed back, plus whether anything
    came back (:class:`ToolResult`). Reads anything; may WRITE only to a scratchpad (``scratch`` or
    /tmp), never the workspace, so the reasoner can persist and process fetched data.
    ``recent_searches`` is the per-gather list of normalized search word-sets the 400 guard uses
    (mutated in place). ``facts`` (mutated in place) collects what each successful fetch PROVED, so
    the gather's findings outlive the gather — see :func:`_record_fetch`."""
    if name in ("exec_command", "shell", "bash", "local_shell"):
        return _exec_command(args, cwd, scratch)
    if name in ("read_file", "cat_file"):
        return _read_file(args, cwd)
    if name == "web_fetch":
        return _web_fetch(args, facts, scratch)
    if name in ("web_search", "local_web_search"):
        return _web_search(args, search_key, recent_searches, facts, scratch)
    return _nothing(prompts.fill(prompts.load_map("planner_steers")["unknown_tool"], tool=name))


# ------------------------------------------------------------------ shell / files

def _exec_command(args: dict, cwd: str, scratch: str | None = None) -> ToolResult:
    cmd = args.get("cmd") or args.get("command") or ""
    if isinstance(cmd, list):
        cmd = " ".join(str(c) for c in cmd)
    cmd = str(cmd).strip()
    if not cmd:
        return _nothing("[no command given]")
    ok, why = is_gather_safe_command(cmd, scratch, workspace=cwd)
    if not ok:
        # An install refusal must NOT carry the write-to-/tmp advice: redirecting a `pip install`
        # into the scratchpad is not a thing, and a refusal that suggests an impossible next move
        # sends the model somewhere worse than the one it was stopped from.
        key = "refused_install" if why == REFUSED_ENV_SETUP else "refused_command"
        return _nothing(prompts.fill(prompts.load_map("planner_steers")[key], cmd=cmd, why=why))
    # cwd stays the WORKSPACE so reads (ls/grep/find the codebase) resolve there; writes are
    # confined to the scratchpad by the gate above. TMPDIR points tempfile-using tools at scratch.
    env = dict(os.environ)
    if scratch:
        env["TMPDIR"] = scratch
    # A workspace that doesn't exist (a fresh build — no repo dir yet) is not a valid cwd, so
    # subprocess can't even launch and EVERY command dies with "failed to launch". Fall back to
    # the scratchpad and tell the planner the workspace is empty — so it plans to CREATE files
    # rather than inspect a repo that isn't there. An UNKNOWN cwd (harness advertised none) falls back
    # the SAME way — NEVER to "." (cria's OWN source tree): a gather ls/grep against cria's repo would
    # feed the planner cria's files as if they were the user's project.
    fresh = not cwd or not os.path.isdir(cwd)
    run_cwd = (scratch or ".") if fresh else cwd
    try:
        # text=False + manual decode: binary stdout under text=True raises UnicodeDecodeError
        # BEFORE any guard runs (a `cat image.png` would crash the gather tool outright).
        out = subprocess.run(["bash", "-lc", cmd], cwd=run_cwd, stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=GATHER_EXEC_TIMEOUT_S, env=env)
        # Full stdout+stderr — the failing assertion / the one grep match the planner needs may be
        # past any fixed clip. The context floor (upstream._prep) bounds the window losslessly-first
        # if this is large; a blind byte-cut here would be a lie the reasoner can't detect.
        raw_out = out.stdout + out.stderr
        printed = raw_out.decode("utf-8", errors="replace").strip()
        if content_reduce.looks_binary(printed):
            printed = content_reduce.binary_note(len(raw_out), content_reduce.binary_kind(raw_out[:16]))
        # A curl/cat through THIS tool bypassed the web_fetch spill and inlined a measured 944,245
        # chars into ONE gather turn — the composed prompt hit ~255K est tokens and the model never
        # answered, twice (run 0729T152706 calls 0005/0006). Oversized exec output takes the same
        # road as an oversized fetch: saved whole to the scratchpad, a pointer + head inlined, and
        # the gather greps the file with the tools it already holds. Spill-impossible (no scratch /
        # write failed) keeps the old inline path — output that reaches the model as nothing at all
        # would be worse than output that costs context.
        if scratch and len(printed) > webfetch.OVERSIZE_CHARS:
            target = os.path.join(scratch, f"exec-{hashlib.sha1(cmd.encode()).hexdigest()[:10]}.txt")
            try:
                os.makedirs(scratch, exist_ok=True)
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write(printed)
                head = printed[:2000]
                printed = prompts.fill(prompts.load_map("planner_steers")["exec_spill"],
                                       chars=f"{len(printed):,}", target=target, head=head)
            except OSError:
                pass
        text = printed or "[no output]"
        if fresh:
            text += "\n" + prompts.fill(prompts.load_map("planner_steers")["fresh_note"], cwd=cwd)
        if "No such file" in text and re.search(r"/tmp/|" + re.escape(scratch or "\0"), cmd):
            text += "\n" + prompts.load_map("planner_steers")["scratch_note"]
        return ToolResult(text, bool(printed))
    except subprocess.TimeoutExpired as e:
        # Keep whatever the command DID print before the clock ran out — a test that printed its
        # failing assertion and then hung, or a build that logged its error before stalling, has already
        # said the useful thing. Returning the bare notice threw that away, contradicting the never-clip
        # rule three lines above. (TimeoutExpired carries bytes or str depending on text=; normalize.)
        def _txt(v):
            if not v:
                return ""
            return v if isinstance(v, str) else v.decode("utf-8", "replace")
        partial = (_txt(e.stdout) + _txt(e.stderr)).strip()
        note = f"[exec timed out after {int(e.timeout)}s]"
        return ToolResult(f"{note}\n{partial}" if partial else note, bool(partial))
    except OSError as e:
        return _nothing(f"[exec failed to launch: {e}]")


def _read_file(args: dict, cwd: str) -> ToolResult:
    path = args.get("path") or args.get("file_path") or ""
    if not path:
        return _nothing("[read_file error: no path]")
    import os
    full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
    try:
        with open(full, "rb") as fh:
            # Full file — the section the planner must modify may be past any fixed clip. The
            # context floor bounds the window losslessly-first if this file is large.
            raw = fh.read()
    except OSError as e:
        return _nothing(f"[read_file error: {e}]")
    body = raw.decode("utf-8", errors="replace")
    if content_reduce.looks_binary(body) or content_reduce.binary_kind(raw[:16]):
        return ToolResult(content_reduce.binary_note(len(raw), content_reduce.binary_kind(raw[:16])), True)
    return ToolResult(body, bool(body.strip()))


# THIS SHELL IS DENY-LISTED, NOT ALLOW-LISTED. An allow-list of ~40 read-only commands used to sit
# here under the words "reject anything else", orphaned by 882bc2c and referenced by nothing since.
# What actually runs is everything below: _CATASTROPHIC, the scratchpad write roots, _MUTATORS,
# _NET_OUT_FLAGS and _ENV_MANAGERS. Two contradictory descriptions of the same guard, eight lines
# apart, with the false one on top — and this is the shell CRIA ITSELF runs, so a maintainer who
# believed the comment would think an unlisted command could not get through. The comment was the
# risk, not the set.
_GIT_READ = {"status", "log", "diff", "show", "ls-files", "branch", "rev-parse", "cat-file",
             "blame", "describe", "remote", "config", "grep"}

# Where the gather MAY write — a scratchpad for processing fetched data. Never the workspace.
_WRITE_ROOTS_BASE = ("/tmp/", "/var/tmp/", "/dev/null", "/dev/stdout", "/dev/stderr")
# Catastrophic ops refused no matter the target — cria runs this shell itself, so its blast
# radius must be bounded (the workspace-wipe lesson: a --yolo model once ran `find . -delete`).
_CATASTROPHIC = re.compile(
    r"(^|[\s|;&(])rm\s+[^|;&]*(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-rf|-fr)\b[^|;&]*\s(/|~|\$HOME|\.)(\s|/|$)"
    r"|(^|[\s|;&(])find\b[^|;&]*\s-delete\b"
    r"|\bmkfs\b|\bdd\b[^|;&]*\bof=/dev/|:\s*\(\s*\)\s*\{|>\s*/dev/(sd|nvme|mapper)|\bshred\b",
    re.I,
)
# The write operators / mutating bases whose TARGETS must land in the scratchpad. A processor
# with no shell write (python3 -c, jq, awk without redirect) is a read as far as the shell sees.
_REDIR_RE = re.compile(r"(?<![0-9<>&])>>?\s*(?!&)([^\s|;&<>]+)")  # `> f` / `>> f`, not `2>&1`
_MUTATORS = {"rm", "rmdir", "mv", "cp", "mkdir", "touch", "dd", "truncate", "install", "ln",
             "chmod", "chown", "shred", "tee", "rsync"}
# curl/wget flags that name an OUTPUT FILE (value is the NEXT token). Bare `-O` (curl) writes the
# remote filename to the cwd = workspace, so it's always a workspace write.
_NET_OUT_FLAGS = {"-o", "--output", "--output-document", "-P", "--directory-prefix"}


# Package / environment managers. These mutate state — site-packages, node_modules, the system, a
# new virtualenv — WITHOUT naming a path argument, so the path-based checks below never see them, and
# `python3 -m venv` hides behind an interpreter. MEASURED (run 0727-125508): the gather ran
# `pip install …` against the user's system python, then `python3 -m venv venv` in the user's
# workspace, burning 3 of its 12 research rounds; the install failed only because the machine is PEP
# 668 externally-managed, and pip's refusal is what taught the model to create the venv.
# Every ecosystem, because the rule is about the CATEGORY, not about Python.
_ENV_MANAGERS = {"pip", "pip3", "pipx", "poetry", "pdm", "uv", "conda", "mamba", "easy_install",
                 "npm", "yarn", "pnpm", "bun",
                 "cargo", "go", "gem", "bundle", "bundler", "composer", "mvn", "gradle", "sbt",
                 "apt", "apt-get", "aptitude", "dnf", "yum", "pacman", "zypper", "apk", "brew",
                 "virtualenv", "pyenv", "rustup", "asdf", "nix-env"}
# Only the MUTATING subcommands: research legitimately runs `pip list`, `npm ls`, `cargo tree`.
_ENV_MUTATE_VERBS = {"install", "uninstall", "add", "remove", "rm", "get", "update", "upgrade",
                     "sync", "init", "new", "require", "download", "build", "publish", "link"}
# Interpreter-hosted forms of the same thing: `python3 -m venv x`, `python -m pip install y`.
_PY_ENV_MODULES = {"venv", "virtualenv", "ensurepip"}


# The refusal reason for an environment mutation, as a CONSTANT: `_exec_command` picks the model
# message by comparing against this exact value, never by pattern-matching the sentence.
REFUSED_ENV_SETUP = "installs packages / builds an environment (planning is research, not setup)"


def _mutates_environment(parts: list[str]) -> bool:
    """Does this command segment install packages or build an environment? Read-only subcommands of
    the same tools are NOT mutations — the gather inspects dependency state all the time."""
    base = parts[0].rsplit("/", 1)[-1]
    if base.startswith("python"):
        if "-m" in parts:
            mod = parts[parts.index("-m") + 1] if parts.index("-m") + 1 < len(parts) else ""
            if mod in _PY_ENV_MODULES:
                return True
            if mod in ("pip", "pip3"):
                parts, base = parts[parts.index("-m") + 1:], "pip"
            else:
                return False
        else:
            return False
    if base not in _ENV_MANAGERS:
        return False
    if base in ("virtualenv", "easy_install"):   # no subcommand — the command IS the mutation
        return True
    # The verb can sit one token deeper when a manager wraps another (`uv pip install httpx`), so
    # look at the first two non-flag tokens rather than only the first. Two is enough for every
    # wrapper form seen, and short enough that a PACKAGE NAME can't be mistaken for the verb.
    words = [p for p in parts[1:] if not p.startswith("-")][:2]
    return any(w in _ENV_MUTATE_VERBS for w in words)


def _net_write_targets(parts: list[str]) -> tuple[list[str], bool]:
    """(output targets, has_bare_curl_O) for a curl/wget segment — only the token AFTER an
    output flag is a target; the URL is not."""
    targets, bare_O = [], False
    for i, p in enumerate(parts):
        if p in _NET_OUT_FLAGS and i + 1 < len(parts):
            targets.append(parts[i + 1])
        elif p == "-O":
            bare_O = True
    return targets, bare_O


def _within(path: str, root: str) -> bool:
    """Is ``path`` inside ``root``? The MECHANISM comes from the one owner; the POLICY below is this
    module's own and deliberately the inverse of everyone else's.

    cria has three places that act in a directory and each had its own containment code. Two were
    answering the same question ("does this leave the workspace") and disagreed on a symlink; that is
    now `dirguard.escapes_workspace`. This one is NOT the same question — the gather may write ONLY
    to a scratchpad and never to the workspace, the opposite of the other two — so the policy stays
    here. What is shared is the primitive, which had no business being written a third time.

    Symlink-resolving, because a write target reached through a link out of the scratchpad is a write
    outside it, and this module runs a real shell."""
    return not dirguard.escapes_workspace(path, root)


def _under_write_roots(target: str, scratch: str | None, workspace: str | None) -> bool:
    """Is a write target inside the allowed scratchpad (scratch dir or /tmp) AND not inside the
    workspace? The workspace exclusion matters because cria's scratch — and a workspace — can
    both live under /tmp; the invariant is 'scratchpad, never the workspace', not 'under /tmp'."""
    t = target.strip().strip('"\'')
    if t in ("/dev/null", "/dev/stdout", "/dev/stderr"):
        return True
    if not os.path.isabs(t):  # relative → resolves in the WORKSPACE cwd → never allowed
        return False
    ap = os.path.normpath(t)
    if workspace and _within(ap, os.path.abspath(workspace)):  # a /tmp workspace is still off-limits
        return False
    roots = list(_WRITE_ROOTS_BASE)
    if scratch:
        roots.append(os.path.normpath(scratch) + "/")
    return any(_within(ap, r) for r in roots)


def is_gather_safe_command(cmd: str, scratch: str | None = None, workspace: str | None = None) -> tuple[bool, str]:
    """The gather may READ anything but WRITE only to the scratchpad (``scratch`` or /tmp), never
    the ``workspace`` — so a small reasoner can persist and process what it fetched without ever
    touching the user's code. Returns ``(ok, reason)``; the reason names the violation for the
    refusal message. Conservative by construction: an unrecognizable mutation is refused (a
    refused command costs a retry; a slipped workspace write corrupts the user's code)."""
    if _CATASTROPHIC.search(cmd):
        return False, "is a destructive operation"
    for target in _REDIR_RE.findall(cmd):  # every redirect target must be in the scratchpad
        if not _under_write_roots(target, scratch, workspace):
            return False, "would write outside the /tmp scratchpad (into the workspace)"
    for seg in re.split(r"[|;&\n]", cmd):
        parts = seg.strip().split()
        if not parts:
            continue
        base = parts[0].rsplit("/", 1)[-1]
        pathargs = [p for p in parts[1:] if not p.startswith("-")]
        if _mutates_environment(parts):
            return False, REFUSED_ENV_SETUP
        if base == "git" and (parts[1:] and parts[1] not in _GIT_READ):
            return False, "mutates the git repository"
        if base == "sed" and "-i" in seg:
            return False, "edits a file in place"
        if base in ("curl", "wget"):
            targets, bare_O = _net_write_targets(parts)
            if bare_O or not all(_under_write_roots(t, scratch, workspace) for t in targets):
                return False, "would download a file outside the /tmp scratchpad"
        elif base in _MUTATORS:
            # every path this mutator touches must be in the scratchpad (dd uses of=… not argv)
            targets = pathargs + [p.split("=", 1)[1] for p in parts if p.startswith("of=")]
            if not targets or not all(_under_write_roots(t, scratch, workspace) for t in targets):
                return False, "would create/modify a file outside the /tmp scratchpad"
    return True, ""


# ------------------------------------------------------------------ web fetch / search

def _web_fetch(args: dict, facts: dict | None = None, scratch: str | None = None) -> ToolResult:
    """Fetch through the SHARED fetcher, reduce MIME-aware, and hand back something that FITS.

    This used to read the socket itself and return the whole decoded body, trusting a comment that
    said "the context floor reduces it if it's large for the window". The floor cannot: truncating
    model-read content is forbidden, so a single tool message larger than the window has no lossless
    reduction left and goes out whole. Measured (run 0727-123534): a 340,951-char page produced
    `msg_before=108954 msg_after=108954` against a 49,152 window, llama.cpp returned 400, and the
    planner spent all three retries on it and produced NO PLAN.

    So a doc bigger than one page takes the coder's route: written IN FULL to the planner's own
    scratchpad — never the workspace — with a pointer and an outline back. Nothing is truncated;
    it moves from the context to a file the gather can grep with the tools it already has."""
    url = str(args.get("url") or "").strip()
    if not url:
        return _nothing("[web_fetch error: no url]")
    try:
        r = webfetch.fetch(url)
    except Exception as e:  # network, TLS, bad scheme — surface the cause, don't crash the gather
        return _nothing(f"[web_fetch error: {e}]")
    reduced, parsed = webfetch.reduce_for_cache(r.body, r.content_type, r.final_url)
    _record_fetch(facts, r.final_url, r.status, reduced, r.content_type)
    note = (f"\n[TRUNCATED at {webfetch.MAX_BODY_BYTES // (1024 * 1024)} MB — this document is "
            f"longer than that and the rest was not read; anything defined past this point "
            f"is missing, so do not read this as the whole document]" if r.truncated else "")
    # The coder is told when a page yielded no endpoints (b862402); the PLANNER — the one still
    # LOOKING for the spec — was not: 0 of 16 planner prompts in run 0727-163703 carried it. Measured
    # across runs 0727-142536/-153326/-163703, the gather fetched a swagger UI SHELL, got a 200 and
    # readable text, and drafted a plan presupposing "the resolve endpoint"; a hardener downstream
    # then turned that phrase into a concrete 404-ing route. Additive (a true sentence, never an
    # action) and self-limiting: only while cria knows NO routes at all — once any spec has been read
    # it goes quiet, because then the planner has something real to plan against.
    note += _no_structure_note(facts)
    if len(reduced) > webfetch.OVERSIZE_CHARS:
        spilled = _spill_to_scratch(r, reduced, parsed, scratch)
        if spilled is not None:
            return ToolResult(spilled + note, True)
    return ToolResult(f"HTTP {r.status} \u00b7 {r.final_url}\n{reduced}{note}", True)


def _search_no_structure_note(facts: dict | None) -> str:
    """The search-result flavor of the no-routes disclosure — same condition, same silence rule as
    :func:`_no_structure_note`, worded for snippets (a search that answered is still not a SOURCE)."""
    if facts is None:
        return ""
    if any((e[1] if len(e) > 1 else "") for e in facts.values()):
        return ""
    return prompts.load_map("planner_steers")["search_no_structure"]


def _no_structure_note(facts: dict | None) -> str:
    """The disclosure to append while NOTHING fetched this session defines a route. Empty once any
    entry carries endpoints — cria says it exactly while it is true and then stops."""
    if facts is None:
        return ""
    if any((e[1] if len(e) > 1 else "") for e in facts.values()):
        return ""
    return prompts.load_map("planner_steers")["fetch_no_structure"]


def _spill_to_scratch(r, reduced: str, parsed, scratch: str | None) -> str | None:
    """Write a too-large doc to the gather's scratchpad and return the pointer message; None if it
    could not be written (then the caller inlines it — a fetch that reached the model as nothing at
    all would be worse than one that costs context)."""
    content = webfetch.spill_content(reduced, parsed, r.content_type)
    try:
        root = scratch or tempfile.mkdtemp(prefix="gather-docs-")
        os.makedirs(root, exist_ok=True)
        target = os.path.join(root, os.path.basename(webfetch._spill_name(r.final_url)))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError:
        return None
    return prompts.fill(prompts.load_map("planner_steers")["fetch_spill"],
                        status=str(r.status), url=r.final_url, chars=f"{len(content):,}",
                        target=target, outline=webfetch.spill_outline(parsed, target))


def _record_fetch(facts: dict | None, url: str, status, body: str, content_type) -> None:
    """Keep what this fetch really PROVED, as ``url -> (status, routes, fields)``.

    The gather's findings used to die with the gather: the planner's transcript is thrown away once
    the plan is drafted, so a spec it had genuinely READ never reached the coder. Measured (run
    0726-221401): at gather call 4 the planner held the real spec — `/handles/{handle}` AND
    `/holders/{address}`, the exact two endpoints that task needs — the plan it then wrote named
    neither, and the coder, never shown them, invented `/handle/{handle}` and 404'd. cria had the
    ground truth in hand and dropped it on the floor.

    Same ``(status, routes, fields)`` tuple the coder-side durable ledger uses, so these merge
    straight into it. Routes/fields are SHAPE-detected by the shared extractors — empty for a doc
    that isn't spec-shaped, so nothing is invented for an ordinary page. Only a 2xx is recorded: a
    fetch that failed proved nothing (a 404 restated as a fact is how a hallucinated endpoint became
    'ground truth' once already)."""
    if facts is None or not str(status).startswith("2"):
        return
    parsed = webfetch._structure_of(body, content_type, url)
    routes = webfetch._endpoint_routes(parsed) if parsed is not None else []
    fields = webfetch._endpoint_response_fields(parsed) if parsed is not None else []
    # ONE shape per LINE — the same separator the coder-side producer uses. Both fill this field and
    # both merge into one ⟦ctx:facts⟧ anchor, and the reader's contract is line-based (`_shape_block`:
    # "entry lines are the ones carrying →"). Joined with "; " instead, five endpoint shapes reached
    # the coder as 1,534 unbroken characters under a heading telling it to use these EXACT names.
    facts[url] = (f"HTTP {status}", ", ".join(routes), "\n".join(fields))


def _web_search(args: dict, search_key: str, recent: list, facts: dict | None = None,
                scratch: str | None = None) -> ToolResult:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return _nothing("[web_search error: no query]")
    blocked = gate_search(recent, query)  # the 400 hard-nudge on a repeat
    if blocked is not None:
        return _nothing(blocked)          # a refusal of a repeat returns no NEW information
    if not (search_key or "").strip():
        return _nothing(prompts.load_map("planner_steers")["no_search_key"])
    try:
        # The no-routes disclosure rides SEARCH results too (run 0728-m11): a gather whose ONLY tool
        # was web_search never saw the note — it was attached to fetch results alone — so the planner
        # drafted a concrete invented route from snippets and the coder built a 404. Snippets are
        # pointers, not the source (the same sentence the coder-side doctrine already carries); the
        # note stays exactly while cria knows no routes and goes quiet the moment any spec is read.
        note = _search_no_structure_note(facts)
        body = format_results(query, brave_search(search_key, query, _SEARCH_COUNT))
        # SPILL, exactly as the fetch sibling does. Twenty results of titles+snippets is thousands of
        # characters of OTHER people's words, and a search is speculative by nature — the model asked
        # "what is out there", not "give me this document". Measured on run 20260801T225200: one
        # web_search for "README.md generation guide install run script tests" put 9,269 characters
        # into the planner's context — npm packages, Reddit threads, jest configs, valkey test docs —
        # none of it about the task. It then survived into the compaction note and was still there,
        # verbatim, at call 0004. The list stays reachable in full on disk; what rides in the context
        # is the pointer plus the titles.
        spilled = _spill_search(query, body, scratch)
        return ToolResult((spilled if spilled is not None else body) + note, True)
    except Exception as e:
        return _nothing(f"[web_search error: {e}]")


def _spill_search(query: str, body: str, scratch: str | None) -> str | None:
    """Save a search result list to the scratchpad and return the pointer + the titles, or None when
    it is small enough to inline. Same contract as :func:`_spill_to_scratch` for fetches."""
    if scratch is None or len(body) <= _SEARCH_INLINE_CHARS:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60] or "search"
    target = os.path.join(scratch, f"search-{slug}.txt")
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        return None
    titles = "\n".join(ln for ln in body.splitlines()
                       if ln[:2].strip().rstrip(".").isdigit() or ln.startswith("Search results for:"))
    return prompts.fill(prompts.load_map("planner_steers")["search_spill"],
                        query=query, chars=f"{len(body):,}", target=target, titles=titles)


def brave_search(api_key: str, query: str, count: int = _SEARCH_COUNT) -> list[dict]:
    """One Brave Search GET. Returns a list of {title,url,description}. Endpoint/encoding/headers
    come from the shared `brave` module so the writeproxy's shell web_search can't diverge."""
    req = urllib.request.Request(brave.query_url(query, count), headers=brave.headers(api_key))
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    results = ((data.get("web") or {}).get("results")) or []
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "description": x.get("description", "")}
            for x in results]


def format_results(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results for query: {query}"
    # Disclose the count so the model knows how many results landed (Brave caps a request at 20).
    out = f"Search results for: {query} ({len(results)} results)\n"
    for i, r in enumerate(results, 1):
        out += f"\n{i}. {r['title']}\n   {r['url']}\n   {(r['description'] or '').strip()}\n"
    return out


# ------------------------------------------------------------------ repeated-search 400 guard

def gate_search(recent: list, query: str) -> str | None:
    """Decide whether this search runs or is refused as a repeat of one already made
    this gather. ``recent`` is a list of normalized word-sets (mutated in place). Returns
    ``None`` to proceed (and records the query), or the HTTP-400 refusal text to block."""
    words = normalize_search(query)
    if not words:
        return None
    if any(searches_match(words, prev) for prev in recent):
        domain = first_domain_in(query)
        steer = (f"\nThis query names a domain — stop searching ABOUT it and FETCH it directly: "
                 f"web_fetch https://{domain} , then parse the response for what you need."
                 if domain else "")
        return (f'HTTP 400 Bad Request · web_search "{query}"\n'
                f"You've searched this before. Make a major change to your search, or try something else.{steer}")
    recent.append(words)
    if len(recent) > 64:  # bound memory on a pathologically search-heavy gather
        del recent[0:len(recent) - 64]
    return None


# normalize_search / searches_match / first_domain_in now live in cria/searchloop.py (imported
# above) — shared by this planner guard, the live webfetch.gate_search, and loop.py's fingerprinting.
