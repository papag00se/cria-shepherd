"""The reasoned planner — decompose a task into a `Plan`.

On a fresh coding task the reasoner GATHERS before it plans: it is given a READ-ONLY
tool subset (inspect the workspace, read files, fetch docs, search the web) and runs a
bounded loop — call a tool, see the result, call more — until it stops calling tools and
emits a plan GROUNDED in what it found rather than guesses. The tool round-trips are fed
back as PROTOCOL (a structured assistant `tool_calls` turn + `role:tool` results), never
flattened into prose — small models parrot prose back as their "plan". cria owns no
workspace files; the read-only tools only LOOK. Cached per task (one gather-and-plan pass
per user task; phase 6 reuses it by the same key).
"""

from __future__ import annotations

import os
import json
import re
import shutil
import tempfile
import threading
import urllib.parse
from dataclasses import replace
from datetime import datetime, timezone

from . import groundtruth, massage, planner_tools, prompts, urlgrounding
from .classify import JUDGE_MAX_TOKENS, _task_key, latest_user_text
from . import jsontext
from .jsontext import extract_json_object, loads as jsontext_loads, strip_think
from .plan import Plan, PlanItem

_CWD_RE = re.compile(r"<cwd>\s*(.*?)\s*</cwd>", re.S)

# Why generation stopped, attached to the message _reason returns. NEVER sent to the model —
# the gather loop builds its own wire dicts. See _gather_and_plan.
FINISH_KEY = "_cria_finish_reason"
# When the gather runs to the round cap without the model submitting, offer submit_plan as its
# ONLY tool and read the call — retried in place a couple of times if it calls something else.
# (No "you've gathered enough, stop investigating" prose — that message was useless and jarring;
# the tool constraint is the whole instruction.)
_MAX_FINAL_RETRIES = 3
# Output budget for ONE targeted judge question. Matches the shared `summarize` primitive: a reasoning
# model spends this budget THINKING before it writes a word, so a small cap does not buy a short answer
# — it buys NO answer. At 2000 the noise judge reasoned its way to the right verdict and was cut off
# mid-sentence with finish_reason=length and zero content, and the plan it should have corrected was
# accepted whole.
ASK_MAX_TOKENS = JUDGE_MAX_TOKENS
# How many times ONE draft may be handed back for a fresh problem. Two, so a plan challenged for an
# invented route can still be challenged for missing every deliverable — and no more, so this can
# never ping-pong: _MAX_FINAL_RETRIES bounds the drafting attempts, and a drafter that insists on its
# plan gets it.
MAX_PLAN_HANDBACKS = 2
# The plan-submission tool. gemma-fable is hardwired to emit tool CALLS, so instead of asking for
# plain text (which it answers with a hallucinated `call:CreateNewProject{…}`), hand it ONE tool
# that IS the plan and read the steps from the call.
_SUBMIT_PLAN_TOOL = {"type": "function", "function": {
    "name": "submit_plan",
    "description": prompts.load_map("planner_tool_descs")["submit_plan"],
    "parameters": {"type": "object", "properties": {
        "steps": {"type": "array", "items": {"type": "string"}, "description": "the ordered steps"}},
        "required": ["steps"]}}}


def _candidate_step_lists(args) -> list[list]:
    """Every list a ``submit_plan`` payload offers as its steps, best first.

    `json.loads` keeps the LAST value when a key repeats, and a small model repeats keys. Measured
    (run 0727-121457) it emitted `{"steps":[<five real steps>],"steps":[1,2,3,4,5]}` — so the real
    plan was discarded before any caller saw it and the ordinals became the plan, handing the coder
    steps literally named "1", "2", "3". Collect ALL values for the key and let the caller take the
    first that survives cleaning, so a junk duplicate can shadow nothing."""
    if isinstance(args, dict):
        v = args.get("steps")
        return [v] if isinstance(v, list) else []
    if not isinstance(args, str):
        return []
    try:
        obj = jsontext_loads(args)          # THE model-JSON parser: repeated keys resolve first-non-empty
    except (json.JSONDecodeError, ValueError):
        return []
    v = obj.get("steps") if isinstance(obj, dict) else None
    return [v] if isinstance(v, list) else []


def _steps_from_submit(msg: dict) -> list[str] | None:
    """Read the plan steps from a ``submit_plan`` tool call (native or recovered from the dialect).
    None if the model called something else or gave no steps."""
    for tc in msg.get("tool_calls") or []:
        if ((tc.get("function") or {}).get("name")) != "submit_plan":
            continue
        args = (tc.get("function") or {}).get("arguments")
        for steps in _candidate_step_lists(args):
            out = [c for s in steps if (c := _clean_step(s))]  # a step that ran into the dialect is trimmed
            if out:
                return out
    return None

# The planner prompt lives in cria/prompts/plan.txt (edit it there). It asks for a
# numbered LIST, not JSON: small local models emit a clean list far more reliably than
# strict JSON — demanding JSON makes some (e.g. Gemma) emit a bespoke tool call instead.
#
# No step cap: EVERY emitted step is a PlanItem the loop executes. A prior 12-step slice
# silently dropped the tail of a longer decomposition (steps 13+), so the loop ran a plan
# that structurally omitted work and could declare done with work missing. The reasoner's
# max_tokens already bounds how long a plan it can emit; the context floor bounds the window.

# A numbered ("1." / "1)") vs a bulleted ("-" / "*" / "•") list line → its text. Kept separate: when a
# plan is numbered, indented `-` sub-bullets are DETAILS of a step (e.g. "7. Add a README containing:"
# then "   - install …" / "   - run the CLI …"), NOT steps — flattening them exploded a 7-step plan
# into 11 and ground the loop through phantom "steps". Prefer numbered; fall back to bullets only when
# there are no numbers (a model that emits a pure bullet-list plan).
_NUM_LINE = re.compile(r"^\s*\d+[.)]\s+(.+\S)")
_BULLET_LINE = re.compile(r"^\s*[-*•]\s+(.+\S)")
# A LETTERED sub-item ("a. Accepts a handle", "b) Sends a GET request") — a step's detail even when the
# model didn't indent it. Single letter only, so a sentence starting "I. " or a word is never matched.
_SUB_ITEM = re.compile(r"^[a-z][.)]\s+\S", re.I)

# A leaked dialect marker (gemma-fable / harmony): a step is ONE action, so anything from the
# first marker on is the model failing to stop after the plan (a thought channel, another tool
# call) — observed live bleeding into a submit_plan step, dirtying the whole plan mirror.
# The ``(?:_start|_end)?`` covers the LFM2-family native pair ``<|tool_call_start|>`` / ``<|tool_call_end|>``
# (retired fleet family, kept as cheap dialect coverage) — without it the plain regex matched
# gemma/qwen/hermes but missed that family's own tokens, so its debris survived into a step
# (writeproxy._TC_DEBRIS already lists the full set; keep them in sync).
_DIALECT_MARKER = re.compile(
    r"<[|/]+(?:tool_call|channel|message|tool_response|think)(?:_start|_end)?[|/]*>"  # delimiter BEFORE the name
    r"|<(?:tool_call|channel|message|tool_response|think)(?:_start|_end)?[|/]+>"       # …or AFTER it
    r"|<\|\"\|>")
# NOTE the [|/]+ requirement: a real leaked control token ALWAYS carries a pipe/slash delimiter
# (<|tool_call|>, <tool_call|>). Matching a BARE <message>/<channel>/<think> also cut a legitimate plan
# step that merely NAMES that XML/HTML tag ("Handle the <message> element" → "Handle the"). Every
# writeproxy._TC_DEBRIS fixture still matches (all carry a delimiter); a sync test guards the pair.


# What the step IS, before how it is carried out. A model that wraps steps in objects usually
# supplies both — `{"outcome": "Read the API documentation", "description": "read_file(path=…)"}` —
# and the mechanism is the worse half: MEASURED (run 0727-135408) the living-plan rescue returned
# exactly that shape, `outcome` was not on this list, cria took `description`, and the noise judge
# then correctly dropped all five steps for "codifying a bare command". The rescue is one-shot, so
# that cost the stuck step its last resort.
_STEP_INTENT_KEYS = ("step", "text", "outcome", "goal", "title", "task", "name", "objective", "action")
# `command`/`cmd`/`shell` sit at the BOTTOM: a command is definitionally HOW, never WHAT, so it must
# lose to any sibling text. Observed (run 0727-143340) as `{"command": "…pytest…", "justification":
# "Run unit tests to verify script functionality"}` — with neither key listed, the model's own field
# order handed cria the shell line, which is the very thing b3d4731 fixed.
_STEP_DETAIL_KEYS = ("description", "detail", "details", "content", "summary", "justification",
                     "purpose", "rationale", "command", "cmd", "shell")
_STEP_TEXT_KEYS = _STEP_INTENT_KEYS + _STEP_DETAIL_KEYS


def _clean_step(text) -> str:
    """Trim a plan step to its action: cut at the first leaked dialect marker, strip a leading
    ordinal (``1.`` / ``2)`` — JSON-array items often embed their own number), and drop the JSON /
    array junk (``',]}`` etc.) that bleeds in when the model runs past the plan. Accepts a str OR a
    dict item — a model that wraps each array element in an object (``{"step": "…"}``) instead of a
    bare string; the field is extracted first, so the step text is never the dict repr ``{'step': …}``."""
    if isinstance(text, dict):
        # A STEP IS A PHRASE. `action` is ambiguous — sometimes the step ("Research the API"),
        # sometimes a tool name — and measured (run 0727-151934) it held "write_file" beside a
        # `description` carrying the real step, so the rescue's step became a bare token the noise
        # judge then dropped. A candidate with no whitespace is a LABEL, not something a coder can
        # carry out; it loses to any sibling that reads like one. Shape, not keywords.
        candidates = [v for k in _STEP_TEXT_KEYS
                      if isinstance(v := text.get(k), str) and v.strip()]
        for v in candidates:
            if len(v.split()) > 1:
                return _clean_step(v)
        if candidates:      # every candidate is a bare token — return it rather than drop the step
            return _clean_step(candidates[0])
        # No key anyone listed. The model still said something — take the FIRST non-empty string in
        # its OWN field order, which is where it put what it considers primary. Better than dropping
        # a whole step because nobody predicted its key name.
        for v in text.values():
            if isinstance(v, str) and v.strip():
                return _clean_step(v)
        return ""
    # A STEP IS TEXT A MODEL WROTE. Anything else in a JSON array — ``null``, a number, a bool, a
    # nested list — is not a step, and ``str()`` on it AUTHORS one out of a Python repr: measured,
    # ``json_steps('[null, null]')`` returned ``['None', 'None']``, and in the living re-derivation
    # that list REPLACES the plan (#5b — cria may not put words in the model's mouth; #2 — the
    # dangerous intervention is the one that replaces a correct prior). Pre-existing and newly
    # reachable now that a bare top-level array is read. Dropped here, and a non-empty list that
    # drops to nothing is refused as unreadable by the callers rather than read as "nothing remains".
    if not isinstance(text, str):
        return ""
    s = text
    m = _DIALECT_MARKER.search(s)
    if m:
        s = s[:m.start()]
    s = re.sub(r"^\s*\d+[.)]\s*", "", s)  # leading "1. " / "2) " embedded in a JSON list item
    # ...and a step that NAMES ITS OWN NUMBER ("**Step 1: Resolve a handle…**"). cria's framing adds
    # its own — "Do ONLY this step (2 of 6)" — and the two collide in front of the coder:
    #
    #   Completed so far:
    #   1. Step 1: Resolve a handle to its Cardano address.
    #   Do ONLY this step (2 of 6), then stop: GET /holders/{address}…
    #
    # Measured on ada-handles_mellum2_codex_pon_1785625253 turn 0023, in the coder's own words:
    # "This is ambiguous… The 'Do ONLY this step (2 of 6)' is likely a copy-paste error in the
    # prompt… Given the ambiguity, I should… ask for clarification." It spent the turn adjudicating
    # cria's numbering instead of doing the step. A step is a PHRASE; its position is cria's to
    # state, and stating it twice with different numbers is worse than not stating it at all.
    # `**` may sit before the word, after the number, or both: "**Step 1:**", "**Step 1:", "Step 1:".
    # A SEPARATOR IS REQUIRED — "Step 1:" / "Step 1." / "Step 1)" / "**Step 1:**". Making it optional
    # also ate "Step 1 of the plan…", which is the step's real content.
    s = re.sub(r"^\s*\**\s*step\s+\d+\s*(?:[:.\)-]\s*\**|\**\s*[:.\)-])\s*", "", s, flags=re.I)
    # Stripping a leading "**" orphans its partner at the end; a dangling "**" is noise the coder
    # reads as part of the instruction.
    if s.rstrip().endswith("**") and "**" not in s.rstrip()[:-2]:
        s = s.rstrip()[:-2].rstrip()
    s = _strip_trailing_junk(s).strip()
    # A bare ordinal is not a step. Stripping the leading "1." off the string "1." leaves nothing, and
    # an integer element stringifies to "1" — neither is an action the coder can carry out. Measured:
    # a duplicate-key plan handed the coder steps literally named "1", "2", "3".
    return "" if re.fullmatch(r"[\d.)\s-]*", s) else s


_CLOSERS = {"}": "{", "]": "["}


def _strip_trailing_junk(s: str) -> str:
    """Drop the JSON/array junk that bleeds in when a model runs past the plan (``step",]}``) — but
    never a bracket the STEP ITSELF opened. A blanket ``[\\s'\"\\],}]+$`` strip ate the brace off a
    step ending in a path template, so ``GET /handles/{handle}`` reached the coder as
    ``GET /handles/{handle`` — and the coder follows the plan verbatim, so it builds that URL wrong.
    A closer is junk only when it is UNBALANCED; a matched one is part of the step's own text.

    The same rule governs QUOTES, which this used to strip unconditionally one line below the
    sentence describing the balance rule. Measured (run 0727-135951): the live-test step
    ``Run live tests to resolve handles like 'goose' and 'papagoose'`` reached the plan as
    ``…and 'papagoose`` — cria ate the closing quote off the two handle names the task is ABOUT.
    A quote is junk only when it has NO PARTNER — a lone trailing `'` really is envelope debris (a
    model that quotes array elements Python-style), but a matched pair belongs to the step. Known
    limit: prose that mixes an apostrophe with a quoted word (`the API's 'goose'`) counts odd and
    loses the closer. That shape has not been observed; the two that have are covered by parity."""
    while s:
        c = s[-1]
        if c in " \t\r\n,":
            s = s[:-1]
        elif c in "'\"" and s.count(c) % 2:
            s = s[:-1]
        elif c in _CLOSERS and s.count(_CLOSERS[c]) < s.count(c):
            s = s[:-1]
        else:
            break
    return s


# Keys a model may wrap its step array under. `steps` is the prompt's ask; `plan` is what Fabliq
# emits about as often — accepting only `steps` dropped a valid {"plan":[…]} to plan.unparsed, which
# silently fell back to the plan-OFF path (no step-gating → the coder coded freely and hallucinated).
_STEP_KEYS = ("steps", "plan", "items")

# Re-draft an EMPTY/unparseable plan this many times before giving up (a weak model is non-deterministic,
# so a re-draft usually lands; the drive's synthetic-plan fallback catches the case where it never does).
PLAN_RETRIES = 2

# A ``"steps"|"plan"|"items": [`` array opener, and a single JSON string element on its own line. The
# item pattern is GREEDY to the last quote so an element with UNESCAPED inner quotes — ``like `"goose"```
# — is still captured whole; that malformed inner quote is exactly what makes ``json.loads`` reject the
# whole object, dropping an otherwise-good plan to plan.unparsed → the UNGUARDED proxy path (runH: a
# clean 6-step plan lost to one `"goose"`, then 60 freewheeling turns with no guard/gate/steer).
_ARR_KEY = re.compile(r'"(?:steps|plan|items)"\s*:\s*\[', re.I)
_ARR_ITEM = re.compile(r'^\s*"(.*)"\s*,?\s*$')


# Inline ordinal boundary — "1. ", "2) " — used to split a numbered plan packed into ONE string
# value (``{"plan": "1. Search… 2. Fetch… 6. README…"}``, runI): the JSON parses, but ``plan`` is a
# str not a list, and every step sits on one line so the line-based fallback can't see them either.
_INLINE_NUM = re.compile(r"(?:^|\s)\d{1,3}[.)]\s+")


def _split_inline_numbered(s: str) -> list[str] | None:
    """Split a single string of numbered steps ("1. a 2. b 3. c") into its items. Requires ≥2 ordinals
    so a lone "1." sentence isn't mistaken for a plan; returns None otherwise."""
    if len(_INLINE_NUM.findall(s)) < 2:
        return None
    parts = [p for chunk in _INLINE_NUM.split(s) if (p := _clean_step(chunk))]
    return parts or None


def _salvage_array_steps(body: str) -> list[str] | None:
    """Recover the step strings from a step-array whose JSON won't parse (a local model's unescaped
    inner quotes). Only engages when a ``steps``/``plan``/``items`` array opener is present, and reads
    the quoted line-items up to the closing ``]`` — so it can't fire on arbitrary quoted prose."""
    m = _ARR_KEY.search(body)
    if not m:
        return None
    steps, seen = [], 0
    for line in body[m.end():].splitlines():
        if line.lstrip().startswith("]"):
            break
        if not line.strip():
            continue
        seen += 1
        im = _ARR_ITEM.match(line)
        if im and (c := _clean_step(im.group(1))):
            steps.append(c)
    # A salvage that keeps only SOME of the items is not a salvage — it is a silently shortened plan.
    # This path exists for JSON that json.loads rejected (an unescaped inner quote), and a line that
    # doesn't match the item shape may well be a real step this regex can't read. Handing back a
    # valid-LOOKING 3-step plan for a 7-step draft loses work with nothing to detect it; bail instead
    # and let the caller re-draft (PLAN_RETRIES) or fall through to the other parsers.
    if not steps or len(steps) != seen:
        return None
    return steps


def json_steps(text: str) -> list[str] | None:
    """The step list a model wrote AS JSON, or ``None`` when the reply holds no JSON step list.

    The ONE owner of "read a step list out of JSON". :func:`parse_steps` is this plus the prose
    fallbacks (numbered/bulleted lines); :func:`cria.loop.reassess_remaining` is this and NOTHING
    else, deliberately — see the direction note there.

    An EMPTY list is a real answer, not a miss: ``[]`` is what cria's own ``replan.txt`` tells the
    reasoner to return when every remaining deliverable is already done, and it is distinguishable
    from ``None`` at every caller.

    Three shapes — each one a shape the model chose, none of them guessed at:

    1. the reply IS a top-level array (of strings, or of ``{"step": …}`` objects);
    2. a ``steps``/``plan``/``items`` list (or a numbered plan packed into one string value);
    3. one — and only one — OTHER key holding a usable list, which is a model answering a synonym
       of the ask (``remaining_steps``).

    Shape 1 is what this function was added for, and its guard is the whole of it: the array must be
    what the reply IS, after fences and ``<think>`` come off — never an array found somewhere INSIDE
    it. Measured 2026-08-02 over 232 captured re-derivation calls: 13 answered with a bare array (7
    with steps, 6 with ``[]``) and every one of them opens with ``[``. The reply that proves the
    guard is needed is run 20260801T232511 call 0067, which answered with a pytest FILE — and whose
    first bracket is ``result["resolved_ada_address"]``, an array of one string that a scan for the
    first ``[`` would have handed back as the plan.

    IT IS TRIED FIRST, and the ORDER is load-bearing (fixed 2026-08-03). Shape 1 used to run last,
    after ``extract_json_object`` — which, on a top-level array of OBJECTS, returns the first
    ELEMENT. ``[{"step": "Write resolve.py"}, {"step": "Write the README"}]`` therefore entered the
    object reader as ``{"step": "Write resolve.py"}``, matched no step key, offered no list to the
    synonym scan, and came back ``None`` — while shape 1 alone reads it perfectly. Only arrays of
    bare STRINGS worked, and the docstring that claimed "same items, same cleaning" for shape 1 was
    describing code that never ran for the dict form (#5b: cria may not state a false fact, and a
    docstring is a fact about the code). The per-object step wrapper is a shape these models really
    emit — ``remaining_steps: [{"step": …, "status": …}]`` is in the corpus — it simply arrived
    wrapped in an object, where the synonym scan caught it. Trying the array first costs nothing:
    it fires only when the whole denoised reply parses as a JSON array, which is a strictly narrower
    test than "contains an object somewhere".
    """
    body = strip_think(text)
    arr = _top_level_array_steps(body)
    if arr is not None:
        return arr
    obj = extract_json_object(body)
    if obj:
        # An explicitly EMPTY primary list is an answer ("nothing remains") — but it is the answer of
        # LAST resort, taken only after the synonym scan has come up empty too. Returning it here
        # short-circuited a reply that carried BOTH: `{"steps": [], "remaining_steps": ["a","b"]}`
        # read as "nothing remains" while the model had written the tail one key over. Zero corpus
        # occurrences, and still wrong in the direction that costs the most — this reader also drafts
        # the INITIAL plan, where one miss costs the whole run.
        empty_answer = False
        for k in _STEP_KEYS:
            v = obj.get(k)
            if isinstance(v, list):
                steps = [c for s in v if (c := _clean_step(s))]
                if steps:
                    return steps
                if not v:
                    empty_answer = True
            elif isinstance(v, str) and v.strip():  # a numbered plan packed into one string value
                steps = _split_inline_numbered(v)
                if steps:
                    return steps
        # No key anyone listed. A model answering a SYNONYM of the ask still answered — cria's own
        # replan prompt opens "Re-derive the REMAINING steps", and the reply came back under
        # `remaining_steps` (run 0727-142536: 981 tokens of correct work discarded, and the one-shot
        # last-resort rescue spent with it). Shape-driven, like the envelope recovery: when exactly
        # ONE key holds a usable list, that is the list. TWO is ambiguous and stays a safe null —
        # cria does not guess which one the model meant.
        candidates = []
        for k, v in obj.items():
            if k in _STEP_KEYS or not isinstance(v, list) or not v:
                continue
            got = [c for x in v if (c := _clean_step(x))]
            if got:
                candidates.append(got)
        if len(candidates) == 1:
            return candidates[0]
        return [] if empty_answer and not candidates else None
    return None


def _top_level_array_steps(body: str) -> list[str] | None:
    """The steps of a reply that IS a JSON array, or ``None``.

    "IS", not "contains": the denoised reply must open with ``[``. That single rule is what keeps a
    Python file, a README, or any prose carrying a subscript from being read as a plan — see
    :func:`json_steps` for the capture that measured it.

    A NON-EMPTY array that yields no step text is ``None``, not ``[]``. The two mean opposite things
    to :func:`cria.loop.reassess_remaining` — ``[]`` drops the remaining plan, ``None`` keeps it — and
    ``[1, 2, 3]`` or ``[null, null]`` is a model that answered with something other than steps, not a
    model saying the work is finished. Only an array the model wrote as literally empty says that."""
    cleaned = jsontext.denoise(body).strip()
    if not cleaned.startswith("["):
        return None
    try:
        arr = jsontext_loads(cleaned)
    except ValueError:
        return None
    if not isinstance(arr, list):
        return None
    steps = [c for x in arr if (c := _clean_step(x))]
    return steps if steps or not arr else None


def parse_steps(text: str) -> list[str] | None:
    """Extract plan steps, accepting a numbered/bulleted list (the prompt's ask, and what small models
    emit best), JSON in any of the shapes :func:`json_steps` reads, OR — when that JSON is malformed
    by unescaped inner quotes — the salvaged array items. Returns None when none yield steps.

    An EMPTY JSON list falls THROUGH to the prose fallbacks here rather than being returned. This
    reader's callers draft a plan, and "the model returned no steps" is a failed draft for them; only
    the living re-derivation has a meaning for ``[]``, and it calls :func:`json_steps` directly."""
    body = strip_think(text)
    steps = json_steps(body)
    if steps:
        return steps
    salvaged = _salvage_array_steps(body)  # malformed JSON array (unescaped inner quotes) → recover items
    if salvaged:
        return salvaged
    lines = body.splitlines()
    numbered = _numbered_with_details(lines)
    if numbered:
        return numbered  # numbered plan → sub-bullets under a step are its DETAILS, folded INTO it
    bullets = [c for line in lines if (m := _BULLET_LINE.match(line)) and (c := _clean_step(m.group(1)))]
    return bullets or None


def _numbered_with_details(lines: list[str]) -> list[str]:
    """A numbered plan's steps, each carrying its own sub-detail lines.

    Sub-bullets under a numbered step are its DETAILS, not steps — folding them in as steps exploded a
    7-step plan into 11 and marched the coder through phantom steps. But DROPPING them destroys the
    step. Observed live (run 0726-132914): the planner wrote "3. Write a Python script (e.g.,
    `resolve_handle.py`) that:" followed by four indented requirements (accept a handle, GET the
    endpoint, parse the three fields, print them) and cria handed the coder the header alone — a
    sentence trailing off at a colon with every requirement deleted. Same for the unit-test and README
    steps. cria must never destroy content the model relies on; the detail belongs WITH its step.

    Attached: any indented line, and any bullet/lettered item, that follows a numbered step. Plain
    unindented prose is NOT attached (it is the model's commentary around the list, not a requirement).
    Joined on ONE line so the plan mirror stays line-based."""
    steps: list[str] = []
    cur: list[str] | None = None
    for line in lines:
        m = _NUM_LINE.match(line)
        if m:
            if cur:
                steps.append(" ".join(cur))
            cur = [m.group(1).strip()]
            continue
        if cur is None:
            continue
        s = line.strip()
        if not s:
            continue
        if line[:1].isspace() or _BULLET_LINE.match(line) or _SUB_ITEM.match(s):
            cur.append(s)
    if cur:
        steps.append(" ".join(cur))
    return [c for s in steps if (c := _clean_step(s))]


# A host-shaped name: dot-separated labels ending in a letters-only suffix. Deliberately
# OVER-inclusive — `fib.py` and `README.md` match it too. This is the GATHER half, and its job is to
# hand the reasoner every candidate; deciding which of them the work actually depends on reading is
# the JUDGE's, and a filename is answered NONE without cria owning a list of what looks like a file.
_HOST_SHAPED = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}\b", re.I)


def _unread_hosts(steps: list[str], facts: dict, task: str = "") -> list[str]:
    """Host-shaped names that BOTH the request and the plan use, and that this session never READ.

    The discrepancy is deterministic: named in the request AND carried into the plan, minus every host
    a 2xx fetch really returned (``facts``). A host counts as read only when something came back from
    it — being NAMED is not evidence of anything, which is the whole point: the user writing
    "api.handle.me" in their request is what creates the dependency, not what satisfies it.

    Requiring it in the REQUEST is what keeps this from firing on every plan. The pattern is
    over-inclusive by design (`fib.py` and `README.md` are host-shaped too), and a plan mentions
    filenames constantly — so matching on the plan alone would spend a reasoner call on almost every
    task. A service the WORK depends on is one the person asking named; a route the planner invented
    on its own is already covered by the URL-grounding check.

    Measured (run 0727-090143): the planner listed an empty git repo, that counted as research, and it
    drafted against `api.handle.me` — named in the request, never fetched — inventing
    `/resolve?handle={handle}`, which the coder built and 404'd."""
    read = set()
    for url in facts:
        try:
            host = urllib.parse.urlsplit(url).netloc.lower()
        except ValueError:
            continue
        if host:
            read.add(host)
    asked = {h.lower() for h in _HOST_SHAPED.findall(task or "")}
    named = {h.lower() for h in _HOST_SHAPED.findall("\n".join(steps))}
    return sorted((named & asked) - read)


def _parse_unread_verdict(ans: str, candidates: list[str]) -> list[str]:
    """A host-judge reply → the candidates it says must be read. STRICT, same posture as the noise
    judge's step-number parse: only a clean list of the candidate names counts. NONE, prose, or any
    token that was not offered takes the safe null (challenge nothing) — cria never hands a plan back
    on a guess, and a reasoner that answers in sentences must not have its nouns mined for a verdict."""
    text = (ans or "").strip().strip(".")
    if not text or re.fullmatch(r"(?i)none", text):
        return []
    parts = [p.strip().lower().strip(",.") for p in re.split(r"[,\s]+", text) if p.strip()]
    allowed = {c.lower() for c in candidates}
    if not parts or any(p not in allowed for p in parts):
        return []
    return sorted(set(parts))


def _parse_missing_verdict(ans: str) -> list[str]:
    """A coverage-judge reply → the requested deliverables it says no step produces.

    Only a clean ``{"missing": [...]}`` counts. Prose, a bare word, or a non-list value takes the safe
    null (nothing missing). That posture matters more here than anywhere else: "what is missing?" is an
    OPEN question, and an open question is exactly where a weak reasoner starts inventing requirements
    the user never asked for — the same failure that made a research step unsatisfiable and held one
    plan open for 111 calls. If it cannot answer cleanly, cria hands nothing back."""
    obj = extract_json_object(strip_think(ans or ""))
    if not isinstance(obj, dict) or not isinstance(obj.get("missing"), list):
        return []
    return [t for item in obj["missing"] if (t := str(item).strip())]


def _facts_digest(facts: dict) -> str:
    """The research findings as a few compact lines — one per source that actually returned, with the
    routes and response fields the shared spec extractors found in it. Rendered from the RECORDED
    result of each fetch, never re-derived from the model's prose, and only ever for a 2xx: this is a
    restatement of ground truth, so a failed fetch contributes nothing."""
    lines = []
    for url, entry in facts.items():
        status, routes, fields = (tuple(entry) + ("", ""))[:3]
        lines.append(f"- {url} → {status}")
        if routes:
            lines.append(f"    routes it defines: {routes}")
        if fields:
            lines.append(f"    response fields: {fields}")
    return "\n".join(lines)


def _gather_evidence(messages: list[dict]) -> str:
    """What the gather actually SAW — the seed/task turns and every tool RESULT, never the model's own
    assistant turns. Excluding its own turns is what makes the grounding check honest: a route it merely
    GUESSED at in a `web_fetch(url=…)` call would otherwise appear in the "evidence" and ground itself.

    It also keeps a FAILED fetch from becoming a fact for free — a failed gather fetch renders as
    `[web_fetch error: HTTP Error 404: Not Found]`, which carries no URL, so a route that 404'd
    contributes nothing to the evidence rather than proving itself real."""
    return "\n".join(str(m.get("content") or "")
                     for m in messages if m.get("role") in ("user", "tool"))


def missing_deliverables(ask, task: str, steps: list[str]) -> list[str]:
    """Which things the REQUEST asks for does this plan not produce? Shared coverage core —
    ``ask(system, user) -> str`` is the caller's one-shot reasoner call. Used by the INITIAL draft
    (Planner._missing_deliverables) and the living re-derivation (loop.reassess_remaining): measured
    (run 0728-m6) a coverage-checked six-step draft was thrash-re-derived into ONE step, dropping
    unit tests + live test + README, and nothing re-checked the tail — the run ended "satisfied"
    with a named deliverable absent. Safe-null parse (_parse_missing_verdict): unparseable → []."""
    ans = ask(prompts.load("plan_coverage"),
              prompts.render("plan_coverage_user", task=task,
                             plan="\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))))
    return _parse_missing_verdict(ans)


def deliverable_lost_by_drop(ask, task: str, dropped: str, remaining: list[str]) -> str:
    """The thing the REQUEST asks for that only ``dropped`` produces — "" when deleting it loses
    nothing. One focused question per deleted step, and the last word on whether it goes.

    THE BROAD COVERAGE CHECK IS NOT ENOUGH, and this is not a second opinion — it is a different
    question. :func:`missing_deliverables` asks "does this whole plan cover everything?", an OPEN
    audit over every step at once, and it is the check that was already running when the noise judge
    deleted a README. Walked on ada-handles_fabliq_codex_pon_1785801960 (00:14:24): the judge dropped

        "Add a README.md file explaining how to install dependencies (`pip install requests
         pytest`), run the script with an Ada Handle, and execute unit tests."

    — a deliverable the task names in its own words — because a README that explains how to install
    necessarily contains `pip install`, which reads as environment setup. `missing_deliverables` then
    ran over the surviving 5 steps and returned NOTHING MISSING. The plan went 8 steps to 6 and no
    step produced a README again. So the answer cannot be to ask the same open question harder.

    This asks about ONE step, names it, and shows what would remain — the narrow question a weak
    reasoner can actually hold (principle 9's corollary: one focused question beats a broad one doing
    the same work). The prompt carries the specific trap by name, because it is the trap: a step can
    DESCRIBE installing while its action is producing documentation.

    IT FAILS CLOSED, unlike every other judge in this file. An unparseable or empty answer KEEPS the
    step. The other judges take the safe null in the direction of doing nothing because their action
    is to hand a plan back or invent a requirement; this one's action is a DELETION, and the
    asymmetry is total — keeping a plumbing step costs one turn, while deleting a deliverable means
    the work never happens and nothing later notices (#2: the dangerous class of intervention is the
    one that removes correct content). Measured in cria's own logs: this noise judge has fired 156
    times across every recorded day and dropped at least one step 75 times; it deleted deliverables
    twice in this ladder alone, once ending a run at 1/4 with "unit tests" and "live test" gone."""
    ans = ask(prompts.load("plan_drop_check"),
              prompts.render("plan_drop_check_user", task=task, dropped=dropped,
                             remaining="\n".join(f"- {s}" for s in remaining) or "(none)"))
    obj = extract_json_object(strip_think(ans or ""))
    if not isinstance(obj, dict) or not isinstance(obj.get("lost"), str):
        return "unreadable verdict"   # fail CLOSED — the step stays
    return obj["lost"].strip()


def surviving_noise_drops(ask, task: str, steps: list[str], drop: set) -> tuple[set, dict]:
    """``drop`` minus every index whose deletion would lose a deliverable — and what each refusal
    saved, for the caller to trace. Deciding one step at a time (rather than refusing the whole drop
    set on one bad member) keeps the genuine plumbing removals that share the verdict: in the walked
    run the same verdict carried a correct venv removal and the README deletion."""
    kept_drop, refused = set(), {}
    for i in sorted(drop):
        remaining = [s for j, s in enumerate(steps) if j != i and j not in drop]
        lost = deliverable_lost_by_drop(ask, task, steps[i], remaining)
        if lost:
            refused[i] = lost
        else:
            kept_drop.add(i)
    return kept_drop, refused


def reasoned_noise_indices(ask, task: str, steps: list[str], facts: str = "") -> set:
    """Indices of NOISE steps to DROP from a plan — pure environment-plumbing, a bare shell command,
    dictated literal code, or a FABRICATED/SPECULATIVE guess (a made-up endpoint/path/field the coder
    should learn from the real source) — JUDGED by the reasoner (plan_noise_steps.txt). ONE reasoner
    question replaces the whole pile of keyword/shape regexes that used to read intent out of prose and
    drive deletions (plumbing, shell-command, baked-content, endpoint-guess). ``ask(system, user) -> str``
    is the caller's one-shot reasoner call. Reasoner-only, no fuzzy fallback: an answer with no step
    numbers (NONE, or anything unparseable) drops NOTHING — cria never deletes a step on a guess. Shared
    by the initial plan (Planner.plan_for) and the living re-derivation (loop.reassess_remaining).

    STRICT parse — the answer must be a CLEAN verdict, never a digit scraped out of prose. A weak model
    that wraps its verdict in reasoning ("steps 1 and 2 look fine; step 3 is plumbing") would otherwise
    have EVERY number it mentions — including the ones it ENDORSES — read as a deletion, silently
    dropping correct steps (principle #2: never delete correct content). So we honor only a bare number
    list; a NONE / prose / mixed answer takes the safe null (drop nothing)."""
    if not steps:
        return set()
    plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    # ONE question, WITH the task. There used to be a second, deliberately TASK-LESS pass asking only "which
    # steps are pure env/dependency setup?", unioned into the drop set — added because the compound judge
    # above waves a "create a venv + pip install" step through as good project work. Measured across the
    # captures, that blinded pass was wrong far more often than right: of 6 acted-on verdicts, 4 deleted a
    # step the prompt explicitly EXCLUDES — twice the RESEARCH step ("fetch the OpenAPI specification…",
    # "web_fetch the spec and store it locally") and twice a DOCS step (a README whose CONTENT mentions
    # `pip install`). Deleting the research step is precisely how the coder ends up guessing an endpoint.
    # Blinding the judge to the task is what did it: without the task it cannot tell a step whose OUTPUT is
    # documentation from a step whose ACTION is installing. And the failure it was built for already has an
    # upstream, ground-truth handler — writeproxy appends prompts/pep668_remedy on the REAL
    # externally-managed-environment error — so this was a speculative pre-deletion in front of a fix that
    # already exists. A setup step is still dropped when the task-aware judge agrees it is one.
    # THE RESEARCH LEDGER, when there is one. The prompt tells this judge to drop a step that bakes in
    # "a guessed API endpoint/path, a guessed field name" — and it was handed the task and the plan and
    # nothing else, so it had no source to check a name against and was ruling on appearance. Over the
    # recorded drops 57% named a snake_case field and 17% named a URL path; one deleted
    # `/holders/{address} … total_handles`, where both names came out of the fetched spec.
    # OMITTED when empty: cria knowing nothing is not evidence that a name is invented, and a judge
    # shown an empty ledger would read every field as unverified and delete correct steps.
    user = f"TASK:\n{task}\n\nPLAN:\n{plan_text}"
    if facts.strip():
        user = f"{facts.strip()}\n\n{user}"
    ans = strip_think(ask(prompts.load("plan_noise_steps"), user) or "").strip()
    return _parse_step_numbers(ans, len(steps))


def _parse_step_numbers(ans: str, n_steps: int) -> set:
    """A reasoner verdict that must be a CLEAN 1-based step-number list (else the safe null: empty). Never
    scrape a digit out of prose — a model that wraps its answer in reasoning would have every number it
    MENTIONS (including endorsed steps) read as a deletion (principle #2: never delete correct content)."""
    if not re.fullmatch(r"[0-9][0-9,\s]*\.?", ans):   # NONE / prose / mixed → drop nothing
        return set()
    return {int(x) - 1 for x in re.findall(r"\d+", ans) if 0 <= int(x) - 1 < n_steps}


# NB: cria does NOT author plan steps. A "research-first" enforcement used to prepend its own step
# ("web_fetch <the named domain>'s real source") whenever the task named an API host and the planner had
# drafted no research step, and PIN it so the living re-derivation couldn't touch it. Both halves were
# overreach: authoring a step is planning cria has no business doing (the injected step still had to guess
# a discovery URL), and pinning made a possibly-wrong step an inescapable mandate — it needed its own
# release valve to stop trapping the coder. plan.txt already tells the drafter to research first, the step
# critic clears a research step on facts obtained, and the durable ⟦ctx:facts⟧ ledger keeps the real
# endpoints in front of the coder across compaction. Those are the general mechanisms; this was a
# task-shaped injection on top of them.


class Planner:
    def __init__(self, provider, *, role=None, search_key: str = "", max_gather_rounds: int = 12, clock=None) -> None:
        self._provider = provider  # an Upstream-like with .chat(body, rlog)
        # No model: the planner's bodies carry no `model`, so the upstream fills the server's loaded
        # model (cria never pins an alias — the single-loaded-model posture).
        self._role = role  # Role | None — the reasoner role's per-request sampling/reasoning
        self._search_key = search_key or ""  # Brave key for the planner's web_search (may be "")
        self._max_rounds = max(1, max_gather_rounds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # NEGATIVE cache only: task_key -> None for tasks that don't plan (unparsed / the model
        # emitted a tool call instead of a plan), so the reasoner isn't re-called every turn of a
        # session. Plannable results are deliberately NOT cached — each session re-plans fresh, so a
        # re-run (e.g. after deleting the files) does the work rather than reusing a prior plan (a
        # cached MUTABLE Plan previously leaked all-`done` state across sessions → immediate exit).
        self._plans: dict[str, None] = {}
        self._retriable_failure = False  # set when a plan failure is a gather overrun, not unplannable
        self._lock = threading.Lock()

    def plan_for(self, messages: list[dict], rlog, prior_work: str = "",
                 rewrite_summary: str = "") -> Plan | None:
        """Return the drafted plan for this task, drafting it the first time and
        returning the cached one thereafter. ``None`` if there's no task text or the
        reasoner produced no usable plan.

        ``prior_work`` (the completion-compaction of an earlier finished plan on this session) grounds
        a FOLLOW-UP so the planner plans the new ask ON TOP of the done work — without it the planner
        sees only ``latest_user_text`` and re-plans from scratch (blind to what it already built).

        ``rewrite_summary`` (the new conversation root after the HARNESS compacted — its summary of
        the thread) frames a post-compaction CONTINUATION: plan only the remaining work, treating the
        summary as record-of-done + current intent — never as a fresh task to plan verbatim (planning
        the summary text produced placeholder plans). Mutually exclusive with ``prior_work`` on
        purpose: stacking two summaries drowned the planner."""
        task = latest_user_text(messages)
        if not task.strip():
            return None
        # The negative cache is FRAME-aware: a failed fresh gather must not permanently kill the
        # rewrite/continuation frames for the same text (and vice versa) — the frames produce
        # different seeds, so one frame's unparseable result says nothing about another's.
        key = _task_key(task) + ("|rw" if rewrite_summary else "|cont" if prior_work else "")
        with self._lock:
            if key in self._plans:  # negatively cached (unplannable) — don't re-call the reasoner every turn
                return None
        cwd = _extract_cwd(messages)
        self._retriable_failure = False
        self._gather_facts = {}   # reset per draft: last run's findings are not this run's evidence
        steps = self._gather_and_plan(task, cwd, rlog, prior_work=prior_work, rewrite_summary=rewrite_summary)
        # A weak model sometimes drafts an EMPTY / unparseable plan (observed: the reasoner returned just
        # "\n" → no plan → the whole coding session fell to the UNGUARDED proxy and stopped silently). It's
        # non-deterministic, so re-draft a couple times before giving up — one bad draft shouldn't cost the
        # session its guarded loop. Only for the unparseable case (a retriable gather-overrun is not re-tried
        # here — the drive re-plans next turn).
        attempts = 0
        while not steps and not self._retriable_failure and attempts < PLAN_RETRIES:
            attempts += 1
            rlog.emit("plan.retry", attempt=attempts, level="info")
            self._retriable_failure = False
            steps = self._gather_and_plan(task, cwd, rlog, prior_work=prior_work, rewrite_summary=rewrite_summary)
        if not steps:
            if self._retriable_failure:
                # The model WANTED to keep working (its last response was a tool call, recovered or
                # native) — a gather overrun, not an unplannable task. Don't poison the cache; the
                # next turn retries planning. (Observed live: one bad forced-plan permanently
                # downgraded a whole session to the proxy path.)
                rlog.emit("plan.retriable", level="info")
                return None
            # Negative cache: an unplannable task (unparsed prose, no plan) must not re-call the
            # reasoner on every subsequent turn of the session.
            with self._lock:
                self._plans[key] = None
            return None
        # A FRESH plan, drafted anew each session — the plannable result is NEVER cached. Re-running
        # a task (a new session, e.g. after deleting the files) re-investigates and re-plans, so it
        # actually does the work instead of reusing a prior run's plan. Within ONE session the loop's
        # own session store holds the live plan; plan_for is called only on that session's first turn,
        # so this doesn't re-plan mid-session.
        # Sanitize the drafted plan with ONE reasoner judgment (no keyword/shape regex reads intent out of
        # prose): which steps are NOISE — pure env-plumbing (unverifiable; the env is fixed / sandbox
        # blocks apt-get+pip), a bare shell command (a coder action, not an outcome), dictated literal
        # code, or a FABRICATED/SPECULATIVE guess (a made-up endpoint/path/field the coder should learn
        # from the real source). plan.txt already tells the drafter to avoid all of these; this is the
        # focused safety judgment for what slips through. Never empties the plan (an all-noise verdict is
        # kept as-is — the step critic still guards every step).
        drop = self._reasoned_noise_indices(task, steps, rlog)
        # Per-step, fail-closed: refuse just the deletions that would lose a deliverable and let the
        # rest of the verdict stand (see planner.deliverable_lost_by_drop for what the broad coverage
        # check below missed, and why this is a different question rather than a second opinion).
        if drop and self._role is not None:
            drop, refused = surviving_noise_drops(
                lambda sysp, usr: self._ask(sysp, usr, rlog), task, steps, drop)
            for i, lost in refused.items():
                rlog.emit("plan.noise_refused", level="warn", lost=lost, step=steps[i][:160])
        kept = [s for i, s in enumerate(steps) if i not in drop]
        if drop and kept:
            # ORDER MATTERS (run 0728-m10): coverage judges the plan at SUBMIT time, so a noise drop
            # after it is an UNCHECKED deletion — the noise judge ate the script and test steps of a
            # coverage-clean draft and a one-step README "plan" entered the loop. The same hole was
            # closed in the living re-derivation (loop.reassess_remaining); this is the initial-draft
            # side. A drop that uncovers deliverables is REFUSED — the plan keeps all its steps (the
            # step critic still guards each one) and the refusal is traced, never silent.
            if self._role is not None and missing_deliverables(
                    lambda sysp, usr: self._ask(sysp, usr, rlog), task, kept):
                rlog.emit("plan.noise_uncovered", count=len(drop), level="warn")
            else:
                rlog.emit("plan.noise_dropped", count=len(drop), level="info")
                steps = kept
        elif drop:
            rlog.emit("plan.noise_all_kept", count=len(drop), level="info")  # dropping would empty it
        # DETERMINISTIC SCRUB, after the reasoned noise pass. Both facts below are EXACT — a path
        # either exists or it doesn't, a tool name either appears or it doesn't — so code gathers
        # them and nothing here is a judgment. Only the tool-step REWRITE goes to the reasoner
        # (principle 8), and it fails safe: an unusable answer keeps the step as drafted.
        scrubbed: list[str] = []
        for st in steps:
            fixed, note = repoint_unusable_paths(st, cwd or "")
            if note:
                rlog.emit("plan.step_path_unusable", level="warn", fix=note, step=st[:160])
            tool = step_names_tool(fixed, task, cwd or "")
            if tool and self._role is not None:
                asked = strip_think(self._ask(prompts.render("plan_step_outcome", step=fixed),
                                              "", rlog) or "").strip().strip('"').splitlines()
                cand = asked[0].strip() if asked else ""
                if cand and not step_names_tool(cand, task, cwd or "") and len(cand) > 12:
                    rlog.emit("plan.step_tool_rewritten", level="info", tool=tool,
                              was=fixed[:120], now=cand[:120])
                    fixed = cand
                else:
                    rlog.emit("plan.step_tool_kept", level="warn", tool=tool, step=fixed[:160])
            scrubbed.append(fixed)
        steps = [st for st in scrubbed if st.strip()] or steps
        # The plan is the PLANNER's, minus the noise judgment above — cria adds no step of its own (see the
        # research-first note above the class).
        items = [PlanItem(text=s) for s in steps]
        plan = Plan(
            id=self._new_id(key),
            task=task,
            created=self._clock().isoformat(timespec="seconds"),
            items=items,
            # What the research READ travels with the plan, so the coder starts knowing the real
            # routes instead of rediscovering (or inventing) them. See Plan.gather_facts.
            gather_facts=dict(getattr(self, "_gather_facts", None) or {}),
        )
        rlog.emit("plan.drafted", id=plan.id, steps=len(steps))
        return plan

    def _ask(self, system_prompt: str, user: str, rlog) -> str:
        """One targeted, single-shot reasoner question → its cleaned text answer ("" on any failure).
        A weak model judges a narrow binary ("does the task name an API?", "does the plan research?")
        far more reliably than a keyword regex reads it out of prose — this is the "reasoner JUDGES,
        code ACTS" path. Toolless; the caller parses YES/NO or a bare token.

        The budget is ASK_MAX_TOKENS, not the 2000 it used to be: a reasoning model spends the budget
        THINKING before it writes anything, so too small a cap means it never reaches the verdict.
        Measured (run 0727-114502, call 0028): `finish_reason: length`, `completion_tokens: 2000` —
        the cap exactly — 8,865 characters of reasoning and ZERO content. It had already reached the
        right answer in that reasoning ("we should remove any steps that are just environment setup.
        Thus steps to remove: 1 (installation)") and was cut off mid-sentence before it could say so,
        and a plan opening with `pip install` and `venv` was accepted whole.

        An empty answer is indistinguishable from "nothing to report", so the judgement is skipped
        silently — hence the emit below: a skipped judgement must show up in the record rather than
        looking like a clean verdict. (Deliberately NOT a reasoning-off retry: that is a second call
        papering over a budget that was simply too small, and it throws away reasoning that had
        already arrived at the answer.)"""
        body = {"temperature": 0, "stream": False, "max_tokens": ASK_MAX_TOKENS,
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": user}]}
        if self._role is not None:
            self._role.apply(body, internal=True, rlog=rlog)
        try:
            comp = json.loads(self._provider.chat(body, rlog))
            msg = _assistant_message_obj(comp)
        except Exception:  # noqa: BLE001 - any upstream/parse failure → let the caller fall back
            return ""
        content = strip_think(msg.get("content") or "")
        if self._role is not None:
            content = self._role.clean_content(content)
        content = content.strip()
        if not content:
            fin = ((comp.get("choices") or [{}])[0]).get("finish_reason")
            rlog.emit("plan.ask_no_answer", level="warn", finish=fin,
                      used=(comp.get("usage") or {}).get("completion_tokens"))
        return content

        return once(False) or once(True)

    def _hosts_needing_read(self, task: str, steps: list[str], facts: dict, rlog) -> list[str]:
        """Which hosts the plan names, but never read, does the work actually DEPEND on reading?

        Deterministic code gathers the discrepancy; ONE reasoner call judges it. The judgment is
        genuinely a judgment — `api.handle.me` in "call it to resolve a handle" must be read, while
        `example.com` in "link to it from the README" need not be, and no lexical rule separates
        those without an exception list that would be wrong on its first unseen case (principles #8,
        the tell). Costs NOTHING when there is nothing to ask about: no unread host, no call. No
        reasoner configured → no judgment, exactly like the noise judge."""
        candidates = _unread_hosts(steps, facts, task)
        if not candidates or self._role is None:
            return []
        ans = strip_think(self._ask(
            prompts.load("plan_host_unread"),
            prompts.render("plan_host_unread_user", task=task, hosts="\n".join(candidates),
                           plan="\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))),
            rlog) or "")
        return _parse_unread_verdict(ans, candidates)

    def _missing_deliverables(self, task: str, steps: list[str], rlog) -> list[str]:
        """Which things the REQUEST asks for does this plan not produce?

        The coder follows the plan and stops when its steps are done, so a plan that omits a
        deliverable silently drops it. `replan.txt` has carried this rule for the re-derivation all
        along ("every deliverable the user asked for ... must still be covered by a step"); the INITIAL
        draft never had it and nothing enforced it. Measured (run 0727-090143): a one-step plan —
        "Explore the workspace" — was accepted for a request wanting a script, unit tests, a live test
        and a README, and only the end-of-task satisfaction critic caught it, long after coder calls
        had been spent. This asks the same question at draft time, for one call, before any of them are.

        Nothing is invented on cria's side either way: the items named back are the USER's own asks,
        and the planner writes the steps. No reasoner → no judgment."""
        if self._role is None or not steps:
            return []
        return missing_deliverables(lambda sysp, usr: self._ask(sysp, usr, rlog), task, steps)

    def _reasoned_noise_indices(self, task: str, steps: list[str], rlog) -> set:
        """Indices of NOISE steps to DROP, JUDGED by the reasoner (see ``reasoned_noise_indices``). No
        reasoner configured → drop NOTHING (the plan is used as drafted); cria doesn't classify steps
        without a reasoner to judge them.

        The gather's OWN research ledger rides along: this judge is asked to spot a guessed endpoint or
        field name, and ``_gather_facts`` is what the research phase actually read. It is populated by
        the time this runs (``_gather_and_plan`` sets it before returning the steps)."""
        if self._role is None:
            return set()
        return reasoned_noise_indices(
            lambda sysp, usr: self._ask(sysp, usr, rlog), task, steps,
            facts=groundtruth.researched_facts(getattr(self, "_gather_facts", None) or {}))

    def _gather_and_plan(self, task: str, cwd: str, rlog, prior_work: str = "",
                         rewrite_summary: str = "") -> list[str] | None:
        """The gather loop: hand the reasoner READ-ONLY tools and let it investigate,
        feeding each round back as protocol, until it stops calling tools and answers with
        the plan. A repeated gather signature (looping) forces the plan; so does the round
        cap. Degrades gracefully — a model that never calls a tool just plans immediately.

        ``prior_work`` seeds the FIRST message with the earlier work's summary + the new ask (via
        ``plan_continuation``), so a follow-up is grounded — it inspects what exists rather than
        guessing filenames and re-planning the whole task. ``rewrite_summary`` seeds the
        post-harness-compaction frame instead (``plan_rewritten``) and wins over prior_work."""
        if rewrite_summary:
            # The compacted root usually IS the latest user text; when they're the same, the "current
            # request" is simply to finish what the summary says is unfinished.
            ask = task if task.strip() != rewrite_summary.strip() else \
                prompts.load_map("planner_steers")["default_ask"]
            seed = prompts.render("plan_rewritten", summary=rewrite_summary, task=ask)
        elif prior_work:
            seed = prompts.render("plan_continuation", prior=prior_work, task=task)
        else:
            seed = task
        # SAY WHERE THE WORKSPACE IS. cria resolves every read_file/exec_command below against `cwd`
        # (see execute_tool) and, until now, never told the planner what it was — so a model with
        # filesystem tools and no location had to guess one. Measured across every captured prompt:
        # the CRITIC is given the workspace root in 292 of 331 prompts (88%); the PLANNER, in 31 of
        # 481 (6%). Run 20260801T211548 (zaya1, ada-handles, 0/4) is what that costs: the planner
        # invented `/workspace/dumps/workspace` and read `setup.py`, `pyproject.toml`, `Dockerfile`,
        # `package.json` and `.github/workflows/test.yml` under it over and over — 140+ tool calls in
        # a single response, three rounds running, each cut off at the token cap. The run spent all
        # fifteen minutes in the planner and never reached the coder once.
        # Same function, same ground truth the critic already gets — one more caller, no new mechanism.
        inventory = groundtruth.workspace_inventory(cwd, flavor="planner") if cwd else ""
        # cria's ask goes LAST, after the task — the same ordering bug, in a third place.
        #
        # The seed ENDS with the user's own request, which for a coding task is literally "write a
        # Python script ... add a README". The planner instruction lives in the system message, far
        # above it. A model obeys the last instruction it reads, and zaya1 says so in its own
        # reasoning on run 20260801T221447 call 0002 — 27,089 characters of it, zero tool calls:
        #   "We can place everything in a single response."
        #   "We'll call web_search with query ... Let's simulate in our mind."
        #   "We'll use web_fetch. But we might not have internet access. However, we can simulate."
        #   "We must be careful not to include any extraneous text like 'Step 1: ...'. The answer is
        #    just the deliverables."
        # It was actively AVOIDING a plan and writing the deliverable instead. Word counts in that
        # reasoning: "script" 86, "readme" 35, "plan" 4. Three attempts, three runs, zero coder calls.
        # da35f4e fixed this ordering for harness compaction and e72a0e9/5d2b119 for the two
        # self-compaction paths; the planner is the same defect in the same shape.
        messages: list[dict] = [{"role": "user", "content": "\n\n".join(
            part for part in (inventory, seed, prompts.load("plan_closing_ask")) if part)}]
        recent_searches: list = []  # normalized word-sets, for the repeated-search 400 guard
        seen_sigs: set[str] = set()
        facts: dict = {}      # url -> (status, routes, fields) the RESEARCH really read (Plan.gather_facts)
        looked = False        # did any round actually call a tool? (the research floor, nudged once)
        nudged = False
        # An ephemeral scratchpad the gather may WRITE to (persist + process fetched data across
        # rounds) — in cria's OWN tmp, never the workspace (no-pollution), torn down after.
        scratch = tempfile.mkdtemp(prefix="cria-gather-")
        try:
            # ---- PHASE A: RESEARCH. `submit_plan` is NOT offered, so the planner CANNOT draft
            # before it has looked — the forced research step is enforced by the tool menu, not by
            # asking. (Prose asking for research-first was already in plan.txt and was ignored: 3 of
            # 4 measured runs planned having read no real source.) Ends when it stops calling tools.
            rounds = 0
            cut_noted = False      # say 'your reply was cut short' once, not every round
            pending_note = ""     # rides WITH the round's tool results, never instead of them
            while rounds < self._max_rounds:
                msg = self._reason(messages, rlog, research=True)
                if msg is None:
                    return None
                calls = _tool_calls(msg)
                # A reply CUT OFF at the output cap did not finish — but WHAT was unfinished
                # decides the handling, and my first version got this wrong in two ways.
                #
                # Checked against every captured cut-off round that carried tool calls (n=8): the
                # LAST call's arguments parse as valid JSON in 5 of them and are truncated mid-object
                # ("{") in 3. So "the list is unfinished" is true less than half the time, and
                # refusing the whole round threw away research the model really had made. And on
                # rounds with NO calls at all, the steer said "none of its tool calls were run" —
                # cria asserting something untrue (principle 5b), which is how it fired on run
                # 20260801T221447 calls 0002 and 0006, both of which made zero calls.
                #
                # So: drop only a trailing call that does not parse, keep and run the rest, and say
                # plainly that the reply was cut short. Nothing real is discarded.
                if msg.get(FINISH_KEY) == "length" and calls:
                    if _last_call_truncated(msg):
                        rlog.emit("plan.gather_partial_call_dropped", tool=calls[-1][1])
                        calls = calls[:-1]
                        msg["tool_calls"] = msg["tool_calls"][:len(calls)]
                    if calls and not cut_noted:
                        cut_noted = True
                        rlog.emit("plan.gather_cut_off", calls=len(calls))
                        pending_note = prompts.load_map("planner_steers")["reply_cut_off"]
                if not calls:
                    if looked or nudged:
                        break            # done looking → draft from what it found
                    # It went to plan without opening anything (measured: one run's planner made ZERO
                    # tool calls and drafted "perform a web search…" as step 1). ONE nudge to look
                    # first. It gets its own iteration rather than a gather round — a round spent on
                    # a nudge is a read not taken — and `nudged` bounds it to exactly one.
                    nudged = True
                    rlog.emit("plan.research_nudge")
                    messages.append({"role": "assistant", "content": msg.get("content") or None})
                    messages.append({"role": "user",
                                     "content": prompts.load_map("planner_steers")["research_first"]})
                    continue
                rounds += 1
                sig = _calls_signature(calls)
                # Feed the round back as PROTOCOL — the structured assistant tool-call turn, then
                # one `tool` result per call. NOT flattened to prose (the parroting trap).
                messages.append({"role": "assistant", "content": msg.get("content") or None, "tool_calls": msg["tool_calls"]})
                if sig in seen_sigs:
                    # A REPEAT — the model re-ran an identical call. Don't force the plan (a
                    # sledgehammer that cut off a still-productive gather); NUDGE it to use the
                    # result it already has (or submit its plan) and keep gathering. The nudge is
                    # a proper tool result per call, so the protocol stays well-formed, and the
                    # round cap still bounds a model that ignores it.
                    rlog.emit("plan.repeat_nudge", tools=[n for _, n, _ in calls])
                    for cid, name, _args in calls:
                        messages.append({"role": "tool", "tool_call_id": cid,
                                         "content": prompts.fill(prompts.load_map("planner_steers")["gather_repeat"], tool=name)})
                    continue
                seen_sigs.add(sig)
                # Execute each DISTINCT call once. A round is not bounded in how many calls it may
                # contain, and a model that loops re-asks the same one many times: measured across
                # every captured planner round (n=328, 719 calls), 236 — 32.8% — are exact duplicates
                # of another call in the SAME round. Run 20260801T211548 (zaya1, 0/4) emitted 138
                # calls in one response of which only 32 were distinct, and 134 in the next of which
                # 16 were, re-reading setup.py / pyproject.toml / Dockerfile / package.json under an
                # invented root and hitting a live API with the same request four times.
                # Nothing is withheld: every distinct call still runs, in full, and every tool_call_id
                # still gets its own complete result, so the protocol stays well-formed and the model
                # sees exactly what it asked for. Only the re-execution is dropped — same bytes, and
                # on a 15-minute wall at ~47 tok/s the time it gives back is the run.
                done: dict[tuple[str, str], object] = {}
                for cid, name, args in calls:
                    ckey = (name, json.dumps(args, sort_keys=True, default=str))
                    result = done.get(ckey)
                    if result is None:
                        result = planner_tools.execute_tool(name, args, cwd, self._search_key, recent_searches,
                                                            rlog, scratch=scratch, facts=facts)
                        done[ckey] = result
                        rlog.emit("plan.gather", tool=name)
                    else:
                        rlog.emit("plan.gather_dedup", tool=name)
                    # "Looked" means something came BACK, not that a call was made: in an empty
                    # workspace `ls`/`find` return nothing, and counting those as research let the
                    # planner draft from memory and invent an endpoint.
                    looked = looked or result.learned
                    messages.append({"role": "tool", "tool_call_id": cid, "content": result.text})
                if pending_note:   # additive: the results come first and whole, the note follows
                    messages.append({"role": "user", "content": pending_note})
                    pending_note = ""
            if rounds >= self._max_rounds:
                rlog.emit("plan.gather_cap", rounds=self._max_rounds)  # investigated to the cap
            # ---- PHASE B: DRAFT, from what the research actually found.
            self._gather_facts = dict(facts)
            return self._draft_plan(messages, task, facts, rlog)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _draft_plan(self, messages: list[dict], task: str, facts: dict, rlog) -> list[str] | None:
        """PHASE B — draft the plan from what the research found. Offer ONLY submit_plan (the gather
        tools are gone), so its one move is to hand over the plan.

        The research findings are re-stated as a COMPACT DIGEST in the final user turn, alongside the
        original ask. Both halves are load-bearing. The raw transcript is not enough on its own: it is
        tens of KB of fetched bodies in which the one line that matters appears once, and the context
        floor drops the OLDEST turns first, so by drafting time the successful-fetch headers can be
        gone. Measured (run 0726-221401): the planner fetched the real spec at gather call 4, the
        `HTTP 200 ·` header for it was floored out by call 10, and the plan it drafted at call 14
        named no endpoint at all. The digest rides in the LAST turn, which the floor drops LAST.

        The full transcript is still kept underneath — the digest is an ADDITION, never a
        replacement (a summary standing in for what the model really read is the substitution class).

        RETRY IN PLACE if it calls something else, rather than discarding the research and
        re-gathering next turn (the amnesia loop)."""
        if facts:
            messages = messages + [{"role": "user", "content": prompts.render(
                "plan_evidence", facts=_facts_digest(facts), task=task)}]
        # Each check may hand the plan back ONCE, and no more than MAX_PLAN_HANDBACKS in total.
        # The budget bounds how often cria HANDS BACK, not how often it LOOKS: a single shared
        # "challenged" flag meant the first check to fire silenced all the others, so the RE-DRAFT —
        # the most likely thing to be degraded — went unexamined. Measured (run 0727-110625): the URL
        # check fired, and the re-draft came back as one step that was a raw shell command producing
        # none of the four deliverables. It was accepted. Replayed against the live model, the
        # coverage check flags that plan 4 times out of 4; it simply never got to look.
        fired: set[str] = set()
        challenged_missing: set[str] = set()  # deliverables coverage has already handed back for

        def may_hand_back(which: str) -> bool:
            return which not in fired and len(fired) < MAX_PLAN_HANDBACKS
        # FROZEN at the end of the gather. `_gather_evidence` excludes the model's own ASSISTANT turns
        # precisely so a route it merely guessed at cannot ground itself — but cria's own challenge is
        # appended as a USER turn that NAMES the offending URLs, so recomputing per attempt let the
        # complaint ground the very thing it complained about: challenge `…/resolve` once, and a
        # planner that re-submits it unchanged is now "grounded" and accepted silently. Nothing after
        # the gather adds real evidence — only cria's steers and the model's drafts.
        evidence = _gather_evidence(messages)
        for attempt in range(_MAX_FINAL_RETRIES):
            msg = self._reason(messages, rlog, plan_only=True)
            if msg is None:
                self._retriable_failure = True  # transport/model error, not an unplannable task
                return None
            steps = _steps_from_submit(msg) or self._parse(msg, rlog)  # the tool call, else any text
            if steps:
                # The coder follows the plan VERBATIM, so a route the research never saw becomes a
                # shipped bug. Measured: a plan drafted after 17 real fetch rounds opened with "send a
                # POST request to the resolve endpoint at https://api.handle.me/resolve" — a host the
                # gather had only seen in search results, a route it had seen nowhere. Hand it back
                # ONCE and let it draft again. Never a rewrite (that would be cria authoring a plan)
                # and never twice (that would wedge): a drafter that insists gets its plan.
                # ALWAYS LOOK. The budget bounds how often cria HANDS BACK, never how often it
                # LOOKS — the same lesson as the shared-flag bug above, one level up. Gating the
                # LOOK meant a plan accepted on the last attempt carrying an invented route emitted
                # nothing, and read exactly like a clean plan. Measured (run 0727-151934): the budget
                # went to coverage and unread-host, and the accepted plan opened with
                # `https://api.handle.me/v1/ada-handles/by-ada-handle/goose` — a REAL route belonging
                # to a different project whose README a search returned, welded onto the task's host.
                # This check is pure deterministic code and costs nothing to run; the reasoner-backed
                # checks below stay gated, since a model call that cannot change anything is not a
                # purposeful call.
                bad = urlgrounding.ungrounded_urls("\n".join(steps), evidence)
                if bad and not may_hand_back("url"):
                    rlog.emit("plan.submit_ungrounded", level="warn", urls=",".join(bad),
                              handed_back=False)
                    bad = []
                if bad:
                    fired.add("url")
                    rlog.emit("plan.submit_ungrounded", urls=",".join(bad), handed_back=True)
                    messages = messages + [
                        {"role": "assistant", "content": msg.get("content") or None},
                        {"role": "user", "content": prompts.fill(
                            prompts.load_map("planner_steers")["submit_ungrounded"],
                            urls=", ".join(bad))}]
                    continue
                # A plan can be built against a host nobody ever READ — no invented route to catch,
                # just an assumption about what that host returns. Code finds the discrepancy (named
                # minus fetched); ONE reasoner call decides whether the work actually depends on
                # reading them, which is what keeps a README link or a package registry from drawing
                # a pointless challenge without cria owning a list of what counts as incidental.
                need = self._hosts_needing_read(task, steps, facts, rlog) \
                    if may_hand_back("host") else []
                if need:
                    fired.add("host")
                    rlog.emit("plan.host_unread", hosts=",".join(need))
                    messages = messages + [
                        {"role": "assistant", "content": msg.get("content") or None},
                        {"role": "user", "content": prompts.fill(
                            prompts.load_map("planner_steers")["host_unread"],
                            hosts=", ".join(need))}]
                    continue
                # And does the plan actually produce everything the request asked for? The coder stops
                # when the steps run out, so an omitted deliverable is silently dropped.
                # Once coverage has challenged, EVERY re-draft is looked at again, and it may hand
                # back again — but only for a deliverable it has not already challenged (a stubborn
                # drafter still gets its plan; the attempt loop bounds the whole exchange). The
                # once-only gate let a re-draft trade one deliverable for another: plan#1 was handed
                # back for total-handles, plan#2 restored that but silently DROPPED the live-test
                # step, and was adopted with no look — the run then structurally could not score
                # (run 0729-gemma4 pon1: the live test never had a plan step again).
                missing = self._missing_deliverables(task, steps, rlog) \
                    if (may_hand_back("coverage") or challenged_missing) else []
                new_missing = [x for x in missing if x not in challenged_missing]
                if missing and not new_missing:
                    rlog.emit("plan.missing_deliverables", missing=", ".join(missing), handed_back=False)
                if new_missing:
                    fired.add("coverage")
                    challenged_missing.update(missing)
                    rlog.emit("plan.missing_deliverables", missing=", ".join(missing), handed_back=True)
                    messages = messages + [
                        {"role": "assistant", "content": msg.get("content") or None},
                        {"role": "user", "content": prompts.fill(
                            prompts.load_map("planner_steers")["missing_deliverables"],
                            missing="; ".join(missing))}]
                    continue
                if attempt:
                    rlog.emit("plan.final_recovered", attempt=attempt + 1)
                rlog.emit("plan.submitted", steps=len(steps))
                return steps
            leaked = [((tc.get("function") or {}).get("name")) for tc in (msg.get("tool_calls") or [])]
            if not leaked:
                # PROSE that doesn't parse — a genuine no-plan verdict, not a tool-protocol slip.
                # Hand it straight back so plan_for re-drafts (PLAN_RETRIES) and then NEGATIVELY
                # CACHES an unplannable task; retrying in place would multiply the same failure and,
                # by ending in the retriable branch below, keep the planner re-called every turn.
                return None
            # Called something OTHER than submit_plan (e.g. a hallucinated `CreateNewProject`) →
            # retry. Log WHAT it called so the record shows it (not just "no plan").
            rlog.emit("plan.final_retry", attempt=attempt + 1, called=leaked)
        self._retriable_failure = True  # still no plan after retries — retriable, never poison-cache
        return None

    def _reason(self, messages: list[dict], rlog, *, research: bool = False, plan_only: bool = False) -> dict | None:
        """One planner call. A round that spends its whole output budget THINKING and emits nothing
        is retried with reasoning forced OFF — the same contract `_verdict` has enforced on the
        critic for the same reason, and which the planner never got.

        The critic's own note describes this exactly: "a reasoning model under the max_tokens cap can
        burn its whole budget THINKING and never emit the closing JSON". Measured over every captured
        planner round (n=499): 15 were cut off at the cap and **5 of those produced nothing usable at
        all** — no tool call, no content — behind 26,337 / 28,936 / 31,248 / 31,475 and 106,829
        characters of reasoning. On zaya1 it is the dominant failure, not a tail case: run
        20260801T221447 lost 2 of its 7 planner rounds this way and never reached the coder in 15
        minutes.

        Bounded to one retry, and only when the round produced NOTHING — a cut-off round that still
        emitted usable calls or text is kept as-is (see _last_call_truncated)."""
        msg = self._reason_once(messages, rlog, research=research, plan_only=plan_only)
        if (msg is not None and msg.get(FINISH_KEY) == "length"
                and not (msg.get("tool_calls") or []) and not (msg.get("content") or "").strip()):
            rlog.emit("plan.think_burn_retry", phase="research" if research else "draft")
            retry = self._reason_once(messages, rlog, research=research, plan_only=plan_only,
                                      think_off=True)
            if retry is not None and ((retry.get("tool_calls") or [])
                                      or (retry.get("content") or "").strip()):
                return retry
        return msg

    def _reason_once(self, messages: list[dict], rlog, *, research: bool = False,
                     plan_only: bool = False, think_off: bool = False) -> dict | None:
        body: dict = {
            "stream": False,
            "temperature": 0,  # default; the reasoner role's config (cria.toml) overrides below
            # Generous output room so a verbose reasoner's plan isn't cut mid-list — a truncated
            # plan is parsed as a PARTIAL step list, silently dropping the tail work. Still bounded
            # so a model that fails to stop can't run to context-length and hang the request.
            "max_tokens": 8192,
            "messages": [{"role": "system", "content": prompts.load("plan")}] + messages,
        }
        if self._role is not None:
            role = replace(self._role, reasoning="off") if think_off else self._role
            role.apply(body, internal=True, rlog=rlog)
        if research:
            # RESEARCH phase: the read-only tools ONLY — `submit_plan` is deliberately absent, so the
            # planner cannot draft before it has looked. The tool menu is the enforcement; the prose
            # version of this rule lived in plan.txt and was ignored (3 of 4 measured runs drafted
            # having read no real source, and two of those shipped an invented endpoint).
            body["tools"] = planner_tools.PLANNER_TOOLS
        elif plan_only:
            body["tools"] = [_SUBMIT_PLAN_TOOL]  # the ONLY move: submit the plan as a tool call
        try:
            rlog.phase = "planner"
            completion = json.loads(self._provider.chat(body, rlog))
            # Recover tool calls the model LEAKED as text (Hermes/XML/gemma-fable dialects) before
            # reading the message — llama.cpp doesn't parse the gemma `<|tool_call>call:NAME{…}`
            # syntax, so without this a quirky reasoner's gather (or submit_plan) call lands in
            # content and the parse fails.
            completion = massage.recover_leaked_tool_calls(completion, body.get("tools"), rlog)
            msg = _assistant_message_obj(completion)
            if msg is not None:
                # Carry WHY generation stopped. Without it cria could not tell a finished reply from
                # one cut off at max_tokens, and executed tool-call lists the model never finished
                # emitting. Private key: the gather composes its own dicts for the wire.
                try:
                    msg[FINISH_KEY] = (completion.get("choices") or [{}])[0].get("finish_reason")
                except (AttributeError, IndexError, TypeError):
                    pass
            return msg
        except Exception as e:
            # An INFRA failure (upstream error, parse crash) — distinct from a genuine no-plan
            # verdict (that returns None from _parse with a plan.unparsed warn). Log at ERROR so a
            # persistently broken planner is visible, not silently degraded to plain routing.
            rlog.emit("plan.error", level="error", error=f"{type(e).__name__}: {e}")
            return None

    def _parse(self, msg: dict, rlog) -> list[str] | None:
        content = msg.get("content") or ""
        if self._role is not None:
            content = self._role.clean_content(content)  # drop leaked reasoning when off
        steps = parse_steps(content)
        if not steps:
            # Log WHAT couldn't be parsed — cria then degrades to plain routing (no plan
            # loop) rather than stopping.
            rlog.emit("plan.unparsed", level="warn", sample=(msg.get("content") or "").strip()[:200])
            return None
        return steps

    def _new_id(self, key: str) -> str:
        return f"{self._clock().strftime('%Y%m%dT%H%M%S')}-{key[:8]}"



# The coder's tool names, EXACT. A plan step is an OUTCOME; a step that names one of these has
# prescribed the coder's mechanics, and cria's own plan_noise_steps.txt says so in three separate
# clauses ("a RAW SHELL COMMAND or tool invocation rather than a goal", "the coder chooses its own
# commands; a step states the OUTCOME, not the command"). The reasoned noise judge does not enforce
# it: walked on ada-handles_nemotron-elastic_codex_pon_1785360304, it read that rule aloud, argued
# "exec_command is a tool invocation, but it's not specifying a literal command like grep … Probably
# keep", and kept `use exec_command to locate the GET /handles/{handle} operation definition` — a
# step with no artifact, so nothing could ever mark it done. It was served 107 times and the run
# never reached step 2. MEASURED over every captured session: 51 of 395 distinct plan steps (13%),
# in 34 of 118 runs, name a coder tool; the other walked run's killer step ("edit_file at /tmp/… to
# add TestInvalidHandle test…") is in that set too.
#
# A tool name is an exact match against a known set — no judgment, no verb list, nothing fuzzy. So
# the DETECTION is deterministic and the REWRITE is the reasoner's (principle 8).
_CODER_TOOLS = ("write_file", "edit_file", "read_file", "list_dir", "view_image", "web_search",
                "web_fetch", "update_plan", "write_stdin", "exec_command", "task_complete",
                "apply_patch")
_TOOL_IN_STEP = re.compile(r"\b(?:" + "|".join(_CODER_TOOLS) + r")\b")

# A path token with a literal ellipsis segment (`/tmp/.../spec.yml`, `/tmp/…/spec.yml`) is not a path
# at all, and an absolute path outside the workspace is one the coder's dirguard refuses. Walked on
# 1785360304: step 1 named the PLANNER's own spill dir, rendered as `/tmp/.../api.handle.me_swagger_
# swagger.yml`. The coder's first four calls failed on it ("No such file or directory" twice,
# "Reading outside the working directory is not permitted here" twice), it absorbed the ellipsis into
# its own reasoning as fact, and the step stayed unsatisfiable for the whole run — while the same
# file sat in the workspace at tmp/read-only/. cria HAS a phantom-path guard (loop._phantom_system_path)
# and it covers steers only.
_ELLIPSIS_PATH = re.compile(r"(?<![\w/])(/(?:[\w.-]+/)*(?:\.\.\.|…)(?:/[\w.-]+)*)")
_ABS_PATH_TOKEN = re.compile(r"(?<![\w])(/(?:[\w.-]+/)+[\w.-]+)")


def _workspace_match(basename: str, root: str) -> str:
    """The single file under ``root`` with this basename, workspace-relative — else "".

    EXACT, not a guess: one basename, one hit, or nothing. Two hits is ambiguous and cria says
    nothing rather than pick."""
    if not basename or not root or not os.path.isdir(root):
        return ""
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        if basename in filenames:
            hits.append(os.path.relpath(os.path.join(dirpath, basename), root))
            if len(hits) > 1:
                return ""
    return hits[0] if len(hits) == 1 else ""


def repoint_unusable_paths(step: str, root: str) -> tuple[str, str]:
    """(step, note) — a plan step with any path the coder CANNOT use corrected or removed.

    Two deterministic classes, both facts cria holds rather than judgments: a path with a literal
    `...`/`…` segment is not a path, and an absolute path outside the workspace is one the dirguard
    refuses. When exactly one file in the workspace carries that basename the token is REPOINTED at
    it — an exact match, nothing invented. Otherwise the token is REMOVED: the step's outcome
    survives and the falsehood does not (rule 5b), which is strictly better than handing the coder a
    location that cannot be read."""
    out, notes = step or "", []
    root_prefix = (str(root).rstrip("/") + "/") if root else ""
    for pat in (_ELLIPSIS_PATH, _ABS_PATH_TOKEN):
        for m in list(pat.finditer(out)):
            tok = m.group(1)
            if tok not in out:
                continue                       # already rewritten by an earlier match
            elided = "..." in tok or "\u2026" in tok
            inside = bool(root_prefix) and tok.startswith(root_prefix)
            if not elided and inside and os.path.exists(tok):
                continue                       # a real path the coder is allowed to read
            if not elided and not root_prefix:
                continue                       # no workspace to judge against — say nothing
            real = _workspace_match(os.path.basename(tok), root)
            if real:
                out = out.replace(tok, real)
                notes.append(f"{tok} -> {real}")
            else:
                out = re.sub(r"\s{2,}", " ", out.replace(tok, "")).strip()
                notes.append(f"{tok} removed")
    return out, "; ".join(notes)


_GROUND_SCAN_MAX_BYTES = 2_000_000   # bounded sweep; a token this common is found long before here


def _token_is_grounded(token: str, task: str, root: str) -> bool:
    """True when this word belongs to the USER'S ask or to the WORKSPACE — not to cria's tool menu.

    Operator, 2026-08-05: "those tool names are not highly unique words. If the user asks to work on
    something that happens to also be a tool name, that breaks. Or if code contains one of those
    names and the plan calls it out. I guess if it isn't in the user prompt and it isn't in the code,
    then we're fine."

    Exactly right, and both halves are facts cria already holds: it has the task text and it has the
    workspace. `read_file`, `write_file`, `list_dir` are ordinary identifiers — a task that says
    "add a read_file helper", or a repo that already defines one, makes that word the USER'S, and a
    step naming it is describing the work rather than prescribing cria's mechanics. Grounded → the
    step is left exactly as drafted."""
    tok = (token or "").casefold()
    if not tok:
        return False
    if tok in (task or "").casefold():
        return True
    if not root or not os.path.isdir(root):
        return False
    spent = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in ("__pycache__", "node_modules",
                                                              "venv", "dist", "build")]
        for name in filenames:
            if tok in name.casefold():
                return True
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
                if size > 1_000_000 or spent + size > _GROUND_SCAN_MAX_BYTES:
                    continue
                with open(path, "r", errors="ignore") as fh:
                    body = fh.read(1_000_000)
                spent += len(body)
            except OSError:
                continue
            if tok in body.casefold():
                return True
    return False


def step_names_tool(step: str, task: str = "", root: str = "") -> str:
    """The coder tool name a plan step PRESCRIBES — else "".

    The match is exact, and so is the exclusion: a token the user's own ask or the workspace already
    uses is not cria prescribing a tool (see :func:`_token_is_grounded`). With neither task nor root
    supplied the exclusion cannot run and the bare match stands — callers that have them must pass
    them."""
    m = _TOOL_IN_STEP.search(step or "")
    if not m:
        return ""
    return "" if _token_is_grounded(m.group(0), task, root) else m.group(0)

def _extract_cwd(messages: list[dict]) -> str | None:
    """The workspace path a harness advertises in its environment preamble (e.g. Codex's
    ``<environment_context><cwd>…</cwd>``) — the harness's OWN repo, where the coding work happens.
    Returns ``None`` when no cwd is advertised: the workspace root is then UNKNOWN, and callers must
    NOT fall back to ``.`` — ``.`` is cria's own invocation dir, never the harness's repo, so a probe
    or a disk read against it would target cria's source tree. The caller persists the last-known cwd
    across turns (a harness compaction turn drops the <cwd> block) instead of re-defaulting to cria's dir."""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        mt = _CWD_RE.search(c or "")
        if mt and mt.group(1).strip():
            return mt.group(1).strip()
    return None


def _assistant_message_obj(obj) -> dict:
    return ((obj.get("choices") or [{}])[0].get("message")) or {} if isinstance(obj, dict) else {}


def _last_call_truncated(msg: dict) -> bool:
    """Is the LAST tool call in ``msg`` a FRAGMENT — arguments cut off mid-object?

    Checked on the RAW argument string, because ``_tool_calls`` parses leniently and turns an
    unparseable one into ``{}`` — indistinguishable from a call that legitimately takes no
    arguments. Raw is unambiguous: a real empty object is "{}", a truncated one is "{".

    Measured over every captured planner round that was cut off at the output cap and still carried
    tool calls (n=8): 5 end on a complete call, 3 on a fragment. So a cut-off reply is NOT
    automatically an unusable list — only the fragment is unusable."""
    tcs = msg.get("tool_calls") or []
    if not tcs:
        return False
    args = ((tcs[-1].get("function") or {}).get("arguments"))
    if isinstance(args, dict) or args in (None, ""):
        return False
    try:
        json.loads(args, strict=False)
        return False
    except (ValueError, TypeError):
        return True


def _tool_calls(msg: dict) -> list[tuple[str, str, dict]]:
    """`(call_id, name, args-dict)` for each tool call in an assistant message. Arguments
    that arrive as a JSON string are parsed leniently (control chars tolerated)."""
    out: list[tuple[str, str, dict]] = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args, strict=False)
            except (json.JSONDecodeError, ValueError):
                args = {}
        out.append((tc.get("id") or "", fn.get("name", ""), args if isinstance(args, dict) else {}))
    return out


def _calls_signature(calls: list[tuple[str, str, dict]]) -> str:
    """A stable signature for a round's tool calls, so an A→B→A gather loop is caught
    (full set, order-independent)."""
    return "|".join(sorted(f"{name}:{json.dumps(args, sort_keys=True)}" for _id, name, args in calls))
