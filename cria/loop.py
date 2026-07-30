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
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

from . import callcapture, editrecovery, focustrim, groundtruth, indicators, massage, probegate, proberun, prompts, selfcompact, toolmenu, urlgrounding, verifytools, webfetch
from .classify import _task_key, latest_user_text
from .jsontext import extract_json_object, strip_think
from .plan import Plan, PlanItem
from .planner import _clean_step, _extract_cwd, missing_deliverables, reasoned_noise_indices
from .searchloop import normalize_search
from .shelltool import _CMD_FIELDS, SHELL_TOOL_NAMES, find_shell_tool, shell_args, with_time_budget
from .toolargs import PATH_KEYS, parse_args
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
# The write class is ONE predicate (`_is_write_tool`, membership in _WRITE_TOOLS below) — shared by
# the repetition signature AND the wheel-spin/truncation guards, so a route can't be a write to one
# and not the other. (A loose substring regex was tried and split the two: it mis-classed `write_stdin`
# as a file write and missed nothing the exact set doesn't.)
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
BRIEFING_OPEN = "⟦ctx:briefing⟧"
BRIEFING_CLOSE = "⟦/ctx:briefing⟧"
CONTINUATION_MARKER = "⟦ctx:continuation⟧"   # leads cria's compaction reframe — marks it as cria
#   scaffolding so classify.latest_user_text skips it (it reads as reasoning and mis-routes the role)
# The re-anchor note injected on the FIRST turn after a detected harness compaction (the plan-off
# path — the loop instead re-plans from the summary) lives in prompts/reanchor.txt. Seed incident: a
# compacted model treated its OWN earlier work as a previous agent's and duplicated a file under a
# different dir; the note re-orients it to inspect before creating.
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


def _is_write_tool(name) -> bool:
    """The single write-class predicate — used by the repetition signature and the wheel-spin /
    truncation guards alike, so a named tool is a write to all of them or to none."""
    return name in _WRITE_TOOLS


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
    # The harness's workspace cwd (its OWN repo), persisted across turns: set from the env-context <cwd>
    # when present, KEPT when a later turn (harness compaction) drops it — so the gate/steer/disk-facts
    # always target the harness's repo, NEVER cria's own dir. None = still unknown (callers skip, never ".").
    workspace_root: str | None = None
    # Whole-task satisfaction re-checks on a plan-ON completion (all steps verified INDIVIDUALLY, but is
    # the user's task actually done end-to-end?). Bounds the re-open-and-fix loop so a task the coder
    # genuinely can't finish still completes instead of looping forever. Parity with the plan-off critic.
    completion_checks: int = 0
    # Per-search reasoned assist. OUTGOING: judge the query before it runs (guard_search_query) — cached
    # per query in ``query_verdicts``. INCOMING: when the model READS a spilled search file, judge its
    # relevance (_judge_search_reads); an off-target file goes in ``poisoned_search_files`` so its reads
    # are stripped going forward, and ``search_recommend`` steers the better query.
    judged_search_files: set = None     # spill files already read-judged (don't re-judge)
    poisoned_search_files: set = None   # spill files judged off-target → strip their reads going forward
    search_recommend: str = ""          # the last recommended query to steer
    query_verdicts: dict = None         # outgoing query -> (on_target, recommendation); cached per query
    rehunt_verdicts: dict = None        # outgoing query -> is it a NEW direction? (cached; see judge_rehunt)
    web_session: str = ""               # the key webfetch's per-session search/fetch gates are keyed by,
    #                                     so the loop can ask about the pair those gates would act on
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
    steer_source: str = ""  # human label of which guard produced the pending steer (for the ⟦cria⟧ note)
    coder_turns: int = 0  # acting coder turns since the last gate — drives the PERIODIC check-in
    drive_count: int = 0  # total plan-off drives this session — drives the periodic SATISFACTION check
    periodic_probe: bool = False  # a periodic check-in gate is in flight (insert its ground truth, no verdict)
    last_gate_red: bool = False  # the most recent gate/check-in found real error-class problems (RED). The
    # plan-off satisfaction judge gates on this: while the deterministic checks already say NOT-done, the
    # LLM done-judge is redundant (both say not-done) and — for a model that can't help emitting a "run the
    # tests" tool call instead of a verdict — pure wasted, always-fail-closed calls. Only spend it on GREEN.
    # STALL tracking (NOT termination — the stall terminator was removed; cria never ends a non-converging
    # session or hands back to a human). A RED-gate streak with the SAME unchanged finding = the coder is
    # stuck on one thing; that drives the REASONED thrash-assist (a concrete unstick step), never a give-up.
    gate_stall: int = 0        # consecutive RED gates with the SAME finding (no progress); reset on change/GREEN
    gate_sig: str = ""         # the last RED finding, to detect an unchanged signature
    last_gate_testless: bool = False  # the last GREEN gate ran NO tests (0 collected / no test probe) — a
    last_gate_skipped: int = 0        # tool-reported SKIPPED count from the last gate's test run — a suite
    # can pass while SKIPPING the checks that matter (0728-m11: live tests skipTest() on the exact 404
    # that proves the resolver broken; "3 passed, 2 skipped" read as green). Same evidence posture:
    # VACUOUS green. Fed to the satisfaction judge as EVIDENCE (not a deterministic block): the judge
    # holds the task and decides whether tests were even part of the ask (a script task is legitimately
    # testless-green; deterministically blocking would wedge it AND push a weak model to fabricate tests).
    # Completion-gate-on-"done" state (plan-off path; the loop uses PlanSession's own fields):
    done_probe: bool = False  # a probe verifying a "done" claim is in flight
    pending_done: str = ""  # the coder's held "done" text, forwarded if the gate passes
    leg0_nudged: bool = False  # the no-tools act-first nudge fired once this session
    # NB: there is deliberately NO search-escape state here. cria used to SUBSTITUTE a web_fetch for a
    # search-looping coder's own web_search (streak/volume counters, a convention URL, a domain-root
    # floor when the reasoner punted). Substituting the coder's action is the REDIRECTION class, and the
    # punt-floor was a deterministic fallback behind a reasoner call — both are what the doctrine forbids
    # (principles #1, #2, #4). The search gate still REFUSES a near-duplicate search and steers "read the
    # source you named" — a steer the coder can disregard, not an action taken for it.
    fetched_pages: dict = None  # url -> (status, routes): DURABLE fetch facts a steer cites after the
    # real result has been floored out of the window (else a steer can't counter a late spiral)


@dataclass
class PlanSession(GuardState):
    plan: Plan = field(kw_only=True)  # required; kw_only so it may follow GuardState's defaulted fields
    # Single-item plan-off mode: the whole task is ONE implicit step. When set, the driver uses
    # raw-task framing (no "step k/n") and runs the off-ramp a finite multi-step plan doesn't need
    # (the task-level satisfaction/done-critic). The explicit flag — NOT len(items)==1 —
    # is the key: a genuine planner 1-step plan must keep step framing and skip those off-ramps.
    synthetic: bool = False
    phase: Phase = Phase.WORK
    summary: str = ""  # running summary of completed steps (the cheap plan-structure axis)
    prior_work: str = ""  # earlier finished work (briefing re-read from history / harness-summary tail)
    compact_state: selfcompact.CompactState = field(default_factory=selfcompact.CompactState)  # mid-session rollup
    compact_pending: bool = False  # a step just verified → force a rollup next turn (clean prior-step signals)
    verify_fails: int = 0
    # CRITIC judgements only — the subset of verify_fails that means "the critic read the evidence and
    # said this step's intent is unmet". `verify_fails` also counts a RED GATE and the LEG-0 "no tools
    # used" nudge, and the stuck-step rescue must not fire on those: a gate failure means FIX THE CODE,
    # not "this step may be impossible". Measured (run 0727-170754): step 3 "Write unit tests…" took
    # one no-tools and two probe-failed, the rescue re-derived it into "Add retry logic…", and the
    # coder's in-flight test work was then failed as "unrelated" against a goal it was never given.
    critic_fails: int = 0
    step_tool_calls: int = 0  # coder tool calls forwarded THIS step (the changed-anything leg)
    thrash_replanned: bool = False  # the tool-call-thrash re-derive fired once this STEP (anti-churn bound)
    verify_replanned: bool = False  # the verify-fail re-derive fired once this STEP (anti-churn bound)
    flail_steers_this_step: int = 0  # flail steers authored this STEP (capped at MAX_FLAIL_STEERS_PER_STEP)
    flail_cap_logged: bool = False    # the cap-reached notice is emitted ONCE per step, not per drive
    leg0_nudged: bool = False  # the no-tools nudge fired once this step (bounds in-process recursion)
    last_gate_flag: str = ""  # previous gate's block-nudge, for convergence/stall detection
    gate_git: str = ""  # last gate's git-status hash (workspace-change signal across gates)
    pending_coder_text: str = ""  # the coder's "done" claim, held for the critic after the probe
    recent_reasoning: list[str] = field(default_factory=list)  # coder's last FLAIL_WINDOW reasonings (flail detector)
    last_flail_drive: int = -100  # drive_count at the last flail diagnosis (cooldown gate)

    def __post_init__(self) -> None:
        # SEED the durable fetch ledger with what the PLANNER's research already read. Those facts
        # were being thrown away with the gather transcript: measured (run 0726-221401) the planner
        # had fetched the real spec — `/handles/{handle}` and `/holders/{address}` — and the coder,
        # never shown them, invented `/handle/{handle}` and 404'd. Seeding here rather than at the
        # four PlanSession call sites so no construction path can miss it. Purely additive: the
        # ⟦ctx:facts⟧ anchor that renders these already exists, and a task whose planner fetched
        # nothing seeds nothing.
        facts = dict(getattr(self.plan, "gather_facts", None) or {})
        if facts:
            self.fetched_pages = _merge_fetches(dict(self.fetched_pages or {}), facts)


# GROUND-TRUTH gate: composed per verification by probegate.plan_gate (syntax floor +
# repo-discovered top probe + top TEST probe + git snapshot), run BY THE HARNESS, and
# interpreted through the ported probe modules. Replaces the old fixed Python-only
# _PROBE_COMMAND — the gate now adapts to whatever ecosystems the workspace actually has.


# How many session SHAPES to retain (conversation-root fingerprints, for harness-compaction
# detection). Cheap (a hash + an int each); evicted oldest-first.
_MAX_SHAPES = 256
# The gate normally fires only on a "done" claim or a guard trip, so an acting-heavy model can edit
# for a long stretch with NO ground truth (it circled on a broken pyproject.toml for ~90 turns). Run
# the checks every N acting coder turns too and INSERT the result (no verdict) so the model sees the
# syntax/lint/test state early, not only when it thinks it's finished.
GATE_EVERY_CODER_TURNS = 15

# On a plan-ON completion (all steps verified individually), run the WHOLE-TASK satisfaction critic
# before declaring done — a multi-step plan can pass every step yet not actually work (the milestone
# run: each step green, but the resolver 404'd on the wrong endpoint and nothing checked end-to-end).
# When it says not-done, re-open with ONE corrective step and re-drive. Bounded so a task the coder
# genuinely can't finish still completes rather than looping forever (the plan-off path relies on the
# harness stopping; cria DRIVES the plan loop, so it must bound the retries itself).
MAX_COMPLETION_CHECKS = 4
_COMPLETION_FIX_PREFIX = "The task is not yet fully satisfied — fix this before finishing: "

# Periodic SATISFACTION check (plan-off): a long session can finish the work but never STOP — the coder
# keeps inventing completion actions (a .task_complete marker, a hallucinated checkpoint tool) so cria's
# no-tool-call done-detection never triggers. Starting at drive `start`, every `every` drives, the
# reasoner judges the WHOLE user task against the real work; if satisfied cria verifies against the
# repo's checks (the same objective backstop the done-gate uses) and ends the turn. The cadence is
# operator-tunable ([context] satisfaction_check_start / satisfaction_check_every) — different models
# spiral at different rates; either set to 0 DISABLES it.


def satisfaction_check_due(drive_count: int, start: int, every: int) -> bool:
    if start <= 0 or every <= 0:  # disabled
        return False
    return drive_count >= start and (drive_count - start) % every == 0


# THRASH-ASSIST threshold (plan-off). When the SAME check error has persisted this many gate cycles (the
# coder is STUCK on one thing, not just churning), replace the raw ground-truth insertion with a REASONED
# thrash-diagnosis + one concrete next step to get the coder UNSTUCK. cria NEVER gives up on a
# non-converging session (the stall terminator + human-escalation were removed — the mission is for the
# model to succeed on its OWN); it just keeps trying to unstick it.
THRASH_STALL_CYCLES = 2

# STUCK-STEP re-plan threshold. A step advances ONLY on a genuine pass — there is deliberately no
# advance-on-unverified cap (real failing checks must be fixed, never skipped). But a MISCONCEIVED step
# — a category-error or confused step the weak planner wrote whose CHECKS pass yet whose critic keeps
# judging its INTENT unmet — can never be satisfied, so the coder re-nudges forever (observed live: a
# "extract the JSON schema to obtain field VALUES" step looped 16 min). After this many consecutive
# CRITIC verify-fails on one step (NOT gate/real-error fails), hand the living-plan reasoner the real
# work done so it can RE-DERIVE that step from ground truth (or confirm the work already satisfies it).
# Re-attempted every STUCK_STEP_REPLAN fails so a declining reasoner doesn't burn a call each turn.
STUCK_STEP_REPLAN = 4

# STUCK-STEP re-plan threshold for a TOOL-CALL thrash. The above triggers on CRITIC verify-fails, but a
# coder can loop on tool calls for a whole step (write→exec→write…, ignoring the guards' steers) WITHOUT
# ever signalling completion — so verify never runs and that escape never accrues (observed live: 30+
# acting turns on a "create the package directory" step that write_file-vs-mkdir-conflicted, 39 steers
# ignored). After this many ACTING turns on one step without advancing, re-derive the step from ground
# truth too (it may simplify an over-engineered step — e.g. a package scaffold → a flat script). Fired
# periodically (every N turns) so a productive-but-long step that yields an unchanged plan isn't churned.
STEP_THRASH_REPLAN = 12


def track_gate_progress(gs: GuardState, finding: str) -> None:
    """Shared plan-off gate-progress tracking. ``finding`` = the RED block-nudge/ground-truth text, or
    a FALSY value on a GREEN/clean gate. Maintains the identical-finding stall (same error unchanged
    across gates = no progress → the reasoned thrash-assist). A COULDN'T-RUN gate must NOT call this
    (it is a neutral non-signal — neither red nor green)."""
    if not finding:
        gs.gate_stall = 0
        gs.gate_sig = ""
        return
    if finding == gs.gate_sig:
        gs.gate_stall += 1
    else:
        gs.gate_stall = 1
        gs.gate_sig = finding


def _satisfaction_verdict(system: str, user: str, reasoner_chat, reasoner_role, rlog, *, reasoning_off: bool, workspace_root: str = "") -> dict | None:
    """One critic call → the parsed {"satisfied": …} dict, or None if the model produced no parseable
    JSON. Mirrors the plan-path _verdict: NOT summarize() — summarize returns free text and only retries
    on EMPTY, but a reasoning-ON critic pass here does not go empty, it ROLE-PLAYS THE CODER (reasons
    'reinstall and run tests', leaking a Bash/Read tool call) and returns non-empty non-JSON, so the
    retry never fired and every verdict failed closed. Parse the completion directly and let the caller
    retry reasoning-OFF on a parse miss — reasoning-off makes the model answer the JSON verdict directly
    instead of thinking itself into the coder's seat."""
    role = reasoner_role
    if reasoning_off:
        role = replace(role, reasoning="off") if role is not None else None
    try:
        # The careful pass may INSPECT (the shared judge loop; operator directive) — the completion
        # critic authors corrective steps the coder must obey, and blind it theorized a wrong
        # endpoint from a field-name collision. The reasoning-off retry stays toolless.
        comp = _judge_completion(
            reasoner_chat, role, system, user, rlog,
            phase="satisfaction" + ("-noreason" if reasoning_off else ""),
            workspace_root="" if reasoning_off else workspace_root,
            force_think_off=reasoning_off)
        if massage.is_truncated(comp):
            # Cut at the cap → not a verdict. Parsing it risks a partial object that happened to
            # close, and the caller's retry/fail-closed path is the honest answer.
            rlog.emit("loop.satisfaction_truncated", level="warn")
            return None
        vtext = _completion_text(comp)
        if reasoner_role is not None:
            vtext = reasoner_role.clean_content(vtext)  # drop leaked reasoning when off
        return extract_json_object(vtext)
    except Exception as e:
        rlog.emit("loop.satisfaction_error", level="warn", error=str(e))
        return None


def judge_query(reasoner_chat, reasoner_role, task: str, query: str, rlog, coder_tools: str = "") -> tuple[bool, str]:
    """Judge an OUTGOING web_search query BEFORE it runs: is it searching for what the task needs? Returns
    (on_target, recommendation) — recommendation is the better search string OR a concrete URL to fetch
    instead (the caller substitutes a web_fetch when it's a URL). Fails OPEN (on_target True, no
    recommendation) on a parse miss or no reasoner — never derail a search we couldn't judge."""
    if reasoner_role is None or not (task.strip() and query.strip()):
        return True, ""
    vtext = summarize(reasoner_chat, reasoner_role, prompts.load("search_query_judge"),
                      prompts.render("search_query_judge_user", task=task, query=query), rlog,
                      phase="reasoner", coder_tools=coder_tools) or ""
    obj = extract_json_object(strip_think(vtext))
    if not isinstance(obj, dict):
        return True, ""
    return obj.get("on_target") is not False, str(obj.get("recommendation") or "").strip()


_CALL_WRAPPED = re.compile(r"""\s*\w+\s*\(\s*(['"])(.+?)\1\s*\)\s*\Z""", re.S)
_QUOTED_SPAN = re.compile(r"""(['"])([^'"]{2,})\1""")


def _same_query(a: str, b: str) -> bool:
    """Two search queries that would send the same thing to the search engine — case and surrounding
    whitespace are not a redirect."""
    return " ".join((a or "").lower().split()) == " ".join((b or "").lower().split())


def _usable_query(rec: str) -> str:
    """The judge's recommendation AS A SEARCH QUERY, or "" when it is not one.

    `recommendation` is written straight into the coder's web_search arguments, so whatever shape the
    reasoner answered in becomes the literal query. MEASURED across every session on 2026-07-27: 53 of
    112 searches (47%, 87% in one run) were rewritten this way, into things like
    `web_search('Ada Handles API documentation')` and `Search for "X" or "Y"` — the coder then searched
    the web for that literal string, and in one case a perfectly good query (`api.handle.me
    openapi.json`) was replaced by prose.

    Shape, never keywords: a tool-call wrapper yields its argument; exactly ONE quoted span yields that
    span; TWO or more are ambiguous and yield "" so the caller leaves the coder's own query alone —
    cria substitutes only when it has a real query to substitute."""
    rec = (rec or "").strip()
    if not rec:
        return ""
    m = _CALL_WRAPPED.fullmatch(rec)
    if m:
        return m.group(2).strip()
    spans = _QUOTED_SPAN.findall(rec)
    if len(spans) > 1:
        return ""              # "X" or "Y" — cria does not pick for the coder
    if len(spans) == 1:
        return spans[0][1].strip()
    return rec


def judge_rehunt(reasoner_chat, reasoner_role, task: str, query: str, prior: str, rlog,
                 coder_tools: str = "") -> bool:
    """Is ``query`` a genuinely NEW direction rather than a re-hunt of ``prior``?

    The repeat gate refuses a search on four hand-tuned word-overlap constants, and refusing the
    model's own tool call is a redirection — cria has already deleted a sibling threshold rule for
    over-firing ("0.6 core-overlap binds distinct searches"). Whether two queries are the same hunt
    or different ones is a judgement, so the overlap test stays as the cheap TRIGGER and this makes
    the actual call.

    Returns True only on a clear "different hunt". Anything else — no reasoner, an unparseable reply,
    an error — leaves the gate's own verdict standing, so this can only ever make cria refuse LESS,
    never more, and a session without a reasoner behaves exactly as before."""
    if reasoner_role is None or not (query.strip() and prior.strip()):
        return False
    vtext = summarize(reasoner_chat, reasoner_role, prompts.load("search_rehunt_judge"),
                      prompts.render("search_rehunt_judge_user", task=task, query=query, prior=prior),
                      rlog, phase="reasoner", coder_tools=coder_tools) or ""
    obj = extract_json_object(strip_think(vtext))
    return isinstance(obj, dict) and obj.get("new_direction") is True


def judge_search(reasoner_chat, reasoner_role, task: str, query: str, results: str, rlog, coder_tools: str = "") -> tuple[bool, bool, str]:
    """Reasoned per-search assist: given the task, the QUERY the coder used, and the RESULTS it got back,
    judge whether the query is on-target and whether the results are on-target, and recommend a better
    query. Returns (query_on_target, results_on_target, recommended_query). Fails OPEN (both True, no
    recommendation) on a parse miss — a judge that can't judge must never STRIP real results (a footgun:
    losing correct search results is worse than tolerating some noise). Only a definite ``false`` strips."""
    if reasoner_role is None or not (task.strip() and results.strip()):
        return True, True, ""
    vtext = summarize(reasoner_chat, reasoner_role, prompts.load("search_judge"),
                      prompts.render("search_judge_user", task=task, query=query or "(none)",
                                     results=results), rlog, phase="reasoner", coder_tools=coder_tools) or ""
    obj = extract_json_object(strip_think(vtext))
    if not isinstance(obj, dict):
        return True, True, ""
    return (obj.get("query_on_target") is not False,
            obj.get("results_on_target") is not False,
            str(obj.get("recommended_query") or "").strip())


REPLAN_TRIGGER_ADVANCE = "A step just finished and was verified."
REPLAN_TRIGGER_STALLED = ("Progress has STALLED on the current step — the plan may be stale or "
                          "mis-scoped. No step was just verified.")


def reassess_remaining(reasoner_chat, reasoner_role, task: str, completed: str, remaining: str,
                       evidence: str, rlog, coder_tools: str = "",
                       trigger: str = REPLAN_TRIGGER_ADVANCE) -> list[str] | None:
    """Dedicated reasoner call for the LIVING plan: re-derive the REMAINING plan steps from the work
    ACTUALLY done (real tool evidence), so the plan adjusts to reality at each verification instead of
    marching a stale guess. Returns the refined remaining step-text list (may be shorter/reworded/
    reordered, or [] when the evidence shows nothing is left), or ``None`` to leave the plan UNCHANGED —
    the fail-safe on a parse miss / decline / no reasoner, because silently blowing away a plan on a bad
    parse is far worse than carrying a stale step (the step critic still guards every step)."""
    if reasoner_role is None or not remaining.strip():
        return None
    # The trigger sentence must be TRUE: the stuck/thrash paths reuse this call, and the old
    # hardcoded "A step just finished and was verified" asserted an event that had not happened
    # (run 0729-gemma4 call 0048 — a thrash-triggered replan told the reasoner a step verified).
    text = summarize(reasoner_chat, reasoner_role,
                     prompts.render("replan", TRIGGER=trigger),
                     prompts.render("replan_user", task=task, completed=completed or "(none)",
                                    remaining=remaining, evidence=evidence or "(no actions recorded yet)"),
                     rlog, phase="reasoner", coder_tools=coder_tools) or ""
    obj = extract_json_object(strip_think(text))
    if not isinstance(obj, dict) or not isinstance(obj.get("steps"), list):
        return None  # unparseable / wrong shape → keep the plan exactly as it was
    if not obj["steps"]:
        return []  # the reasoner says nothing remains → the plan is complete
    # _clean_step coerces a dict item ({"step": "…"}, which a small model emits instead of a bare string)
    # to its text — else the step becomes the dict repr "{'step': …}" (the observed leak).
    cleaned = [c for x in obj["steps"] if (c := _clean_step(x))]
    if not cleaned:
        return None  # no usable step text → keep the plan we had
    # Same reasoner NOISE judgment the INITIAL plan gets (reasoned_noise_indices): drop a re-derived step
    # that codified a bare command, dictated literal code, or a speculative guess — a re-derivation
    # grounded in the coder's FAILED work otherwise codifies its guessed endpoint into an authoritative
    # step (observed: a research step re-derived into "call requests.get('<root>')", shipped as a 404/403).
    # replan.txt already tells the reasoner to avoid these; this is the focused safety judgment. An
    # all-noise re-derivation → None (keep the prior plan), never an empty plan.
    _ask = lambda sysp, usr: summarize(reasoner_chat, reasoner_role, sysp, usr, rlog, phase="reasoner")
    drop = reasoned_noise_indices(_ask, task, cleaned)
    kept = [s for i, s in enumerate(cleaned) if i not in drop]
    # SAY WHAT THE JUDGE DID. The initial plan reports this (plan.noise_dropped / plan.noise_all_kept);
    # the re-derivation ran the same judge and reported nothing, so a tail that came back carrying a
    # bare shell command was indistinguishable from one the judge had cleaned. Measured (run
    # 0727-164951): a good six-step plan — step 2 "Create a Python function resolve_handle(handle)" —
    # was re-derived twice (5→8, then 7→3) into a plan whose step 2 was `grep -n 'resolved_addresses'
    # <file>` and step 3 "Run unit tests": a bare command and plumbing, the two categories this judge
    # deletes. Nothing in the log said whether it ran, kept them, or dropped something else.
    rlog.emit("loop.replan_noise", dropped=len(drop), kept=len(kept),
              level="warn" if not kept else "info")
    if not kept:
        return None
    # COVERAGE — the same ENFORCED check the initial draft gets (Planner._missing_deliverables), on
    # the plan as it would stand: completed steps + the re-derived tail. replan.txt carries the rule
    # as prose ("every deliverable ... must still be covered") and prose was not enough — measured
    # (run 0728-m6): a coverage-checked six-step draft was thrash-re-derived into ONE step, silently
    # dropping unit tests + the live test + the README, and the run ended "satisfied" with a named
    # deliverable absent from the workspace. A tail that drops deliverables is REFUSED — the plan
    # stays untouched (the same fail-safe as a parse miss; the step critic still guards every step
    # and the done-critic still backstops), and the refusal is TRACED, never silent.
    done_texts = [ln[2:].strip() for ln in (completed or "").splitlines() if ln.startswith("- ")]
    missing = missing_deliverables(_ask, task, done_texts + kept)
    if missing:
        rlog.emit("loop.replan_uncovered", level="warn", missing=", ".join(missing))
        return None
    # NO research-first re-prepend here — and none at plan time either. cria does not AUTHOR plan steps:
    # injecting "web_fetch the named source" was cria planning, and pinning it made a possibly-wrong step
    # an inescapable mandate. The general mechanisms carry it instead — plan.txt tells the drafter to
    # research first, the critic clears a research step on facts obtained, and the durable ⟦ctx:facts⟧
    # ledger keeps the real endpoints in front of the coder across compaction.
    return kept


def _judge_completion(chat_fn, role, system: str, user: str, rlog, *, phase: str,
                      workspace_root: str = "", max_tokens: int = 8192,
                      force_think_off: bool = False) -> dict:
    """ONE judge completion whose author may first LOOK — the shared inspection loop behind the step
    critic AND the completion critic (operator directive: judges get real read-only tools, not just a
    snapshot). With a ``workspace_root``, the judge is offered verifytools (list_dir/read_file,
    cria-executed, workspace-contained) and each round is fed back as PROTOCOL — the planner-gather
    pattern — until it answers, or VERIFY_MAX_ROUNDS is spent and the tools are withdrawn with the
    answer-now steer. Returns the FINAL parsed completion; the caller keeps its own truncation/parse
    handling. Measured need for the completion critic specifically: the toolless satisfaction judge
    authored a corrective step steering the coder to /stats ("total handles" BY FIELD NAME — the
    GLOBAL count, not the holder's) because it could not read the spec section that distinguishes
    them, and it ruled a run satisfied while the inventory in its prompt showed no README."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    inspectable = bool(workspace_root) and os.path.isdir(workspace_root)
    rounds = 0
    while True:
        body: dict = {"stream": False, "temperature": 0, "max_tokens": max_tokens,
                      "messages": list(messages)}
        if inspectable and rounds < verifytools.VERIFY_MAX_ROUNDS:
            body["tools"] = verifytools.VERIFY_TOOLS
        if role is not None:
            role.apply(body, internal=True, rlog=rlog)
        elif force_think_off:  # no role configured, but still force the think block off
            body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        rlog.phase = phase
        comp = _parse_completion(chat_fn(body, rlog))
        msg = ((comp.get("choices") or [{}])[0].get("message")) or {}
        calls = msg.get("tool_calls") or []
        if not (inspectable and calls and rounds < verifytools.VERIFY_MAX_ROUNDS):
            return comp
        rounds += 1
        messages.append({"role": "assistant", "content": msg.get("content") or None,
                         "tool_calls": calls})
        for tc in calls:
            fn = tc.get("function") or {}
            try:
                targs = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                targs = None
            out = (verifytools.execute(fn.get("name") or "", targs, workspace_root)
                   if isinstance(targs, dict) else "[unparseable tool arguments — call again with valid JSON]")
            messages.append({"role": "tool", "tool_call_id": tc.get("id") or f"vt{rounds}",
                             "content": out})
        rlog.emit("loop.verify_inspect", round=rounds, calls=len(calls))
        if rounds == verifytools.VERIFY_MAX_ROUNDS:
            messages.append({"role": "user", "content": verifytools.ANSWER_NOW})


def _confirm_completion(claim: str, reason: str, workspace_root: str, reasoner_chat, reasoner_role,
                        rlog, *, phase: str) -> tuple[bool, str]:
    """The APPROVE-path brake — one narrow, reasoning-off check run ONLY on a done/satisfied verdict:
    is the completion claim CONSISTENT with (a) the fresh on-disk listing and (b) the verdict's own
    reason? Measured need (n=3 in one day, both judges): a judge holding contrary ground truth in its
    prompt ruled from the coder's NARRATIVE — passed "write unit tests" against a complete inventory
    of three tmp spills while citing a test function that exists nowhere (m8); ruled satisfied with
    no README in the listing (m6); attached a full failure analysis to a DONE (m7). The checker sees
    ONLY claim + reason — the coder's summary, the confabulation fuel, is deliberately absent — and
    INSPECTS the workspace itself via the shared read-only tools rather than being handed a pasted
    listing (operator's call, twice over: a real repo's complete listing can be massive, and a judge
    that must look cannot rubber-stamp a narrative). Returns (confirmed, why). No workspace to
    inspect → confirmed (nothing to check against); an unparseable check KEEPS the verdict (the
    brake is additive, never a new wedge) but is traced."""
    if not workspace_root or not os.path.isdir(workspace_root):
        return True, ""
    labels = prompts.load_map("verify_confirm")
    user = prompts.fill(labels["user"], step=claim, reason=reason or "(none stated)")
    role = replace(reasoner_role, reasoning="off") if reasoner_role is not None else None
    comp = _judge_completion(reasoner_chat, role, labels["system"], user, rlog,
                             phase=phase, force_think_off=True, workspace_root=workspace_root)
    vtext = _completion_text(comp)
    if reasoner_role is not None:
        vtext = reasoner_role.clean_content(vtext)
    obj = extract_json_object(strip_think(vtext))
    if not isinstance(obj, dict) or not isinstance(obj.get("consistent"), bool):
        rlog.emit("loop.confirm_unparsed", level="info", phase=phase)
        return True, ""
    return obj["consistent"], str(obj.get("why") or "").strip()


# A judge holds ONLY read-only inspection tools (list_dir/read_file) — a verdict whose reason
# claims it ran, curled, fetched or tested something is FABRICATED evidence (observed: a
# satisfaction verdict said "confirmed by curling api.handle.me/goose"; its own reasoning shows it
# merely INTENDED to curl via exec_command — a tool it does not hold — and the retry asserted the
# intent as fact; that false fact became pinned plan-step text, run 0729-mellum2 calls 0153-0154).
# Third-person reports ("the coder ran pytest") don't match — only the judge claiming its own acts.
_JUDGE_ACTION_CLAIM = re.compile(
    r"(?i)\b(?:i|we)\s+(?:ran|executed|curled|fetch(?:ed)?|tested)\b"
    r"|\bconfirmed by (?:curl|runn?)ing\b")


def _claims_impossible_action(obj: dict | None, rlog, phase: str) -> bool:
    """True (and traced) when a parsed verdict's reason claims a judge-performed action the judge
    cannot perform — the caller treats the verdict as unusable, which routes to the normal
    reasoning-off retry / fail-closed path instead of letting fabricated evidence stand."""
    reason = str((obj or {}).get("reason") or "")
    if _JUDGE_ACTION_CLAIM.search(reason):
        rlog.emit("loop.verdict_fabricated_action", level="warn", phase=phase,
                  head=_clip(reason, 120))
        return True
    return False


def _fill_missing_verdict_flag(obj: dict, flag: str, rlog, phase: str) -> dict | None:
    """A verdict object MISSING its verdict key ("done"/"satisfied") is not a verdict — unless the
    schema's own contract decides it: ``proposed_fix`` is defined as "" when the flag is true and
    a concrete action when false (verify.txt / satisfaction prompts), so its presence
    disambiguates a keyless verdict. Returns the object with the flag filled (traced via rlog —
    an inference must never bind silently), or None when nothing sound can fill it, which routes
    the caller to its normal parse-miss retry.

    Observed live (suite run, qwythos): the judge reasoned "done: true", then emitted
    ``{"reason": …, "proposed_fix": ""}`` with NO done key. ``bool(obj.get("done"))`` silently
    read that as NOT-done — a contradiction the coder was nudged with (a reason arguing complete
    under a NOT-DONE verdict), re-verified 4× in 2 minutes, and the parse-miss retry never fired
    because the JSON parsed fine. A doom loop: the retry pass may only REJECT, so a model that
    consistently omits the key could never pass the step at all. An inferred TRUE is still not
    blindly trusted — it passes through the approve-path confirm brake like any other approval."""
    if flag in obj:
        return obj
    if "proposed_fix" not in obj:
        return None
    inferred = not str(obj.get("proposed_fix") or "").strip()
    rlog.emit("loop.verdict_flag_inferred", flag=flag, inferred=inferred, phase=phase)
    return {**obj, flag: inferred}


def judge_satisfaction(task: str, evidence: str, reasoner_chat, reasoner_role, rlog, coder_tools: str = "",
                       workspace_root: str = "", routes: str = "") -> tuple[bool, str]:
    """Reasoner critic for the WHOLE user task (task-level, unlike the step-level _verify): is the user's
    original request satisfied by the REAL work (the coder's tool output — ground truth, not its claim)?
    Returns (satisfied, reason). Reasoning-ON first, then reasoning-OFF on a parse miss (the reasoner
    otherwise role-plays the coder and never emits the verdict). Fails CLOSED — an unparseable verdict is
    NOT satisfied, so a session is never ended on the critic's silence."""
    if not task.strip():
        return False, "no task text to judge", ""
    system = prompts.load("satisfaction")
    user = prompts.render("satisfaction_user", task=task,
                          evidence=evidence or "(no actions recorded yet)")
    if coder_tools:  # reasoning about the coder's work → give it the coder's tools (see _verify)
        user = user + "\n\n" + prompts.render("reasoner_coder_tools", tools=coder_tools)
    obj = _satisfaction_verdict(system, user, reasoner_chat, reasoner_role, rlog, reasoning_off=False,
                                workspace_root=workspace_root)
    if obj is not None:
        obj = _fill_missing_verdict_flag(obj, "satisfied", rlog, "satisfaction")
    if obj is not None and _claims_impossible_action(obj, rlog, "satisfaction"):
        obj = None   # fabricated evidence → same path as an unparseable verdict (retry, fail closed)
    if obj is not None:
        # The careful (reasoning-ON) pass produced a clean verdict — the ONLY pass trusted to APPROVE
        # ending the task, because approving requires the verification a reasoning-off judge can't do
        # (catching a placeholder/mocked "solution" — e.g. hardcoding the task's example handles so the
        # unit tests pass while nothing really resolves).
        satisfied = bool(obj.get("satisfied"))
        if satisfied and workspace_root:
            # The approve-path brake (see _confirm_completion): "satisfied" must be consistent with
            # the FRESH on-disk listing and with its own stated reason (m6 ended a run with no README
            # while the listing in the judge's prompt proved its absence).
            confirmed, why = _confirm_completion(task, str(obj.get("reason") or ""), workspace_root,
                                                 reasoner_chat, reasoner_role, rlog,
                                                 phase="satisfaction-confirm")
            rlog.emit("loop.satisfaction_confirm", confirmed=confirmed)
            if not confirmed:
                return False, why or str(obj.get("reason") or "a named deliverable is not on disk"), ""
        # The ACTION comes back separately so a caller building a plan step can use the fix alone —
        # the old single string (framing + reason essay + fix) became a whole step verbatim
        # (run 0729-mellum2: a diagnostic paragraph as step 3, held for 118 calls).
        return satisfied, _verdict_nudge(obj, satisfied, routes), str(obj.get("proposed_fix") or "").strip()
    # No parseable careful verdict (the reasoner over-thought, or leaked a spurious tool call instead of
    # the JSON). A reasoning-OFF retry can RECOVER a verdict, but a reasoning-off judge is a rubber
    # stamp — competent to REJECT, not to APPROVE. So use it only to confirm NOT-satisfied; a
    # "satisfied" that exists ONLY because the careful pass failed is downgraded and we fail CLOSED. A
    # false "done" over fake work is far worse than a few more work turns.
    retry = _satisfaction_verdict(system, user, reasoner_chat, reasoner_role, rlog, reasoning_off=True)
    if retry is None:
        return False, "unverified (no parseable verdict)", ""
    if retry.get("satisfied"):
        rlog.emit("loop.satisfaction_failclosed", level="info")
        return False, "unverified — the careful check could not confirm completion; keep working", ""
    return False, _verdict_nudge(retry, False, routes), str(retry.get("proposed_fix") or "").strip()


def satisfaction_done_note(reason: str) -> str:
    """The completion text forwarded when the satisfaction check + repo checks agree the task is done."""
    return f"Task complete — verified by the completion check and the repo's own checks. {reason}".strip()


# The critic/re-derivation evidence budget, in characters. This is a prompt cria COMPOSES for a judge,
# not something the coder reads — and principle #5's counter-nuance is explicit that bounding a composed
# prompt breaks no rule, while over-applying never-truncate to one is itself a documented footgun.
# Observed live (run 0726-203600, stuck on step 5): the work log grew 34KB → 106KB → 223KB across
# re-nudges on ONE step; at 223KB the critic call needed a floor REFIT, then errored outright, so the
# verdict came back "unverified (no parseable verdict)" — which fails CLOSED and re-nudges, which grows
# the evidence again. A doom loop where the judge can no longer answer at all.
EVIDENCE_BUDGET_CHARS = 24000


def _bound_evidence(log: str) -> str:
    """The work log bounded to the MOST RECENT actions, with the elision DISCLOSED.

    Recency is what a step verdict turns on ("did the coder do this step?"), so the tail is the part
    worth keeping; the durable fetch facts are appended separately and are never dropped by this. The
    head is replaced by a labelled marker rather than silently cut — a judge that is told it is seeing
    a window can weigh it, one that isn't will treat a partial log as the whole history."""
    if len(log) <= EVIDENCE_BUDGET_CHARS:
        return log
    tail = log[-EVIDENCE_BUDGET_CHARS:]
    nl = tail.find("\n")            # start at a clean action boundary, never mid-line
    if 0 <= nl < 400:
        tail = tail[nl + 1:]
    dropped = len(log) - len(tail)
    return (f"[{dropped:,} characters of EARLIER actions elided to keep this readable — the most recent "
            f"actions follow in full; the durable fetch facts below are complete and unaffected]\n" + tail)


class LoopStore:
    """The loop's server-side session state: live plans and each session's conversation-root
    SHAPE (structural harness-compaction detection + a one-bit `done` marker). DETECTION state
    only — the completion BRIEFING is never stored here; it rides in the conversation (embedded
    in the closing message) and is re-read from the history the harness sends back.

    ``state_path`` (optional) persists the shapes as one small JSON file so a cria restart
    doesn't orphan detection. Live ``PlanSession``s are deliberately NOT persisted (a Plan
    mid-flight has in-memory phases/flags; resuming one across a restart is future work,
    recorded in docs/port-fidelity-audit.md)."""

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
    coder_role: object = None  # Role | None — per-request sampling/reasoning for the coder
    reasoner_role: object = None  # Role | None — for the critic
    # Compaction/summarization sampling (temp 0.6, reasoning on) — the [roles.compactor] role,
    # falling back to the reasoner. Distinct from reasoner_role so the SUMMARIZE callers (self-compact,
    # completion rollup) can't accidentally ride the coder's act-temp. The redirect/critic keep the
    # reasoner_role — those are judgments, not rollups.
    compactor_role: object = None  # Role | None
    # Root of the per-run folders (the SAME root the call captures use, so one session's
    # plan mirror, verify dumps, and captures share one folder). cria's OWN dir — NEVER the
    # workspace. None → _RUNS_DIR_DEFAULT; "" → don't write run artifacts (tests).
    runs_dir: str | None = None
    # Workspace root for the completion gate's READ-ONLY discovery (probegate.plan_gate). None →
    # derived per request from the harness env-context (<cwd>), falling back to ".". Probe
    # EXECUTION always rides the harness shell tool regardless — cria never runs the commands.
    workspace_root: str | None = None
    # Focus-trim the OUTBOUND coder view (collapse exact-duplicate tool calls). [context] focus_trim.
    focus_trim: bool = True
    # Roll the OLD middle of a long coder view into a reasoner summary (mid-STEP transcript bloat —
    # orthogonal to `summary`, which only summarizes COMPLETED steps). [context] self_compact / trigger.
    self_compact: bool = True
    trigger_compaction: int = 16384
    # Is the planner stage ON? False = plan-off: the loop synthesizes a degenerate 1-item plan
    # (PlanSession.synthetic) and drives it through _drive_single_item — the relocated plan-off path.
    # The planner object above is then dormant (plan_for is never called on the synthetic path).
    planner_enabled: bool = True
    # Periodic SATISFACTION check cadence for the single-item path — start at drive `start`, then every
    # `every` drives (operator-tunable [context]; 0 disables). Only the single-item off-ramps use these.
    satisfaction_check_start: int = 100
    satisfaction_check_every: int = 25
    # The COMPACTOR endpoint's chat for the single-item self-compaction summary — rides the compactor
    # box (compactor_upstream.chat) like the plan-off _summarize did, so a compactor on its own base_url
    # is honored. None → fall back to reasoner_chat (the summarize sampling still uses compactor_role).
    compactor_chat: object = None  # (body, rlog) -> bytes | None


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
        # The PLAN loop can only run a coding task when the harness will RUN tools for it. The shell
        # tool is the primitive it needs — for its plan file, for the ground-truth probe, AND for the
        # coder's file writes (the writeproxy lowers write_file → a shell command, so NO shell tool =
        # no writes at all). Harnesses (Codex) also send genuinely tool-less requests — title /
        # summarize turns — that can classify as 'task' but aren't drivable. Decline → proxy; a LIVE
        # plan is NOT dropped, so the next tool-bearing turn resumes it (has_session keeps it alive).
        # PLAN-OFF is the exception: the single-item path runs the guarded coder even with NO shell
        # tool (the completion gate simply fails open on a native-write_file harness), so gating this
        # decline to planner-ON is load-bearing — otherwise the synthetic path silently loses every
        # rumination/truncation/repetition guard on a shell-less harness.
        if self._ctx.planner_enabled and find_shell_tool(body.get("tools")) is None:
            live = self._store.get(session_key) is not None
            rlog.emit("loop.no_shell_tool", level="info", deferred=live)
            return None
        # NO ACTIONABLE TOOLS — the harness advertised nothing the coder can write/edit/run with (only
        # the completion tool, or none at all: Codex's post-auto-compaction request can arrive tool-less).
        # The plan-off note above assumes native write_file exists; with NOTHING, the coder can only call
        # task_complete → the critic rejects → re-nudge → repeat, and with no shell the re-nudge recurses
        # INLINE until the SSE times out (observed: 170 attempts on one turn). Decline → proxy; a LIVE
        # session is NOT dropped, so the next tool-bearing turn resumes it (has_session keeps it alive).
        if not _has_actionable_tools(body.get("tools")):
            rlog.emit("loop.no_actionable_tools", level="warn",
                      live=self._store.get(session_key) is not None, n_tools=len(body.get("tools") or []))
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
            if not self._ctx.planner_enabled:
                # PLAN-OFF: the whole task is ONE implicit step — synthesize a degenerate 1-item plan
                # and drive it through the single-item path (raw-task framing + the off-ramps). A
                # non-coding turn is NOT ours (mirrors the old _produce_completion direct-coder gate) —
                # proxy it. A live synthetic session (loaded above) skips this entirely.
                if classification is None or classification.task_type != "coding":
                    return None
                sess = PlanSession(plan=_synthetic_plan(latest_user_text(messages)),
                                   synthetic=True, prior_work=briefing)
                # PERSISTENCE (Invariant 3, load-bearing): a stable ``sid:`` key persists + resumes;
                # an unstable ``task:`` key is EPHEMERAL — never ``put`` (re-synthesized each turn),
                # exactly as the plan-off path handed unstable keys a fresh state, so a synthetic session
                # can't leak across unrelated same-prompt conversations (the plan-cache-leak class).
                # A synthetic plan is NEVER mirrored to disk (no _persist_plan): it's just the raw task.
                if _stable_session(session_key):
                    self._store.put(session_key, sess)
                rlog.emit("loop.start", id=sess.plan.id, steps=1, synthetic=True)
            else:
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
                    sess = PlanSession(plan=plan, prior_work=briefing or root_text)
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
                        # Planner gave nothing back even after its own re-draft retries. A gather-overrun
                        # (retriable) will re-plan next turn — let it. But a genuine give-up on a CODING task
                        # must NOT fall to the unguarded proxy (it freewheels and can stop with no reason):
                        # drive the whole task as ONE synthetic guarded step, keeping the gate/guards/steers.
                        if getattr(self._ctx.planner, "_retriable_failure", False) \
                                or classification is None or classification.task_type != "coding":
                            return None
                        sess = PlanSession(plan=_synthetic_plan(latest_user_text(messages)),
                                           synthetic=True, prior_work=briefing)
                        if _stable_session(session_key):
                            self._store.put(session_key, sess)
                        rlog.emit("loop.start", id=sess.plan.id, steps=1, synthetic=True, planner_fallback=True)
                    else:
                        sess = PlanSession(plan=plan, prior_work=briefing)
                        self._store.put(session_key, sess)
                        rlog.emit("loop.start", id=plan.id, steps=len(plan.items), continued=bool(briefing))
                        self._persist_plan(plan, rlog)  # mirror to cria's OWN dir (never the workspace)

        if sess.synthetic:  # degenerate 1-item plan → the single-item driver (raw-task framing +
            # the off-ramps a finite multi-step plan doesn't need). Placed BEFORE the multi-item
            # awaiting_probe branch: the single-item path reads its own probe results internally.
            return self._drive_single_item(sess, body, session_key, rlog, rewritten=rewritten)

        if sess.awaiting_probe:  # the ground-truth probe we emitted last turn has now run
            sess.awaiting_probe = False
            out = self._verify_after_probe(sess, session_key, body, rlog, rewritten=rewritten)
            self._store.clear_rewrite(session_key)  # consumed (probe re-issued or judged)
            return out

        self._store.clear_rewrite(session_key)  # live session: framing is rebuilt each turn anyway
        return self._work(sess, session_key, body, rlog)

    # ------------------------------------------------------------------ work

    def _coder_turn(self, sess: PlanSession, framed: dict, body: dict, *, step: int, rlog) -> dict:
        """ONE guarded coder call — the shared core of BOTH driver halves (``_work`` multi-item and
        ``_drive_single_item`` synthetic/plan-off), so a coder-turn guard can NEVER land in one and
        silently miss the other (the divergence that killed the search-escape on the live path). The
        caller owns the framing (before) and the GATE (after — the ONE thing that legitimately differs:
        multi-step probe/`_verify` vs single `_gate_single_done`); this owns everything between:
        advertise the completion tool → call the coder → normalise a `task_complete` → rumination +
        truncation guards → banner/reasoning hygiene → track repetition + write-streak on an acting turn
        → the outgoing search's query judge. Returns the guarded completion ({} on a decode failure — a
        no-tool 'done' the caller's gate then handles)."""
        _add_completion_tool(framed)  # advertise the explicit-done tool for THIS coder call
        rlog.phase = f"coder-s{step}"  # label the call capture with the role + step
        coder = massage.apply(_parse_completion(self._ctx.coder_chat(framed, rlog)), framed.get("tools"), rlog)
        coder = _normalize_completion(coder, rlog)  # a task_complete call → step 'done' (or dropped)
        coder = guard_rumination(coder, framed, self._ctx.coder_chat, rlog, step=step, phase=f"coder-s{step}")
        coder = guard_truncation(coder, framed, self._ctx.coder_chat, rlog, step=step, phase=f"coder-s{step}")
        _strip_completion_banners(coder)  # scrub cria's own banners the coder parroted
        _record_reasoning(sess, coder)  # keep the coder's thinking for the quiet-flail detector
        if self._ctx.coder_role is not None:  # strip leaked reasoning from the coder's content when off
            _clean_completion(coder, self._ctx.coder_role)
        # Judge an outgoing web_search's query (off-target → a better query). Before the tracking, so the
        # repetition/write-streak guards see what's actually FORWARDED.
        coder = guard_search_query(sess, coder, body, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog)
        _track_fetched_pages(sess, body.get("messages", []))  # durable fetch facts for later steers
        if _has_tool_calls(coder):  # the coder ACTED → track the fingerprint for the repetition/spin guards
            guard_track_repetition(sess, coder, rlog, step=step)
            guard_track_write_streak(sess, coder, rlog, step=step, messages=framed.get("messages"))
        return coder

    def _work(self, sess: PlanSession, key: str, body: dict, rlog) -> dict:
        # Persist the harness's workspace cwd on the SESSION: a fresh <cwd> updates it, a turn without one
        # (harness compaction) keeps the last-known, and an operator-configured LoopContext root is the
        # final fallback — so the gate/steer target the harness's repo, never cria's own dir. (_ctx.
        # workspace_root is shared across sessions/None in prod; the per-session copy is the live source.)
        sess.workspace_root = _extract_cwd(body.get("messages", [])) or sess.workspace_root or self._ctx.workspace_root
        # The key webfetch's per-session gates use is the SAME key the loop drives under (server passes
        # one `sk` to both drive() and the outbound translation), so recording it here lets the search
        # judge ask about exactly the prior those gates would refuse against.
        sess.web_session = key
        body = {**body, "messages": self._judge_search_reads(sess, body, rlog)}  # strip off-target search reads
        item = sess.plan.current()
        if item is None:  # every step verified INDIVIDUALLY — but is the WHOLE task actually done?
            reason = self._reopen_if_unsatisfied(sess, body, rlog)
            if reason is not None:
                # not satisfied → a corrective step is now current; re-drive it (don't complete green-but-wrong)
                return self._work(sess, key, body, rlog)
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
        return self._work_item(sess, key, body, rlog, item, idx)

    def _reopen_if_unsatisfied(self, sess: PlanSession, body: dict, rlog) -> str | None:
        """Plan-ON completion critic (parity with the plan-off :func:`_done_critic_reason`). All steps
        verified individually, but is the USER'S TASK actually satisfied end-to-end? Grounds on the REAL
        tool output (the 404s, the failing run) — NOT the coder's own possibly-poisoned code — so it
        catches a green-but-wrong finish. When NOT satisfied, RE-OPEN the plan with ONE corrective step
        (reused across re-checks, so the plan doesn't grow) carrying the critic's concrete reason, and
        return that reason so the caller re-drives instead of completing. Returns None to COMPLETE:
        satisfied, no reasoner, or the ``MAX_COMPLETION_CHECKS`` bound hit (a task the coder can't finish
        still exits rather than looping forever). Fail-CLOSED on an undecidable verdict (judge_satisfaction
        only ever CONFIRMS not-done), so the bound — not a shaky 'satisfied' — is what lets it out."""
        if self._ctx.reasoner_role is None:
            return None
        if sess.completion_checks >= MAX_COMPLETION_CHECKS:
            # Spending this budget ENDS THE TASK: the caller reads None as "satisfied" and sets
            # Phase.DONE. That is the intended escape from an unfinishable task, but it used to
            # return before the emit below, so the record could not tell a run that finished from one
            # that gave up still being told "not done". Say which it was.
            rlog.emit("loop.done_unverified", level="warn", checks=sess.completion_checks)
            return None
        # The AUTHORITATIVE task is the plan's own — NOT _history_root, which after a harness compaction
        # is the SUMMARY (it may have dropped a requirement), letting a green-but-incomplete finish pass.
        # (Parity with _replan_tail, which already judges against sess.plan.task.)
        task = sess.plan.task or _history_root(body.get("messages", []))[0]
        ev = _satisfaction_evidence(body.get("messages", []))
        ev += _gate_notes(sess)
        satisfied, reason, fix_action = judge_satisfaction(task, ev, self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                               rlog, coder_tools=_coder_tools_summary(body.get("tools")),
                                               workspace_root=sess.workspace_root or "",
                                               routes=known_routes(body.get("messages", []), sess))
        rlog.emit("loop.done_critic", plan_off=False, satisfied=satisfied, check=sess.completion_checks)
        if satisfied:
            return None
        sess.completion_checks += 1
        reason = reason or "a deliverable the task named is missing, stubbed, or does not actually work"
        # The STEP is the judge's proposed ACTION, not its verdict essay: the old framing+reason+fix
        # paragraph became a step verbatim and pinned a run for 118 calls (0729-mellum2) — carrying
        # literal {{…}} braces the coder shipped into a URL, and "or fallback on…" advice. The essay
        # still reaches the coder through the nudge below; the plan gets only something DOABLE. And
        # a judge-authored step is NOT exempt from the noise scrub every other authored step passes
        # (operator: the model may author steps; cria's routing must apply the same quality bar).
        step_text = fix_action or reason
        try:
            noisy = reasoned_noise_indices(
                lambda sysm, userm: summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                              sysm, userm, rlog, phase="reasoner") or "",
                task, [step_text])
        except Exception:  # noqa: BLE001 — the scrub is advisory; never lose the corrective step to a crash
            noisy = set()
        if 0 in noisy:
            rlog.emit("loop.completion_fix_noise", level="info", head=_clip(step_text, 120))
        else:
            fix = PlanItem(text=_COMPLETION_FIX_PREFIX + step_text)
            if sess.plan.items and sess.plan.items[-1].text.startswith(_COMPLETION_FIX_PREFIX):
                sess.plan.items[-1] = fix      # reuse the one corrective step across re-checks (no plan bloat)
            else:
                sess.plan.items.append(fix)
        sess.plan.status = "in_progress"
        sess.nudge_reason = prompts.render("done_incomplete", reason=reason,
                                           check_state=prompts.load_map("done_check_state")["passed"])
        sess.steer_source = "completion critic (task not fully done)"
        self._persist_plan(sess.plan, rlog)
        return reason

    def _work_item(self, sess: PlanSession, key: str, body: dict, rlog, item, idx: int) -> dict:
        total = len(sess.plan.items)
        # Repetition/wheel-spin intervention (shared with the plan-off path): emit a ground-truth
        # probe now, or park a canned steer in sess.nudge_reason for the framing below.
        intervention = guard_intervene(sess, body, rlog, step=idx, workspace_root=sess.workspace_root)
        if intervention is not None:
            return intervention
        sess.drive_count += 1  # session-wide drive counter (feeds the flail cooldown; read only here + single-item)
        # QUIET-FLAIL catcher (parity with the single-item driver), CAPPED per step — see the method.
        self._flail_steer_if_circling(sess, body, idx, rlog)
        # PERIODIC ground-truth check-in WITHIN a long step (M2 parity with the plan-off driver): every
        # GATE_EVERY_CODER_TURNS acting turns, run the repo's checks so a step that edits many DIFFERENT
        # things for dozens of turns (never spiraling, never claiming done) still gets ground truth — the
        # exact case the per-step gate + wheel-spin detectors miss. Only when nothing else steers this turn.
        if not sess.nudge_reason:
            periodic = guard_periodic_gate(sess, body, rlog, workspace_root=sess.workspace_root)
            if periodic is not None:
                return periodic
        framed = dict(body)
        framed.pop("model", None)  # no alias — the upstream fills the server's loaded model
        framed["stream"] = False
        msgs = _frame_for_item(body.get("messages", []), item.text, sess.summary, idx, total,
                               prior_work=sess.prior_work, tools=body.get("tools"),
                               gate_plan=getattr(sess, "gate_plan", None))
        facts = _fetched_facts_anchor(sess)  # durable fetch ledger → the coder keeps the real endpoints it
        if facts is not None:                # already fetched past a HARNESS compaction (re-injected from
            msgs = _insert_after_system(msgs, facts)  # cria's own memory), so it stops re-fetching to rediscover
        steered = ""
        if sess.nudge_reason:  # re-driving after a failed check → tell the coder what's still wrong
            msgs = msgs + [{"role": "user", "content": prompts.render("nudge", reason=sess.nudge_reason)}]
            sess.nudge_reason = ""
            steered, sess.steer_source = sess.steer_source, ""  # set only for a GUARD steer, not a verify re-nudge
        framed["messages"] = msgs
        if self._ctx.self_compact:  # roll the old WORK-HISTORY middle into a rollup (the step framing
            msgs = self._self_compact(msgs, sess, idx, rlog, force=sess.compact_pending)  # lives in the protected system msg
            sess.compact_pending = False   # consumed the step-boundary force (a step just verified)
            framed["messages"] = msgs
        if self._ctx.focus_trim:  # focus the OUTBOUND coder view (never the history the guards read)
            trimmed, rep = focustrim.trim(msgs)
            if rep.applied:
                framed["messages"] = trimmed
                rlog.emit("context.focus_trim", step=idx,
                          dropped_calls=rep.dropped_calls, dropped_msgs=rep.dropped_msgs)
        if self._ctx.coder_role is not None:  # the coder role's sampling/reasoning from cria.toml
            self._ctx.coder_role.apply(framed)
        rlog.emit("loop.item", step=idx, total=total, text=item.text)

        coder = self._coder_turn(sess, framed, body, step=idx, rlog=rlog)  # SHARED coder turn (see _drive_single_item)
        if steered:  # no hidden guards: surface WHICH guard steered the coder (same note as plan-off)
            _add_note(coder, f"steered the coder — {steered}")
        if _has_tool_calls(coder):
            sess.step_tool_calls += 1  # the coder ACTED this step (the did-real-work leg's signal)
            sess.coder_turns += 1      # M2: acting turn — drives the periodic check-in cadence (was plan-off only)
            thrash = self._replan_if_thrashing(sess, key, body, idx, rlog)  # tool-call thrash escape
            if thrash is not None:
                return thrash
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
            return self._renudge(sess, key, body, prompts.load("leg0_nudge_step"), rlog)
        # LEG 2 setup: compose the completion gate (syntax floor + top probe + top TEST probe,
        # discovered fresh from the workspace) as ONE shell command the harness runs.
        probe_tc = self._gate_op(body, sess, rlog)
        if probe_tc is not None:
            sess.awaiting_probe = True
            sess.probe_call_id = probe_tc["id"]
            sess.pending_coder_text = _completion_text(coder)
            return _completion_toolcalls([probe_tc], note=f"verifying step {idx}/{total} — running checks")
        # no shell tool → cannot probe; still ground the critic in the coder's own tool output
        evidence = self._grounded_evidence(sess, body)
        ok, reason = self._verify(item.text, _completion_text(coder), "", evidence, rlog, idx=idx, total=total, key=key,
                                  coder_tools=_coder_tools_summary(body.get("tools")),
                                  routes=known_routes(body.get('messages', []), sess),
                                  workspace_root=sess.workspace_root or "")
        if ok:  # advance ONLY on a genuine pass — no fail cap (re-nudge forever otherwise)
            return self._advance(sess, key, body, idx, total, rlog)
        sess.verify_fails += 1
        sess.critic_fails += 1
        rlog.emit("loop.step_incomplete", step=idx, reason=reason, attempt=sess.verify_fails)
        return self._renudge_or_replan(sess, key, body, reason, idx, rlog)  # critic fail → may re-derive a stuck step

    def _judge_search_reads(self, sess: PlanSession, body: dict, rlog) -> list[dict]:
        """When the model READS a spilled search-results file, judge whether what it's reading is relevant
        to the task. Off-target → strip that read result from the model's view (replace it with a short
        denial note that also steers the recommended query) and mark the file so any re-read is likewise
        stripped/denied. Judged once per file (cached). Returns the messages (rewritten where poisoned)."""
        msgs = body.get("messages", [])
        if sess.judged_search_files is None:
            sess.judged_search_files = set()
        if sess.poisoned_search_files is None:
            sess.poisoned_search_files = set()
        read_file_of: dict = {}       # tool_call_id -> search file it read
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "assistant":
                for tc in (m.get("tool_calls") or []):
                    f = _toolcall_reads_search_file(tc)
                    if f:
                        read_file_of[tc.get("id")] = f
        if not read_file_of:
            return msgs
        q_of: dict = {}               # search file -> the query that produced it (from the pointer)
        for m in msgs:
            for mm in _SEARCH_POINTER_RE.finditer(_content_text(m.get("content")) if isinstance(m, dict) else ""):
                q_of[mm.group(2)] = mm.group(1)
        out: list[dict] = []
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "tool" and read_file_of.get(m.get("tool_call_id")):
                f = read_file_of[m.get("tool_call_id")]
                key = "content" if m.get("content") is not None else "output"
                if f not in sess.judged_search_files:
                    sess.judged_search_files.add(f)
                    # Judge the REAL results off disk — NOT the tool result, which for a spilled file is
                    # cria's own "grep this instead" steer. Handing the judge that envelope and asking
                    # "are the RESULTS on target?" gets a false for a search that was perfectly on target,
                    # and a definite false DELETES it. Unreadable → judge nothing, strip nothing (the file
                    # stays marked judged, so this can never become a per-turn reasoner call either).
                    results = search_file_text(sess.workspace_root, f)
                    _q, r_ok, rec = judge_search(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                                 latest_user_text(msgs), q_of.get(f, ""), results, rlog,
                                                 coder_tools=_coder_tools_summary(body.get("tools")))
                    if not r_ok:
                        sess.poisoned_search_files.add(f)
                        sess.search_recommend = rec
                        rlog.emit("loop.search_read_poison", file=f, rec=rec)
                if f in sess.poisoned_search_files:
                    # Marker-tagged and prompt-file-sourced: this note is cria's OWN voice written back
                    # into the message stream, so it must be identifiable — the work log and the critic
                    # were reading it as something the coder's tool returned.
                    steer = f" Search instead for: {sess.search_recommend}." if sess.search_recommend else ""
                    out.append({**m, key: prompts.render("search_read_denied",
                                                         marker=selfcompact.SEARCH_MARKER, steer=steer, file=f)})
                    continue
            out.append(m)
        return out

    def _self_compact(self, msgs: list[dict], sess: PlanSession, idx: int, rlog, *, force: bool = False) -> list[dict]:
        """Adopt the SAME self-compaction the plan-off path uses — roll the old work-history middle
        into a ⟦ctx:rollup⟧ summary via the SHARED summarize primitive (reasoner). Orthogonal to
        sess.summary (that's the cheap completed-STEP axis in the protected system message). ``force``
        (set at a step boundary) compacts now even below the size trigger, to clear the prior step's signals."""
        out, sess.compact_state, applied = selfcompact.compact(
            msgs,
            # Ground the reasoner's summary in cria's REAL last check state — so a summary that launders
            # an unverified 'tests pass' claim is overridden by what the checks actually reported.
            lambda mm: summarize(self._ctx.reasoner_chat, self._ctx.compactor_role or self._ctx.reasoner_role,
                                 prompts.load("selfcompact_summary"),
                                 selfcompact.serialize(probegate.clean_gate_results(mm)), rlog,
                                 phase="self-compact", max_tokens=ROLLUP_MAX_TOKENS) + _briefing_gate_ground_truth(sess),
            sess.compact_state, trigger_tokens=self._ctx.trigger_compaction, force=force,
            # The task is a foldable history message in the plan frame (only the STEP is in the system
            # message). Pin it as a ⟦ctx:task⟧ anchor so a boundary fold — which keeps NO verbatim tail —
            # can't summarize the original requirements away.
            pinned_task=(getattr(sess.plan, "task", "") or ""),
            # The coder-flavored files list (operator's design): the compacted view carries the LIST
            # of what exists; read_file is the road back to any content.
            files_list=workspace_inventory(sess.workspace_root or "", flavor="coder"),
            # The RARE fold-of-the-accumulated-summary (see selfcompact REFOLD_TOKENS).
            refold=lambda text: summarize(self._ctx.reasoner_chat,
                                          self._ctx.compactor_role or self._ctx.reasoner_role,
                                          prompts.load("selfcompact_refold"), text, rlog,
                                          phase="self-compact-refold", max_tokens=ROLLUP_MAX_TOKENS))
        if applied:
            rlog.emit("context.self_compact", step=idx, before=len(msgs), after=len(out), boundary=force)
            return out
        return msgs

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
        if sess.periodic_probe:  # M2 parity: a mid-step PERIODIC check-in, NOT a completion gate. Inject any
            # ground-truth error and keep working; NEVER advance the step (the coder didn't claim done). A
            # CLEAN check-in stays silent (guard_periodic_result returns None), so this can't complete a step.
            truth = guard_periodic_result(sess, body, rlog)
            return self._renudge(sess, key, body, truth, rlog) if truth else self._work(sess, key, body, rlog)
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
        steer = guard_probe_steer(sess, body, rlog, step=idx, author=self._probe_author)
        if steer is not None:
            return self._renudge(sess, key, body, steer, rlog)
        if not outcome.ran:
            # The script never ran (harness declined / no markers). Don't wedge — the pre-existing
            # fail-open: the critic still judges, told explicitly that no diagnostics ran.
            rlog.emit("loop.probe", step=idx, passed=True, gate_ran=False)
            digest = prompts.load("probe_digest_none")
            evidence = self._grounded_evidence(sess, body)
            ok, reason = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key,
                                      coder_tools=_coder_tools_summary(body.get("tools")),
                                      routes=known_routes(body.get('messages', []), sess),
                                      workspace_root=sess.workspace_root or "")
            if ok:
                return self._advance(sess, key, body, idx, total, rlog)
            sess.verify_fails += 1
            sess.critic_fails += 1
            rlog.emit("loop.step_incomplete", step=idx, reason=reason, attempt=sess.verify_fails)
            return self._renudge_or_replan(sess, key, body, reason, idx, rlog)  # critic fail → may re-derive a stuck step

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
        # Mirror guard_gate_verdict's gate-state onto the plan-ON path — WITHOUT this, last_gate_red /
        # last_gate_testless are only ever set by the plan-off readers, so the anti-laundering rollup
        # override (_briefing_gate_ground_truth) and the C4 vacuous-green evidence (_reopen_if_unsatisfied)
        # were dead on every real multi-step plan — exactly where "ground truth over judgment" needs them.
        if nudge is not None:
            sess.last_gate_red = True
        else:
            sess.last_gate_red = False   # ran and genuinely clean → GREEN
            sess.last_gate_testless = not proberun.gate_ran_tests(outcome.report)  # vacuous-green evidence
            sess.last_gate_skipped = proberun.gate_skipped_count(outcome.report)
        rlog.emit("loop.probe", step=idx, passed=nudge is None)

        if nudge is not None:  # GROUND TRUTH: floor or probes failed → the exact file:line errors
            sess.verify_fails += 1
            rlog.emit("loop.step_incomplete", step=idx, reason="probe failed", attempt=sess.verify_fails)
            return self._renudge(sess, key, body, nudge, rlog)

        digest = proberun.completion_probe_digest(outcome.report, missing=outcome.unran)
        evidence = self._grounded_evidence(sess, body)
        ok, reason = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key,
                                  coder_tools=_coder_tools_summary(body.get("tools")),
                                  routes=known_routes(body.get('messages', []), sess),
                                  workspace_root=sess.workspace_root or "")  # grounded in the coder's own runs
        if ok:  # advance ONLY on a genuine pass — no fail cap
            return self._advance(sess, key, body, idx, total, rlog)
        sess.verify_fails += 1
        sess.critic_fails += 1
        rlog.emit("loop.step_incomplete", step=idx, reason=reason, attempt=sess.verify_fails)
        return self._renudge_or_replan(sess, key, body, reason, idx, rlog)  # critic fail → may re-derive a stuck step

    def _advance(self, sess: PlanSession, key: str, body: dict, idx: int, total: int, rlog) -> dict:
        """Mark the current step VERIFIED (a step advances ONLY on a genuine pass — there is no
        accept-unverified), update cria's plan mirror, and move on."""
        item = sess.plan.current()
        item.done = True
        # A CLEAN status only — never the coder's raw output. The coder's text is unbounded prose (and
        # small models parrot cria's own banners back), which is what leaked "logs" into the plan file.
        item.note = "verified"
        sess.summary = _extend_summary(sess.summary, idx, item.text)
        sess.verify_fails = sess.critic_fails = 0
        sess.pending_coder_text = ""
        sess.step_tool_calls = 0   # fresh step, fresh did-real-work signal
        sess.thrash_replanned = False  # a new step-position may earn its own one-shot thrash re-derive
        sess.verify_replanned = False  # ...and its own one-shot verify-fail re-derive
        sess.flail_steers_this_step = 0  # ...and a fresh flail-steer budget
        sess.flail_cap_logged = False    # ...so the next step can report its own exhaustion
        sess.leg0_nudged = False
        sess.recent_writes, sess.spin_path = [], ""
        sess.spin_probe_due = False
        sess.recent_actions = []
        sess.redirect_due = False
        sess.last_gate_flag = ""   # convergence tracking is per step
        sess.compact_pending = True  # a step just VERIFIED → force a rollup next turn so the completed
        #                              step's raw work-signals don't distract the next step (operator ask)
        rlog.emit("loop.step_done", step=idx, verified=True)
        self._replan_tail(sess, body, idx, rlog)  # living plan: refine the not-done steps from real work
        self._persist_plan(sess.plan, rlog)  # refresh cria's own plan mirror; advance in-memory
        return self._work(sess, key, body, rlog)

    def _replan_tail(self, sess: PlanSession, body: dict, idx: int, rlog, *, trigger: str = REPLAN_TRIGGER_ADVANCE) -> None:
        """LIVING PLAN. A step just verified — hand a dedicated reasoner the real work done and let it
        re-derive the REMAINING (not-done) steps, replacing that tail. Completed steps are immutable
        history; only the not-yet-done steps are rewritten. This is what prunes a step the coder already
        satisfied while doing an earlier one (or that the work made moot) BEFORE it can make the coder
        redo/undo good work. Fail-safe: a parse miss / decline leaves the plan exactly as it was, and an
        'all done' verdict is confirmed by the task critic before it is allowed to empty the plan (the
        pruned steps skip the per-step gate, so completion must clear the same backstop the plan-off
        path uses). Skipped for a synthetic 1-item plan (no tail) and when no reasoner is configured."""
        if self._ctx.reasoner_role is None or sess.synthetic:
            return
        done_items = [it for it in sess.plan.items if it.done]
        remaining = [it for it in sess.plan.items if not it.done]
        if not remaining:
            return
        # EVERY pending step is re-derivable. cria used to hold a PINNED step out of the re-derivation so
        # its own injected research step could never be reworded or dropped — but a step held out of the
        # living plan is an inescapable mandate (485 calls burned on one), and cria authoring the step was
        # the overreach underneath it. Nothing cria writes outranks the re-derivation any more.
        rederivable = remaining
        evidence = self._grounded_evidence(sess, body)
        # The replanner is cria's SECOND author of plan steps, and it was never told the thing the
        # planner is told (147e224): that nothing read so far DEFINES a route. Measured (run
        # 0727-180058) its evidence carried zero `endpoints:` and zero `/handles/{handle}` while
        # "resolve endpoint" echoed through it 9 times from the plan and the coder's own turns — it
        # knew no routes and wrote "search for THE RESOLVE ENDPOINT pattern", which the coder turned
        # into `https://api.handle.me/resolve/{handle}` (404). This fires BECAUSE the ledger is empty,
        # which is the state that produces a presupposed endpoint — the inverse of a route CHECK,
        # which needs a populated ledger and so cannot help here. Silent once any real route is known.
        if not known_routes(body.get("messages", []), sess):
            evidence = (evidence + "\n\n" + prompts.load_map("planner_steers")["fetch_no_structure"]).strip()
        tools = _coder_tools_summary(body.get("tools"))
        steps = reassess_remaining(
            self._ctx.reasoner_chat, self._ctx.reasoner_role, sess.plan.task,
            "\n".join(f"- {it.text}" for it in done_items),
            "\n".join(f"- {it.text}" for it in rederivable), evidence, rlog, coder_tools=tools,
            trigger=trigger)
        if steps is None:  # declined / unparseable → keep the plan untouched
            rlog.emit("loop.replan_noop", step=idx, result="declined", remaining=len(rederivable))
            return
        if not steps:  # claims the re-derivable tail is done — confirm before dropping it
            satisfied, _, _fix = judge_satisfaction(sess.plan.task, evidence, self._ctx.reasoner_chat,
                                              self._ctx.reasoner_role, rlog, coder_tools=tools,
                                              workspace_root=sess.workspace_root or "",
                                              routes=known_routes(body.get("messages", []), sess))
            if not satisfied:  # not actually done → keep the remaining steps, let them verify normally
                rlog.emit("loop.replan_empty_declined", step=idx)
                return
        if [it.text for it in rederivable] == steps:
            # Unchanged → no churn, but NOT no log. Both stuck-step callers spend their one-shot
            # BEFORE calling here, so a re-derivation that returns the same tail permanently retires
            # the rescue and the step re-nudges to the completion bound. Silence here made that
            # indistinguishable, in the record, from a rescue that never fired.
            rlog.emit("loop.replan_noop", step=idx, result="unchanged", remaining=len(rederivable))
            return
        sess.plan.items = done_items + [PlanItem(text=s) for s in steps]
        rlog.emit("loop.replan", step=idx, before=len(rederivable), after=len(steps))
        # Re-persist the mirror — the ONE plan mutation that didn't (run 0728-m12): after a live
        # resize the on-disk plan showed 5 steps while the coder was correctly framed "4 of 7", so
        # the operator (and any forensic read) compared live frames against a dead snapshot. The
        # corrective-step mutation and _advance both persist; parity here.
        self._persist_plan(sess.plan, rlog)

    def _renudge(self, sess: PlanSession, key: str, body: dict, reason: str, rlog) -> dict:
        """A step failed its check → re-drive the coder on THIS step with the concrete
        reason, going back through `_work` so the SAME invariant holds: the coder's fix
        (a tool call) is forwarded, or — if it answers with prose — a fresh ground-truth
        probe is emitted. It NEVER returns a bare/prose completion, which would end the
        harness turn (stopping the session) and render as an empty ⟦cria⟧ line."""
        sess.nudge_reason = reason
        return self._work(sess, key, body, rlog)

    def _renudge_or_replan(self, sess: PlanSession, key: str, body: dict, reason: str,
                           idx: int, rlog) -> dict:
        """A CRITIC verify-fail (the step's checks are clean but its INTENT is judged unmet) — same as
        _renudge, EXCEPT: when the SAME step has failed the critic STUCK_STEP_REPLAN times, the step may
        be MISCONCEIVED (a confused/category-error step the planner wrote that no coder work can satisfy),
        so re-nudging with the same reason loops forever. Give the living-plan reasoner one grounded shot
        at re-deriving the not-done tail from the REAL work done: if it rewrites/drops the stuck step, we
        re-drive fresh on the new current step; otherwise (declined/unchanged) we fall through to a normal
        re-nudge. NEVER used on a gate/real-error fail — those must be FIXED, not re-derived away."""
        if (self._ctx.reasoner_role is not None and not sess.synthetic
                and not sess.verify_replanned and sess.critic_fails >= STUCK_STEP_REPLAN):
            # ONE grounded re-derive per step. Firing every STUCK_STEP_REPLAN fails (the old
            # `verify_fails % STUCK_STEP_REPLAN == 0`) re-derived the whole tail again and again and
            # THRASHED the plan — observed live: 8 stuck_replans bouncing the size 3→4→5→7→3→2, burning
            # the coder's turn budget so the deliverable never finished. This is the SAME churn
            # _replan_if_thrashing was already bounded to one-shot to avoid; the verify path must match.
            # Spend the one-shot up front (like the thrash path), so an unchanged re-derive can't re-fire.
            sess.verify_replanned = True
            before = [it.text for it in sess.plan.items if not it.done]
            self._replan_tail(sess, body, idx, rlog, trigger=REPLAN_TRIGGER_STALLED)   # grounded re-derivation; its own fail-safes apply
            after = [it.text for it in sess.plan.items if not it.done]
            if after != before:  # the reasoner un-stuck the plan from ground truth → clean restart
                sess.verify_fails, sess.critic_fails, sess.nudge_reason = 0, 0, ""
                rlog.emit("loop.stuck_replan", step=idx, before=len(before), after=len(after), trigger="verify")
                return self._work(sess, key, body, rlog)
        return self._renudge(sess, key, body, reason, rlog)

    def _replan_if_thrashing(self, sess: PlanSession, key: str, body: dict, idx: int, rlog) -> dict | None:
        """Tool-call-thrash sibling of the verify-fail re-derive: a coder can loop on tool calls for a
        whole step (write→exec→write…) WITHOUT ever signalling completion, so the verify-fail escape
        never accrues. After STEP_THRASH_REPLAN acting turns on one step, ask the living-plan reasoner
        ONCE to re-derive the not-done tail from ground truth — it may simplify an over-engineered step
        and dissolve the loop. Fired at most ONCE per step-position (``thrash_replanned``, reset only on
        ADVANCE): re-deriving REPEATEDLY churned the plan — a weak reasoner returns a different tail each
        call (observed: step count oscillated 11→5→6→9), destabilising the coder. One grounded attempt,
        then the normal guards/gate carry it. Returns a fresh re-drive when the plan MOVED, else None."""
        if (self._ctx.reasoner_role is None or sess.synthetic or sess.thrash_replanned
                or sess.step_tool_calls < STEP_THRASH_REPLAN):
            return None
        sess.thrash_replanned = True   # spend the one-shot regardless of outcome — no re-derive churn
        before = [it.text for it in sess.plan.items if not it.done]
        self._replan_tail(sess, body, idx, rlog, trigger=REPLAN_TRIGGER_STALLED)   # same grounded re-derivation + fail-safes
        after = [it.text for it in sess.plan.items if not it.done]
        if after != before:
            sess.step_tool_calls, sess.verify_fails, sess.critic_fails, sess.nudge_reason = 0, 0, 0, ""
            rlog.emit("loop.stuck_replan", step=idx, before=len(before), after=len(after), trigger="thrash")
            return self._work(sess, key, body, rlog)
        return None

    def _flail_steer_if_circling(self, sess: PlanSession, body: dict, idx: int, rlog) -> None:
        """QUIET-FLAIL catcher (parity with the single-item driver): when the coder's recent REASONING is
        circling and nothing else is nudging, a reasoner reads its thinking and — only if genuinely stuck —
        authors ONE unstick steer. The cheap lexical pre-filter + the cooldown gate the reasoner call.
        CAPPED at MAX_FLAIL_STEERS_PER_STEP per step (reset on ADVANCE): the cooldown SPACES steers but does
        not BOUND their total, so a step stuck for hundreds of drives drew ~25 — each redirecting the coder,
        so cria's own steers thrashed an already-stuck coder (assists are footguns; silence over noise). A
        few grounded nudges, then SILENCE — the gate/satisfaction/advance carry it from there."""
        if (sess.flail_steers_this_step >= MAX_FLAIL_STEERS_PER_STEP
                and not sess.flail_cap_logged and self._ctx.reasoner_role is not None):
            # Say ONCE that the reasoned nudges for this step are spent. The cap itself is measured
            # and stays (uncapped, one stuck step drew ~25 steers and cria's own nudges thrashed the
            # coder) — but "the coder recovered" and "cria has nothing left" are different situations
            # and looked identical in the log. The gate keeps speaking either way; this is the record.
            sess.flail_cap_logged = True
            rlog.emit("loop.flail_exhausted", level="warn", step=idx,
                      steers=sess.flail_steers_this_step, drives=sess.drive_count)
        if (sess.nudge_reason or self._ctx.reasoner_role is None
                or sess.flail_steers_this_step >= MAX_FLAIL_STEERS_PER_STEP
                or not _flail_candidate(sess.recent_reasoning)
                or sess.drive_count - sess.last_flail_drive < FLAIL_COOLDOWN):
            return
        sess.last_flail_drive = sess.drive_count
        diag = author_flail_steer(self._ctx.reasoner_chat, self._ctx.reasoner_role, sess.recent_reasoning, body, rlog)
        if diag:
            sess.flail_steers_this_step += 1  # spend one of the step's few unstick nudges (then SILENCE)
            sess.nudge_reason, sess.steer_source = diag, "reasoning appears to be circling"
            rlog.emit("loop.flail_steer", step=idx, drive=sess.drive_count)

    def _probe_author(self, condition: str, sess: PlanSession, outcome, body: dict, rlog):
        """The loop's reasoned steer author for a guard probe — dispatches on the detector ``condition``
        to the SHARED authors (so the plan-off path runs the identical reasoning) on the routed reasoner
        endpoint. Repetition keeps a canned floor (via author_redirect); wheel-spin may return None
        (ON_TRACK / nothing → inject nothing)."""
        item = sess.plan.current()
        step_text = item.text if item is not None else sess.plan.task
        root = sess.workspace_root
        if condition == "repetition":
            return author_redirect(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                   root, step_text, sess, outcome, body, rlog)
        return author_steer(self._ctx.reasoner_chat, self._ctx.reasoner_role, root, sess, body, rlog,
                            condition="wheel_spin", outcome=outcome, step_text=step_text)

    def _gate_op(self, body: dict, sess: PlanSession, rlog) -> dict | None:
        """The loop's completion gate — delegates to the shared :func:`guard_gate_op`, passing the
        configured workspace root."""
        return guard_gate_op(sess, body, rlog, workspace_root=sess.workspace_root)

    # ------------------------------------------------------------------ helpers

    def _grounded_evidence(self, sess: PlanSession, body: dict) -> str:
        """The critic's / re-derivation's ground truth: the coder's recent tool actions (the work log)
        PLUS the DURABLE fetched-page facts (url→status→endpoints) cria accumulated PLUS what actually
        exists on disk (the workspace inventory). Without the durable facts, a research step is judged
        NOT-done — or needlessly re-added — because the fetch that satisfied it scrolled off after a
        compaction (observed: the step critic saw a 3-action window and concluded "no OpenAPI spec
        reference" while the coder had fetched openapi.json 45× with the /handles/{handle} outline right
        there). Without the inventory, an artifact step is judged on INFERENCE: a "write README.md" step
        was passed on feasibility with zero write actions and no README on disk (run 0728-m4), and a
        FileNotFoundError naming one file was read as "the directory does not exist" while the workspace
        held files (run 0728-m1). Additive: every section only ever tells the critic MORE about the real
        state; none claims work that wasn't done."""
        messages = body.get("messages", [])
        log = _bound_evidence(_work_log(messages))
        facts = _fetch_ground_truth(messages, sess, header=CODER_FETCH_HEADER)
        inventory = workspace_inventory(sess.workspace_root)
        return "\n\n".join(part for part in (log, facts, inventory) if part)

    def _verify(self, item: str, coder_text: str, probe: str, evidence: str, rlog,
                *, idx: int = 0, total: int = 0, key: str = "", coder_tools: str = "",
                routes: str = "", workspace_root: str = "") -> tuple[bool, str]:
        # NB: no per-step fast-path around the critic. The one that existed shortcut a research step whose
        # facts cria had surfaced — but it could only recognize a step cria itself had injected and pinned,
        # and that injection is gone. The critic judges every step, grounded on the same durable fetch
        # facts (_grounded_evidence) the fast-path was reading.
        # System instruction: cria/prompts/verify.txt. User message (the step + real
        # ground truth): assembled from the labels in cria/prompts/verify_user.txt.
        system = prompts.load("verify")
        labels = prompts.load_map("verify_user")
        parts = [prompts.fill(labels["step"], step=item)]
        if evidence:  # what the coder's OWN tools returned — real ground truth, not a claim
            parts.append(prompts.fill(labels["evidence"], evidence=evidence))
        if probe:
            parts.append(prompts.fill(labels["probe"], probe=probe))
        parts.append(prompts.fill(labels["summary"], coder_summary=coder_text))
        # The critic is reasoning about the coder's work — give it the coder's tools too, so a NOT-done
        # reason it writes back names an action the coder can actually take (blind to them, it can't).
        if coder_tools:
            parts.append(prompts.render("reasoner_coder_tools", tools=coder_tools))
        # LAST: the step again. It was stated once at the top, before ~10K of evidence; the coder's
        # summary that lands just above the verdict often narrates its own numbered plan, and the
        # judge anchors on that instead (measured: it named a file that existed only in the summary).
        # Additive — the same step text, nothing dropped.
        parts.append(prompts.fill(labels["step_again"], step=item))
        user = "\n\n".join(parts)

        # First pass uses the reasoner role AS CONFIGURED (reasoning may be ON → a considered
        # judgment). If that yields no parseable verdict, retry with reasoning forced OFF: a
        # verdict is a one-line classification, and a reasoning model under the max_tokens cap
        # can burn its whole budget THINKING and never emit the closing JSON — which used to
        # fall through to a silent DONE. Reasoning-off makes it answer the JSON directly.
        obj, raw = self._verdict(system, user, rlog, reasoning_off=False, workspace_root=workspace_root)
        if obj is not None:
            obj = _fill_missing_verdict_flag(obj, "done", rlog, "critic")
        if obj is not None and _claims_impossible_action(obj, rlog, "critic"):
            obj = None   # fabricated evidence → the parse-miss retry path, never a standing verdict
        if obj is not None:
            # The careful (reasoning-ON) pass is the ONLY one trusted to APPROVE a step done — it does
            # the verification a reasoning-off judge can't.
            done = bool(obj.get("done"))
            if done and workspace_root:
                # The approve-path brake (see _confirm_completion): a DONE must be consistent with
                # the FRESH on-disk listing and with its own stated reason.
                confirmed, why = _confirm_completion(item, str(obj.get("reason") or ""), workspace_root,
                                                     self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                                     rlog, phase="critic-confirm")
                rlog.emit("loop.done_confirm", step=idx, confirmed=confirmed)
                if not confirmed:
                    done = False
                    obj = {**obj, "reason": why or str(obj.get("reason") or ""), "proposed_fix": ""}
            reason = _verdict_nudge(obj, done, routes)
            _dump_verify(self._run_dir(rlog), key, idx, total, item, system, user, done, reason, response=raw)
            return done, reason
        # No parseable careful verdict — the reasoner over-thought or leaked a tool call. Retry
        # reasoning-off, but a reasoning-off judge is a rubber stamp (competent to REJECT, not APPROVE):
        # use it only to confirm NOT-done. A "done" that exists ONLY because the careful pass failed is
        # FAILED CLOSED — a wrongly-passed step is never re-checked, so a shallow retry must never
        # advance the plan (the plan-off satisfaction judge fails closed the same way).
        rlog.emit("loop.verify_retry", level="info", reason="no parseable verdict; retry reasoning-off")
        retry, raw = self._verdict(system, user, rlog, reasoning_off=True)  # raw now = the retry's response
        if retry is not None and retry.get("done"):
            rlog.emit("loop.verify_failclosed", level="info")
            retry = None
        if retry is None:
            reason = "unverified (no parseable verdict)"
            _dump_verify(self._run_dir(rlog), key, idx, total, item, system, user, False, reason, response=raw)
            return False, reason
        reason = _verdict_nudge(retry, False, routes)   # a reasoning-off NOT-done is trustworthy
        _dump_verify(self._run_dir(rlog), key, idx, total, item, system, user, False, reason, response=raw)
        return False, reason

    def _verdict(self, system: str, user: str, rlog, *, reasoning_off: bool,
                 workspace_root: str = "") -> tuple[dict | None, str]:
        """One critic judgement → (parsed verdict dict OR None if the model produced no parseable
        JSON / the call failed, RAW response text). The raw text is dumped alongside the verdict so a
        human can see the verifier's ACTUAL output — the parrot (an echoed instruction) or an
        empty/rambling non-verdict is invisible in the parsed reason alone. `reasoning_off` forces
        enable_thinking=false so a reasoning model can't exhaust its token budget before the verdict.

        With a ``workspace_root``, the judge gets cria-executed READ-ONLY inspection tools
        (verifytools: list_dir/read_file) and this becomes a bounded tool loop — the same protocol
        as the planner's gather (structured assistant tool_calls turn, then role:tool results).
        Observed need: the toolless judge REACHED for these ("list_dir would show this" in its own
        reasoning) and asserted the imagined result. The reasoning-off retry stays toolless — its
        one job is "just answer the JSON"."""
        role = self._ctx.reasoner_role
        if reasoning_off:
            role = replace(role, reasoning="off") if role is not None else None
        try:
            # max_tokens bounds the output generously: the verdict's `reason` feeds the coder
            # re-nudge, so it must never be truncated at generation — the cap stays only as a
            # runaway backstop. The reasoning-off retry stays toolless (workspace_root dropped).
            comp = _judge_completion(
                self._ctx.reasoner_chat, role, system, user, rlog,
                phase="critic" + ("-noreason" if reasoning_off else ""),
                workspace_root="" if reasoning_off else workspace_root,
                force_think_off=reasoning_off)
            vtext = _completion_text(comp)
            if role is not None:
                vtext = role.clean_content(vtext)  # drop leaked reasoning when off
            if massage.is_truncated(comp):
                # Cut at the cap → not a verdict (measured: 3 critic calls in one day came back
                # finish_reason=length with content). The reasoning-off retry above has the whole
                # budget for content; if that is also cut, _verify fails closed as it already does.
                rlog.emit("loop.verify_truncated", level="warn", chars=len(vtext))
                return None, vtext
            return extract_json_object(vtext) or None, vtext
        except Exception as e:
            rlog.emit("loop.verify_error", level="warn", error=str(e))
            return None, ""

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
            f"{i + 1}. [{'done' if it.done else 'incomplete'}] {it.text}"
            for i, it in enumerate(sess.plan.items)
        )
        log = _work_log(body.get("messages", []))
        prior = (prompts.render("done_summary_prior", prior_work=sess.prior_work) + "\n\n") if sess.prior_work else ""
        user = prompts.render("done_summary_user", prior=prior, task=sess.plan.task,
                              checklist=checklist, log=log or "(no tool activity captured)")
        system = prompts.load("done_summary")
        # The shared summarize primitive handles the reasoning-off retry (a reasoning model can burn
        # its whole budget THINKING and emit empty content — the observed loop.compact_empty).
        text = summarize(self._ctx.reasoner_chat, self._ctx.compactor_role or self._ctx.reasoner_role,
                         system, user, rlog, phase="compactor")
        if text:
            rlog.emit("loop.compacted", id=sess.plan.id, chars=len(text))
            return text
        rlog.emit("loop.compact_empty", level="warn", id=sess.plan.id)
        # Fallback: the running per-step summary (or the bare checklist) still grounds a follow-up.
        return (sess.summary or checklist).strip()

    def _closing(self, sess: PlanSession, briefing: str = "") -> str:
        """The final message — a clean completion. Every step is VERIFIED: cria advances a step ONLY on a
        genuine pass and re-nudges INDEFINITELY otherwise, so a step is never 'accepted unverified' and
        cria never ends a plan with untrusted work (the removed accept-and-advance/handback path).

        The completion BRIEFING is embedded here, in the enveloped block — this message is the briefing's
        home. The harness stores it in the conversation, its compactor summarizes from it, and cria
        re-reads it from history (``_briefing_from_history``). One summary, carried by the transcript —
        never a server-side copy."""
        brief_block = f"\n\n{BRIEFING_OPEN}\n{briefing}\n{BRIEFING_CLOSE}" if briefing else ""
        return f"{indicators.MARKER}plan complete — all {len(sess.plan.items)} steps verified.{brief_block}".strip()

    # -------------------------------------------------------- single-item (plan-off) mode
    # A degenerate 1-item "plan" (``sess.synthetic``) is driven HERE, not through ``_work``: the whole
    # task is ONE implicit step, so the coder gets RAW-task framing (no "step k/n") and the off-ramp a
    # finite multi-step plan doesn't need — the task-level satisfaction/done critic.
    # These methods are the relocated plan-off direct-coder path (formerly ``server._drive_direct_coder``
    # et al.): the SAME shared guard/gate/author/summarize primitives, rewired onto the loop's OWN
    # LoopContext so ONE driver serves both producers. Reached only via ``sess.synthetic`` in _drive_locked.

    def _drive_single_item(self, sess: PlanSession, body: dict, session_key: str, rlog, *, rewritten: bool = False) -> dict | None:
        """The single-item coder turn with the SAME protections the loop gives its coder: the
        repetition/wheel-spin guard (probe → steer), the completion gate on a bare 'done' (verify the
        repo's checks before ending), harness-compaction re-anchoring, and the periodic + done
        satisfaction critic. Cross-turn state lives on the PlanSession (persisted for
        stable keys, ephemeral for ``task:`` keys). Returns the completion to send, or None on decode fail."""
        sess.drive_count += 1  # this session's total drives — the periodic satisfaction check keys off it
        sess.workspace_root = _extract_cwd(body.get("messages", [])) or sess.workspace_root or self._ctx.workspace_root  # harness cwd, persisted (see _work)
        body = {**body, "messages": self._judge_search_reads(sess, body, rlog)}  # strip off-target search reads
        # A probe whose result a harness compaction erased is re-issued (parity with the loop), rather
        # than fail-open / downgrade to a canned steer with no ground truth.
        reissue = guard_probe_reissue(sess, body, rlog, rewritten=rewritten, workspace_root=sess.workspace_root)
        if reissue is not None:
            return reissue
        # A completion-gate probe we emitted last turn (to verify a 'done') has now run.
        if sess.done_probe:
            sess.done_probe = False
            errors = guard_gate_verdict(sess, body, rlog)
            if errors:  # a check FAILED → steer to fix (pass the FULL output; the context floor bounds it)
                rlog.emit("loop.gate", plan_off=True, blocked=True)
                sess.nudge_reason = prompts.render("gate_fail_steer", errors=errors)
                sess.steer_source = "completion gate (repo checks failed)"
            elif self._ctx.reasoner_role is not None and (critic_reason := self._done_critic_reason(sess, body, rlog)):
                # The objective gate is GREEN, but the task-level reasoner critic (parity with the loop's
                # _verify) says the WHOLE task isn't done. NO once-bound: this re-runs on EVERY green
                # 'done', steering the coder back with the critic's CONCRETE reason, until the task is
                # actually satisfied. cria never lets a still-incomplete task exit early — the model
                # finishes the real work on its own; there is no "give up after one look".
                sess.nudge_reason = prompts.render("done_incomplete", reason=critic_reason,
                                                   check_state=prompts.load_map("done_check_state")["passed"])
                sess.steer_source = "completion critic (task not fully done)"
                sess.pending_done = ""
            else:  # green + (satisfied / already critiqued / no reasoner) → trust the objective gate, END
                rlog.emit("loop.gate", plan_off=True, blocked=False)
                held, sess.pending_done, sess.leg0_nudged = sess.pending_done, "", False
                return _completion_final(held or "Done.")
        # A PERIODIC check-in probe's result → insert the ground truth as a steer (no verdict).
        if sess.periodic_probe:
            truth = guard_periodic_result(sess, body, rlog)
            if truth:
                # C5: if the SAME error has persisted (the coder is STUCK, not just churning), replace the
                # raw ground-truth insertion with a REASONED thrash-diagnosis + one concrete next step (on
                # the routed reasoner). A reasoned unstick on a persistent RED stall — never a give-up.
                if self._ctx.reasoner_role is not None and sess.gate_stall >= THRASH_STALL_CYCLES:
                    truth = author_thrash_steer(
                        self._ctx.reasoner_chat, self._ctx.reasoner_role,
                        sess.workspace_root or _extract_cwd(body.get("messages", [])), sess, truth, body, rlog)
                    rlog.emit("loop.thrash_diagnosed", plan_off=True, stall=sess.gate_stall)
                sess.nudge_reason = truth
                sess.steer_source = "periodic check-in"
        # (No stall terminator: cria never ends a non-converging session by handing back to the human —
        # the mission is for the model to succeed on its own. A persistent RED drives the reasoned
        # thrash-assist above and the redirect/flail steers to keep getting the coder unstuck, never a
        # give-up. Stall detection/escalation may return later, only after every unstick lever is built.)
        # A guard probe (repetition/wheel-spin) result, or a fresh detection this turn.
        steer, intervention = None, None
        if sess.awaiting_probe:
            sess.awaiting_probe = False
            # PARITY: the single-item path gets the SAME reasoner-authored steers as the loop (via the
            # shared authors on the routed reasoner endpoint). CANNED only if there's no reasoner.
            def _author(condition, g, outcome, b, r):
                root = sess.workspace_root or _extract_cwd(b.get("messages", []))
                if condition == "repetition":
                    task = _history_root(b.get("messages", []))[0] or "the user's task"
                    return author_redirect(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                           root, task, g, outcome, b, r)
                return author_steer(self._ctx.reasoner_chat, self._ctx.reasoner_role, root, g, b, r,
                                    condition="wheel_spin", outcome=outcome)
            author = _author if self._ctx.reasoner_role is not None else CANNED
            steer = guard_probe_steer(sess, body, rlog, author=author)
        elif not sess.nudge_reason:  # (a gate-fail steer is already parked — don't double-intervene)
            intervention = guard_intervene(sess, body, rlog, workspace_root=sess.workspace_root)
        if intervention is not None:
            return intervention
        if steer is None and sess.nudge_reason:
            steer, sess.nudge_reason = sess.nudge_reason, ""
        # QUIET-FLAIL catcher: nothing above is steering, but the coder's REASONING has been circling on a
        # failure (the thrash the gate misses — the checks aren't even red). A no-tools reasoner reads its
        # recent thinking and, ONLY if it judges the coder genuinely stuck, authors one unstick step. The
        # cheap lexical pre-filter + a cooldown gate the reasoner call; the reasoner is the real judge.
        if steer is None and self._ctx.reasoner_role is not None and not rewritten and not sess.done_probe \
                and _flail_candidate(sess.recent_reasoning) \
                and sess.drive_count - sess.last_flail_drive >= FLAIL_COOLDOWN:
            sess.last_flail_drive = sess.drive_count
            diag = author_flail_steer(self._ctx.reasoner_chat, self._ctx.reasoner_role, sess.recent_reasoning, body, rlog)
            if diag:
                steer, sess.steer_source = diag, "reasoning appears to be circling"
                rlog.emit("loop.flail_steer", plan_off=True, drive=sess.drive_count)
        # PERIODIC SATISFACTION CHECK (the off-ramp for a session that finished the work but can't STOP):
        # on a long session the reasoner judges whether the USER'S WHOLE TASK is satisfied; if yes, cria
        # initiates the done-gate (verify the repo's checks) and ends next turn. GATED ON GREEN.
        if steer is None and not rewritten and not sess.done_probe and not sess.last_gate_red \
                and satisfaction_check_due(
                sess.drive_count, self._ctx.satisfaction_check_start, self._ctx.satisfaction_check_every):
            task = _history_root(body.get("messages", []))[0]
            evidence = _satisfaction_evidence(body.get("messages", []))
            evidence += _gate_notes(sess)
            satisfied, reason, _fix = judge_satisfaction(
                task, evidence, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog,
                coder_tools=_coder_tools_summary(body.get("tools")),
                workspace_root=sess.workspace_root or "",
                routes=known_routes(body.get("messages", []), sess))
            rlog.emit("loop.satisfaction_check", plan_off=True, drive=sess.drive_count, satisfied=satisfied)
            if satisfied:
                probe_tc = guard_gate_op(sess, body, rlog, workspace_root=sess.workspace_root)
                if probe_tc is not None:  # verify the repo's checks before ending (same backstop as 'done')
                    sess.done_probe = True
                    sess.probe_call_id = probe_tc["id"]
                    sess.pending_done = satisfaction_done_note(reason)
                    sess.steer_source = "completion check (task satisfied)"
                    return _completion_toolcalls([probe_tc],
                                                 note="cria completion check: the task looks done — verifying the repo's checks")
                return _completion_final(satisfaction_done_note(reason))  # no shell to verify → end fail-open
            # NOT satisfied → do NOT steer (the reason is judgment, not ground truth). Just log the verdict.
        # PERIODIC gate: every N acting turns, run the checks and insert ground truth — only when nothing
        # else is steering this turn (a guard steer / re-anchor takes precedence).
        if steer is None and not rewritten:
            periodic = guard_periodic_gate(sess, body, rlog, workspace_root=sess.workspace_root)
            if periodic is not None:
                return periodic
        framed = {**body, "messages": _frame_for_item(
            body.get("messages", []), "", sess.summary, 1, 1,
            prior_work=sess.prior_work, tools=body.get("tools"), synthetic=True,
            gate_plan=getattr(sess, "gate_plan", None))}
        extra = []
        if rewritten:  # first turn after a harness compaction → re-orient (a REASONED continuation).
            extra.append({"role": "user", "content": prompts.render("nudge", reason=self._reasoned_reanchor(body, rlog))})
            self._store.clear_rewrite(session_key)  # acted on it (framing rebuilt each turn)
        if steer:  # inject the steer into the coder framing this turn
            extra.append({"role": "user", "content": prompts.render("nudge", reason=steer)})
        if extra:
            framed = {**framed, "messages": framed["messages"] + extra}
        # Pin the conversation-root task (from the RAW body, where env-context detection still works —
        # framed has already been reframed) so self-compaction can't summarize it away.
        framed = self._self_compact_single(framed, sess, rlog,
                                           root_task=_history_root(body.get("messages", []))[0])
        if self._ctx.coder_role is not None:  # the coder role's sampling/reasoning from cria.toml
            self._ctx.coder_role.apply(framed)
        if self._ctx.focus_trim:  # focus the OUTBOUND view (logged, not bannered — routine housekeeping)
            trimmed, rep = focustrim.trim(framed["messages"])
            if rep.applied:
                framed = {**framed, "messages": trimmed}
                rlog.emit("context.focus_trim", dropped_calls=rep.dropped_calls, dropped_msgs=rep.dropped_msgs)
        comp = self._coder_turn(sess, framed, body, step=1, rlog=rlog)  # SHARED coder turn (see _work)
        if rewritten:  # no hidden guards: surface that cria re-anchored the turn
            _add_note(comp, "re-anchored after a harness compaction")
        if steer:  # no hidden guards: surface WHICH guard steered the coder
            _add_note(comp, f"steered the coder — {sess.steer_source or 'guard'}")
            sess.steer_source = ""
        if _has_tool_calls(comp):
            sess.coder_turns += 1  # an acting turn — drives the periodic check-in cadence
            return comp  # acting → forward
        return self._gate_single_done(sess, comp, framed, body, session_key, rlog)

    def _gate_single_done(self, sess: PlanSession, comp: dict, framed: dict, body: dict, key: str, rlog) -> dict:
        """The coder answered with NO tool call (thinks it's done). Verify before ending: LEG0 (never
        acted → one act-first nudge, re-call once), then the OBJECTIVE completion gate (run the repo's
        checks). NOTE: the gate reads cwd from the ORIGINAL body (reframe_preamble stripped the <cwd>
        tags from ``framed``)."""
        if sess.action_seq == 0 and not sess.leg0_nudged:  # the session never acted at all
            sess.leg0_nudged = True
            rlog.emit("loop.step_incomplete", plan_off=True, reason="no tools used")
            conv = framed["messages"] + [{"role": "user", "content": prompts.render("nudge", reason=prompts.load("leg0_nudge"))}]
            comp = self._coder_turn(sess, {**framed, "messages": conv}, body, step=1, rlog=rlog)  # SHARED
            if _has_tool_calls(comp):
                return comp  # it acted after the nudge
        probe = guard_gate_op(sess, body, rlog, workspace_root=sess.workspace_root)  # body, NOT framed
        if probe is not None:
            sess.done_probe = True
            sess.probe_call_id = probe["id"]
            sess.pending_done = _completion_text(comp)
            rlog.emit("loop.completion_probe", plan_off=True)
            return _completion_toolcalls([probe], note="verifying — running the repo's checks")
        # No shell tool → the objective gate can't run. Don't exit BLIND: if a reasoner is available, run
        # the task-level critic (fail-closed) — a NOT-satisfied verdict steers the coder back with the
        # concrete gap instead of forwarding an unverified 'done' (parity with the loop's no-shell _verify).
        if self._ctx.reasoner_role is not None and (critic_reason := self._done_critic_reason(sess, body, rlog)):
            sess.steer_source = "completion critic (task not fully done)"
            # No shell → the gate never ran; say so rather than claiming the checks passed.
            return self._renudge(sess, key, body, prompts.render(
                "done_incomplete", reason=critic_reason,
                check_state=prompts.load_map("done_check_state")["never_ran"]), rlog)
        return comp  # no reasoner AND no shell → can't verify at all; forward the 'done' (Tier-2 fail-open, left)

    def _done_critic_reason(self, sess: PlanSession, body: dict, rlog) -> str:
        """The task-level reasoner critic on a GREEN single-item 'done' (parity with the loop's _verify):
        judge the WHOLE task against the real work + the vacuous-green fact. Returns the critic's CONCRETE
        reason when the task is NOT satisfied — a specific unmet deliverable to steer the coder back with —
        or "" when satisfied. Runs on EVERY green 'done' (NO once-bound): cria never lets a still-
        incomplete task exit early; the model finishes the real work on its own. Fail-CLOSED — an
        undecidable judge counts as not-satisfied (judge_satisfaction already only confirms NOT-done)."""
        task = _history_root(body.get("messages", []))[0]
        ev = _satisfaction_evidence(body.get("messages", []))
        ev += _gate_notes(sess)
        satisfied, reason, _fix = judge_satisfaction(
            task, ev, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog,
            coder_tools=_coder_tools_summary(body.get("tools")),
            workspace_root=sess.workspace_root or "",
            routes=known_routes(body.get("messages", []), sess))
        rlog.emit("loop.done_critic", plan_off=True, satisfied=satisfied)
        return "" if satisfied else (reason or "a deliverable the task named is missing, stubbed, or never verified")

    def _reasoned_reanchor(self, body: dict, rlog) -> str:
        """A REASONED continuation after a harness compaction (parity with the loop's re-plan from the
        summary): the reasoner reads the compaction SUMMARY and authors a grounded 'what's done / what
        remains / inspect before creating' directive. Falls back to the canned reanchor when there is no
        reasoner or it yields nothing — a compacted coder is never left without re-orientation."""
        canned = prompts.load("reanchor")
        summary = _history_root(body.get("messages", []))[0]
        if self._ctx.reasoner_role is None or not summary.strip():
            return canned
        text = summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                         prompts.load("reanchor_reasoned"), summary, rlog, phase="reasoner")
        return text or canned

    def _self_compact_single(self, framed: dict, sess: PlanSession, rlog, root_task: str = "") -> dict:
        """Roll the OLD middle of a long single-item coder history into a compactor summary (info-
        preserving) instead of letting the floor drop-oldest lose it. Uses ``sess.compact_state`` (per-
        session), so it can't leak across conversations — an unstable-key session is ephemeral anyway.
        ``root_task`` is pinned verbatim so it can't erode across compaction rounds. Runs BEFORE the floor."""
        if not self._ctx.self_compact:
            return framed
        msgs = framed.get("messages") or []
        out, sess.compact_state, applied = selfcompact.compact(
            msgs, lambda mm: self._summarize_single(mm, rlog), sess.compact_state,
            trigger_tokens=self._ctx.trigger_compaction, pinned_task=root_task,
            files_list=workspace_inventory(sess.workspace_root or "", flavor="coder"),
            refold=lambda text: summarize(self._ctx.compactor_chat or self._ctx.reasoner_chat,
                                          self._ctx.compactor_role or self._ctx.reasoner_role,
                                          prompts.load("selfcompact_refold"), text, rlog,
                                          phase="self-compact-refold", max_tokens=ROLLUP_MAX_TOKENS))
        if not applied:
            return framed
        rlog.emit("context.self_compact", before=len(msgs), after=len(out), covered=sess.compact_state.covered)
        return {**framed, "messages": out}

    def _summarize_single(self, messages: list[dict], rlog) -> str:
        """Fold a span of the single-item coder transcript into a factual briefing — via the SHARED
        summarize primitive on the COMPACTOR endpoint (``compactor_chat``, falling back to the reasoner
        endpoint), same mechanism the loop's completion compaction uses, so the two can't diverge."""
        text = summarize(self._ctx.compactor_chat or self._ctx.reasoner_chat,
                         self._ctx.compactor_role or self._ctx.reasoner_role,
                         prompts.load("selfcompact_summary"),
                         selfcompact.serialize(probegate.clean_gate_results(messages)), rlog,
                         phase="self-compact", max_tokens=ROLLUP_MAX_TOKENS)
        return text or "(earlier work this session)"


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
        # Both delimiters, and the opener at the START of a line — the shape cria's own closing message
        # writes. The coder READS this block in its context and can parrot it, and a bare substring
        # match anywhere in any assistant turn would then promote the coder's own prose to `prior_work`
        # for the planner. This does not make the envelope unforgeable (it is deliberately marker-free
        # so strip_history spares it, and there is no server-side copy by design) — it just stops the
        # accidental case, which is the one that actually happens.
        if isinstance(c, str) and BRIEFING_CLOSE in c and any(
                ln.lstrip().startswith(BRIEFING_OPEN) for ln in c.splitlines()):
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
            "items": [{"text": it.text, "done": it.done, "note": it.note}
                      for it in sess.plan.items],
        },
        "summary": sess.summary,
        "prior_work": sess.prior_work,
        "verify_fails": sess.verify_fails,
        "synthetic": sess.synthetic,  # a resumed single-item session must stay single-item, not
        #                               flip to multi-step framing after a restart
    }


def _session_from_dict(d) -> PlanSession | None:
    """Rebuild a resumable PlanSession; None on any shape mismatch (never block startup)."""
    try:
        p = d["plan"]
        plan = Plan(id=str(p["id"]), task=str(p["task"]), created=str(p["created"]),
                    status=str(p.get("status", "in_progress")),
                    items=[PlanItem(text=str(it["text"]), done=bool(it.get("done")), note=it.get("note"))
                           for it in p["items"]])
        return PlanSession(plan=plan, summary=str(d.get("summary", "")),
                           prior_work=str(d.get("prior_work", "")),
                           verify_fails=int(d.get("verify_fails", 0)),
                           synthetic=bool(d.get("synthetic")))
    except Exception:  # noqa: BLE001
        return None


def _synthetic_plan(task: str, clock=None) -> Plan:
    """A degenerate 1-item 'plan' for PLAN-OFF mode: the whole task is ONE implicit step whose item
    text IS the raw task. The PlanSession carries the ``synthetic`` flag (which selects raw-task
    framing + the single-item off-ramps); the Plan itself is an ordinary 1-item Plan. id/created match
    the Planner's convention (clock + task-key) so a resumed synthetic session keeps a stable id. Never
    mirrored to disk (no ``_persist_plan``) — it holds no decomposition, only the user's own words."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    return Plan(id=f"{now.strftime('%Y%m%dT%H%M%S')}-{_task_key(task)[:8]}", task=task,
                created=now.isoformat(timespec="seconds"), items=[PlanItem(text=task)])


def _history_root(messages: list[dict]) -> tuple[str, str]:
    """``(text, fingerprint)`` of the conversation's ROOT — the first user message that isn't a
    harness env-context block (the SAME message the ``task:`` fallback ``session_key`` hashes,
    deliberately). This is the structural identity of a conversation: appending turns never
    changes it, but a harness compaction REPLACES it (the summary becomes the root). A changed
    fingerprint under a stable ``sid:`` session key is therefore the compaction signal — content-
    based, no phrase-matching, harness-agnostic. ``task:``-keyed sessions never detect rewrites
    (``_stable_session`` gates it): their key derives from this very root, so a rewritten root
    mints a new key and simply looks like a new session (recorded in docs/port-fidelity-audit.md)."""
    for m in messages:
        if m.get("role") == "user" and not _is_env_context(m):
            text = _content_text(m.get("content"))
            return text, hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
    return "", ""


def _work_log(messages: list[dict]) -> str:
    """A log of the coder's REAL actions — the tool calls it made (file writes, commands)
    and what they returned — for the completion compaction. cria's own plan-file writes and probe
    runs are stripped so the summary reflects the actual work, not the orchestration scaffolding.
    Full content flows: this is a model-read input (the summarizer/judge), and the context floor is
    the one window-aware place any physical truncation happens — a per-site clip here would just be a
    dumber, undetectable slice of what the model reads."""
    lines: list[str] = []
    # Same scrub chain every other reasoner-facing serialization uses (author_steer, _summarize_single,
    # _self_compact): without clean_gate_results, cria's OWN gate probe renders here as a coder action —
    # `$ shell {"command": "cd … || exit 97\necho ___CRIA_GATE_…\npytest …"}` — and its raw output as
    # something the coder's tool returned. This log feeds the step critic, the re-derivation, the
    # satisfaction judge and the completion briefing, so the orchestration was being judged as work.
    for m in probegate.clean_gate_results(_reasoner_session(messages)):
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = str(fn.get("arguments", "")).strip()
                if _is_cria_scaffolding(args):
                    continue
                lines.append(f"$ {fn.get('name')} {args}")
        elif role == "tool":
            c = str(m.get("content") or "").strip()
            if c and not _is_cria_scaffolding(c):
                lines.append(f"  -> {c}")
    return "\n".join(lines)


def _is_cria_scaffolding(text: str) -> bool:
    """Is this cria's own orchestration rather than the coder's work?

    The old test was ``"PROBE_EXIT" not in c`` — the NAME of the constant, never its value. The emitted
    sentinel is ``proberun.PROBE_EXIT_SENTINEL`` ("EXIT:") and the gate's section prefix is
    ``probegate.SECTION_PREFIX`` ("___CRIA_GATE_"), so the literal it checked for occurs only in test
    fixtures — the guard never fired in production and every raw probe dump landed in the work log as
    the coder's own tool output. Keyed on the real constants now, so it cannot drift again."""
    return (probegate.SECTION_PREFIX in text
            or proberun.PROBE_EXIT_SENTINEL in text
            or probegate.CHECKS_MARKER in text
            or selfcompact.SEARCH_MARKER in text)


def _satisfaction_evidence(messages: list[dict]) -> str:
    """Evidence for the whole-task satisfaction judge. Beyond the structured tool-action log
    (_work_log), it MUST include cria's summary-marker prose — continuation / rollup / briefing —
    because a HARNESS or self compaction REPLACES the structured tool history with that prose. On the
    turn right after a compaction _work_log alone is empty, so the judge saw "(no actions recorded
    yet)" and hallucinated that NO work was done (the observed false "the coder hasn't started" that
    marked a real, in-progress build as not-satisfied). The summary is the best record of the
    compacted-away work; the judge weighs it against the still-verbatim recent actions."""
    log = _work_log(messages)
    # The marker must START the message, and the message must not be an ASSISTANT turn. cria authors
    # these blocks as user/system turns; matching a bare substring in ANY role meant a coder that merely
    # parroted "⟦ctx:rollup⟧" — a marker it reads in its own context every turn — got its own claim
    # hoisted under "treat this as a record of what was already built" and handed to the done-judge as
    # authoritative history.
    summaries = [c.strip() for m in messages
                 if m.get("role") != "assistant"
                 and (c := _msg_text_content(m)).lstrip().startswith(
                     (CONTINUATION_MARKER, selfcompact.SUMMARY_MARKER, BRIEFING_OPEN))]
    if not summaries:
        return log
    head = ("SUMMARY OF EARLIER WORK (the detailed tool log was compacted to fit the window — treat "
            "this as a record of what was already built, then check it against the recent actions):\n"
            + "\n\n".join(summaries))
    tail = ("\n\nRECENT VERBATIM ACTIONS:\n" + log) if log.strip() else ""
    return head + tail


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


def _collapse_editfails(messages: list[dict]) -> list[dict]:
    """REASONER-only: one-line each raw ``⟦ctx:editfail⟧<base64>`` tool result. The base64 embeds the
    file's whole current bytes — noise the reasoner can't use (it can't decode it, and repeated blobs
    poisoned a verify prompt with ~96K tokens). The coder path deliberately does NOT call this: its
    represent_inbound decodes the marker into the recovery directive (with the bytes) the model needs."""
    out: list[dict] = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str) and editrecovery.EDITFAIL in c:
            m = {**m, "content": editrecovery.summarize(c)}
        out.append(m)
    return out


def _reasoner_session(messages: list[dict]) -> list[dict]:
    """Shared scrub for a session about to be serialized for a reasoner: hide cria's own file-ops/banners
    and collapse edit-fail base64 blobs to one line. (Harness-frame drop is applied separately since one
    caller reframes gate results between.)"""
    return _collapse_editfails(_strip_cria_file_ops(messages))


def _drop_harness_frame(messages: list[dict]) -> list[dict]:
    """Drop the harness's own agent system/developer prompt from a session about to be serialized for a
    reasoner. When cria hands a critic/steer-author the raw ``body`` transcript, message[0] is the
    harness's coding-agent boilerplate (Codex ships ~7.8K tokens of it — ``update_plan``/``apply_patch``
    docs, planning examples ×2, plugin blurbs); it is a full QUARTER of the steer prompt and pure noise
    to a reasoner that has its OWN supervisor system prompt. The coder path already drops exactly this
    (:func:`_frame_for_item` — cria owns the system prompt); this is the same drop for the reasoner path.

    This removes the FRAME only — every ``user``/``assistant``/``tool`` turn (the real task, every tool
    call and its result) is kept verbatim — so it is NOT the 'curated slice' :func:`author_steer` warns
    against (a curated view once made a steer hallucinate a path). Harness-agnostic: any role the harness
    puts its agent prompt in (``system``/``developer``) is dropped.

    The harness's env-context/`<INSTRUCTIONS>` USER preamble is not dropped but REFRAMED (same
    :func:`reframe_preamble` the coder path applies), so the reasoner sees cria's clean cwd/shell/date
    voice instead of the raw foreign XML + sandbox plumbing — the residual of the same passthrough class."""
    return [reframe_preamble(m) for m in messages if m.get("role") not in ("system", "developer")]


# Codex's VS Code extension compacts by APPENDING this user turn (it keeps the original task as the
# root, so the structural rewrite detection never fires) and frames the model's OWN earlier summary
# as "another language model's". That misattribution makes a small model disown its prior work and
# duplicate files. cria recognizes the known harness artifact (as it reframes <environment_context>)
# and REATTRIBUTES the summary to the model itself + re-anchors it (inspect before creating).
_COMPACTION_MARKER = "Another language model started to solve this problem"
_COMPACTION_BOUNDARY = "assist with your own analysis:"


def _workspace_is_empty(cwd: str) -> bool:
    """True when the advertised workspace does not exist or is empty. The continuation reframe's
    'the files that should already exist / do NOT recreate' claim is then objectively FALSE — the
    drift ROOT: a fresh/restarted session over an empty cwd took that claim at face value and sent
    the model hunting for its 'prior work' in sibling directories (the codex-handles drift).
    Conservative: an unknown cwd ('.'/none — the harness advertised no workspace) or ANY entry at
    all (even hidden) → NOT empty, so a repo with real work keeps the normal 'build on it' reframe."""
    if not cwd or cwd == ".":
        return False
    try:
        return not os.listdir(cwd)
    except FileNotFoundError:
        return True   # the advertised workspace is absent → the 'files already exist' claim is false
    except OSError:
        return False  # unreadable (permissions, not-a-dir) → can't assert emptiness; stay with normal


def reframe_compaction(messages: list[dict]) -> tuple[list[dict], bool]:
    """Reattribute the harness's 'another language model' compaction turn to the model itself and
    re-anchor it, keeping the summary. Returns (messages, reframed?) — the SAME list (no copy) when
    no compaction turn is present. Idempotent per turn: the reframed content no longer carries the
    marker, so a later pass won't touch it again.

    Ground-truth guard: when the advertised workspace is EMPTY, the normal reframe's "read the files
    that already exist, do NOT recreate" is false and harmful — it overrides the model's own correct
    "the dir is empty, start fresh" and sends it hunting elsewhere. In that case emit the INVERTED
    reframe ("none of that work is present here; start fresh in this workspace, don't look elsewhere")."""
    cwd = _extract_cwd(messages) or ""   # unknown → "" (never "." / "None"); _workspace_is_empty treats it as unknown
    template = "compaction_reframe_empty" if _workspace_is_empty(cwd) else "compaction_reframe"
    out: list[dict] = []
    reframed = False
    for m in messages:
        text = _msg_text_content(m)  # handles list-shaped content (a chat client's structured parts)
        if m.get("role") == "user" and _COMPACTION_MARKER in text:
            idx = text.find(_COMPACTION_BOUNDARY)  # split off the harness preamble, keep the summary tail
            if idx != -1:
                summary = text[idx + len(_COMPACTION_BOUNDARY):].lstrip("\n")
            else:
                # boundary drifted/absent: strip up to the END of the marker's own line so the foreign
                # "another language model…" sentence is NEVER wrapped in "this is YOUR OWN work".
                nl = text.find("\n", text.find(_COMPACTION_MARKER))
                summary = text[nl + 1:].lstrip("\n") if nl != -1 else ""
            # Tag with a ⟦ctx:⟧ marker so classify.latest_user_text skips it — this reframe is cria
            # scaffolding, not the user's task; classifying it flips a coding session onto the reasoner.
            out.append({**m, "content": f"{CONTINUATION_MARKER} {prompts.render(template, summary=summary, cwd=cwd)}"})
            reframed = True
        else:
            out.append(m)
    return (out, True) if reframed else (messages, False)


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
        parts.append(prompts.render("preamble_instructions", instructions=instr.replace("\r", "").strip()))
    if env:
        fields = [(label, v.strip()) for tag, label in _ENV_FIELDS
                  if (v := _tag_body(env, tag)) and v.strip()]
        if fields:
            parts.append(prompts.render("preamble_environment", fields=", ".join(f"{k}: {v}" for k, v in fields)))
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


def _frame_for_item(messages: list[dict], item: str, summary: str, idx: int, total: int, prior_work: str = "", tools=None, synthetic: bool = False, gate_plan=None) -> list[dict]:
    """Rewrite the conversation so the coder's task IS the current step, and so cria — not the
    harness — owns the system prompt:

    * DROP the harness's agent system prompt entirely. When cria is driving the loop it provides
      the orchestration, so a harness's "you are an autonomous coding agent, plan and finish the
      whole task" boilerplate (Codex ships ~7.8K tokens of it — a third of the window) is pure
      conflict: it fights cria's step-by-step driving and buries cria's instruction. cria leads
      with its OWN concise coder system prompt instead (`prompts/coder_system.txt`). Harness-
      agnostic: whatever agent prompt any harness puts in `system`/`developer` is replaced.
    * KEEP the user's real task as HISTORY (the whole goal — every requirement, so the coder works
      from the full ask, not just the terse step text), followed by an acknowledgement that it has been
      decomposed into a plan — so it reads as BACKGROUND, not a standing "do the whole thing now" ask.
      The ACTIVE directive is the CURRENT step, appended last and carried in the authoritative system
      message. The plan's LATER steps are never shown, so the coder still cannot race ahead to one.
    * KEEP everything else: the user's own instructions (AGENTS.md), env context, and the work
      history — those are user/assistant/tool messages, not the harness agent prompt.
    * On a FOLLOW-UP (prior_work set), fold the completion-compaction of the earlier plan into the
      system message so the coder knows what already exists this session — same reason as the step:
      system is protected from floor-trimming and authoritative.
    """
    messages = _strip_cria_file_ops(messages)  # don't let the coder see/mimic `.cria/` writes
    # The plan carries each section's probe KIND, which is what lets a non-zero TEST/BUILD exit whose
    # output is all advisory-shaped (-Werror, deny(warnings), tsc noUnusedLocals) be reported as the
    # failure it is instead of "no error-class problems".
    messages = probegate.clean_gate_results(messages, gate_plan)  # strip raw gate plumbing/advisory
    hint = toolmenu.cheatsheet(tools)
    done_block = (prompts.render("done_block", prior_work=prior_work) + "\n\n") if prior_work else ""
    if synthetic:
        # RAW-TASK MODE (plan-off / degenerate 1-item plan): cria's coder_system + the menu-derived
        # tool hint (+ a follow-up done-context when prior_work is set), NO step prompt, and the user's
        # real task message is KEPT (never replaced). Byte-equivalent to the former _direct_coder_body,
        # so turning the planner off is a fair 'coder without a planner', not a bare passthrough.
        system = (prompts.load("coder_system") + (f"\n\n{hint}" if hint else "")
                  + (f"\n\n{done_block.rstrip()}" if prior_work else ""))
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.get("role") in ("system", "developer"):
                continue  # harness agent boilerplate → replaced by cria's coder_system above
            out.append(reframe_preamble(m))  # env-context preamble → cria's clean voice; task kept raw
        return out
    # cria's step instruction goes in the SYSTEM message, NOT a front user turn. The context floor
    # protects system messages but trims old user turns — and on a large history (after compaction)
    # it was trimming cria's own step framing AWAY, leaving the coder with no idea what step it was
    # on (it then flails and the re-nudge loop never converges = "Thinking forever"). In the system
    # message the instruction can never be dropped, and system is authoritative for the model.
    # cria owns the system prompt: base coder prompt → the menu-derived tool hint (so the coder is
    # told to use ONLY the tools actually in this turn's menu — the harness system message that
    # add_cheatsheet folded the hint into is dropped here) → done-context → the step (kept last).
    prompt = _item_prompt(item, summary, idx, total)
    hint_block = f"{hint}\n\n" if hint else ""
    out: list[dict] = [{"role": "system",
                        "content": prompts.load("coder_system") + "\n\n" + hint_block + done_block + prompt}]
    acked = False
    for m in messages:
        if m.get("role") in ("system", "developer"):
            continue  # harness agent boilerplate → replaced by cria's coder_system above
        out.append(reframe_preamble(m))  # env-context preamble → cria's clean voice; the real TASK is KEPT
        if not acked and m.get("role") == "user" and not _is_env_context(m):
            # The user's real task just went in as history — acknowledge it's been decomposed, so it
            # reads as the overall GOAL (background), not a fresh "do it all now" ask. Consecutive
            # assistant turns (this ack + the first work turn) are merged upstream (_merge_consecutive_assistant).
            out.append({"role": "assistant", "content": prompts.load("plan_ack")})
            acked = True
    out.append({"role": "user", "content": prompt})  # the CURRENT step = the active ask (last turn; also in system)
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


# ---- completion tool: an EXPLICIT "done" the model can CALL, instead of the harder-for-a-tool-
# trained-model absence of a tool call. NOT lowered or forwarded — the driver folds it into the
# normal flow (a lone call → a plain-text 'done' that runs the SAME LEG0 → gate → verdict a bare done
# does). Description in prompts/tool_descs.txt (tunable). Advertised on coder turns only.
TASK_COMPLETE_TOOL = "task_complete"


def _tool_name(tc) -> str:
    """The name of a tool CALL or tool SCHEMA (both nest it under `function`)."""
    fn = (tc.get("function") or tc) if isinstance(tc, dict) else {}
    return fn.get("name") or ""


def _has_actionable_tools(tools) -> bool:
    """True if the harness advertised ANY tool the coder can ACT with — anything other than the
    completion tool. A coding turn with none (Codex's post-auto-compaction request can arrive
    tool-less) can only call ``task_complete`` forever, so cria must not drive it."""
    return any(_tool_name(t) and _tool_name(t) != TASK_COMPLETE_TOOL for t in tools or [])


def _completion_tool() -> dict:
    desc = prompts.load_map("tool_descs").get(
        TASK_COMPLETE_TOOL, "Call this when the task is fully done and verified. Pass a short summary.")
    return {"type": "function", "function": {
        "name": TASK_COMPLETE_TOOL, "description": desc,
        "parameters": {"type": "object", "required": ["summary"],
                       "properties": {"summary": {"type": "string",
                                      "description": "A short plain-text summary of what you did."}}}}}


def _add_completion_tool(framed: dict) -> None:
    """Advertise the completion tool on a coder turn (a fresh tools list, so the caller's body isn't
    mutated). No-op when the menu already carries a task_complete."""
    tools = list(framed.get("tools") or [])
    if not any(_tool_name(t) == TASK_COMPLETE_TOOL for t in tools):
        tools.append(_completion_tool())
    framed["tools"] = tools


def _tc_summary(tc) -> str:
    try:
        return str(json.loads(((tc.get("function") or {}).get("arguments")) or "{}").get("summary", "")).strip()
    except (json.JSONDecodeError, AttributeError, TypeError):
        return ""


def _normalize_completion(comp: dict, rlog) -> dict:
    """Fold a `task_complete` call into the normal flow, in place. Called ALONE → rewrite the turn
    into a plain-text 'done' carrying the summary (so the existing LEG0 → gate → verdict runs
    unchanged, and the checks still verify before the session ends). Called ALONGSIDE real tool calls
    → drop it (the coder is still working; the done is premature). No-op when it wasn't called."""
    for ch in comp.get("choices", []):
        msg = ch.get("message") or {}
        tcs = msg.get("tool_calls")
        if not tcs:
            continue
        done = [tc for tc in tcs if _tool_name(tc) == TASK_COMPLETE_TOOL]
        if not done:
            continue
        real = [tc for tc in tcs if _tool_name(tc) != TASK_COMPLETE_TOOL]
        if real:
            msg["tool_calls"] = real
            rlog.emit("loop.task_complete_ignored", reason="called alongside real tool calls")
        else:
            summary = _tc_summary(done[0])
            msg.pop("tool_calls", None)
            if summary:
                msg["content"] = summary  # becomes the bare-done text → pending_done
            rlog.emit("loop.task_complete", summary=summary[:160])
    return comp


_PATH_KEYS = PATH_KEYS  # the one shared alias set (also used by the raw-regex fallback below)
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
    """The file a single tool call writes; None for non-write calls. Covers the named write tools AND
    a SHELL-native write (redirect/heredoc/`tee`), so the wheel-spin guard counts a model rewriting
    one file straight through the shell the same as a write_file."""
    name = fn.get("name")
    if _is_write_tool(name):
        return _path_of_args(fn.get("arguments") or "", patch_ok=name == "apply_patch")
    if name in SHELL_TOOL_NAMES:
        return _shell_write_target(fn.get("arguments") or "")
    return None


# Extract the file a shell command writes via redirect/heredoc/`tee` — the target token after a
# `>`/`>>` (not `/dev/…`, `&`, or a comparison) or after `tee [-a]`. Quoted spans are stripped first
# so a `>` inside a string isn't read as a redirect. Best-effort: a miss just doesn't group (never
# over-fires), matching the streak guard's existing tolerance.
_REDIRECT_TARGET_RE = re.compile(r'(?<![-=<>\d])>{1,2}\s*(?!/dev/|&)([\w./~$-]+)')
_TEE_TARGET_RE = re.compile(r'\btee\b\s+(?:-a\s+)?(?!-)([\w./~$-]+)')


def _shell_write_target(args) -> str | None:
    text = _command_text(args)
    if text is None:
        return None
    masked = _QUOTED_SPAN_RE.sub("", text)  # drop quoted spans so a `>` inside them isn't a redirect
    m = _REDIRECT_TARGET_RE.search(masked) or _TEE_TARGET_RE.search(masked)
    return m.group(1) if m else None


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
    root = workspace_root or _extract_cwd(body.get("messages", [])) or ""
    if root == ".":  # a stray "." from any caller IS cria's own cwd — refuse it (never probe cria's tree)
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
        # The gate script is bounded per-probe (timeout -k 5 240) but a harness exec's DEFAULT
        # yield window (Codex: 10s) cut it mid-pytest — ask for the script's real budget via
        # whatever ms-unit field the tool's own schema declares (none declared → unchanged).
        "function": {"name": tool["name"],
                     "arguments": json.dumps(with_time_budget(tool, shell_args(tool, plan.script)))},
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
                gs.repeat_action = f"{name} {args}"
                rlog.emit("loop.repetition", step=step, tool=name,
                          count=REPEAT_FINGERPRINT_N, args=_clip(args, 120))


def guard_track_write_streak(gs: GuardState, coder: dict, rlog, *, step=None, messages=None) -> None:
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
                    and not gs.redirect_due and not gs.redirect_probe
                    # Don't flag a rewrite cria ITSELF ordered: when edit-recovery has escalated this file
                    # to a whole-file rewrite, its compliance rewrites are sanctioned. Once that guidance
                    # scrolls out of the recent window (the model moved on to pure rewriting), the spin
                    # re-arms and the reasoned wheel-spin can diagnose the real bug.
                    and not editrecovery.rewrite_sanctioned(messages or [], path)):
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
        gs.nudge_reason = prompts.render(
            "redirect_canned", repeat_action=gs.repeat_action, ground_truth="")
        gs.steer_source = "repetition guard"
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
        gs.nudge_reason = prompts.render("spin_nogate", spin_path=gs.spin_path)  # a steer, never silence
        gs.steer_source = "wheel-spin guard"
        rlog.emit("loop.spin_probe_result", step=step, canned=True)
    return None


def guard_probe_reissue(gs: GuardState, body: dict, rlog, *, rewritten: bool, workspace_root=None) -> dict | None:
    """A probe cria emitted last turn should have a result this turn. If the harness COMPACTED the
    history (``rewritten``), that result was LOST, not declined — re-issue the gate rather than
    fail-open (accept an unverified 'done') or downgrade to a canned steer. Capped by
    MAX_PROBE_REISSUES. Shared with the loop's _verify_after_probe so BOTH paths recover a
    compaction-lost probe. Returns the re-issued probe completion, or None (result present, not a
    compaction loss, cap hit, or no gate). Leaves the pending flag armed so next turn reads the new
    result the same way."""
    if not (gs.done_probe or gs.awaiting_probe):
        return None
    if _read_tool_result(body.get("messages", []), gs.probe_call_id).strip():
        gs.probe_reissues = 0  # the result arrived — clear the streak
        return None
    if not rewritten or gs.probe_reissues >= MAX_PROBE_REISSUES:
        return None
    probe_tc = guard_gate_op(gs, body, rlog, workspace_root=workspace_root)
    if probe_tc is None:
        return None
    gs.probe_call_id = probe_tc["id"]
    gs.probe_reissues += 1
    rlog.emit("loop.probe_reissued", plan_off=workspace_root is None, attempt=gs.probe_reissues)
    return _completion_toolcalls([probe_tc], note="re-running checks (history was compacted)")


def guard_periodic_gate(gs: GuardState, body: dict, rlog, *, workspace_root=None) -> dict | None:
    """Every GATE_EVERY_CODER_TURNS acting coder turns, emit the repo's checks as a probe so the
    model gets GROUND TRUTH on a cadence — not only when it claims 'done' or a guard trips. INSERTs
    the result (no verdict, the turn stays open), like the wheel-spin probe. Returns the probe
    completion, or None (not due yet, or no gate available). Resets the counter either way so a
    gate-less workspace doesn't retry every turn."""
    if gs.coder_turns < GATE_EVERY_CODER_TURNS:
        return None
    gs.coder_turns = 0
    probe_tc = guard_gate_op(gs, body, rlog, workspace_root=workspace_root)
    if probe_tc is None:
        return None  # no shell tool / unknown root — can't gate; try again in another N turns
    gs.awaiting_probe = True
    gs.periodic_probe = True
    gs.probe_call_id = probe_tc["id"]
    rlog.emit("loop.periodic_gate", plan_off=workspace_root is None)
    return _completion_toolcalls([probe_tc], note="periodic check-in — running the repo's checks")


def guard_periodic_result(gs: GuardState, body: dict, rlog) -> str | None:
    """Read the periodic check-in probe's result and return the error-class GROUND TRUTH to insert
    (file:line findings, or a check that ran and failed) — no verdict, the model keeps working. None
    when no periodic probe is pending, OR when the checks are CLEAN / couldn't run: a periodic check-in
    with nothing to FIX stays silent rather than prod a passing check-in with 'the checks pass but
    that's not proof of correctness', which just makes the model distrust the pass and keep working."""
    if not gs.periodic_probe:
        return None
    gs.periodic_probe = False
    gs.awaiting_probe = False
    probe = _read_tool_result(body.get("messages", []), gs.probe_call_id)
    outcome = probegate.interpret_gate(gs.gate_plan, probe) if gs.gate_plan is not None \
        else probegate.GateOutcome(ran=False)
    # A periodic check-in speaks ONLY when there is a real PROBLEM to fix. On a CLEAN result it stays
    # SILENT — prodding a passing check-in with "the checks pass but that's not proof of correctness"
    # just makes the model distrust the pass and keep working (feeding the can't-stop spiral).
    err = gate_error_text(outcome)
    rlog.emit("loop.periodic_gate_result", ran=outcome.ran, spoke=bool(err))
    if err:
        gs.last_gate_red = True
        track_gate_progress(gs, err)            # RED → streak++, stall on an unchanged finding
    elif outcome.ran:
        gs.last_gate_red = False  # ran and clean → GREEN (the satisfaction judge may now run)
        gs.last_gate_testless = not proberun.gate_ran_tests(outcome.report)  # vacuous-green evidence
        gs.last_gate_skipped = proberun.gate_skipped_count(outcome.report)
        track_gate_progress(gs, "")             # GREEN → reset the streak/stall
    # a couldn't-run probe leaves last_gate_red + the streak unchanged — no evidence either way
    if not err:
        return None  # clean or couldn't-run → nothing to fix → stay silent, don't editorialize a pass
    return prompts.render("periodic_gate", truth=err)


def summarize(chat_fn, role, system: str, user: str, rlog, *, phase: str = "compactor",
              max_tokens: int = 8192, retry_off: bool = True, coder_tools: str = "") -> str:
    """The ONE reasoner text-generation primitive — call the model with (system, user) and return the
    text ("" on failure/empty). With ``retry_off`` (default), retries with reasoning FORCED OFF when
    the first pass yields no text (a reasoning model can burn its whole budget THINKING and emit empty
    content); recovers a leaked tool-call 'answer' back to text. Shared by the loop's completion
    compaction (_compact_done), the reasoned redirect (_author_redirect, single-pass), the plan-off
    self-compaction, and the loop's mid-session rollup — one place, so the mechanism can't diverge.
    ``chat_fn(body, rlog) -> bytes`` + ``role`` (Role|None) are the caller's provider + sampling.
    ``coder_tools`` (opt-in): a rendered coder-tool summary. When set, the reasoner is reasoning ABOUT
    the coder's session, so it is prepended as context — the reasoner is otherwise blind to the coder's
    tools and can name an action the coder can't do (it wavered 'we don't have a grep tool' with
    exec_command right there). Compaction/summarization callers leave it empty (not reasoning about acts)."""
    if coder_tools:
        user = prompts.render("reasoner_coder_tools", tools=coder_tools) + "\n\n" + user
    def _one(reasoning_off: bool) -> str:
        call = {"stream": False, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        r = role
        if reasoning_off:
            r = replace(role, reasoning="off") if role is not None else None
        if r is not None:
            r.apply(call, internal=True, rlog=rlog)
        elif reasoning_off:
            call.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        try:
            rlog.phase = phase + ("-noreason" if reasoning_off else "")
            applied = massage.apply(_parse_completion(chat_fn(call, rlog)), None, rlog)
            # A summarize/redirect call offers NO tools, so ANY tool call the model produced (native, or
            # a dialect leak recover_leaked_tool_calls promoted) means it answered in ACT/PLAN mode, not
            # prose. coerce_text_answer then salvages its reasoning_content — but on a "summarize past
            # work" prompt that reasoning is forward PLANNING ("Plan: 1. …", "I should start by…"), not a
            # retrospective. So a tool-call answer's recovered "summary" is the wrong text (the observed
            # 6/6 compactor failures). Fail this (reasoning-ON) pass so the reasoning-OFF retry forces the
            # summary straight into content, where there is no reasoning to leak.
            answered_with_tool_call = bool(
                ((applied.get("choices") or [{}])[0].get("message") or {}).get("tool_calls"))
            comp = massage.coerce_text_answer(applied, rlog)
            text = _completion_text(comp)
            if role is not None:
                text = role.clean_content(text)
            text = _strip_cria_banners(text).strip()
            if massage.has_tool_call_leak(text):
                # A leaked/mangled tool call, not prose — fail this pass so the reasoning-off retry
                # fires. Returning it would inject a wall of `<|tool_call>…` garbage as the briefing.
                rlog.emit("summarize.leaked_tool_call", level="warn", phase=rlog.phase)
                return ""
            if answered_with_tool_call and not reasoning_off:
                rlog.emit("summarize.tool_call_answer", level="warn", phase=rlog.phase)
                return ""  # recovered reasoning is a plan, not a summary — force the reasoning-off retry
            if massage.is_truncated(applied) and text:
                # CUT OFF at the cap with content already emitted. cria checked this nowhere on its
                # own calls — only the plain proxy path surfaces a truncation indicator — so half an
                # answer was consumed as a whole one. Measured across one day's captures: 3 self-
                # compact rollups (one cut mid-JSON), 3 critic verdicts and a plan, all with
                # finish_reason=length and non-empty content. The rollup is the worst of those: it
                # BECOMES the coder's context after a compaction, so adopting a cut one hands it a
                # truncated account of its own work. Fail the pass; the reasoning-off retry has the
                # whole budget for content and usually lands.
                rlog.emit("summarize.truncated", level="warn", phase=rlog.phase, chars=len(text))
                return ""
            return text
        except Exception as e:
            rlog.emit("summarize.error", level="warn", error=str(e))
            return ""
    return (_one(False) or _one(True)) if retry_off else _one(False)


def _add_note(completion: dict, note: str) -> None:
    """Record a cria assist as an out-of-band note on the completion. The server surfaces it as a
    ⟦cria⟧ line when [indicators] assists is on — 'no hidden guards': every intervention that fires
    is visible under the flag. A SEPARATE channel from content, so the loop's parroted-banner scrub
    (_strip_completion_banners) can't drop cria's own intentional notes."""
    if note:
        completion.setdefault("cria_notes", []).append(note)


def guard_gate_verdict(gs: GuardState, body: dict, rlog) -> str | None:
    """Read a completion-gate probe's result and return a block-steer when the repo's checks FAILED,
    else None (genuinely clean, or the checks couldn't run → fail-open, don't wedge). The OBJECTIVE half
    of the loop's completion gate — no reasoner critic — so the plan-off path can verify a 'done' claim
    against ground truth before letting the turn end.

    A failure blocks whether or not cria could parse a location: the file:line errors from
    completion_block_nudge, OR a check that RAN and exited non-zero with no parseable finding
    (failed_unparsed_probes — a test that failed on a bare traceback, a build that errored). Only a
    couldn't-run (exit_code None, no signal) is fail-open — cria's own inability must not wedge a real
    'done'. Without the failed_unparsed_probes arm a failing test whose output didn't parse was accepted
    as a genuine 'done'."""
    probe = _read_tool_result(body.get("messages", []), gs.probe_call_id)
    outcome = probegate.interpret_gate(gs.gate_plan, probe) if gs.gate_plan is not None \
        else probegate.GateOutcome(ran=False)
    if not outcome.ran:
        return None  # the checks couldn't run → accept the 'done' (fail-open, like the loop)
    findings = proberun.completion_block_nudge(outcome.report)
    if findings:
        gs.last_gate_red = True
        track_gate_progress(gs, findings)
        return findings
    failed = proberun.failed_unparsed_probes(outcome.report)
    if failed:  # a check ran and FAILED (no parseable line) → the 'done' isn't genuine
        gs.last_gate_red = True
        msg = "the repo's own checks did not pass — resolve these before finishing:\n" + "\n".join(failed)
        track_gate_progress(gs, msg)
        return msg
    gs.last_gate_red = False  # ran and genuinely clean → GREEN
    gs.last_gate_testless = not proberun.gate_ran_tests(outcome.report)  # vacuous-green evidence for the judge
    gs.last_gate_skipped = proberun.gate_skipped_count(outcome.report)
    track_gate_progress(gs, "")
    return None


def gate_error_text(outcome) -> str:
    """The ERROR-class ground truth from a gate outcome — file:line findings, or a check that RAN and
    FAILED with no parseable location. Returns '' when the gate is clean, couldn't run, or never ran.

    This is the ONLY part a PERIODIC check-in surfaces. On a clean check-in there is nothing to fix, so
    injecting the "the checks pass, but that's not proof of correct behaviour — keep fixing" hedge just
    makes the model distrust a genuine pass and keep working (it can't stop). Judging "is the task
    actually done" is the done-gate's + satisfaction check's job; the periodic gate only surfaces real
    problems early."""
    if not outcome.ran:
        return ""
    findings = proberun.completion_block_nudge(outcome.report)
    if findings:
        return findings
    failed = proberun.failed_unparsed_probes(outcome.report)
    if failed:
        return prompts.render("ground_truth_failed", failed="\n".join(failed))
    return ""


def _gate_notes(sess) -> str:
    """Ground-truth notes for the satisfaction judge about what the gate's test run actually
    verified (prompts/gate_notes.txt): the C4 vacuous-green (0 collected) and the skipped-count fact
    (0728-m11: live tests skipTest() on the exact failure that proves the deliverable broken, and
    "3 passed, 2 skipped" read as green). Empty when there is nothing to disclose — silence over
    noise, and never a doubt-hedge on a clean run."""
    lines = prompts.load_map("gate_notes")
    if getattr(sess, "last_gate_testless", False):
        return "\n\n" + lines["testless"]
    skipped = getattr(sess, "last_gate_skipped", 0)
    if skipped:
        return "\n\n" + prompts.fill(lines["skipped"], count=str(skipped))
    return ""


def _briefing_gate_ground_truth(sess) -> str:
    """A ground-truth check-state line appended to cria's rolling briefing, so a summary that LAUNDERS
    the coder's unverified 'tests pass' claim into a fact is OVERRIDDEN by what the repo's own checks
    actually reported. Silent when cria has no negative signal — it never manufactures a 'green' the gate
    did not give (a red gate with findings, or a green-but-testless gate, are the only claims made)."""
    # Model-facing, so it lives in a prompt file and carries NO literal project name: this string
    # shipped as "GROUND TRUTH — cria ran the repo's own checks…" on every red gate, which is exactly
    # the proper noun principle #17 forbids the model from ever seeing.
    lines = prompts.load_map("briefing_checks")
    if getattr(sess, "last_gate_red", False) and getattr(sess, "last_gate_flag", ""):
        return "\n\n" + prompts.fill(lines["red"], findings=sess.last_gate_flag.strip())
    if getattr(sess, "last_gate_testless", False):
        return "\n\n" + lines["testless"]
    return ""


def guard_ground_truth(outcome) -> str:
    """The coder-facing ground truth from a gate outcome — emitted ONLY when cria has a real,
    code-level signal. cria speaks to the model from POSITIVE signal (a check that actually ran); it
    does not narrate its own failures.

    * error-class findings (a check RAN and found a problem) → the block-nudge (fix these at the line).
    * everything that ran was clean AND nothing failed to launch → a NEUTRAL clean note — framed as
      "no error-class findings", NOT "done" (a content-blind streak can't tell a spiral from honest
      edits, so it must not claim the bug is elsewhere or that the task is finished).
    * anything else — the gate never ran, or a probe FAILED TO LAUNCH / timed out → "" (SILENCE). A
      couldn't-run is almost always cria's OWN setup gap (wrong interpreter, no venv, deps not
      installed, a service not up), not a fact the model can act on. Surfacing it would either confess
      cria's failure as noise or, worse, risk reading as a pass. cria stays quiet; the model proceeds
      on its own judgement (it has its own shell); the miss is logged for the operator, not the model.
    """
    err = gate_error_text(outcome)
    if err:
        return err   # a check ran and found a real error-class problem — surface it
    if not outcome.ran or proberun.unran_probes(outcome.report):
        return ""    # never ran / a probe couldn't launch → no clean signal → stay silent
    return prompts.load("ground_truth_clean")


def guard_canned_redirect(gs: GuardState, outcome) -> str:
    """The canned repetition redirect (no reasoner) — the shared steer both the plan-off path and
    the loop's reasoner-unavailable fallback deliver. The GROUND TRUTH leads (its block-nudge already
    says 'fix these exact problems; go to the reported line, do not rewrite whole files') so the
    concrete error is foregrounded — not buried after the 'you repeated an action' framing, where a
    small model reads past it and rewrites the whole file again. When the checks gave no positive
    signal (couldn't run), guard_ground_truth is empty and the redirect carries no checks block —
    just the 'you repeated an action, do something different' steer."""
    gt = guard_ground_truth(outcome)
    return prompts.render(
        "redirect_canned", repeat_action=gs.repeat_action,
        ground_truth=(f"{gt}\n\n" if gt else ""))


# ---- ONE reasoned steer author behind EVERY detector. A detector (repetition / wheel-spin / thrash /
# flail) is a cheap deterministic TRIGGER; the steer itself is always REASONED here, grounded in the real
# session + the churned files' real on-disk bytes + the repo's checks (+ the coder's private reasoning
# when that was the trigger). It replaces the family of canned "stop rewriting / do something different"
# templates that could prescribe a broken tool or be misread as "abandon the file". The reasoner may
# reply ON_TRACK (the detector was a false positive) → we inject nothing (silence over a bad steer).
# One-line description of WHAT tripped, per condition — the only condition-specific text. Grounded in gs
# so the reasoner knows the concrete signal; the rest of the bundle (session/disk/truth) is uniform.
_STEER_TRIGGER = {
    "repetition": lambda gs, step: (
        f"It keeps repeating the SAME action {REPEAT_FINGERPRINT_N}× without the outcome changing: {gs.repeat_action}"),
    "wheel_spin": lambda gs, step: (
        f"It has rewritten the file `{gs.spin_path}` at least {WHEEL_SPIN_WRITES} times with varying "
        f"content and it still is not converging."),
    "thrash": lambda gs, step: (
        f"The repo's own checks have failed with the SAME error for {gs.gate_stall} rounds while it kept "
        f"editing — it is not converging."),
    "flail": lambda gs, step: (
        "Its recent private reasoning (below) looks like it may be circling on a failure, while no check "
        "is currently steering it."),
}


# cria's own web_fetch render header — `HTTP 200 OK · https://…` — and the endpoints outline it adds
# for a spec. The ` · <url>` shape appears ONLY in a real rendered result, never in the coder's prose,
# so matching it cleanly separates the ground-truth outcome from a hallucinated "the fetch 400'd".
_FETCH_STATUS_RE = re.compile(r"HTTP (\d{3})[^\n·]*·\s*(https?://\S+)")
_FETCH_ROUTES_RE = re.compile(r"\[API endpoints \(\d+\): ([^\]]+)\]")
# The RESPONSE-SHAPE block cria surfaces beside the routes (webfetch.SHAPE_MARKER). It is the half of
# the surfaced facts that names the real FIELDS, and it was never captured into the durable ledger —
# so after a compaction the coder kept the endpoints and lost `resolved_addresses{ada}` / `holder`,
# which is precisely what it then guesses. Multi-line; ends at the block's closing bracket.
def _shape_block(text: str, start: int) -> str:
    """The `[response shape — …]` block beginning at/after ``start``, read by LINE.

    A regex terminated on `]` cannot work here: a field summary marks an array field as `k[]`, so the
    first entry line ending in an array closes the match and every endpoint after it is silently lost
    — measured, that dropped `/holders/{address} → total_handles`, the second call this task needs,
    from the durable ledger the coder is told to "use these EXACT names ... do not guess" from.

    Entry lines are the ones carrying `→`; a trailing note (webfetch's "…+more endpoints have shapes
    not shown here") is kept too, because a cap the model cannot see reads as the complete set."""
    i = text.find(webfetch.SHAPE_MARKER, start)
    if i < 0:
        return ""
    lines = text[i:].splitlines()
    out = [lines[0][len(webfetch.SHAPE_MARKER):].strip()] if lines else []
    for ln in lines[1:]:
        if "→" in ln or ln.strip().startswith("…"):
            out.append(ln.rstrip())
            continue
        break
    block = "\n".join(x for x in out if x.strip()).strip()
    # Drop the block's closing bracket — but never mistake an ARRAY field for it: `holders[]` ends in
    # `]` too, and stripping that turns a real field name into `holders[`.
    return block[:-1].rstrip() if block.endswith("]") and not block.endswith("[]") else block


def _fetch_facts(entry) -> tuple:
    """A ledger entry as ``(status, routes, shapes)``, accepting the older 2-tuple form."""
    status, routes, shapes = (tuple(entry) + ("", ""))[:3]
    return status, routes or "", shapes or ""


def _extract_fetches(messages: list[dict]) -> dict:
    """url -> (status, routes, shapes) for every web_fetch result in ``messages`` (last occurrence
    wins), read from the REAL rendered tool headers. The ` · <url>` shape is cria's render, absent
    from coder prose."""
    latest: dict[str, tuple[str, str, str]] = {}
    for m in messages:
        # TOOL RESULTS ONLY. This used to read every role, and the docstring's premise — "the ` · <url>`
        # shape is cria's render, absent from coder prose" — is false: the coder READS that header in its
        # context and can parrot it. A sentence like "I tried again and got HTTP 400 · <url>" then
        # overwrote the real HTTP 200, and the ok/failed split filed that URL under "THESE URLS DID NOT
        # WORK — do not write code against them" with its real endpoints still attached. That is the
        # hallucination-laundering this ledger exists to defeat (runG: the coder insisted on a 400 the
        # server never sent, the steer parroted it, 40 turns lost).
        if m.get("role") not in ("tool", "function_call_output") and m.get("type") != "function_call_output":
            continue
        c = m.get("content")
        if c is None:
            c = m.get("output") or ""
        if isinstance(c, list):
            c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
        if not isinstance(c, str) or "·" not in c:
            continue
        for sm in _FETCH_STATUS_RE.finditer(c):
            url = sm.group(2).rstrip(".,);")
            rm = _FETCH_ROUTES_RE.search(c, sm.end())
            latest[url] = (f"HTTP {sm.group(1)}", rm.group(1).strip() if rm else "",
                           _shape_block(c, sm.end()))
    return latest


def _merge_fetches(dst: dict, src: dict) -> dict:
    """Merge fetch facts, keeping the RICHER routes AND shapes per URL: a later ``web_fetch(url,
    find=…)`` returns a sub-section WITHOUT the ``[API endpoints]`` / ``[response shape]`` blocks, so
    those are empty — that must not clobber an earlier full outline (they are the whole point of the
    fact: they name /handles/{handle} and resolved_addresses{ada})."""
    for url, entry in src.items():
        status, routes, shapes = _fetch_facts(entry)
        prev = dst.get(url)
        if prev:
            p_routes, p_shapes = _fetch_facts(prev)[1:]
            routes = routes or p_routes   # preserve the earlier outline when this occurrence had none
            shapes = shapes or p_shapes
        dst[url] = (status, routes, shapes)
    return dst


def _fetch_succeeded(status) -> bool:
    """Did this ledger entry actually return something? ``status`` is the rendered "HTTP <code>" from
    the window, or the bare int a session's durable ledger carries — accept either."""
    m = re.search(r"\d{3}", str(status if status is not None else ""))
    return bool(m) and 200 <= int(m.group(0)) < 300


def _format_fetches(latest: dict, header: str = "PAGES YOU HAVE ALREADY FETCHED") -> str:
    """The durable fetch ledger, SPLIT by whether the fetch actually returned anything.

    A failed fetch is not the same kind of fact as a successful one, and merging them into one list
    made the anchor's "code directly against the endpoints and response fields listed above" apply to
    entries that have neither. Observed live (run 0726-132211, 66 calls, empty workspace): the coder
    invented the domain `ada-handles.github.io`, got two 404s, and cria handed it back every turn as
    "your REAL fetch results this session ... you already have it" — restating the hallucination as
    ground truth and telling it to code against a dead URL. Failures are worth keeping (don't re-fetch
    a URL that 404'd) but they must be labelled as the dead ends they are."""
    if not latest:
        return ""
    labels = prompts.load_map("fetched_facts_sections")
    ok, failed = [], []
    for url, entry in latest.items():
        status, routes, shapes = _fetch_facts(entry)
        line = f"- {url} → {status}" + (f"; endpoints: {routes}" if routes else "")
        # THIRD case. The anchor explains an entry WITH facts and an entry that ERRORED; a 2xx whose
        # page had no readable structure looks identical to a successful spec read. Measured (run
        # 0727-142536): the planner fetched the swagger UI SHELL, the coder's entire fetch record was
        # one `→ HTTP 200` under "these SUCCEEDED", and it invented `/resolve/{handle}` with zero
        # occurrences of the real route in its window. A status alone is a fact about the REQUEST.
        if _fetch_succeeded(status) and not routes and not shapes.strip():
            line += labels["no_structure"]
        # The REAL field names — the half the coder guesses once they scroll away. Keep only the
        # per-endpoint entry lines: the captured block opens with webfetch's OWN header, and emitting
        # that under cria's label prints the same instruction twice.
        entries = [ln.strip() for ln in shapes.splitlines()
               if "→" in ln or ln.strip().startswith("…")]   # keep the "…+more" cap note too
        if entries:
            line += f"\n  {labels['fields']}\n" + "\n".join(f"  {e}" for e in entries)
        (ok if _fetch_succeeded(status) else failed).append(line)
    blocks = []
    if ok:
        blocks.append(prompts.fill(labels["ok"], header=header) + "\n" + "\n".join(ok))
    if failed:
        blocks.append(labels["failed"] + "\n" + "\n".join(failed))
    return "\n\n".join(blocks)


def _track_fetched_pages(sess, messages: list[dict]) -> None:
    """Accumulate the session's fetch facts DURABLY on the GuardState, so a steer can still cite that
    api.handle.me/openapi.json returned 200 (with /handles/{handle}) after that result has been floored
    out of the live window — the point when a late wrong-entity spiral (runJ: Windows GetHandleInformation)
    most needs the correction. In-window results still win at read time (see :func:`_fetch_ground_truth`)."""
    if sess is None:
        return
    if getattr(sess, "fetched_pages", None) is None:
        sess.fetched_pages = {}
    _merge_fetches(sess.fetched_pages, _extract_fetches(messages))


def _fetched_facts_anchor(sess) -> dict | None:
    """A ⟦ctx:facts⟧ anchor carrying cria's DURABLE fetch ledger (url→status→endpoints), re-injected into
    the coder's OUTBOUND view every turn there are facts — so the coder KEEPS the real endpoints/fields it
    already fetched even after the HARNESS compacts the raw tool result out of its OWN history. cria's own
    anchoring can't protect that: it only ever sees what the harness sends, and the harness compacts before
    the request arrives. But cria controls the view it sends UPSTREAM to the model, so it re-injects the
    ledger from its server-side memory. Without it the coder re-fetches a spec whose routes cria already
    surfaced (observed live: 370 calls re-reading api.handle.me/openapi.json, its /handles/{handle} outline
    scrolled off; 0 of the last 20 coder prompts still held it). GENERAL: fires only when real fetches exist
    (sess.fetched_pages); a task with no web_fetch (a bash/git chore) has an empty ledger → nothing injected.
    Additive ground truth — the real tool results, never a claim about work not done."""
    ledger = _fetch_ground_truth([], sess, header="PAGES YOU HAVE ALREADY FETCHED")
    if not ledger.strip():
        return None
    return {"role": "user", "content": prompts.render("fetched_facts_anchor",
                                                       marker=selfcompact.FACTS_MARKER, ledger=ledger)}


def _insert_after_system(msgs: list[dict], anchor: dict) -> list[dict]:
    """Place ``anchor`` right after the leading system/developer message(s) — in the protected head, so it
    is always visible to the model and never reads as the oldest droppable turn."""
    i = 0
    while i < len(msgs) and msgs[i].get("role") in ("system", "developer"):
        i += 1
    return msgs[:i] + [anchor] + msgs[i:]


def _fetch_ground_truth(messages: list[dict], sess=None,
                        header: str = "PAGES YOU HAVE ALREADY FETCHED") -> str:
    """Deterministic FACTS about the web_fetches already made — final status per URL + any endpoint
    routes. Handed to the steer author so a weak reasoner can't echo the coder's hallucination that a
    fetch failed when it actually returned 200 (runG: the coder insisted api.handle.me/openapi.json gave
    a 400; it returned HTTP 200 with 33 endpoints incl. /handles/{handle}, and the steer PARROTED the
    400 — 40 wasted turns). Merges the session's DURABLE facts (kept past the window) with the current
    window, so the correction survives even after the result scrolls out; in-window status wins. ``header``
    re-frames the subject for a non-coder reader (the step critic)."""
    latest = _merge_fetches(dict(getattr(sess, "fetched_pages", None) or {}), _extract_fetches(messages))
    return _format_fetches(latest, header)


# Derived from the ONE canonical shell-tool family (shelltool.SHELL_TOOL_NAMES) so it can't drift — a
# hand-kept second copy had already lost `shell_command` and would leave a `shell_command` harness
# unflagged to the steer reasoner (match-by-family, principle #18). `container.exec` is added for the
# summary's broader "does the coder have ANY shell?" question (it's not a write-lowering target).
_SHELL_TOOLNAMES = SHELL_TOOL_NAMES | {"container.exec"}


def _coder_tools_summary(tools) -> str:
    """One line per tool the CODER has (name + its params) — so a reasoner authoring a steer grounds any
    action it suggests in what the coder can ACTUALLY do. Observed: the coder wavered on whether it could
    grep, with exec_command right there; a reasoner that can't see the coder's tools can't say 'run
    grep via exec_command'. The shell tool is flagged explicitly — it runs grep/cat/sed/python/pytest/…."""
    lines = []
    for t in (tools or []):
        fn = t.get("function") or t
        name = fn.get("name")
        if not name:
            continue
        params = list(((fn.get("parameters") or {}).get("properties") or {}).keys())
        sig = f"{name}({', '.join(params)})"
        if name in _SHELL_TOOLNAMES:
            sig += " — runs ANY shell command (grep, cat, sed, ls, find, python, pytest …)"
        lines.append("  - " + sig)
    return "\n".join(lines) or "  (none advertised this turn)"


def author_steer(reasoner_chat, reasoner_role, workspace_root, gs, body: dict, rlog, *,
                 condition: str, outcome=None, truth_text: str = "", step_text: str = "",
                 reasoning_window=None) -> str | None:
    """THE single reasoned steer author. A detector fired (``condition``); hand a no-tools reasoner the
    FULL grounded picture — the real session (scrubbed of cria's own plumbing AND the harness's own agent
    prompt), the churned files' real ON-DISK bytes, the repo's check output, and (for the flail trigger)
    the coder's recent private reasoning — and let it diagnose why the coder is stuck and give ONE
    concrete, grounded next step. Returns the directive, or ``None`` when the reasoner judges the coder is
    actually progressing (``ON_TRACK``) or yields nothing — the caller decides whether to fall back.

    We hand it the real session rather than a curated slice: a curated view is exactly what made an
    earlier steer invent a path. The one thing dropped is the harness's agent system prompt
    (:func:`_drop_harness_frame`) — that is the coder's FRAME, not part of what the coder DID, and the
    reasoner has its own supervisor prompt; every user/assistant/tool turn stays verbatim, so this is not
    the curation the note above warns against. Grounded in what actually happened (and no longer padded
    with a quarter-prompt of Codex boilerplate), it cannot hallucinate a filesystem it cannot see."""
    session = selfcompact.serialize(
        _drop_harness_frame(probegate.clean_gate_results(_reasoner_session(body.get("messages", [])))))
    # recent_writes is a CONSUMABLE detector window — interventions flush it by design, which left
    # the steer author's on-disk section reading "(no files touched yet)" for an ENTIRE run (14
    # steers judging a one-character file bug blind, run 0729-gemma4) while the workspace held the
    # files. The durable source is the normalized history itself: every write the coder ever made
    # is still there as a tool_call (paths survive compaction stubs).
    touched = _touched_paths(body.get("messages", []))
    recent = list(getattr(gs, "recent_writes", None) or []) + touched if gs is not None else touched
    disk = _fresh_disk_facts(workspace_root, recent, getattr(gs, "spin_path", "") if gs is not None else "")
    truth = truth_text or (guard_ground_truth(outcome) if outcome is not None else "")
    # Fold the deterministic fetch outcomes in with the check truth so the reasoner grounds on what the
    # fetches ACTUALLY returned, not the coder's narration of them (the hallucinated-400 amplification).
    # Pass gs so DURABLE facts (a spec fetched long ago, now floored out) still reach the steer.
    # THIRD-person header — the default "PAGES YOU HAVE ALREADY FETCHED" told the STEER AUTHOR that
    # it had fetched pages (role-collapse fuel for the same reasoner that fabricates transcripts).
    # And checks-truth FIRST: the template's label says "GROUND TRUTH FROM THE REPO'S CHECKS", so the
    # checks must sit directly under it, not the fetch block (run 0729-gemma4: every steer prompt
    # opened the checks section with fetch content and floated the checks below the endpoint list).
    fetch_truth = _fetch_ground_truth(body.get("messages", []), gs, header=CODER_FETCH_HEADER)
    truth = "\n\n".join(t for t in (truth, fetch_truth) if t)
    reasoning = "\n\n--- turn ---\n".join(reasoning_window) if reasoning_window else ""
    trigger = _STEER_TRIGGER[condition](gs, step_text)
    user = prompts.render("steer_diagnose_user", trigger=trigger, session=session,
                          disk=(disk or "(no files touched yet)"),
                          truth=(truth or "(no check results for this steer)"),
                          reasoning=(reasoning or "(not captured for this trigger)"))
    text = (summarize(reasoner_chat, reasoner_role, prompts.load("steer_diagnose"), user, rlog,
                      phase="reasoner", coder_tools=_coder_tools_summary(body.get("tools"))) or "").strip()
    return _grounded_steer_or_none(_steer_or_none(text), user, rlog)


def _steer_or_none(text: str) -> str | None:
    """A steer_diagnose reply → the directive to inject, or None for a genuine "on track" verdict. The
    "fine, no help" sentinel is ON_TRACK — a POSITIVE token on purpose: the old NOT_STUCK was a negation
    trap a weak reasoner would emit for the WRONG reason ("the coder is NOT progressing → NOT_STUCK"),
    vetoing its own rescue while looping. A verbose reasoner (Fabliq) also HEDGES — it writes the verdict
    token and THEN a real, grounded directive ("the endpoint is GET /handles/{handle}, stop fetching,
    write it"); a naive prefix check discarded the whole reply, silently dropping good steers. Strip the
    verdict token(s) + think/markdown scaffolding; deliver whatever substantive directive remains, and
    treat it as an on-track veto only when essentially nothing else is there. (Legacy NOT_STUCK still
    stripped, in case a model reaches for the old word.)"""
    if not text:
        return None
    body = strip_think(text)
    body = re.sub(r"```[a-z]*|`|</?think>|</?assistant>", " ", body)      # markdown/channel scaffolding
    # Drop every SENTENCE that carries a verdict token, rather than excising the token and keeping the
    # wreckage of the sentence around it. Both prompts end by teaching the exact bigram "is NOT
    # ON_TRACK", so a reasoner that agrees the coder is stuck echoes it — and token-level stripping
    # left the negation behind: "NOT ON_TRACK" became "NOT" (under the floor → read as an on-track
    # VETO, silently cancelling the rescue the reasoner had just called for) and "The coder is NOT
    # ON_TRACK" became "The coder is NOT", which cleared the floor and was injected into the coder AS
    # its rescue. That is the NOT_STUCK negation trap this sentinel was renamed to escape.
    # A verdict sentence carries no instruction either way, so losing it costs nothing, and the hedge
    # this function exists for survives: Fabliq's "ON_TRACK. You keep re-fetching; write it now."
    # keeps its second sentence. Nothing left → the caller falls back to its grounded text.
    # A NEGATED verdict takes its whole sentence (it asserts a judgement and carries no instruction);
    # a BARE token is only a label on a hedged reply and is excised in place, so "ON_TRACK You are
    # stuck; write it now" keeps its directive.
    negated = re.compile(r"(?i)\b(?:not|never|isn't|aren't)\s+(?:on[_ ]track|not[_ ]stuck)\b")
    kept = [s for s in re.split(r"(?<=[.!?])\s+|\n+", body) if not negated.search(s)]
    directive = re.sub(r"(?i)\b(on[_ ]track|not[_ ]stuck)\b", " ", " ".join(kept))
    directive = re.sub(r"\s+", " ", directive).lstrip(" >-*:.,;").strip()
    # A directive remains once the verdict is stripped → deliver it (Fabliq hedges the verdict + advice);
    # essentially nothing left → a genuine on-track veto, inject nothing. The small floor skips a bare
    # "ok"/"yes" residue without discarding a real short steer.
    return directive if len(directive) >= 8 else None


# A steer that CONTAINS a transcript is not a directive — it is the reasoner role-playing the
# session: fake tool calls with invented file content, fake "tool: Wrote …" results, fake command
# output. Injected as ⟦ctx:steer⟧ it reads as fact (observed: the coder copied a steer's INVENTED
# mock addresses verbatim into the shipped file, run 0729-mellum2 call 0157). Deterministic
# markers of transcript syntax — never a judgment call:
_ROLEPLAY_STEER = re.compile(
    r"(?m)(?:\b(?:write_file|edit_file|exec_command|read_file|web_fetch|apply_patch)\s*\(\s*\{"   # tool-call syntax
    r"|^\s*(?:assistant|tool|user)\s*:\s"      # transcript role labels
    r"|⟦ctx:"                                   # a steer must not nest cria's own markers
    r"|\b[Ii] will (?:write|create|implement|add|run|fix|build)\b)"  # the author announcing ITS OWN
    # plans — the steer contract is second person ("You …"); "I will write resolve.py" is the
    # reasoner in the coder's seat (run 0729-mellum2 call 0059, injected verbatim, twice-doubled)
)


def _dedupe_doubled(text: str) -> str:
    """A weak reasoner sometimes emits its directive twice, verbatim, in one reply (run
    0729-mellum2: the identical paragraph back-to-back). Injecting the doubled text doubles the
    noise a small coder must wade through — keep one copy when the halves match exactly."""
    t = text.strip()
    half, rem = divmod(len(t), 2)
    if half > 40:
        a, b = t[:half].strip(), t[half + rem:].strip()
        if a == b:
            return a
    return text


def _grounded_steer_or_none(directive: str | None, evidence: str, rlog) -> str | None:
    """The authored steer, or None when it names a URL the evidence cannot support.

    The steer author's own system prompt already says "NEVER invent a file path, directory, command,
    value, or error that does not appear above" — but a prompt is a request, not an enforcement, and a
    small reasoner breaks it. This is the enforcement, and it is deterministic: cria composed the
    evidence, so it can check the claim against it exactly rather than judging it.

    The whole steer is withheld, not just the bad URL: a directive built AROUND an invented route
    ("fetch the response from <invented>, parse the JSON …") is wrong as a whole, and excising the URL
    would leave cria authoring a mutilated instruction — repairing a guess with another guess. The
    callers that need a signal already have a grounded one to fall back to (the canned redirect, the
    raw check truth); the flail caller falls back to silence, which is the correct assist here."""
    if not directive:
        return None
    directive = _dedupe_doubled(directive)
    if _ROLEPLAY_STEER.search(directive):
        rlog.emit("loop.steer_roleplay_dropped", level="warn", head=_clip(directive, 120))
        return None
    bad = urlgrounding.ungrounded_urls(directive, evidence)
    if bad:
        rlog.emit("loop.steer_ungrounded", level="warn", urls=",".join(bad))
        return None
    return directive


def author_redirect(reasoner_chat, reasoner_role, workspace_root, step_text: str,
                    gs: GuardState, outcome, body: dict, rlog) -> str:
    """The REASONED redirect (repetition trigger) — a thin wrapper over :func:`author_steer`. Falls back
    to the canned redirect when the reasoner declines/yields nothing: the identical-repeat signal is
    strong, so a stuck repeater is never left without a steer."""
    return author_steer(reasoner_chat, reasoner_role, workspace_root, gs, body, rlog,
                        condition="repetition", outcome=outcome, step_text=step_text) \
        or guard_canned_redirect(gs, outcome)


def author_thrash_steer(reasoner_chat, reasoner_role, workspace_root, gs: GuardState,
                        truth: str, body: dict, rlog) -> str:
    """C5 — the reasoned thrash-assist (thrash trigger) — a thin wrapper over :func:`author_steer`. The
    persistent-error string is the trigger's ground truth; on an ON_TRACK / empty reasoner reply we fall
    back to inserting that raw ground truth (the periodic check-in's baseline behaviour, valuable on its
    own — the reasoned diagnosis is an upgrade of it, not a replacement)."""
    return author_steer(reasoner_chat, reasoner_role, workspace_root, gs, body, rlog,
                        condition="thrash", truth_text=truth, step_text="") or truth


# ---- QUIET-FLAIL detector: the coder's REASONING is circling (re-trying the same failed thing) while
# no gate/guard is steering. The gate catches "the checks stay red"; this catches "the coder keeps
# THINKING the same thing" — the thrash the capsys/venv sessions showed with almost no gate activity.
# A cheap LENIENT lexical pre-filter (below) only decides whether to spend a reasoner call; the reasoner
# makes the real stuck/not-stuck call. Calibrated on real captured reasoning: fires on both thrash
# sessions, never on the clean one. See docs + tests/test_flail.py.
FLAIL_WINDOW = 4             # coder reasonings examined for circling
FLAIL_MIN_STRUGGLING = 2     # of the window, how many must show struggle language to spend a reasoner call
FLAIL_COOLDOWN = 5           # coder drives between flail diagnoses (a steer needs room to land)
MAX_FLAIL_STEERS_PER_STEP = 3  # cap flail steers on ONE step. The cooldown SPACES them but does not BOUND
#                                the total, so a step stuck for hundreds of drives drew ~25 steers — each
#                                redirecting the coder, so cria's OWN steers thrashed an already-stuck coder
#                                (assists are footguns; silence over noise). A few grounded unstick nudges,
#                                then SILENCE and let the gate/satisfaction/advance carry it. Reset on advance.
# BROAD struggle vocabulary — a PRE-FILTER, not a judge: its only job is to skip windows with no failure
# language at all (obvious progress) so the reasoner isn't run on healthy work. The reasoner judges.
_STRUGGLE_RE = re.compile(
    r"\b(?:fail(?:ed|ing|ure)?|doesn't|does not|didn't|isn't|is not|wasn't|can't|cannot|won't|error|"
    r"broke|broken|still|again|instead|guessing|keep|the real|tried|another|revert|retry|no longer|"
    r"but the|however|wrong|invalid|not exist|neither|turns out|mistake)\b", re.IGNORECASE)


def _reasoning_of(comp: dict) -> str:
    """The coder's private reasoning from a completion — the split-out ``reasoning_content`` when the
    server provides it, ELSE the message ``content`` (a model that inlines its thinking with no separate
    channel). Mirrors the rumination watcher's ``reasoning or content`` fallback (upstream.py) so the
    quiet-flail detector isn't silently INERT for any model that doesn't split reasoning out — the
    `_reasoning_of` used to read only reasoning_content, disabling the whole flail assist for such a model."""
    for ch in comp.get("choices", []):
        msg = ch.get("message") or {}
        r = msg.get("reasoning_content") or msg.get("reasoning") or msg.get("content")
        if isinstance(r, str) and r.strip():
            return r.strip()
    return ""


def _record_reasoning(sess, comp: dict) -> None:
    """Keep the coder's last FLAIL_WINDOW reasonings on the session for the flail pre-filter."""
    r = _reasoning_of(comp)
    if r:
        sess.recent_reasoning = (sess.recent_reasoning + [r])[-FLAIL_WINDOW:]


def _flail_candidate(window: list[str]) -> bool:
    """LENIENT pre-filter: does the recent reasoning look like it MIGHT be circling on a failure? Skips
    windows with no struggle language (clear progress) so the reasoner isn't spent on healthy work — the
    reasoner then makes the real call. Needs a full window of FLAIL_WINDOW turns first."""
    if len(window) < FLAIL_WINDOW:
        return False
    return sum(1 for r in window if _STRUGGLE_RE.search(r)) >= FLAIL_MIN_STRUGGLING


def author_flail_steer(reasoner_chat, reasoner_role, window: list[str], body: dict, rlog) -> str | None:
    """The reasoned FLAIL-assist (flail trigger) — a thin wrapper over :func:`author_steer`. The pre-filter
    fired on the coder's circling PRIVATE reasoning (which the transcript doesn't carry), so we pass that
    reasoning window alongside the real session; the reasoner decides stuck-or-ON_TRACK. There is no gate
    outcome and no GuardState here (the trigger is reasoning, not a check/write count), so disk facts are
    empty — the reasoner grounds on the session's own tool results and reads on demand via the steer."""
    return author_steer(reasoner_chat, reasoner_role, None, None, body, rlog,
                        condition="flail", reasoning_window=window)


def _substitute_fetch(coder: dict, msg: dict, tc: dict, url: str, note: str) -> dict:
    """Swap one tool call for a web_fetch of ``url`` and attach ``note`` telling the coder cria did it."""
    msg["tool_calls"] = [{"id": tc.get("id") or ("call_" + uuid.uuid4().hex[:16]), "type": "function",
                          "function": {"name": "web_fetch", "arguments": json.dumps({"url": url})}}]
    _add_note(coder, note)
    return coder


_URL_LIKE = re.compile(r"^(https?://\S+|(?:[a-z0-9-]+\.)+[a-z]{2,}/\S*)$", re.I)
# A read (read_file path / cat|grep command) that targets a spilled search-results file, and the search
# POINTER that names (query, file) — cria controls this filename, so a read of it is unambiguously the
# model consuming a search's results, which the read-judge then checks for relevance.
_SEARCH_FILE_RE = re.compile(r"\.?/?tmp/read-only/search-[\w.\-]+\.txt")
_SEARCH_POINTER_RE = re.compile(r'web_search "([^"]*)"\s*[—-]+\s*results saved to (\.?/?tmp/read-only/search-[\w.\-]+\.txt)')


def _toolcall_reads_search_file(tc) -> str | None:
    """The ./tmp/read-only search file a tool call reads (read_file path / a cat|grep command), else None."""
    raw = (tc.get("function") or {}).get("arguments")
    s = raw if isinstance(raw, str) else json.dumps(raw or {})
    m = _SEARCH_FILE_RE.search(s or "")
    return m.group(0) if m else None


def search_file_text(workspace_root: str, rel: str) -> str:
    """The REAL results in a spilled search file, read from DISK NOW — "" when it can't be read.

    The read-judge decides whether to DELETE the coder's search results, so it must judge the RESULTS.
    It used to be handed the tool RESULT of the coder's read, which for a spilled file is not the
    results at all — it is cria's own pointer/steer ("<path> is a large reference document — grep it
    instead"). Observed live: the judge was asked "do the RESULTS contain the right thing?" about that
    boilerplate, answered results_on_target=false (it had seen no results), and cria permanently
    stripped a search whose top hits were the API's own GitHub repo and the URL of its real spec —
    on step 1 of a research step. cria authored the file, so it reads the bytes itself rather than
    judging its own envelope (principle #11: read disk NOW, never the transcript's view of a file).
    """
    if not rel:
        return ""
    try:
        root = Path(workspace_root or ".").resolve()
        p = (root / rel.lstrip("./")).resolve()
        if root not in p.parents and p != root:
            return ""     # never read outside the workspace, whatever the path claimed
        return p.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _looks_like_url(s: str) -> bool:
    """A recommendation that is a concrete URL / domain+path to fetch, not a search phrase."""
    return bool(_URL_LIKE.match((s or "").strip()))


def guard_search_query(sess: GuardState, coder: dict, body: dict,
                       reasoner_chat, reasoner_role, rlog) -> dict:
    """Judge an OUTGOING web_search query before it runs (reduce flailing at the source). Off-target →
    substitute a web_fetch when the recommendation is a URL, else re-issue the recommended query. The
    verdict is cached per query, so a repeated off-target query is re-substituted without a fresh call."""
    msg = (coder.get("choices") or [{}])[0].get("message") or {}
    search_tc = next((tc for tc in (msg.get("tool_calls") or []) if _tool_name(tc) == "web_search"), None)
    if search_tc is None:
        return coder
    query = str(massage._args((search_tc.get("function") or {}).get("arguments")).get("query", "")).strip()
    if not query:
        return coder
    if sess.query_verdicts is None:
        sess.query_verdicts = {}
    task = latest_user_text(body.get("messages", []))
    tools_summary = _coder_tools_summary(body.get("tools"))
    # The repeat gate downstream refuses this search if it overlaps a visible earlier one, on four
    # hand-tuned word counts. Ask about exactly the pair it would act on — and only when it WOULD act,
    # so a search with no prior costs nothing. A clear "different hunt" clears the query; anything
    # else leaves the gate's verdict alone, so this can only ever refuse LESS.
    # An IDENTICAL query is not a judgement call, it is identity — re-running the same search
    # returns the same results, and asking anyway is how a repeat got cleared (measured: the coder
    # then issued it three times). Only an OVERLAPPING query is worth a reasoner call.
    prior = webfetch.prior_matching_search(sess.web_session, query)
    if prior and normalize_search(prior) == normalize_search(query):
        prior = None
    if prior and query not in (sess.rehunt_verdicts or {}):
        if sess.rehunt_verdicts is None:
            sess.rehunt_verdicts = {}
        fresh = judge_rehunt(reasoner_chat, reasoner_role, task, query, prior, rlog,
                             coder_tools=tools_summary)
        sess.rehunt_verdicts[query] = fresh
        if fresh:
            webfetch.allow_search(sess.web_session, query)
            rlog.emit("loop.search_rehunt_cleared", query=query, prior=prior)
    if query in sess.query_verdicts:
        on_target, rec = sess.query_verdicts[query]
    else:
        on_target, rec = judge_query(reasoner_chat, reasoner_role, task, query, rlog,
                                     coder_tools=tools_summary)
        sess.query_verdicts[query] = (on_target, rec)
    if on_target or not rec:
        return coder
    # The recommendation must be a QUERY before it can replace the coder's own. Measured: 47% of all
    # searches today were rewritten, and the replacements included `web_search('…')` wrappers and
    # instruction sentences used verbatim as the search string. An unusable recommendation means cria
    # leaves the coder's query alone — substituting a worse query is strictly worse than not acting.
    rec = _usable_query(rec)
    if not rec:
        rlog.emit("loop.search_rec_unusable", level="warn", query=query)
        return coder
    if _same_query(rec, query):
        return coder      # a query rewritten to itself is not a redirect — touch nothing, log nothing
    if _looks_like_url(rec):
        url = rec if rec.lower().startswith("http") else "https://" + rec
        # SUBSTITUTING the coder's own tool call is the strongest thing cria does here, and the url it
        # substituted was never checked — while an authored steer's url is (_grounded_steer_or_none).
        # Only the HOST is required here, not the path: this judge's whole job is to say "fetch the
        # spec of the domain the task named", and a path nobody has fetched yet is exactly what it is
        # for. What it must not do is send the coder to a site it invented — which its own prompt
        # invites, saying "never invented" and then asking it to synthesise `<domain>/openapi.json`.
        evidence = task + "\n" + selfcompact.serialize(_reasoner_session(body.get("messages", [])))
        if not urlgrounding.host_is_grounded(url, evidence):
            rlog.emit("loop.search_query_ungrounded", level="warn", query=query, rec=url)
            return coder
        rlog.emit("loop.search_query_judged", action="fetch", query=query, rec=url)
        return _substitute_fetch(coder, msg, search_tc, url,
                                 f"'{query}' looked off-target for this task — fetching {url} instead")
    search_tc["function"] = {**(search_tc.get("function") or {}), "arguments": json.dumps({"query": rec})}
    _add_note(coder, f"'{query}' looked off-target for this task — searching '{rec}' instead")
    rlog.emit("loop.search_query_judged", action="requery", query=query, rec=rec)
    return coder


# Explicit sentinel for a path that genuinely has NO reasoner: it must pass author=CANNED, not omit the
# arg. `author` is REQUIRED (below) so a path can never silently select the degraded canned redirect by
# omission — the failure class the parity audit caught (a shared guard with an optional-degraded default).
CANNED = object()


def guard_probe_steer(gs: GuardState, body: dict, rlog, *, author, step=None) -> str | None:
    """A guard probe (repetition redirect or wheel-spin) we emitted last turn has now run — read its
    result, interpret the gate, and return the steer text to hand the coder. ``author`` is REQUIRED: a
    callable that REASONS the redirect from ground truth (both paths now supply one via
    :func:`author_redirect`), or the ``CANNED`` sentinel when a path truly has no reasoner. Returns None
    when this isn't a guard probe (a plan completion-gate — the loop handles that itself)."""
    if not (gs.spin_probe or gs.redirect_probe):
        return None
    probe = _read_tool_result(body.get("messages", []), gs.probe_call_id)
    outcome = probegate.interpret_gate(gs.gate_plan, probe) if gs.gate_plan is not None \
        else probegate.GateOutcome(ran=False)
    if gs.redirect_probe:  # repetition: a REASONED redirect (or the canned floor when no reasoner)
        gs.redirect_probe = False
        gs.steer_source = "repetition guard"
        redirect = guard_canned_redirect(gs, outcome) if author is CANNED \
            else author("repetition", gs, outcome, body, rlog)  # author_redirect keeps a canned floor → never None
        rlog.emit("loop.redirect", step=step, chars=len(redirect))
        return f"[REDIRECT]\n{redirect}"
    # wheel-spin: the same file rewritten with varying content. A REASONER reads the file's real on-disk
    # bytes + the checks + the session and authors a grounded unstick — NOT a canned "stop rewriting"
    # that prescribes a broken edit or reads as "abandon the file". When it declines / there's no reasoner,
    # fall back to INSERTING the ground truth (fact, always worth surfacing) — never a suppressed probe (a
    # None here would misroute into the completion gate). The step stays open either way; no verdict.
    gs.spin_probe = False
    gs.steer_source = "wheel-spin guard"
    truth = guard_ground_truth(outcome)
    canned = prompts.render("spin_ground_truth", spin_path=gs.spin_path, truth=truth) if truth \
        else prompts.render("spin_no_truth", spin_path=gs.spin_path)
    steer = canned if author is CANNED else (author("wheel_spin", gs, outcome, body, rlog) or canned)
    rlog.emit("loop.spin_probe_result", step=step, spoke=True)
    return steer


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


def _refusal_turn(body: dict, text: str) -> None:
    """Append a model-facing note to the OUTBOUND conversation so a dropped tool call is visible to the
    coder on its next turn. cria's ⟦cria⟧ notes are human indicators and are stripped before the model,
    so a refusal recorded only there leaves the coder with no result, no error, and no advice — it
    re-sends the same doomed call. Mutates ``body["messages"]`` in place; harmless if absent."""
    msgs = body.get("messages")
    if isinstance(msgs, list) and text:
        msgs.append({"role": "user", "content": text})


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
    # SELF-TRUNCATED write: the model cut its own write_file off mid-content (a normal `tool_calls`
    # finish, not `length` — so `is_truncated` never sees it), leaving the `content` string unclosed.
    # massage's arg-recovery refuses to salvage a partial, so the arguments are still malformed here.
    # Refuse it the SAME way as a length-truncation: never lower a half-written file to disk. The turn
    # then reads as non-acting and the caller gates on ground truth rather than a broken file.
    # A cut-off response comes in TWO shapes: it hit the output cap (`is_truncated`), or it cut its OWN
    # tool arguments off mid-string on a normal `tool_calls` finish. Both leave a half-written file that
    # must never reach disk, and both have the SAME remedy — build the file in small pieces.
    def _cut_off(c: dict) -> bool:
        return massage.is_truncated(c) or massage.has_incomplete_tool_args(c)

    if not massage.is_truncated(coder) and massage.has_incomplete_tool_args(coder) \
            and _truncated_write_path(coder) is None:
        # Not a write (e.g. a shell command with inline code) — there is nothing to chunk, so refuse it.
        rlog.emit("loop.incomplete_tool_call_dropped", step=step)
        _drop_tool_calls(coder)
        _add_note(coder, "tool call was cut off mid-arguments — partial call refused")
        # ...and tell the MODEL too: _add_note is a ⟦cria⟧ human indicator, stripped before the model,
        # so a refusal reported only there is invisible to the coder — its call just vanishes.
        _refusal_turn(body, prompts.load_map("call_refused")["incomplete_args"])
        return coder
    attempt = 0
    conv = list(body.get("messages") or [])
    while _cut_off(coder) and attempt < MAX_TRUNCATION_RETRIES:
        path = _truncated_write_path(coder)
        out_tok = _output_tokens(coder)
        # A SELF-cut write used to fall out here with only a ⟦cria⟧ note — which is HUMAN-facing and
        # stripped before the model, so the coder was told nothing at all: its write silently never
        # landed and it re-sent the same oversized write. Observed live (run 0726-133755): 7 self-cut
        # writes, 81 calls, empty workspace. It gets the same real remedy the cap-truncation gets,
        # worded truthfully for what actually happened (it stopped itself; it did not hit the cap).
        selfcut = not massage.is_truncated(coder)
        rlog.emit("loop.truncated", step=step, attempt=attempt + 1, path=path,
                  output_tokens=out_tok, selfcut=selfcut)
        if path is None:
            break  # not a mid-write truncation → the write steer doesn't apply; refuse below
        attempt += 1
        rlog.phase = f"{phase}-continue{attempt}"
        remedy = (prompts.render("truncation_guard_selfcut", path=path) if selfcut else
                  prompts.render("truncation_guard", path=path,
                                 limit=f"~{out_tok} tokens" if out_tok else "the output-token limit"))
        conv = conv + [{"role": "user", "content": remedy}]
        coder = massage.apply(
            _parse_completion(coder_chat({**body, "messages": conv}, rlog)), body.get("tools"), rlog)
    dropped = _cut_off(coder)
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
        # SAY WHICH IT WAS. The retry remedy already distinguishes a self-cut from a cap; these two
        # closing messages did not, so the model got the correct diagnosis on the retry and "your
        # response hit the output limit" on exhaustion — cria contradicting itself about one event.
        # Measured (run 0727-145921): 17 truncations, ALL self-cuts. It matters: told it hit a limit,
        # a model shrinks its content, and a generation that ended early is not fixed by being shorter.
        _add_note(coder, ("output stopped early mid-write — partial write refused (retry in smaller pieces)"
                          if selfcut else
                          "output hit the token limit — partial write refused (retry in smaller pieces)"))
        _refusal_turn(body, prompts.load_map("call_refused")[
            "selfcut_write" if selfcut else "truncated_write"])
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




def _touched_paths(messages, cap: int = 8) -> list[str]:
    """Paths the coder actually WROTE this session, recovered from the normalized history's
    assistant tool_calls — the durable record. GuardState's recent_writes window is consumed by
    detector interventions (flushed on purpose), so it alone cannot ground the steer author's
    on-disk section. Newest-last, deduped, bounded to the last ``cap`` distinct paths."""
    seen: list[str] = []
    for m in messages or []:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            p = _write_path(tc.get("function") or {})
            if p:
                if p in seen:
                    seen.remove(p)   # re-touch moves it to newest
                seen.append(p)
    return seen[-cap:]


def _fresh_disk_facts(root: str | None, recent_writes, spin_path: str) -> str:
    """The files the coder has been TOUCHING, read from disk NOW (via cria.groundtruth) — not the
    transcript's stale 'what the model said it wrote' view. This is the grounding the reasoned
    redirect was missing (groundtruth.py was ported but never wired). Empty when the workspace root
    is unknown or nothing has been written yet, so the redirect degrades to its prior behavior."""
    if not root or root == ".":   # "." is cria's OWN dir, never the coder's workspace — never read it
        return ""
    paths: list[str] = []
    for p in list(recent_writes or []) + [spin_path]:
        if p and p not in paths:
            paths.append(p)
    if not paths:
        return ""
    snaps = groundtruth.file_snapshot(root, paths, groundtruth.DEFAULT_FILE_CAP)
    return groundtruth.GroundTruth(files=snaps).render()


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
# Shell boilerplate stripped from an action's word-set before repetition matching: the interpreter
# invocation, PLUS output-plumbing that shapes a command's OUTPUT without changing what it
# investigates — the `cd` prefix, output pagers/formatters (head/tail/cat/less/more/wc/nl), and the
# `/dev/null` redirect noise. Incident (api.handle.me, 2026-07-21): the coder ran `git log --oneline
# -5`, then `… 2>&1`, then `… 2>&1 | head -n 5` — same failing command, but the pipe/redirect added
# ~5 jitter tokens, dropping Jaccard to 0.64 (jitter>2 AND <0.7), so the variants scattered into
# separate signatures and the redirect fired ~16 calls late instead of at the 3rd. Stripping the
# plumbing collapses the variants to their shared core (`git log --oneline`) so the spin trips on time,
# while distinct commands (git log vs ls vs git rev-parse; cat a.py vs cat b.py) still don't match.
_BOILERPLATE_WORDS = frozenset({
    "bash", "sh", "zsh", "dash", "-lc", "-c", "-l", "-e", "env",
    "cd", "head", "tail", "cat", "less", "more", "wc", "nl", "-n", "dev", "null"})

# Navigation/read tools whose repeated use is usually PROGRESS, not a spiral: paging through a doc
# (web_fetch cursor), drilling by key (find), reading further into a file (start_line), listing a new
# dir. Their word-set signature is dominated by a constant host/path token ({http, api.handle.me}), so
# three progressive fetches at different cursors falsely matched as "the same action" and tripped the
# repetition redirect — aborting a legitimate paginated read. For these, the signature keys on the
# DISTINGUISHING locator, so a changed url/path/cursor/find/offset reads as progress; only the SAME
# target repeated (which the web_fetch visibility gate already refuses) matches.
_NAV_TOOLS = frozenset({"web_fetch", "web_search", "read_file", "list_dir"})


def _action_signature(name: str, args: str) -> tuple:
    """The NATURE of a tool call, for repetition matching — not its bytes. A write is its
    target + content (path, content-hash); a nav/read tool is its target + locator (so paging or
    drilling to a new spot is progress, not a repeat); everything else is its tool name + a normalized
    word-set of its argument values minus shell boilerplate (flag/word jitter survives, per
    the codex-local lesson that exact fingerprints don't). Args that normalize to NOTHING
    (symbol-only/non-ASCII) fall back to an exact-bytes hash — an empty set must not match
    every other empty set of the same tool."""
    parsed = parse_args(args)
    if _is_write_tool(name):
        path = _path_of_args(args, patch_ok=name == "apply_patch") or ""
        body = str(parsed.get("content") or parsed.get("contents") or parsed.get("text")
                   or parsed.get("input") or parsed.get("patch") or args)
        return ("write", path, hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:16])
    if name in _NAV_TOOLS:
        loc = (parsed.get("url") or parsed.get("path") or parsed.get("dir") or parsed.get("directory") or "",
               parsed.get("cursor") or "", parsed.get("find") or parsed.get("query") or "",
               parsed.get("start_line") or parsed.get("offset") or "")
        return ("nav", name, tuple(str(x) for x in loc))
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
    if a[0] in ("write", "nav"):  # exact target+content / target+locator — a changed spot is progress
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


# The mid-session rollup's OUTPUT bound. summarize's default 8192 is a runaway backstop sized for
# fast models; on a 27B at ~7 tok/s it is an 18-MINUTE worst case, generated SYNCHRONOUSLY inside
# the coder's turn (observed: a 13+ minute compactor call while the harness's SSE idle timer fired).
# Median REAL rollup ≈ 500 tokens (295 measured; the p90 outliers were echo, now stripped) — 2048 is
# 4× headroom, and a genuinely over-long pass fails safe exactly as before (truncated → "" → no fold).
ROLLUP_MAX_TOKENS = 2048

CODER_FETCH_HEADER = "PAGES THE CODER ALREADY FETCHED"

# Dirs that are never deliverables (VCS, caches, cria's own state, vendored deps) are pruned from the
# inventory; everything else is listed IN FULL, newest-first — the operator ruled out truncation, so
# the completeness clause always holds and the judge can trust absence as absence.
_INVENTORY_EXCLUDE = frozenset({".git", ".cria", "__pycache__", ".pytest_cache", ".mypy_cache",
                                ".ruff_cache", "node_modules", "venv", ".venv", "site-packages",
                                ".tox", ".eggs"})


def workspace_inventory(root: str | None, flavor: str = "judge") -> str:
    """What ACTUALLY exists in the workspace right now — deterministic ground truth for the critic's
    evidence, gathered by cria from the filesystem (never from the model's claims). Closes the judge's
    blind spot on artifact steps: without it, a "write README.md" step was passed on FEASIBILITY with
    zero write actions in evidence and no README on disk, and a FileNotFoundError naming one file was
    read as "the directory does not exist" while the workspace held files. The listing is COMPLETE —
    never truncated (operator's call: a bounded list weakens the one clause that makes it decisive) —
    so "not listed = does not exist" always holds. Empty string when there is no workspace root to
    inspect (evidence composition drops the section, as with the fetch facts)."""
    if not root or not os.path.isdir(root):
        return ""
    labels = prompts.load_map("workspace_inventory")
    entries: list[tuple[float, str, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _INVENTORY_EXCLUDE)
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue  # vanished mid-walk (the coder is live) — a missing entry, never a crash
            entries.append((st.st_mtime, os.path.relpath(path, root), st.st_size))
    if not entries:
        return prompts.fill(labels["empty"], root=root)
    entries.sort(key=lambda e: (-e[0], e[1]))
    if flavor == "coder":
        # The post-compaction files list for the CODER (operator's design: content lives on disk +
        # in read_file range; the compacted view carries the LIST, not the bytes).
        lines = [labels["coder_header"]]
        lines += [f"  {rel} ({size} B)" for _, rel, size in entries]
        lines.append(labels["coder_note"])
        return "\n".join(lines)
    lines = [prompts.fill(labels["header"], root=root)]
    lines += [f"  {rel} ({size} B)" for _, rel, size in entries]
    lines.append(labels["complete"])
    return "\n".join(lines)


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + "…"


def known_routes(messages: list, sess=None) -> str:
    """Every endpoint route cria EXTRACTED from a real 2xx document this session, as one string.

    Read from the ledger DATA, never scraped from a rendered prompt. The scraped version partitioned
    the critic's prompt at a header and took everything after it, sweeping in the GROUND-TRUTH CHECKS
    block and the CODER'S SUMMARY — grounding a route against the coder's own text is precisely the
    self-grounding this check exists to defeat.

    EMPTY when nothing spec-shaped has been fetched, and an empty route list is cria knowing NOTHING
    — not evidence that a route is invented. The caller must abstain, never delete, on empty."""
    merged = _merge_fetches(_extract_fetches(messages), (getattr(sess, "fetched_pages", None) or {}))
    return " ".join(r for r in (_fetch_facts(e)[1] for e in merged.values()) if r)


def _verdict_nudge(obj: dict, done: bool, routes: str = "") -> str:
    """The coder-facing nudge from a critic verdict dict: the ``reason``, plus the ``proposed_fix`` (a
    concrete next action the critic named) when the step is NOT done — so the coder is handed a move,
    not just a diagnosis. ``proposed_fix`` is meaningless on a pass (nothing to fix), so it is dropped
    when ``done``. Either field may be absent/empty; the fix is appended on its own line when present."""
    reason = str(obj.get("reason", "")).strip()
    fix = str(obj.get("proposed_fix", "")).strip()
    if done or not fix:
        return reason
    # A proposed fix is authored text the coder ACTS ON, so it is held to the same bar as a steer
    # (c17ffd8): cria does not hand over a concrete external detail the evidence never showed. A
    # `METHOD /path` route is unambiguous — nothing writes "POST /x" about a file it is creating —
    # and a judge learns that spelling from cria's OWN shape ledger. Measured (run 0727-153326): the
    # critic proposed `POST /handles/resolve`, a route in no spec, 12 times; the coder grepped for
    # that literal string across 322 calls on one step. The REASON always survives — the step really
    # was not done; only the invented move is dropped.
    if routes and urlgrounding.ungrounded_routes(fix, routes):
        return reason
    return f"{reason}\nProposed fix: {fix}" if reason else f"Proposed fix: {fix}"


def _dump_verify(run_dir, key: str, idx: int, total: int, step: str, system: str, user: str,
                 done: bool, reason: str, response: str = "") -> None:
    """Write the EXACT context the critic saw (its system + user message), its RAW response, and the
    parsed verdict into THE RUN FOLDER (same folder as the call captures + plan mirror). This is the
    WHOLE basis on which a step was judged — so a human can see precisely what the model had to work
    with, what it actually emitted (the raw response exposes a parrot / empty / rambling non-verdict
    that the parsed reason alone hides), and what it was missing. Best-effort; never breaks the loop."""
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
            f"## VERIFIER RESPONSE (the reasoner's raw output)\n\n```\n{response or '(empty / call failed)'}\n```\n\n"
            "Below is the COMPLETE context the reasoner saw when it decided this step — it judged "
            "on nothing else beyond any inspection-tool reads it made mid-judgement (those are in "
            "the capture's critic .json files; the WORKSPACE FILES section below is the on-disk "
            "listing it was handed).\n\n"
            f"## SYSTEM message (cria/prompts/verify.txt)\n\n```\n{system}\n```\n\n"
            f"## USER message (the step + the ground truth it was handed)\n\n```\n{user}\n```\n"
        )
        # NO plan TOTAL in the name. The living plan resizes the tail under a running step, so a
        # total in the filename makes the dumps stop sorting in the order the verdicts happened —
        # observed (run 0727-174120) step 1's four dumps sorting 06,06,06,09 with the EARLIEST verdict
        # (of-09, 17:42) last and the DONE one above it, so the bottom file read as step 1's final
        # word says NOT DONE while the step actually passed six minutes later. The total is in the
        # file's own header, where it cannot reorder anything.
        (d / f"verify-step-{idx:02d}-{stamp}.md").write_text(md, encoding="utf-8")
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
