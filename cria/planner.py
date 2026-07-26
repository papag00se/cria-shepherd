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
from dataclasses import replace
from datetime import datetime, timezone

from . import massage, planner_tools, prompts, searchloop
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
    s = re.sub(r"[\s'\"\],}]+$", "", s)  # trailing quote/comma/bracket/brace junk
    return s.strip()


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
    steps = []
    for line in body[m.end():].splitlines():
        if line.lstrip().startswith("]"):
            break
        im = _ARR_ITEM.match(line)
        if im and (c := _clean_step(im.group(1))):
            steps.append(c)
    return steps or None


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
    numbered = [c for line in lines if (m := _NUM_LINE.match(line)) and (c := _clean_step(m.group(1)))]
    if numbered:
        return numbered  # numbered plan → sub-bullets under a step are its DETAILS, not steps
    bullets = [c for line in lines if (m := _BULLET_LINE.match(line)) and (c := _clean_step(m.group(1)))]
    return bullets or None


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
    ans = strip_think(ask(prompts.load("plan_noise_steps"), f"TASK:\n{task}\n\nPLAN:\n{plan_text}") or "").strip()
    drop = _parse_step_numbers(ans, len(steps))
    # ENVIRONMENT/DEPENDENCY SETUP is asked as its OWN focused, TASK-LESS question. In the compound judge
    # above the weak model read the TASK + 4-category framing as a request to GENERATE a plan and answered
    # NONE, missing every "create a venv + pip install" step (its verbatim reasoning: "we haven't been
    # given any prior steps; we have to generate a plan from scratch?"). That step then trapped the run on
    # PEP-668. A single question about ONLY setup, over just the numbered steps with an explicit "do NOT
    # write a plan", removes the ambiguity — same STRICT parse (a bare number list, else drop nothing).
    setup_ans = strip_think(ask(prompts.load("plan_setup_steps"), plan_text) or "").strip()
    return drop | _parse_step_numbers(setup_ans, len(steps))


def _parse_step_numbers(ans: str, n_steps: int) -> set:
    """A reasoner verdict that must be a CLEAN 1-based step-number list (else the safe null: empty). Never
    scrape a digit out of prose — a model that wraps its answer in reasoning would have every number it
    MENTIONS (including endorsed steps) read as a deletion (principle #2: never delete correct content)."""
    if not re.fullmatch(r"[0-9][0-9,\s]*\.?", ans):   # NONE / prose / mixed → drop nothing
        return set()
    return {int(x) - 1 for x in re.findall(r"\d+", ans) if 0 <= int(x) - 1 < n_steps}


def reasoned_api_domain(ask, task: str) -> str:
    """The external API host the task requires — "" for none. The host the task LITERALLY names is GROUND
    TRUTH and WINS over a reasoner paraphrase (the reasoner was seen to drop `api.` from `api.handle.me`,
    steering the coder at the website); the reasoner supplies a domain only for a product-only mention the
    task didn't spell out. ``ask(system, user) -> str`` is the caller's one-shot reasoner call."""
    ans = ask(prompts.load("plan_names_api"), "TASK:\n" + task) or ""
    tok = ans.split()[0].strip("`'\".,;:()") if ans.split() else ""
    if not (tok and searchloop._looks_like_domain(tok)):
        return ""  # NONE or unparseable → no domain
    tok = tok.lower()
    literal = searchloop.task_api_domain(task)
    if literal and (literal == tok or literal.endswith("." + tok)):
        return literal   # the exact host the task named beats a registrable-domain paraphrase
    return tok


def reasoned_has_research(ask, task: str, steps: list[str], evidence: str = "") -> bool:
    """Whether the plan's API research is already SATISFIED — True unless a remaining step still CALLS the
    API with no earlier step (and no prior work in ``evidence``) reading its real source first. ``evidence``
    lets the LIVING re-derivation see that the coder already read the spec, so it doesn't re-prepend a
    research step forever. Unclear → True (never prepend a redundant step on a guess — silence over noise)."""
    if not steps:
        return True
    plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    user = f"TASK:\n{task}\n\nPLAN:\n{plan_text}"
    if evidence.strip():
        user += f"\n\nEVIDENCE:\n{evidence}"
    m = re.search(r"\b(YES|NO)\b", ask(prompts.load("plan_has_research"), user) or "", re.I)
    return m.group(1).upper() == "YES" if m else True


def reasoned_research_step_index(ask, task: str, steps: list[str]) -> int:
    """The 0-based index of the plan step that READS the API's real source (its spec/docs) to learn the real
    endpoint + fields — the research step to PIN — or -1 if no step does. Lets enforce_research_first pin the
    research step whether the PLANNER drafted it or cria injected it, so the verify ground-truth fast-path
    recognizes the research step either way (a planner-drafted research step was left unpinned → the fast-path
    never fired → the critic false-negatived it hundreds of times). Unclear / unparseable → -1 (pin nothing
    on a guess)."""
    if not steps:
        return -1
    plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    ans = strip_think(ask(prompts.load("plan_research_step"), f"TASK:\n{task}\n\nPLAN:\n{plan_text}") or "")
    m = re.search(r"\d+", ans)
    if not m:
        return -1
    n = int(m.group())
    return n - 1 if 1 <= n <= len(steps) else -1


def enforce_research_first(ask, task: str, steps: list[str]) -> tuple[list[str], str, int]:
    """ADDITIVE research-first invariant — Planner.plan_for only. When the task names an external API host,
    ensure exactly ONE research step exists AND identify it for PINNING, whether the PLANNER drafted it or
    cria must inject it. Returns (steps, domain-or-'', pin_index): pin_index is the index of the research step
    to pin — so the living re-derivation can't drop it AND the verify ground-truth fast-path recognizes it
    (a planner-drafted research step left unpinned meant the fast-path never fired and the critic
    false-negatived it) — or -1 when no host is named or no research step is warranted. NEVER deletes or
    rewrites a step."""
    domain = reasoned_api_domain(ask, task)
    if not (domain and steps):
        return steps, "", -1
    idx = reasoned_research_step_index(ask, task, steps)
    if idx >= 0:  # the planner already drafted a research step — PIN it, never add a redundant second one
        return steps, domain, idx
    # no step reads the real source — prepend cria's ONLY when a step actually codes against the API
    if reasoned_has_research(ask, task, steps):
        return steps, domain, -1   # nothing calls the API un-researched → no research step is warranted
    return [prompts.render("research_named_source", domain=domain)] + steps, domain, 0


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
        # RESEARCH-FIRST enforcement (ADDITIVE): when the task names an external API host, ensure exactly ONE
        # research step exists and PIN it — whether the PLANNER drafted its own "read the spec/docs" step or
        # cria has to prepend one (the coder learns the real endpoint + fields before any code depends on
        # them; the URL is the NAMED host's standard discovery path). The pin (below) is what lets the living
        # re-derivation (_replan_tail) keep it from being dropped/reworded AND lets the verify ground-truth
        # fast-path recognize it as the research step — so a planner-authored research step is no longer
        # invisible to the fast-path (which left it churning against the weak critic). Never deletes/rewrites.
        pin_idx, domain = -1, ""
        if self._role is not None:
            before_n = len(steps)
            steps, domain, pin_idx = enforce_research_first(
                lambda sysp, usr: self._ask(sysp, usr, rlog), task, steps)
            if domain and pin_idx >= 0:  # a new cria step was prepended, OR the planner's own step is pinned
                rlog.emit("plan.research_prepended" if len(steps) > before_n else "plan.research_pinned",
                          domain=domain, index=pin_idx, level="info")
        items = [PlanItem(text=s) for s in steps]
        if 0 <= pin_idx < len(items):  # PIN the research step (planner's own OR cria's)
            items[pin_idx].pinned = True
        plan = Plan(
            id=self._new_id(key),
            task=task,
            created=self._clock().isoformat(timespec="seconds"),
            items=items,
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
        # An ephemeral scratchpad the gather may WRITE to (persist + process fetched data across
        # rounds) — in cria's OWN tmp, never the workspace (no-pollution), torn down after.
        scratch = tempfile.mkdtemp(prefix="cria-gather-")
        try:
            for _round in range(self._max_rounds):
                msg = self._reason(messages, rlog, gather=True)  # gather tools + submit_plan
                if msg is None:
                    return None
                calls = _tool_calls(msg)
                if not calls:  # no tool call → the content IS the plan
                    return self._parse(msg, rlog)
                steps = _steps_from_submit(msg)  # the model ended the gather by SUBMITTING its plan
                if steps:
                    rlog.emit("plan.submitted", steps=len(steps))
                    return steps
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
                    result = planner_tools.execute_tool(name, args, cwd, self._search_key, recent_searches, rlog, scratch=scratch)
                    rlog.emit("plan.gather", tool=name)
                    messages.append({"role": "tool", "tool_call_id": cid, "content": result})
            rlog.emit("plan.gather_cap", rounds=self._max_rounds)  # investigated to the cap
            return self._final_plan(messages, rlog)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _final_plan(self, messages: list[dict], rlog) -> list[str] | None:
        """The gather hit the round cap without the model submitting. Offer ONLY submit_plan (the
        gather tools are gone), so its one move is to hand over the plan — no prose telling it to
        stop. RETRY IN PLACE (the gather stays in ``messages``) if it calls something else, rather
        than discarding it and re-gathering next turn (the amnesia loop)."""
        for attempt in range(_MAX_FINAL_RETRIES):
            msg = self._reason(messages, rlog, plan_only=True)
            if msg is None:
                self._retriable_failure = True  # transport/model error, not an unplannable task
                return None
            steps = _steps_from_submit(msg) or self._parse(msg, rlog)  # the tool call, else any text
            if steps:
                if attempt:
                    rlog.emit("plan.final_recovered", attempt=attempt + 1)
                return steps
            # Called something OTHER than submit_plan (e.g. a hallucinated `CreateNewProject`) →
            # retry. Log WHAT it called so the record shows it (not just "no plan").
            leaked = [((tc.get("function") or {}).get("name")) for tc in (msg.get("tool_calls") or [])]
            rlog.emit("plan.final_retry", attempt=attempt + 1, called=leaked or "(no tool call)")
        self._retriable_failure = True  # still no plan after retries — retriable, never poison-cache
        return None

    def _reason(self, messages: list[dict], rlog, *, gather: bool = False, plan_only: bool = False) -> dict | None:
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
        if gather:  # investigate OR submit — the model ends the gather by submitting, not by force
            body["tools"] = planner_tools.PLANNER_TOOLS + [_SUBMIT_PLAN_TOOL]
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
