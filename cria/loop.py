"""Phase 6 — the plan-driven loop. cria becomes an orchestrator: it drafts a plan,
hands the coder ONE item at a time (framed as if it were the whole task), lets the
harness run the coder's tools, and when the coder says "done" checks with the
reasoner before marking the item complete and moving on.

Owns no executors: cria never touches the workspace. The plan file is created and
updated by emitting a `shell` tool call the HARNESS runs. A shell tool is REQUIRED —
it's the primitive the loop needs for its plan file, its ground-truth probe, AND the
coder's file writes (the writeproxy lowers write_file → a shell command). A request
with no shell tool is declined (`drive` returns None → proxy), because the loop
literally can't execute anything without it — and harnesses send genuinely tool-less
turns (title/summarize) that misclassify as tasks. The loop keeps the harness's turn
alive by only ever returning a completion with a tool call until the plan is
exhausted; the final item's completion is the first bare answer the harness sees,
ending the turn.

Simplifications (flagged; both are refinements, not correctness holes):
* Coder turns are BUFFERED so cria can inspect tool-calls-vs-done before responding
  — no live token streaming *inside* the loop yet.
* The plan file is rewritten whole on each update (simple + idempotent).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from . import callcapture, indicators, massage, probegate, proberun, prompts, toolmenu
from .classify import _task_key, latest_user_text
from .jsontext import extract_json_object
from .plan import Plan, PlanItem
from .planner import _extract_cwd
from .planner_tools import normalize_search
from .shelltool import _CMD_FIELDS, find_shell_tool, shell_args
from .writeproxy import _WRITE_NAMES as writeproxy_names

# NOTE: the "accept + advance after N failed verifications" cap was REMOVED at the user's
# request — a step that fails verification is now re-nudged INDEFINITELY; it never advances
# unverified. A step advances only when it genuinely passes. This means a step the coder
# can't satisfy will loop forever (one harness turn per nudge) until it passes or the run is
# stopped externally. To restore the escape hatch: reintroduce a cap and gate the failure
# branches in _work / _verify_after_probe on `sess.verify_fails >= cap → _advance(ok=False)`.


# Output-truncation guard retry budget. After this many incremental-write re-prompts a write is
# still hitting the cap, so cria stops rewriting (each rewrite re-truncates at the same place) and
# refuses the partial. Matches codex-local's MAX_BAIL_RETRIES.
MAX_TRUNCATION_RETRIES = 3
# Rumination guard retry budget — how many times to re-prompt a reasoning-loop turn to refocus
# before accepting whatever it produced. Same MAX_BAIL_RETRIES ceiling.
MAX_RUMINATION_RETRIES = 3
# WHEEL-SPINNING trigger (operator, 2026-07-11; windowed 2026-07-12): the same file written this
# many times — ANY content — within the last WRITE_WINDOW forwarded calls → run the gate mid-work
# and INSERT the results into the coder's next turn. No done-claim needed, no judging — pure
# ground truth, aimed at the tiny-edit spiral: the file's indentation is wrong, and the model
# rewrites it ten times changing SOMETHING each time but never the fault, so content-hashing
# (the repetition trigger) can't see it and a consecutive streak undercounts it (reads/tests/
# other-file writes interleave). Byte-identical rewrites trip the (stricter, 3×) repetition
# redirect first; this is the varying-content tier.
WHEEL_SPIN_WRITES = 5
# REPETITION REDIRECT (operator, 2026-07-12): the same tool call BY NATURE — not by exact
# bytes; exact fingerprints were tried on the codex-local side and failed, because the model
# jitters one flag or word without changing what it's doing — REPEAT_FINGERPRINT_N times within
# the last REPEAT_WINDOW forwarded calls → run the gate for fresh ground truth, then the
# REASONER authors a redirect (codex-local's reasoned-guidance pattern: detect → ground truth →
# reason). Windowed, not consecutive-only, so interleaved loops (write, test, write, test —
# byte-identical writes) are caught. Nature-matching (the codex-local search-guard lesson):
# writes match on path+content (identical rewrite = repeat; NEW content = progress and RESETS
# the window, so a healthy edit→test→edit→test cycle never trips on its repeated test runs);
# everything else matches on a normalized word-set of its args, loosely, so `pytest -q` /
# `pytest -q --tb=short` count as the same hunt.
REPEAT_FINGERPRINT_N = 3
REPEAT_WINDOW = 12
# Writes are counted over a window sized to five full write→read→test cycles (3 calls per
# edit): the canonical tiny-edit spiral interleaves a cat and a pytest between edits, so five
# edits span 13 calls — a 12-call window missed the incident's exact shape by ONE, permanently
# (round 5). Sparser revisits (3+ calls between edits) still age out and stay silent.
WRITE_WINDOW = WHEEL_SPIN_WRITES * 3
# Tool names of the write class — their nature is path+content, and new content is progress.
_WRITE_TOOL_RE = re.compile(r"write|edit|patch|create|replace", re.I)
# Shell-command words that mutate the workspace: a shell call carrying one of these, with no
# match already in the window, is progress too (the apply_patch/tee equivalents of a write).
_MUTATOR_WORDS = frozenset({"apply_patch", "tee", "mv", "cp", "touch", "mkdir", "rm"})
# Probe re-issues after a history rewrite erased the result. A harness compacting EVERY turn
# would otherwise re-issue forever; past the cap the absent result falls back to fail-open (the
# pre-existing don't-wedge behavior).
MAX_PROBE_REISSUES = 2
# The completion briefing rides IN THE CONVERSATION (the plan-complete closing message), wrapped in
# this envelope — so the harness stores it, its compactor summarizes FROM it, and cria re-reads it
# from the history it's sent. No server-side copy of the summary. The envelope deliberately does
# NOT start with the indicator MARKER ("⟦cria⟧ "), so strip_history leaves it intact inbound.
BRIEFING_OPEN = "⟦cria:briefing⟧"
BRIEFING_CLOSE = "⟦/cria:briefing⟧"
# ONE FOLDER PER RUN (operator direction 2026-07-11): everything cria produces for a session —
# call captures, reasoning files, the plan mirror, the critic's verify dumps — lands under
# <runs_dir>/<session>/, keyed by the SAME session id the captures use. No more tying a
# plan-id-named file in one tree to a session-uuid folder in another.
_RUNS_DIR_DEFAULT = "~/.cria/calls"
# Tools whose truncation corrupts a file on disk (the writeproxy lowers their content verbatim).
# Every write route the trackers must see: the writeproxy's lowered names (write_file,
# create_file — import shared so they can't drift), plus the edit dialects massage leaves
# intact when the HARNESS advertises them (edit_file/str_replace), plus apply_patch (what
# massage lowers edits into otherwise). Round 5: create_file was missing — a varying-content
# create_file rewrite spiral was invisible to BOTH tiers.
_WRITE_TOOLS = tuple(dict.fromkeys(
    tuple(sorted(writeproxy_names)) + ("edit_file", "str_replace", "apply_patch")))


class Phase(Enum):
    WORK = auto()  # driving items
    DONE = auto()


@dataclass
class GuardState:
    """Cross-turn repetition / wheel-spin guard state: the ground-truth-probe round-trip plus the
    rolling action/write windows. Shared so ONE implementation of the guard drives both paths —
    ``PlanSession`` IS-A ``GuardState`` (the plan loop), and the plan-off direct path keeps a bare
    ``GuardState`` per session. The module-level ``guard_*`` functions operate on this state."""
    awaiting_probe: bool = False  # cria emitted a ground-truth probe; next request is its result
    probe_call_id: str = ""  # the id of the probe tool call, to find its result
    probe_reissues: int = 0  # probes re-issued after a history rewrite erased their result (capped)
    gate_plan: object = None  # probegate.GatePlan for the in-flight gate (maps result → reports)
    recent_writes: list = None  # rolling window: written path (or None) per forwarded tool call
    spin_path: str = ""  # the file whose windowed rewrite count tripped wheel-spinning
    spin_probe_due: bool = False  # wheel-spinning tripped → run the gate before the next coder turn
    spin_probe: bool = False  # the in-flight gate is a spin probe (insert results, don't judge)
    recent_actions: list = None  # rolling window of (seq, nature-signature) per forwarded call
    action_seq: int = 0  # forwarded-call counter — ages recent_actions entries out of the window
    repeat_action: str = ""  # human-readable description of the repeated action (for the reasoner)
    redirect_due: bool = False  # repetition tripped → gate + redirect before next coder turn
    redirect_probe: bool = False  # the in-flight gate feeds a reasoner-authored redirect (loop only)
    nudge_reason: str = ""  # a steer to hand the coder on its next work turn
    # Completion-gate-on-"done" state (plan-off path; the loop uses PlanSession's own fields):
    done_probe: bool = False  # a probe verifying a "done" claim is in flight
    pending_done: str = ""  # the coder's held "done" text, forwarded if the gate passes
    leg0_nudged: bool = False  # the no-tools act-first nudge fired once this session


@dataclass
class PlanSession(GuardState):
    plan: Plan = field(kw_only=True)  # required; kw_only so it may follow GuardState's defaulted fields
    phase: Phase = Phase.WORK
    summary: str = ""  # running summary of completed steps
    prior_work: str = ""  # earlier finished work (briefing re-read from history / harness-summary tail)
    verify_fails: int = 0
    step_tool_calls: int = 0  # coder tool calls forwarded THIS step (the changed-anything leg)
    leg0_nudged: bool = False  # the no-tools nudge fired once this step (bounds in-process recursion)
    last_gate_flag: str = ""  # previous gate's block-nudge, for convergence/stall detection
    gate_git: str = ""  # last gate's git-status hash (workspace-change signal across gates)
    pending_coder_text: str = ""  # the coder's "done" claim, held for the critic after the probe


class GuardStore:
    """Per-session GuardState for the plan-off path — the loop keeps its guard state inside its
    PlanSession, but the plan-off direct path is otherwise stateless, so it holds the cross-turn
    repetition/spin windows here (keyed by session, like the write-translation store)."""

    def __init__(self) -> None:
        self._m: dict[str, GuardState] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> GuardState:
        with self._lock:
            gs = self._m.get(key)
            if gs is None:
                gs = self._m[key] = GuardState()
            return gs


# GROUND-TRUTH gate: composed per verification by probegate.plan_gate (syntax floor +
# repo-discovered top probe + top TEST probe + git snapshot), run BY THE HARNESS, and
# interpreted through the ported probe modules. Replaces the old fixed Python-only
# _PROBE_COMMAND — the gate now adapts to whatever ecosystems the workspace actually has.


# How many session SHAPES to retain (conversation-root fingerprints, for harness-compaction
# detection). Cheap (a hash + an int each); evicted oldest-first.
_MAX_SHAPES = 256


class LoopStore:
    """The loop's server-side session state: live plans and each session's conversation-root
    SHAPE (structural harness-compaction detection + a one-bit `done` marker). DETECTION state
    only — the completion BRIEFING is never stored here; it rides in the conversation (embedded
    in the closing message) and is re-read from the history the harness sends back.

    ``state_path`` (optional) persists the shapes as one small JSON file so a cria restart
    doesn't orphan detection. Live ``PlanSession``s are deliberately NOT persisted (a Plan
    mid-flight has in-memory phases/flags; resuming one across a restart is future work,
    recorded in DEFERRALS.md)."""

    def __init__(self, state_path: str | None = None) -> None:
        self._sessions: dict[str, PlanSession] = {}
        # session key -> {"fp": sha1-of-root, "n": msg count, "pending": rewrite?, "done": completed a plan?}
        # DETECTION state only — the completion briefing itself is never stored server-side; it
        # rides in the conversation (the closing message) and is re-read from history.
        self._shapes: dict[str, dict] = {}
        self._state_path = Path(state_path).expanduser() if state_path else None
        self._lock = threading.Lock()
        self._load()

    def get(self, key: str) -> PlanSession | None:
        with self._lock:
            return self._sessions.get(key)

    def put(self, key: str, sess: PlanSession) -> None:
        with self._lock:
            self._sessions[key] = sess
            self._save_locked()

    def persist(self, key: str) -> None:
        """Re-save after in-place PlanSession mutations (step advanced, nudge recorded) — a cria
        restart mid-plan then RESUMES the plan instead of re-planning blind (the restart-amnesia
        bug: a fresh plan chose new filenames → duplicate near-identical files in the workspace)."""
        with self._lock:
            if key in self._sessions:
                self._save_locked()

    def drop(self, key: str) -> None:
        with self._lock:
            self._sessions.pop(key, None)
            self._save_locked()

    def mark_done(self, key: str) -> None:
        """Record that this session COMPLETED a plan — a one-bit detection signal (the briefing
        itself rides in the conversation, never server-side). A later post-compaction pure handoff
        on this session is then continued even when the classifier chokes on the summary text."""
        with self._lock:
            shape = self._shapes.get(key)
            if shape is not None and not shape.get("done"):
                shape["done"] = True
                self._save_locked()

    def shape_done(self, key: str) -> bool:
        with self._lock:
            shape = self._shapes.get(key)
            return bool(shape and shape.get("done"))

    def observe_shape(self, key: str, fp: str, n_messages: int) -> bool:
        """Record this session's conversation-root fingerprint; return True while a rewrite is
        PENDING — the root CHANGED under a stable session key (the harness REPLACED the history:
        a compaction, structurally — no phrase-matching). Turns merely appended keep the root.

        The signal is STICKY: a detected rewrite stays pending until ``clear_rewrite`` — so a
        turn that couldn't act on it (planner failed, non-task decline) doesn't consume it; the
        next turn still knows the history was rewritten."""
        if not fp:
            return False
        with self._lock:
            prev = self._shapes.get(key)
            changed = prev is not None and prev.get("fp") != fp
            pending = changed or bool(prev and prev.get("pending"))
            first_sight = prev is None
            self._shapes.pop(key, None)  # re-put refreshes recency
            self._shapes[key] = {"fp": fp, "n": n_messages, "pending": pending,
                                 "done": bool(prev and prev.get("done"))}  # done bit survives re-puts
            while len(self._shapes) > _MAX_SHAPES:
                self._shapes.pop(next(iter(self._shapes)))
            if first_sight or changed:  # persist only on root changes, not every turn
                self._save_locked()
        return pending

    def clear_rewrite(self, key: str) -> None:
        """The pending rewrite was ACTED on (continuation planned / probe re-issued / live turn
        processed) — stop flagging it."""
        with self._lock:
            shape = self._shapes.get(key)
            if shape and shape.get("pending"):
                shape["pending"] = False
                self._save_locked()

    def knows(self, key: str) -> bool:
        """True if this session has ANY history with the loop — a live plan or a recorded
        shape. The server keeps routing known sessions through the loop so a post-compaction
        continuation can't be lost to a mis-classified turn."""
        with self._lock:
            return key in self._sessions or key in self._shapes

    # ------------------------------------------------------------- persistence

    def _load(self) -> None:
        if self._state_path is None:
            return
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8"))
            shapes = state.get("shapes") if isinstance(state, dict) else None
            if isinstance(shapes, dict):
                self._shapes = {str(k): v for k, v in list(shapes.items())[-_MAX_SHAPES:]
                                if isinstance(v, dict) and isinstance(v.get("fp"), str)}
            sessions = state.get("sessions") if isinstance(state, dict) else None
            if isinstance(sessions, dict):
                for k, v in sessions.items():
                    sess = _session_from_dict(v)
                    if sess is not None:
                        self._sessions[str(k)] = sess
        except Exception:  # noqa: BLE001 — a corrupt/wrong-shape state file must NEVER block startup
            self._shapes, self._sessions = {}, {}

    def _save_locked(self) -> None:
        """Write the shapes atomically (tmp + rename). Caller holds the lock. DETECTION state
        only — briefings ride in the conversation, never in this file."""
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"shapes": self._shapes,
                                       "sessions": {k: _session_to_dict(v)
                                                    for k, v in self._sessions.items()}},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._state_path)
        except OSError:
            pass  # persistence is a nicety — never break the request path


@dataclass
class LoopContext:
    """What the loop needs from the outside — injected so it's testable."""

    planner: object  # .plan_for(messages, rlog) -> Plan | None
    coder_chat: object  # (body, rlog) -> bytes  (a buffered completion)
    reasoner_chat: object  # (body, rlog) -> bytes
    # No coder_model / reasoner_model: the loop's bodies carry no `model`, so the upstream fills the
    # server's loaded model (cria never pins an alias — the single-loaded-model posture).
    coder_role: object = None  # LocalRole | None — per-request sampling/reasoning for the coder
    reasoner_role: object = None  # LocalRole | None — for the critic
    # Root of the per-run folders (the SAME root the call captures use, so one session's
    # plan mirror, verify dumps, and captures share one folder). cria's OWN dir — NEVER the
    # workspace. None → _RUNS_DIR_DEFAULT; "" → don't write run artifacts (tests).
    runs_dir: str | None = None
    # Workspace root for the completion gate's READ-ONLY discovery (probegate.plan_gate). None →
    # derived per request from the harness env-context (<cwd>), falling back to ".". Probe
    # EXECUTION always rides the harness shell tool regardless — cria never runs the commands.
    workspace_root: str | None = None


class Loop:
    def __init__(self, ctx: LoopContext, store: LoopStore | None = None) -> None:
        self._ctx = ctx
        self._store = store or LoopStore()
        # Per-session serialization: ThreadingHTTPServer handles requests on parallel threads, and
        # drive() does get→mutate→put on PlanSession with model calls in between — two concurrent
        # requests for ONE session could double-plan or race the probe flags. One lock per session
        # key serializes them; different sessions still run fully in parallel.
        self._session_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _session_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._session_locks.get(key)
            if lock is None:
                if len(self._session_locks) > _MAX_SHAPES:  # bounded like the shapes it mirrors
                    self._session_locks.clear()  # only ever drops IDLE locks in practice (harnesses serialize turns)
                lock = self._session_locks.setdefault(key, threading.Lock())
            return lock

    def has_session(self, key: str) -> bool:
        """True if a plan is IN FLIGHT for this key. The server uses this to keep driving the loop
        even on a turn the classifier reads as a 'question': a tool RESULT coming back mid-plan (or
        the model's own continuation) routinely classifies as non-task, and gating the loop on
        per-turn classification abandons the in-progress plan → 'it stopped after a command ran'.
        Classification gates only whether to START a new plan, never whether to CONTINUE one."""
        return self._store.get(key) is not None

    def knows_session(self, key: str) -> bool:
        """True if the loop has ANY memory of this session — live plan, completed briefing, or a
        recorded conversation shape. The server routes known sessions through ``drive`` so that a
        post-compaction continuation (whose summary text classifies as anything at all) still
        reaches the loop's structural rewrite detection instead of being proxied blind."""
        return self._store.knows(key)

    def drive(self, body: dict, session_key: str, classification, rlog) -> dict | None:
        """Return the completion (OpenAI dict) cria should send, or ``None`` to fall
        through to the normal proxy (not a plan-driven task)."""
        with self._session_lock(session_key):
            out = self._drive_locked(body, session_key, classification, rlog)
            self._store.persist(session_key)  # durable plan progress → restarts RESUME, not re-plan
            if out is not None:
                # The loop's synthesized completions carry only object+choices; a plain
                # /v1/chat/completions client (non-Codex) needs a well-formed envelope. Codex's
                # Responses adapter rebuilds its own, so this is for the direct chat clients.
                out.setdefault("id", f"chatcmpl-{uuid.uuid4().hex}")
                out.setdefault("created", int(time.time()))
                out.setdefault("model", body.get("model") or "")
            return out

    def _drive_locked(self, body: dict, session_key: str, classification, rlog) -> dict | None:
        messages = body.get("messages", [])
        # The loop can only run a coding task when the harness will RUN tools for it. The shell tool
        # is the primitive it needs — for its plan file, for the ground-truth probe, AND for the
        # coder's file writes (the writeproxy lowers write_file → a shell command, so NO shell tool =
        # no writes at all). Harnesses (Codex) also send genuinely tool-less requests — title /
        # summarize turns — that can classify as 'task' but aren't drivable. Decline → proxy; a LIVE
        # plan is NOT dropped, so the next tool-bearing turn resumes it (has_session keeps it alive).
        if find_shell_tool(body.get("tools")) is None:
            live = self._store.get(session_key) is not None
            rlog.emit("loop.no_shell_tool", level="info", deferred=live)
            return None
        # HARNESS-COMPACTION detection, structural (no phrase-matching): the session key (a header /
        # Codex's prompt_cache_key) is stable across a compaction, but compaction REPLACES the
        # conversation root — the first real user message becomes the harness's summary. So a
        # changed root under a stable key = the history was rewritten. Normal turns only append.
        # ONLY content-independent (`sid:`) keys can detect this: the `task:` fallback key derives
        # from the root, so its shapes/briefings are skipped entirely (see _stable_session — a
        # briefing under a task-text hash would leak into unrelated same-prompt conversations).
        stable = _stable_session(session_key)
        root_text, root_fp = _history_root(messages)
        rewritten = stable and self._store.observe_shape(session_key, root_fp, len(messages))
        sess = self._store.get(session_key)
        if rewritten:
            rlog.emit("loop.history_rewritten", live=sess is not None, n_messages=len(messages))

        if sess is None:
            # The completion briefing rides IN THE CONVERSATION (embedded in the closing message,
            # see _closing) — cria re-reads it from the history the harness sends back. Nothing is
            # stored server-side; the harness owns the transcript, cria owns the content.
            briefing = _briefing_from_history(messages)
            # A rewrite is a CONTINUATION only as a pure handoff — the summary IS the latest user
            # text (the harness replaced history, the user typed nothing new). Then a completed
            # plan on record (the shape's `done` bit — the briefing itself was likely folded into
            # the harness summary) proves the session was a task, and the classifier's opinion of
            # the summary text (unparseable half the time) is ignored. But when the user DID type
            # a new ask after the compaction, the classifier judged THAT text — respect it: a
            # question stays a question (proxied), never hijacked into a plan.
            pure_handoff = rewritten and latest_user_text(messages).strip() == root_text.strip()
            was_task = bool(briefing) or self._store.shape_done(session_key)
            classified_task = classification is not None and classification.engagement == "task"
            if rewritten and ((was_task and pure_handoff) or classified_task):
                # Post-compaction continuation: plan the REMAINING work from the harness's summary
                # (the new conversation root) via the rewrite frame — never as a fresh task, and
                # never stacking cria's own briefing on top of the harness summary (two summaries
                # drowned the planner → the placeholder plan).
                plan = self._ctx.planner.plan_for(messages, rlog, rewrite_summary=root_text)
                if plan is None:
                    return None  # rewrite stays PENDING (sticky) — the next turn can still continue
                # The coder's protected prior-work context: cria's own briefing when we have one
                # (compact, focused); else the harness summary TAIL, clipped — summaries put the
                # current state / remaining work at the END, so the head is the droppable part.
                sess = PlanSession(plan=plan, prior_work=briefing or _clip_tail(root_text, 4000))
                self._store.put(session_key, sess)
                self._store.clear_rewrite(session_key)  # acted on it
                rlog.emit("loop.start", id=plan.id, steps=len(plan.items), continued=True, rewritten=True)
                self._persist_plan(plan, rlog)
            else:
                if classification is None or classification.engagement != "task":
                    return None  # a pending rewrite (if any) stays pending for a later task turn
                # A follow-up on a FINISHED session starts from the completion-compaction of the
                # prior plan (see loop.done), so the planner isn't blind to what it already built —
                # it plans the new ask ON TOP of the done work, not from the latest sentence.
                plan = self._ctx.planner.plan_for(messages, rlog, prior_work=briefing)
                if plan is None:
                    return None
                sess = PlanSession(plan=plan, prior_work=briefing)
                self._store.put(session_key, sess)
                rlog.emit("loop.start", id=plan.id, steps=len(plan.items), continued=bool(briefing))
                self._persist_plan(plan, rlog)  # mirror to cria's OWN dir (never the workspace)
                # drive straight into the first item — cria's scratch stays out of the project

        if sess.awaiting_probe:  # the ground-truth probe we emitted last turn has now run
            sess.awaiting_probe = False
            out = self._verify_after_probe(sess, session_key, body, rlog, rewritten=rewritten)
            self._store.clear_rewrite(session_key)  # consumed (probe re-issued or judged)
            return out

        self._store.clear_rewrite(session_key)  # live session: framing is rebuilt each turn anyway
        return self._work(sess, session_key, body, rlog)

    # ------------------------------------------------------------------ work

    def _work(self, sess: PlanSession, key: str, body: dict, rlog) -> dict:
        item = sess.plan.current()
        if item is None:  # every step done
            sess.phase = Phase.DONE
            sess.plan.status = "done"
            # Completion compaction: summarize the FINISHED work into a briefing and embed it in
            # the CLOSING MESSAGE — the briefing rides in the conversation (the harness stores it,
            # its compactor summarizes from it, cria re-reads it from history on a follow-up).
            # Never stored server-side; no cross-conversation leak possible. Only the one-bit
            # `done` marker lands in the shape (stable keys), for the post-compaction bypass.
            briefing = self._compact_done(sess, body, rlog)
            if _stable_session(key):
                self._store.mark_done(key)
            self._store.drop(key)
            rlog.emit("loop.done", id=sess.plan.id)
            return _completion_final(self._closing(sess, briefing))

        idx = sess.plan.items.index(item) + 1
        total = len(sess.plan.items)
        # Repetition/wheel-spin intervention (shared with the plan-off path): emit a ground-truth
        # probe now, or park a canned steer in sess.nudge_reason for the framing below.
        intervention = guard_intervene(sess, body, rlog, step=idx, workspace_root=self._ctx.workspace_root)
        if intervention is not None:
            return intervention
        framed = dict(body)
        framed.pop("model", None)  # no alias — the upstream fills the server's loaded model
        framed["stream"] = False
        msgs = _frame_for_item(body.get("messages", []), item.text, sess.summary, idx, total,
                               prior_work=sess.prior_work, tools=body.get("tools"))
        if sess.nudge_reason:  # re-driving after a failed check → tell the coder what's still wrong
            msgs = msgs + [{"role": "user", "content": prompts.render("nudge", reason=sess.nudge_reason)}]
            sess.nudge_reason = ""
        framed["messages"] = msgs
        if self._ctx.coder_role is not None:  # the coder role's sampling/reasoning from cria.toml
            self._ctx.coder_role.apply(framed)
        rlog.emit("loop.item", step=idx, total=total, text=item.text)

        rlog.phase = f"coder-s{idx}"  # label the call capture with the role + step
        coder = massage.apply(_parse_completion(self._ctx.coder_chat(framed, rlog)), framed.get("tools"), rlog)
        coder = self._guard_rumination(coder, framed, idx, rlog)  # reasoning-loop → refocus, don't accept empty
        coder = self._guard_truncation(coder, framed, idx, rlog)  # cut-off write → incremental, don't ship partial
        _strip_completion_banners(coder)  # scrub cria's own banners the coder parroted (both
        #   forwarded to the harness AND captured below as pending_coder_text for the critic)
        if self._ctx.coder_role is not None:  # strip leaked reasoning from the coder's content when off
            _clean_completion(coder, self._ctx.coder_role)
        if _has_tool_calls(coder):
            sess.step_tool_calls += 1  # the coder ACTED this step (the did-real-work leg's signal)
            self._track_repetition(sess, coder, idx, rlog)
            self._track_write_streak(sess, coder, idx, rlog)
            return coder  # coder is acting → forward; the harness runs it, then loops back here

        # coder produced no tool call → it thinks the step is done.
        # LEG 0 (ported from codex-local's completion gate): a "done" with ZERO tool calls this
        # step did nothing — nudge it to act before spending probe round-trips. (codex-local's
        # leg counts FILES MODIFIED in the active turn; cria's steps legitimately include
        # verification-only work, so the cria adaptation counts ANY tool activity this step.)
        if sess.step_tool_calls == 0 and not sess.leg0_nudged:
            sess.leg0_nudged = True  # once per step; a coder that STILL won't act falls to the gate
            sess.verify_fails += 1
            rlog.emit("loop.step_incomplete", step=idx, reason="no tools used", attempt=sess.verify_fails)
            return self._renudge(sess, key, body,
                                 "you used no tools and changed nothing this step — do the step's "
                                 "work with tool calls first, then report", rlog)
        # LEG 2 setup: compose the completion gate (syntax floor + top probe + top TEST probe,
        # discovered fresh from the workspace) as ONE shell command the harness runs.
        probe_tc = self._gate_op(body, sess, rlog)
        if probe_tc is not None:
            sess.awaiting_probe = True
            sess.probe_call_id = probe_tc["id"]
            sess.pending_coder_text = _completion_text(coder)
            return _completion_toolcalls([probe_tc], note=f"verifying step {idx}/{total} — running checks")
        # no shell tool → cannot probe; still ground the critic in the coder's own tool output
        evidence = _coder_evidence(body.get("messages", []), None)
        ok, reason = self._verify(item.text, _completion_text(coder), "", evidence, rlog, idx=idx, total=total, key=key)
        if ok:  # advance ONLY on a genuine pass — no fail cap (re-nudge forever otherwise)
            return self._advance(sess, key, body, idx, total, ok, rlog, reason)
        sess.verify_fails += 1
        rlog.emit("loop.step_incomplete", step=idx, reason=reason, attempt=sess.verify_fails)
        return self._renudge(sess, key, body, reason, rlog)

    def _guard_rumination(self, coder: dict, framed: dict, idx: int, rlog) -> dict:
        """The loop's coder step — delegates to the shared :func:`guard_rumination` with the
        loop's watched coder call, so the plan-off proxy path runs the IDENTICAL guard."""
        return guard_rumination(coder, framed, self._ctx.coder_chat, rlog, step=idx, phase=f"coder-s{idx}")

    def _guard_truncation(self, coder: dict, framed: dict, idx: int, rlog) -> dict:
        """The loop's coder step — delegates to the shared :func:`guard_truncation`."""
        return guard_truncation(coder, framed, self._ctx.coder_chat, rlog, step=idx, phase=f"coder-s{idx}")

    def _verify_after_probe(self, sess: PlanSession, key: str, body: dict, rlog, *, rewritten: bool = False) -> dict:
        """The ground-truth probe cria emitted last turn has run — read its result and
        gate the step on it: a failing probe hands the coder the real error; a passing
        probe goes to the critic (grounded in the probe, not the coder's prose).

        ``rewritten``: the harness REPLACED the history this turn (compaction), which can erase
        the probe's tool result. Normally an absent result is fail-open (the harness didn't run
        it — don't wedge). But when the history was rewritten, the result wasn't declined, it was
        LOST — so re-issue the probe instead of letting the step pass with no ground truth."""
        item = sess.plan.current()
        if item is None:
            return self._work(sess, key, body, rlog)
        idx = sess.plan.items.index(item) + 1
        total = len(sess.plan.items)
        probe = _read_tool_result(body.get("messages", []), sess.probe_call_id)
        if not probe.strip() and rewritten and sess.probe_reissues < MAX_PROBE_REISSUES:
            probe_tc = self._gate_op(body, sess, rlog)
            if probe_tc is not None:
                sess.awaiting_probe = True
                sess.probe_call_id = probe_tc["id"]
                sess.probe_reissues += 1
                rlog.emit("loop.probe_reissued", step=idx, attempt=sess.probe_reissues)
                return _completion_toolcalls([probe_tc], note=f"re-running checks for step {idx}/{total} (history was compacted)")
        sess.probe_reissues = 0  # a result (or the capped fallback) resolves the streak

        # Interpret the gate output through the ported probe modules (floor + probes + git).
        outcome = probegate.interpret_gate(sess.gate_plan, probe) if sess.gate_plan is not None \
            else probegate.GateOutcome(ran=False)
        # Guard-probe result (repetition redirect / wheel-spin ground truth) — shared with the
        # plan-off path via guard_probe_steer; the loop supplies its reasoner to author the redirect.
        steer = guard_probe_steer(sess, body, rlog, step=idx, author=self._author_redirect)
        if steer is not None:
            return self._renudge(sess, key, body, steer, rlog)
        if not outcome.ran:
            # The script never ran (harness declined / no markers). Don't wedge — the pre-existing
            # fail-open: the critic still judges, told explicitly that no diagnostics ran.
            rlog.emit("loop.probe", step=idx, passed=True, gate_ran=False)
            digest = "SYNTAX FLOOR: did not run\nPROBES: none ran — the gate command produced no output."
            evidence = _coder_evidence(body.get("messages", []), sess.probe_call_id)
            ok, reason = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key)
            if ok:
                return self._advance(sess, key, body, idx, total, ok, rlog, reason)
            sess.verify_fails += 1
            rlog.emit("loop.step_incomplete", step=idx, reason=reason, attempt=sess.verify_fails)
            return self._renudge(sess, key, body, reason, rlog)

        # TRUTH CAPTURE (ported): every gate run is auditable — a silent pass is not a pass.
        nudge = proberun.completion_block_nudge(outcome.report)
        rlog.emit("loop.gate",
                  probes_run=len(outcome.report.results),
                  commands=[" ".join(c.command) for c in outcome.report.selected],
                  findings=sum(len(r.findings) for r in outcome.report.results),
                  floor_clean=proberun.syntax_floor_clean(outcome.report), blocked=nudge is not None)
        # Convergence signal (ported): the SAME flagged issues twice = the model is stuck, not
        # converging. codex-local ACCEPTS at that point with an UNRESOLVED banner; cria's operator
        # chose no-cap (a step never advances unverified), so a stall is LOGGED loudly instead.
        if nudge and nudge == sess.last_gate_flag:
            rlog.emit("loop.gate_stalled", level="warning", step=idx)
        sess.last_gate_flag = nudge or ""
        sess.gate_git = outcome.git_state
        rlog.emit("loop.probe", step=idx, passed=nudge is None)

        if nudge is not None:  # GROUND TRUTH: floor or probes failed → the exact file:line errors
            sess.verify_fails += 1
            rlog.emit("loop.step_incomplete", step=idx, reason="probe failed", attempt=sess.verify_fails)
            return self._renudge(sess, key, body, _clip_tail(nudge, 1800), rlog)

        digest = proberun.completion_probe_digest(outcome.report)
        evidence = _coder_evidence(body.get("messages", []), sess.probe_call_id)
        ok, reason = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key)  # grounded in the coder's own runs
        if ok:  # advance ONLY on a genuine pass — no fail cap
            return self._advance(sess, key, body, idx, total, ok, rlog, reason)
        sess.verify_fails += 1
        rlog.emit("loop.step_incomplete", step=idx, reason=reason, attempt=sess.verify_fails)
        return self._renudge(sess, key, body, reason, rlog)

    def _advance(self, sess: PlanSession, key: str, body: dict, idx: int, total: int, ok: bool, rlog, reason: str = "") -> dict:
        """Mark the current step done (verified or accepted-unverified), update the plan
        file through the harness, and move on."""
        item = sess.plan.current()
        item.done = True
        # A CLEAN status only — never the coder's raw output. The coder's text is
        # unbounded prose (and small models parrot cria's own banners back), which is
        # what leaked "logs" into the plan file. The step line already says what was done.
        item.note = "verified" if ok else "accepted unverified"
        if not ok:  # remember WHY, for the honest closing (not written to the plan file)
            item.fail_reason = _clip(reason, 200) or "its checks did not pass"
        sess.summary = _extend_summary(sess.summary, idx, item.text)
        sess.verify_fails = 0
        sess.pending_coder_text = ""
        sess.step_tool_calls = 0   # fresh step, fresh did-real-work signal
        sess.leg0_nudged = False
        sess.recent_writes, sess.spin_path = [], ""
        sess.spin_probe_due = False
        sess.recent_actions = []
        sess.redirect_due = False
        sess.last_gate_flag = ""   # convergence tracking is per step
        rlog.emit("loop.step_done", step=idx, verified=ok, accepted_unverified=not ok)
        self._persist_plan(sess.plan, rlog)  # refresh cria's own plan mirror; advance in-memory
        return self._work(sess, key, body, rlog)

    def _renudge(self, sess: PlanSession, key: str, body: dict, reason: str, rlog) -> dict:
        """A step failed its check → re-drive the coder on THIS step with the concrete
        reason, going back through `_work` so the SAME invariant holds: the coder's fix
        (a tool call) is forwarded, or — if it answers with prose — a fresh ground-truth
        probe is emitted. It NEVER returns a bare/prose completion, which would end the
        harness turn (stopping the session) and render as an empty ⟦cria⟧ line."""
        sess.nudge_reason = reason
        return self._work(sess, key, body, rlog)

    def _track_repetition(self, sess: PlanSession, coder: dict, idx: int, rlog) -> None:
        """The loop's coder step — delegates to the shared :func:`guard_track_repetition` so the
        plan-off path runs the IDENTICAL detection."""
        guard_track_repetition(sess, coder, rlog, step=idx)

    def _author_redirect(self, sess: PlanSession, outcome, body: dict, rlog) -> str:
        """The reasoned redirect (codex-local's reasoned-guidance pattern): hand the reasoner the
        step, the REPEATED ACTION, its recent tool results, and the fresh probe findings; it
        authors the coder's next instruction. Falls back to a canned redirect when the reasoner
        produces nothing — a stuck coder must never be left without a steer."""
        item = sess.plan.current()
        step_text = item.text if item is not None else sess.plan.task
        if outcome.ran:
            findings = proberun.completion_block_nudge(outcome.report)
            # a FACT for the reasoner, not an inference: it sees the recent tool results (which
            # reveal whether the repeats hit the same or different targets) and decides.
            truth = findings or "the repo's checks (lint + type-check + syntax) all PASS — no error-class findings"
        else:
            truth = "(the checks could not run)"
        evidence = _coder_evidence(body.get("messages", []), sess.probe_call_id)
        user = (f"STEP THE CODER IS ON:\n{step_text}\n\n"
                f"THE ACTION IT KEEPS REPEATING ({REPEAT_FINGERPRINT_N}x):\n{sess.repeat_action}\n\n"
                f"ITS RECENT TOOL RESULTS:\n{evidence or '(none)'}\n\n"
                f"GROUND TRUTH FROM THE REPO'S CHECKS:\n{_clip_tail(truth, 1200)}\n\n"
                "Write the redirect now.")
        text = self._summarize(prompts.load("redirect"), user, rlog, reasoning_off=False)
        if not text:
            text = self._summarize(prompts.load("redirect"), user, rlog, reasoning_off=True)
        if text:
            return _clip(text, 1200)
        # Reasoner unavailable → the SAME canned redirect the plan-off path uses (one steer text).
        return guard_canned_redirect(sess, outcome)

    def _track_write_streak(self, sess: PlanSession, coder: dict, idx: int, rlog) -> None:
        """The loop's coder step — delegates to the shared :func:`guard_track_write_streak`."""
        guard_track_write_streak(sess, coder, rlog, step=idx)

    def _gate_op(self, body: dict, sess: PlanSession, rlog) -> dict | None:
        """The loop's completion gate — delegates to the shared :func:`guard_gate_op`, passing the
        configured workspace root."""
        return guard_gate_op(sess, body, rlog, workspace_root=self._ctx.workspace_root)

    # ------------------------------------------------------------------ helpers

    def _verify(self, item: str, coder_text: str, probe: str, evidence: str, rlog,
                *, idx: int = 0, total: int = 0, key: str = "") -> tuple[bool, str]:
        # System instruction: cria/prompts/verify.txt. User message (the step + real
        # ground truth): assembled from the labels in cria/prompts/verify_user.txt.
        system = prompts.load("verify")
        labels = prompts.load_map("verify_user")
        parts = [prompts.fill(labels["step"], step=item)]
        if evidence:  # what the coder's OWN tools returned — real ground truth, not a claim
            parts.append(prompts.fill(labels["evidence"], evidence=_clip(evidence, 900)))
        if probe:
            parts.append(prompts.fill(labels["probe"], probe=_clip(probe, 900)))
        parts.append(prompts.fill(labels["summary"], coder_summary=_clip(coder_text, 800)))
        user = "\n\n".join(parts)

        # First pass uses the reasoner role AS CONFIGURED (reasoning may be ON → a considered
        # judgment). If that yields no parseable verdict, retry with reasoning forced OFF: a
        # verdict is a one-line classification, and a reasoning model under the max_tokens cap
        # can burn its whole budget THINKING and never emit the closing JSON — which used to
        # fall through to a silent DONE. Reasoning-off makes it answer the JSON directly.
        obj = self._verdict(system, user, rlog, reasoning_off=False)
        if obj is None:
            rlog.emit("loop.verify_retry", level="info", reason="no parseable verdict; retry reasoning-off")
            obj = self._verdict(system, user, rlog, reasoning_off=True)

        if obj is None:
            # FAIL CLOSED. A step must never pass on the verifier's SILENCE — an unreadable or
            # failed verdict is not evidence of completion. Treat it as not-done so the loop
            # re-nudges; if it never verifies, _closing reports it honestly as accepted-unverified.
            reason = "unverified (no parseable verdict)"
            _dump_verify(self._run_dir(rlog), key, idx, total, item, system, user, False, reason)
            return False, reason
        done, reason = bool(obj.get("done")), _clip(str(obj.get("reason", "")), 200)
        # Dump the EXACT context the critic judged on — so a human can see what it saw.
        _dump_verify(self._run_dir(rlog), key, idx, total, item, system, user, done, reason)
        return done, reason

    def _verdict(self, system: str, user: str, rlog, *, reasoning_off: bool) -> dict | None:
        """One critic call → the parsed verdict dict, or None if the model produced no
        parseable JSON (or the call failed). `reasoning_off` forces enable_thinking=false so a
        reasoning model can't exhaust its token budget before emitting the verdict."""
        body = {
            "stream": False,
            "temperature": 0,  # default; the reasoner role's config (cria.toml) overrides below
            # Bound the output: the verdict is a one-line JSON. Without a cap a reasoning
            # model that fails to stop generates tens of thousands of tokens and HANGS the loop.
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        role = self._ctx.reasoner_role
        if reasoning_off:
            role = replace(role, reasoning="off") if role is not None else None
        if role is not None:
            role.apply(body)
        elif reasoning_off:  # no role configured, but still force the think block off
            body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        try:
            rlog.phase = "critic" + ("-noreason" if reasoning_off else "")
            vtext = _completion_text(_parse_completion(self._ctx.reasoner_chat(body, rlog)))
            if role is not None:
                vtext = role.clean_content(vtext)  # drop leaked reasoning when off
            return extract_json_object(vtext) or None
        except Exception as e:
            rlog.emit("loop.verify_error", level="warn", error=str(e))
            return None

    def _persist_plan(self, plan: Plan, rlog) -> None:
        """Mirror the plan markdown to cria's OWN state dir (`~/.cria/plans/<id>.md`) for human
        visibility — NEVER into the workspace. cria used to shell a `.cria/<id>.md` write into the
        project; the coder then found it via `ls`, `cat`'d cria's orchestration state, and imitated
        it (naming files after cria). cria owns `~/.cria` and writes there directly (like its logs /
        captures), so its scratch never appears in — or leaks into — the user's project. Best-effort:
        the loop drives from the in-memory plan; this file is a convenience, never load-bearing."""
        d = self._run_dir(rlog)
        if d is None:
            return
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / f"plan-{plan.id}.md").write_text(plan.to_markdown(), encoding="utf-8")
        except OSError as e:
            rlog.emit("loop.plan_persist_error", level="info", error=str(e))

    def _run_dir(self, rlog) -> Path | None:
        """This run's single artifact folder: <runs_dir>/<session>/ — the SAME folder the call
        captures use (same root, same session id), so everything for one run lives together."""
        raw = self._ctx.runs_dir
        target = _RUNS_DIR_DEFAULT if raw is None else raw
        if not target:  # explicitly disabled (tests)
            return None
        session = getattr(rlog, "session", None)
        # SAME folder name the captures use (callcapture.session_dirname) — <timestamp>-<session>
        # — so a run's plan mirror, verify dumps, and call captures all land together.
        return Path(target).expanduser() / callcapture.session_dirname(session)

    def _compact_done(self, sess: PlanSession, body: dict, rlog) -> str:
        """Compact a FINISHED plan into a work-done briefing (the reasoner), so a follow-up prompt
        on this session starts from a clean, accurate context. Focus is the completed state — files
        and their purpose, how it runs/tests, key facts — not narration or next steps. Grounded in
        the actual coder actions (from the transcript) + the plan, so it names real files, not
        guesses. Best-effort: on any failure, fall back to the running per-step summary / checklist.
        A prior session summary is threaded in so a chain of follow-ups keeps ONE cumulative briefing."""
        checklist = "\n".join(
            f"{i + 1}. [{'done' if it.done else 'incomplete'}"
            f"{'' if it.note == 'verified' or not it.done else ', UNVERIFIED'}] {it.text}"
            for i, it in enumerate(sess.plan.items)
        )
        log = _work_log(body.get("messages", []))
        prior = f"EARLIER IN THIS SESSION:\n{sess.prior_work}\n\n" if sess.prior_work else ""
        user = (
            f"{prior}TASK COMPLETED:\n{sess.plan.task}\n\n"
            f"PLAN (with status):\n{checklist}\n\n"
            f"WORK LOG (the coder's actual actions and their results):\n{log or '(no tool activity captured)'}\n\n"
            "Produce the completed-work summary now."
        )
        system = prompts.load("done_summary")
        # First pass with the reasoner AS CONFIGURED. If it yields no text — a reasoning model can
        # burn the whole max_tokens budget THINKING and emit an empty content (the observed
        # loop.compact_empty) — retry with reasoning forced OFF: a briefing is extraction, not
        # judgment, so reasoning-off answers directly instead of ruminating past the cap.
        text = self._summarize(system, user, rlog, reasoning_off=False)
        if not text:
            text = self._summarize(system, user, rlog, reasoning_off=True)
        if text:
            rlog.emit("loop.compacted", id=sess.plan.id, chars=len(text))
            return text
        rlog.emit("loop.compact_empty", level="warn", id=sess.plan.id)
        # Fallback: the running per-step summary (or the bare checklist) still grounds a follow-up.
        return (sess.summary or checklist).strip()

    def _summarize(self, system: str, user: str, rlog, *, reasoning_off: bool) -> str:
        """One completion-compaction call → the summary text ("" on failure/empty). ``reasoning_off``
        forces enable_thinking=false so a reasoning model can't exhaust its budget before answering."""
        call = {
            "stream": False,
            "max_tokens": 1024,  # a briefing, not an essay — and an uncapped reasoner can hang the turn
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        role = self._ctx.reasoner_role
        if reasoning_off:
            role = replace(role, reasoning="off") if role is not None else None
        if role is not None:
            role.apply(call)
        elif reasoning_off:
            call.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        try:
            rlog.phase = "compactor" + ("-noreason" if reasoning_off else "")
            comp = _parse_completion(self._ctx.reasoner_chat(call, rlog))
            # This call offered no tools — recover a dialect/tool-call "answer" back to text: the
            # leak becomes tool_calls, then coerce drops them and promotes the reasoning summary.
            comp = massage.coerce_text_answer(massage.apply(comp, None, rlog), rlog)
            text = _completion_text(comp)
            if role is not None:
                text = role.clean_content(text)
            return _strip_cria_banners(text).strip()
        except Exception as e:  # a summary is a nicety — never let it break completion
            rlog.emit("loop.compact_error", level="warn", error=str(e))
            return ""

    def _closing(self, sess: PlanSession, briefing: str = "") -> str:
        """The final message. Report the truth: if any step was accepted UNVERIFIED (its
        checks never passed after the retry budget), say so and name it — don't claim a
        clean completion when e.g. the test step's tests don't pass.

        The completion BRIEFING is embedded here, in the enveloped block — this message is the
        briefing's home. The harness stores it in the conversation, its compactor summarizes
        from it, and cria re-reads it from history (``_briefing_from_history``). One summary,
        carried by the transcript — never a server-side copy."""
        items = sess.plan.items
        total = len(items)
        unverified = [(i + 1, it) for i, it in enumerate(items) if it.done and it.note != "verified"]
        brief_block = f"\n\n{BRIEFING_OPEN}\n{briefing}\n{BRIEFING_CLOSE}" if briefing else ""
        if not unverified:
            return f"{indicators.MARKER}plan complete — all {total} steps verified.{brief_block}".strip()
        lines = [f"{indicators.MARKER}plan finished, but {len(unverified)} of {total} steps did NOT pass verification:"]
        for n, it in unverified:
            why = f" — {it.fail_reason}" if it.fail_reason else ""
            lines.append(f"  ⚠ step {n}: {it.text}{why}")
        lines.append("\nThose steps ran but their checks never passed — the result needs review before it can be trusted (e.g. the tests may still be failing).")
        return ("\n".join(lines) + brief_block).strip()


# ------------------------------------------------------------------ module functions


def session_key(headers, messages: list[dict]) -> str:
    """Correlate the many harness requests of one task. Prefer an explicit session
    header; else key on the ORIGINAL (first) user message, which is stable across a
    task's requests even as cria rewrites what it sends the coder.

    The fallback SKIPS harness env-context preambles (``_is_env_context``), keying on the
    first REAL user message — the same message ``_history_root`` fingerprints. Keying on a
    stable preamble collided every conversation in a repo onto one ``task:`` key, which made
    a NEW task look like a compaction-rewrite of the old one (false ``rewritten``) and leaked
    the old conversation's briefing into it."""
    if headers is not None:
        sid = headers.get("X-Cria-Session-Id")
        if sid:
            return f"sid:{sid}"
    for m in messages:
        if m.get("role") == "user" and not _is_env_context(m):
            return f"task:{_task_key(_content_text(m.get('content')))}"
    return "task:none"


def _stable_session(key: str) -> bool:
    """True when the session key is CONTENT-INDEPENDENT (a harness session header or Codex's
    prompt_cache_key → ``sid:``). Only these keys can support rewrite detection and persisted
    briefings: the ``task:`` fallback key is DERIVED from the conversation root, so a rewritten
    root simply mints a new key (nothing to compare), and a briefing stored under a task-text
    hash would resurrect for an unrelated conversation that happens to start with the same
    prompt — e.g. re-running the same task in a wiped workspace would falsely claim the work
    already exists (the plan-cache-leak bug, again, but persisted)."""
    return key.startswith("sid:")


def _briefing_from_history(messages: list[dict]) -> str:
    """The completion briefing of THIS conversation's last finished plan, re-read from the
    history the harness sent — the enveloped block cria itself embedded in the closing message
    (see ``_closing``). Matching cria's OWN sentinel is structural, not phrase-matching the
    harness. Returns "" when absent (e.g. the harness compacted it away — then the harness
    summary, which was written WITH the briefing in view, carries the content instead)."""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, str) and BRIEFING_OPEN in c:
            block = c.split(BRIEFING_OPEN, 1)[1]
            return block.split(BRIEFING_CLOSE, 1)[0].strip()
    return ""


def _session_to_dict(sess: PlanSession) -> dict:
    """The DURABLE subset of a live PlanSession — the plan + progress. Transient turn state
    (awaiting flags, gate plans, streaks) is deliberately dropped: on resume the loop simply
    re-drives the current step from a clean turn."""
    return {
        "plan": {
            "id": sess.plan.id, "task": sess.plan.task, "created": sess.plan.created,
            "status": sess.plan.status,
            "items": [{"text": it.text, "done": it.done, "note": it.note,
                       "fail_reason": it.fail_reason} for it in sess.plan.items],
        },
        "summary": sess.summary,
        "prior_work": sess.prior_work,
        "verify_fails": sess.verify_fails,
    }


def _session_from_dict(d) -> PlanSession | None:
    """Rebuild a resumable PlanSession; None on any shape mismatch (never block startup)."""
    try:
        p = d["plan"]
        plan = Plan(id=str(p["id"]), task=str(p["task"]), created=str(p["created"]),
                    status=str(p.get("status", "in_progress")),
                    items=[PlanItem(text=str(it["text"]), done=bool(it.get("done")),
                                    note=it.get("note"), fail_reason=it.get("fail_reason"))
                           for it in p["items"]])
        return PlanSession(plan=plan, summary=str(d.get("summary", "")),
                           prior_work=str(d.get("prior_work", "")),
                           verify_fails=int(d.get("verify_fails", 0)))
    except Exception:  # noqa: BLE001
        return None


def _history_root(messages: list[dict]) -> tuple[str, str]:
    """``(text, fingerprint)`` of the conversation's ROOT — the first user message that isn't a
    harness env-context block (the SAME message the ``task:`` fallback ``session_key`` hashes,
    deliberately). This is the structural identity of a conversation: appending turns never
    changes it, but a harness compaction REPLACES it (the summary becomes the root). A changed
    fingerprint under a stable ``sid:`` session key is therefore the compaction signal — content-
    based, no phrase-matching, harness-agnostic. ``task:``-keyed sessions never detect rewrites
    (``_stable_session`` gates it): their key derives from this very root, so a rewritten root
    mints a new key and simply looks like a new session (recorded in DEFERRALS.md)."""
    for m in messages:
        if m.get("role") == "user" and not _is_env_context(m):
            text = _content_text(m.get("content"))
            return text, hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
    return "", ""


def _work_log(messages: list[dict], limit: int = 6000) -> str:
    """A compact log of the coder's REAL actions — the tool calls it made (file writes, commands)
    and what they returned — for the completion compaction. cria's own plan-file writes and probe
    runs are stripped so the summary reflects the actual work, not the orchestration scaffolding.
    Tool arguments are clipped (a write_file's full body is noise here; the path is the signal)."""
    lines: list[str] = []
    for m in _strip_cria_file_ops(messages):
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                lines.append(f"$ {fn.get('name')} {_clip(str(fn.get('arguments', '')), 200)}")
        elif role == "tool":
            c = str(m.get("content") or "").strip()
            if c and "PROBE_EXIT" not in c:  # skip cria's ground-truth probe output
                lines.append(f"  -> {_clip(c, 200)}")
    return _clip_tail("\n".join(lines), limit)


def _strip_cria_banners(text: str) -> str:
    """Drop cria's own `⟦cria⟧ …` status lines from a text blob — so the coder can't parrot
    them and they never reach the critic (via pending_coder_text) as 'the coder's summary'."""
    if not text or indicators.SENTINEL not in text:
        return text
    return "\n".join(ln for ln in text.splitlines() if indicators.SENTINEL not in ln).strip()


def _strip_completion_banners(completion: dict) -> None:
    """Strip cria's parroted `⟦cria⟧` banners from a completion's content, in place — so they
    aren't forwarded to the harness (and re-echoed into the next turn's history)."""
    for ch in completion.get("choices", []):
        msg = ch.get("message") or {}
        if isinstance(msg.get("content"), str):
            msg["content"] = _strip_cria_banners(msg["content"])


def _strip_cria_file_ops(messages: list[dict]) -> list[dict]:
    """Hide cria's OWN artifacts from the coder: any `.cria/` plan-file writes (`mkdir -p .cria &&
    … > .cria/<id>.md`) AND its `⟦cria⟧` status banners. cria no longer EMITS `.cria/` writes — the
    plan mirror moved to cria's own dir with the no-workspace-pollution fix — but a resumed or
    compacted conversation can still carry historical ones in its replayed history, so the scrub
    stays. The banner scrub is always needed too, else the coder PARROTS the banners back and they
    land in the critic as 'the coder's summary'."""
    hidden: set = set()
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "assistant" and isinstance(content, str) and indicators.SENTINEL in content:
            content = _strip_cria_banners(content)  # scrub cria's own banner lines
            m = {**m, "content": content}
        if role == "assistant" and m.get("tool_calls"):
            kept = []
            for tc in m["tool_calls"]:
                a = (tc.get("function") or {}).get("arguments") or ""
                a = a if isinstance(a, str) else json.dumps(a)
                if "mkdir -p .cria &&" in a:  # cria's historical file-op signature
                    hidden.add(tc.get("id"))
                else:
                    kept.append(tc)
            if kept or (content or "").strip():
                out.append({**m, "tool_calls": kept})
            # else: the message was ONLY cria artifacts — drop it entirely
        elif role == "tool" and m.get("tool_call_id") in hidden:
            continue  # drop the file-op's result too
        elif role == "assistant" and isinstance(content, str) and not content.strip():
            continue  # an assistant message that was ONLY banners → now empty → drop
        else:
            out.append(m)
    return out


def reframe_preamble(m: dict) -> dict:
    """Re-present a harness env-context/instructions preamble in cria's OWN clean voice instead
    of forwarding it raw (ports codex-local's extract_project_instructions). A harness like Codex
    prepends a `# AGENTS.md instructions <INSTRUCTIONS>…</INSTRUCTIONS><environment_context>…`
    blob — foreign tags, CRLF, sandbox/permission plumbing — which a small model reads as a
    patchwork of another voice (and parrots). Unwrap the real content: the project instructions
    and just the useful environment fields (cwd/shell/date), dropping the XML and the sandbox
    noise. Only touches a recognized preamble; an unrecognized message is returned untouched, and
    the raw form is kept if nothing could be extracted (never lose the user's instructions)."""
    if m.get("role") != "user" or not _is_env_context(m):
        return m
    new = _reframe_preamble_text(_msg_text_content(m))
    return {**m, "content": new} if new else m


def _msg_text_content(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""


def _tag_body(text: str, name: str) -> str | None:
    """The content between ``<name>`` and ``</name>`` (first occurrence), or None."""
    open_t, close_t = f"<{name}>", f"</{name}>"
    lo, hi = text.find(open_t), text.find(close_t)
    if lo == -1 or hi == -1 or hi < lo:
        return None
    return text[lo + len(open_t):hi]


# The environment fields worth showing a coder — cwd/shell/date — by tag name. Sandbox /
# permission_profile / filesystem plumbing is deliberately NOT surfaced: it's harness noise a
# small model burns attention on (approval semantics the flow never uses).
_ENV_FIELDS = (("cwd", "cwd"), ("shell", "shell"), ("current_date", "date"), ("timezone", "timezone"))


def _reframe_preamble_text(text: str) -> str | None:
    instr = _tag_body(text, "INSTRUCTIONS") or _tag_body(text, "user_instructions")
    env = _tag_body(text, "environment_context")
    parts: list[str] = []
    if instr and instr.strip():
        parts.append("Project instructions (from the repo — follow these):\n"
                     + instr.replace("\r", "").strip())
    if env:
        fields = [(label, v.strip()) for tag, label in _ENV_FIELDS
                  if (v := _tag_body(env, tag)) and v.strip()]
        if fields:
            parts.append("Working environment — " + ", ".join(f"{k}: {v}" for k, v in fields) + ".")
    return "\n\n".join(parts) if parts else None


def _is_env_context(m: dict) -> bool:
    """A harness-injected environment/instructions preamble (not the real task) that some
    harnesses prepend as a user message. cria recognizes the known conventions — e.g. Codex's
    `<environment_context>` (cwd/shell/date) and `<user_instructions>` blocks; a harness that
    sends none simply has its FIRST user message treated as the task, which is the right default."""
    c = m.get("content")
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    c = c or ""
    return "<environment_context>" in c or "<user_instructions>" in c


def _frame_for_item(messages: list[dict], item: str, summary: str, idx: int, total: int, prior_work: str = "", tools=None) -> list[dict]:
    """Rewrite the conversation so the coder's task IS the current step, and so cria — not the
    harness — owns the system prompt:

    * DROP the harness's agent system prompt entirely. When cria is driving the loop it provides
      the orchestration, so a harness's "you are an autonomous coding agent, plan and finish the
      whole task" boilerplate (Codex ships ~7.8K tokens of it — a third of the window) is pure
      conflict: it fights cria's step-by-step driving and buries cria's instruction. cria leads
      with its OWN concise coder system prompt instead (`prompts/coder_system.txt`). Harness-
      agnostic: whatever agent prompt any harness puts in `system`/`developer` is replaced.
    * REPLACE the user's actual task with the step framing, so the coder can't see — and race
      ahead to — later steps. The task is the first user message that ISN'T a harness env-context
      block (Codex prepends one).
    * KEEP everything else: the user's own instructions (AGENTS.md), env context, and the work
      history — those are user/assistant/tool messages, not the harness agent prompt.
    * On a FOLLOW-UP (prior_work set), fold the completion-compaction of the earlier plan into the
      system message so the coder knows what already exists this session — same reason as the step:
      system is protected from floor-trimming and authoritative.
    """
    prompt = _item_prompt(item, summary, idx, total)
    messages = _strip_cria_file_ops(messages)  # don't let the coder see/mimic `.cria/` writes
    # cria's step instruction goes in the SYSTEM message, NOT a front user turn. The context floor
    # protects system messages but trims old user turns — and on a large history (after compaction)
    # it was trimming cria's own step framing AWAY, leaving the coder with no idea what step it was
    # on (it then flails and the re-nudge loop never converges = "Thinking forever"). In the system
    # message the instruction can never be dropped, and system is authoritative for the model.
    done_block = f"Already done earlier this session (build on it, don't redo):\n{prior_work}\n\n" if prior_work else ""
    # cria owns the system prompt: base coder prompt → the menu-derived tool hint (so the coder is
    # told to use ONLY the tools actually in this turn's menu — the harness system message that
    # add_cheatsheet folded the hint into is dropped here) → done-context → the step (kept last).
    hint = toolmenu.cheatsheet(tools)
    hint_block = f"{hint}\n\n" if hint else ""
    out: list[dict] = [{"role": "system",
                        "content": prompts.load("coder_system") + "\n\n" + hint_block + done_block + prompt}]
    replaced = False
    for m in messages:
        if m.get("role") in ("system", "developer"):
            continue  # harness agent boilerplate → replaced by cria's coder_system above
        if not replaced and m.get("role") == "user" and not _is_env_context(m):
            out.append({"role": "user", "content": prompt})  # the TASK → the step (env context kept)
            replaced = True
        else:
            out.append(reframe_preamble(m))  # env-context preamble → cria's clean voice, not raw
    if not replaced:
        out.append({"role": "user", "content": prompt})  # no task message found → the step is the ask
    return out


def _item_prompt(item: str, summary: str, idx: int, total: int) -> str:
    # Templates: cria/prompts/step_framing.txt (+ step_completed.txt for the prior-steps
    # prefix, included only once there's progress to show).
    completed = prompts.render("step_completed", summary=summary) + "\n\n" if summary else ""
    return prompts.render("step_framing", completed=completed, idx=idx, total=total, step=item)


def _completion_toolcalls(tool_calls: list[dict], *, note: str | None = None) -> dict:
    content = f"{indicators.MARKER}{note}" if note else None
    return {
        "object": "chat.completion",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content, "tool_calls": tool_calls}, "finish_reason": "tool_calls"}
        ],
    }


def _completion_final(text: str) -> dict:
    return {
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


def _parse_completion(raw: bytes) -> dict:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _has_tool_calls(completion: dict) -> bool:
    for ch in completion.get("choices", []):
        if (ch.get("message") or {}).get("tool_calls"):
            return True
    return False


_PATH_KEYS = ("path", "file_path", "file", "filename")  # aliases the writeproxy itself accepts
# Patch-body target on PARSED text (real newlines bound the path).
_PATCH_FILE_RE = re.compile(r"\*\*\* (?:Add|Update) File: ([^\n]+)")
# Patch-body target on RAW arg blobs, where \n is two ESCAPED characters: the path ends at an
# escaped newline, a quote, or a real newline. A greedy `.+` here swallows the whole patch tail —
# every tiny edit then "targets" a different garbage path and the wheel-spin count never accrues
# (and rstrip('\\n"') is a CHARACTER-SET strip that mangles real paths ending in n/quote: .json).
_PATCH_FILE_RAW_RE = re.compile(r'\*\*\* (?:Add|Update) File: ((?:[^"\\\n]|\\[^n])+)')
_PATH_KEY_RAW_RE = re.compile(r'"(?:path|file_path|file|filename)"\s*:\s*"((?:[^"\\]|\\.)+)"')


def _path_of_args(args, patch_ok: bool = True) -> str | None:
    """The target file named by a write-class call's arguments — a path-key alias, or (when
    ``patch_ok``, i.e. the call IS an apply_patch) the first Add/Update target of the patch
    body (the writeproxy lowers edit_file → apply_patch BEFORE tracking, so the patch route is
    the COMMON one for edits). ``patch_ok`` must be False for write_file/edit_file calls: their
    CONTENT can legitimately contain patch-example text, and a truncated write's raw blob would
    otherwise yield a file the model never touched. Lenient: malformed JSON falls back to
    boundary-bounded regexes; None when no path is recoverable (skipped, never guessed)."""
    try:
        obj = json.loads(args) if isinstance(args, str) else dict(args or {})
    except (json.JSONDecodeError, TypeError, ValueError):
        obj = None
    if isinstance(obj, dict):
        for k in _PATH_KEYS:
            p = obj.get(k)
            if isinstance(p, str) and p:
                return p
        if not patch_ok:
            return None
        blob = obj.get("input") or obj.get("patch") or ""
        m = _PATCH_FILE_RE.search(blob) if isinstance(blob, str) else None
        return (m.group(1).strip() or None) if m else None
    if not isinstance(args, str):
        return None
    m = _PATH_KEY_RAW_RE.search(args)
    if m:
        return m.group(1)
    if not patch_ok:
        return None
    m = _PATCH_FILE_RAW_RE.search(args)
    return (m.group(1).strip() or None) if m else None


def _write_path(fn: dict) -> str | None:
    """The file a single write-class tool call targets; None for non-write calls."""
    if fn.get("name") not in _WRITE_TOOLS:
        return None
    return _path_of_args(fn.get("arguments") or "", patch_ok=fn.get("name") == "apply_patch")


def _write_paths(completion: dict) -> list:
    """Paths of the files this completion WRITES, in call order."""
    return [p for ch in completion.get("choices", [])
            for tc in (ch.get("message") or {}).get("tool_calls") or []
            if (p := _write_path(tc.get("function") or {}))]


def guard_gate_op(gs: GuardState, body: dict, rlog, *, workspace_root=None) -> dict | None:
    """Compose the completion gate (probegate.plan_gate: syntax floor + discovered top probe +
    top TEST probe + git snapshot) and build it as a shell tool call for the HARNESS to run.
    None if the harness advertises no shell tool (then cria can only prose-verify). The plan is
    stashed on ``gs`` so the result can be replayed through the ported interpreters. Shared by the
    plan loop (workspace_root from its LoopContext) and the plan-off path (root from the request)."""
    tool = find_shell_tool(body.get("tools"))
    if tool is None:
        return None
    # NEVER fall back to "." — that is cria's OWN cwd, not the workspace (it once composed a
    # probe over cria's repo). Unknown root → a minimal git-only gate; the harness's shell
    # still runs in the workspace, so the change-signal lands and the floor/probes abstain.
    root = workspace_root or _extract_cwd(body.get("messages", []))
    if root == ".":  # _extract_cwd's no-cwd fallback IS cria's own cwd — refuse it here
        root = ""
    try:
        plan = probegate.plan_gate(root)
    except OSError as e:  # unreadable workspace → no gate; the caller still fails open
        rlog.emit("loop.gate_error", level="warn", error=str(e))
        gs.gate_plan = None
        return None
    gs.gate_plan = plan
    return {
        "id": "call_" + uuid.uuid4().hex[:16],
        "type": "function",
        "function": {"name": tool["name"], "arguments": json.dumps(shell_args(tool, plan.script))},
    }


def guard_track_repetition(gs: GuardState, coder: dict, rlog, *, step=None) -> None:
    """Repetition detection, by the NATURE of each forwarded tool call, not its bytes
    (exact fingerprints were tried on the codex-local side and missed one-flag jitter).
    REPEAT_FINGERPRINT_N nature-matches within the last REPEAT_WINDOW calls trips the
    redirect. Windowed, not consecutive-only, so write→test→write→test loops with
    byte-identical writes are caught (the canonical small-model spiral) — while PROGRESS
    (a write/mutation matching nothing in the window, i.e. new ground changed) resets the
    hunt, so a healthy edit→test→edit→test cycle never trips on its repeated test runs.

    Operates on GuardState so the plan loop and the plan-off path run ONE implementation."""
    if gs.recent_actions is None:
        gs.recent_actions = []
    for ch in coder.get("choices", []):
        for tc in (ch.get("message") or {}).get("tool_calls") or []:
            if (gs.redirect_due or gs.redirect_probe
                    or gs.spin_probe_due or gs.spin_probe):
                return  # an intervention is in flight — it consumed the evidence; nothing
                # accrues until it's delivered (a fire mid-completion must not let the
                # completion's REMAINING calls repopulate the just-flushed windows)
            fn = tc.get("function") or {}
            name = fn.get("name") or "?"
            args = fn.get("arguments") or ""
            args = args if isinstance(args, str) else json.dumps(args)
            sig = _action_signature(name, args)
            gs.action_seq += 1
            # AGE-based trim (entries are (seq, sig)): an entry expires REPEAT_WINDOW
            # forwarded calls after it was seen — even across progress resets. A length
            # trim alone made preserved write signatures immortal: identical writes 60
            # calls apart counted as "3× in the last 12".
            cutoff = gs.action_seq - REPEAT_WINDOW
            gs.recent_actions = [e for e in gs.recent_actions if e[0] > cutoff]
            matches = sum(1 for e in gs.recent_actions if _actions_match(sig, e[1]))
            if not matches and _is_progress(sig, args):
                # a real move — reset the hunt for ACTIONS, but keep (in-window) write
                # signatures: the per-file rule ("same file, same content, 3× in the
                # window") must survive interleaved progress on OTHER files
                gs.recent_actions = [e for e in gs.recent_actions if e[1][0] == "write"]
                gs.recent_actions.append((gs.action_seq, sig))
                continue
            gs.recent_actions.append((gs.action_seq, sig))
            if (matches + 1 >= REPEAT_FINGERPRINT_N
                    and not gs.redirect_due and not gs.redirect_probe
                    and not gs.spin_probe_due and not gs.spin_probe):
                gs.redirect_due = True
                # flush BOTH windows: one intervention consumes the evidence — the writes
                # that fired this redirect must not ALSO count toward a wheel-spin right
                # after the coder complies (that steer would point away from the very file
                # it just fixed).
                gs.recent_actions = []
                gs.recent_writes = []
                gs.repeat_action = f"{name} {_clip(args, 300)}"
                rlog.emit("loop.repetition", step=step, tool=name,
                          count=REPEAT_FINGERPRINT_N, args=_clip(args, 120))


def guard_track_write_streak(gs: GuardState, coder: dict, rlog, *, step=None) -> None:
    """Wheel-spinning detection, WINDOWED (operator, 2026-07-12): the same file written
    WHEEL_SPIN_WRITES times — ANY content — within the last WRITE_WINDOW forwarded tool
    calls (sized to five write→read→test cycles). Consecutive is not required: the tiny-edit
    spiral rewrites the file with small varying changes (never fixing the actual fault, e.g.
    indentation) while interleaving reads, tests, and other-file writes, so a consecutive streak
    undercounts it and the repetition trigger's content-hash can't see it. At the threshold the
    next turn runs the gate and INSERTS the lint/type-check findings — ground truth on the next
    call, not more rewriting. Operates on GuardState — shared by both paths."""
    if gs.recent_writes is None:
        gs.recent_writes = []
    for ch in coder.get("choices", []):
        for tc in (ch.get("message") or {}).get("tool_calls") or []:
            if (gs.redirect_due or gs.redirect_probe
                    or gs.spin_probe_due or gs.spin_probe):
                return  # intervention in flight — nothing accrues (this tracker runs AFTER
                # guard_track_repetition on the SAME completion: without this check it would
                # repopulate the flushed window with the very writes that fired the redirect,
                # and the coder's single compliance write would re-trip a spin probe steering
                # it away from the file it just fixed)
            path = _write_path(tc.get("function") or {})
            gs.recent_writes.append(path)  # None for non-writes — the window is CALLS
            del gs.recent_writes[:-WRITE_WINDOW]
            if (path is not None
                    and gs.recent_writes.count(path) >= WHEEL_SPIN_WRITES
                    and not gs.spin_probe_due and not gs.spin_probe
                    and not gs.redirect_due and not gs.redirect_probe):
                gs.spin_probe_due = True
                gs.spin_path = path
                # flush BOTH windows (one intervention at a time — a pending redirect's
                # gate would otherwise be hijacked and its reasoner-authored nudge
                # overwritten by the spin renudge)
                gs.recent_writes = []
                gs.recent_actions = []
                rlog.emit("loop.wheel_spinning", step=step, path=path, writes=WHEEL_SPIN_WRITES)


def guard_intervene(gs: GuardState, body: dict, rlog, *, step=None, workspace_root=None) -> dict | None:
    """If a repeat/spin was flagged on a prior turn, intervene BEFORE the next coder turn: emit a
    ground-truth probe (a repo-checks shell call the harness runs) and return that completion to
    send now — or, when no gate is available (no shell tool / unreadable workspace), NEVER swallow
    the tripped intervention: park a canned steer in ``gs.nudge_reason`` for the caller to inject
    into the coder framing, and return None. Returns None when nothing is pending. Shared by the
    plan loop and the plan-off path — one implementation of the repetition→probe→steer round-trip."""
    if gs.redirect_due:  # repetition tripped → ground truth, then a redirect
        gs.redirect_due = False
        gs.spin_probe_due = False  # the redirect's gate supersedes a pending spin probe — never run
        # two back-to-back gates, and never let the spin steer overwrite the redirect in nudge_reason
        probe_tc = guard_gate_op(gs, body, rlog, workspace_root=workspace_root)
        if probe_tc is not None:
            gs.awaiting_probe = True
            gs.redirect_probe = True
            gs.probe_call_id = probe_tc["id"]
            rlog.emit("loop.redirect_probe", step=step)
            return _completion_toolcalls([probe_tc], note="running the repo's checks (repeated action detected)")
        gs.nudge_reason = (
            f"you have repeated the same action {REPEAT_FINGERPRINT_N} times "
            f"({_clip(gs.repeat_action, 160)}) — repeating it will not change the outcome. "
            "Choose a DIFFERENT next action and take it now via a tool call.")
        rlog.emit("loop.redirect", step=step, canned=True, chars=len(gs.nudge_reason))
    if gs.spin_probe_due:  # wheel-spinning tripped last turn → ground truth BEFORE more digging
        gs.spin_probe_due = False
        probe_tc = guard_gate_op(gs, body, rlog, workspace_root=workspace_root)
        if probe_tc is not None:
            gs.awaiting_probe = True
            gs.spin_probe = True
            gs.probe_call_id = probe_tc["id"]
            rlog.emit("loop.spin_probe", step=step, path=gs.spin_path)
            return _completion_toolcalls([probe_tc], note="running the repo's checks (repeated rewrites detected)")
        gs.nudge_reason = (  # same no-gate fallback: a steer, never silence
            f"you have rewritten `{gs.spin_path}` repeatedly; the repo's checks could not "
            "run here. Stop rewriting it — re-read the step and verify a DIFFERENT part of "
            "the work before touching that file again.")
        rlog.emit("loop.spin_probe_result", step=step, canned=True)
    return None


def _add_note(completion: dict, note: str) -> None:
    """Record a cria assist as an out-of-band note on the completion. The server surfaces it as a
    ⟦cria⟧ line when [indicators] assists is on — 'no hidden guards': every intervention that fires
    is visible under the flag. A SEPARATE channel from content, so the loop's parroted-banner scrub
    (_strip_completion_banners) can't drop cria's own intentional notes."""
    if note:
        completion.setdefault("cria_notes", []).append(note)


def guard_gate_verdict(gs: GuardState, body: dict, rlog) -> str | None:
    """Read a completion-gate probe's result and return the block-nudge (the file:line errors) when
    the repo's checks FAILED, else None (checks passed, or couldn't run → fail-open, don't wedge).
    The OBJECTIVE half of the loop's completion gate — no reasoner critic — so the plan-off path can
    verify a 'done' claim against ground truth before letting the turn end. Reuses the shared
    interpret + block-nudge modules (no duplicated verdict logic)."""
    probe = _read_tool_result(body.get("messages", []), gs.probe_call_id)
    outcome = probegate.interpret_gate(gs.gate_plan, probe) if gs.gate_plan is not None \
        else probegate.GateOutcome(ran=False)
    if not outcome.ran:
        return None  # the checks couldn't run → accept the 'done' (fail-open, like the loop)
    return proberun.completion_block_nudge(outcome.report)  # errors, or None when clean


def guard_ground_truth(outcome) -> str:
    """The coder-facing ground truth from a gate outcome: the block-nudge findings if any, else a
    plain 'all checks pass' (NEUTRAL — a content-blind streak can't tell a spiral from honest
    sequential edits, so it must NOT claim the bug is elsewhere), else 'could not run'."""
    findings = proberun.completion_block_nudge(outcome.report) if outcome.ran else None
    if findings:
        return findings
    if outcome.ran:
        return ("the repo's checks (lint + type-check + syntax) all PASS on your current "
                "edits — no error-class findings in this file")
    return "the checks could not run"


def guard_canned_redirect(gs: GuardState, outcome) -> str:
    """The canned repetition redirect (no reasoner) — the shared steer both the plan-off path and
    the loop's reasoner-unavailable fallback deliver."""
    return (f"you have repeated the same action {REPEAT_FINGERPRINT_N} times "
            f"({_clip(gs.repeat_action, 160)}) — repeating it will not change the outcome. "
            f"Ground truth: {_clip_tail(guard_ground_truth(outcome), 600)}. Choose a DIFFERENT "
            "next action and take it now via a tool call.")


def guard_probe_steer(gs: GuardState, body: dict, rlog, *, step=None, author=None) -> str | None:
    """A guard probe (repetition redirect or wheel-spin) we emitted last turn has now run — read
    its result, interpret the gate, and return the steer text to hand the coder (the caller injects
    it as a nudge). ``author`` (loop only) reasons the redirect from the ground truth; without it
    (plan-off) the redirect is canned. Returns None when this isn't a guard probe (a plan
    completion-gate — the loop handles that itself)."""
    if not (gs.spin_probe or gs.redirect_probe):
        return None
    probe = _read_tool_result(body.get("messages", []), gs.probe_call_id)
    outcome = probegate.interpret_gate(gs.gate_plan, probe) if gs.gate_plan is not None \
        else probegate.GateOutcome(ran=False)
    if gs.redirect_probe:  # repetition: ground truth → a redirect (reasoner-authored, or canned)
        gs.redirect_probe = False
        redirect = author(gs, outcome, body, rlog) if author is not None else guard_canned_redirect(gs, outcome)
        rlog.emit("loop.redirect", step=step, chars=len(redirect))
        return f"[REDIRECT]\n{redirect}"
    # wheel-spin: INSERT the ground truth and keep working — no verdict, the step stays open
    gs.spin_probe = False
    findings = proberun.completion_block_nudge(outcome.report) if outcome.ran else None
    rlog.emit("loop.spin_probe_result", step=step, clean=findings is None and outcome.ran)
    return (f"you have rewritten `{gs.spin_path}` repeatedly; "
            f"ground truth from the repo's own checks:\n{_clip_tail(guard_ground_truth(outcome), 1800)}")


def guard_rumination(coder: dict, body: dict, coder_chat, rlog, *, step=None, phase: str = "coder") -> dict:
    """Rumination guard (ported from codex-local §19). The streaming coder aborted this turn as
    a reasoning loop (``finish_reason == "rumination"``) — the model was second-guessing itself
    into the ground and would otherwise return an empty turn or run to truncation. Re-prompt to
    pick the simplest next step and act, capped. Distinct from the truncation guard (that's a
    cut-off WRITE; this is runaway THINKING) — they key off different finish_reasons.

    ``coder_chat(body, rlog) -> bytes`` is injected so BOTH the plan loop (its watched coder
    call) and the plan-off proxy path (a per-request watched call) run the identical guard —
    the guards are NOT gated behind the planner; only plan-authored guidance is."""
    attempt = 0
    conv = list(body.get("messages") or [])
    while massage.is_ruminating(coder) and attempt < MAX_RUMINATION_RETRIES:
        v = coder.get("cria_rumination") or {}
        attempt += 1
        rlog.emit("loop.rumination", step=step, attempt=attempt,
                  hits=v.get("hits"), reasoning_tokens=v.get("reasoning_tokens"))
        conv = conv + [{"role": "user", "content": prompts.render(
            "rumination_guard", hits=v.get("hits", "several"), tokens=v.get("reasoning_tokens", "many"))}]
        rlog.phase = f"{phase}-focus{attempt}"
        coder = massage.apply(
            _parse_completion(coder_chat({**body, "messages": conv}, rlog)), body.get("tools"), rlog)
    coder.pop("cria_rumination", None)  # internal marker — never forward it
    for ch in coder.get("choices", []):  # normalize the sentinel finish_reason for downstream
        if ch.get("finish_reason") == "rumination":
            ch["finish_reason"] = "stop"
    if attempt:  # no hidden guards: surface that the reasoning loop was broken
        _add_note(coder, f"reasoning loop detected — aborted and refocused ({attempt}×)")
    return coder


def guard_truncation(coder: dict, body: dict, coder_chat, rlog, *, step=None, phase: str = "coder") -> dict:
    """Output-truncation guard (ported from codex-local `local_routing.rs`). The model hit
    the output-token cap MID-generation, so any file it was writing is cut off. NEVER ship
    that partial write: the model would re-read an "incomplete" file and rewrite it forever,
    each rewrite truncating at the SAME cap (the file-corruption loop we watched burn a whole
    run). Instead — when the truncation was mid-`write_file` — steer to INCREMENTAL writes
    (first chunk via write_file, then edit_file appends) and retry, capped. If it's still cut
    off after the retry budget (or the truncation wasn't a write), refuse the partial: drop
    the tool call so the caller gates on ground truth rather than writing a corrupt file.

    NOTE: the retry deliberately does NOT feed the model its own truncated output — the remedy
    is 'write the file in small pieces', which starts the file over in chunks, so 'continue
    from byte N' isn't needed (and the truncated text is unreliable anyway).

    ``coder_chat`` is injected so the loop and the plan-off proxy path share ONE guard."""
    attempt = 0
    conv = list(body.get("messages") or [])
    while massage.is_truncated(coder) and attempt < MAX_TRUNCATION_RETRIES:
        path = _truncated_write_path(coder)
        out_tok = _output_tokens(coder)
        rlog.emit("loop.truncated", step=step, attempt=attempt + 1, path=path, output_tokens=out_tok)
        if path is None:
            break  # not a mid-write truncation → the write steer doesn't apply; refuse below
        attempt += 1
        limit = f"~{out_tok} tokens" if out_tok else "the output-token limit"
        conv = conv + [{"role": "user", "content": prompts.render("truncation_guard", path=path, limit=limit)}]
        rlog.phase = f"{phase}-continue{attempt}"
        coder = massage.apply(
            _parse_completion(coder_chat({**body, "messages": conv}, rlog)), body.get("tools"), rlog)
    dropped = massage.is_truncated(coder)
    if dropped:
        # Exhausted (or a non-write truncation): do NOT forward the partial write — a cut-off
        # write_file lowered to disk is exactly the corruption. Drop the tool call; the turn then
        # reads as non-acting and the caller gates on ground truth rather than a corrupt file.
        rlog.emit("loop.truncated_dropped", step=step)
        _drop_tool_calls(coder)
    coder.pop("cria_rumination", None)  # a retry may itself ruminate — never forward the marker
    for ch in coder.get("choices", []):
        if ch.get("finish_reason") == "rumination":
            ch["finish_reason"] = "stop"
    if dropped:  # no hidden guards: the partial write was refused
        _add_note(coder, "output hit the token limit — partial write refused (retry in smaller pieces)")
    elif attempt:  # recovered after steering to incremental writes
        _add_note(coder, f"output hit the token limit — steered to incremental writes ({attempt}×)")
    return coder


def _truncated_write_path(completion: dict) -> str | None:
    """The path of a file the model was writing when it hit the token cap, read from the
    (possibly cut-off) tool-call arguments. Same lenient extraction as _path_of_args — a
    truncated response can leave the args as invalid JSON, and alias-keyed writes
    (file_path/file) must keep their incremental-write steer too."""
    for ch in completion.get("choices", []):
        for tc in (ch.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") not in _WRITE_TOOLS:
                continue
            # same patch_ok gate as _write_path: a truncated write_file whose CONTENT contains
            # patch-example text must not steer the coder to a file it never touched
            p = _path_of_args(fn.get("arguments") or "", patch_ok=fn.get("name") == "apply_patch")
            if p:
                return p
    return None


def _output_tokens(completion: dict) -> int | None:
    """The completion-token count the server reported for this response (when present)."""
    n = (completion.get("usage") or {}).get("completion_tokens")
    return n if isinstance(n, int) else None


def _drop_tool_calls(completion: dict) -> None:
    """Strip tool calls from a completion in place (used to REFUSE a truncated/partial write so
    it never reaches the writeproxy → disk). The turn then reads as non-acting and the loop gates
    on ground truth. Also normalizes ``finish_reason`` away from ``length`` so downstream code
    doesn't re-trip the truncation check."""
    for ch in completion.get("choices", []):
        (ch.get("message") or {}).pop("tool_calls", None)
        if ch.get("finish_reason") == "length":
            ch["finish_reason"] = "stop"


def _read_tool_result(messages: list[dict], call_id: str) -> str:
    """The harness's result for a tool call cria emitted (e.g. the ground-truth probe),
    found by its call id in the message stream."""
    for m in reversed(messages):
        if m.get("role") == "tool" and m.get("tool_call_id") == call_id:
            return str(m.get("content") or "")
    return ""




def _coder_evidence(messages: list[dict], probe_id, limit: int = 3) -> str:
    """The results of the coder's OWN tool runs (its test/build/command output), for the
    critic to judge on — cria OBSERVES what the coder ran, it never fabricates a run.
    Excludes cria's own probe and its silent `.cria/` writes."""
    out: list[str] = []
    for m in reversed(messages):
        if m.get("role") != "tool" or m.get("tool_call_id") == probe_id:
            continue
        c = str(m.get("content") or "").strip()
        if c and "PROBE_EXIT" not in c and probegate.SECTION_PREFIX not in c:  # skip the probe/gate output
            out.append(_clip(c, 400))
            if len(out) >= limit:
                break
    return "\n---\n".join(reversed(out))


def _completion_text(completion: dict) -> str:
    for ch in completion.get("choices", []):
        c = (ch.get("message") or {}).get("content")
        if isinstance(c, str):
            return c
    return ""


def _clean_completion(completion: dict, role) -> None:
    """Strip a role's leaked reasoning (when reasoning is off) from a completion's content,
    in place — so it never reaches the harness/coder verbatim."""
    for ch in completion.get("choices", []):
        msg = ch.get("message") or {}
        if isinstance(msg.get("content"), str):
            msg["content"] = role.clean_content(msg["content"])


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _extend_summary(summary: str, idx: int, item: str) -> str:
    line = f"{idx}. {item}"
    return f"{summary}\n{line}".strip() if summary else line


# Shell wrapper boilerplate carries no intent: without stripping it, `bash -lc cat a.py` and
# `bash -lc cat b.py` share {bash, -lc, cat} and false-match as "the same hunt" — three reads
# of three DIFFERENT files would fire the redirect.
_BOILERPLATE_WORDS = frozenset({"bash", "sh", "zsh", "dash", "-lc", "-c", "-l", "-e", "env"})


def _action_signature(name: str, args: str) -> tuple:
    """The NATURE of a tool call, for repetition matching — not its bytes. A write is its
    target + content (path, content-hash); everything else is its tool name + a normalized
    word-set of its argument values minus shell boilerplate (flag/word jitter survives, per
    the codex-local lesson that exact fingerprints don't). Args that normalize to NOTHING
    (symbol-only/non-ASCII) fall back to an exact-bytes hash — an empty set must not match
    every other empty set of the same tool."""
    try:
        parsed = json.loads(args) if isinstance(args, str) else dict(args or {})
    except (ValueError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    if _WRITE_TOOL_RE.search(name):
        path = _path_of_args(args, patch_ok="patch" in name.lower()) or ""
        body = str(parsed.get("content") or parsed.get("contents") or parsed.get("text")
                   or parsed.get("input") or parsed.get("patch") or args)
        return ("write", path, hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:16])
    text = " ".join(str(v) for v in _flat_values(parsed)) or (args if isinstance(args, str) else "")
    words = frozenset(normalize_search(text)) - _BOILERPLATE_WORDS
    if not words:  # nothing survived normalization → exact bytes only (never a wildcard)
        raw = args if isinstance(args, str) else json.dumps(args or {})
        return ("act", name, hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16])
    return ("act", name, words)


def _flat_values(obj) -> list:
    """Leaf values of a parsed args object, in order — flattens nested lists/dicts (a shell
    call's {"command": ["bash", "-lc", "pytest -q"]} yields the actual words)."""
    if isinstance(obj, dict):
        return [v for val in obj.values() for v in _flat_values(val)]
    if isinstance(obj, list):
        return [v for val in obj for v in _flat_values(val)]
    return [obj]


def _actions_match(a: tuple, b: tuple) -> bool:
    """Same action by nature? Writes: exact target+content. Others: same tool, and the
    word-sets are the same hunt — exact, or near-identical (≥2 shared, ≤2 words of jitter),
    or heavily overlapping (Jaccard ≥ 0.7 with ≥3 shared)."""
    if a[0] != b[0] or a[1] != b[1]:
        return False
    if a[0] == "write":
        return a[2] == b[2]
    sa, sb = a[2], b[2]
    if isinstance(sa, str) or isinstance(sb, str):  # exact-bytes fallback signatures
        return sa == sb
    if sa == sb:
        return True
    # NOTE (round 6): a "file-target veto" was tried here — treat commands naming DISJOINT
    # files as different hunts, to spare `head a.py/b.py/c.py` exploration. It was removed: a
    # token bag can't tell a file target from a version pin or a decimal, so it (a) still
    # fired on any survey sharing one dotted token (python3.11, --cov=app.py) and (b) SILENCED
    # the exact loops we exist to catch — `pip install ==1.0.1/1.0.2/1.0.3`, a parameter sweep,
    # is "the same nature, one thing jittered". Missing that is the expensive failure; a survey
    # false-positive is cheap (the reasoner sees 3 different files in the evidence and waves it
    # through, and the gate confirms clean first). Bias to firing — the reasoner mediates.
    shared = len(sa & sb)
    jitter = len(sa ^ sb)
    return (shared >= 2 and jitter <= 2) or (shared >= 3 and shared / len(sa | sb) >= 0.7)


# A shell-native write: an output redirect (`> file`, `>> file`) or a heredoc (`<<EOF`).
# Checked on the DECODED, quote-masked COMMAND text only: quoted spans hide comparison
# operators (`awk '$3 > 100'`, `grep 'n > 0'`, `python -c "1 << 20"` are reads), `>/dev/null`,
# `2>&1`, `->`, `>=` are not workspace writes — and prose sidecar fields (justification,
# description) are excluded entirely, because one apostrophe there (don't) would unbalance the
# quote masking in both directions.
_QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_SHELL_WRITE_RE = re.compile(r'(?<![-=<>])>{1,2}\s*(?!/dev/|&)[\w./~$-]|<<-?\s*\w')
# Raw-blob variant for UNPARSEABLE args (truncated JSON): quotes/newlines are still escaped
# there, so tolerate a leading backslash — and never quote-mask raw blobs (the JSON string
# delimiters would mask the entire command away).
_SHELL_WRITE_RAW_RE = re.compile(r'(?<![-=<>])>{1,2}\s*(?!/dev/|&)\\?["\']?[\w./~$-]|<<-?\s*\\?["\']?\w')
# The shell tool's command fields, shared with shelltool.shell_args so they can't drift
# (round 4: shell_command was missing here, blinding progress detection on such harnesses).
# `script` is spliced BEFORE `input`: a script-runner tool carrying both means script=program,
# input=stdin — appending script after the shared tuple silently demoted it below input and
# read stdin data as "the command" (round 5).
_COMMAND_KEYS = tuple(dict.fromkeys(
    [k for k in _CMD_FIELDS if k != "input"] + ["script", "input"]))


def _command_text(args) -> str | None:
    """The command-carrying text of a call's arguments (decoded). Dicts yield their command
    field only — prose sidecars (justification/description) are deliberately excluded.
    Decodable non-dict shapes (bare shell text, a JSON argv array — shapes cria's own
    leaked-tool-call recovery mints) ARE the command, with real balanced quotes. None means
    an undecodable JSON FRAGMENT (truncated object/array) — only then do raw-blob rules apply."""
    if not isinstance(args, str):
        parsed = args
    else:
        try:
            parsed = json.loads(args)
        except ValueError:
            s = args.strip()
            # bare shell text IS the command — including `[ -f x ] && …` test-brackets and
            # `{ cmd; } | …` brace groups. A FRAGMENT (cut-off JSON) is a bracket followed by
            # a string delimiter (`{"…`, possibly pretty-printed) — shell never opens that way.
            return None if re.match(r'\s*[\{\[]\s*"', args) else args
    if isinstance(parsed, dict):
        for k in _COMMAND_KEYS:
            v = parsed.get(k)
            if v:
                return " ".join(str(x) for x in _flat_values(v))
        return ""
    if parsed is None:
        return ""
    return " ".join(str(x) for x in _flat_values(parsed))


def _is_progress(sig: tuple, raw: str = "") -> bool:
    """Does this action CHANGE the workspace? A write always; a shell call whose COMMAND
    carries a known mutator (or a sed -i) or writes via redirect/heredoc. Mutator words and
    the redirect scan both read the command text only — never prose sidecars ("don't touch
    the config" in a justification is not a `touch`). Progress on new ground resets the
    repetition hunt — a healthy edit→test→edit→test cycle must never trip on its repeated
    test runs, whichever write route the model favors."""
    if sig[0] == "write":
        return True
    text = _command_text(raw)
    if text is None:  # undecodable fragment — escape-tolerant raw scan
        blob = raw if isinstance(raw, str) else ""
        words = frozenset(normalize_search(blob))
        if words & _MUTATOR_WORDS or ("sed" in words and "-i" in words):
            return True
        return bool(_SHELL_WRITE_RAW_RE.search(blob))
    words = frozenset(normalize_search(text))
    if words & _MUTATOR_WORDS or ("sed" in words and "-i" in words):
        return True
    return bool(_SHELL_WRITE_RE.search(_QUOTED_SPAN_RE.sub(" q ", text)))


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + "…"


def _clip_tail(s: str, n: int) -> str:
    """Keep the LAST n chars. The probe's actionable output — the pytest short-summary
    (`FAILED …`, `8 failed, 20 passed`) and the failing traceback — lands at the tail;
    a head clip would hand the coder only the probe banner and miss the real error."""
    s = s.strip()
    return s if len(s) <= n else "…" + s[-n:]


def _dump_verify(run_dir, key: str, idx: int, total: int, step: str, system: str, user: str, done: bool, reason: str) -> None:
    """Write the EXACT context the critic saw (its system + user message) and its verdict into
    THE RUN FOLDER (same folder as the call captures + plan mirror). This is the WHOLE basis on
    which a step was judged done — so a human can see precisely what the model had to work with,
    and what it was missing. Best-effort; never breaks the loop."""
    if run_dir is None:
        return
    try:
        d = Path(run_dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S-%f")[:-3]
        md = (
            f"# Step {idx}/{total} — verdict: {'DONE' if done else 'NOT DONE'}\n\n"
            f"- session: `{key}`\n"
            f"- step: {step}\n"
            f"- reason: {reason}\n\n"
            "This is the COMPLETE context the reasoner saw when it decided this step — it judged "
            "on nothing else (no file listing, no workspace state, only what is below).\n\n"
            f"## SYSTEM message (cria/prompts/verify.txt)\n\n```\n{system}\n```\n\n"
            f"## USER message (the step + the ground truth it was handed)\n\n```\n{user}\n```\n"
        )
        (d / f"verify-step-{idx:02d}-of-{total:02d}-{stamp}.md").write_text(md, encoding="utf-8")
    except OSError:
        pass


def completion_to_sse(completion: dict):
    """Fake-stream a completion dict (content and/or tool_calls) as OpenAI SSE, so a
    streaming client gets the loop's response in the format it expects."""
    choice = (completion.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    model = completion.get("model", "")
    cid = completion.get("id", "")
    created = completion.get("created", 0)

    def chunk(delta: dict, finish=None) -> bytes:
        payload = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                   "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"

    yield chunk({"role": "assistant"})
    if msg.get("content"):
        yield chunk({"content": msg["content"]})
    if msg.get("tool_calls"):
        deltas = [
            {"index": i, "id": tc.get("id"), "type": "function",
             "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
            for i, tc in enumerate(msg["tool_calls"])
        ]
        yield chunk({"tool_calls": deltas})
    finish = choice.get("finish_reason") or ("tool_calls" if msg.get("tool_calls") else "stop")
    yield chunk({}, finish=finish)
    yield b"data: [DONE]\n\n"
