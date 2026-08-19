"""What reading has actually been done — the FACTS, gathered from cria's own fetch ledger.

WHY THIS EXISTS. Two fabliq runs of the same task, same code, same model, failed from opposite
sides of the same hole:

  * PLANNER-ON (run 1785804243). The plan's step 1 was "Research the Ada Handles API documentation
    by fetching the GitHub repo root directory". That fetch is denied, so the step could never be
    satisfied, and the step critic correctly refused it forever: 114 of 195 calls went to step 1 and
    the run never reached step 2.
  * PLANNER-OFF (run 1785805694). No plan step said "research", so nothing did. **Zero web_fetch
    calls in 237.** The coder wrote a resolver, unit tests, a live test and a README against
    `api.handle.me/v1/handle/` with fields `address`/`holder`/`totalHandles` — an API it invented
    whole. It scored 1/4 and the ceiling was structural: the resolver cannot resolve.

THE ANSWER TO THE SECOND ONE IS NOT A STEP. It is `prompts/coder_system.txt` — "RESEARCH &
INVESTIGATE FIRST: if the task depends on an external thing, READ its real source/docs before
writing code against it" — which predates the step this module used to author by eighteen days,
costs no model call, and reaches every run. The authored step, the reasoner call that wrote it, and
the periodic check that cleared it were removed on 2026-08-19; across 174 captured authorings, 102
said some version of "read the files already in the workspace" and the run was already doing that.
The reasoning is in `docs/audits/base-vs-cria-footgun-patterns.md`.

WHAT REMAINS is the deterministic half, and it is the half that was always trustworthy: cria records
every fetch that came back and what was parsed out of it (``loop._extract_fetches`` → url → status,
routes, response shapes), and this module turns that into a list of sources actually read, with what
each one defined. Judges and steers are given those facts; none of them is asked to take a claim
about reading on trust (#8: deterministic code gathers the facts, the reasoner judges them).
"""
from __future__ import annotations

import re

from . import denial, jsontext, prompts
from .jsontext import extract_json_object, strip_think




def sources_read(ledger: dict, messages: list | None = None) -> list[tuple[str, str, str]]:
    """Everything really READ this session — the web documents that defined something, AND the files
    on disk that were opened and came back with content.

    RESEARCH IS NOT ONLY WEB. The first version of this module counted web fetches alone, which made
    the whole check inert for every other kind of reading a task can require: files already in the
    workspace, a library's own source, a schema on disk, a data set, a tool's `--help`. For those the
    ledger is empty, so the verdict was permanently NOT_DONE — the check could never clear the step it
    exists to clear, which is the trap it was built to remove, one class over.

    The rule is the same for both kinds and it is what keeps this honest: a source counts only when
    the read RETURNED SOMETHING. For a web document that means 2xx with routes or response fields
    actually parsed out of it — a page that answered and defined nothing is not research (run
    1785804243's ledger was five HTTP 200s reading "no endpoint definitions were found in it"). For a
    file it means the read produced content cria did not refuse and that was not empty. An attempted
    read is not a read."""
    out = list(grounded_sources(ledger))
    for path, size in files_read(messages or []):
        out.append((path, "", f"{size} chars read from disk"))
    return out


def files_read(messages: list) -> list[tuple[str, int]]:
    """``(path, chars)`` for each distinct file this session actually read, largest read per path.

    Reads the CALL for the path and its paired RESULT for the content, because only the pair carries
    both. A refusal (cria's own denial marker) is not a read, and neither is an empty result: both are
    the shapes that made a coder believe it had seen a file it had not."""
    calls: dict[str, str] = {}
    got: dict[str, int] = {}
    written = _paths_written(messages or [])
    for m in messages or []:
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            if str(fn.get("name", "")) not in _READ_TOOLS:
                continue
            args = fn.get("arguments")
            try:
                d = jsontext.loads(args) if isinstance(args, str) else (args or {})
            except (ValueError, TypeError, AttributeError):
                d = {}
            path = d.get("path") or d.get("file") or d.get("filename")
            if isinstance(path, str) and path.strip() and tc.get("id"):
                calls[tc["id"]] = path.strip()
        if m.get("role") == "tool" and m.get("tool_call_id") in calls:
            body = m.get("content")
            if isinstance(body, list):
                body = "".join(str(p.get("text", "")) for p in body if isinstance(p, dict))
            body = body if isinstance(body, str) else ""
            if body.strip() and not denial.is_denied(body):
                path = calls[m["tool_call_id"]]
                # READING BACK YOUR OWN WRITING IS NOT RESEARCH. A file the coder created earlier in
                # this same session teaches it nothing it did not already know, and counting it let
                # the research step close on the coder's own output.
                #
                # Measured, nemotron-elastic/rust 0033: the block headed "WHAT HAS REALLY BEEN READ
                # THIS SESSION" listed `tests/test_nested_lookup.rs`, written by the coder four calls
                # earlier, and the judge closed the documentation step with "So we have DONE." No
                # page defining the toml crate API was read at any point in the run.
                #
                # A file that existed BEFORE the session — a seed, a schema, a data set — is
                # untouched: that is real reading, and the whole reason this ledger covers files at
                # all rather than fetches alone.
                if path not in written:
                    got[path] = max(got.get(path, 0), len(body))
    return sorted(got.items())


def _paths_written(messages: list) -> set:
    """Every path this session WROTE, so a read of one can be told from a read of the world."""
    out = set()
    for m in messages or []:
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            if str(fn.get("name", "")) not in _WRITE_TOOLS:
                continue
            try:
                d = jsontext.loads(fn.get("arguments")) if isinstance(fn.get("arguments"), str) \
                    else (fn.get("arguments") or {})
            except (ValueError, TypeError, AttributeError):
                d = {}
            path = (d or {}).get("path") or (d or {}).get("file") or (d or {}).get("filename")
            if isinstance(path, str) and path.strip():
                out.add(path.strip())
    return out


# The write-shaped tools, by the same rule as _READ_TOOLS below: named tools only, never a shell
# command line, because a wrong attribution here would silently delete a real read from the ledger.
_WRITE_TOOLS = ("write_file", "edit_file", "create_file", "apply_patch")


# The read-shaped tools by name. Shell reads (`cat`, `grep`) are deliberately NOT here: cria lowers
# its own file tools THROUGH shell, so a shell result cannot be attributed to a path without parsing
# the command line, and a wrong attribution would report a file as read that never was. Under-count,
# and say so, rather than guess (#5b).
_READ_TOOLS = ("read_file", "view_file", "open_file", "cat_file")


def fetch_succeeded(status) -> bool:
    """Did this ledger entry actually return something?

    ONE OWNER for the question, because the status has TWO spellings and reading only one of them
    silently disabled a whole guard. A ledger built from the live window carries the RENDERED
    ``"HTTP 200"``; a session's durable ledger can carry the bare int ``200``. `grounded_sources`
    tested ``startswith("2")``, which matches the bare int and NEVER matches ``"HTTP 200"`` — so
    every window-derived entry was invisible and the research exit answered NOT_DONE on a ledger
    full of parsed routes. Journal, every firing today: ``loop.research_check … sources=0``, while
    the same prompt carried ``api.handle.me/openapi.json → HTTP 200`` with ``resolved_addresses{ada}``
    parsed out of it. Scan for the code instead of matching a prefix; loop._fetch_succeeded delegates
    here so the two cannot drift apart again."""
    m = re.search(r"\d{3}", str(status if status is not None else ""))
    return bool(m) and 200 <= int(m.group(0)) < 300






def grounded_sources(ledger: dict) -> list[tuple[str, str, str]]:
    """``(url, routes, shapes)`` for the fetches that came back 2xx AND defined something.

    A page that answered but yielded no routes and no response fields is NOT a source here. That
    distinction is the whole point: in run 1785804243 the ledger was injected into all 115 coder
    prompts and every line of it read "this page answered, but no endpoint definitions were found in
    it". Five HTTP 200s and nothing read. Counting those as research done would report the coder
    having successfully loaded a home page as reading having happened."""
    out = []
    for url, entry in (ledger or {}).items():
        status, routes, shapes = (tuple(entry) + ("", "", ""))[:3]
        if fetch_succeeded(status) and (str(routes).strip() or str(shapes).strip()):
            out.append((url, str(routes), str(shapes)))
    return out


def _sources_block(sources: list[tuple[str, str, str]]) -> str:
    lines = []
    for url, routes, shapes in sources:
        lines.append(f"- {url}")
        if routes.strip():
            lines.append(f"    routes it defines: {routes.strip()}")
        if shapes.strip():
            lines.append(f"    response fields it defines: {shapes.strip()}")
    return "\n".join(lines)






