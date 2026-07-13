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

from . import massage, planner_tools, prompts
from .classify import _task_key, latest_user_text
from .jsontext import extract_json_object, strip_think
from .plan import Plan, PlanItem

_CWD_RE = re.compile(r"<cwd>\s*(.*?)\s*</cwd>", re.S)
_FORCE_PLAN = "You've gathered enough. Stop investigating and output ONLY the numbered plan now."
# Forced-plan retries IN PLACE (gather kept): the model is offered a submit_plan tool each time
# and its call is read; a couple of retries cover a stray call to something else.
_MAX_FORCE_RETRIES = 3
# The plan-submission tool. gemma-fable is hardwired to emit tool CALLS, so instead of asking for
# plain text (which it answers with a hallucinated `call:CreateNewProject{…}`), hand it ONE tool
# that IS the plan and read the steps from the call.
_SUBMIT_PLAN_TOOL = {"type": "function", "function": {
    "name": "submit_plan",
    "description": "Submit the final plan: a numbered list of small, concrete, verifiable steps "
                   "(one action per step) for the coder to execute.",
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
            out = [str(s).strip() for s in steps if str(s).strip()]
            if out:
                return out
    return None

# The planner prompt lives in cria/prompts/plan.txt (edit it there). It asks for a
# numbered LIST, not JSON: small local models emit a clean list far more reliably than
# strict JSON — demanding JSON makes some (e.g. Gemma) emit a bespoke tool call instead.

_MAX_STEPS = 12

# A numbered ("1." / "1)") or bulleted ("-" / "*" / "•") list line → its text.
_LIST_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+\S)")


def parse_steps(text: str) -> list[str] | None:
    """Extract plan steps, accepting EITHER a numbered/bulleted list (the prompt's ask,
    and what small models emit best) OR a JSON ``{"steps": [...]}`` object (still valid
    if a model chooses it). Returns None when neither yields steps."""
    body = strip_think(text)
    obj = extract_json_object(body)
    if obj and isinstance(obj.get("steps"), list):
        steps = [str(s).strip() for s in obj["steps"] if str(s).strip()]
        if steps:
            return steps[:_MAX_STEPS]
    steps = [m.group(1).strip() for line in body.splitlines() if (m := _LIST_LINE.match(line))]
    return steps[:_MAX_STEPS] or None


class Planner:
    def __init__(self, provider, model: str, *, role=None, search_key: str = "", max_gather_rounds: int = 12, clock=None) -> None:
        self._provider = provider  # an Upstream-like with .chat(body, rlog)
        self._model = model
        self._role = role  # LocalRole | None — the reasoner role's per-request sampling/reasoning
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
        self._retriable_failure = False
        steps = self._gather_and_plan(task, _extract_cwd(messages), rlog,
                                      prior_work=prior_work, rewrite_summary=rewrite_summary)
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
        plan = Plan(
            id=self._new_id(key),
            task=task,
            created=self._clock().isoformat(timespec="seconds"),
            items=[PlanItem(text=s) for s in steps],
        )
        rlog.emit("plan.drafted", id=plan.id, steps=len(steps))
        return plan

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
                "Continue and finish the remaining work described in the summary."
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
                msg = self._reason(messages, rlog, tools=True)
                if msg is None:
                    return None
                calls = _tool_calls(msg)
                if not calls:  # no tool call → the content IS the plan
                    return self._parse(msg, rlog)
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
                        messages.append({"role": "tool", "tool_call_id": cid, "content": (
                            f"[you already ran {name} with these exact arguments this gather — its "
                            "result is already above. Don't repeat it: use that result, investigate "
                            "something DIFFERENT, or if you have enough, output your plan.]")})
                    continue
                seen_sigs.add(sig)
                for cid, name, args in calls:
                    result = planner_tools.execute_tool(name, args, cwd, self._search_key, recent_searches, rlog, scratch=scratch)
                    rlog.emit("plan.gather", tool=name)
                    messages.append({"role": "tool", "tool_call_id": cid, "content": result})
            rlog.emit("plan.gather_cap", rounds=self._max_rounds)  # investigated to the cap
            return self._forced_plan(messages, rlog)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _forced_plan(self, messages: list[dict], rlog) -> list[str] | None:
        """Stop gathering, get the plan. This model (gemma-fable) is hardwired to emit TOOL CALLS
        — asked for plain text it answers with `call:Bash{…}`/`call:thought{…}` no matter what —
        so cria works WITH that: it offers a single `submit_plan(steps)` tool and reads the steps
        from the call. RETRY IN PLACE (the gather stays in ``messages``) rather than discarding it
        and re-gathering next turn (the amnesia loop) if the model calls something else."""
        convo = messages + [{"role": "user", "content": _FORCE_PLAN}]
        for attempt in range(_MAX_FORCE_RETRIES):
            msg = self._reason(convo, rlog, tools=False, plan_tool=True)
            if msg is None:
                self._retriable_failure = True  # transport/model error, not an unplannable task
                return None
            steps = _steps_from_submit(msg) or self._parse(msg, rlog)  # the tool call, else any text
            if steps:
                if attempt:
                    rlog.emit("plan.forced_recovered", attempt=attempt + 1)
                return steps[:_MAX_STEPS]
            # Called something OTHER than submit_plan (e.g. a hallucinated `CreateNewProject`) →
            # retry, gather intact. Log WHAT it called so the record shows it (not just "no plan").
            leaked = [((tc.get("function") or {}).get("name")) for tc in (msg.get("tool_calls") or [])]
            rlog.emit("plan.force_retry", attempt=attempt + 1, called=leaked or "(no tool call)")
        self._retriable_failure = True  # still no plan after retries — retriable, never poison-cache
        return None

    def _reason(self, messages: list[dict], rlog, *, tools: bool, plan_tool: bool = False) -> dict | None:
        body: dict = {
            "model": self._model,
            "stream": False,
            "temperature": 0,  # default; the reasoner role's config (cria.toml) overrides below
            # Cap the output so a reasoning model that fails to stop can't run to
            # context-length and hang the request.
            "max_tokens": 1536,
            "messages": [{"role": "system", "content": prompts.load("plan")}] + messages,
        }
        if self._role is not None:
            self._role.apply(body)
        if tools:
            body["tools"] = planner_tools.PLANNER_TOOLS
        elif plan_tool:
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
            rlog.emit("plan.error", level="warn", error=str(e))
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


def _extract_cwd(messages: list[dict]) -> str:
    """The workspace path a harness advertises in its environment preamble (e.g. Codex's
    ``<environment_context><cwd>…</cwd>``) so the planner's read-only shell / read_file run
    where the harness is, not where cria is. Falls back to ``.`` when no cwd is advertised —
    a harness that doesn't send one just runs relative to the invocation dir."""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        mt = _CWD_RE.search(c or "")
        if mt:
            return mt.group(1).strip()
    return "."


def _assistant_message_obj(obj) -> dict:
    return ((obj.get("choices") or [{}])[0].get("message")) or {} if isinstance(obj, dict) else {}


def _assistant_message(raw: bytes) -> dict:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
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
