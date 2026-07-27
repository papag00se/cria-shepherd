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

import json
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone

from . import massage, planner_tools, prompts, urlgrounding
from .classify import _task_key, latest_user_text
from .jsontext import extract_json_object, strip_think
from .plan import Plan, PlanItem

_CWD_RE = re.compile(r"<cwd>\s*(.*?)\s*</cwd>", re.S)
# When the gather runs to the round cap without the model submitting, offer submit_plan as its
# ONLY tool and read the call — retried in place a couple of times if it calls something else.
# (No "you've gathered enough, stop investigating" prose — that message was useless and jarring;
# the tool constraint is the whole instruction.)
_MAX_FINAL_RETRIES = 3
# The plan-submission tool. gemma-fable is hardwired to emit tool CALLS, so instead of asking for
# plain text (which it answers with a hallucinated `call:CreateNewProject{…}`), hand it ONE tool
# that IS the plan and read the steps from the call.
_SUBMIT_PLAN_TOOL = {"type": "function", "function": {
    "name": "submit_plan",
    "description": prompts.load_map("planner_tool_descs")["submit_plan"],
    "parameters": {"type": "object", "properties": {
        "steps": {"type": "array", "items": {"type": "string"}, "description": "the ordered steps"}},
        "required": ["steps"]}}}


def _steps_from_submit(msg: dict) -> list[str] | None:
    """Read the plan steps from a ``submit_plan`` tool call (native or recovered from the dialect).
    None if the model called something else or gave no steps."""
    for tc in msg.get("tool_calls") or []:
        if ((tc.get("function") or {}).get("name")) != "submit_plan":
            continue
        args = (tc.get("function") or {}).get("arguments")
        try:
            args = json.loads(args) if isinstance(args, str) else (args or {})
        except (json.JSONDecodeError, ValueError):
            args = {}
        steps = args.get("steps") if isinstance(args, dict) else None
        if isinstance(steps, list):
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
# The ``(?:_start|_end)?`` covers the LFM2/fabliq native pair ``<|tool_call_start|>`` / ``<|tool_call_end|>``
# (the LIVE model) — without it the plain regex matched gemma/qwen/hermes but MISSED the live model's own
# tokens, so its debris survived into a step (writeproxy._TC_DEBRIS already lists the full set; keep them in sync).
_DIALECT_MARKER = re.compile(
    r"<[|/]+(?:tool_call|channel|message|tool_response|think)(?:_start|_end)?[|/]*>"  # delimiter BEFORE the name
    r"|<(?:tool_call|channel|message|tool_response|think)(?:_start|_end)?[|/]+>"       # …or AFTER it
    r"|<\|\"\|>")
# NOTE the [|/]+ requirement: a real leaked control token ALWAYS carries a pipe/slash delimiter
# (<|tool_call|>, <tool_call|>). Matching a BARE <message>/<channel>/<think> also cut a legitimate plan
# step that merely NAMES that XML/HTML tag ("Handle the <message> element" → "Handle the"). Every
# writeproxy._TC_DEBRIS fixture still matches (all carry a delimiter); a sync test guards the pair.


_STEP_TEXT_KEYS = ("step", "text", "description", "action", "title", "task", "name", "content")


def _clean_step(text) -> str:
    """Trim a plan step to its action: cut at the first leaked dialect marker, strip a leading
    ordinal (``1.`` / ``2)`` — JSON-array items often embed their own number), and drop the JSON /
    array junk (``',]}`` etc.) that bleeds in when the model runs past the plan. Accepts a str OR a
    dict item — a model that wraps each array element in an object (``{"step": "…"}``) instead of a
    bare string; the field is extracted first, so the step text is never the dict repr ``{'step': …}``."""
    if isinstance(text, dict):
        for k in _STEP_TEXT_KEYS:
            v = text.get(k)
            if isinstance(v, str) and v.strip():
                return _clean_step(v)
        return ""
    s = str(text)
    m = _DIALECT_MARKER.search(s)
    if m:
        s = s[:m.start()]
    s = re.sub(r"^\s*\d+[.)]\s*", "", s)  # leading "1. " / "2) " embedded in a JSON list item
    return _strip_trailing_junk(s).strip()


_CLOSERS = {"}": "{", "]": "["}


def _strip_trailing_junk(s: str) -> str:
    """Drop the JSON/array junk that bleeds in when a model runs past the plan (``step",]}``) — but
    never a bracket the STEP ITSELF opened. A blanket ``[\\s'\"\\],}]+$`` strip ate the brace off a
    step ending in a path template, so ``GET /handles/{handle}`` reached the coder as
    ``GET /handles/{handle`` — and the coder follows the plan verbatim, so it builds that URL wrong.
    A closer is junk only when it is UNBALANCED; a matched one is part of the step's own text."""
    while s:
        c = s[-1]
        if c in " \t\r\n'\",":
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


def parse_steps(text: str) -> list[str] | None:
    """Extract plan steps, accepting a numbered/bulleted list (the prompt's ask, and what small models
    emit best), a JSON object whose step array is under ``steps``/``plan``/``items`` (models vary the
    key), OR — when that JSON is malformed by unescaped inner quotes — the salvaged array items. Returns
    None when none yield steps."""
    body = strip_think(text)
    obj = extract_json_object(body)
    if obj:
        for k in _STEP_KEYS:
            v = obj.get(k)
            if isinstance(v, list):
                steps = [c for s in v if (c := _clean_step(s))]
                if steps:
                    return steps
            elif isinstance(v, str) and v.strip():  # a numbered plan packed into one string value
                steps = _split_inline_numbered(v)
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


def reasoned_noise_indices(ask, task: str, steps: list[str]) -> set:
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
    ans = strip_think(ask(prompts.load("plan_noise_steps"), f"TASK:\n{task}\n\nPLAN:\n{plan_text}") or "").strip()
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
        kept = [s for i, s in enumerate(steps) if i not in drop]
        if drop and kept:
            rlog.emit("plan.noise_dropped", count=len(drop), level="info")
            steps = kept
        elif drop:
            rlog.emit("plan.noise_all_kept", count=len(drop), level="info")  # dropping would empty it
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
        code ACTS" path. Toolless, low max_tokens; the caller parses YES/NO or a bare token."""
        body = {"temperature": 0, "stream": False, "max_tokens": 2000,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}]}
        if self._role is not None:
            self._role.apply(body)
        try:
            msg = _assistant_message_obj(json.loads(self._provider.chat(body, rlog)))
        except Exception:  # noqa: BLE001 - any upstream/parse failure → let the caller fall back
            return ""
        content = strip_think(msg.get("content") or "")
        if self._role is not None:
            content = self._role.clean_content(content)
        return content.strip()

    def _reasoned_noise_indices(self, task: str, steps: list[str], rlog) -> set:
        """Indices of NOISE steps to DROP, JUDGED by the reasoner (see ``reasoned_noise_indices``). No
        reasoner configured → drop NOTHING (the plan is used as drafted); cria doesn't classify steps
        without a reasoner to judge them."""
        if self._role is None:
            return set()
        return reasoned_noise_indices(lambda sysp, usr: self._ask(sysp, usr, rlog), task, steps)

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
        messages: list[dict] = [{"role": "user", "content": seed}]
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
            while rounds < self._max_rounds:
                msg = self._reason(messages, rlog, research=True)
                if msg is None:
                    return None
                calls = _tool_calls(msg)
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
                looked = True
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
                for cid, name, args in calls:
                    result = planner_tools.execute_tool(name, args, cwd, self._search_key, recent_searches,
                                                        rlog, scratch=scratch, facts=facts)
                    rlog.emit("plan.gather", tool=name)
                    messages.append({"role": "tool", "tool_call_id": cid, "content": result})
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
        messages = messages + [{"role": "user", "content": prompts.render(
            "plan_evidence", facts=_facts_digest(facts), task=task)}] if facts else messages
        challenged = False  # an ungrounded-route plan is handed back at most ONCE (never wedge)
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
                bad = [] if challenged else urlgrounding.ungrounded_urls(
                    "\n".join(steps), _gather_evidence(messages))
                if bad:
                    challenged = True
                    rlog.emit("plan.submit_ungrounded", urls=",".join(bad))
                    messages = messages + [
                        {"role": "assistant", "content": msg.get("content") or None},
                        {"role": "user", "content": prompts.fill(
                            prompts.load_map("planner_steers")["submit_ungrounded"],
                            urls=", ".join(bad))}]
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
            self._role.apply(body)
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
            return _assistant_message_obj(completion)
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
