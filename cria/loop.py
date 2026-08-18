"""Phase 6 — the plan-driven loop. cria becomes an orchestrator: it drafts a plan,
hands the coder ONE item at a time (framed as if it were the whole task), lets the
harness run the coder's tools, and when the coder says "done" checks with the
reasoner before marking the item complete and moving on.

Owns no executors for anything the MODEL does: every model-facing tool is lowered to the
harness's shell. cria does run things on its own side — the repo's tests, the syntax floor,
the linters, the exec-check, read-only gathers — and it deletes the litter its own probes
leave, with the workspace as cwd. The older wording here was "cria never touches the
workspace", which stopped being true and is the cautionary example principle 23 records: a
boundary that has stopped being true is worse than a wide one, because audits measure against
it. The plan file is created and
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

import difflib
import hashlib
import json
import os
import fnmatch
import re
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

from . import bodykeys
from . import callcapture, dedup, denial, editrecovery, execcheck, focustrim, groundtruth, indicators, massage, probegate, proberun, prompts, selfcompact, toolmenu, urlgrounding, verifytools, webfetch
from .classify import _task_key, latest_user_text
from . import jsontext, planner
from .jsontext import extract_json_object, strip_think
from . import research
from .plan import Plan, PlanItem
from .groundtruth import workspace_inventory
from .planner import (_extract_cwd, missing_deliverables, reasoned_noise_indices,
                      surviving_noise_drops)
from .searchloop import first_domain_in, normalize_search
from .shelltool import (_CMD_FIELDS, find_shell_tool, is_shell_tool_name, shell_args,
                        with_time_budget)
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
# How many DISTINCT gate finding-states to remember per step. `last_gate_flag` answers "same as last
# time" and an ALTERNATION defeats it by construction — the findings genuinely change every turn.
# Base-rated 2026-08-01 across 61 captured runs: 19 (31%) return to a finding-set they had left.
# Long enough to see an A-B-A cycle and its variants, short enough that a converging run forgets its
# early noise.
GATE_SIGNATURE_WINDOW = 8

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
    # WHEN THE REFUSAL TRIGGER LAST FIRED. Its evidence lives in the message history, which a
    # fire cannot flush the way the signature trigger flushes `recent_actions` — so without
    # this it re-fires on every call until the refusals age out. Replayed on cycle 4 cell 13:
    # 14 redirects over 48 calls instead of one. One intervention consumes the evidence.
    blocked_fired_seq: int = -10_000
    repeat_action: str = ""  # human-readable description of the repeated action (for the reasoner)
    redirect_due: bool = False  # repetition tripped → gate + redirect before next coder turn
    redirect_probe: bool = False  # the in-flight gate feeds a reasoner-authored redirect (loop only)
    nudge_reason: str = ""  # a steer to hand the coder on its next work turn
    # The last gap the PERIODIC completion check named to the coder. Its only job is to stop the
    # same verdict being re-delivered: that check fires on a drive counter, so an unchanged workspace
    # produces an unchanged verdict, and one cycle-2 cell produced twelve consecutive identical ones.
    last_gap_named: str = ""
    nudge_reply: str = ""  # the coder's own no-tool-call reply the pending nudge is ABOUT — re-framed
    # views rebuild history from the harness body, which never saw an internal prose turn, so without
    # this the unexecuted-write nudge says "your last message contained the file's contents" about a
    # message that is not there (nemotron-nano 1786243834 call 0073: told to resend content the frame
    # had dropped, the model re-read the spec a 7th time instead)
    exec_finding: str = ""  # cria RAN the deliverable and it failed — ground truth, owed to the coder
    steer_source: str = ""  # human label of which guard produced the pending steer (for the ⟦cria⟧ note)
    coder_turns: int = 0  # acting coder turns since the last gate — drives the PERIODIC check-in
    research_checked_turn: int = -1  # the coder_turns tick the reading check last ran on (once per tick)
    # The set of sources the reading check last judged. It re-judges the moment new reading lands
    # instead of waiting out a ten-turn clock, and never judges the same evidence twice — a cadence
    # was gating a fact, and a step satisfied at turn 4 stayed pinned until turn 10.
    research_evidence: tuple = ()
    step_checked_turn: int = -1     # the coder_turns tick the periodic STEP check last ran on
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
    # (reason, exec_marker) for a satisfaction-accepted 'done', held until the gate's result decides
    # which claim the note may open with. Empty when the held text is the coder's own words.
    pending_done_parts: tuple = ()
    # The plan-ON completion backstop's OWN probe id. Deliberately NOT ``done_probe``: the plan-ON
    # periodic satisfaction check also sets done_probe and nothing on the plan path consumes it, so
    # keying the backstop off done_probe read whatever stale result probe_call_id pointed at by the
    # time the plan emptied (audited 2026-08-04). The backstop reads ONLY the probe it issued.
    completion_probe_id: str = ""
    completion_gate_reds: int = 0  # RED results at the completion backstop (ledger visibility; no cap)
    # A completion-gate probe's RESULT has been read since the coder's last forwarded acting turn —
    # green, or couldn't-run (the per-step fail-open posture, unchanged); RED clears it. The plan-ON
    # completion requires this: walked on ada-handles_ternary-bonsai_codex_poff_1785818931, a replan
    # returned [] with the coder mid-step-1, three LLM judges approved files that were never executed,
    # and the session exited 3/4 with ZERO gates run — pytest would have printed "5 failed". A session
    # must not end on judgment alone while cria never even ATTEMPTED the repo's checks.
    gate_fresh: bool = False
    leg0_nudged: bool = False  # the no-tools act-first nudge fired once this session
    # NB: there is deliberately NO search-escape state here. cria used to SUBSTITUTE a web_fetch for a
    # search-looping coder's own web_search (streak/volume counters, a convention URL, a domain-root
    # floor when the reasoner punted). Substituting the coder's action is the REDIRECTION class, and the
    # punt-floor was a deterministic fallback behind a reasoner call — both are what the doctrine forbids
    # (principles #1, #2, #4). The search gate still REFUSES a near-duplicate search and steers "read the
    # source you named" — a steer the coder can disregard, not an action taken for it.
    fetched_pages: dict = None  # url -> (status, routes): DURABLE fetch facts a steer cites after the
    # real result has been floored out of the window (else a steer can't counter a late spiral)
    same_checks_relooked: bool = False  # the ONE second look at unchanged findings has been spent
    #                                     (rearms whenever the findings move; see author_steer)


@dataclass
class PlanSession(GuardState):
    plan: Plan = field(kw_only=True)  # required; kw_only so it may follow GuardState's defaulted fields
    # Single-item plan-off mode: the whole task is ONE implicit step. When set, the driver uses
    # raw-task framing (no "step k/n") and runs the off-ramp a finite multi-step plan doesn't need
    # (the task-level satisfaction/done-critic). The explicit flag — NOT len(items)==1 —
    # is the key: a genuine planner 1-step plan must keep step framing and skip those off-ramps.
    synthetic: bool = False
    # PLAN-OFF sessions, whatever their item count. The operator's contract (2026-08-04): plan-off
    # gets a READING STEP and nothing else of the plan machinery — the task itself is never caged
    # behind "Do ONLY this step (k of n)" framing, and the living re-derivation never splits the
    # user's own task into steps (it re-derives PLANNER guesses; the raw task is not a guess).
    # Audited: gemma4, temperature 0, ladder 4/4 → campaign 0/4 twice, both runs pinned on step 1
    # for ~86-89 coder calls with the README structurally unreachable behind hidden steps the
    # replans kept regrowing. When the reading step clears, drive() flips the session to
    # ``synthetic`` and the raw-task single-item drive takes over exactly as before the rewiring.
    plan_off: bool = False
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
    unexecuted_nudges: int = 0  # bounded pushes for a turn that PASTED the file instead of writing it
    thrash_replanned: bool = False  # the tool-call-thrash re-derive fired once this STEP (anti-churn bound)
    verify_replanned: bool = False  # the verify-fail re-derive fired once this STEP (anti-churn bound)
    leg0_nudged: bool = False  # the no-tools nudge fired once this step (bounds in-process recursion)
    last_gate_flag: str = ""  # previous gate's block-nudge, for convergence/stall detection
    # Did the last completion gate actually RUN? `guard_gate_verdict` returns None for BOTH a green
    # gate and a gate that could not run, so its callers could not tell them apart and two of the
    # three hardcoded "The repo's automated checks pass". Measured: that wording shipped 80 times,
    # twice in a prompt whose newest check block showed failing tests, while the honest `never_ran`
    # wording the prompt file already carries fired zero times.
    last_gate_ran: bool = False
    # The last exec-intent question and its answer, keyed on what the question was BUILT from. The
    # question is "how does this project run itself"; it moves only when the task or the workspace
    # moves, and re-asking an unchanged one is the repeat #9's bound forbids.
    exec_intent_key: str = ""
    exec_intent_reply: str = ""
    # The highest PASSING test count any green gate has reported this session. Regression-only (#2):
    # it exists so cria can state, as a fact from the runner's own tally (#12), that the suite used
    # to pass more tests than it does now. See `passing_test_regression`.
    tests_passed_high: int = 0
    # Every DISTINCT gate finding-set this step has produced, oldest first. `last_gate_flag` answers
    # "same as last time" and an ALTERNATION defeats it by construction — the findings genuinely
    # change every turn. Base-rated 2026-08-01 across 61 captured runs: 19 of them (31%) return to a
    # finding-set they had already left. Bounded; only the signatures are kept, never the text.
    gate_signatures: list = field(default_factory=list)
    oscillation_note: str = ""   # set when the gate returns to a finding-set it had left
    # The last check output as TEXT, for the steer author. Some triggers carry no gate outcome,
    # so its author saw the header "GROUND TRUTH FROM THE REPO'S CHECKS:" with NOTHING under it — in
    # 6 of 6 gemma runs, on the MAJORITY of steers (57/57, 88/109, 87/117, 69/74, 79/109, 31/47).
    # Authoring blind, it invented endpoints, fields, paths and flags, and the coder obeyed. cria HELD
    # this text the whole time.

    # The check text the LAST authored steer was written against. A detector firing again over check
    # output that has not moved means the previous steer did not land — and re-describing the same
    # findings in fresh prose is the failure mode measured across 24 runs: ~554 steers, 61% authored
    # on top of already-located findings, 36% of ALL steers re-diagnosing findings unchanged since the
    # previous one. g22 is the shape of it: ten consecutive steers on ONE pytest assertion diff, each
    # contradicting the last ("an extra zero" -> "asserting ..01 but mocking ..02" -> "assertions
    # swapped" -> "addresses cut off mid-string") while the diff itself sat in the coder's context
    # naming the exact character.
    steered_checks_text: str = ""
    gate_git: str = ""  # last gate's git-status hash (workspace-change signal across gates)
    pending_coder_text: str = ""  # the coder's "done" claim, held for the critic after the probe

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
    (it is a neutral non-signal — neither red nor green).

    IT ALSO PERSISTS THE FINDING-SET, and this is the one place that can. `last_gate_flag` is read by
    five seats — `_gate_notes`, `_briefing_gate_ground_truth`, `author_steer`, `judge_satisfaction`'s
    `gate_findings=` at three call sites, and the server's checks note — and its only writer used to
    be `_verify_after_probe`, the plan-ON per-step gate. `Loop.drive` returns into
    `_drive_single_item` at the `sess.synthetic` dispatch BEFORE that writer is reached, so on a
    plan-off session it was never written: 348 of 410 suite rows and all 129 captured sessions are
    plan-off, which means the anti-laundering briefing override, the judge's red evidence and the
    steer author's finding-set were all silent while cria was holding the findings.

    It used to write `last_checks_text` here instead — a second carrier with ZERO readers, whose own
    docstring claimed it fed the steer author. One field, written at the one funnel every gate path
    reaches (#23: one owner)."""
    gs.last_gate_flag = finding or ""
    if not finding:
        gs.gate_stall = 0
        gs.gate_sig = ""
        return
    if finding == gs.gate_sig:
        gs.gate_stall += 1
    else:
        gs.gate_stall = 1
        gs.gate_sig = finding



def _satisfaction_verdict(system: str, user: str, reasoner_chat, reasoner_role, rlog, *, reasoning_off: bool, workspace_root: str = "", capped: list | None = None) -> dict | None:
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
        # the retry is TOOLLESS, but the system prompt opens "You have exactly two READ-ONLY
        # inspection tools" — tell this pass the truth (the steer_diagnose stale-line lesson).
        system = system + "\n\n" + prompts.load("judge_toolless_note")
    try:
        # The careful pass may INSPECT (the shared judge loop; operator directive) — the completion
        # critic authors corrective steps the coder must obey, and blind it theorized a wrong
        # endpoint from a field-name collision. The reasoning-off retry stays toolless.
        comp = _judge_completion(
            reasoner_chat, role, system, user, rlog,
            phase="satisfaction" + ("-noreason" if reasoning_off else ""),
            workspace_root="" if reasoning_off else workspace_root,
            # The careful pass may answer through the verdict tool — same channel it inspects on.
            # The toolless retry has no channel to answer on but text, and declares no key.
            verdict_key="" if reasoning_off else "satisfied",
            capped=capped,
            force_think_off=reasoning_off)
        if massage.is_truncated(comp):
            # Cut at the cap → not a verdict. Parsing it risks a partial object that happened to
            # close, and the caller's retry/fail-closed path is the honest answer.
            rlog.emit("loop.satisfaction_truncated", level="warn")
            return None
        vtext = _completion_text(comp)
        if reasoner_role is not None:
            vtext = reasoner_role.clean_content(vtext)  # drop leaked reasoning when off
        obj = extract_json_object(vtext)
        if obj is not None:
            return obj
        ph = "satisfaction" + ("-noreason" if reasoning_off else "")
        bogus = leaked_judge_tool(vtext)
        if bogus:
            # Not "unparseable" — the judge called a tool it does not have. Recorded by name so the
            # record says what actually happened.
            rlog.emit("loop.judge_phantom_tool", level="warn", phase=ph, tool=bogus)
        # The answer was not a verdict — but the judge's own THINKING, or its PROSE answer, may carry
        # one. Recovers a NOT-satisfied ruling only: of 46 unparseable replies on this box, 20 held a
        # clear judgment in the reasoning and 4 more stated one in plain prose ("The claim is
        # inconsistent... Fix: add src/__init__.py"), all of it discarded.
        #
        # The judge's OWN object comes first when one absent brace is all that is wrong with it
        # (verdict_from_unclosed) — same one-way NOT-satisfied contract, but it carries the reason
        # and proposed_fix the judge actually wrote. 3 of this phase's replies on this box.
        recover = ((lambda sysm: ask_closed(reasoner_chat, reasoner_role, sysm, rlog,
                                            phase=ph + "-recover"))
                   if reasoner_role is not None else None)
        return (verdict_from_unclosed(vtext, "satisfied", rlog, ph)
                or verdict_from_reasoning(_reasoning_of(comp), "satisfied", rlog, ph, recover)
                or verdict_from_reasoning(vtext, "satisfied", rlog, ph + "-prose", recover))
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


def _tool_names(coder_tools: str) -> list[str]:
    """The bare tool names out of the coder-tools summary cria renders for a reasoner.

    ANCHORED ON THE FORMAT, not on what follows the name. This used to key on a name followed by
    `(`, `:`, a dash or end-of-line — which worked while the block rendered `write_file(path,
    content)` and broke the moment that callable syntax was defanged to prose: `exec_command` was
    lost entirely and `command` was harvested out of "runs ANY shell command". Every line
    _coder_tools_summary writes is `  - <name>`, so that is what this reads."""
    lines = re.findall(r"(?m)^\s*-\s*([a-z_][a-z0-9_]{2,})\b", coder_tools or "")
    if lines:
        return lines
    return re.findall(r"\b([a-z_][a-z0-9_]{2,})\b(?=\s*[(:\u2014-]|\s*$)", coder_tools or "", re.M) \
        or re.findall(r"\b([a-z_][a-z0-9_]{2,})\b", coder_tools or "")


def reassess_remaining(reasoner_chat, reasoner_role, task: str, completed: str, remaining: str,
                       evidence: str, rlog, coder_tools: str = "",
                       trigger: str = REPLAN_TRIGGER_ADVANCE, facts: str = "") -> list[str] | None:
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
    # ONE READER for "a step list written as JSON" — planner.json_steps, the same function the
    # initial draft reads through. This call used to require a dict with a literal `steps` key, and
    # cria already owned every other shape the reasoner uses: a bare top-level array, a synonym key,
    # a dict item per step. RE-MEASURED at review 2026-08-03 over 233 captured re-derivations, by
    # replaying the OLD test (`isinstance(obj, dict) and isinstance(obj["steps"], list)`) against
    # this new one: 11 replies main could not read and this reader can — 5 carrying real steps (run
    # 20260727T234416 call 0024 returned a complete four-step re-derivation, its own thinking saying
    # "I need to produce JSON steps only") and 6 the empty `[]`. The plan was left unchanged on all 11.
    # (The commit that landed this said "13 … 7 with steps"; the empty half reproduces exactly and
    # the steps half does not. The inflation came from a replay gate that tested `obj["steps"]` for
    # TRUTHINESS rather than for being a list, which counts `{"steps": []}` — a shape main already
    # handled — as a miss. Corrected here rather than left to the next walk: rule 23b.)
    #
    # JSON ONLY — deliberately NOT parse_steps, whose prose fallbacks read numbered and bulleted
    # LINES. The re-derivation's replies are not drafts: run 20260728T101412 call 0121 answered with
    # a README in markdown, and parse_steps reads four of its bullets as plan steps. Reading a
    # README as the remaining plan is a worse outcome than reading nothing (principle 2 — the
    # dangerous class of intervention is the one that REPLACES a correct prior).
    cleaned = planner.json_steps(strip_think(text))
    if cleaned is None:
        return None  # unparseable / wrong shape → keep the plan exactly as it was
    if not cleaned:
        # The reasoner says nothing remains. replan.txt asks for exactly this ("Return [] ONLY when
        # the evidence shows every remaining deliverable is already done") and this function's own
        # contract defines it, so it is honoured whether it arrived as `{"steps": []}` or bare `[]`.
        # NOT a false-finish path: the caller does not drop the tail on this alone — it re-asks
        # judge_satisfaction against the same evidence first, and a not-satisfied answer keeps every
        # remaining step (loop.replan_empty_declined).
        return []
    # Same reasoner NOISE judgment the INITIAL plan gets (reasoned_noise_indices): drop a re-derived step
    # that codified a bare command, dictated literal code, or a speculative guess — a re-derivation
    # grounded in the coder's FAILED work otherwise codifies its guessed endpoint into an authoritative
    # step (observed: a research step re-derived into "call requests.get('<root>')", shipped as a 404/403).
    # replan.txt already tells the reasoner to avoid these; this is the focused safety judgment. An
    # all-noise re-derivation → None (keep the prior plan), never an empty plan.
    _ask = lambda sysp, usr: summarize(reasoner_chat, reasoner_role, sysp, usr, rlog, phase="reasoner")
    drop = reasoned_noise_indices(_ask, task, cleaned, facts=facts)
    # PER-STEP, FAIL-CLOSED: a deletion that would lose a deliverable is refused on its own, and the
    # rest of the verdict still applies (planner.surviving_noise_drops). The broad coverage check
    # below is NOT this check — it ran in the walked run and passed a tail whose README step had just
    # been deleted, because "does this plan cover everything?" over five steps skims where "does
    # deleting THIS step lose something?" does not.
    if drop:
        drop, refused = surviving_noise_drops(_ask, task, cleaned, drop)
        for i, lost in refused.items():
            rlog.emit("loop.replan_noise_refused", level="warn", lost=lost, step=cleaned[i][:160])
    kept = [s for i, s in enumerate(cleaned) if i not in drop]
    # SAY WHAT THE JUDGE DID. The initial plan reports this (plan.noise_dropped / plan.noise_all_kept);
    # the re-derivation ran the same judge and reported nothing, so a tail that came back carrying a
    # bare shell command was indistinguishable from one the judge had cleaned. Measured (run
    # 0727-164951): a good six-step plan — step 2 "Create a Python function resolve_handle(handle)" —
    # was re-derived twice (5→8, then 7→3) into a plan whose step 2 was `grep -n 'resolved_addresses'
    # <file>` and step 3 "Run unit tests": a bare command and plumbing, the two categories this judge
    # deletes. Nothing in the log said whether it ran, kept them, or dropped something else.
    # LOG WHAT WENT, not just how many. Measured across every log day: this fired 156 times, dropped
    # at least one step 75 times, and left ZERO steps 37 times — and none of those events record
    # WHICH steps were deleted, so "did the noise judge delete a deliverable?" cannot be answered
    # from the logs at all. It happened twice in this ladder (runs 1785625253 and 1785659842, the
    # second ending the session at 1/4 with "unit tests" and "live test" deleted from the plan), and
    # both times the finding needed the raw captures to reconstruct. A count is not a reading.
    rlog.emit("loop.replan_noise", dropped=len(drop), kept=len(kept),
              dropped_steps=" | ".join(cleaned[i][:160] for i in sorted(drop)),
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
    # A re-derived step must not name a CODER TOOL as code the deliverable calls or mocks. cria's
    # harness is not a library the product may import. See urlgrounding.harness_tool_leaks: the
    # initial plan said "mock the API call" and the re-derivation rewrote it to "mock web_fetch",
    # after which the coder shipped `resp_text = web_fetch(url=url)` — an undefined name — and the
    # run scored 0/4. REFUSE the tail; the step that was already correct stands. cria never rewrites
    # a plan step.
    leaked = urlgrounding.harness_tool_leaks("\n".join(kept), _tool_names(coder_tools))
    if leaked:
        rlog.emit("loop.replan_tool_leak", level="warn", tools=",".join(leaked))
        return None
    # NO research-first re-prepend here — and none at plan time either. cria does not AUTHOR plan steps:
    # injecting "web_fetch the named source" was cria planning, and pinning it made a possibly-wrong step
    # an inescapable mandate. The general mechanisms carry it instead — plan.txt tells the drafter to
    # research first, the critic clears a research step on facts obtained, and the durable ⟦ctx:facts⟧
    # ledger keeps the real endpoints in front of the coder across compaction.
    #
    # NO "this step claims an endpoint returns a field it does not" gate here either. MEASURED
    # 2026-08-03 over all 86 recorded runs: 3,779 coder prompts carried a step, 71 of them named a
    # route whose response FIELDS the ledger already held, and a token matcher over those flagged
    # 15 — which are TWO distinct steps repeated, and BOTH state the truth outright ("`total_handles`
    # is **not** in that response – it appears in `/holders/{address}`" and "…then GET
    # /holders/{holder} to get total_handles"). Two of two false positives, zero true positives.
    # The step that IS false — run 20260803T112245's "sends a GET request to
    # https://api.handle.me/handles/{handle} … extracts … total handles held by the holder", carried
    # into 20 coder prompts — names no field token at all, so no matcher over the sentence can see
    # it. That is principle 9's table again: the difference is not in the sentence.
    #
    # And the facts were never the missing part. That run made SIX re-derivation calls and every one
    # was handed the per-endpoint field list showing `/handles/{handle}` returns no `total_handles`;
    # 105 of its 107 coder prompts carried the same list under "use these EXACT names and nesting; do
    # not guess". The evidence, the instruction (line 5 of replan.txt) and the ability to rewrite the
    # tail were all already here. A second surface saying it again is noise on a delivered fact
    # (principle 3), and a deterministic trigger for it cannot be built from what the corpus holds
    # (principle 15).
    return kept


def _judge_completion(chat_fn, role, system: str, user: str, rlog, *, phase: str,
                      workspace_root: str = "", max_tokens: int = 8192,
                      force_think_off: bool = False, transcript: list | None = None,
                      answer_now: str | None = None, answer_now_simple: str | None = None,
                      verdict_key: str = "", capped: list | None = None) -> dict:
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
    forced_rounds = 0
    while True:
        body: dict = {"stream": False, "temperature": 0, "max_tokens": max_tokens,
                      "messages": list(messages)}
        sent_chars = sum(len(str(m.get("content") or "")) for m in messages)
        room_left = sent_chars < verifytools.VERIFY_MAX_CHARS
        if inspectable and rounds < verifytools.VERIFY_MAX_ROUNDS and room_left and not forced_rounds:
            # …AND A WAY TO ANSWER IN THE SAME CHANNEL. Offered tools on one channel and made to
            # answer on another, judges answered where they had been speaking: `<function=satisfied>`,
            # `<function=exec_command>`. cria discarded those and "unverified — keep working" reached
            # a finished workspace (qwen35/ruby 0138 and 9 more). Opt-in by key: the steer author
            # shares this loop and answers in prose.
            body["tools"] = verifytools.tools_for(verdict_key)   # withdrawn on the forced-answer round
        elif inspectable and not room_left and not forced_rounds:
            rlog.emit("loop.verify_inspect_capped", phase=phase, chars=sent_chars,
                      rounds=rounds, level="info")
            # …AND THE CALLER IS TOLD. A judge that ran out of looking has not finished looking, and
            # what it says next is a guess wearing a verdict's clothes. Cycle 4 cell 10: the
            # inspection capped five times and the judge told the coder "Importer.java is the
            # original unmodified code (WORKERS_ENABLED=false, no OpenCSV usage, no malformed input
            # handling)" — four minutes after the suite had measured all five checks passing by
            # running them. cria handed that to the coder as the named gap, six times over 62
            # minutes, and the coder edited a working 5/5 solution down to 4/5. #11b: a mechanism
            # that could not observe the thing it was asked about must not answer as if it had.
            if capped is not None:
                capped.append(rounds)
        if role is not None:
            role.apply(body, internal=True, rlog=rlog)
        elif force_think_off:  # no role configured, but still force the think block off
            body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        rlog.phase = phase
        # massage the reply exactly like every other reasoner path: a flaky-dialect model leaks its
        # tool call as TEXT ('read_file({"path":...})' in content), which this loop then never
        # executed — measured live in the steer-author matrix (qwythos trial 1, mellum2 trial 3:
        # both wanted to inspect, both leaks dropped on the floor). Recovery promotes the leak to a
        # real tool_calls entry so the inspection actually happens.
        comp = massage.apply(_parse_completion(chat_fn(body, rlog)), body.get("tools"), rlog)
        msg = ((comp.get("choices") or [{}])[0].get("message")) or {}
        calls = msg.get("tool_calls") or []
        if not (inspectable and calls and rounds < verifytools.VERIFY_MAX_ROUNDS and room_left):
            # A final reply that is a CORRUPTED tool call (leaked dialect the recovery could not
            # parse — g2-0104: four clean read rounds, then `<|tool_call>call:read_file{...<|"|>`)
            # meant the model asked a question nobody answered and the whole loop died silently.
            # ONE forced-answer round (tools withdrawn) instead of returning garbage; bounded once.
            content = str(msg.get("content") or "")
            # The judge/author ASKED for something and no answer is possible: either the reply is
            # an unexecutable tool call (tools withdrawn, or the round cap reached — g2-0104's
            # `<|tool_call>call:read_file{…<|"|>` recovered into a call nobody could run) or it is
            # raw leak debris. Returning it means the whole inspection dies as silence. ONE forced
            # textual round, tools withdrawn, bounded once.
            # ESCALATION, not a fallback: round 1 asks for the verdict in its normal shape; round 2
            # asks the SAME question in the simplest shape the caller can accept. Measured across the
            # fleet on real captured rounds — nine of ten models answer the normal (JSON) shape 4/4,
            # so they never reach round 2 and nothing changes for them. gemma4 answers it 0/10,
            # because a JSON object is the shape of the tool-call template it has just used five
            # times, so it emits another one; asked for a bare word it answers 10/10. zaya1 is the
            # mirror — JSON 4/4, word 1/4 — which is exactly why the simple shape is a SECOND
            # attempt keyed on an unreadable reply, never the standing ask. Nothing here keys on
            # which model is loaded.
            if forced_rounds < (2 if answer_now_simple else 1) and (calls or massage.has_tool_call_leak(content)):
                forced_rounds += 1
                # turn_text, not `content`: a thinking model that called a tool leaves `content`
                # empty and its analysis in the reasoning channel, and writing that turn back as
                # {"content": None} erases the judge's own work from its own transcript.
                messages.append({"role": "assistant",
                                 "content": massage.turn_text(msg) or None,
                                 **({"tool_calls": calls} if calls else {})})
                if calls:   # a dangling tool_call needs its result turn or the next request is malformed
                    for tc in calls:
                        messages.append({"role": "tool", "tool_call_id": tc.get("id") or "vt",
                                         "content": "[not executed — no further inspection rounds]"})
                ask_text = (answer_now_simple if forced_rounds == 2
                            else (answer_now or verifytools.ANSWER_NOW))
                if forced_rounds == 2:
                    rlog.emit("loop.verdict_simplified", phase=phase)
                messages.append({"role": "user", "content": ask_text})
                continue
            if transcript is not None:  # the caller wants the inspection record (e.g. for grounding)
                transcript.extend(messages[2:])
            return comp
        # THE ANSWER ARRIVED AS A CALL. Read it off the structured tool_call (#12) and stop: this is
        # the judge declaring its verdict, not asking to look at something. Any inspection call made
        # in the same turn is ignored on purpose — the tool's own description forbids mixing them,
        # and a judge that has decided has nothing left to look up.
        said = next((tc for tc in calls
                     if (tc.get("function") or {}).get("name") == "verdict"), None)
        if verdict_key and said is not None:
            try:
                obj = json.loads((said.get("function") or {}).get("arguments") or "{}")
            except ValueError:
                obj = None
            if isinstance(obj, dict) and verdict_key in obj:
                rlog.emit("loop.verdict_by_tool", phase=phase, round=rounds)
                if transcript is not None:
                    transcript.extend(messages[2:])
                return _completion_of(comp, json.dumps(obj))
        rounds += 1
        # Same reason as the write-back above: preserve what the judge produced this round, from
        # whichever channel it produced it in, or the next round asks it to answer against a
        # transcript where it appears to have been silent.
        messages.append({"role": "assistant", "content": massage.turn_text(msg) or None,
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
        if rounds == verifytools.VERIFY_MAX_ROUNDS or \
                sum(len(str(m.get("content") or "")) for m in messages) >= verifytools.VERIFY_MAX_CHARS:
            # THE CLOSER MUST ASK FOR THE SCHEMA THIS JUDGE DECLARES. Three judges share this loop and
            # they answer under three different keys — `done`, `satisfied`, `consistent` — while the
            # default closer demands `{"done": …}`. The confirm judge passes answer_now_simple with
            # its own one-word ask, but only the leaked-tool-call branch above ever reached it; the
            # round cap, which is the path a five-round inspection actually takes, sent the wrong
            # template every time.
            #
            # Walked on maple-preview 1786228135. Four gate cycles, ~40 calls, roughly 20 of the run's
            # 35 minutes, and NOT ONE BYTE was written to the workspace after the first. Three cycles
            # answered `{"done": true}` — the shape cria asked for and the shape cria then failed to
            # recognise — and each time cria said "not yet verified" and started again. The fourth
            # ignored the closer, answered `{"consistent": true}`, and the run ended. Same workspace,
            # same verdict, four times; the only variable was which key came back.
            messages.append({"role": "user",
                             "content": answer_now_simple or answer_now or verifytools.ANSWER_NOW})


def _consistent_word(text: str) -> bool | None:
    """The confirm judge's one-word verdict, or None when it did not give one.

    Both shapes are read, always: the ask is now a WORD (a JSON demand after five rounds of the
    judge's own tool calls gets another tool call — measured 0/10 vs 10/10 on gemma4), but a model
    that answers with the JSON object anyway is still understood. ternary-bonsai answers every shape
    6/6, so no model can be made worse by the change — the only movement is a model that answered
    NOTHING now answering."""
    head = (text or "").strip().lstrip("*#`\"' ").upper()
    if head.startswith("INCONSISTENT"):
        return False
    if head.startswith("CONSISTENT"):
        return True
    return None


def step_names_absent_artifact(claim: str, workspace_root: str) -> str:
    """The file this step names, when the workspace is EMPTY — else "".

    Ground truth, not judgment (principle 8): there is nothing here for a reasoner to weigh. If the
    workspace holds no files at all, then every file the step names is absent — whether the step was
    to WRITE it, read it, or document it — so the step cannot be complete. The reasoned brake below
    is asked only about cases this cannot settle.

    MEASURED across every captured critic verdict (n=135 with an inventory, 92 approvals): 7 approvals
    named a file that was not on disk. Three of them are this exact shape — run 20260801T160104, calls
    0034/0038/0041, step "Write a CLI script `resolve_handle.py`", inventory "the workspace has no
    files at judging time". Call 0038's verdict refutes itself in its own reason and cria still
    advanced: {"done": true, "reason": "workspace has no files, so the claimed resolve_handle.py does
    not exist ... I default to DONE per instructions."} The reasoned brake caught it twice and then,
    on the third attempt, ruled `consistent: true` against the identical listing. cria moved to step 4
    — write unit tests importing a module that was never written — and the run's remaining 40 turns
    were spent on `ModuleNotFoundError: No module named 'resolve_handle'`.

    Deliberately narrow. The other 4 approvals had a NON-empty workspace, where a named file may be
    one the step merely mentions (a README step naming the module it documents), and blocking those
    would be a guess. An empty workspace admits no such reading."""
    if not workspace_root or not os.path.isdir(workspace_root):
        return ""
    try:
        if any(not e.name.startswith(".") for e in os.scandir(workspace_root)):
            return ""
    except OSError:
        return ""   # unreadable → say nothing; the reasoned brake still runs
    dom = (first_domain_in(claim or "") or "").lower()
    for m in _STEP_ARTIFACT.finditer(claim or ""):
        at = m.start()
        if "://" in claim[max(0, at - 60):at]:   # a URL's path is not a workspace artifact
            continue
        # A DOMAIN the step names is not a workspace file ("api.handle.me" matches the file-token
        # pattern — ".me" reads as an extension; first_domain_in is TLD-allowlisted and
        # file-extension-aware, so real filenames never qualify).
        if dom and m.group(1).lower() == dom:
            continue
        return m.group(1)
    return ""


def _claim_promises_artifacts(claim: str) -> bool:
    """Does this completion claim promise anything the workspace could hold?

    The confirm brake below inspects the DISK, and every one of its measured wins is a claim that
    promises an artifact — by a production verb ("write unit tests", m8) or by naming a file (the
    empty-workspace CLI step). A claim with neither — the model-authored READING step is the common
    case — leaves the checker nothing it can legitimately inspect: its own prompt says "a
    research/investigation step needs no files", and a weak checker ignores that and invents one.

    MEASURED over every captured confirm chain on the box (313 final verdicts on claims naming no
    artifact): 155 confirmed, 158 blocked — a coin flip, across 36 sessions. Walked on
    ada-handles_ornith_codex_poff_1785830161: the critic ruled the reading step done THREE times on
    real fetch-ledger evidence, and the confirm vetoed each one — "no resolver script exists" (the
    resolver is step 2's work), then "move or symlink the file from tmp/read-only/", then a
    wrong-schema reply that failed closed — ~30 judge calls, and the coder started writing with 7 of
    its 15 minutes left. 0/4.

    File tokens are _STEP_ARTIFACT with the URL exclusion, minus the one DOMAIN the claim names
    (first_domain_in is TLD-allowlisted and file-extension-aware, so "api.handle.me" is excluded
    exactly and "resolve_handle.py" never is). A named file is EXACT — no judgment involved. The
    first version also carried a production-VERB list; that was a pattern doing judgment's work
    (operator, 2026-08-04: "fuzzy deterministic code, against principle") and it was verb-blind —
    "Update the README", "Fix the retry loop", "Rewrite the resolver" all read as artifact-free.
    The verbless question now goes to the reasoner in :func:`_confirm_applies`."""
    dom = (first_domain_in(claim or "") or "").lower()
    for m in _STEP_ARTIFACT.finditer(claim or ""):
        at = m.start()
        if "://" in (claim or "")[max(0, at - 60):at]:
            continue
        if dom and m.group(1).lower() == dom:
            continue
        return True
    return False


def _confirm_applies(claim: str, red_findings: str = "", *, gate_red: bool = False, ask=None,
                     rlog=None, phase: str = "critic-confirm") -> bool:
    """Should the per-STEP confirm brake run on this approved claim at all?

    Grounds, any suffices: the repo's checks are red — per THIS call's findings OR the session's
    standing red state (the audit found the per-call arm alone left periodic-gate reds invisible
    here) — then the disk is contested and the brake's look is grounded whatever the step names;
    or the claim names a FILE (exact, deterministic); or, when it names none, ONE focused reasoner
    question rules whether the step promises anything on disk at all (deterministic code gathers,
    the reasoner judges — the verb list this replaces couldn't see "Update the README"). Every
    failure direction keeps the brake: no reasoner, or an unreadable answer → it runs.

    Scoped to the per-step confirm on purpose. The whole-TASK satisfaction confirm keeps its brake
    unconditionally: a task names its deliverables as NOUNS ("script plus README"), and the brake's
    measured wins there (satisfied with no README on disk) are exactly that shape."""
    if (red_findings or "").strip() or gate_red:
        return True
    if _claim_promises_artifacts(claim):
        return True
    if ask is None:
        return True   # no reasoner → the brake stays (the pre-skip behavior)
    ans = strip_think(ask(prompts.render("confirm_applies", step=claim)) or "")
    head = ans.upper().split()[0].strip(".,:;`*\"'") if ans.split() else ""
    if head == "NO":
        if rlog is not None:
            rlog.emit("loop.confirm_skipped_no_artifact", level="info", phase=phase)
        return False
    return True   # YES, or anything unreadable → the brake runs


# The veto shapes that assert ABSENCE — the one claim class cria can refute with a stat() of its
# own. A trigger, not a verdict: the file check below is the verdict.
_VETO_MISSING = re.compile(r"(?i)\b(?:does not exist|not founds?|missing|no such files?|absent|"
                           r"no files? (?:or artifact )?named|was not found"
                           # EMPTINESS is the same class as ABSENCE: a claim that the artifact is
                           # there but holds nothing. Walked on mellum2 1785996352 call 0060, where
                           # the confirm judge called list_dir, never read_file, and then asserted
                           # resolve_handle.py "is a 1.8 KB file with no imports, no function
                           # definitions, no API calls, and no evidence of any Ada Handles
                           # integration" — about a file with four imports, two defs and a urllib
                           # POST. None of the old alternatives matched, so the disk refuter never
                           # ran and cria forwarded the falsehood to the coder as its own steer. The
                           # coder read the file, saw cria was wrong, dismissed the steer and quit.
                           r"|no (?:imports|functions?|function definitions|code|content|evidence)"
                           r"|is empty|are empty|contains nothing|no actual)\b")
# Path tokens including ABSOLUTE ones — _STEP_ARTIFACT starts at \w and silently drops a leading
# slash, which would re-root an absolute path under the workspace and miss the file.
_VETO_PATH = re.compile(r"(/?[\w][\w./-]*\.[A-Za-z][A-Za-z0-9]{0,4})")


def _veto_refuted_by_disk(why: str, workspace_root: str, ask=None, rlog=None) -> tuple[str, str]:
    """``(refuted_path, disk_facts)`` for a NOT-consistent veto — ``("", "")`` when nothing applies.

    ``refuted_path`` is the file the veto wrongly claims is MISSING, or "" when the veto stands.
    ``disk_facts`` is what the filesystem actually says about every path the veto named, returned in
    BOTH directions: a veto the disk corroborates is a verified fact, not one reader's opinion.

    Walked on ada-handles_nemotron-elastic_codex_pon_1785834747 call 0054: the confirm checker
    ruled {"consistent": false, "why": "Missing swagger.json file at /tmp/…/tmp/read-only/
    api.handle.me_swagger.json"} — WITHOUT one inspection call — while that exact path existed
    (the coder `ls`'d it one call later). The false veto re-blocked a step the critic had verified,
    three times in one run; the coder received "Missing <file>" in cria's voice — the false fact
    rule 5b forbids. Measured: 31 of 152 captured confirm-false verdicts assert a missing file.

    DETERMINISTIC CODE GATHERS, THE REASONER JUDGES (principle 8; operator, 2026-08-04). The first
    version of this decided WHAT "missing" referred to with a regex and a substring rule — and
    overturned vetoes about content missing INSIDE an existing file, about absent functions, and
    about a genuinely-missing X.py "covered" by test_X.py (audited same day, one live misfire:
    a veto about an unverifiable API response overturned because the word "missing" appeared and
    some file existed). What "missing" refers to is judgment; no pattern separates the shapes.
    So: the missing-word regex is only the TRIGGER for spending one call, the disk facts are
    gathered exactly (stat per named path), and ONE focused reasoner question rules STANDS or
    REFUTED against those facts. Every failure direction keeps the veto: no reasoner, no named
    file that exists, an unreadable answer — all STANDS. Only a clear REFUTED overturns."""
    if not why or not workspace_root or ask is None or not _VETO_MISSING.search(why):
        return "", ""
    facts, first_existing = [], ""
    for m in _VETO_PATH.finditer(why):
        tok = m.group(1)
        try:
            path = tok if os.path.isabs(tok) else groundtruth.resolve(workspace_root, tok)
            exists = os.path.isfile(path)
        except (OSError, ValueError):
            exists = False
        # SIZE AND SHAPE, not just existence — an emptiness claim is settled by what the file HOLDS.
        detail = "NOT on disk"
        if exists:
            try:
                body = open(path, errors="replace").read(200_000)
            except OSError:
                body = ""
            n_lines = body.count("\n") + 1 if body else 0
            code = sum(1 for ln in body.splitlines()
                       if ln.strip() and not ln.lstrip().startswith("#"))
            detail = (f"EXISTS on disk — {len(body):,} bytes, {n_lines} lines, "
                      f"{code} non-comment code lines")
        facts.append(f"- {tok}: {detail}")
        if exists and not first_existing:
            first_existing = tok
    if not first_existing:
        # THE DISK AGREED, AND cria USED TO THROW THAT AWAY. Only the REFUTED direction had a return
        # path; when the filesystem corroborated the veto, these facts — freshly stat'ed, exact —
        # were computed and dropped, and the report reached the coder under done_incomplete's
        # "one reader's opinion of your work, not a verified fact". In cart-billing-go x gemma4 the
        # veto said `discounts.json` was missing, cria confirmed it was missing, discarded that, and
        # the coder declared done twice claiming it had created a file its own `list_dir` showed
        # absent. A verified fact must not be labelled an opinion (#5b), and telling the coder MORE
        # about the real state is the additive direction (#2).
        return "", "\n".join(facts)
    ans = strip_think(ask(prompts.render("confirm_veto_disk", why=why, facts="\n".join(facts))) or "")
    head = ans.upper().split()[0].strip(".,:;`*\"'") if ans.split() else ""
    return (first_existing if head == "REFUTED" else ""), "\n".join(facts)


def _restates_the_verdict(why: str, reason: str) -> bool:
    """True when a confirm verdict's stated `why` IS the done-reason it was handed, word for word.

    A verdict that says `consistent: false` and then gives, as its whole justification, the very
    sentence that argued the step was DONE has not contradicted anything — it has echoed the
    question. cria used to read the boolean and forward that sentence to the coder as the reason it
    is NOT done, so the coder read "the coder successfully fetched the specification and extracted
    all required endpoints" printed directly under "Do ONLY this step, then stop".

    MEASURED across all 124 captured sessions on the box (288 confirm invocations parsed with cria's
    own verdict reader, both phases): 125 answered false, and **40 of those 125 restate the done
    reason verbatim** — 14% of every confirm ever run. All 40 are fabliq, which is also the model
    that called an inspection tool 0 times in 87 confirm invocations; a judge that never looks has
    nothing in its context but the reason it was handed, and hands it straight back. One run
    (20260802T195958) contributed 36 of the 40 and never left step 1 in 255 calls; another
    (20260802T214153) held step 1 of 5 from call 0037 to 0209 on work its own evidence had finished.
    Verbatim example, both fields byte-identical: {"consistent": false, "why": "The coder
    successfully fetched the Ada Handles API specification from https://api.handle.me/openapi.json
    and extracted all required endpoints, request formats, and response structures."}

    An EQUALITY test, not a similarity ratio — the same shape `_dedupe_doubled` uses on a doubled
    steer, and for the same reason: "substantially a restatement" is a judgment, and a tuned ratio is
    the pattern principle 9's corollary says to replace with a question rather than tune. The
    normalisation is whitespace + case only. The remaining 85 falses were read: every one names a
    real absence or contradiction, so a *non*-verbatim affirming why has zero measured instances and
    no detector is built for it (principle 1 — the bar to ADD is high; principle 15 — base-rate it
    first)."""
    a = re.sub(r"\s+", " ", (why or "").strip()).casefold()
    b = re.sub(r"\s+", " ", (reason or "").strip()).casefold()
    return bool(a) and a == b


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
    inspect → confirmed (nothing to check against).

    An UNPARSEABLE check fails CLOSED — it does not confirm. It used to keep the verdict, on the
    reasoning that an additive brake must never become a new wedge; that is the fail-open on missing
    ground truth this whole file treats as the root of early exits, and the policy stated a hundred
    lines below ("a 'satisfied' that exists ONLY because the careful pass failed is downgraded and we
    fail CLOSED") already contradicted it. Measured, g20 (gemma4, ada-handles, 2/4, exited at 12 of
    its 30 minutes): the judge spent all six inspection rounds calling tools and never answered, cria
    logged `confirm_unparsed`, confirmed anyway, and ended the run over a workspace holding no test
    file at all — while that same judge's own reasoning had found the real defects ("the test suite
    never asserts total_handles", "a circular mock of the function under test"). Not confirming costs
    work turns cria had already paid for; confirming on nothing ends the run.

    A verdict that RESTATES its own claim (see :func:`_restates_the_verdict`) is treated as UNUSABLE,
    exactly like an unparseable one: re-asked once, then failed CLOSED. It is deliberately NOT
    flipped to `consistent: true`. Flipping it would make the step ADVANCE on a judge that gave no
    evidence — the fail-OPEN on completion principle 13 forbids outright, and the same reasoning that
    keeps `_claims_impossible_action` from repairing a fabricated reason: an incoherent verdict tells
    you the judge did not answer, never what the answer was. The direction is what makes a false
    positive harmless. Should a done-reason ever legitimately describe missing work (clause (b) of
    the checker's own prompt), quoting it back would be a fair veto — and cria's response here is
    still to withhold approval. The only thing lost is the specific wording; the boolean is
    identical. Nothing can advance that would not have advanced before."""
    if not workspace_root or not os.path.isdir(workspace_root):
        return True, ""
    absent = step_names_absent_artifact(claim, workspace_root)
    if absent:
        rlog.emit("loop.confirm_absent_artifact", level="info", phase=phase, artifact=absent)
        return False, prompts.render("confirm_absent_artifact", artifact=absent)
    labels = prompts.load_map("verify_confirm")
    role = replace(reasoner_role, reasoning="off") if reasoner_role is not None else None

    def ask(extra: str = "") -> tuple[bool | None, str]:
        """One confirm judgement → (consistent, why), or (None, "") when it cannot be read."""
        user = prompts.fill(labels["user"], step=claim, reason=reason or "(none stated)") + extra
        comp = _judge_completion(reasoner_chat, role, labels["system"], user, rlog,
                                 phase=phase, force_think_off=True, workspace_root=workspace_root,
                                 answer_now_simple=verifytools.ANSWER_NOW_CONSISTENT)
        vtext = _completion_text(comp)
        if reasoner_role is not None:
            vtext = reasoner_role.clean_content(vtext)
        cleaned = strip_think(vtext)
        word = _consistent_word(cleaned)
        if word is not None:
            # The one-word answer, plus whatever reason line followed it.
            return word, "\n".join(cleaned.strip().splitlines()[1:]).strip()
        obj = extract_json_object(cleaned)
        if not isinstance(obj, dict) or not isinstance(obj.get("consistent"), bool):
            # One absent closing brace is not "no answer" — but only a NOT-consistent one is
            # recovered (verdict_from_unclosed). This is the APPROVE-path brake: recovering a
            # `consistent: true` out of a defect in the bytes would confirm a done, which is the
            # one direction principle 13 forbids; recovering the false costs a work turn.
            # Truncation is refused HERE because this site, unlike the other two judges, has no
            # is_truncated guard of its own: a reply cut at the cap is not an answer even when its
            # bytes happen to balance once closed (rule #5).
            recovered = (None if massage.is_truncated(comp)
                         else verdict_from_unclosed(vtext, "consistent", rlog, phase))
            if recovered is not None:
                return False, str(recovered.get("why") or recovered.get("reason") or "").strip()
            rlog.emit("loop.confirm_unparsed", level="warning", phase=phase)
            return None, ""
        return obj["consistent"], str(obj.get("why") or "").strip()

    verdict, why = ask()
    if verdict is False and _restates_the_verdict(why, reason):
        # ONE re-ask, escalated — the checker is told that echoing the reason answers nothing and
        # pointed back at the tools it holds. A plain repeat would be worthless: the judge call runs
        # at temperature 0, so the identical prompt returns the identical echo. The escalation is
        # neutral on the answer (it demands the missing artifact OR the contradiction OR consistent)
        # and asserts nothing about what the judge did — cria cannot see whether it looked, and a
        # "you did not look" it cannot check would be the false fact principle 5b forbids.
        rlog.emit("loop.confirm_restated_claim", level="warning", phase=phase, head=_clip(why, 120))
        verdict, why = ask("\n\n" + labels["restate"])
        if verdict is False and _restates_the_verdict(why, reason):
            rlog.emit("loop.confirm_restated_twice", level="warning", phase=phase)
            verdict = None
    if verdict is None:
        # The coder-facing reason is the plain keep-working instruction, never cria's bookkeeping and
        # never the satisfied-verdict's own reason (which argues the opposite of what the caller is
        # about to say) — same wording the satisfaction path already uses when it fails closed. That
        # rule was written for the unparseable case and the echo is exactly the case it names: the
        # done-reason arriving back as the not-done reason, only this time through a verdict that
        # parsed. Both callers (_verify and judge_satisfaction) inject this string verbatim.
        return False, prompts.load("unverified_step")
    if verdict is False:
        # Disk facts gathered exactly, ONE reasoner ruling on whether the veto's "missing" claim
        # survives them (see _veto_refuted_by_disk — the regex is only the trigger; every failure
        # direction keeps the veto). Rule 5b: a "Missing <file>" the disk disproves must not reach
        # the coder in cria's voice.
        disk_ask = (lambda sysm: summarize(reasoner_chat, role, sysm, _ASK_USER_TURN, rlog,
                                           phase="confirm-disk", temperature=0.0) or "") \
            if reasoner_role is not None else None
        refuted, disk_facts = _veto_refuted_by_disk(why, workspace_root, ask=disk_ask, rlog=rlog)
        if refuted:
            rlog.emit("loop.confirm_refuted_by_disk", level="warn", phase=phase,
                      path=refuted, head=_clip(why or "", 120))
            return True, ""
        if disk_facts:
            # The disk CORROBORATED the veto — carry that with it, so a report cria has just
            # verified does not reach the coder labelled one reader's opinion (#5b, #2).
            rlog.emit("loop.confirm_confirmed_by_disk", level="info", phase=phase,
                      head=_clip(why or "", 120))
            return verdict, why + "\n\n" + prompts.render("veto_disk_confirms", facts=disk_facts)
    return verdict, why


# A judge holds ONLY read-only inspection tools (list_dir/read_file) — a verdict whose reason
# claims it ran, curled, fetched or tested something is FABRICATED evidence (observed: a
# satisfaction verdict said "confirmed by curling api.handle.me/goose"; its own reasoning shows it
# merely INTENDED to curl via exec_command — a tool it does not hold — and the retry asserted the
# intent as fact; that false fact became pinned plan-step text, run 0729-mellum2 calls 0153-0154).
# Third-person reports ("the coder ran pytest") don't match — only the judge claiming its own acts.
_JUDGE_ACTION_CLAIM = re.compile(
    r"(?i)\b(?:i|we)\s+(?:ran|executed|curled|fetch(?:ed)?|tested)\b"
    r"|\bconfirmed by (?:curl|runn?)ing\b")


def _claims_impossible_action(obj: dict | None, rlog, phase: str, ask=None) -> bool:
    """True (and traced) when a parsed verdict's reason claims a judge-performed action the judge
    cannot perform — the caller treats the verdict as unusable, which routes to the normal
    reasoning-off retry / fail-closed path instead of letting fabricated evidence stand.

    TRIGGER, THEN JUDGE (operator, 2026-08-08). `_JUDGE_ACTION_CLAIM` stays as the cheap pre-filter
    — it costs nothing and most verdicts never mention an action — but WHETHER the sentence claims
    the judge's own act is a reading, not a pattern. The regex alone cannot tell "I ran the tests"
    from "I ran through the checklist" or "we tested the assumption that…", and a false hit throws
    away a good verdict and burns a retry. With no reasoner the trigger decides alone, exactly as
    before; an unreadable answer keeps the verdict (CLEAN is the safe direction — a fabricated
    reason that slips through still faces every other guard, while a discarded good verdict is a
    lost turn)."""
    reason = str((obj or {}).get("reason") or "")
    if not _JUDGE_ACTION_CLAIM.search(reason):
        return False
    if ask is not None:
        answer = strip_think(ask(prompts.render("judge_claimed_an_action", reason=reason)) or "")
        head = answer.strip().upper().split()[0].strip(".,:;`*\"'") if answer.split() else ""
        if head != "FABRICATED":
            return False
    rlog.emit("loop.verdict_fabricated_action", level="warn", phase=phase,
              head=_clip(reason, 120))
    return True


# A judge's own THINKING, when its final answer was not a verdict. Recovers ONLY a NOT-satisfied
# ruling — never an approval.
#
# Measured 2026-08-01 over every gemma4 satisfaction/confirm response on the box: of 46 replies cria
# could not parse, **20 carry a clear verdict in reasoning_content**. One example, verbatim, after a
# prompt whose last line was "Answer NOW with ONLY the JSON verdict" — the content field held a
# leaked `<|tool_call>call:read_file{...}` and the thinking held this:
#
#   "The task is not done. The live test output shows Holder: unknown and Total Handles: 0 for
#    papagoose, while the real data has holder='stake1...' and a non-zero total. This means
#    resolve_handle is not correctly extracting the holder."
#
# Correct, specific, actionable, discarded. cria already holds this rule for the CODER — read the
# reasoning before concluding the model failed; "found it then lost it" is not "never found it" —
# and did not apply it to its own judges.
#
# ONE DIRECTION ONLY. An approval recovered from prose would be failing OPEN on completion, which
# principle 13 forbids outright. A recovered NOT-satisfied can only ever mean "keep working", so a
# false positive costs a turn and never a false finish. That asymmetry is why a recovery is safe to
# attempt at all — and the reading itself is now a reasoner's job, not a phrase list's
# (see verdict_from_reasoning).


# Tool names a judge EMITS that it was never given. Its menu is exactly list_dir + read_file; across
# 46 unparseable gemma4 verdicts it called Bash, Grep, Read, Edit, EditFile, Write, ReadAll, ReadMe,
# web_fetch, write_file, edit_file — and once a tool named after itself ("Gemma4Judge"). Bash/Grep/
# Read/Edit/Write are another harness's vocabulary entirely. Detecting this does not repair the turn;
# it names the failure in the record instead of filing it under "unparseable", and lets the retry
# tell the model the truth about what it holds.
_JUDGE_TOOLS = ("list_dir", "read_file")
_LEAKED_CALL_NAME = re.compile(r"<\|tool_call>\s*call:([A-Za-z_][\w.]*)")


def leaked_judge_tool(text: str) -> str:
    """The name of a tool the judge invoked but does not have, or ""."""
    m = _LEAKED_CALL_NAME.search(text or "")
    name = m.group(1) if m else ""
    return name if name and name not in _JUDGE_TOOLS else ""


# Past this a recovered reason is an ESSAY, not a directive — and the coder ACTS on it, so it is
# content a model reads. #5 leaves one way to shorten it: the judge restates its own reason in a
# line. `reason[:300]` once cut a judge's thinking mid-word and handed the fragment on as the
# diagnosis; whole-sentences-up-to-a-budget was the same defect with a tidier seam. If the ask is
# unavailable or empty the long reason rides WHOLE — too much is recoverable, a silent slice is not.
REASON_ONE_LINE_CHARS = 600


def _reason_in_one_line(reason: str, ask, rlog, phase: str) -> str:
    """A long recovered reason restated by the JUDGE in one line, or the reason unchanged. Failure in
    any direction returns the input untouched."""
    if len(reason) <= REASON_ONE_LINE_CHARS or ask is None:
        return reason
    short = strip_think(ask(prompts.render("verdict_reason_one_line", reason=reason)) or "").strip()
    if not short or len(short) >= len(reason):
        return reason
    rlog.emit("loop.reason_condensed", level="info", phase=phase,
              chars_before=len(reason), chars_after=len(short))
    return short


def verdict_from_unclosed(vtext: str, flag: str, rlog, phase: str) -> dict | None:
    """A judge's OWN verdict object, recovered when its only defect is an absent closing brace — and
    ONLY when it rules NOT-done. ``None`` otherwise.

    ``flag`` is the phase's own key ("done" / "satisfied" / "consistent"), exactly as
    :func:`verdict_from_reasoning` takes it, so no caller's reading path changes shape.

    WHAT WAS MEASURED. Replaying all 18,655 captured final replies through cria's own reader
    (2026-08-02): 14 came back unreadable while holding a syntactically complete JSON object missing
    a single ``}``. All 14 stopped on their own (``finish_reason: stop``). Twelve are NOT-done
    rulings, ELEVEN of them with a written reason AND a written proposed_fix — the diagnosis the
    coder never got. (The commit said twelve carried both. The twelfth is 0120-critic-confirm, whose
    phase schema is ``{consistent, why}`` and has no ``proposed_fix`` field to carry; corrected at
    review rather than left standing, rule 23b.) One is an APPROVAL (``done: true``, run
    20260801T232511 call 0173-critic) and one is a plan re-derivation carrying no verdict flag at
    all (0050-reasoner). Both are refused here.

    DIRECTION (#13), stated as code below and not only in prose: the recovered object must carry the
    phase's flag and it must be literally ``False``. A recovered NOT-done can only ever cost a turn
    of work; a recovered "done" would be a false finish reached through a defect in the bytes, which
    is the fail-OPEN-on-missing-ground-truth root of every early exit this file documents. The same
    one-way contract, and the same reason, as ``verdict_from_reasoning`` and the reasoning-off
    retry's ``verify_failclosed``.

    WHY BEFORE ``verdict_from_reasoning``: both recover a NOT-done, but this one recovers the verdict
    the judge actually WROTE — its own ``reason`` and its own ``proposed_fix``, verbatim — where the
    reasoning path can only forward sentences scraped out of the thinking and leaves ``proposed_fix``
    empty. Strictly better evidence for the same ruling, so it is tried first.

    WHAT IT ACTUALLY CHANGES, read rather than assumed (the corrective this entry exists to record).
    The first draft of this docstring claimed all twelve "fell to ``unverified_step``". They did not.
    Following each one to the next captured call: in 4 of the 8 step-critic cases the reasoning-OFF
    retry answered with its own readable NOT-done, so the coder read THAT — the change here is which
    pass's words reach it (the careful one's) and one reasoner call saved, not a rescue. The 3
    satisfaction cases and the 1 confirm case fell closed as designed. In exactly ONE call in 126
    sessions did the coder actually read cria saying it had no verdict: run 20260728T092146 call
    0019, where BOTH critic passes came back unclosed and the coder was handed the bare line
    ``unverified (no parseable verdict)``. Asked again through ``suite/replay_recompose.py`` on the
    same model at that call's own sampling, the shipped prompt produced a reply whose thinking reads
    "the user's steering instruction says 'unverified (no parseable verdict)' — meaning they haven't
    given me a specific check to perform", and answered with prose and no tool call at all; the
    recomposed prompt sent it to inspect the API response the judge had named. That is the whole
    measured model-facing effect: n=1. This ships as a READER fix, not a rescue.

    NOT TRUNCATION. A ``finish_reason: length`` reply is refused before it reaches here, at every
    one of the three call sites — the two judges already ran ``massage.is_truncated`` and returned;
    the confirm brake, which had no such guard, grew one at its call to this. A cut generation stays
    refused however neatly its bytes happen to close. This function is given only text and cannot
    see the finish reason, which is why the refusal is stated at the sites that CAN.
    """
    obj = jsontext.close_unclosed_object(vtext or "")
    if not isinstance(obj, dict) or obj.get(flag) is not False:
        return None      # no repairable object, no verdict flag, or an APPROVAL — all refused
    if not _is_a_finding(str(obj.get("reason") or obj.get("why") or "")):
        return None      # a ruling with nothing behind it — see _is_a_finding
    rlog.emit("loop.verdict_from_unclosed", level="info", phase=phase, flag=flag,
              reason=_clip(str(obj.get("reason") or obj.get("why") or ""), 120))
    return obj


def _is_a_finding(reason: str) -> bool:
    """Does this ``reason`` carry an answer, rather than the SHAPE of one?

    Every judge prompt defines ``reason`` as "your SPECIFIC finding grounded in THIS evidence", and
    recovery exists to rescue the judge's own words. When there are no words there is nothing to
    rescue, and the fail-closed path already reaches the same NOT-done ruling without cria claiming
    the judge said something. So refusing here costs nothing and can only ever move the outcome
    toward "keep working" — which is why it ships at a measured prevalence of ZERO (0 of the 12
    repairable NOT-done verdicts on this box, and 1 of 314 verdicts cria's ordinary reader already
    accepts). It is a bound on what recovery may do, not a detector.

    TWO SHAPES, no vocabulary — this must not become a list of words anyone has to keep tuning:

    * nothing but punctuation or whitespace. ``close_unclosed_object`` makes a new input reachable —
      a model that ECHOES the instruction it was given and stops mid-object — and the instruction it
      is given ends in a literal JSON template. ``Answer in the form {"done": false, "reason": "..."``
      repairs perfectly and yields a "finding" of ``...``, which ``_verdict_nudge`` would then hand
      the coder as its corrective.
    * an angle-bracket placeholder and nothing else. That is cria's OWN convention for a slot the
      model is meant to fill — ``"reason": "<short>"``, ``"proposed_fix": "<brief fix prose>"``,
      ``grep -n "<keyword>"`` — so a reason that IS one is the template coming back, not a reading of
      the evidence. Structural (the bracket shape cria writes), never a list of the words inside."""
    r = (reason or "").strip()
    if not re.search(r"\w", r):
        return False
    return not (r.startswith("<") and r.endswith(">") and ">" not in r[1:-1])


# Sentinel that opens a recovered ruling. A POSITIVE token, like ON_TRACK: the alternative is
# UNCLEAR, so a model that cannot decide does not accidentally emit the recovery.
_RECOVERED = "NOT_DONE"


def verdict_from_reasoning(reasoning: str, flag: str, rlog, phase: str, ask=None) -> dict | None:
    """A NOT-satisfied verdict recovered from a judge's thinking OR its prose answer, or None.

    `flag` is the phase's own key — "satisfied", "done" or "consistent" — so the caller's existing
    reading path is untouched.

    THE REASONER READS THE THINKING (operator, 2026-08-08). This used to decide with
    `_VERDICT_NEGATIVE`, a regex of ruling phrasings — "task is not done", "remains incomplete",
    "no readme was found". It is the single most fragile matcher cria had: every other word-hunter
    reads text cria composed or a tool emitted, and this one reads a model's UNCONSTRAINED private
    prose, in whatever words that model reaches for, and turns the answer into a verdict. A miss
    loses a real not-done ruling and the session can end on work that is not finished; a false hit
    reopens finished work on a sentence the judge never meant as a ruling.

    It is also the cheapest possible place to spend a call: this path only runs when the judge's
    reply ALREADY failed to parse, so the alternative to one focused question is a wasted turn.

    Every failure direction keeps today's safe answer — no reasoner, an unreadable reply, or any
    doubt on the model's part all return None, which routes to the caller's existing fail-closed
    retry. Approval is never recovered from thinking, in either implementation."""
    text = (reasoning or "").strip()
    if not text or ask is None:
        return None
    answer = strip_think(ask(prompts.render("verdict_in_reasoning", thinking=text)) or "").strip()
    head = answer.split(":", 1)
    if head[0].strip().upper() != _RECOVERED:
        return None
    recovered = head[1].strip() if len(head) > 1 else ""
    # The sentence carrying the ruling IS the reason — the coder needs the diagnosis, not "the judge
    # said no". Bounded because this is a prompt cria COMPOSES, not content the coder reads.
    # From the ruling sentence ONWARD, not the ruling alone. "The task is not done." tells the coder
    # nothing; the sentences after it carry the diagnosis ("Holder: unknown and Total Handles: 0 ...
    # resolve_handle is not correctly extracting the holder"), which is the whole value of the
    # recovery. Bounded because this is a prompt cria COMPOSES, not content the coder reads.
    # The reasoner reports the judge's reason IN THE JUDGE'S WORDS; anchor the excerpt on it so the
    # sentences AFTER the ruling — which carry the diagnosis the coder needs — ride along, exactly as
    # the regex version did from its match onward.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    key = " ".join(recovered.split()[:6]).lower()
    start = next((i for i, sn in enumerate(sentences) if key and key in " ".join(sn.split()).lower()),
                 None)
    if start is None and not key:
        # A BARE `NOT_DONE` with no sentence after it. The reasoner ruled but quoted nothing, so
        # there is no anchor to miss and the judge's own text from the top is the best available
        # reason — the long-standing behaviour, deliberately kept.
        start = 0
    if start is None:
        # THE ANCHOR MISSED, SO THE ANCHORED EXCERPT IS WORTHLESS. This defaulted to 0 and shipped
        # the thinking FROM THE TOP — which is the model warming up, not its ruling. The one piece of
        # text known to be about the ruling is the sentence the reasoner just handed back, and it was
        # thrown away at exactly the moment the recovery had worked.
        #
        # Measured, ternary-bonsai/ruby 0085. Recovered: "the code was broken because it used the
        # wrong API (`EuCountries.eu_members` instead of `ISO3166.EUCountry.codes.include?(code)`)".
        # Delivered to the coder: "Let me check if there's a way to see what happened after my
        # write_file call." — sentence zero.
        #
        # A fallback that fires precisely when the recovery succeeded is the band-aid (#4), so it is
        # deleted rather than tuned.
        reason = recovered
        if not reason:
            return None                      # nothing about the ruling to carry — fail closed (#13)
        rlog.emit("loop.verdict_from_reasoning", level="info", phase=phase, anchor_missed=True,
                  matched=_clip(recovered, 60), reason=_clip(reason, 120))
        return {flag: False, "reason": reason, "proposed_fix": ""}
    # WHOLE SENTENCES up to the budget, never a hard character slice. `reason[:300]` cut a judge's
    # thinking mid-word and handed the fragment onward as the diagnosis the coder must act on — an
    # instruction that stops mid-sentence is one the coder completes by guessing. The budget bounds
    # how MANY sentences, so a single long sentence rides whole rather than being amputated.
    reason = _reason_in_one_line(" ".join(sentences[start:]).strip() or text, ask, rlog, phase)
    rlog.emit("loop.verdict_from_reasoning", level="info", phase=phase,
              matched=_clip(recovered, 60), reason=_clip(reason, 120))
    return {flag: False, "reason": reason, "proposed_fix": ""}


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
    inferred = not _fix_text(obj)
    rlog.emit("loop.verdict_flag_inferred", flag=flag, inferred=inferred, phase=phase)
    return {**obj, flag: inferred}


# Textual null spellings a model writes where the schema means "" — observed live: gemma emits
# "None"/"none" in proposed_fix on DONE verdicts (g2 0141; g1's role-collapsed steers). A bounded
# normalization of null spellings, not a judgment list.
_NULL_FIX = {"", "none", "null", "n/a"}


def _fix_text(obj: dict) -> str:
    """The verdict's proposed_fix as ACTION TEXT — "" when absent or a textual null. Without this,
    the emptiness contract read the literal word "None" as a concrete fix (inferring NOT-done on a
    done verdict), and the completion fix-step path could append a step whose entire text was
    "None"."""
    fix = str(obj.get("proposed_fix") or "").strip()
    return "" if fix.lower().rstrip(".") in _NULL_FIX else fix


def judge_satisfaction(task: str, evidence: str, reasoner_chat, reasoner_role, rlog, coder_tools: str = "",
                       workspace_root: str = "", routes: str = "",
                       gate_findings: str = "") -> tuple[bool, str]:
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
    inspection_capped: list = []
    obj = _satisfaction_verdict(system, user, reasoner_chat, reasoner_role, rlog, reasoning_off=False,
                                capped=inspection_capped,
                                workspace_root=workspace_root)
    if obj is not None:
        obj = _fill_missing_verdict_flag(obj, "satisfied", rlog, "satisfaction")
    fab_ask = ((lambda sysm: ask_closed(reasoner_chat, reasoner_role, sysm, rlog,
                                        phase="satisfaction-action"))
               if reasoner_role is not None else None)
    if obj is not None and _claims_impossible_action(obj, rlog, "satisfaction", fab_ask):
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
        # A GAP NAMED FROM AN UNFINISHED LOOK IS NOT A GAP. When the inspection hit its cap the judge
        # was made to answer without having finished reading, and what it produced on cycle 4 cell 10
        # was "Importer.java is the original unmodified code (WORKERS_ENABLED=false, no OpenCSV
        # usage…)" — four minutes after the suite had measured all five checks passing BY RUNNING
        # THEM. Six such reasons went to the coder over 62 minutes and it edited a working 5/5
        # solution down to 4/5. The VERDICT still stands (not satisfied, fail closed, #13); what is
        # withheld is the invented reason, so the caller falls back to the plain instruction rather
        # than sending the coder to fix work that is already right (#3, #5b).
        if inspection_capped and not satisfied:
            rlog.emit("loop.satisfaction_gap_withheld", level="warn",
                      rounds=inspection_capped[0], head=_clip(str(obj.get("reason") or ""), 120))
            return False, prompts.load("unverified_step"), ""
        return satisfied, _verdict_nudge(obj, satisfied, routes, evidence=user,
                                         workspace_root=workspace_root, rlog=rlog), _fix_text(obj)
    # No parseable careful verdict (the reasoner over-thought, or leaked a spurious tool call instead of
    # the JSON). A reasoning-OFF retry can RECOVER a verdict, but a reasoning-off judge is a rubber
    # stamp — competent to REJECT, not to APPROVE. So use it only to confirm NOT-satisfied; a
    # "satisfied" that exists ONLY because the careful pass failed is downgraded and we fail CLOSED. A
    # false "done" over fake work is far worse than a few more work turns.
    retry = _satisfaction_verdict(system, user, reasoner_chat, reasoner_role, rlog, reasoning_off=True)
    if retry is None:
        # Fail closed — but the CODER-facing reason is a plain instruction, never cria's internal
        # bookkeeping: "unverified (no parseable verdict)" injected as a steer made one model
        # confabulate a meaning for it and leap ahead to another file (run 0729-gemma4 pon2 0243).
        return False, prompts.load("unverified_step") + _named_gap(gate_findings), ""
    if retry.get("satisfied"):
        rlog.emit("loop.satisfaction_failclosed", level="info")
        return False, "unverified — the careful check could not confirm completion; keep working", ""
    return False, _verdict_nudge(retry, False, routes, evidence=user,
                                 workspace_root=workspace_root, rlog=rlog), \
        str(retry.get("proposed_fix") or "").strip()


def satisfaction_done_note(reason: str, exec_marker: str = "", *, checks_ran: bool = True) -> str:
    """The completion text forwarded when the satisfaction check accepts a 'done'.

    `checks_ran` decides which claim it opens with, and it has to, because `guard_gate_verdict`
    returns None for a green gate AND for one that could not run — the same fail-open every other
    seat honours. The old wording asserted "verified by the completion check AND THE REPO'S OWN
    CHECKS" in both cases, and in the second case nothing had verified anything: a false fact about
    the world, stated in the session's last message (#5b). The same wording also shipped on the
    no-shell path, where no gate was even composed. Both wordings live in prompts/ (#22); the answer
    comes from `last_gate_ran`, which every gate reader now writes (see record_gate_state).

    `exec_marker` is the LIVE EXECUTION result (cria/execcheck.py) and is APPENDED, never gating:
    the repo's own checks prove a workspace compiles, lints and passes its tests, and none of that
    can tell you the delivered program does anything. Measured across 51 archived runs: 13 (25%)
    contained no entry point at all and not one of those ever scored full marks. The marker is empty
    on a confirmed run and on a task that needs no run, so a clean signal stays silent."""
    words = prompts.load_map("satisfaction_done")
    note = f"{words['checked' if checks_ran else 'unchecked']} {reason}".strip()
    return f"{note}\n\n{exec_marker}".strip() if exec_marker else note


def live_execution_marker(sess, body: dict, task: str, reasoner_chat, reasoner_role, rlog) -> str:
    """Ask the model what to run, corroborate it against the README and the files on disk, run it if
    all three agree, and return the marker. NEVER blocks — returns "" on anything unclear.

    The whole call is skipped when there is no workspace to inspect, so a session with nothing on
    disk pays nothing.
    """
    root = getattr(sess, "workspace_root", "") or ""
    if not root or not task.strip():
        return ""
    try:
        # The workspace listing rides along — see execcheck.intent_prompt. cria could always read it
        # (the steer author and the step critic already get the same inventory); withholding it is
        # what made this judge invent three filenames that never existed.
        system, user = execcheck.intent_prompt(
            task, files=workspace_inventory(root),
            # …and what the project says about ITSELF. cria parses these already and
            # uses them to veto this very answer; withholding them made the probe guess.
            declared=execcheck.declared_listing(root))
        # ONE ANSWER PER QUESTION. This runs on every completion attempt, and the question is built
        # from the task, the workspace listing and the project's declared commands — so when none of
        # those has moved, the prompt is byte-identical and so is the answer. Measured over five
        # days: 240 exec-intent calls, 104 of them byte-identical repeats (43%), 82,221 completion
        # tokens; one session asked the same question seven times. #9 spends a call to ground the
        # next action and bounds it with exactly this: a call that does not move the plan must not
        # repeat. Keyed on the prompt itself, so any real change re-asks.
        key = hashlib.sha1((system + "\x00" + user).encode("utf-8", "replace")).hexdigest()
        cached = getattr(sess, "exec_intent_reply", "") if getattr(sess, "exec_intent_key", "") == key else ""
        # REASONING OFF, and a cut answer is no answer. This asks for three JSON fields and nothing
        # else — there is nothing here to think about, and thinking is what killed it. Its first and
        # only live firing, ada-handles_mellum2_codex_poff_1785714194 call 0032: `finish_reason=length`,
        # empty content, all 8,192 tokens spent in reasoning_content, ending in a degenerate `5x5x5…`
        # loop. No JSON, so parse_intent returned {} and the delivered program was never run — the one
        # check built to catch a green gate over a broken program, 0 for 1. Every sibling judge already
        # does one of these two things (force_think_off at _satisfaction_verdict, the truncation retry
        # at the critic); this call did neither.
        if cached:
            rlog.emit("loop.exec_intent_reused", level="info", key=key[:8])
            intent_text = cached
        else:
            comp = _judge_completion(reasoner_chat, reasoner_role, system, user, rlog,
                                     phase="exec-intent", workspace_root="", force_think_off=True)
            if massage.is_truncated(comp):
                rlog.emit("loop.exec_intent_truncated", level="warn")
                return ""   # a cut intent is not an intent; say nothing rather than guess a command
            intent_text = _completion_text(comp) or ""
            if intent_text.strip():
                sess.exec_intent_key, sess.exec_intent_reply = key, intent_text
        # The output-vs-expectation question is the reasoner's (see execcheck.evaluate). Reasoning
        # OFF and temperature 0: it answers one word from a fixed set, like every other closed
        # question cria asks. No reasoner configured → evaluate() falls back to today's silence.
        off = replace(reasoner_role, reasoning="off") if reasoner_role is not None else None
        match_ask = (lambda sysm: summarize(reasoner_chat, off, sysm, _ASK_USER_TURN, rlog,
                                            phase="exec-output", temperature=0.0) or "") \
            if reasoner_role is not None else None
        result = execcheck.evaluate(root, execcheck.parse_intent(intent_text), ask=match_ask)
        rlog.emit("loop.exec_check", verdict=result.verdict, command=_clip(result.command, 80),
                  exit_code=result.exit_code)
        # THE CODER GETS IT TOO. Walked on both 2026-08-07 runs, and it is the whole resolver_cli
        # failure in each. cria ran `handle_resolver.py goose`, watched it exit 1, wrote the finding
        # correctly — and put it in the satisfaction judge's evidence and nowhere else. All three
        # call sites feed `ev`/`evidence`; none feeds the coder. So the one party that could fix the
        # command-line entry point was never told cria had run it and it failed, while the judge —
        # invited by the marker's own closing hedge to treat it as "evidence, not a verdict" —
        # discounted it and ended the session. Twice, on two different models.
        #
        # NOT_OBSERVED only. That verdict is a defect in the coder's program, stated from an exit
        # code cria observed itself; `inconclusive` is a gap in what CRIA could establish, and
        # telling the coder "I could not work out how to run your program" is noise it cannot act on
        # (principle 3). Still never a gate — the marker rides along with whatever cria was already
        # going to say, and if cria was going to say nothing this changes nothing.
        sess.exec_finding = result.marker if result.verdict == execcheck.NOT_OBSERVED else ""
        return result.marker
    except Exception as e:  # noqa: BLE001
        rlog.emit("loop.exec_check_error", level="warn", error=f"{type(e).__name__}: {e}")
        return ""   # a check that cannot run must never affect a completion


def _exec_finding_line(sess) -> str:
    """cria's own run of the deliverable, as a line for the coder — or "" when there is nothing to say.

    Consumed once. The finding is true of the workspace as it stood when cria ran it; leaving it
    parked would re-assert a failure the coder may have just fixed, which is the stale-ground-truth
    fault this same walk found four times over."""
    line = getattr(sess, "exec_finding", "") or ""
    sess.exec_finding = ""
    return f"\n\n{line}" if line else ""


# A briefing sentence DENYING that a named file exists: a filename token, a negation, a creation
# verb, one sentence. Used ONLY to decide whether to append cria's file list as an override — never
# to delete text. See _briefing_disk_truth.
_DENIES_FILE = re.compile(
    r"\b([\w./-]+\.\w{1,5})\b[^.\n]{0,80}?\b(?:not|never|no|n't|yet\s+to)\b[^.\n]{0,40}?"
    r"\b(?:written|created|added|implemented|exists?|started)\b"
    r"|\b(?:not|never|no)\b[^.\n]{0,60}?\b(?:written|created|added)\b[^.\n]{0,40}?"
    r"\b([\w./-]+\.\w{1,5})\b", re.I)


def _briefing_denies_real_files(briefing: str, files_list: str) -> list[str]:
    """Files the briefing says are missing that cria's OWN disk listing shows exist."""
    present = {m.lower() for m in re.findall(r"[\w./-]+\.\w{1,5}", files_list or "")}
    if not present:
        return []
    named = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", briefing or ""):
        m = _DENIES_FILE.search(sent)
        if not m:
            continue
        f = (m.group(1) or m.group(2) or "").lower()
        if f and any(f == q or q.endswith("/" + f) for q in present) and f not in named:
            named.append(f)
    return named


def _briefing_disk_truth(briefing: str, files_list: str, rlog=None) -> str:
    """The briefing, plus a ground-truth line when it denies a file cria can see. NEVER deletes.

    THE maple 1786218955 ROLLUP, twice: "The Python script … has not been written. Unit tests have
    not been added. … The implementation has not yet been started" over a ⟦ctx:files⟧ block in the
    SAME prompt listing both files, and a real `2 failed, 7 passed`.

    The first cut of this DELETED the offending sentences, and stress-testing it found exactly the
    fault it was written to fix: "resolver.py: the main() function has not been written" — a TRUE
    statement about missing work — was erased because the FILE exists, and a repeated sentence left
    "A.  B." behind. A regex cannot tell a claim about a file from a claim about something inside
    it, and the cost of guessing wrong is hiding real remaining work. So it appends instead, exactly
    as _briefing_gate_ground_truth already does for the check state: cria states its fact, the
    briefing keeps its words, and the reader is told which to trust. Same mechanism, same file,
    additive in both cases."""
    named = _briefing_denies_real_files(briefing, files_list)
    if not named:
        return briefing
    if rlog is not None:
        rlog.emit("context.briefing_denies_disk", level="warn", files=",".join(named[:6]))
    return briefing + "\n\n" + prompts.fill(
        prompts.load_map("briefing_checks")["files_exist"], files=", ".join(named))


# Past this, a COMPOSED two-message prompt cannot be made to fit by the context floor: the floor's
# lever is dropping whole oldest turns, and a two-message call has none to drop. This is where #5's
# second exception applies — a MODEL-MADE summary, labelled as one — because the alternative that
# used to sit here was a character clip, and the one after that is a judge call that errors out and
# fails closed into the same re-nudge loop the clip was built for.
EVIDENCE_SUMMARY_TRIGGER_CHARS = 48000


def _summarised_evidence(log: str, chat_fn, role, rlog) -> str:
    """`log` condensed by the MODEL, labelled as a summary — never a clip. Returns the log unchanged
    when there is no reasoner or the summary comes back empty: carrying too much is recoverable, and
    a silent slice is not (#5, #13)."""
    ready = chat_fn is not None and role is not None and rlog is not None
    text = summarize(chat_fn, role, prompts.load("evidence_summary"), log, rlog,
                     phase="compactor") if ready else ""
    if not text.strip():
        return log
    if rlog is not None:
        rlog.emit("evidence.summarised", level="info",
                  chars_before=len(log), chars_after=len(text))
    return prompts.render("evidence_summary_note", summary=text.strip())


def _dedup_evidence(log: str, rlog=None, chat_fn=None, role=None) -> str:
    """The work log with byte-identical repeated ACTION BLOCKS folded to one copy plus a pointer.

    THIS REPLACED A TAIL CLIP (`_bound_evidence`, 24,000 characters, head discarded). #5 now reads
    "cria never truncates" for every reader — a judge's and a steer author's prompt included — with
    de-duplication and a model-made summary as the only exceptions. The incident that justified the
    old budget is the argument for folding rather than clipping: live on run 0726-203600, stuck on
    step 5, the log grew 34KB -> 106KB -> 223KB across re-nudges on ONE step, which is the same
    actions re-rendered. Folding removes exactly that redundancy and keeps every DISTINCT action; the
    clip removed whichever happened to be oldest, which on a stuck step is the write that started it.

    What is left after folding is fitted by the context floor, which is the one lossless-first place
    (#5) — and `_work_log`'s own docstring already said so: "a per-site clip here would just be a
    dumber, undetectable slice of what the model reads"."""
    out, folded = dedup.fold_repeated_actions(log, prompts.load(dedup.REPEAT_NOTE_KEY).strip())
    if folded and rlog is not None:
        rlog.emit("evidence.repeats_folded", level="info", folded=folded,
                  chars_before=len(log), chars_after=len(out))
    if len(out) > EVIDENCE_SUMMARY_TRIGGER_CHARS:
        out = _summarised_evidence(out, chat_fn, role, rlog)
    return out


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
            # A REPLACING put on a stable (sid:) key is the same CONVERSATION getting a new
            # session object — the post-compaction continuation, the follow-up plan. Its durable
            # fetch ledger is conversation truth and must survive the swap: walked on run
            # 1785893473 call 0083, the continuation session started blank and the next prompt
            # told the coder "no endpoint definitions were found in it" about a spec whose full
            # 33-endpoint outline the OLD session's ledger still held. _merge_fetches keeps the
            # richer entry per URL, so a later outline-less fetch can't clobber an earlier
            # outline. task: keys are prompt-derived and can collide across unrelated runs —
            # those inherit nothing (the plan-cache-leak lesson, applied to fetches).
            prev = self._sessions.get(key)
            if prev is not None and _stable_session(key) and getattr(prev, "fetched_pages", None):
                sess.fetched_pages = _merge_fetches(dict(sess.fetched_pages or {}),
                                                    prev.fetched_pages)
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
        """Record this session's conversation SHAPE; return True while a rewrite is PENDING — the
        harness REPLACED the history under a stable session key. Structural, no phrase-matching.

        TWO signals, because harnesses rewrite two different ways and cria only watched for one:

        * the ROOT CHANGED — the summary became the first user message.
        * the HISTORY SHRANK — the harness kept the user messages (the original task among them) and
          dropped the assistant/tool work behind them. Codex does this, and it is why the root test
          alone was dead: `loop.history_rewritten` had fired ZERO times over 256 recorded sessions
          while the harness compacted 139 times in the same window, and all 256 persisted `pending`
          flags were still False. The four mechanisms gated on this — the continuation plan and the
          three probe re-issues — had never run, so a gate result lost to a compaction was simply
          gone. `n_messages` was already being STORED here and never compared.

        Turns that merely append can only grow the history, so a shrink cannot be an append. Measured
        across 141 real sessions: inbound length dropped 108 times, and every one of the 108 followed
        a harness compaction — no false positives. 56 of the 60 compacting sessions show it (the
        other 4 ended on the compaction).

        The signal is STICKY: a detected rewrite stays pending until ``clear_rewrite`` — so a
        turn that couldn't act on it (planner failed, non-task decline) doesn't consume it; the
        next turn still knows the history was rewritten."""
        if not fp:
            return False
        with self._lock:
            prev = self._shapes.get(key)
            shrank = prev is not None and n_messages < int(prev.get("n") or 0)
            changed = prev is not None and (prev.get("fp") != fp or shrank)
            pending = changed or bool(prev and prev.get("pending"))
            first_sight = prev is None
            self._shapes.pop(key, None)  # re-put refreshes recency
            self._shapes[key] = {"fp": fp, "n": n_messages, "pending": pending,
                                 "done": bool(prev and prev.get("done"))}  # done bit survives re-puts
            while len(self._shapes) > _MAX_SHAPES:
                self._shapes.pop(next(iter(self._shapes)))
            if first_sight or changed:  # persist only on shape changes, not every turn
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
    # `synthetic` means DEGENERATE, not "the planner is off": it is set from len(plan.items) == 1
    # (see _drive), so a plan-off session whose model drafts TWO steps runs the ordinary multi-item
    # driver and the coder sees "Do ONLY this step (1 of 2)". That is the NORMAL path — 37 of 50
    # cycle-1 captures took it. Read as "planner off means one item", it manufactures a bug report:
    # it did, on 2026-08-14.
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
        # Codex's prompt_cache_key) is stable across a compaction, but the conversation SHAPE is not
        # — either the root is replaced by the harness's summary, or the history simply gets shorter
        # (Codex keeps every user message, the original task included, and drops the work behind
        # them). Normal turns only append, so either is a rewrite. See observe_shape: the root test
        # alone had never once fired, because the shape Codex produces is the second one.
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
                # The reading step is written BY THE MODEL (research.authored_research_step) — cria
                # only supplies the one fact it can establish on its own, that the task names an
                # external source. cria does not write plan steps.
                def _plan_ask(sysp, usr):
                    return summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                     sysp, usr, rlog, phase="research-step")
                sess = _plan_off_session(_synthetic_plan(latest_user_text(messages), ask=_plan_ask,
                                                         files=workspace_inventory(_extract_cwd(messages)
                                                                                   or self._ctx.workspace_root)),
                                          briefing)
                # PERSISTENCE (Invariant 3, load-bearing): a stable ``sid:`` key persists + resumes;
                # an unstable ``task:`` key is EPHEMERAL — never ``put`` (re-synthesized each turn),
                # exactly as the plan-off path handed unstable keys a fresh state, so a synthetic session
                # can't leak across unrelated same-prompt conversations (the plan-cache-leak class).
                # A DEGENERATE plan is never mirrored to disk: it's just the raw task. One that gained
                # a reading step is a real plan and mirrors like any other.
                if _stable_session(session_key):
                    self._store.put(session_key, sess)
                if not sess.synthetic:
                    self._persist_plan(sess.plan, rlog)
                rlog.emit("loop.start", id=sess.plan.id, steps=len(sess.plan.items),
                          synthetic=sess.synthetic)
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
                    # via the rewrite frame — never as a fresh task, and never stacking cria's own
                    # briefing on top of the harness summary (two summaries drowned the planner →
                    # the placeholder plan). The summary is NOT always the root: on a harness that
                    # keeps the user messages, the root is still the original task and handing that
                    # over as "the summary" would ask the planner to re-plan the whole job from
                    # scratch, which is the one thing a continuation exists to avoid.
                    summary_text = _rewrite_summary_text(messages, root_text)
                    plan = self._ctx.planner.plan_for(messages, rlog, rewrite_summary=summary_text)
                    if plan is None:
                        return None  # rewrite stays PENDING (sticky) — the next turn can still continue
                    # The coder's protected prior-work context: cria's own briefing when we have one
                    # (compact, focused); else the harness summary TAIL, clipped — summaries put the
                    # current state / remaining work at the END, so the head is the droppable part.
                    sess = PlanSession(plan=plan, prior_work=briefing or summary_text)
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
                        def _plan_ask(sysp, usr):
                            return summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                             sysp, usr, rlog, phase="research-step")
                        sess = _plan_off_session(_synthetic_plan(latest_user_text(messages), ask=_plan_ask,
                                                                 files=workspace_inventory(_extract_cwd(messages)
                                                                                           or self._ctx.workspace_root)),
                                                 briefing)
                        if _stable_session(session_key):
                            self._store.put(session_key, sess)
                        rlog.emit("loop.start", id=sess.plan.id, steps=len(sess.plan.items), synthetic=sess.synthetic,
                                  planner_fallback=True)
                    else:
                        sess = PlanSession(plan=plan, prior_work=briefing)
                        self._store.put(session_key, sess)
                        rlog.emit("loop.start", id=plan.id, steps=len(plan.items), continued=bool(briefing))
                        self._persist_plan(plan, rlog)  # mirror to cria's OWN dir (never the workspace)

        # PLAN-OFF HAND-BACK: the reading step was the ONLY plan machinery plan-off is entitled to.
        # The moment the current item IS the raw task (the reading step verified, or was never
        # authored and a resume lands here), the session becomes the degenerate single-item drive —
        # raw-task framing, the plan-off off-ramps, no step cage. The flip is one-way and idempotent.
        if (sess.plan_off and not sess.synthetic
                and (cur := sess.plan.current()) is not None and cur.text == sess.plan.task):
            sess.synthetic = True
            rlog.emit("loop.plan_off_handback", id=sess.plan.id)

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
        return self._work(sess, session_key, body, rlog, rewritten=rewritten)

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
        if self._ctx.coder_role is not None:  # strip leaked reasoning from the coder's content when off
            _clean_completion(coder, self._ctx.coder_role)
        # Judge an outgoing web_search's query (off-target → a better query). Before the tracking, so the
        # repetition/write-streak guards see what's actually FORWARDED.
        coder = guard_search_query(sess, coder, body, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog)
        _track_fetched_pages(sess, body.get("messages", []))  # durable fetch facts for later steers
        if _has_tool_calls(coder):  # the coder ACTED → track the fingerprint for the repetition/spin guards
            guard_track_repetition(sess, coder, rlog, step=step,
                                   messages=body.get("messages"))
            guard_track_write_streak(sess, coder, rlog, step=step, messages=framed.get("messages"))
        return coder

    def _work(self, sess: PlanSession, key: str, body: dict, rlog, rewritten: bool = False) -> dict:
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
            # OBJECTIVE completion backstop (parity with BOTH plan-off done paths, which always run
            # guard_gate_op before ending). Not every route here verified its steps: a replan can
            # return [] and empty the tail on the satisfaction judge's word alone — walked on
            # ada-handles_ternary-bonsai_codex_poff_1785818931, where that route exited 3/4 with the
            # repo's checks NEVER run (5 unit tests failing on disk, three LLM judges approving).
            # `gate_fresh` (a gate result read since the coder last acted) is what a normally-
            # completing plan already has from its final step's verification, so the healthy path
            # emits no duplicate probe; the judgment-only routes get ground truth before the end.
            if sess.completion_probe_id:  # the backstop's OWN probe has now run — read it before judging
                # A harness compaction can erase the probe's result between emit and read; that is a
                # LOST result, not a declined one — re-issue rather than fail open (parity with
                # guard_probe_reissue on the other two probe readers; audited 2026-08-04).
                if (not _read_tool_result(body.get("messages", []), sess.completion_probe_id).strip()
                        and rewritten and sess.probe_reissues < MAX_PROBE_REISSUES):
                    probe_tc = guard_gate_op(sess, body, rlog, workspace_root=sess.workspace_root)
                    if probe_tc is not None:
                        sess.probe_reissues += 1
                        sess.completion_probe_id = sess.probe_call_id = probe_tc["id"]
                        rlog.emit("loop.probe_reissued", plan_off=False, attempt=sess.probe_reissues)
                        return _completion_toolcalls([probe_tc], note="re-running checks (history was compacted)")
                sess.probe_call_id, sess.completion_probe_id = sess.completion_probe_id, ""
                sess.probe_reissues = 0
                errors = guard_gate_verdict(sess, body, rlog)
                if errors:
                    # RED is ground truth about the repo — the task cannot complete over failing
                    # checks. Reopen with the ONE reused corrective step; the findings ride in the
                    # nudge (the channel built for them), never as a plan-step essay.
                    sess.completion_gate_reds += 1
                    fix = PlanItem(text=_COMPLETION_FIX_PREFIX + "make the repo's own checks pass")
                    if (sess.plan.items and sess.plan.items[-1].text.startswith(_COMPLETION_FIX_PREFIX)
                            and not sess.plan.items[-1].done):  # a DONE corrective step is history, not a slot
                        sess.plan.items[-1] = fix
                    else:
                        sess.plan.items.append(fix)
                    sess.plan.status = "in_progress"
                    self._persist_plan(sess.plan, rlog)
                    rlog.emit("loop.gate", plan_off=False, at="completion", blocked=True,
                              reds=sess.completion_gate_reds)
                    sess.steer_source = "completion gate (repo checks failed)"
                    return self._renudge(sess, key, body,
                                         prompts.render("gate_fail_steer", errors=errors), rlog)
            elif not sess.gate_fresh:
                probe_tc = guard_gate_op(sess, body, rlog, workspace_root=sess.workspace_root)
                if probe_tc is not None:
                    sess.completion_probe_id = sess.probe_call_id = probe_tc["id"]
                    rlog.emit("loop.completion_probe", plan_off=False)
                    return _completion_toolcalls([probe_tc], note="verifying — running the repo's checks")
                # no shell tool → the objective gate can't run; the judge below decides alone (fail-open)
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
        ev = _satisfaction_evidence(body.get("messages", []), rlog=rlog,
                     chat_fn=self._reasoner()[0], role=self._reasoner()[1],
                     gate_plan=getattr(sess, "gate_plan", None))
        ev += _gate_notes(sess)
        # RUN THE DELIVERABLE. The repo's own checks prove a workspace compiles, lints and passes its
        # tests; none of that can tell you the delivered program does anything. This check existed and
        # was wired only into _periodic_satisfaction — so the plan-ON path, where a session ends because
        # every STEP verified, never ran what it was shipping. Judges twice wrote "Let me run it" into
        # their reasoning and structurally could not. The marker is EVIDENCE, never a gate, and is empty
        # on a confirmed run or a task that needs no run, so a clean signal stays silent.
        exec_marker = live_execution_marker(sess, body, task, self._ctx.reasoner_chat,
                                            self._ctx.reasoner_role, rlog)
        if exec_marker:
            ev += "\n\n" + exec_marker
        satisfied, reason, fix_action = judge_satisfaction(task, ev, self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                               rlog, coder_tools=_coder_tools_summary(body.get("tools"), params=False),
                                               workspace_root=sess.workspace_root or "",
                                               routes=known_routes(body.get("messages", []), sess),
                                               gate_findings=getattr(sess, "last_gate_flag", "") or "")
        rlog.emit("loop.done_critic", plan_off=False, satisfied=satisfied, check=sess.completion_checks)
        if satisfied:
            return None
        sess.completion_checks += 1
        reason = reason or prompts.load("done_no_named_gap")
        # The STEP is the judge's proposed ACTION, not its verdict essay: the old framing+reason+fix
        # paragraph became a step verbatim and pinned a run for 118 calls (0729-mellum2) — carrying
        # literal {{…}} braces the coder shipped into a URL, and "or fallback on…" advice. The essay
        # still reaches the coder through the nudge below; the plan gets only something DOABLE. And
        # a judge-authored step is NOT exempt from the noise scrub every other authored step passes
        # (operator: the model may author steps; cria's routing must apply the same quality bar).
        # NO ACTION, NO STEP. The comment above states the rule — "the plan gets only something
        # DOABLE" — and `or reason` broke it: with no proposed_fix, the judge's VERDICT ESSAY became
        # the plan step, which is the exact shape that pinned a run for 118 calls. Measured over the
        # 19 distinct corrective steps in the captures, 2 are essays; one of them is
        # "So the task is NOT satisfied because: 1. resolve_handle.py … are not in the workspace",
        # appended as a step in the same prompt where cria's own disk read listed those files as
        # present. The essay still reaches the coder — through `nudge_reason` below, which is the
        # channel built for it.
        step_text = fix_action
        try:
            noisy = reasoned_noise_indices(
                lambda sysm, userm: summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                              sysm, userm, rlog, phase="reasoner") or "",
                task, [step_text] if step_text else [],
                facts=session_research_facts(body.get("messages", []), sess))
        except Exception:  # noqa: BLE001 — the scrub is advisory; never lose the corrective step to a crash
            noisy = set()
        if not step_text:
            rlog.emit("loop.completion_fix_absent", level="info", head=_clip(reason, 120))
        elif 0 in noisy:
            rlog.emit("loop.completion_fix_noise", level="info", head=_clip(step_text, 120))
        else:
            fix = PlanItem(text=_COMPLETION_FIX_PREFIX + step_text)
            if (sess.plan.items and sess.plan.items[-1].text.startswith(_COMPLETION_FIX_PREFIX)
                    and not sess.plan.items[-1].done):  # a DONE corrective step is history, not a slot
                sess.plan.items[-1] = fix      # reuse the one corrective step across re-checks (no plan bloat)
            else:
                sess.plan.items.append(fix)
        sess.plan.status = "in_progress"
        sess.nudge_reason = prompts.render("done_incomplete", reason=reason,
                                           check_state=_check_state_words(sess),
                                           exec_finding=_exec_finding_line(sess))
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
        sess.drive_count += 1  # session-wide drive counter
        # PERIODIC ground-truth check-in WITHIN a long step (M2 parity with the plan-off driver): every
        # GATE_EVERY_CODER_TURNS acting turns, run the repo's checks so a step that edits many DIFFERENT
        # things for dozens of turns (never spiraling, never claiming done) still gets ground truth — the
        # exact case the per-step gate + wheel-spin detectors miss. Only when nothing else steers this turn.
        if not sess.nudge_reason:
            periodic = guard_periodic_gate(sess, body, rlog, workspace_root=sess.workspace_root)
            if periodic is not None:
                return periodic
        # PERIODIC READING CHECK. A step that asks for research has no way to declare itself finished
        # except through the step critic reading the transcript, and when the step names a source that
        # cannot be reached the critic is right to refuse it forever: run 1785804243 spent 114 of its
        # 195 calls on "Research the Ada Handles API documentation by fetching the GitHub repo root
        # directory" and never reached step 2. Every RESEARCH_CHECK_EVERY acting turns, ask one focused
        # question against what cria has really parsed — and when the reading this step wanted is
        # already in hand, complete it and move on. Grounded in the fetch ledger, so it cannot clear a
        # step on a claim: with no parsed routes and no parsed fields it answers NOT_DONE without
        # calling the model at all (cria.research).
        advanced = self._research_check(sess, key, body, idx, total, rlog)
        if advanced is not None:
            return advanced
        # PERIODIC STEP CHECK. The research check above can only clear a READING step; a build step
        # still moves only when the coder volunteers "done". Ask the real critic on a cadence so a
        # step cannot outlive the run (see the method — additive, fail-closed, same authority).
        advanced = self._periodic_step_check(sess, key, body, idx, total, rlog)
        if advanced is not None:
            return advanced
        # PERIODIC SATISFACTION CHECK on the PLAN-ON path. It lived only on the single-item driver
        # until 2026-08-01, which is the path that needed it least: plan-off already ends the moment
        # the coder says done. With a plan, the session ends only when every STEP verifies — so a
        # plan naming files the task never asked for can hold a FINISHED task open for its whole
        # budget. Measured on ada-handles_nemotron-elastic_codex_pon_1785629694: 145 driven turns,
        # all four deliverables complete and hand-verified at 15 minutes, 15 step_incomplete events,
        # and zero satisfaction checks where four were due.
        done_now = self._periodic_satisfaction(
            sess, body, rlog, plan_off=False,
            blocked=bool(sess.nudge_reason or sess.done_probe or sess.last_gate_red))
        if done_now is not None:
            return done_now
        framed = dict(body)
        framed.pop("model", None)  # no alias — the upstream fills the server's loaded model
        framed["stream"] = False
        msgs = _frame_for_item(body.get("messages", []), item.text, sess.summary, idx, total,
                               prior_work=sess.prior_work, tools=body.get("tools"),
                               gate_plan=getattr(sess, "gate_plan", None),
                               workspace_root=sess.workspace_root,
                               gate_red=bool(getattr(sess, "last_gate_red", False)))
        facts = _fetched_facts_anchor(sess, body.get("messages", []))  # durable fetch ledger → the coder keeps the real endpoints it
        if facts is not None:                # already fetched past a HARNESS compaction (re-injected from
            msgs = _insert_after_system(msgs, facts)  # cria's own memory), so it stops re-fetching to rediscover
            msgs = _elide_ledger_copies(msgs, sess, rlog)  # the anchor is the ONE copy — duplicates collapse
        steered = ""
        if sess.nudge_reason:  # re-driving after a failed check → tell the coder what's still wrong
            if sess.nudge_reply:  # the reply the nudge refers to rides in front of it, as itself
                msgs = msgs + [{"role": "assistant", "content": sess.nudge_reply}]
                sess.nudge_reply = ""
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
            sess.gate_fresh = False    # the workspace may change → any prior gate result is stale
            thrash = self._replan_if_thrashing(sess, key, body, idx, rlog)  # tool-call thrash escape
            if thrash is not None:
                return thrash
            return coder  # coder is acting → forward; the harness runs it, then loops back here

        # coder produced no tool call → it thinks the step is done.
        # …unless cria ATE the call. massage recovers a tool call the model left in its reasoning
        # channel, and refuses the span when a name is not on the menu — correctly, since a call to
        # a tool that does not exist cannot be forwarded. What it used to do next was nothing: the
        # turn went back empty, the model read its own action as having produced no result, and this
        # branch read the same empty turn as a completion claim and spent a gate and a judge on a
        # workspace where nothing had happened.
        #
        # A lost turn is not a finish. cria owns the menu, so naming the tool that does not exist —
        # and the ones that do — is a fact it can state (#5b). Same shape as unexecuted_write below:
        # refusing to draw a conclusion the evidence contradicts, not a new assist.
        lost = coder.pop(massage.LOST_CALL_KEY, None)
        if lost and sess.unexecuted_nudges < MAX_UNEXECUTED_NUDGES:
            sess.unexecuted_nudges += 1
            rlog.emit("loop.lost_call_offmenu", step=idx, tried=lost.get("tried"),
                      attempt=sess.unexecuted_nudges)
            sess.nudge_reply = ""
            return self._renudge(sess, key, body, denial.mark(prompts.render(
                "lost_call_offmenu",
                tried=", ".join(f"`{n}`" for n in lost.get("tried") or ["a tool"]),
                menu=", ".join(lost.get("menu") or []) or "(none)")), rlog)
        # LEG 0 (ported from codex-local's completion gate): a "done" with ZERO tool calls this
        # step did nothing — nudge it to act before spending probe round-trips. (codex-local's
        # leg counts FILES MODIFIED in the active turn; cria's steps legitimately include
        # verification-only work, so the cria adaptation counts ANY tool activity this step.)
        # BEFORE reading this as a completion claim: a turn that pasted a whole file did not finish
        # the step, it failed to emit the call. See unexecuted_write().
        # NOT ON A READING STEP. This nudge exists for the turn that PASTED a file instead of
        # writing it — and a reading step produces no files, by its own prompt's words. Walked on
        # cycle 4 cell 18 (`rust-toml-cli x ternary-bonsai`): the coder's research summary quoted
        # fifteen lines of the crate API it had just fetched, and cria answered "your last message
        # contained the file's contents as text, but no write tool call was made, so nothing reached
        # the disk" — over a turn that drafted no file, two calls after cria's own tool results said
        # `Wrote .../Cargo.toml` and `Wrote .../src/main.rs`. That was the run's ONLY tool-call-less
        # coder turn, its one chance to be judged and advanced, and it was spent on `read_file` to
        # check cria's claim.
        #
        # The self-quote exemption cannot reach this: the coder did not COPY the page, it wrote its
        # own summary with its own comments interleaved with lifted lines, so whitespace-normalised
        # containment can never match — and loosening that to line-level would silence the nudge on
        # exactly the turns it earns its keep, where a model retypes a file it has just read. The
        # deterministic fact cria already holds is the better test (#8).
        if (not _is_reading_step(sess, sess.plan.current())
                and unexecuted_write(_completion_text(coder),
                                     _injected_fence_texts(sess, body.get("messages", [])))
                and sess.unexecuted_nudges < MAX_UNEXECUTED_NUDGES):
            sess.unexecuted_nudges += 1
            rlog.emit("loop.unexecuted_write", step=idx, attempt=sess.unexecuted_nudges)
            # The nudge says "send that same content again" — so the content must be IN the frame.
            # The re-framed view rebuilds from the harness body, which never saw this internal prose
            # turn; without the reply the model is ordered to resend text it cannot see.
            # …unless it was CUT OFF, in which case carrying it is the worse lie: "send that same
            # content again as a write tool call" over a fragment asks for a COMPLETE write of
            # incomplete content, and guard_truncation cannot catch that one — the tool call would
            # be whole, only its payload short (the self-truncated-write footgun, from the other
            # end). Measured: the truncated replies are also the two largest ever carried
            # (15,044 and 33,638 est tokens), so skipping them removes the size risk with the lie.
            sess.nudge_reply = "" if massage.is_truncated(coder) else _completion_text(coder)
            return self._renudge(sess, key, body, prompts.load("unexecuted_write_nudge"), rlog)
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
        evidence = self._grounded_evidence(sess, body, rlog)
        ok, reason = self._verify(item.text, _completion_text(coder), "", evidence, rlog, idx=idx, total=total, key=key,
                                  coder_tools=_coder_tools_summary(body.get("tools")),
                                  routes=known_routes(body.get('messages', []), sess),
                                  sources_read=research.sources_read(
                                      _extract_fetches(body.get('messages', [])), body.get('messages', [])),
                                  workspace_root=sess.workspace_root or "",
                                  gate_red=bool(sess.last_gate_red))
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
                q_of[_search_key(mm.group(2))] = mm.group(1)
        out: list[dict] = []
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "tool" and read_file_of.get(m.get("tool_call_id")):
                f = read_file_of[m.get("tool_call_id")]
                key = "content" if m.get("content") is not None else "output"
                if _search_key(f) not in sess.judged_search_files:
                    sess.judged_search_files.add(_search_key(f))
                    # Judge the REAL results off disk — NOT the tool result, which for a spilled file is
                    # cria's own "grep this instead" steer. Handing the judge that envelope and asking
                    # "are the RESULTS on target?" gets a false for a search that was perfectly on target,
                    # and a definite false DELETES it. Unreadable → judge nothing, strip nothing (the file
                    # stays marked judged, so this can never become a per-turn reasoner call either).
                    results = search_file_text(sess.workspace_root, f)
                    _q, r_ok, rec = judge_search(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                                 latest_user_text(msgs), q_of.get(_search_key(f), ""), results, rlog,
                                                 coder_tools=_coder_tools_summary(body.get("tools")))
                    # DETERMINISTIC VETO over a destructive fuzzy verdict. Ruling the results
                    # off-target DENIES the coder a file that is still on disk, permanently, on one
                    # judgment call. Twice now that judgment has been wrong on this task and thrown
                    # away the answer: on run 1785686596 the judge was asked about a query cria had
                    # mangled to "(none)", and on run 1785714194 it had a clean query and STILL ruled
                    # false while its own prompt carried a link described as "documentation on how to
                    # resolve handles to addresses and get all handles by address", plus the official
                    # api.handle.me swagger. The model gave up searching in the next turn.
                    #
                    # If the results name a host the TASK ITSELF names, they are on-target by
                    # construction and no verdict can make them otherwise. That is exact — cria holds
                    # both strings — and it only ever REFUSES a deletion, never causes one.
                    if not r_ok and _results_name_the_tasks_host(latest_user_text(msgs), results):
                        rlog.emit("loop.search_poison_refused", level="info", file=f)
                        r_ok = True
                    if not r_ok:
                        sess.poisoned_search_files.add(_search_key(f))
                        sess.search_recommend = rec
                        rlog.emit("loop.search_read_poison", file=f, rec=rec)
                if _search_key(f) in sess.poisoned_search_files:
                    # Marker-tagged and prompt-file-sourced: this note is cria's OWN voice written back
                    # into the message stream, so it must be identifiable — the work log and the critic
                    # were reading it as something the coder's tool returned.
                    #
                    # It carries the SHARED did-not-run mark (cria.denial), not a private one. This
                    # denial is the same species as every refusal writeproxy lowers — the read did not
                    # happen and these are cria's words in its place — and a marker of its own bought
                    # only a second thing to keep in sync. The work log used to DELETE this note for
                    # being cria's voice, which left the critic a `$ read_file …` call with no result
                    # line at all: a call that looks like it returned nothing, on a file that is still
                    # on disk. Measured 2026-08-03: 229 coder turns across 9 runs. Labelled now, not
                    # deleted (#2 — never destroy, disclose).
                    steer = f" Search instead for: {sess.search_recommend}." if sess.search_recommend else ""
                    out.append({**m, key: prompts.render("search_read_denied",
                                                         marker=denial.DENIED_MARKER, steer=steer, file=f)})
                    continue
            out.append(m)
        return out

    def _self_compact(self, msgs: list[dict], sess: PlanSession, idx, rlog, *, force: bool = False,
                      pinned_task: str | None = None) -> list[dict]:
        """THE self-compaction — one owner for BOTH drivers. Rolls the old work-history middle into a
        ⟦ctx:rollup⟧ summary via the shared summarize primitive. Orthogonal to sess.summary (the cheap
        completed-STEP axis in the protected system message). ``force`` (set at a step boundary)
        compacts now even below the size trigger, to clear the prior step's signals. ``pinned_task``
        overrides the plan's task — the plan-off driver pins the conversation ROOT task, detected from
        the raw body where env-context detection still works.

        There were two of these, and merging them fixed two more sibling misses on the spot: the
        plan-ON copy sent its summarize to ``reasoner_chat`` while selecting the COMPACTOR role (so a
        configured compactor endpoint was ignored on that path), and the plan-OFF copy never appended
        ``_briefing_gate_ground_truth`` — the override that stops a rollup laundering an unverified
        "the tests pass" past cria's real last check state. Each had a piece the other needed. That is
        what having two of something costs, every time."""
        out, sess.compact_state, applied = selfcompact.compact(
            msgs,
            # Ground the reasoner's summary in cria's REAL last check state — so a summary that launders
            # an unverified 'tests pass' claim is overridden by what the checks actually reported.
            lambda mm: _briefing_disk_truth(summarize(
                                 self._ctx.compactor_chat or self._ctx.reasoner_chat,
                                 self._ctx.compactor_role or self._ctx.reasoner_role,
                                 prompts.load("selfcompact_summary"),
                                 # CRIA'S ASK GOES LAST. Without it the transcript ends on the
                                 # coder's own step ("Do ONLY this step (2 of 4)... Write
                                 # test_resolve_handle.py") and the compactor obeys THAT instead of
                                 # summarizing: on ada-handles_mellum2_codex_pon_1785628543 call 25 it
                                 # emitted `write_file({"path": ...` and degenerated to `v5v5v5…`
                                 # until the cap, and call 26 produced a whole unittest file. cria
                                 # adopted it as "⟦ctx:rollup⟧ Summary of your earlier turns this
                                 # session" — a file that had never been written and was not on disk.
                                 # The coder believed it ("The user has given me a test suite"), and
                                 # that is where unittest entered a pytest run.
                                 # This is the SAME fix as da35f4e, which landed on the harness path
                                 # (server.py) and never reached its sibling here.
                                 selfcompact.compaction_request(
                                     mm,
                                     # …AND THE DISK. This inventory was already gathered on
                                     # the line below, but only to CORRECT the briefing after
                                     # the fact (_briefing_disk_truth, denial direction only).
                                     # The writer never saw it and invented files that never
                                     # existed. Same fact, given before the question.
                                     workspace_inventory(sess.workspace_root or "",
                                                         flavor="briefing"),
                                     # …and the gate plan, so the cleaner reports what the gate
                                     # actually found rather than its most forgiving branch.
                                     getattr(sess, "gate_plan", None)), rlog,
                                 phase="self-compact", max_tokens=ROLLUP_MAX_TOKENS),
                                 workspace_inventory(sess.workspace_root or "", flavor="coder"),
                                 rlog) + _briefing_gate_ground_truth(sess),
            sess.compact_state, trigger_tokens=self._ctx.trigger_compaction, force=force,
            # The task is a foldable history message in the plan frame (only the STEP is in the system
            # message). Pin it as a ⟦ctx:task⟧ anchor so a boundary fold — which keeps NO verbatim tail —
            # can't summarize the original requirements away.
            pinned_task=(pinned_task if pinned_task is not None else (getattr(sess.plan, "task", "") or "")),
            # The coder-flavored files list (operator's design): the compacted view carries the LIST
            # of what exists; read_file is the road back to any content.
            files_list=workspace_inventory(sess.workspace_root or "", flavor="coder"),
            # The RARE fold-of-the-accumulated-summary (see selfcompact REFOLD_TOKENS).
            refold=lambda text: summarize(self._ctx.compactor_chat or self._ctx.reasoner_chat,
                                          self._ctx.compactor_role or self._ctx.reasoner_role,
                                          prompts.load("selfcompact_refold"), text, rlog,
                                          phase="self-compact-refold", max_tokens=ROLLUP_MAX_TOKENS),
            rlog=rlog)
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
        outcome = read_gate(sess.gate_plan, probe, rlog)
        # Guard-probe result (repetition redirect / wheel-spin ground truth) — shared with the
        # plan-off path via guard_probe_steer; the loop supplies its reasoner to author the redirect.
        # It records the reading itself (record_gate_state) before returning, so this early return
        # no longer discards a gate that the guard happened to be reading on the same turn.
        steer = guard_probe_steer(sess, body, rlog, step=idx, author=self._probe_author)
        if steer is not None:
            return self._renudge(sess, key, body, steer, rlog)
        # The reading is state whichever way this turn goes. Captured BEFORE the mirror overwrites it,
        # because the stall signal is "the same finding as last time" and comparing the new flag with
        # itself is always true.
        prev_flag = sess.last_gate_flag
        record_gate_state(sess, outcome, gate_error_text(outcome))
        if not outcome.ran:
            # The script never ran (harness declined / no markers). Don't wedge — the pre-existing
            # fail-open: the critic still judges, told explicitly that no diagnostics ran.
            rlog.emit("loop.probe", step=idx, passed=True, gate_ran=False)
            digest = prompts.load("probe_digest_none")
            evidence = self._grounded_evidence(sess, body, rlog)
            ok, reason = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key,
                                      coder_tools=_coder_tools_summary(body.get("tools")),
                                      routes=known_routes(body.get('messages', []), sess),
                                  sources_read=research.sources_read(
                                      _extract_fetches(body.get('messages', [])), body.get('messages', [])),
                                      workspace_root=sess.workspace_root or "",
                                      gate_red=bool(sess.last_gate_red))
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
        if nudge and nudge == prev_flag:
            rlog.emit("loop.gate_stalled", level="warning", step=idx)
        # OSCILLATION: this exact finding-set has been here before, with a different one in between.
        # Two errors that are each other's cause — clearing A re-creates B — and every individual fix
        # is locally correct, so nothing else in cria can see it. Walked on
        # ada-handles_mellum2_codex_pon_1785628543: "fixture 'self' not found" and "undefined name
        # 'self'" traded places for 18 targeted edits, each right for the error it was shown.
        sig = (nudge or "").strip()
        if sig:
            prior = sess.gate_signatures
            if sig in prior and prior[-1] != sig:   # seen before, but NOT immediately before
                rlog.emit("loop.gate_oscillating", level="warn", step=idx,
                          states=len(set(prior)), head=_clip(sig, 100))
                sess.oscillation_note = prompts.load("gate_oscillating")
            if not prior or prior[-1] != sig:
                prior.append(sig)
                del prior[:-GATE_SIGNATURE_WINDOW]
        sess.gate_git = outcome.git_state
        # The plan-ON extras on top of the shared mirror (record_gate_state, called above with the
        # reading): the repo-wide regression check, which needs the report and only makes sense on a
        # gate that came back GREEN.
        if not sess.last_gate_red and (lost := passing_test_regression(sess, outcome.report)):
            sess.nudge_reason = sess.nudge_reason or lost
            rlog.emit("loop.tests_regressed", level="warning", step=idx,
                      high=sess.tests_passed_high)
        rlog.emit("loop.probe", step=idx, passed=nudge is None)

        # A RED gate is GROUND TRUTH about the REPOSITORY — it is not, by itself, a verdict on THIS
        # step, and it used to `return` right here, before the critic ever ran. The gate is repo-wide,
        # so one failing pytest held EVERY step of the plan, including steps that write no executable
        # code at all. Measured over the seven captured log-days: 872 red-gate holds across 64
        # step-positions in 40 sessions; 27 of those step-positions (167 holds) never received a
        # single critic verdict. Reading all 64 step texts, ~190 of the holds sit on READMEs,
        # requirements.txt / pyproject.toml, and pure read/confirm research steps — none of which can
        # make pytest green. Walked on ada-handles_fabliq_codex_pon_1785721353: step 1, "Read the Ada
        # Handles API documentation", held nine times by a red pytest whose fix was steps 3 and 4,
        # sitting BEHIND it. Perfect deadlock — 267 calls, the plan never left step 1, the last critic
        # call in the run was 0060, and the two deliverables that were never reached do not exist.
        #
        # WHOSE failure is this? is a judgment, and nothing in probegate/proberun attributes a finding
        # to a step. So it goes to the critic (principle 8; #9's corollary — the rule that would need
        # an exception list is the rule that should have been a question), which ALREADY carries the
        # rule verbatim — "Ignore failures NOT related to this step's goal" — and structurally never
        # got to apply it. It is handed the checker's own lines WITHOUT the coder-facing "resolve
        # exactly what it names" preamble (proberun.block_findings), because an imperative reads as a
        # task briefing to a weak judge.
        #
        # SAFE DIRECTION, both ways it can be wrong:
        #  * critic wrongly NOT-done → byte-identical to the old behaviour. No regression exists.
        #  * critic wrongly DONE → ONE step advances. `last_gate_red` is set above and STAYS set, so
        #    _periodic_satisfaction is still blocked from proposing a finish, _gate_notes hands the red
        #    findings to the completion judge, _repair_note keeps restating the failure, and the gate
        #    re-runs on the next completion claim. The run cannot COMPLETE while red.
        # Principle 13 governs declaring the TASK done; advancing one step of a plan is not that, and
        # the task-level judges stay fail-closed. Today's wrong hold, by contrast, has no recovery at
        # all — the plan can never reach the step that would fix the checks.
        red_findings = proberun.block_findings(outcome.report) if nudge is not None else None

        digest = proberun.completion_probe_digest(outcome.report, missing=outcome.unran)
        evidence = self._grounded_evidence(sess, body, rlog)
        ok, reason = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key,
                                  coder_tools=_coder_tools_summary(body.get("tools")),
                                  routes=known_routes(body.get('messages', []), sess),
                                  sources_read=research.sources_read(
                                      _extract_fetches(body.get('messages', [])), body.get('messages', [])),
                                  workspace_root=sess.workspace_root or "",
                                  red_findings=red_findings or "",  # grounded in the coder's own runs
                                  gate_red=bool(sess.last_gate_red))
        if nudge is not None:
            if ok:
                # The critic read the findings and ruled they are not this step's goal. Loud by
                # design: this is the one place a step moves while the repo is red, so the record must
                # say so and carry the reason a human can audit.
                rlog.emit("loop.gate_red_advance", level="warn", step=idx,
                          findings=_clip(red_findings or "", 200), reason=_clip(reason, 200))
                return self._advance(sess, key, body, idx, total, rlog)
            sess.verify_fails += 1
            # critic_fails is deliberately NOT incremented here, and this stays on plain _renudge:
            # a red gate must never drive the stuck-step rescue (see PlanSession.critic_fails — run
            # 0727-170754, where the rescue rewrote "Write unit tests…" into "Add retry logic…" and
            # then failed the coder's in-flight test work against a goal it was never given), which
            # is the contract _renudge_or_replan states in its own docstring.
            rlog.emit("loop.step_incomplete", step=idx, reason="probe failed", attempt=sess.verify_fails)
            # The CHECKER's own errors go to the coder, not the critic's prose — the ground truth is
            # the repairable signal, and it is what the old short-circuit already delivered.
            return self._renudge(sess, key, body, nudge, rlog)

        if ok:  # advance ONLY on a genuine pass — no fail cap
            return self._advance(sess, key, body, idx, total, rlog)
        sess.verify_fails += 1
        sess.critic_fails += 1
        rlog.emit("loop.step_incomplete", step=idx, reason=reason, attempt=sess.verify_fails)
        return self._renudge_or_replan(sess, key, body, reason, idx, rlog)  # critic fail → may re-derive a stuck step

    def _periodic_step_check(self, sess: PlanSession, key: str, body: dict, idx: int, total: int, rlog):
        """Every STEP_CHECK_EVERY acting turns, ask THE STEP CRITIC whether the open step is done.

        A step advances only when the CODER volunteers that it is finished — `_verify` runs on
        `pending_coder_text`, i.e. a turn with no tool call, or `task_complete`. A coder that keeps
        calling tools never volunteers, so the step is immortal and the plan cannot move. Walked
        twice: 1785360304 held "step 1 of 7" for 107 injections and its critic did not run once in
        the final 46 turns — nothing existed that COULD release it, and the run hit the wall clock
        still on step 1; 1785888803 held step 6 from call 0174 past 0215 the same way. MEASURED
        box-wide: 74% of all coder calls sit inside a stretch of 30+ turns with no critic call at all.

        THIS IS NOT A SECOND COMPLETION AUTHORITY — that mistake is documented in `_research_check`
        below, where a workspace-blind judge marked six build steps done in three minutes and turned
        a 1.0 into a 0.0. This calls the SAME `_verify` every completion claim goes through: the same
        critic, reading the same workspace inventory and the same check state, behind the same
        `_confirm_completion` brake. The only thing that changes is WHO asked — cria's own
        bookkeeping instead of the model's say-so.

        ADDITIVE, and currently OBSERVE-ONLY: it asks the question and records the answer, and
        NOTHING changes either way — no advance, no steer, no nudge, no fail counter, no word to the
        coder. The measurement it produces is what decides whether it ever gets to advance a step;
        see the note at the bottom of the method for exactly what flips it."""
        if sess.coder_turns <= 0 or sess.coder_turns % STEP_CHECK_EVERY:
            return None
        if sess.step_checked_turn == sess.coder_turns:
            return None   # the driver recurses without advancing coder_turns — once per tick
        sess.step_checked_turn = sess.coder_turns
        item = sess.plan.current()
        if item is None or item.done:
            return None
        msgs = body.get("messages", [])
        # DO NOT TELL THE JUDGE NO CHECKS RAN WHEN THEY DID. This path composes no gate of its own,
        # and it used to say so by handing the critic `probe_digest_none` — two lines that assert
        # "SYNTAX FLOOR: did not run" and "PROBES: none ran". Walked on cycle 4 cell 18
        # (`rust-toml-cli x ternary-bonsai`): two calls earlier cria had handed a reasoner four red
        # cargo failures under "GROUND TRUTH FROM THE REPO'S CHECKS" — `src/main.rs:31: type
        # annotations needed`, from clippy, check and test alike — and this judge was told, in the
        # same session, that the repo's checks did not exist. Two judges, two calls apart, opposite
        # ground truth; whichever one is wrong, cria said it (#5b).
        #
        # Composing no gate is not the same fact as no gate having run. When the session holds a
        # reading, pass the reading: `last_gate_flag` is the finding-set every gate reader persists,
        # and the `probe_red` slot is what carries it into the critic's prompt.
        findings = (getattr(sess, "last_gate_flag", "") or "").strip()
        ok, reason = self._verify(
            item.text, prompts.load("periodic_step_claim"),
            prompts.load("probe_digest_none") if not sess.last_gate_ran else "",
            self._grounded_evidence(sess, body, rlog), rlog, idx=idx, total=total, key=key,
            coder_tools=_coder_tools_summary(body.get("tools")),
            routes=known_routes(msgs, sess),
            sources_read=research.sources_read(_extract_fetches(msgs), msgs),
            workspace_root=sess.workspace_root or "",
            red_findings=findings if sess.last_gate_red else "",
            gate_red=bool(sess.last_gate_red))
        # SAY WHAT IT DID, always — the lesson _research_check records: a guard that is silent when it
        # declines cannot be told apart from one that never ran.
        rlog.emit("loop.periodic_step_check", step=idx, done=bool(ok), turns=sess.coder_turns,
                  reason=_clip(reason or "", 160))
        # OBSERVE-ONLY (operator, 2026-08-05: "I'm not too comfortable with #16"). It ASKS and it
        # RECORDS; it does not advance. The reasoning is the same one that governs the dictated-code
        # guard beside it: this is new authority over when a plan MOVES, its documented predecessor
        # turned a 1.0 into a 0.0. A guard earns power on evidence, not on argument.
        #
        # STALE PREMISE, CORRECTED 2026-08-16 — this used to add "it has never executed live: both
        # runs on this code state were plan-off, where this path does not exist". Route-unify made
        # plan-off a synthetic one-item plan, so the path DOES exist there and has now executed.
        # cart-billing-go x ternary-bonsai, 14:23:19, three and a half minutes in:
        #   loop.periodic_step_check  step=1 done=true  reason="the go.mod file ... contains the
        #                                                       required content"
        #   loop.periodic_step_satisfied  observe_only=true  step_text="go.mod"
        # The critic was RIGHT and could not act, so the run spent 26 more minutes on a five-line
        # file and scored 1 of 5 on a workspace three edits from 4 of 5. That is one case, on the
        # plan-off path rather than the planner-ON runs the flip condition below asks for, and the
        # operator's discomfort was with the authority itself — so it is recorded here, not acted on.
        # The step that caused it is refused upstream now (research.step_defect's bare-location arm),
        # which removes this instance without granting the guard any new power.
        #
        # WHAT FLIPS IT: `loop.periodic_step_check done=true` events across real planner-ON runs,
        # each read against what the workspace actually held at that turn. If the critic is right
        # about a step the coder never claimed, drop this block and return `self._advance(...)`. If
        # it is wrong even once in a way the confirm brake did not catch, delete the whole method.
        # Until then the cost is one judge call per twelve turns and the risk is zero.
        if ok:
            rlog.emit("loop.periodic_step_satisfied", level="warn", step=idx, turns=sess.coder_turns,
                      observe_only=True, step_text=item.text[:160])
        return None

    def _research_check(self, sess: PlanSession, key: str, body: dict, idx: int, total: int, rlog):
        """Every ``RESEARCH_CHECK_EVERY`` acting turns: has the reading THIS step asks for been done?
        Returns the driven next turn when the step is complete, else None (the usual case).

        THE FACTS ARE GATHERED, NOT ASKED FOR. :func:`research.grounded_sources` reads cria's own
        fetch ledger and keeps only the documents that came back 2xx AND had routes or response
        fields parsed out of them. An empty list short-circuits to NOT_DONE with no model call — the
        guarantee that matters, because run 1785804243's ledger was five HTTP 200s that defined
        nothing ("this page answered, but no endpoint definitions were found in it") and a judge
        shown that could still have been talked into DONE.

        MOST STEPS ARE NOT RESEARCH and the verdict says so (NOT_RESEARCH), which costs one reasoner
        call per ten turns and changes nothing. That is the price of the one case it exists for; the
        alternative was a run spending its entire window on a step it could never satisfy.

        It only ever COMPLETES a step — it never fails one, never steers, and never speaks to the
        coder. A step it declines to clear is left exactly as it was, for the ordinary critic to
        judge (#13, and #2: the safe class of intervention is the additive one)."""
        # ONCE PER TICK. The driver recurses into the next item without advancing coder_turns, so a
        # modulo test alone re-fires for every remaining step inside one turn — that recursion is how
        # run 1785812224 walked six steps in under three minutes.
        if sess.coder_turns <= 0:
            return None
        if sess.research_checked_turn == sess.coder_turns:
            return None
        item = sess.plan.current()
        if item is None or item.done:
            return None
        msgs = body.get("messages", [])
        # A CADENCE WAS GATING A FACT. The trigger used to be `coder_turns % RESEARCH_CHECK_EVERY`
        # alone, so a step whose reading finished at turn 4 stayed pinned until turn 10. What it is
        # waiting for is deterministic and free — sources_read is a pure function of the ledger and
        # the message list — so the EVIDENCE decides when to look, and the clock only covers the
        # case where no new evidence ever arrives.
        #
        # Measured on ternary-bonsai's orders-api-py run: the step "read app.py and db.py" was
        # satisfied at coder call 4 and stayed the LAST user turn for seven consecutive turns,
        # telling a weak model to restart at "read and plan" after every finished piece of work.
        # Four byte-identical db.py writes and two identical app.py writes followed; those tripped
        # cria's own repetition detector, which fired six reasoner interventions, which
        # produced the rabbit hole that cost the run. 3/4 unaided became 2/4 assisted.
        #
        # Strictly ADDITIVE (#2): this can only make the check fire MORE often than before, and the
        # check only ever COMPLETES a step — it never fails one, never steers, never speaks to the
        # coder. Bounded by the evidence itself: the same set of sources is never judged twice, so a
        # step that reads nothing new costs nothing beyond the old cadence.
        ledger = _merge_fetches(_extract_fetches(msgs), (getattr(sess, "fetched_pages", None) or {}))
        sources = research.sources_read(ledger, msgs)
        # A PAGE THAT ANSWERED COUNTS AS EVIDENCE TO RE-ASK ON, even when nothing parsed out of it —
        # otherwise the fingerprint never moves for a docs-only reading step and the check declines
        # on cadence forever. See research.step_reading_verdict for the run this cost.
        fingerprint = tuple(sorted({s[0] for s in sources} | set(research.answered_sources(ledger))))
        evidence_changed = fingerprint != sess.research_evidence
        if not evidence_changed and sess.coder_turns % research.RESEARCH_CHECK_EVERY:
            return None
        sess.research_checked_turn = sess.coder_turns
        sess.research_evidence = fingerprint
        # THE DURABLE LEDGER, not just this window. `_extract_fetches` reads raw web_fetch TOOL
        # RESULTS, and those are the first thing compaction drops — so from the first compaction on,
        # this check saw zero sources and short-circuited to NOT_DONE with no model call, forever.
        # The step it exists to clear could then never clear. Measured on maple-preview 1786053138:
        # `research-check` ran 3 times across today's runs, every one `sources=0`, while the ledger
        # in the very same prompt carried `api.handle.me/openapi.json → HTTP 200` with
        # `resolved_addresses{ada}` parsed out of it — and the reading step stayed pinned for 27
        # consecutive turns. Every OTHER consumer of the ledger already merges sess.fetched_pages
        # (the steer author, the anchor composer, the judges); this one was the lone reader of the
        # window alone. The exit that justifies re-adding a research step at all was inert.
        # (`sources` is computed above, where the evidence also decides whether to look at all.)
        verdict = research.step_reading_verdict(
            lambda sysp, usr: summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                        sysp, usr, rlog, phase="research-check"),
            sess.plan.task, item.text, sources, ledger_urls=ledger)
        # SAY WHAT IT DID, always. A guard that is silent when it declines cannot be told apart from
        # one that never ran — and on this check's first live run that is exactly what happened: zero
        # events, and no way to know whether the cadence was never reached or the verdict was NOT_DONE
        # every time. The same lesson the replan noise judge already carries: a count is not a reading.
        rlog.emit("loop.research_check", step=idx, verdict=verdict, sources=len(sources),
                  turns=sess.coder_turns)
        # IT REPORTS. IT DOES NOT COMPLETE.
        #
        # This used to call _advance on a DONE, which made it a SECOND completion authority — one
        # that never looks at the workspace. On its first planner-on run (1785812224) that bypass
        # marked steps 1 through 6 verified in under three minutes, among them "Write a Python
        # script…", "Implement unit tests…" and "Create a live test…", with two files on disk and
        # nothing else built. The run scored 0.0 where the same task under plan-off scored 1.0: the
        # guard was worse than its absence.
        #
        # Two things went wrong and only one of them was the model. fabliq answered DONE for plainly
        # build-shaped steps, which NOT_RESEARCH exists to catch and did catch twice — a small model
        # on a three-way judgement is simply not a completion gate. But the design handed it that
        # power, and that is the defect: the step critic is the only thing here that reads the
        # workspace, and #13 says completion fails CLOSED. A check that cannot see whether a file was
        # written must never be what says a step producing a file is finished.
        #
        # What it is FOR survives intact: saying, in the log, whether the reading a step asked for has
        # actually happened — which is the fact nobody had when run 1785804243 spent 114 calls on an
        # unreachable research step. That fact now reaches the critic as EVIDENCE too (`_verify`'s
        # `sources_read=`), so the one authority that checks the workspace can act on it; this
        # comment used to call that "the next change", which it has not been for some time.
        if verdict == research.DONE:
            rlog.emit("loop.research_satisfied", step=idx, sources=len(sources),
                      turns=sess.coder_turns, step_text=item.text[:160])
            # PLAN-OFF HAND-BACK RIDER (operator contract 2026-08-04: plan-off gets a reading step
            # and NOTHING else of the plan machinery). The plan-off reading step is the one step
            # whose whole deliverable IS the ledger fact this check just verified — there is no
            # workspace artifact for a critic to weigh, and walked run 1785861503 shows what the
            # critic path costs instead: the reading was ledger-complete by call 12, the repo went
            # red on step-2 work, and weak critics then refused the reading step for 247 calls —
            # "Do ONLY this step (1 of 2)" recited ~30 times fed the very re-fetch compulsion the
            # framing was supposed to prevent, and the hand-back never fired. This is NOT the
            # 1785812224 second-completion-authority defect returning: that run marked BUILD steps
            # done on a planner-ON plan. Here the scope is plan-off only, the READING step only
            # (never the task item), on a DONE that structurally requires grounded sources — and
            # everything that produces files still answers to the gates on the raw-task drive this
            # advance hands back to.
            if _is_reading_step(sess, item):
                rlog.emit("loop.reading_step_cleared", step=idx, plan_off=True)
                return self._advance(sess, key, body, idx, total, rlog)
        return None

    def _advance(self, sess: PlanSession, key: str, body: dict, idx: int, total: int, rlog) -> dict:
        """Mark the current step VERIFIED (a step advances ONLY on a genuine critic pass — there is no
        accept-unverified), update cria's plan mirror, and move on.

        The bar is unchanged: the careful reasoning-ON critic, plus the on-disk _confirm_completion
        brake. What changed (see _verify_after_probe) is that a RED repo-wide gate is now EVIDENCE the
        critic weighs rather than a veto that skipped it — a step may advance while the checks are red
        IF the critic ruled the findings belong to another step's work. That is still a genuine pass;
        it is not a cap, a budget, or an accept-unverified."""
        item = sess.plan.current()
        item.done = True
        # A CLEAN status only — never the coder's raw output. The coder's text is unbounded prose (and
        # small models parrot cria's own banners back), which is what leaked "logs" into the plan file.
        item.note = "verified"
        sess.summary = _extend_summary(sess.summary, idx, item.text)
        sess.verify_fails = sess.critic_fails = 0
        sess.pending_coder_text = ""
        sess.step_tool_calls = 0   # fresh step, fresh did-real-work signal
        sess.unexecuted_nudges = 0
        sess.thrash_replanned = False  # a new step-position may earn its own one-shot thrash re-derive
        sess.verify_replanned = False  # ...and its own one-shot verify-fail re-derive
        sess.leg0_nudged = False
        sess.recent_writes, sess.spin_path = [], ""
        sess.spin_probe_due = False
        sess.recent_actions = []
        sess.redirect_due = False
        # Convergence tracking is per step — EXCEPT while the repo is still RED. This string is the
        # only carrier of the failing findings into cria's rolling briefing
        # (_briefing_gate_ground_truth reads exactly this field) and into the completion judge's
        # evidence (_gate_notes). A step may now advance over a red gate the critic attributed to
        # other work; clearing the findings there would make cria go quiet about a failure it is
        # still holding — the same silent-loss shape rule #5b exists to prevent.
        if not sess.last_gate_red:
            sess.last_gate_flag = ""
        sess.compact_pending = True  # a step just VERIFIED → force a rollup next turn so the completed
        #                              step's raw work-signals don't distract the next step (operator ask)
        rlog.emit("loop.step_done", step=idx, verified=True)
        if not sess.plan_off:  # plan-off's tail IS the user's task — never re-derived into steps
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
        evidence = self._grounded_evidence(sess, body, rlog)
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
            trigger=trigger, facts=session_research_facts(body.get("messages", []), sess))
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
        # The oscillation note rides WITH the re-nudge, never instead of it: the checker's own
        # findings stay first and whole, and this only adds the fact that they have recurred. It is
        # consumed on use so it appears once per detection, not on every subsequent turn.
        if getattr(sess, "oscillation_note", ""):
            reason = reason + "\n\n" + sess.oscillation_note
            sess.oscillation_note = ""
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
        if (self._ctx.reasoner_role is not None and not sess.synthetic and not sess.plan_off
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
        if (self._ctx.reasoner_role is None or sess.synthetic or sess.plan_off or sess.thrash_replanned
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

    def _reasoner(self):
        """``(chat_fn, role)`` for this Loop, or ``(None, None)``. The evidence builders take the
        reasoner so an oversized log can be SUMMARISED rather than clipped (#5's second exception);
        without one they carry the log whole, which is the same safe answer."""
        ctx = getattr(self, "_ctx", None)
        return (getattr(ctx, "reasoner_chat", None), getattr(ctx, "reasoner_role", None))

    def _grounded_evidence(self, sess: PlanSession, body: dict, rlog=None) -> str:
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
        log = _dedup_evidence(_work_log(messages, rlog=rlog,
                                        gate_plan=getattr(sess, "gate_plan", None)),
                              rlog=rlog, chat_fn=self._reasoner()[0], role=self._reasoner()[1])
        facts = _fetch_ground_truth(messages, sess, header=CODER_FETCH_HEADER)
        inventory = workspace_inventory(sess.workspace_root)
        return "\n\n".join(part for part in (log, facts, inventory) if part)

    def _verify(self, item: str, coder_text: str, probe: str, evidence: str, rlog,
                *, idx: int = 0, total: int = 0, key: str = "", coder_tools: str = "",
                routes: str = "", workspace_root: str = "", red_findings: str = "",
                gate_red: bool = False, sources_read: list | None = None) -> tuple[bool, str]:
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
        # A RED gate is EVIDENCE the critic weighs, not a veto that skips it — see _verify_after_probe
        # for the measurement. The checker's OWN lines, under a label that states the one thing the
        # findings cannot state for themselves: they are repo-wide, so they do not say whose step
        # broke them. Additive — nothing else in the prompt changes, and it is absent on a clean gate.
        if red_findings:
            parts.append(prompts.fill(labels["probe_red"], findings=red_findings))
        # The summary slot is a CLAIM, labeled as such — but unbounded it carried a measured 119KB
        # leaked edit_file blob into a 151KB critic prompt (0567-critic, run 0728T000013), 5x the
        # evidence budget in the same prompt. A leaked tool call is not a summary at all; a huge
        # summary keeps only its tail, disclosed.
        if massage.has_tool_call_leak(coder_text):
            coder_text = labels["summary_leak"]
        elif len(coder_text) > 8000:
            coder_text = (f"[{len(coder_text) - 8000:,} characters of the coder's summary elided — "
                          f"its most recent part follows]\n" + coder_text[-8000:])
        parts.append(prompts.fill(labels["summary"], coder_summary=coder_text))
        # The critic is reasoning about the coder's work — give it the coder's tools too, so a NOT-done
        # reason it writes back names an action the coder can actually take (blind to them, it can't).
        if coder_tools:
            parts.append(prompts.render("reasoner_coder_tools", tools=coder_tools))
        # LAST: the step again. It was stated once at the top, before ~10K of evidence; the coder's
        # summary that lands just above the verdict often narrates its own numbered plan, and the
        # judge anchors on that instead (measured: it named a file that existed only in the summary).
        # A quoted literal the step names that is absent from the artifact it names. Deterministic
        # fact, offered as evidence — the critic still judges (principle 8). Measured need: a critic
        # approved "resolve the handle 'goose' and 'papagoose'" against a file containing neither,
        # and said so in its own reason. See groundtruth.absent_step_literals.
        for artifact, missing in groundtruth.absent_step_literals(item, workspace_root):
            parts.append(prompts.fill(labels["absent_literals"], artifact=artifact,
                                      literals=", ".join(repr(m) for m in missing),
                                      them="it" if len(missing) == 1 else "them"))
        # WHAT HAS ACTUALLY BEEN READ, when anything has. The same shape as absent_step_literals
        # above: a deterministic fact cria gathered, handed to the critic, which still judges
        # (principle 8). This is the fact the critic did not have when it refused a research step
        # forever — run 1785804243 spent 114 of its 195 calls on "Research the Ada Handles API
        # documentation…" while the transcript held five HTTP 200s that defined nothing, and the
        # critic had no way to tell reading-that-succeeded from reading-that-failed. Only sources
        # that RETURNED something are here (research.sources_read): a page that answered and defined
        # nothing is not evidence that anything was learned. Absent entirely when nothing was read,
        # which is itself the honest state — cria says nothing rather than implying research happened.
        if sources_read:
            parts.append(prompts.fill(labels["sources_read"],
                                      sources=research._sources_block(sources_read)))
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
            # MEASURED AND DELIBERATELY NOT BUILT (2026-08-02): the mirror of the reasoning recovery in
            # _verdict — "the judge APPROVED but its own thinking says NOT done" — does not exist. Of
            # 493 captured critic calls, 264 approved with a readable verdict and 7 of those have a
            # negative ruling somewhere in the thinking. All 7 were read in full; every one is the
            # judge ARGUING ITSELF TO the approval it emitted, not contradicting it — the negative is
            # hypothetical ("maybe the step is not fully satisfied because they haven't verified the
            # fetched file … but they used web_fetch with the exact URL, that's sufficient") or about
            # a DIFFERENT scope ("the README is missing overall … but for THIS step: DONE"). Same for
            # the satisfaction judge: 2 of 88, both the same shape. A lexical read cannot tell a
            # considered-and-rejected objection from a real one, so overriding a verdict the judge
            # actually reached would be 0-for-9 on the evidence. The approve path's brake is
            # _confirm_completion, which asks a fresh question against fresh ground truth.
            #
            # The careful (reasoning-ON) pass is the ONLY one trusted to APPROVE a step done — it does
            # the verification a reasoning-off judge can't.
            done = bool(obj.get("done"))
            if done and workspace_root:
                # One focused question when the claim names no file and the repo isn't red — the
                # verb list this replaces was fuzzy-deterministic (operator, 2026-08-04); the ask
                # fails toward running the brake.
                off_role = (replace(self._ctx.reasoner_role, reasoning="off")
                            if self._ctx.reasoner_role is not None else None)
                applies_ask = (lambda sysm: summarize(self._ctx.reasoner_chat, off_role, sysm,
                                                      _ASK_USER_TURN,
                                                      rlog, phase="confirm-applies",
                                                      temperature=0.0) or "") \
                    if self._ctx.reasoner_role is not None else None
                if not _confirm_applies(item, red_findings, gate_red=gate_red,
                                        ask=applies_ask, rlog=rlog):
                    # A claim that promises nothing on disk, over a non-red repo, leaves the disk
                    # checker nothing it can legitimately inspect — measured coin-flip, and the
                    # walked run it cost. The careful critic pass already ruled.
                    pass
                else:
                    # The approve-path brake (see _confirm_completion): a DONE must be consistent with
                    # the FRESH on-disk listing and with its own stated reason.
                    confirmed, why = _confirm_completion(item, str(obj.get("reason") or ""), workspace_root,
                                                         self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                                         rlog, phase="critic-confirm")
                    rlog.emit("loop.done_confirm", step=idx, confirmed=confirmed)
                    if not confirmed:
                        done = False
                        obj = {**obj, "reason": why or str(obj.get("reason") or ""), "proposed_fix": ""}
            reason = _verdict_nudge(obj, done, routes, evidence=user,
                                    workspace_root=workspace_root, rlog=rlog)
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
            # Same fail-closed / plain-instruction contract as the satisfaction judge above.
            reason = prompts.load("unverified_step") + _named_gap(red_findings)
            _dump_verify(self._run_dir(rlog), key, idx, total, item, system, user, False, reason, response=raw)
            return False, reason
        reason = _verdict_nudge(retry, False, routes, evidence=user,   # reasoning-off NOT-done: trustworthy
                                workspace_root=workspace_root, rlog=rlog)
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
            # toolless pass → the system prompt's tool claim would be false; disclose it.
            system = system + "\n\n" + prompts.load("judge_toolless_note")
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
            obj = extract_json_object(vtext)
            if obj is not None:
                return obj, vtext
            # THE SAME RECOVERY THE SATISFACTION JUDGE HAS HAD SINCE 08-01, which this phase never got.
            # Measured 2026-08-02 over every captured step-critic call on this box (n=493, replayed
            # through cria's own reading path — extract_json_object then _fill_missing_verdict_flag):
            # 175 were unreadable, and 7 of those carry a clear NOT-done in the thinking cria threw
            # away. Four are one shape — the judge spent its inspection rounds calling tools and never
            # answered (finish_reason=tool_calls, content ""), e.g. "So the step 'Write a live test
            # that runs resolve_handle.py with handle goose' is not done — there is no test for
            # 'goose' in the file." What the coder got instead was `unverified_step`, a generic
            # keep-working line carrying none of that.
            #
            # ONE DIRECTION ONLY, and for the same reason given at verdict_from_reasoning: a recovered
            # NOT-done can only ever mean "keep working", so a false positive costs a turn and never a
            # false finish (principle 13). The mirror case was measured and DELIBERATELY not built —
            # see the note in _verify.
            ph = "critic" + ("-noreason" if reasoning_off else "")
            # ...and BEFORE that: the judge's own verdict object when one absent closing brace is
            # the only thing wrong with it (verdict_from_unclosed — 8 of this phase's replies on this
            # box, every one a NOT-done with a written proposed_fix). Same one direction, for the
            # same reason; it just recovers what the judge wrote instead of paraphrasing it. Mostly
            # this spares the reasoning-off retry below and lets the CAREFUL pass speak; twice in the
            # corpus both passes were unclosed and the coder read nothing at all.
            recover = ((lambda sysm: ask_closed(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                                sysm, rlog, phase=ph + "-recover"))
                        if self._ctx.reasoner_role is not None else None)
            return (verdict_from_unclosed(vtext, "done", rlog, ph)
                    or verdict_from_reasoning(_reasoning_of(comp), "done", rlog, ph, recover)
                    or verdict_from_reasoning(vtext, "done", rlog, ph + "-prose", recover)), vtext
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
        log = _work_log(body.get("messages", []), rlog=rlog,
                        gate_plan=getattr(sess, "gate_plan", None))
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

    def _periodic_satisfaction(self, sess, body: dict, rlog, *, plan_off: bool, blocked: bool):
        """The off-ramp for a session that has FINISHED the work but cannot stop. Returns a
        completion to send, or None to carry on.

        Ran on the plan-OFF path only until 2026-08-01, which is where it was needed least. Measured
        on ada-handles_nemotron-elastic_codex_pon_1785629694 (planner ON): 145 driven turns, all four
        deliverables verified complete and hand-checked at the 15-minute mark, and **zero**
        satisfaction checks — it should have fired at drives 80, 100, 120 and 140. With the planner
        on, a session ends only when every plan STEP verifies, so a plan that named files the task
        never asked for held a finished task open for the rest of its budget (15 step_incomplete
        events on work that was already done).

        `blocked` is the caller's own reason to stay quiet this turn — a steer is pending, the
        history was just rewritten, a done-probe is already in flight, or the gate is red. Gated on
        GREEN either way: cria never proposes ending a task while the repo's own checks fail.
        """
        if blocked or not satisfaction_check_due(
                sess.drive_count, self._ctx.satisfaction_check_start, self._ctx.satisfaction_check_every):
            return None
        task = (sess.plan.task if getattr(sess, "plan", None) and sess.plan.task
                else _history_root(body.get("messages", []))[0])
        evidence = _satisfaction_evidence(body.get("messages", []), rlog=rlog,
                     chat_fn=self._reasoner()[0], role=self._reasoner()[1],
                           gate_plan=getattr(sess, "gate_plan", None))
        evidence += _gate_notes(sess)
        # RUN THE DELIVERABLE, BEFORE the verdict. This check existed on this path already — but only
        # AFTER the judge had said "satisfied", where it can decorate a completion and never inform
        # one. Measured on ada-handles_mellum2_codex_poff_1785693138 (planner off, 166 calls, 2/4):
        # `loop.satisfaction_check` fired twice and `loop.exec_check` fired ZERO times, because both
        # verdicts were not-satisfied and the marker sits past that return. The delivered CLI crashes
        # with `NameError: name 'json' is not defined` — json is imported inside a function at line
        # 124 and used in main() at line 87 — while the unit tests pass and cria's own lint floor
        # reports "no problems reported". A green gate over a program that cannot run, and the one
        # mechanism built to catch exactly that was never asked.
        exec_marker = live_execution_marker(sess, body, task, self._ctx.reasoner_chat,
                                            self._ctx.reasoner_role, rlog)
        if exec_marker:
            evidence += "\n\n" + exec_marker
        satisfied, reason, _fix = judge_satisfaction(
            task, evidence, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog,
            coder_tools=_coder_tools_summary(body.get("tools"), params=False),
            workspace_root=sess.workspace_root or "",
            routes=known_routes(body.get("messages", []), sess),
            gate_findings=getattr(sess, "last_gate_flag", "") or "")
        rlog.emit("loop.satisfaction_check", plan_off=plan_off, drive=sess.drive_count,
                  satisfied=satisfied)
        if not satisfied:
            # THE OPERATOR'S RULING, 2026-08-15. This path used to `return None` — log only — on the
            # grounds that a timer's verdict is judgment rather than ground truth, and that steering
            # off a clock is noise on a clock (#3, #11). Cycle 2 measured what that cost. On
            # shipping-rates-rb × nemotron-elastic the judge returned NOT-satisfied four times
            # (calls 0041, 0059, 0072, 0086), each naming `Shipping.zone_for` as not implemented and
            # each carrying a written fix; the coder heard none of it and the cell ended 2 of 4 with
            # that method still absent — reproduced cold as `undefined method 'zone_for'`. Cycle 1
            # recorded the same shape on feed-pipeline-java × qwen35, where the unheard deliverable
            # was a REVIEW.md worth 20 points that needed sixty words and no build.
            #
            # The ruling: a verdict that NAMES a specific missing deliverable is not the timer's
            # opinion, it is a checkable absence, and it may reach the coder.
            #
            # Bounded three ways, because the original objection was right about the noise:
            #   - only when the judge actually said something — an empty reason stays silent (#3);
            #   - only when nothing else is steering this turn (the caller's `blocked` covers the
            #     guard steers; this covers a nudge already parked for the next turn);
            #   - and NEVER the same reason twice running. feed-pipeline-java × qwen35 produced
            #     TWELVE consecutive not-satisfied verdicts on a workspace already scoring 5 of 5;
            #     twelve identical steers is precisely the clock-noise the old comment defended
            #     against, and this is what keeps that objection satisfied.
            #
            # It carries the judge's REASON only. `proposed_fix` stays unused on this path: naming
            # the gap is what was ruled on, choosing the implementation is not (#2's corollary, and
            # steer_diagnose's own "Do not choose the IMPLEMENTATION").
            named = (reason or "").strip()
            if named and not sess.nudge_reason and named != (sess.last_gap_named or "").strip():
                sess.last_gap_named = named
                sess.nudge_reason = prompts.render("periodic_gap", reason=reason)
                sess.steer_source = "completion check (deliverable not found)"
                rlog.emit("loop.satisfaction_gap_named", level="info", head=_clip(named, 120))
            return None   # never ENDS the session on a not-satisfied verdict — that is unchanged
        probe_tc = guard_gate_op(sess, body, rlog, workspace_root=sess.workspace_root)
        if probe_tc is not None:  # verify the repo's checks before ending (same backstop as 'done')
            sess.done_probe = True
            sess.probe_call_id = probe_tc["id"]
            # Held as PIECES, not as prose: the note's opening claim depends on whether the gate
            # actually ran, and that is not known until its result comes back next turn. The
            # exec_marker is what must not be recomputed (it costs a reasoner call).
            sess.pending_done_parts = (reason, exec_marker)
            sess.pending_done = satisfaction_done_note(reason, exec_marker)   # reuse; never run twice
            sess.steer_source = "completion check (task satisfied)"
            return _completion_toolcalls([probe_tc],
                                         note="cria completion check: the task looks done — verifying the repo's checks")
        # No shell to verify → end fail-open, and SAY that nothing verified it. This path composes no
        # gate at all, so the "and the repo's own checks" claim was false here every single time.
        return _completion_final(satisfaction_done_note(reason, checks_ran=False))

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
                                                   check_state=_check_state_words(sess),
                                                   exec_finding=_exec_finding_line(sess))
                sess.steer_source = "completion critic (task not fully done)"
                sess.pending_done = ""
            else:  # green + (satisfied / already critiqued / no reasoner) → trust the objective gate, END
                rlog.emit("loop.gate", plan_off=True, blocked=False)
                parts, sess.pending_done_parts = sess.pending_done_parts, ()
                held, sess.pending_done, sess.leg0_nudged = sess.pending_done, "", False
                if parts:   # recompose now that the gate's own answer is in
                    held = satisfaction_done_note(*parts, checks_ran=bool(sess.last_gate_ran))
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
        # thrash-assist above and the redirect steers to keep getting the coder unstuck, never a
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
        # PERIODIC SATISFACTION CHECK — the off-ramp for a session that finished but cannot stop.
        done_now = self._periodic_satisfaction(
            sess, body, rlog, plan_off=True,
            blocked=bool(steer is not None or rewritten or sess.done_probe or sess.last_gate_red))
        if done_now is not None:
            return done_now
        # PERIODIC gate: every N acting turns, run the checks and insert ground truth — only when nothing
        # else is steering this turn (a guard steer / re-anchor takes precedence).
        if steer is None and not rewritten:
            periodic = guard_periodic_gate(sess, body, rlog, workspace_root=sess.workspace_root)
            if periodic is not None:
                return periodic
        framed = {**body, "messages": _frame_for_item(
            body.get("messages", []), "", sess.summary, 1, 1,
            prior_work=sess.prior_work, tools=body.get("tools"), synthetic=True,
            gate_plan=getattr(sess, "gate_plan", None),
            workspace_root=sess.workspace_root,
            gate_red=bool(getattr(sess, "last_gate_red", False)))}
        # THE DURABLE FETCH LEDGER — the same anchor the plan-ON driver has always injected. It was
        # wired into _work_item only, so on THIS path (planner off — which is how every dense model on
        # the ladder runs, and mellum2) the coder never got it: the ⟦ctx:facts⟧ marker appears in 0 of
        # the 166 prompts of ada-handles_mellum2_codex_poff_1785693138. Its docstring names precisely
        # the failure that then happened — at call 0102 a harness compaction took the fetched
        # /handles/{handle} and /holders/{address} field shapes out of the coder's view and they never
        # came back, for the 25 prompts to the end of the run, while the reasoner kept being given
        # them. cria held those facts in its own memory the whole time and re-injected them on one
        # path only.
        facts = _fetched_facts_anchor(sess, framed.get("messages", []))
        if facts is not None:
            framed = {**framed, "messages": _elide_ledger_copies(   # the anchor is the ONE copy —
                _insert_after_system(framed["messages"], facts), sess, rlog)}  # duplicates collapse
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
            sess.gate_fresh = False  # the workspace may change → any prior gate result is stale
            return comp  # acting → forward
        return self._gate_single_done(sess, comp, framed, body, session_key, rlog)

    def _gate_single_done(self, sess: PlanSession, comp: dict, framed: dict, body: dict, key: str, rlog) -> dict:
        """The coder answered with NO tool call (thinks it's done). Verify before ending: LEG0 (never
        acted → one act-first nudge, re-call once), then the OBJECTIVE completion gate (run the repo's
        checks). NOTE: the gate reads cwd from the ORIGINAL body (reframe_preamble stripped the <cwd>
        tags from ``framed``)."""
        # A CALL CRIA COULD NOT FORWARD MUST NOT LEAVE THE MODEL IN SILENCE — and this path never
        # said so. The nudge landed on the multi-step branch only, so the whole plan-off column of
        # the matrix ran without it. Walked on cycle 4 cell 19 (`shipping-rates-rb x
        # nemotron-elastic`): at call 0025 the model emitted a complete `str_replace_editor` call in
        # its reasoning channel, `massage.reasoning_call_off_menu` recorded it by name, and 0.257s
        # later cria read the empty turn as a completion claim and spent a gate and a judge on a
        # workspace where nothing had happened. That is verbatim the failure the fix was written for.
        lost = comp.pop(massage.LOST_CALL_KEY, None)
        if lost and sess.unexecuted_nudges < MAX_UNEXECUTED_NUDGES:
            sess.unexecuted_nudges += 1
            rlog.emit("loop.lost_call_offmenu", plan_off=True, tried=lost.get("tried"),
                      attempt=sess.unexecuted_nudges)
            conv = framed["messages"] + [{"role": "user", "content": denial.mark(prompts.render(
                "lost_call_offmenu",
                tried=", ".join(f"`{n}`" for n in lost.get("tried") or ["a tool"]),
                menu=", ".join(lost.get("menu") or []) or "(none)"))}]
            comp = self._coder_turn(sess, {**framed, "messages": conv}, body, step=1, rlog=rlog)
            if _has_tool_calls(comp):
                return comp   # it re-issued the call with a tool that exists
        # BEFORE reading this as "thinks it's done": a turn that pasted a whole file did not finish,
        # it failed to emit the call. Same check as the multi-step half — see unexecuted_write().
        if (unexecuted_write(_completion_text(comp),
                             _injected_fence_texts(sess, body.get("messages", [])))
                and sess.unexecuted_nudges < MAX_UNEXECUTED_NUDGES):
            sess.unexecuted_nudges += 1
            rlog.emit("loop.unexecuted_write", plan_off=True, attempt=sess.unexecuted_nudges)
            # The reply the nudge refers to rides in front of it — `framed` is what the coder was
            # SENT, so its own prose answer is not in there, and "send that same content again"
            # about an invisible message is unactionable (see the multi-step sibling, including why
            # a CUT-OFF reply is carried by neither).
            carried = ([] if massage.is_truncated(comp)
                       else [{"role": "assistant", "content": _completion_text(comp)}])
            conv = framed["messages"] + carried + [
                {"role": "user", "content": prompts.render(
                    "nudge", reason=prompts.load("unexecuted_write_nudge"))}]
            comp = self._coder_turn(sess, {**framed, "messages": conv}, body, step=1, rlog=rlog)  # SHARED
            if _has_tool_calls(comp):
                return comp  # it emitted the write after the nudge
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
                check_state=prompts.load_map("done_check_state")["never_ran"],
                exec_finding=_exec_finding_line(sess)), rlog)
        return comp  # no reasoner AND no shell → can't verify at all; forward the 'done' (Tier-2 fail-open, left)

    def _done_critic_reason(self, sess: PlanSession, body: dict, rlog) -> str:
        """The task-level reasoner critic on a GREEN single-item 'done' (parity with the loop's _verify):
        judge the WHOLE task against the real work + the vacuous-green fact. Returns the critic's CONCRETE
        reason when the task is NOT satisfied — a specific unmet deliverable to steer the coder back with —
        or "" when satisfied. Runs on EVERY green 'done' (NO once-bound): cria never lets a still-
        incomplete task exit early; the model finishes the real work on its own. Fail-CLOSED — an
        undecidable judge counts as not-satisfied (judge_satisfaction already only confirms NOT-done)."""
        task = _history_root(body.get("messages", []))[0]
        ev = _satisfaction_evidence(body.get("messages", []), rlog=rlog,
                     chat_fn=self._reasoner()[0], role=self._reasoner()[1],
                     gate_plan=getattr(sess, "gate_plan", None))
        ev += _gate_notes(sess)
        # RUN THE DELIVERABLE — the THIRD sibling of the same wiring. The marker was added to
        # _periodic_satisfaction and _reopen_if_unsatisfied on 2026-08-02 and this path was missed, and
        # this path is the one that actually fires: on a plan-OFF run the coder reaches a green gate and
        # calls task_complete, which lands HERE, while _periodic_satisfaction is `blocked` by exactly the
        # conditions that precede a finish (a pending steer, a red gate, a done-probe in flight).
        # Measured on ada-handles_mellum2_codex_poff_1785693138: `loop.done_critic` fired twice (calls
        # 0158 and 0164), `loop.satisfaction_check` fired ZERO times, so the two fixes that day did not
        # touch the run they were written for. Both judges approved a CLI that dies with
        # `NameError: name 'json' is not defined` in main(); the coder's own two attempts to run it were
        # blocked on a typo'd path and nothing else ever executed it. EVIDENCE, never a gate — empty on
        # a confirmed run or a task that needs no run, so a clean signal stays silent.
        exec_marker = live_execution_marker(sess, body, task, self._ctx.reasoner_chat,
                                            self._ctx.reasoner_role, rlog)
        if exec_marker:
            ev += "\n\n" + exec_marker
        satisfied, reason, _fix = judge_satisfaction(
            task, ev, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog,
            coder_tools=_coder_tools_summary(body.get("tools"), params=False),
            workspace_root=sess.workspace_root or "",
            routes=known_routes(body.get("messages", []), sess),
            gate_findings=getattr(sess, "last_gate_flag", "") or "")
        rlog.emit("loop.done_critic", plan_off=True, satisfied=satisfied)
        return "" if satisfied else (reason or prompts.load("done_no_named_gap"))

    def _reasoned_reanchor(self, body: dict, rlog) -> str:
        """A REASONED continuation after a harness compaction (parity with the loop's re-plan from the
        summary): the reasoner reads the compaction SUMMARY and authors a grounded 'what's done / what
        remains / inspect before creating' directive. Falls back to the canned reanchor when there is no
        reasoner or it yields nothing — a compacted coder is never left without re-orientation."""
        canned = prompts.load("reanchor")
        # THE SUMMARY, NOT THE TASK. This read `_history_root`, which returns the first user message
        # that is not env context — and under a harness that keeps its user messages (Codex does)
        # that is the ORIGINAL TASK, never the compaction summary. So the reasoner was handed a list
        # of REQUIREMENTS under a prompt saying "the working history was just compacted into the
        # summary you are given… state what has already been built", and it answered the only way
        # that question can be answered from a task: by inventing accomplishments.
        #
        # Walked on cycle 4 cell 10, feed-pipeline-java x qwen35, where it fired three times. The
        # reasoner said so itself — "Since the summary is not provided… I am in a bind", "If I output
        # a message claiming I know what was built, I am hallucinating" — and cria injected the guess
        # as a four-item "Remains to Fix" list whose every item was already done and passing. The
        # coder went back into working code and broke `messy_feed_handled`; the cell had been 5/5 at
        # the fifteen-minute mark and finished 4/5.
        #
        # The re-anchored turn IS the summary, whichever shape the harness rewrites in: a harness that
        # REPLACES the root has its compaction message rewritten in place by `reframe_compaction`, and
        # one that KEEPS the root has it appended — either way the marker is on it. No marked turn
        # means no summary reached this turn, so there is nothing to describe and the canned reanchor
        # says the true thing without claiming to know (#11b).
        msgs = body.get("messages", [])
        summary = next((_content_text(m.get("content")) for m in reversed(msgs)
                        if m.get("role") == "user"
                        and CONTINUATION_MARKER in _content_text(m.get("content"))), "")
        if self._ctx.reasoner_role is None or not summary.strip():
            return canned
        text = summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                         prompts.load("reanchor_reasoned"), summary, rlog, phase="reasoner")
        return text or canned

    def _self_compact_single(self, framed: dict, sess: PlanSession, rlog, root_task: str = "") -> dict:
        """The plan-OFF driver's adapter onto :meth:`_self_compact` — dict in, dict out. It had its own
        copy of the whole compaction and its own summarizer; both are gone. ``root_task`` is pinned
        verbatim so it cannot erode across rounds."""
        if not self._ctx.self_compact:
            return framed
        msgs = framed.get("messages") or []
        out = self._self_compact(msgs, sess, None, rlog, pinned_task=root_task)
        return framed if out is msgs else {**framed, "messages": out}

# ------------------------------------------------------------------ module functions


def session_key(headers, messages: list[dict]) -> str:
    """Correlate the many harness requests of one task. Prefer an explicit session
    header; else key on the ORIGINAL (first) user message, which is stable across a
    task's requests even as cria rewrites what it sends the coder.

    The fallback SKIPS harness env-context preambles (``selfcompact.is_env_context``), keying on the
    first REAL user message — the same message ``_history_root`` fingerprints. Keying on a
    stable preamble collided every conversation in a repo onto one ``task:`` key, which made
    a NEW task look like a compaction-rewrite of the old one (false ``rewritten``) and leaked
    the old conversation's briefing into it."""
    if headers is not None:
        sid = headers.get("X-Cria-Session-Id")
        if sid:
            return f"sid:{sid}"
    for m in messages:
        if m.get("role") == "user" and not selfcompact.is_env_context(m):
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



def _plan_off_session(plan: Plan, briefing: str) -> PlanSession:
    """The plan-off session, with ``synthetic`` meaning what it has always meant: DEGENERATE.

    ``synthetic`` selects the single-item driver, whose framing is deliberately the RAW TASK — it
    ignores the plan's items (route-unify invariant 2). That is exactly right for the 1-item case it
    was built for, and exactly wrong the moment the plan holds a model-authored reading step: run
    20260803T211734 authored the step, the retry recovered it, ``loop.start`` reported ``steps=2`` —
    and the step appeared in ZERO of the run's 56 coder prompts, because the single-item driver never
    frames items. The feature was inert on the one path it was built for, and the run wrote four
    files against an invented API having read nothing.

    So: one item → synthetic, the degenerate raw-task drive, unchanged. Two items → an ordinary
    plan session, driven by the multi-item machinery — the step is FRAMED ("Do ONLY this step
    (1 of 2): Read…"), the step critic gates it with the sources_read evidence, the reading check
    fires at its cadence, and the raw task follows as step 2."""
    return PlanSession(plan=plan, synthetic=len(plan.items) == 1, plan_off=True, prior_work=briefing)


def _synthetic_plan(task: str, clock=None, ask=None, files: str = "") -> Plan:
    """A degenerate 1-item 'plan' for PLAN-OFF mode: the whole task is ONE implicit step whose item
    text IS the raw task. The PlanSession carries the ``synthetic`` flag (which selects raw-task
    framing + the single-item off-ramps); the Plan itself is an ordinary 1-item Plan. id/created match
    the Planner's convention (clock + task-key) so a resumed synthetic session keeps a stable id. Never
    mirrored to disk (no ``_persist_plan``) — it holds no decomposition, only the user's own words."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    # A READING STEP FIRST when the task itself names an external source. Plan-off has no planner, so
    # nothing ever told the coder to look anything up — and it didn't: run 1785805694 made ZERO
    # web_fetch calls in 237, then wrote a resolver, unit tests, a live test and a README against
    # `api.handle.me/v1/handle/` returning `address`/`holder`/`totalHandles`, an API it invented
    # whole. It scored 1/4 and could not have scored more: the resolver cannot resolve.
    #
    # THIS IS A DELIBERATE RETURN, and the thing it returns to was retired for cause. The old
    # research-first injection baked a PATH in (`https://<domain>/openapi.json`) and pinned the step
    # so the re-derivation could not drop it — a possibly-wrong URL made an inescapable mandate, and
    # one wrong "not satisfied" re-added it over and over (~275 churning turns). Two things are
    # different now. It names only the DOMAIN THE TASK ITSELF NAMES, never a path, so there is no
    # guess to be trapped by. And it has an EXIT that the retired version never had: the periodic
    # reading check (Loop._research_check) clears it the moment the ledger holds what it asked for,
    # grounded in parsed routes and fields rather than in anyone's claim. A step with an exit is a
    # different object from a step without one.
    #
    # The step is an ordinary item — not pinned, not immutable. The living re-derivation may drop it
    # like any other, and the step critic judges it like any other.
    # ASK ON EVERY CODING TASK, not only when the task's words hold a domain — that quietly defined
    # research as a web thing, and it is not: reading files already in the workspace, a schema on
    # disk, a library's source or a tool's --help is the same act. cria contributes only what it can
    # establish alone (a domain if the task names one, the workspace listing); the MODEL decides
    # whether anything must be read and writes the step, and NONE is a first-class answer.
    step = research.authored_research_step(ask, task, domain=first_domain_in(task) or "",
                                           files=files) if ask else ""
    items = ([PlanItem(text=step)] if step else []) + [PlanItem(text=task)]
    return Plan(id=f"{now.strftime('%Y%m%dT%H%M%S')}-{_task_key(task)[:8]}", task=task,
                created=now.isoformat(timespec="seconds"), items=items)


def _history_root(messages: list[dict]) -> tuple[str, str]:
    """``(text, fingerprint)`` of the conversation's ROOT — the first user message that isn't a
    harness env-context block (the SAME message the ``task:`` fallback ``session_key`` hashes,
    deliberately). This is the structural identity of a conversation: appending turns never
    changes it. SOME harnesses replace it on a compaction (the summary becomes the root), which a
    changed fingerprint under a stable ``sid:`` key detects. Codex does NOT: it keeps every user
    message, this one included, and drops the assistant/tool work — so the fingerprint alone can
    never see a Codex compaction and ``observe_shape`` watches the history LENGTH as well.
    ``task:``-keyed sessions never detect rewrites
    (``_stable_session`` gates it): their key derives from this very root, so a rewritten root
    mints a new key and simply looks like a new session (recorded in docs/port-fidelity-audit.md)."""
    for m in messages:
        if m.get("role") == "user" and not selfcompact.is_env_context(m):
            text = _content_text(m.get("content"))
            return text, hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
    return "", ""


def _rewrite_summary_text(messages: list[dict], root_text: str) -> str:
    """The harness's compaction summary, whichever way the harness rewrote the history.

    Two shapes, both real. A harness that REPLACES the conversation root leaves the summary AS the
    root, and ``root_text`` is it. A harness that keeps every user message and drops the work behind
    them (Codex) leaves the original task at the root and the summary as a later user turn — already
    re-anchored by :func:`reframe_compaction`, so it carries ``CONTINUATION_MARKER`` and is found
    structurally, with no phrase-matching here. Falls back to the root, which is what the second
    shape's caller used to pass unconditionally."""
    for m in reversed(messages):
        if m.get("role") == "user" and CONTINUATION_MARKER in _content_text(m.get("content")):
            return _content_text(m.get("content"))
    return root_text


def _work_log(messages: list[dict], *, keep_checks: bool = False, rlog=None,
              gate_plan=None) -> str:
    """A log of the coder's REAL actions — the tool calls it made (file writes, commands)
    and what they returned — for the completion compaction. cria's own plan-file writes and probe
    runs are stripped so the summary reflects the actual work, not the orchestration scaffolding.
    Full content flows: this is a model-read input (the summarizer/judge), and the context floor is
    the one window-aware place any physical truncation happens — a per-site clip here would just be a
    dumber, undetectable slice of what the model reads.

    A REFUSED CALL IS LABELLED AS ONE. cria lowers a refusal to a ``printf`` of its own words, so the
    refusal arrives as a tool result and rendered as ``  -> …`` it is byte-identical to a real one —
    while ``prompts/verify.txt`` tells the step critic, in cria's voice, that "each ``-> ...`` line is
    what it returned". Measured 2026-08-03 across 127 sessions: 216 of 537 step-critic prompts with an
    action log (40%) and 140 of 370 satisfaction prompts (38%) carry at least one. The label goes on
    the ``$`` CALL line, because the call is the only thing cria knows did not happen; the result body
    is left entirely alone, verbatim and unqualified. That restraint is the fix's whole shape — a
    refusal frequently carries REAL ground truth (a repeat-fetch refusal embeds the document's own
    endpoint list, the very block ``selfcompact`` anchors verbatim), and an earlier draft that
    labelled the BODY told the judge to discard its only real evidence.

    Which results are refusals is decided at the site that refused (:mod:`cria.denial`) and read here
    from the mark, never from wording. Pairing is by ``tool_call_id``: an assistant turn can carry
    several calls and only one of them be refused, and there is no other record of which. A tool
    result with no id cannot be attributed to a call, so nothing is labelled for it — the safe
    direction (an unlabelled line is exactly today's behaviour) and it is counted in the event rather
    than left silent."""
    lines: list[str] = []
    # Loaded per call like every other model-facing string, so the wording is tunable without a code
    # change (#22). It says one thing and stops there: the call did not run.
    DENIED_CALL_LABEL = prompts.load("work_log_denied")
    # Same scrub chain every other reasoner-facing serialization uses (author_steer, _summarize_single,
    # _self_compact): without clean_gate_results, cria's OWN gate probe renders here as a coder action —
    # `$ shell {"command": "cd … || exit 97\necho ___CRIA_GATE_…\npytest …"}` — and its raw output as
    # something the coder's tool returned. This log feeds the step critic, the re-derivation, the
    # satisfaction judge and the completion briefing, so the orchestration was being judged as work.
    # THE PLAN IS WHAT MAKES THE GATE TEXT HONEST. Without it `clean_gate_output` has no workspace
    # and no `untested` list, so the stranded-test sentence and the disk-quoted findings are dropped
    # and the same gate renders as a bare "no error-class problems". Measured on maple-preview
    # 1786138747: 8 of 8 CODER-side gate blocks carried "Test code in testAdaHandleResolver.py will
    # not run: pytest only runs tests named test_*.py or *_test.py"; 0 of 8 reasoner-side ones did.
    # cria then asked those reasoners what the coder should do next and got "implement the API
    # calls" — the rename the coder had just decided on was dropped and never came back.
    scrubbed = list(probegate.clean_gate_results(_reasoner_session(messages), gate_plan))
    denied_ids = {tid for m in scrubbed
                  if m.get("role") == "tool" and (tid := m.get("tool_call_id"))
                  and denial.is_denied(str(m.get("content") or ""))}
    unpaired = sum(1 for m in scrubbed
                   if m.get("role") == "tool" and not m.get("tool_call_id")
                   and denial.is_denied(str(m.get("content") or "")))
    labelled = 0
    for m in scrubbed:
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = str(fn.get("arguments", "")).strip()
                if _is_cria_scaffolding(args, keep_checks=keep_checks):
                    continue
                mark = ""
                if tc.get("id") in denied_ids:
                    mark = " " + DENIED_CALL_LABEL
                    labelled += 1
                lines.append(f"$ {fn.get('name')} {args}{mark}")
        elif role == "tool":
            c = str(m.get("content") or "").strip()
            if c and not _is_cria_scaffolding(c, keep_checks=keep_checks):
                lines.append(f"  -> {c}")
    if rlog is not None and (labelled or unpaired):
        rlog.emit("loop.work_log_denied", level="info", labelled=labelled, unpaired=unpaired)
    return "\n".join(lines)


def _is_cria_scaffolding(text: str, *, keep_checks: bool = False) -> bool:
    """Is this cria's own orchestration rather than the coder's work?

    The old test was ``"PROBE_EXIT" not in c`` — the NAME of the constant, never its value. The emitted
    sentinel is ``proberun.PROBE_EXIT_SENTINEL`` ("EXIT:") and the gate's section prefix is
    ``probegate.SECTION_PREFIX`` ("___CRIA_GATE_"), so the literal it checked for occurs only in test
    fixtures — the guard never fired in production and every raw probe dump landed in the work log as
    the coder's own tool output. Keyed on the real constants now, so it cannot drift again.

    A ⟦ctx:checks⟧ block is NOT scaffolding: it is cria's rendering of a real checker's real output.
    Stripping it is right for a log that describes what the CODER did, and wrong for the judge that
    decides whether the task is done — which is the one reader for whom "did the checks pass" is the
    question. ``keep_checks`` says which reader this is.

    Walked on ada-handles_mellum2_codex_poff_1785714194 call 0033: the satisfaction judge wrote "the
    test suite test_resolve_handle.py passes" and nothing in its evidence said so. The string
    `4 passed` appears nowhere in its prompt; the only pytest result it could see was the original
    `3 failed, 1 passed`, because every check block had been stripped. cria then supplied the gap in
    its own words — "Everything else the checks cover passed" — and the judge's verdict repeated that
    sentence back. cria may SELECT which of a checker's real lines to show; it may never SUBSTITUTE
    its own, and least of all to the judge that ends the session on the answer.

    THE SEARCH-READ DENIAL IS NO LONGER HERE, and that is a fix, not an omission. It was added for
    the right reason — the note is cria's voice and was being read as a tool's answer — but deleting
    a tool RESULT does not delete the CALL that produced it, so the log kept the coder's
    ``$ read_file …`` line and lost its ``->`` line entirely: a call that appears to have returned
    nothing, about a file that is still sitting on disk. Measured 2026-08-03 over ~/.cria/calls: 229
    coder turns across 9 runs, every one of them a hole. Deletion was the wrong tool for the job the
    whole time; the note is now labelled by :func:`_work_log` as a call that did not run and shown
    verbatim (#2 — the safe class of intervention is additive, never destructive).
    """
    if probegate.CHECKS_MARKER in text:
        return not keep_checks
    return (probegate.SECTION_PREFIX in text
            or proberun.PROBE_EXIT_SENTINEL in text)


def _satisfaction_evidence(messages: list[dict], rlog=None, gate_plan=None,
                           chat_fn=None, role=None) -> str:
    """Evidence for the whole-task satisfaction judge. Beyond the structured tool-action log
    (_work_log), it MUST include cria's summary-marker prose — continuation / rollup / briefing —
    because a HARNESS or self compaction REPLACES the structured tool history with that prose. On the
    turn right after a compaction _work_log alone is empty, so the judge saw "(no actions recorded
    yet)" and hallucinated that NO work was done (the observed false "the coder hasn't started" that
    marked a real, in-progress build as not-satisfied). The summary is the best record of the
    compacted-away work; the judge weighs it against the still-verbatim recent actions."""
    # Bounded like the step critic's evidence (e4564da) — this sibling never got the fix and grew a
    # measured 73.7KB slot (0183-satisfaction, run 0729T224807); the judge holds read_file/list_dir
    # to drill past the disclosed elision, and the doom loop (fail closed -> re-nudge -> grow) is
    # the same mechanism the critic bound was shipped for.
    log = _dedup_evidence(_work_log(messages, keep_checks=True, rlog=rlog, gate_plan=gate_plan),
                          rlog=rlog, chat_fn=chat_fn, role=role)
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


# A line that OPENS in cria's voice: the human-facing `⟦cria⟧` banner, or anything in the
# model-facing `⟦ctx:…⟧` namespace. The namespace SHAPE, not a list of known markers, because the
# forgeries that matter invented names cria has never emitted (`⟦ctx:complete⟧`, `⟦ctx:compacted⟧`,
# `⟦ctx:summary⟧`) — a list would have missed exactly those, and would need editing every time a
# real marker is added.
_CRIA_VOICE_OPENER = re.compile(r"^\s*⟦(?:cria|ctx:[a-z]*)⟧")


def _strip_cria_banners(text: str, *, whole_namespace: bool = False) -> str:
    """Drop cria's own status lines from a text blob — so the coder can't parrot them and they
    never reach the critic (via pending_coder_text) as 'the coder's summary'.

    ``whole_namespace`` extends that from `⟦cria⟧` to every marker in cria's `⟦ctx:…⟧` namespace,
    and is for text the MODEL wrote and cria has not yet added anything to. It was measured over
    ~/.cria/calls (2026-08-03): of 6,959 captured replies carrying text, **23 open a line with a
    cria marker** and only 6 of those are coder turns — small, but the shape is rule 5b one level
    down, because the reader downstream cannot tell cria's voice from the model's. Walked on
    `20260728T000013` call 0244: the coder answered with NO tool calls and the line
    `⟦ctx:complete⟧ Step 4 of 5 completed.`; it arrived at line 300 of the step critic's prompt at
    0245 and the critic returned ``done: true``. The old docstring promised this could not happen.
    Two of the six are worse than parroting — an invented `⟦ctx:complete⟧` and a forged
    `⟦ctx:steer⟧` ("All remaining steps are complete") — cria's completion and directive channels,
    written by the model, on turns that did no work.

    Only a line that OPENS with a marker goes. A marker MID-line is a model QUOTING the work log
    ("tool: ⟦ctx:checks⟧ the repo's own checks report…") — 348 of them in the same corpus, nearly
    all reasoner and compactor summaries doing exactly the job they were asked to do. Dropping
    those would delete real content to catch 23, which is the wrong trade and the wrong direction
    (#2 — the safe class of intervention is additive). Only the line goes, never the block under
    it: a parroted check dump demoted out of cria's voice is still the coder's own claim, and the
    judge may weigh it as one.

    NOT applied to replayed HISTORY (:func:`_strip_cria_file_ops`), and that is deliberate. cria
    AUTHORS assistant-role content carrying `⟦ctx:briefing⟧` — `_compact_done` embeds the briefing
    in the closing message and the follow-up turn reads it back out (see the BRIEFING_OPEN split in
    :func:`_briefing_from_history`). There is no signature that separates cria's briefing from a
    forged one, so on that path the namespace scrub would delete cria's own words to catch a
    forgery. History keeps the `⟦cria⟧`-only rule."""
    if not text:
        return text

    def _drop(ln: str) -> bool:
        return indicators.SENTINEL in ln or (whole_namespace and bool(_CRIA_VOICE_OPENER.match(ln)))

    kept = [ln for ln in text.splitlines() if not _drop(ln)]
    if len(kept) == len(text.splitlines()):
        # NOTHING was cria's — return the text byte-identical. The rebuild-and-strip below must not
        # touch a reply it had no business in: this runs on EVERY coder reply, and the forgery it
        # exists for is 0.33% of them. Trimming the other 99.67% would be an unmeasured edit to all
        # of them, made to catch a few.
        return text
    return "\n".join(kept).strip()


def _strip_completion_banners(completion: dict) -> None:
    """Strip cria's banners from a completion's content, in place — so they aren't forwarded to the
    harness (and re-echoed into the next turn's history).

    The WHOLE namespace: this runs on the coder's raw reply, before cria has added anything of its
    own to it, so every cria marker in it was written by the model."""
    for ch in completion.get("choices", []):
        msg = ch.get("message") or {}
        if isinstance(msg.get("content"), str):
            msg["content"] = _strip_cria_banners(msg["content"], whole_namespace=True)


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
    the raw form is kept if nothing could be extracted.

    The instructions half is PROVENANCE-GATED — see :func:`_workspace_instructions`. cria used to
    re-present whatever the harness sent as "Project instructions (from the repo — follow these)",
    which is a claim about where the text came from that cria had never checked, and on the
    six-language battery it relayed another repo's development doctrine into a bare /tmp task. Only
    instructions cria can find in an instruction file inside the workspace the preamble names are
    relayed; everything else is dropped. The environment fields are unaffected."""
    if m.get("role") != "user" or not selfcompact.is_env_context(m):
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


# The files a harness reads project instructions out of. cria does not need to know which one THIS
# harness used — only whether the text it was handed is present in one belonging to the workspace.
_INSTRUCTION_FILES = ("AGENTS.md", "AGENT.md", "CLAUDE.md", "GEMINI.md", "CONVENTIONS.md",
                      ".cursorrules", ".windsurfrules", ".github/copilot-instructions.md")


def _squash(s: str) -> str:
    return " ".join(s.split())


def _workspace_instructions(cwd: str, relayed: str) -> str | None:
    """The part of ``relayed`` that is genuinely THIS workspace's own instruction file, or None.

    A harness concatenates every instruction file it can see — the operator's global one and the
    repo's — and hands cria the blob. cria re-presents that blob as "Project instructions (from the
    repo — follow these)", which is a claim about provenance cria never checked.

    Measured on the six-language battery: that clause put THIS repo's development doctrine inside an
    unrelated /tmp task workspace containing no such file — "Mitigations, fallbacks, and band-aids
    are strictly prohibited. There is an upstream fix. Find it." nemotron-elastic cited it to justify
    a destructive rewrite and talked itself past its own caution to do so ("the instruction says we
    should not make unnecessary changes; but this is necessary"). A rule written for a long-lived
    repo is the worst possible instruction for a weak model that has just formed a wrong theory.

    So the provenance is CHECKED against the world rather than asserted (#5b): the workspace's own
    file is read from disk and relayed only when the harness's blob actually contains it. Anything
    else is another repo's authority and is dropped — silence over noise (#3), and the subtractive
    direction (#1). The workspace is the ``cwd`` the preamble itself carries, so this needs no
    plumbing and works for any harness that states one."""
    if not cwd:
        return None
    try:
        base = Path(cwd)
        if not base.is_dir():
            return None
    except OSError:
        return None
    blob = _squash(relayed)
    for name in _INSTRUCTION_FILES:
        try:
            f = base / name
            if not f.is_file():
                continue
            own = f.read_text(errors="replace").strip()
        except OSError:
            continue
        if own and _squash(own) in blob:
            return own
    return None


def _reframe_preamble_text(text: str) -> str | None:
    instr = _tag_body(text, "INSTRUCTIONS") or _tag_body(text, "user_instructions")
    env = _tag_body(text, "environment_context")
    cwd = _tag_body(env or "", "cwd") or ""
    parts: list[str] = []
    if instr and instr.strip():
        own = _workspace_instructions(cwd.strip(), instr)
        if own:
            parts.append(prompts.render("preamble_instructions", instructions=own.replace("\r", "").strip()))
    if env:
        fields = [(label, v.strip()) for tag, label in _ENV_FIELDS
                  if (v := _tag_body(env, tag)) and v.strip()]
        if fields:
            parts.append(prompts.render("preamble_environment", fields=", ".join(f"{k}: {v}" for k, v in fields)))
    return "\n\n".join(parts) if parts else None


def _frame_for_item(messages: list[dict], item: str, summary: str, idx: int, total: int, prior_work: str = "", tools=None, synthetic: bool = False, gate_plan=None, workspace_root: str | None = None, gate_red: bool = False) -> list[dict]:
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
    prompt = _item_prompt(item, summary, idx, total, workspace_root, gate_red)
    hint_block = f"{hint}\n\n" if hint else ""
    out: list[dict] = [{"role": "system",
                        "content": prompts.load("coder_system") + "\n\n" + hint_block + done_block + prompt}]
    acked = False
    for m in messages:
        if m.get("role") in ("system", "developer"):
            continue  # harness agent boilerplate → replaced by cria's coder_system above
        out.append(reframe_preamble(m))  # env-context preamble → cria's clean voice; the real TASK is KEPT
        if not acked and m.get("role") == "user" and not selfcompact.is_env_context(m):
            # The user's real task just went in as history — acknowledge it's been decomposed, so it
            # reads as the overall GOAL (background), not a fresh "do it all now" ask. Consecutive
            # assistant turns (this ack + the first work turn) are merged upstream (_merge_consecutive_assistant).
            out.append({"role": "assistant", "content": prompts.load("plan_ack")})
            acked = True
    out.append({"role": "user", "content": prompt})  # the CURRENT step = the active ask (last turn; also in system)
    return out


# A file-looking token in a step's text: `test_resolve_handle.py`, src/main.go, "README.md".
_STEP_ARTIFACT = groundtruth._STEP_ARTIFACT   # defined one level down; see the note there


# A step that AUTHORS a file, as opposed to one that merely mentions a path. `grep -n 'x' spec.json`
# names a file and is exactly the bare-shell-command noise this judge SHOULD delete; "Write
# live_test.py: ..." names one and is the deliverable.
# The verb must GOVERN the filename, not merely co-occur with it in the same sentence.
#
# The looser "any authoring verb anywhere + any filename anywhere" version shipped and immediately
# protected junk: run 20260802T024816 fired `replan_noise_refused` three times on
#     "Commit the three files (resolve.py, resolve_test.py, README.md) to a new repo, add a
#      .gitignore with __pycache__ and .pyc, push to a new GitHub repo."
# — git plumbing the task never asked for, which the noise judge was right to delete and which my
# rule kept alive. Intended firings across the whole ladder: 3. False firings in ONE run: 3. An
# assist that fires on a clean signal is pure downside, so the rule is narrowed to the shape the
# real cases actually have: the verb, then the file.
def step_artifacts_named(step: str) -> list[str]:
    """File artifacts a step NAMES — the plain token match, no disk access.

    Distinct from :func:`step_artifacts_on_disk`, which asks whether they exist. Here the question is
    only whether the step is about producing a file at all, which is what separates deliverable work
    from the strategy/plumbing steps the noise judge is meant to delete."""
    seen, out = set(), []
    for m in _STEP_ARTIFACT.finditer(step or ""):
        rel = m.group(1)
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def step_artifacts_on_disk(step: str, root: str | None) -> list[str]:
    """Files the STEP NAMES that already exist. Deterministic — the filesystem, asked now."""
    if not step or not root:
        return []
    out: list[str] = []
    for m in _STEP_ARTIFACT.finditer(step):
        rel = m.group(1)
        if rel in out:
            continue
        try:
            if os.path.isfile(groundtruth.resolve(root, rel)):
                out.append(rel)
        except (OSError, ValueError):
            continue
    return out


def _repair_note(item: str, workspace_root: str | None, gate_red: bool) -> str:
    """Reframe an AUTHORING step whose artifact already exists and is currently failing.

    Measured on mellum2 attempt 3 (`ada-handles_mellum2_codex_pon_1785625253`). Step 4 of 7 read
    "Write unit tests in `test_resolve_handle.py` …" and was sent, byte-identical, in **33
    consecutive prompts**. The gate's findings rode along in only **15** of them. On the 18 turns
    where the step arrived without the failures attached, the model read the standing order and did
    exactly what it said — its own words, three turns running: *"The user is telling me to write
    unit tests"*, *"asking me to complete step 4"*, *"The user is asking me to write unit tests"* —
    and rewrote the file each time, regenerating the same two failing assertions it had just been
    told to fix. The instruction that caused the loop was present 100% of the time; the correction,
    45%.

    So the fix is not to act on the stall signal, it is to stop the step's wording outliving its
    artifact. Both conditions are facts cria already holds, and BOTH are required:

      * the file the step names is on disk NOW (not a claim — `os.path.isfile`)
      * the repo's own checks are currently RED

    Either one alone stays silent (principle 3), and nothing is ever deleted or blocked — the step
    itself is untouched and this only ever tells the coder MORE about the real state (principle 2).
    """
    if not gate_red:
        return ""
    files = step_artifacts_on_disk(item, workspace_root)
    if not files:
        return ""
    # The note states a FACT and stops. It used to add "this step's wording asks you to WRITE them",
    # which is a claim about the step's INTENT that the file list cannot support: step_artifacts_on_disk
    # matches every filename token, and 14% of the 1,052 delivered notes named more than one — including
    # files a step only MENTIONED. Live (run 20260801T232511 call 0097) the step was a critic's essay
    # asserting "resolve_handle.py and get_holder_handle_count.py are not in the workspace / No README.md
    # exists", and three lines below it cria listed all three as present. Both claims stood, unresolved,
    # in one prompt. Restating the note as a direct disk read that OVERRIDES anything above is true
    # whichever way the step meant those names, and it settles the contradiction instead of adding to it.
    # (The old wording also read "but them are already written" — shipped 145 times.)
    many = len(files) > 1
    return "\n\n" + prompts.render(
        "step_repair_note", files=", ".join(f"`{f}`" for f in files),
        plural="s" if many else "", verb="" if many else "s")


def _item_prompt(item: str, summary: str, idx: int, total: int,
                 workspace_root: str | None = None, gate_red: bool = False) -> str:
    # Templates: cria/prompts/step_framing.txt (+ step_completed.txt for the prior-steps
    # prefix, included only once there's progress to show, + step_repair_note.txt when the step's
    # artifact already exists and the checks are red).
    completed = prompts.render("step_completed", summary=summary) + "\n\n" if summary else ""
    return (prompts.render("step_framing", completed=completed, idx=idx, total=total, step=item)
            + _repair_note(item, workspace_root, gate_red))


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


# A fenced block this long is a FILE the model typed into chat, not a snippet illustrating a point.
UNEXECUTED_WRITE_LINES = 12
MAX_UNEXECUTED_NUDGES = 2   # bounded: after this the turn falls through to the completion gate


def _injected_fence_texts(sess, messages: list[dict] | None = None) -> list[str]:
    """Everything the coder was SHOWN this session — the strings a coder's fenced "file" might merely
    be quoting back. Deterministic gather; the comparison happens in unexecuted_write().

    IT USED TO READ ONE SLOT: `fetched_pages[url][2]`, the parsed response SHAPES. That slot is filled
    by a REST-spec reader, so it is empty for every page that is not an API spec — and the exemption
    it feeds was then inert exactly when the coder had read documentation. Walked on cycle 4 cell 18
    (`rust-toml-cli x ternary-bonsai`): the coder fetched docs.rs/toml, 7,925 characters of the crate's
    real API, and cria's own `⟦ctx:facts⟧` recorded `HTTP 200 (this page answered, but no endpoint
    definitions were found in it)` — routes empty, shapes empty. The coder's next turn summarised what
    it had learned, quoting fifteen lines of `pub enum Value { … }` from that page, and cria answered

        your last message contained the file's contents as text, but no write tool call was made, so
        nothing reached the disk — send that same content again as a write tool call

    which was false on both halves: the fence was not a file, and cria's own tool results two calls
    earlier said `Wrote .../Cargo.toml` and `Wrote .../src/main.rs`. That turn was the run's ONLY
    tool-call-less coder turn — its one chance to be judged and advanced — and it was spent on
    `read_file` to check cria's claim.

    So the haystack is now every tool result in the conversation: the pages fetched, the files read,
    the command output. If a fenced block already appears verbatim in what the coder was handed, it is
    a quote whatever kind of page it came from (#20). The comparison is unchanged — whitespace-
    normalized containment with an 80-character floor — it was being handed an empty haystack."""
    out: list[str] = []
    for entry in (getattr(sess, "fetched_pages", None) or {}).values():
        shapes = (tuple(entry) + ("", "", ""))[2]
        if str(shapes).strip():
            out.append(str(shapes))
    for m in messages or []:
        if m.get("role") == "tool":
            body = _content_text(m.get("content"))
            if body.strip():
                out.append(body)
    return out


def _is_reading_step(sess, item) -> bool:
    """Is the step in flight the plan-off READING step — the one that produces no files?

    Its own prompt says so in as many words: *"It produces nothing — no script, no tests, no files."*
    cria has always known this deterministically (the hand-back below has used the same test since
    2026-08-04); it just had no name, so no other seat could ask."""
    return bool(getattr(sess, "plan_off", False) and item is not None
                and item.text != getattr(sess.plan, "task", None))


def unexecuted_write(content: str, injected=None) -> bool:
    """Did this tool-call-less turn CONTAIN the work instead of doing it?

    The branch below reads a coder turn with no tool call as "it thinks the step is done". That
    inference is a model-trait bet, and it loses badly on some models. Measured over every captured
    coder turn: gemma4 0.0% tool-call-less turns (n=3,955), qwopus 3.4%, qwythos 4.5% — and mellum2
    **29.4%** (192 of 653). Nearly a third of one model's turns were being read as completion claims
    and sent through a probe round-trip and a critic call.

    They are not completion claims. Read in full, run 20260801T160104: call 0012 is the complete
    resolver typed into chat, and call 0033 is a polished rewrite of it — correct base URL, correct
    `GET /handles/{handle}`, argparse CLI, typed dataclass — with no write_file call. That run scored
    0/4 with its own finished deliverable sitting in the transcript. A summary of finished work does
    not paste the file; a model that failed to emit the call does.

    So this is not a new assist — it is refusing to draw a conclusion the evidence contradicts. The
    nudge is the one cria already sends, and it is bounded (MAX_UNEXECUTED_NUDGES) so a model that
    keeps printing code still reaches the gate."""
    # DEPTH, not a toggle. A pasted README is a ```markdown block containing ```bash blocks, and a
    # toggle reads the inner CLOSING fence as opening a new one — so the run of lines never reaches
    # the threshold and the whole file slips through. Measured on run 20260801T232511 (mellum2,
    # ada-handles, 3/4): of 12 tool-call-less turns carrying a fenced block, the toggle caught 7 and
    # missed 5. Four of the five were the complete README, WITH its `## Installation` /
    # `pip install requests pytest` section — the exact content whose absence cost the run its
    # fourth point. The coder wrote it three times and never called a write tool.
    body = content or ""
    injected_norm = ["".join(t.split()) for t in (injected or []) if t and t.strip()]

    def _is_self_quote(fence_lines: list[str]) -> bool:
        # A fence the coder copied out of cria's own prompt is not an unsaved file. Walked on
        # mellum2 1786196176 calls 0013/0020: two research summaries quoted the ⟦ctx⟧ response-shape
        # block (the ```ts schema cria itself injected), the nudge fired both times — "your last
        # message contained the file's contents as text" — and the coder, told to persist a file it
        # never drafted, tried to overwrite the read-only spec spill. cria HOLDS every string it
        # injected, so identity is a comparison, not a judgment: whitespace-normalized containment,
        # with a floor so a two-token overlap cannot exempt a real file.
        blob = "".join("".join(l.split()) for l in fence_lines)
        return len(blob) >= 80 and any(blob in inj for inj in injected_norm)

    depth, run, fence = 0, 0, []
    for line in body.splitlines():
        t = line.lstrip()
        if t.startswith("```"):
            if t[3:].strip():              # ```lang → opening (the tag, not the fence)
                depth += 1
            elif depth > 0:                # bare ``` → closing
                if depth == 1 and run >= UNEXECUTED_WRITE_LINES and not _is_self_quote(fence):
                    return True
                depth -= 1
                if depth == 0:
                    run, fence = 0, []
            else:                          # bare ``` with nothing open → an opening fence
                depth = 1
            continue
        if depth > 0:
            fence.append(line)
            if line.strip():
                run += 1
    return (depth > 0 and run >= UNEXECUTED_WRITE_LINES   # unclosed fence, e.g. cut off mid-file
            and not _is_self_quote(fence))


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
    desc = prompts.fill(prompts.load_map("tool_descs").get(
        TASK_COMPLETE_TOOL, "Call this when the task is fully done and verified. Pass a short summary."),
                        spill_dir=webfetch.SPILL_DIR)
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
    if is_shell_tool_name(name):
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


def _denied_signatures(messages: list[dict] | None) -> list[tuple]:
    """Signatures of the calls cria itself REFUSED, newest last.

    A refused call changed nothing — cria knows, because cria is what stopped it. `_is_progress`
    reads the command TEXT and answers "this writes a Gemfile / makes a directory / installs a gem",
    which is true of the words and false of the outcome, and every such answer FLUSHES the repetition
    window. Walked on cycle 4 cell 13 (`shipping-rates-rb x ternary-bonsai`, 10% useful): the walk
    replayed the run's real 53-call sequence through this guard and it fires **zero times** — six
    identical refused `gem install` attempts across 25 calls, and each `write_file Gemfile` and
    `mkdir -p vendor/bundle` between them reset the hunt. Writing a Gemfile and making vendor
    directories is exactly what an install loop does between attempts, so the loop kept erasing the
    evidence of itself. Call 0051 rewrote the Gemfile with bytes identical to call 0033 and still
    counted as progress on new ground.

    The protected case is untouched: a real edit→test→edit→test cycle resets, because those writes
    really do change bytes and cria never refused them."""
    out: list[tuple] = []
    by_id: dict[str, str] = {m.get("tool_call_id"): _content_text(m.get("content"))
                             for m in (messages or []) if m.get("role") == "tool"}
    for m in messages or []:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            body = by_id.get(tc.get("id"))
            if body and denial.is_denied(body):
                fn = tc.get("function") or {}
                args = fn.get("arguments") or ""
                out.append(_action_signature(fn.get("name") or "?",
                                             args if isinstance(args, str) else json.dumps(args)))
    return out


def _last_write_by_path(messages: list[dict] | None) -> dict:
    """path -> content hash of the LAST write to it this session.

    The most recent write is the only one that can answer "is this already what is on disk". An
    earlier-but-superseded copy cannot: write A, edit it, write A's original bytes back IS a change,
    and comparing against every historical write would call it a no-op."""
    out: dict = {}
    for m in messages or []:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            if not _is_write_tool(name):
                continue
            args = fn.get("arguments") or ""
            sig = _action_signature(name, args if isinstance(args, str) else json.dumps(args))
            if sig[0] == "write" and sig[1]:
                out[sig[1]] = sig[2]
    return out


def _rewrites_the_same_bytes(sig: tuple, last_write: dict) -> bool:
    """This write puts back exactly what the last write to that path already put there.

    `_is_progress` answers "does this action CHANGE the workspace" and says yes to every write. It is
    right about the words and wrong here: re-writing identical bytes changes nothing, and a change on
    new ground FLUSHES the repetition window. Walked on cycle 4 cell 13
    (`shipping-rates-rb x ternary-bonsai`): call 0051 re-wrote `Gemfile` with bytes identical to call
    0033 and counted as progress on new ground, flushing an install loop that had been running for
    eighteen calls. The window's own age trim is why the earlier copy could not catch it — entries
    expire after REPEAT_WINDOW forwarded calls, and 0033 to 0051 is eighteen.

    Only the LAST write to the path is compared, so a write→edit→write-the-original cycle is still
    the change it really is."""
    return sig[0] == "write" and bool(sig[1]) and last_write.get(sig[1]) == sig[2]


def _refusals_in_window(messages: list[dict] | None) -> int:
    """How many of the last REPEAT_WINDOW forwarded calls cria itself refused.

    A fact cria owns outright — it is what stopped them — so no similarity judgement is needed and
    none is made. See the fire site for the replay that showed why the similarity rule cannot cover
    this shape."""
    seen = 0
    for m in reversed(messages or []):
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        seen += 1
        if seen > REPEAT_WINDOW:
            break
    tail, n = [], 0
    for m in messages or []:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            tail.append(m)
    tail = tail[-REPEAT_WINDOW:]
    ids = {tc.get("id") for m in tail for tc in (m.get("tool_calls") or [])}
    by_id = {m.get("tool_call_id"): _content_text(m.get("content"))
             for m in (messages or []) if m.get("role") == "tool"}
    for cid in ids:
        if cid is not None and denial.is_denied(by_id.get(cid) or ""):
            n += 1
    return n


def guard_track_repetition(gs: GuardState, coder: dict, rlog, *, step=None,
                           messages: list[dict] | None = None) -> None:
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
    denied = _denied_signatures(messages)
    last_write = _last_write_by_path(messages)
    blocked = _refusals_in_window(messages)
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
            # …AND IT ACTUALLY HAPPENED. A call cria refused wrote nothing, whatever its words say,
            # and a write whose bytes are already what is on disk changed nothing either.
            refused = any(_actions_match(sig, d) for d in denied)
            if not matches and _is_progress(sig, args) and not refused \
                    and not _rewrites_the_same_bytes(sig, last_write):
                # a real move — reset the hunt for ACTIONS, but keep (in-window) write
                # signatures: the per-file rule ("same file, same content, 3× in the
                # window") must survive interleaved progress on OTHER files
                gs.recent_actions = [e for e in gs.recent_actions if e[1][0] == "write"]
                gs.recent_actions.append((gs.action_seq, sig))
                continue
            gs.recent_actions.append((gs.action_seq, sig))
            # …OR CRIA HAS SIMPLY BLOCKED IT, OVER AND OVER. The rule above asks whether the last
            # three actions were the SAME action; an install loop is not that. Replayed over cycle 4
            # cell 13's real 48 forwarded calls with their real tool results, the signature rule
            # fires ZERO times against nine refusals — the three attempts inside one window score
            # Jaccard 0.636 against a 0.7 bar, and cleaning the `tail -5` / `tail -10` noise lifts
            # them to a match and still yields two, not three. The loop is twenty different attempts
            # at ONE goal, which no similarity threshold can see.
            #
            # What cria has that needs no similarity judgement is its OWN refusals. It blocked 9 of
            # 48 calls in that run and 6 of 45 in the sibling, and it knows it blocked them (#8: the
            # deterministic half gathers a fact cria owns). Same threshold, same window, same
            # redirect — this only makes the existing mechanism REACHABLE by a second route.
            blocked_fires = (blocked >= REPEAT_FINGERPRINT_N
                             and gs.action_seq - gs.blocked_fired_seq >= REPEAT_WINDOW)
            if (matches + 1 >= REPEAT_FINGERPRINT_N or blocked_fires) \
                    and not gs.redirect_due and not gs.redirect_probe \
                    and not gs.spin_probe_due and not gs.spin_probe:
                if blocked_fires:
                    gs.blocked_fired_seq = gs.action_seq
                gs.redirect_due = True
                # flush BOTH windows: one intervention consumes the evidence — the writes
                # that fired this redirect must not ALSO count toward a wheel-spin right
                # after the coder complies (that steer would point away from the very file
                # it just fixed).
                gs.recent_actions = []
                gs.recent_writes = []
                # BOUND IT. This string is pasted into the coder's redirect verbatim, and for a
                # write it carried the WHOLE file body. Walked on
                # ada-handles_fabliq_codex_pon_1785732102 call 0079: cria re-sent the exact 3.2 KB of
                # handle_resolver.py it was telling the model to stop producing, under the words
                # "Choose a DIFFERENT next action". The model satisfied that literally — same 3.2 KB,
                # new filename — and did it again three calls later. That is where test_handle.py and
                # resolver.py came from: cria handed over the content and asked for something
                # different, so the only thing left to vary was the name.
                #
                # The line below already clips this same string to 120 chars for cria's OWN log. It
                # was bounded for the record and unbounded for the model.
                gs.repeat_action = _clip(f"{name} {args}", REPEAT_ACTION_CHARS)
                rlog.emit("loop.repetition", step=step, tool=name,
                          count=REPEAT_FINGERPRINT_N, args=_clip(args, 120))


# How much of the repeated action the redirect quotes back. Enough to IDENTIFY it (tool + path +
# the leading args); never enough to re-supply a file body the model would otherwise have to retype.
REPEAT_ACTION_CHARS = 200


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


# How many acting coder turns a STEP may run before cria asks its own critic whether it is done.
# MEASURED over every captured session (2026-08-05), counting consecutive coder calls between two
# critic calls: n=806 stretches, median 5, p90 56, max 282 — and 149 stretches of 30+ turns hold
# 11,831 of the 15,896 coder calls on the box. 74% OF ALL CODER WORK HAPPENS IN A STRETCH WHERE CRIA
# NEVER ONCE ASKS WHETHER THE STEP IS DONE. 12 sits far above the median, so ordinary work never
# reaches it, and well below the tail this exists for.
STEP_CHECK_EVERY = 12


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
    outcome = read_gate(gs.gate_plan, probe, rlog)
    # A periodic check-in speaks ONLY when there is a real PROBLEM to fix. On a CLEAN result it stays
    # SILENT — prodding a passing check-in with "the checks pass but that's not proof of correctness"
    # just makes the model distrust the pass and keep working (feeding the can't-stop spiral).
    err = gate_error_text(outcome)
    rlog.emit("loop.periodic_gate_result", ran=outcome.ran, spoke=bool(err))
    # THE SHARED MIRROR (record_gate_state). This was a fourth hand-written copy, and what it left
    # out was `last_gate_ran` — so a periodic check-in that ran was indistinguishable from one that
    # never happened to every later reader of that field. `gate_fresh` is DELIBERATELY not part of
    # what a periodic check-in claims: the coder has not said done, so its clean result must not
    # pre-satisfy the completion backstop for a 'done' that comes later. That is the one field this
    # path owns differently, and it is restored right after.
    fresh_before = gs.gate_fresh
    record_gate_state(gs, outcome, err)
    gs.gate_fresh = fresh_before
    if not err and outcome.ran and (lost := passing_test_regression(gs, outcome.report)):
        rlog.emit("loop.tests_regressed", level="warning", high=gs.tests_passed_high)
        return prompts.render("periodic_gate", truth=lost)
    # a couldn't-run probe leaves last_gate_red + the streak unchanged — no evidence either way
    if not err:
        return None  # clean or couldn't-run → nothing to fix → stay silent, don't editorialize a pass
    return prompts.render("periodic_gate", truth=err)


# A closed question cria asks a reasoner. THE QUESTION GOES IN THE USER TURN. cria used to put the
# whole thing in `system` and send `user: ""` — walked on maple-preview 1786228135 call 0092, where
# the prompt was `system(2658 chars) + user(0 chars)` and the model answered "We need to parse the
# user's message. It's just a single period." A model looks for the ask where an ask lives; an empty
# user turn is cria asking nothing and grading the answer.
_ASK_USER_TURN = "Answer the question above."


def ask_closed(chat_fn, role, question: str, rlog, *, phase: str, max_tokens: int = 1024) -> str:
    """ONE primitive for every closed question cria puts to a reasoner — reasoning off, temperature
    0, the question in the user turn where the model looks for it. Returns "" on anything unreadable,
    which every caller already treats as "no answer"."""
    return summarize(chat_fn, replace(role, reasoning="off") if role is not None else None,
                     question, _ASK_USER_TURN, rlog, phase=phase, max_tokens=max_tokens,
                     temperature=0.0) or ""


def summarize(chat_fn, role, system: str, user: str, rlog, *, phase: str = "compactor",
              max_tokens: int = 8192, retry_off: bool = True, coder_tools: str = "",
              capture: list | None = None, temperature: float | None = None) -> str:
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
    exec_command right there). Compaction/summarization callers leave it empty (not reasoning about acts).
    ``capture`` (opt-in): a list the RAW completion of each pass is appended to, in order, so a caller
    that needs more than the text can have it. summarize returns "" on a truncated or tool-call reply
    and thereby discards the reasoning behind it — which is exactly the channel the steer author's
    answer-vs-thinking recovery must read (:func:`_steer_from_reasoning`). Capturing does not change
    what is returned; capture[0] is always the reasoning-ON pass."""
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
        if temperature is not None:
            # AFTER role.apply, so it wins over the role's sampling. summarize is the primitive
            # behind two very different jobs: writing prose (a briefing, a directive), where the
            # role's temperature belongs, and answering a CLOSED question with one word from a fixed
            # set (STANDS/REFUTED, DICTATES/DESCRIBES, ON_TRACK, YES/NO). The second is a
            # classification, and cria already pins temperature 0 for every classification that goes
            # through _judge_completion — these four had been running at the reasoner role's 0.6.
            # MEASURED by replaying the captured guard prompts against a live model, 8 samples each:
            # at 0.6 the steer-code guard answered correctly 7/8 and 6/8 on two real directives that
            # were full of literal code; at 0 it answered correctly every time. A one-word verdict
            # has no use for sampling diversity — the dice only ever cost accuracy.
            call["temperature"] = temperature
        try:
            rlog.phase = phase + ("-noreason" if reasoning_off else "")
            applied = massage.apply(_parse_completion(chat_fn(call, rlog)), None, rlog)
            if capture is not None:
                capture.append(applied)   # BEFORE any of the rejections below discard it
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
            # The WHOLE namespace: this is the summarizer's own reply, so a cria marker in it is the
            # model's. A briefing that opens `⟦ctx:rollup⟧`/`⟦ctx:continuation⟧` in the model's voice
            # is re-injected as cria's summary and re-summarized next round — the rollup-of-a-rollup
            # selfcompact's anchor list exists to prevent.
            text = _strip_cria_banners(text, whole_namespace=True).strip()
            if massage.has_tool_call_leak(text):
                # A leaked/mangled tool call, not prose — fail this pass so the reasoning-off retry
                # fires. Returning it would inject a wall of `<|tool_call>…` garbage as the briefing.
                rlog.emit("summarize.leaked_tool_call", level="warn", phase=rlog.phase)
                return ""
            if answered_with_tool_call and not reasoning_off:
                rlog.emit("summarize.tool_call_answer", level="warn", phase=rlog.phase)
                return ""  # recovered reasoning is a plan, not a summary — force the reasoning-off retry
            if (applied.get(bodykeys.RUMINATION)
                    or (applied.get("choices") or [{}])[0].get("finish_reason") == "rumination"):
                # A STREAM CRIA ITSELF KILLED IS NOT AN ANSWER — the rule `_steer_from_reasoning`
                # already states one function over, missing from the primitive every summariser
                # shares. When the guard aborts a summariser mid-reasoning there is no content, so
                # `coerce_text_answer` recovers `reasoning_content`, and the corpse becomes the
                # summary.
                #
                # Walked on cycle 4 cell 23 (`handles-cli-node x nemotron-elastic`), twice: the
                # compactor's aborted private narration was handed to the satisfaction judge in the
                # slot where the coder's ACTION LOG belongs — "We need to continue the process. The
                # user wants a condensed log of all distinct actions… Then attempts to exec command
                # node __tests__/lookup.end2end.test.js again, error." forty times over, with not one
                # real command, exit code or error string from the session in it. The judge then
                # ruminated too and invented a log of its own, citing a README path that does not
                # exist, and the coder was handed a report about cria's judge failing.
                #
                # Failing the pass fires the reasoning-off retry, which is where a summary belongs
                # anyway: straight into content, with no reasoning to salvage.
                rlog.emit("summarize.ruminated", level="warn", phase=rlog.phase)
                return ""
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
        completion.setdefault(bodykeys.NOTES, []).append(note)


def _check_state_words(gs) -> str:
    """The check-state clause of `done_incomplete`, chosen by what actually happened.

    `guard_gate_verdict` returns None for a green gate AND for a gate that could not run, so callers
    that hardcoded the "passed" wording asserted a check they had no evidence for. The prompt file has
    carried the honest alternative since it was written, and its own header records this exact
    incident — the fix reached one of three callers. #5b, then #13."""
    words = prompts.load_map("done_check_state")
    return words["passed"] if getattr(gs, "last_gate_ran", False) else words["never_ran"]


def record_gate_state(gs: GuardState, outcome, findings: str) -> None:
    """A gate reading becomes session state HERE, and only here. Every reader calls this.

    There were three readers and two of them wrote the state inline, in their own words, with their
    own idea of which fields mattered — and the third, :func:`guard_probe_steer`, wrote NONE of it.
    That third one reads the very same probe result as the completion gate (same call id, same plan)
    and then RETURNED the steer, so on a repetition-redirect or wheel-spin turn the whole reading was
    thrown away: `last_gate_red` kept whatever the PREVIOUS gate said. A gate that went green→red on
    such a turn left cria believing green, which is the completion side of #13 failing open.

    A gate that could not RUN is a neutral non-signal: never red, never green, and it must not touch
    the stall streak (:func:`track_gate_progress` says so in its own words). It still counts as
    ATTEMPTED — the completion backstop's long-standing fail-open — so `gate_fresh` is set."""
    gs.last_gate_ran = bool(outcome.ran)
    if not outcome.ran:
        gs.gate_fresh = True     # ATTEMPTED — cria's own inability must never wedge a real 'done'
        return
    if findings:
        gs.last_gate_red = True
        gs.gate_fresh = False    # red never satisfies the completion backstop
        track_gate_progress(gs, findings)
        return
    gs.last_gate_red = False     # ran and genuinely clean → GREEN
    gs.gate_fresh = True         # fresh ground truth — the completion backstop is satisfied
    gs.last_gate_testless = not proberun.gate_ran_tests(outcome.report)  # vacuous-green evidence
    gs.last_gate_skipped = proberun.gate_skipped_count(outcome.report)
    track_gate_progress(gs, "")


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
    outcome = read_gate(gs.gate_plan, probe, rlog)
    # gate_error_text, not a private copy: it surfaces the located findings AND the checks that
    # failed without a parseable line TOGETHER. This function used to pick one or the other, which
    # is the exact contradiction gate_error_text was written to end — a turn that said "a specific
    # line could not be parsed" while a ⟦ctx:checks⟧ block in the same prompt quoted the located
    # error. Its wording lives in prompts (#22); the old one was an inline f-string here.
    findings = gate_error_text(outcome)
    record_gate_state(gs, outcome, findings)
    if not outcome.ran:
        rlog.emit("loop.gate", plan_off=True, blocked=False, gate_ran=False)  # #12: say which happened
        return None  # the checks couldn't run → accept the 'done' (fail-open, like the loop)
    return findings or None


def read_gate(plan, probe_text: str, rlog) -> "probegate.GateOutcome":
    """``interpret_gate`` for every caller, with the two things that must never be silent.

    A harness can REFUSE the gate outright — Codex's sandbox rejects the exec if the script contains a
    verb it dislikes, and a refused exec returns no section markers, which reads exactly like "no gate
    was ever composed". cria then abstains from its largest assist on every single turn and logs
    nothing. That happened for a whole 24-cell arm. The refusal now lands in the log with the harness's
    own words. It stays out of the MODEL's view: it is cria's plumbing problem, not the coder's.

    Also reports what the sweep took back, so litter removal is visible rather than assumed."""
    if plan is None:
        return probegate.GateOutcome(ran=False)
    outcome = probegate.interpret_gate(plan, probe_text)
    if outcome.refused:
        rlog.emit("loop.gate_refused", level="warn", reason=outcome.refused)
    if outcome.swept:
        rlog.emit("loop.gate_swept", paths=len(outcome.swept), sample=outcome.swept[:5])
    return outcome


def gate_error_text(outcome) -> str:
    """The ERROR-class ground truth from a gate outcome — file:line findings, or a check that RAN and
    FAILED with no parseable location. Returns '' when the gate is clean, couldn't run, or never ran.

    This is the ONLY part a PERIODIC check-in surfaces. On a clean check-in there is nothing to fix, so
    injecting the "the checks pass, but that's not proof of correct behaviour — keep fixing" hedge just
    makes the model distrust a genuine pass and keep working (it can't stop). Judging "is the task
    actually done" is the done-gate's + satisfaction check's job; the periodic gate only surfaces real
    problems early.

    NEVER SAY "no line could be parsed" WHEN A LINE WAS PARSED. The two readers below look at the
    same report and used to be exclusive: any findings at all returned early, and the unparsed
    hard-failures were dropped. When findings were empty for the probe cria happened to ask about,
    the `ground_truth_failed` wording — "a specific line could not be parsed from the output" —
    went out in the same turn as a `⟦ctx:checks⟧` block quoting the located error, with the coarse
    text quoting Maven's trailing `[Help 1]` URL instead. Measured in cycle 2 at five occurrences
    across two runs (feed-pipeline-java × qwen35 calls 0018/0045/0056/0170, × gemma4 call 0020), and
    it is the same sentence `probeparse.split_diag`'s comment already records costing the Java column
    0 / 40 / 0 / 0 in cycle 1. That fix repaired the PARSER; this one stops the two readers
    contradicting each other. Both are now surfaced together, and the "could not be parsed" framing
    is reserved for the case where nothing was.
    """
    if not outcome.ran:
        return ""
    findings = proberun.completion_block_nudge(outcome.report)
    failed = proberun.failed_unparsed_probes(outcome.report)
    if findings and failed:
        return prompts.render("ground_truth_failed_also",
                              findings=findings, failed="\n".join(failed))
    if findings:
        return findings
    if failed:
        return prompts.render("ground_truth_failed", failed="\n".join(failed))
    return ""


# A cached finding that is a TEST failure — the only class a coder-run test suite can supersede. A
# pyflakes or compileall finding is not cleared by pytest going green, so those are never dropped.
# A finding is ABOUT A TEST when its path is a test file in any language cria knows, or when the text
# carries a runner's own failure tally. Both halves defer to owners that are already generalised:
# probediscovery.TEST_CONVENTIONS knows every language's test-file convention, and
# probegate.runner_tally reads twelve runners' summary lines.
#
# The regex this replaces was `\btest[\w.]*\.\w+:\d+:` — a filename whose basename STARTS with
# "test". Checked against real findings: `tests/test_db.py:12:` matched, `test/test_rates.rb:41:`
# matched, `tests/handle-lookup.test.js:8:` matched — and `cart_test.go:22:`, `OrderTest.java:31:`
# and `tests/cli.rs:22:` did not. So the supersede below, which exists to stop cria restating
# failures the coder has already cleared, was inert in Go, Java and Rust: exactly the languages
# whose test files are named by suffix rather than prefix. Its own consumer
# (probegate.runner_tally) was properly generalised; the trigger in front of it was not.
_FAIL_WORDS = re.compile(r"(?im)\b\d+ failed\b|^FAILED\b|^\s*---\s*FAIL:|\bFAILURES?!")
_PATH_LINE = re.compile(r"(?im)^[^\n]*?([\w./\\-]+\.\w+):\d+:")


# Moved to probediscovery, which owns TEST_CONVENTIONS — execcheck needed the same answer and had
# been carrying a narrower private copy of it (#23: one owner).
def _looks_like_a_test_path(path: str) -> bool:
    from . import probediscovery
    return probediscovery.looks_like_a_test_path(path)


def _is_test_finding(checks: str) -> bool:
    if not checks:
        return False
    if _FAIL_WORDS.search(checks):
        return True
    if probegate.runner_tally(checks):
        return True
    return any(_looks_like_a_test_path(m) for m in _PATH_LINE.findall(checks))


def _checks_superseded_by_coder_run(messages: list[dict], checks: str) -> str:
    """The tally from the coder's OWN test run, when it is newer than cria's cached findings and
    green — else "". cria's cached failures are then stale and must not be restated as ground truth.

    WHY THIS EXISTS. The coder has its own shell and runs pytest itself, and cria's gate cache has no
    idea. So cria kept asserting failures the disk had already cleared, in prompts that carried the
    contradiction: run 1786047359 call 0051 got "⟦ctx:steer⟧ The repo's checks report persistent test
    failures on lines 44 and 109" two turns after the same prompt said "no error-class problems" and
    "6 passed in 0.01s"; call 0057 stacked three mutually exclusive claims under the word GROUND
    TRUTH ("executed NO tests", "6 passed", and three named failures). Run 1786053138 call 0142 said
    "unchanged since you were last shown them — you have not cleared them yet" four calls after the
    coder's own pytest printed "1 failed, 4 passed" with the named test PASSED. Five independent
    walkers, both runs. Every one of them sent the coder back into a loop it had already left.

    SCOPED BY WHAT THE GREEN RUN ACTUALLY PROVES. A green pytest says nothing about a pyflakes
    finding — an unused import fails the linter and runs fine — so an interpreted runner only
    settles a TEST finding. A runner that must BUILD before it can pass settles more than that:
    `cargo test` cannot print "test result: ok" over an unresolved import, and `go test` cannot
    print "ok <pkg>" over an undefined symbol, so a green tally from one of those is proof the
    compile error is gone too (probegate.COMPILES_FIRST).

    THAT DISTINCTION USED TO BE A PHRASE LIST over the finding's text, and it covered pytest and
    minitest while missing every compiled language — go, java and rust, three of the six battery
    families, and the ones where a stale error costs most. The question is not how the finding is
    spelled, it is what the newer run establishes (#12: read the runner cria is holding, do not
    match English in the prose cria rendered).

    And only results AFTER cria's last gate count — an older coder run is not newer information."""
    if not checks:
        return ""
    compile_class = not _is_test_finding(checks)
    msgs = messages or []
    last_gate = -1
    for i, m in enumerate(msgs):
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str) and probegate.SECTION_PREFIX in c:
            last_gate = i
    for m in msgs[last_gate + 1:]:
        if not isinstance(m, dict):
            continue
        if m.get("role") not in ("tool", "function_call_output") and m.get("type") != "function_call_output":
            continue
        c = m.get("content") if m.get("content") is not None else m.get("output")
        if not isinstance(c, str) or probegate.SECTION_PREFIX in c:
            continue
        runner, tally = probegate.runner_and_tally(c)
        if not tally or not (tally.startswith("0f/") or tally.endswith("/OK")):
            continue
        if compile_class and runner not in probegate.COMPILES_FIRST:
            continue          # a green interpreter proves nothing about a lint or compile finding
        return tally
    return ""


def _checks_ran_before(paths: list[str]) -> str:
    """The ``{{SINCE}}`` clause for ``steer_checks_repeat``: what the coder wrote since the checks ran.

    THE SENTENCE THIS REPLACED. The block used to open "unchanged since you were last shown them —
    you have not cleared them yet". cria cannot know that. It knows when the checks last RAN and that
    nothing has run them since; whether the findings still hold is settled only by a re-run, and the
    coder edits between gates. Stated as fact it outranks the model's own eyes, so the model doubts
    reality rather than doubting cria — inventing stale bytecode, a Ruby cache, an unsaved file.
    Measured on the six-language battery: 25 wrong turns, every model, five languages (#5b).

    Anchored on the coder's OWN writes, which it can find in its context — never a call or turn
    number, which is cria's private bookkeeping and resolves to nothing on the coder's side.

    NOTE for whoever edits the prompt file: `prompts.load`/`render` do NOT strip `#` lines (only
    `load_map` does), so a rationale comment placed in that file would be sent to the model verbatim.
    That is why this explanation lives here. tests/test_the_model_sees_neither_the_name_nor_the_
    numbering.py enforces it.

    Empty when cria knows of no intervening write — then the sentence reads "They last ran, and
    nothing has run them again since", which is still true and still claims no currency."""
    labels = prompts.load_map("checks_ran_before")
    if not paths:
        return labels.get("none", "").strip()
    key = "one" if len(paths) == 1 else "many"
    return prompts.fill(labels[key], files=", ".join(paths)).rstrip("\n")


def _writes_since_last_gate(messages: list[dict], cap: int = 3) -> list[str]:
    """Files the coder wrote AFTER cria's checks last ran — newest first, bounded.

    cria caches a check result and re-shows it. It cannot know the findings still hold: the coder
    edits between gates, and only a re-run settles it. What cria DOES know is exactly this — when the
    checks ran, and what has been written since. Saying that instead of "unchanged … you have not
    cleared them yet" is the difference between a fact and an assertion cria has no basis for (#5b).

    Same gate anchor as :func:`_checks_superseded_by_coder_run`, which handles the narrower case
    where the coder's own run has already proven the findings gone."""
    msgs = messages or []
    last_gate = -1
    for i, m in enumerate(msgs):
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str) and probegate.SECTION_PREFIX in c:
            last_gate = i
    out: list[str] = []
    for m in msgs[last_gate + 1:]:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            p = _write_path(tc.get("function") or {})
            if p and p not in out:
                out.append(p)
    return list(reversed(out))[:cap]


def _checks_already_visible(body: dict, checks: str) -> bool:
    """Is the check output the guard assumes the coder can see actually in this request?

    The suppression it gates was measured withholding cria's correction while nothing else carried
    it: 129 of 176 coder prompts in one run had neither the checks nor a steer. Anchored on the
    checker's own FIRST line rather than the whole block, because the block is re-rendered with
    different framing in different places and an exact-match test would answer "no" every time.
    """
    first = next((ln.strip() for ln in (checks or "").splitlines() if ln.strip()), "")
    if not first:
        return True          # nothing to re-show -> nothing withheld
    needle = first.lstrip("•").strip()[:80]
    for m in (body.get("messages") or []):
        c = m.get("content")
        if isinstance(c, str) and needle and needle in c:
            return True
    return False


def passing_test_regression(sess, report) -> str:
    """A note when the suite reports FEWER passing tests than it did earlier this session, else "".

    Two of cycle 3's twenty-four lost checks are one shape: the coder meant to APPEND a test, wrote
    the edit as a replace, and a seeded test went out with the old text. Nothing in the loop asked
    whether a turn destroyed working code — the gate runs vet/build/test and all three stay green
    with a test deleted. In cart-billing-go x gemma4 the satisfaction judge's evidence held the test
    present, the test passing, the full untruncated edit that overwrote it, and the next run with it
    gone, and it answered `satisfied: true`.

    REGRESSION-ONLY (#2). It cannot fire on a first attempt, a new suite or a still-broken one: it
    needs a green tally that was higher earlier. Deletion is the dangerous shape and this is the one
    signal that sees it.

    FROM THE RUNNER'S OWN TALLY (#12) — `probegate.gate_passing_tests` reads twelve runners' summary
    lines, so this is language-agnostic by construction (#20) rather than by a list of test-file
    conventions. -1 means no runner printed a tally cria recognises, which is silence, not zero.

    IT STATES THE FACT, IT DOES NOT ACCUSE (#2's corollary, #5b). A count can legitimately drop when
    two tests are merged into one, so cria reports what the runner reported and leaves the judgement
    to the coder — which is also what makes it safe to speak on a GREEN gate at all (#3)."""
    passed = probegate.gate_passing_tests(report)
    if passed < 0:
        return ""                       # no tally → no signal, and no guess
    high = getattr(sess, "tests_passed_high", 0)
    if passed >= high:
        sess.tests_passed_high = passed
        return ""
    return prompts.render("tests_regressed", was=str(high), now=str(passed))


def _gate_notes(sess) -> str:
    """Ground-truth notes for the satisfaction judge about what the gate's test run actually
    verified (prompts/gate_notes.txt): the C4 vacuous-green (0 collected) and the skipped-count fact
    (0728-m11: live tests skipTest() on the exact failure that proves the deliverable broken, and
    "3 passed, 2 skipped" read as green). Empty when there is nothing to disclose — silence over
    noise, and never a doubt-hedge on a clean run."""
    lines = prompts.load_map("gate_notes")
    # RED FIRST. A step may now advance over a red gate the step critic attributed to another step's
    # work (_verify_after_probe), so the plan can reach its end with the checks still failing — which
    # was structurally impossible before, and is the one way this change could have opened a
    # fail-OPEN on completion (principle 13). The judge gets the failure as a fact and holds the task.
    if getattr(sess, "last_gate_red", False) and getattr(sess, "last_gate_flag", ""):
        return "\n\n" + prompts.fill(lines["red"], findings=sess.last_gate_flag.strip())
    if getattr(sess, "last_gate_testless", False):
        return "\n\n" + lines["testless"]
    skipped = getattr(sess, "last_gate_skipped", 0)
    if skipped:
        return "\n\n" + prompts.fill(lines["skipped"], count=str(skipped))
    # …AND THE GREEN, LAST, for the seat deciding whether the work is FINISHED. Last because every
    # disclosure above it describes a pass that does not mean what it looks like — a red gate, a run
    # that executed no tests, a run that skipped some — and each of those must win over a plain
    # "it passed". See the prompt file for the run this cost.
    #
    # Gated on the gate having actually RUN and still being fresh: `gate_fresh` goes false the moment
    # the workspace may have moved under the reading, and a green cria cannot vouch for right now is
    # worse than none (#5b, #11b).
    if (getattr(sess, "last_gate_ran", False) and getattr(sess, "gate_fresh", False)
            and lines.get("green")):
        return "\n\n" + lines["green"]
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
# is a cheap deterministic TRIGGER; the steer itself is always REASONED here, grounded in the real
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
}


# cria's own web_fetch render header — `HTTP 200 OK · https://…` — and the endpoints outline it adds
# for a spec.
#
# THE SHAPE IS NOT WHAT SEPARATES THEM; THE ROLE IS. This comment used to claim the ` · <url>` form
# "appears ONLY in a real rendered result, never in the coder's prose", and the reader below refutes
# it in detail: the coder READS that header in its own context and can parrot it, and one did —
# "I tried again and got HTTP 400 · <url>" overwrote a real HTTP 200 and filed the URL under "THESE
# URLS DID NOT WORK". What makes the ledger trustworthy is that :func:`_extract_fetches` reads TOOL
# RESULTS ONLY. The pattern is a renderer, not a provenance test.
_FETCH_STATUS_RE = re.compile(r"HTTP (\d{3})[^\n·]*·\s*(https?://\S+)")
# Greedy to the LAST `]` ON THE LINE, not the first: a GraphQL discovery entry names a list type
# as `[Handle]`, and stopping at the first bracket cut every route after it out of the ledger.
# `.` excludes newlines, so this still cannot run past the marker line.
_FETCH_ROUTES_RE = re.compile(r"\[API endpoints \(\d+\): (.+)\]")
# The RESPONSE-SHAPE block cria surfaces beside the routes (webfetch.SHAPE_MARKER). It is the half of
# the surfaced facts that names the real FIELDS, and it was never captured into the durable ledger —
# so after a compaction the coder kept the endpoints and lost `resolved_addresses{ada}` / `holder`,
# which is precisely what it then guesses. Multi-line; ends at the block's closing bracket.
def _catalog_block(text: str, start: int) -> str:
    """The `[API descriptions — …]` block beginning at/after ``start``, read by LINE — same reasoning as
    :func:`_shape_block` (a url can contain `]`, and entry lines are the ones carrying `→`)."""
    return _marker_block(text, start, webfetch.CATALOG_MARKER)


def _shape_block(text: str, start: int) -> str:
    """The `[response shape — …]` block beginning at/after ``start``, read by LINE.

    A regex terminated on `]` cannot work here: a field summary marks an array field as `k[]`, so the
    first entry line ending in an array closes the match and every endpoint after it is silently lost
    — measured, that dropped `/holders/{address} → total_handles`, the second call this task needs,
    from the durable ledger the coder is told to "use these EXACT names ... do not guess" from.

    Entry lines are the ones carrying `→`; a trailing note (webfetch's "…+more endpoints have shapes
    not shown here") is kept too, because a cap the model cannot see reads as the complete set."""
    return _marker_block(text, start, webfetch.SHAPE_MARKER)


def _marker_block(text: str, start: int, marker: str) -> str:
    """The cria-authored block introduced by ``marker`` at/after ``start``, read by LINE (see
    :func:`_shape_block` for why a regex cannot do this). ONE reader for every such block, so a second
    marker cannot drift into a second, subtly different parser."""
    i = text.find(marker, start)
    if i < 0:
        return ""
    lines = text[i:].splitlines()
    out = [lines[0][len(marker):].strip()] if lines else []
    # Two entry grammars, ONE reader. The old render is one `GET /x → f1, f2{a,b}` line per
    # endpoint. The 2026-08-07 render (operator's format) is an endpoint head ending `returns:`
    # followed by a ```ts fence of `name?: type;` lines. The day that format landed, this reader —
    # keyed on `→` alone — kept the marker's header and dropped every field: the durable ledger
    # carried routes and ZERO response shapes, the judges' sources block promised "response fields
    # it defines:" and delivered nothing after the colon (walked, mellum2 1786196176 calls
    # 0021/0028 — one judge hallucinated the fields), and the phantom-field steer guard went blind.
    # Fence state makes the TS block self-delimiting; everything else keeps the old rule.
    fence = False
    for ln in lines[1:]:
        t = ln.strip()
        if fence:
            out.append(ln.rstrip())
            if t.rstrip("]") == "```":     # the render closes the whole block as ````]` — one line
                fence = False
            continue
        if t.startswith("```") and t != "```":
            fence = True
            out.append(ln.rstrip())
            continue
        if "→" in ln or t.startswith("…") or t.endswith("returns:"):
            out.append(ln.rstrip())
            continue
        break
    block = "\n".join(x for x in out if x.strip()).strip()
    # Drop the block's closing bracket — but never mistake an ARRAY field for it: `holders[]` ends in
    # `]` too, and stripping that turns a real field name into `holders[`.
    return block[:-1].rstrip() if block.endswith("]") and not block.endswith("[]") else block


# ONE reader for the ledger tuple, in groundtruth — planner cannot import loop, and both plan
# judges need it. Kept as a module-level name here because a dozen call sites read it.
_fetch_facts = groundtruth.fetch_facts


def _extract_fetches(messages: list[dict]) -> dict:
    """url -> (status, routes, shapes) for every web_fetch result in ``messages`` (last occurrence
    wins), read from the REAL rendered tool headers — TOOL RESULTS ONLY, which is what makes this a
    ledger of what happened rather than of what the coder said happened. The ` · <url>` shape is
    cria's render, but the coder reads it in its own context and can parrot it, so the shape alone
    proves nothing; see the note at `_FETCH_STATUS_RE` and the one on the role filter below."""
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
                           _shape_block(c, sm.end()), _catalog_block(c, sm.end()))
    return latest


def _merge_fetches(dst: dict, src: dict) -> dict:
    """Merge fetch facts, keeping the RICHER routes AND shapes per URL: a later ``web_fetch(url,
    find=…)`` returns a sub-section WITHOUT the ``[API endpoints]`` / ``[response shape]`` blocks, so
    those are empty — that must not clobber an earlier full outline (they are the whole point of the
    fact: they name /handles/{handle} and resolved_addresses{ada})."""
    for url, entry in src.items():
        status, routes, shapes, catalog = _fetch_facts(entry)
        prev = dst.get(url)
        if prev:
            p_routes, p_shapes, p_catalog = _fetch_facts(prev)[1:]
            routes = routes or p_routes   # preserve the earlier outline when this occurrence had none
            shapes = shapes or p_shapes
            catalog = catalog or p_catalog
        dst[url] = (status, routes, shapes, catalog)
    return dst


# ONE OWNER (research.fetch_succeeded). Two copies of "did this fetch work?" is how the research
# exit ended up reading only the bare-int spelling while every ledger in play carried "HTTP 200".
_fetch_succeeded = research.fetch_succeeded


# `{param}` in a route template stands for one path segment, never a slash.
_ROUTE_PARAM = re.compile(r"\{[^{}/]*\}")
# "(replace in the URL path: {address} = The stake/enterprise/script/other address of the Holder)"
_PARAM_DESC = re.compile(r"\(replace in the URL path:\s*(\{[^}]+\}[^)]*)\)")


def _route_templates(latest: dict) -> list[str]:
    """Every route the spec defined, across every fetch this session. cria parsed these itself."""
    seen: list[str] = []
    for entry in (latest or {}).values():
        for r in (_fetch_facts(entry)[1] or "").split(","):
            r = r.strip()
            if r.startswith("/") and r not in seen:
                seen.append(r)
    return seen


def _param_descriptions(latest: dict) -> dict[str, str]:
    """route template -> the spec's own description of its path parameter, where cria rendered one."""
    out: dict[str, str] = {}
    for entry in (latest or {}).values():
        for line in str(_fetch_facts(entry)[2] or "").splitlines():
            m = _PARAM_DESC.search(line)
            if not m:
                continue
            route = line.strip().split()[1] if len(line.strip().split()) > 1 else ""
            if route.startswith("/"):
                out.setdefault(route, m.group(1).strip())
    return out


def _failed_fetch_diagnosis(url: str, latest: dict) -> str:
    """The one narrow true sentence about THIS failed URL — wrong route, wrong value, or silence.

    THE 2026-08-07 DOUBLE MISS. The `failed` label used to name one cause for every failure, "check
    the VALUE you put in the path", and on one day it was wrong in both directions:

      maple-preview 0014   /handle/goose       the ROUTE was wrong (singular) — cria said check the value
      mellum2       0019   /holders/addr1q…    the VALUE was wrong — a sibling note said compare the routes

    Both times cria sent the coder to inspect the half that was already right. maple's coder decided
    "goose is not a valid Ada handle", never recovered, and the live test scored zero.

    cria never had to guess. It composed this ledger, so it holds the spec's route list and the URL
    that failed, and matching one against the other is arithmetic. When no fetch this session yielded
    a route list there is nothing to match and this says NOTHING — silence over a guess (principle 3).
    """
    routes = _route_templates(latest)
    if not routes:
        return ""
    try:
        path = urllib.parse.urlsplit(url).path or "/"
    except ValueError:
        return ""
    labels = prompts.load_map("fetched_facts_sections")
    for tmpl in routes:
        if re.fullmatch(_ROUTE_PARAM.sub("[^/]+", re.escape(tmpl).replace("\\{", "{").replace("\\}", "}")),
                        path.rstrip("/") or "/"):
            desc = _param_descriptions(latest).get(tmpl, "")
            return (prompts.fill(labels["bad_value"], param=desc) if desc
                    else labels["bad_value_bare"])
    # Not a route. Name the closest real one ONLY when it is a near miss — a wrong guess at "closest"
    # is the phantom-path fault, and "/handles/{handle}" for "/handle/goose" is worth its own sentence
    # while a scattershot suggestion is worth none.
    near = _nearest_route(path, routes)
    nearest = (prompts.fill(labels["bad_route_nearest"], route=near) if near
               else labels["bad_route_bare"])
    return prompts.fill(labels["bad_route"], nearest=nearest)


# A literal segment must be THIS close to the route's to count as a typo of it. `handle`/`handles`
# scores 0.92; `handle`/`holders` scores 0.62 and must not be offered as "the closest one".
_TYPO_RATIO = 0.8


def _nearest_route(path: str, routes: list[str]) -> str:
    """The one route a failed path is plainly a typo of, or "".

    Same segment count, exactly one literal segment differing, and that segment close enough to be a
    slip rather than a different word. Ties return "" — naming one of two equally-close routes is the
    invented-path fault, and this whole helper exists because cria guessed."""
    segs = [p for p in path.split("/") if p]
    scored: list[tuple[float, str]] = []
    for tmpl in routes:
        t = [p for p in tmpl.split("/") if p]
        if len(t) != len(segs):
            continue
        differing = [(a, b) for a, b in zip(segs, t)
                     if not (a == b or (b.startswith("{") and b.endswith("}")))]
        if len(differing) != 1:
            continue
        a, b = differing[0]
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        if ratio >= _TYPO_RATIO:
            scored.append((ratio, tmpl))
    scored.sort(reverse=True)
    if not scored:
        return ""
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return ""    # two equally-close candidates — naming one would be a guess
    return scored[0][1]


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
        status, routes, shapes, catalog = _fetch_facts(entry)
        line = f"- {url} \u2192 {status}" + (f"; endpoints: {routes}" if routes else "")
        # THIRD case. The anchor explains an entry WITH facts and an entry that ERRORED; a 2xx whose
        # page had no readable structure looks identical to a successful spec read. Measured (run
        # 0727-142536): the planner fetched the swagger UI SHELL, the coder's entire fetch record was
        # one `→ HTTP 200` under "these SUCCEEDED", and it invented `/resolve/{handle}` with zero
        # occurrences of the real route in its window. A status alone is a fact about the REQUEST.
        # ...but the note may only say what is TRUE. Its old wording — "no endpoints or field names
        # could be read from it ... the source that DEFINES them is still unread" — is written for a
        # SPEC page and is false about a plain DATA response, which legitimately has no OpenAPI
        # structure while its body is right there in the transcript with its field names in it.
        # Walked on ada-handles_mellum2_codex_poff_1785686596, where cria attached it to
        # `/handles/goose → HTTP 200` in a prompt whose line 87 is that page's full body, `holder`
        # and `resolved_addresses.ada` included. The reasoner believed cria over the transcript —
        # the block is headed GROUND TRUTH — and authored the steer that told the coder the API
        # "returns 404 for every request" and offered to "remove the live test from the suite
        # entirely". The coder did. That was two of the four deliverables.
        #
        # And "the source that DEFINES them is still unread" is checkable, not a guess: cria composed
        # this ledger, so it knows whether ANY fetch this session yielded routes. When one did, the
        # sentence is simply false and is dropped. All that survives is the true, narrow fact — this
        # URL yielded no endpoint definitions — which is what the swagger-shell case needed.
        if _fetch_succeeded(status) and not routes and not shapes.strip() and not catalog.strip():
            any_routes = any(_fetch_facts(e)[1] for e in latest.values())
            line += labels["no_spec_here" if any_routes else "no_structure"]
        # The REAL field names — the half the coder guesses once they scroll away. Keep only the
        # per-endpoint entry lines: the captured block opens with webfetch's OWN header, and emitting
        # that under cria's label prints the same instruction twice.
        entries, fence = [], False
        for ln in shapes.splitlines():
            t = ln.strip()
            if fence:
                entries.append(ln.rstrip())
                fence = t != "```"
            elif t.startswith("```") and t != "```":
                entries.append(ln.rstrip()); fence = True
            elif "→" in ln or t.startswith("…") or t.endswith("returns:"):   # old render + cap note
                entries.append(t)
        if entries:
            line += f"\n  {labels['fields']}\n" + "\n".join(f"  {e}" for e in entries)
        # A catalogue names WHERE each API's spec lives. Without this the durable ledger recorded the
        # fetch as "HTTP 200, no readable structure" and the hrefs — the only thing a catalogue has —
        # were gone the moment the raw result scrolled out.
        cat = [ln.strip() for ln in catalog.splitlines() if "→" in ln or ln.strip().startswith("…")]
        if cat:
            line += f"\n  {labels['descriptions']}\n" + "\n".join(f"  {c}" for c in cat)
        if not _fetch_succeeded(status):
            diagnosis = _failed_fetch_diagnosis(url, latest)
            line += f" {diagnosis}" if diagnosis else ""
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


def _fetched_facts_anchor(sess, messages: list[dict] | None = None) -> dict | None:
    """A ⟦ctx:facts⟧ anchor carrying cria's DURABLE fetch ledger (url→status→endpoints), re-injected into
    the coder's OUTBOUND view every turn there are facts — so the coder KEEPS the real endpoints/fields it
    already fetched even after the HARNESS compacts the raw tool result out of its OWN history. cria's own
    anchoring can't protect that: it only ever sees what the harness sends, and the harness compacts before
    the request arrives. But cria controls the view it sends UPSTREAM to the model, so it re-injects the
    ledger from its server-side memory. Without it the coder re-fetches a spec whose routes cria already
    surfaced (observed live: 370 calls re-reading api.handle.me/openapi.json, its /handles/{handle} outline
    scrolled off; 0 of the last 20 coder prompts still held it). GENERAL: fires only when real fetches exist
    (sess.fetched_pages); a task with no web_fetch (a bash/git chore) has an empty ledger → nothing injected.
    Additive ground truth — the real tool results, never a claim about work not done.

    ``messages`` IS NOT OPTIONAL IN PRACTICE. It was `[]` here, and that made the same-host mismatch
    fact — the one that says "cria's own fetch of this host returned 200, your code got 403, compare
    the two requests" — structurally unable to reach the coder: `_route_mismatch_fact` finds the
    coder's HTTP failure by scanning the messages, so an empty list always yields "". Every other
    caller of `_fetch_ground_truth` passes real messages, and every one of them is a cria-INTERNAL
    reader: the step critic, the steer author, the blames-the-service guard. Walked on mellum2
    1786137318: the diagnosis appears in reasoner prompts 0037, 0038, 0045 and 0046 and in ZERO
    coder prompts, while the coder spent 24 calls concluding the sandbox had no network. The fix's
    own docstring says it exists because "four separate steers instead told the coder the sandbox
    blocked the network" — and it could never have prevented that from here."""
    ledger = _fetch_ground_truth(messages or [], sess, header="PAGES YOU HAVE ALREADY FETCHED")
    if not ledger.strip():
        return None
    return {"role": "user", "content": prompts.render("fetched_facts_anchor",
                                                       marker=selfcompact.FACTS_MARKER, ledger=ledger)}


# An anchor block is the DESIGNATED single copy of its content: folding it into a pointer at a later
# duplicate would move the content out of the protected head. Mirrors selfcompact._ANCHOR_MARKERS
# (a test asserts sync) plus the denial marker, whose repetition IS the signal.
_ANCHOR_MARKERS_FOR_DEDUP = (selfcompact.FACTS_MARKER, selfcompact.TASK_MARKER,
                             selfcompact.SUMMARY_MARKER, BRIEFING_OPEN, CONTINUATION_MARKER)


def _elide_ledger_copies(msgs: list[dict], sess, rlog=None) -> list[dict]:
    """ONE copy of the fetch ledger per outbound view. The ⟦ctx:facts⟧ anchor just injected is the
    owner; byte-identical copies elsewhere — the compaction summary's fetch-facts appendix (baked
    in by server._harden_compaction_reply, redundant every call the anchor also rides), and the
    identical field-shape lines inside the original fetched-page result — collapse to a one-line
    pointer. Measured on the maple full walk: the ~2.4KB field block rode up to 3× per prompt.
    Byte-exact, aggregate-lossless, identity when nothing matches (see cria/dedup.py)."""
    ledger = _fetch_ground_truth([], sess, header="PAGES YOU HAVE ALREADY FETCHED")
    out, n = dedup.elide_from_messages(msgs, dedup.ledger_units(ledger),
                                       prompts.load("ledger_dedup_note"),
                                       skip_prefix=selfcompact.FACTS_MARKER)
    if n and rlog is not None:
        rlog.emit("context.ledger_dedup", excised=n)
    # …and the same rule for whole messages the harness repeated verbatim, which the ledger units
    # cannot reach: a file read twice, cria's own refusal re-earned, one page delivered twice.
    # Measured at 13% of coder prompts and 2.2 MB. See dedup.fold_repeated_messages.
    out, folded = dedup.fold_repeated_messages(
        out, prompts.load("repeated_message_note").strip(), protect=_ANCHOR_MARKERS_FOR_DEDUP)
    if folded and rlog is not None:
        rlog.emit("context.repeat_dedup", folded=folded)
    return out


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
    out = _format_fetches(latest, header)
    mismatch = _route_mismatch_fact(latest, messages,
                                    getattr(sess, "workspace_root", "") or "")
    return f"{out}\n\n{mismatch}" if mismatch else out


# An HTTP failure the CODER's own process ACTUALLY HIT, in the exact form a RUNTIME prints it.
#
# THE FIRST CUT MATCHED A BARE `HTTP 404` AND SHIPPED A FALSE FACT. Test files are full of status
# codes that were never received: docstrings ("""Test handling when a handle is not found (HTTP
# 404)."""), mock constructors (HTTPError("url", 404, "Not Found", {}, None)), assertions
# (self.assertIn("404", ...)). A `cat` or `read_file` of such a file is a tool result, so the
# scraper read source as observation. Measured on maple-preview 1786062317: `(HTTP 404)` appears
# 148 times and `HTTP 404` 24 times — ALL from the test file — while the coder's real failures were
# 403. cria told its own reasoner "Your code got HTTP 404 from that same host" in four prompts. No
# request in that run ever returned 404. That is rule 5b broken by the check written to uphold it.
#
# So: only the shapes a runtime emits, never a shape source code can contain.
#   urllib   `urllib.error.HTTPError: HTTP Error 403: Forbidden`  → "HTTP Error <code>"
#   requests `403 Client Error: Forbidden for url: …`             → "<code> Client/Server Error"
#   curl/httpx/go `HTTP/1.1 403 Forbidden`                        → "HTTP/x.y <code>"
# Counted over that same capture: 18 hits, every one a real 403; zero false hits.
# A program that catches the error and prints its own prose ("Error: … (HTTP 403)") is MISSED on
# purpose — a miss shows the coder nothing, a false fact sends it somewhere wrong.
# THE DISCRIMINATOR IS THE REASON PHRASE. A status a server really returned is printed with the
# reason it came back with — `403: Forbidden`, `(HTTP 403): Forbidden`, `500 Internal Server Error`.
# A status in source code is not: a docstring ends `(HTTP 404).`, a mock constructor writes
# `404, "Not Found"` with a COMMA, an assertion writes `assertIn("404", …)`. Requiring `<code>:` +
# a capitalised reason keeps every observed failure in both walked runs — 1786047359's
# `Error resolving handle: HTTP 403: Forbidden` and 1786062317's
# `urllib.error.HTTPError: HTTP Error 403: Forbidden` — and rejects all 172 source mentions.
_CODER_HTTP_FAIL = re.compile(
    r"(?:HTTP\s+Error\s+([45]\d{2})\b"                       # urllib runtime
    r"|\b([45]\d{2})\s+(?:Client|Server)\s+Error\b"          # requests runtime
    r"|\bHTTP/\d(?:\.\d)?\s+([45]\d{2})\b"                   # a raw status line
    r"|\b([45]\d{2})\)?:\s+[A-Z][A-Za-z]{2,}(?:\s[A-Za-z]+){0,3})")   # <code>: Reason Phrase
_HOST_IN_TEXT = re.compile(r"https?://([A-Za-z0-9.-]+)")


def _host_in_workspace_code(root: str, host: str) -> bool:
    """Does the coder's OWN source name this host? The grounded link between "cria reached H" and a
    bare `HTTP 403` in the coder's output, which carries no URL of its own (measured: every one of
    run 1786047359's eight failures printed only `Error resolving handle: HTTP 403: Forbidden`).
    Searching the conversation instead would be circular — cria's own ledger puts the host there."""
    if not root or not host or not os.path.isdir(root):
        return False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in execcheck._SKIP_DIRS]
        for name in filenames:
            if not name.endswith((".py", ".js", ".mjs", ".ts", ".go", ".rs", ".rb", ".java", ".php",
                                  ".sh", ".json", ".toml", ".yaml", ".yml")):
                continue
            try:
                if host in open(os.path.join(dirpath, name), errors="replace").read():
                    return True
            except OSError:
                continue
    return False


def _diagnosis_clause(url: str, ledger: dict) -> str:
    """`_failed_fetch_diagnosis` as its own sentence, or "" — ONE owner of route-vs-value.

    The ledger appends it to `→ HTTP 404`, so it is written to follow a status and opens with a dash.
    Here it follows a full stop. Same words, re-punctuated — not a second wording to keep in step."""
    d = _failed_fetch_diagnosis(url, ledger).lstrip(" —-").strip()
    return f" {d[0].upper()}{d[1:]}" if d else ""


def _route_mismatch_fact(ledger: dict, messages: list[dict], workspace_root: str = "") -> str:
    """One stated fact when cria reached a host that the coder's OWN code could not — else "".

    THE DIAGNOSIS cria held and never said, in run 1786047359. Its ledger recorded
    `https://api.handle.me → HTTP 200` in every prompt; the coder's script got `HTTP Error 403:
    Forbidden` from that same host, eight times. The difference is the User-Agent — cria's fetcher
    sends a browser one, urllib sends `Python-urllib/3.12`, and Cloudflare refuses the second. cria's
    own tool description already warns about exactly this, and the reasoner's own prompt already
    carries the rule in prose ("that mismatch IS the diagnosis"). Prose is not a computation: four
    separate steers instead told the coder the sandbox blocked the network, a satisfaction judge
    certified it, and the coder wrote that falsehood into two shipped documents. live_test MISS.

    Both halves are things cria OBSERVED — its own fetch outcome, and the coder's own tool output —
    so this states them, names the one difference cria actually knows about, and prescribes nothing
    beyond "compare the two". It cannot fire on a host cria never reached, and it cannot fire on a
    coder failure with no host attached."""
    ok_hosts = {}
    for url, entry in (ledger or {}).items():
        status = (tuple(entry) + ("", "", ""))[0]
        m = _HOST_IN_TEXT.match(str(url))
        if m and research.fetch_succeeded(status):
            ok_hosts.setdefault(m.group(1), str(status))
    if not ok_hosts:
        return ""
    for m in messages or []:
        if m.get("role") not in ("tool", "function_call_output") and m.get("type") != "function_call_output":
            continue
        c = m.get("content") if m.get("content") is not None else m.get("output")
        if not isinstance(c, str):
            continue
        # NOT CRIA'S OWN FETCH. A `HTTP 500 err · <url>` line is cria's fetcher reporting its own
        # attempt — the ledger already owns that outcome, and reading it as "the coder's code
        # failed" would let a superseded fetch of a host that later answered 200 fire the mismatch
        # against itself. The ` · ` render is exactly what _extract_fetches keys on, so the two
        # readers agree on what a cria fetch result looks like.
        if "·" in c:
            continue
        fail = _CODER_HTTP_FAIL.search(c)
        if not fail:
            continue
        code = next(g for g in fail.groups() if g)
        # The host is USUALLY absent from the failure line itself, so prefer one named in the same
        # result and fall back to the coder's own source naming it. Never to "cria reached exactly
        # one host, so it must be that one" — that is a guess, and a wrong attribution would send
        # the coder at the wrong request.
        named = [h for h in _HOST_IN_TEXT.findall(c) if h in ok_hosts]
        for host in named or [h for h in ok_hosts if _host_in_workspace_code(workspace_root, h)]:
            # THE STATUS DECIDES THE DIAGNOSIS. The first cut named the User-Agent whatever the
            # code was. mellum2 1786064398 got a REAL 404 — `Error: 404 Client Error: Not Found for
            # url: https://api.handle.me/v1/handles/goose` — because it invented a `/v1` prefix the
            # API does not have, and cria told it 23 times that the difference was its User-Agent.
            # A 404 is a wrong path; a 401/403/429 is a rejected request. Naming one cause for both
            # sent the coder at its headers while the path stayed broken.
            fail_url = next((u for u in _URL_IN_TEXT.findall(c) if host in u), "")
            ok_url = next((u for u in ledger if host in u), f"https://{host}")
            if code in _ROUTING_CODES and fail_url and fail_url != ok_url:
                # WHICH HALF IS WRONG IS NOT THIS ANCHOR'S TO GUESS. It used to end "so this is
                # about the path", which is true of a route that does not exist and false of a real
                # route given a bad parameter. mellum2 1786167643 was the second kind —
                # /holders/{address} IS defined, and the coder had put a payment address where the
                # spec asks for the holder's stake address. Told to compare the URLs against the
                # route list, it concluded "So /holders/{address} is not a valid endpoint", then
                # caught cria contradicting itself: "The fetch record says /holders/{address}
                # returns 404, but the endpoint list shows it. That's confusing."
                # `_failed_fetch_diagnosis` already answers this from the parsed route list and is
                # the ledger's owner of the question; both places now say the same sentence, or
                # (no routes parsed) neither says anything.
                return prompts.render("fetch_route_mismatch_path", host=host, ok_url=ok_url,
                                      ok_status=ok_hosts[host], fail_url=fail_url,
                                      fail_status=f"HTTP {code}",
                                      diagnosis=_diagnosis_clause(fail_url, ledger))
            if code in _REJECTION_CODES:
                return prompts.render("fetch_route_mismatch", host=host,
                                      ok_status=ok_hosts[host], fail_status=f"HTTP {code}")
            return ""   # any other class — cria has no cause it can name, so it says nothing
    return ""


# A wrong PATH (the route does not exist) versus a rejected REQUEST (the route does, the caller is
# refused). cria only speaks where it can name the difference; every other 4xx/5xx gets silence.
_ROUTING_CODES = frozenset({"404", "410"})
_REJECTION_CODES = frozenset({"401", "403", "407", "429"})
_URL_IN_TEXT = re.compile(r"https?://[A-Za-z0-9.\-]+(?:/[^\s'\"),]*)?")


# The ONE canonical family test (shelltool.is_shell_tool_name) so it can't drift — a hand-kept second
# copy had already lost `shell_command` and would leave a `shell_command` harness unflagged to the
# steer reasoner (match-by-family, principle #18). `container.exec` needs no special case now: the
# family test splits on `.` and reads `exec` as a shell token.


def _coder_tools_summary(tools, *, params: bool = True) -> str:
    """One line per tool the CODER has (name + its params) — so a reasoner authoring a steer grounds any
    action it suggests in what the coder can ACTUALLY do. Observed: the coder wavered on whether it could
    grep, with exec_command right there; a reasoner that can't see the coder's tools can't say 'run
    grep via exec_command'. The shell tool is flagged explicitly.

    THE EXEMPLARS ARE LANGUAGE-NEUTRAL, deliberately. The clause used to end "(grep, cat, sed, ls,
    find, python, pytest …)" — a fixed string, appended to every reasoner, steer-author and
    satisfaction-judge prompt in every language. All four walkers found it verbatim in the go, java,
    node, rust and ruby prompts, and on ruby it was not inert: the judge at call 0145 reached
    straight for it — "Use exec_command to run pytest or rake test" — and spent an inspection round
    on a runner the project does not have. Naming a language's tools where cria does not know the
    language is an invented fact in cria's own voice. grep/cat/sed/ls/find carry the same point
    ("this runs shell commands") without asserting anything about the project."""
    lines = []
    for t in (tools or []):
        fn = t.get("function") or t
        name = fn.get("name")
        if not name:
            continue
        param_names = list(((fn.get("parameters") or {}).get("properties") or {}).keys())
        # NAMES AND PROSE, NOT A SIGNATURE. This rendered `write_file(path, content)` — a complete
        # template for opening a call — directly beside a transcript that selfcompact defangs for
        # exactly that reason: measured over 717 reasoner calls, a prompt showing 30-59 tool-call
        # shapes was answered by imitating one 8% of the time. The judge then answers on the tool
        # channel (`<function=satisfied>`), cria discards the reply, and a finished workspace is told
        # "unverified — keep working". The parameter NAMES stay, because grounding a suggested action
        # in what the coder can actually do is why this block exists; the callable syntax goes.
        # EVERY LINE USES THE SAME ` — ` SEPARATOR, because _tool_names reads the names back OUT of
        # this block for the harness-leak check, and it keys on what follows the name.
        #
        # AND A JUDGE GETS THE NAMES WITHOUT THE PARAMETERS (`params=False`). Removing the callable
        # syntax above was the right half of this fix and it left the other half standing: measured
        # on feed-pipeline-java × qwen35, cycle 2, 28 of 82 satisfaction-family calls ended with no
        # content, no tool call and a literal `<tool_call>` block written as prose in the reasoning —
        # and the parameters in those invented calls are `justification`, `login`,
        # `max_output_tokens`, `shell`, copied straight out of this line. cria handed the judge the
        # vocabulary and then read its silence as an undecidable verdict, which fail-closed turns
        # into "not done"; twelve of those landed on a workspace already scoring 5 of 5.
        # The STEER AUTHOR keeps the parameters, because grounding a suggested action in what the
        # coder can actually do is the reason this block exists and that reason is real for a caller
        # that suggests actions. A judge rules on completeness and suggests nothing.
        notes = []
        if is_shell_tool_name(name):
            notes.append("runs ANY shell command (grep, cat, sed, ls, find …)")
        if params and param_names:
            notes.append("takes " + ", ".join(param_names))
        sig = f"{name} — {'; '.join(notes)}" if notes else name
        lines.append("  - " + sig)
    return "\n".join(lines) or "  (none advertised this turn)"


# NO REASONING WINDOW. `author_steer` took a `reasoning_window=` and rendered it into a five-line
# prompt section — "THE CODER'S RECENT PRIVATE THINKING" — plus its own entry in the authority list
# the author is told to weigh. No production caller ever passed one: its only producer was
# `_record_reasoning`, deleted with the flail detector, whose removal note already says "the window
# it kept goes with it: nothing else ever read them". What shipped on every real steer was the
# section header, the instructions for reading it, and the words "(not captured for this trigger)".
# A prompt that teaches a weak model to weigh evidence that is never there is the useless-prompting
# class; removing the leftover is the completion of that decision, not a reversal of it.
def author_steer(reasoner_chat, reasoner_role, workspace_root, gs, body: dict, rlog, *,
                 condition: str, outcome=None, truth_text: str = "", step_text: str = "",
                 ) -> str | None:
    """THE single reasoned steer author. A detector fired (``condition``); hand a no-tools reasoner the
    FULL grounded picture — the real session (scrubbed of cria's own plumbing AND the harness's own agent
    prompt), the churned files' real ON-DISK bytes and the repo's check output — and let it diagnose why the coder is stuck and give ONE
    concrete, grounded next step. Returns the directive, or ``None`` when the reasoner judges the coder is
    actually progressing (``ON_TRACK``) or yields nothing — the caller decides whether to fall back.

    We hand it the real session rather than a curated slice: a curated view is exactly what made an
    earlier steer invent a path. The one thing dropped is the harness's agent system prompt
    (:func:`_drop_harness_frame`) — that is the coder's FRAME, not part of what the coder DID, and the
    reasoner has its own supervisor prompt; every user/assistant/tool turn stays verbatim, so this is not
    the curation the note above warns against. Grounded in what actually happened (and no longer padded
    with a quarter-prompt of Codex boilerplate), it cannot hallucinate a filesystem it cannot see."""
    # SILENCE OVER A SECOND OPINION ON THE SAME FACTS. If the repo's checks have not moved since the
    # last steer, the previous directive did not land — and a small reasoner asked to explain the same
    # output again does not repeat itself, it re-guesses. Measured over 24 runs: 36% of every steer
    # cria has ever authored was a fresh prose diagnosis of check findings unchanged since the
    # previous one. g22 is what that costs: TEN consecutive steers on one pytest assertion diff, each
    # contradicting the last, while the diff sat in the coder's own context pointing at the exact
    # character ("- addr1e000…0002  ?  -"). The check output is the better steer, it is already in
    # front of the coder, and cria adding a worse paraphrase of it is the assist-as-footgun case.
    # THE FINDING-SET, WHOEVER TRIGGERED. `truth_text` is passed only by the thrash caller; the
    # repetition and wheel-spin callers pass nothing, so `checks_now` was "" for them — the guard
    # compared against an empty string, never suppressed, and then OVERWROTE the stored streak with
    # "" a few lines down, so the next thrash steer saw no streak either. Measured over five days:
    # `loop.steer_same_checks` fired ZERO times, and 318 steers passed no check text against 44 that
    # did. One session shows two redirects wiping the streak between thrash steers at stall 2, 3 and
    # 4 on one unchanged finding-set — three fresh diagnoses of one pytest state, which is precisely
    # what this guard exists to stop. `last_gate_flag` is the authoritative finding-set every other
    # seat reads (#12); taking it here makes the guard live on every trigger, not one of three.
    checks_now = (truth_text or "").strip()
    if not checks_now and gs is not None:
        checks_now = (getattr(gs, "last_gate_flag", "") or "").strip()
    # STALE FAILURES ARE NOT GROUND TRUTH. The coder runs the tests itself, out of band, and cria's
    # gate cache does not know — so cria kept restating failures the disk had already cleared, under
    # the word GROUND TRUTH, in prompts that carried the contradiction (see the helper). Dropped, not
    # reworded: cria has no fresh finding to offer, and silence beats a false one.
    superseded = _checks_superseded_by_coder_run(body.get("messages", []), checks_now)
    if superseded:
        rlog.emit("loop.steer_checks_stale", level="info", condition=condition, tally=superseded,
                  head=_clip(checks_now, 100))
        checks_now, truth_text = "", ""
    if (checks_now and gs is not None and checks_now == getattr(gs, "steered_checks_text", "")
            and not getattr(gs, "same_checks_relooked", False)):
        # ONE grounded SECOND LOOK per unchanged-findings streak (provenance audit 2026-08-04): the
        # never-re-invoke rule was measured entirely on the blind-author corpus, where a second ask
        # necessarily re-guessed (g22's ten contradicting steers). A sighted author gets exactly one
        # more considered pass at the same findings; the streak's third and later asks fall through
        # to the reattach/silence below unchanged. The flag rearms whenever the findings move.
        gs.same_checks_relooked = True
    elif checks_now and gs is not None and checks_now == getattr(gs, "steered_checks_text", ""):
        # The suppression above rests on ONE premise, stated in its own reasoning: "the check output
        # is already in front of the coder". Measured on run ada-handles_mellum2_codex_poff_1785626379
        # that premise was false for 129 of 176 coder prompts — the checks or a steer rode along in
        # only 27% of them. So cria was withholding its correction on the grounds that a better one
        # was visible, while for three turns in four nothing was.
        #
        # The answer is NOT to let the reasoner paraphrase again (that is the 36%-junk-steer problem
        # this guard exists to stop, and g22's ten contradicting steers). It is to make the premise
        # TRUE: hand back the CHECKER'S OWN LINES verbatim. cria may select which real lines to show
        # and must never substitute its own words for them — so this repeats ground truth, and
        # authors nothing.
        if not _checks_already_visible(body, checks_now):
            since = _writes_since_last_gate(body.get("messages", []))
            rlog.emit("loop.steer_checks_reattached", level="info", condition=condition,
                      since=since, head=_clip(checks_now, 100))
            return prompts.render("steer_checks_repeat", findings=checks_now,
                                  seeded_test_rule=prompts.load("seeded_test_rule").strip(),
                                  since=_checks_ran_before(since))
        rlog.emit("loop.steer_same_checks", level="info", condition=condition,
                  head=_clip(checks_now, 100))
        return None
    if gs is not None:
        if checks_now != getattr(gs, "steered_checks_text", ""):
            gs.same_checks_relooked = False   # findings moved → the one second look rearms
        gs.steered_checks_text = checks_now

    # Superseded write payloads are STUBBED to their on-disk reference (the existing compact_view
    # write_stub — restructuring, not trimming: the bytes stay on disk and the author holds
    # read_file). Without this the author's session carried every historical version whole — 49
    # copies of one function at g2-0159 — and it asserted "current state" from the pile instead of
    # reading (the latest tool-call turn keeps its full arguments: the live working set).
    # DEFANGED, and with cria's OWN past output marked as such. Two measured faults, one call:
    # mellum2 1786302864 call 0060 was shown tool-call syntax 50× and answered with a fabricated
    # exec_command plus an invented Chunk ID and addr1q… address; call 0166 read the CODER's guess
    # ("the endpoint only supports search_handles") as established fact and reversed a correct
    # earlier directive, starting a four-way flip-flop that cost 83 edits. The first is imitation
    # of a copyable template; the second is provenance — a wall of undifferentiated text in which
    # a real endpoint response and a stuck model's speculation look identical.
    session = _mark_own_notes(selfcompact.serialize(selfcompact.stub_old_write_args(
        _drop_harness_frame(probegate.clean_gate_results(
            _reasoner_session(body.get("messages", [])), getattr(gs, "gate_plan", None)))),
        defang=True))
    # recent_writes is a CONSUMABLE detector window — interventions flush it by design, which left
    # the steer author's on-disk section reading "(no files touched yet)" for an ENTIRE run (14
    # steers judging a one-character file bug blind, run 0729-gemma4) while the workspace held the
    # files. The durable source is the normalized history itself: every write the coder ever made
    # is still there as a tool_call (paths survive compaction stubs).
    touched = _touched_paths(body.get("messages", []))
    recent = list(getattr(gs, "recent_writes", None) or []) + touched if gs is not None else touched
    disk = _label_spill_entries(
        _fresh_disk_facts(workspace_root, recent, getattr(gs, "spin_path", "") if gs is not None else ""))
    if not disk and workspace_root:
        # The write history can be GONE: a harness compaction replaces the turns that carried the
        # write tool_calls, so _touched_paths — the "durable" source above — recovers nothing. What
        # then printed was "(no files touched yet)" under a header reading "trust this over the
        # transcript", i.e. cria telling the judge to believe an empty workspace over a transcript
        # that shows the files. Walked THREE times: 1785888803 calls 0122 and 0124 (both unstick
        # judges blinded, both then prescribing code already on disk) and 1785360304 call 0088
        # (`(no files touched yet)` while resolve_handle.py sat at 2,582 B, and the same prompt
        # spoke of "your current edits" fourteen lines below). The disk is the answer cria could
        # always have read — the same inventory the step critic is given.
        # …and cria's OWN spill copies in it are labelled as such: the template heads this section
        # "THE FILES IT HAS BEEN CHANGING", and on nemotron-nano 1786243834 the only entry was the
        # spilled openapi reference — file activity where the coder had produced NOTHING, feeding
        # five ON_TRACK verdicts over an untouched workspace (rule 5b, in cria's own prompt).
        disk = _label_spill_entries(workspace_inventory(workspace_root))  # same label on BOTH branches
    truth = truth_text or (guard_ground_truth(outcome) if outcome is not None else "")
    # THE AUTHORITATIVE FINDING-SET, ADDED WHEN THE COMPUTED TRUTH CARRIES NONE. `last_gate_flag` is
    # the gate's own finding-set — the object `_gate_notes` already builds the CODER's checks block
    # from, and the one `judge_satisfaction` already receives as `gate_findings=` at three call
    # sites. The steer author was the only seat reading a re-render of the transcript instead, and
    # on shipping-rates-rb x nemotron-elastic that re-render came back as "a specific line could not
    # be parsed" plus two exit codes. Writing from that, the author named
    # `test_domestic_light_parcel` with numbers from a stale failure and told the coder to set the
    # constant the LIVE failing test asserts is 12.0 to 0.0 — while the gate's own output, nineteen
    # lines above it in the same prompt, named `test_oversize_surcharge_still_applies_to_free_
    # shipping`. Derive the signal from the authoritative event, never a re-render of it (#12).
    # ADDITIVE (#2): it only ever tells the author MORE, and stays silent when the flag is already
    # represented or empty (#3).
    flag = (getattr(gs, "last_gate_flag", "") or "").strip()
    if flag and flag not in truth:
        truth = "\n\n".join(t for t in (truth, flag) if t)
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
    # ONE copy of the ledger in the author's prompt too: the serialized session often still holds
    # the original fetched-page result (and the compaction appendix) with the SAME field lines the
    # labeled fetch-record block above re-states. The labeled block is the authority the template
    # names ("trust these over any note"); byte-identical copies in the session collapse to a
    # pointer (measured on the maple walk: every steer/judge prompt carried the ~2.4KB block 2×+).
    session, _n_deduped = dedup.elide_text(session, dedup.ledger_units(fetch_truth),
                                           prompts.load("ledger_dedup_note"))
    trigger = _STEER_TRIGGER[condition](gs, step_text)
    # THE AGE OF THE FINDINGS, in the author's own evidence block. cria already computes exactly
    # this for the CODER-facing repeat prompt ("they last ran X, and <file> has been written since")
    # and left the author reading the same cached block as the present tense under the word GROUND
    # TRUTH. qwen35/go 0034: "The repo checks confirm: `sum.Add` is being called with 2 arguments
    # but expects 1", while the file quoted in the same prompt reads sum.Add(price.Mul(quantity))
    # and the coder's build one call later said "Build succeeded".
    written = _writes_since_last_gate(body.get("messages", []))
    user = prompts.render("steer_diagnose_user", trigger=trigger, session=session,
                          disk=(disk or "(no files touched yet)"),
                          truth=(truth or "(no check results for this steer)"),
                          checks_age=(prompts.fill(prompts.load_map("steer_checks_age")["written"],
                                                   files=", ".join(written[:6])) if written else ""))
    coder_tools = _coder_tools_summary(body.get("tools"))
    # The one-shot reasoner the dictated-code check uses. Toolless and phase-tagged so it is
    # visible in the captures as its own call, never mistaken for the authoring pass.
    def _steer_ask(system: str, _user: str) -> str:
        return summarize(reasoner_chat, reasoner_role, system, _ASK_USER_TURN, rlog, phase="steer-code",
                         temperature=0.0) or ""
    # Same shape for the answer-vs-thinking recovery below, under its own phase tag.
    def _recover_ask(system: str) -> str:
        return summarize(reasoner_chat, reasoner_role, system, _ASK_USER_TURN, rlog,
                         phase="steer-recover") or ""
    if workspace_root and os.path.isdir(workspace_root):
        # The author INSPECTS like the critic (operator redesign, 07-30): the disk section above
        # lists names/sizes only, and the author holds the same read-only tools the judges hold —
        # it reads the real bytes it wants to cite instead of having every touched file inlined
        # (the 210K-prompt incident). The inspection transcript joins the grounding evidence so a
        # URL the author legitimately READ from a file is not dropped as invented.
        tooled_user = prompts.render("reasoner_coder_tools", tools=coder_tools) + "\n\n" + user
        transcript: list = []
        comp = _judge_completion(reasoner_chat, reasoner_role, prompts.load("steer_diagnose"),
                                 tooled_user, rlog, phase="reasoner",
                                 workspace_root=workspace_root, transcript=transcript,
                                 answer_now=verifytools.ANSWER_NOW_STEER)
        # A CUT REPLY IS NOT A DIRECTIVE. Its toolless sibling `summarize()` has checked this since
        # the truncation guard landed, and `live_execution_marker` says it outright — "a cut intent is
        # not an intent". This branch never got it. Walked on
        # ada-handles_fabliq_codex_pon_1785721353 call 0139: the author returned finish_reason=length
        # with 8,192 tokens of the coder's own pytest failures repeated ~9x, and cria delivered 27,000
        # characters of that to the coder, in cria's voice, under a prompt asking for "a SHORT
        # directive (under 120 words)". The real directive was sitting in the discarded
        # reasoning_content.
        if massage.is_truncated(comp):
            rlog.emit("loop.steer_truncated", level="warn", phase="reasoner")
            return None
        text = _completion_text(comp)
        if reasoner_role is not None:
            text = reasoner_role.clean_content(text)
        text = strip_think(text or "").strip()
        # A RUMINATING REPLY IS NOT A DIRECTIVE either. The rumination guard is wired to the
        # streaming coder path alone; these calls are non-streamed, so a reply that looped to a
        # clean stop passed every guard. Walked on ada-handles_maple-preview_codex_poff_1785956867
        # call 0055: one first-person paragraph repeated ~45x (finish=stop), delivered verbatim as
        # a ~10KB ⟦ctx:steer⟧. Same pure detector as the stream watcher; dropped like a cut reply.
        if _ruminating_reply(text):
            rlog.emit("loop.steer_degenerate", level="warn", phase="reasoner", chars=len(text))
            return None
        evidence = user + "\n\n" + "\n".join(
            str(m.get("content") or "") for m in transcript if m.get("role") == "tool")
        directive = _steer_or_none(text) or _steer_from_reasoning(comp, text, _recover_ask, rlog)
        return _grounded_steer_or_none(directive, evidence, rlog, ask=_steer_ask,
                                       sess=gs, messages=body.get("messages", []),
                                       workspace_root=workspace_root)
    # BOTH PATHS, not just the tooled one: `capture` hands back the raw completions so the toolless
    # branch can read the same discarded thinking. capture[0] is the reasoning-ON pass — summarize's
    # retry runs with reasoning forced OFF and has none to read.
    passes: list = []
    text = (summarize(reasoner_chat, reasoner_role, prompts.load("steer_diagnose"), user, rlog,
                      phase="reasoner", coder_tools=coder_tools, capture=passes) or "").strip()
    if _ruminating_reply(text):   # same guard as the tooled branch — see loop.steer_degenerate above
        rlog.emit("loop.steer_degenerate", level="warn", phase="reasoner", chars=len(text))
        return None
    directive = _steer_or_none(text)
    if directive is None and passes:
        directive = _steer_from_reasoning(passes[0], text, _recover_ask, rlog)
    return _grounded_steer_or_none(directive, user, rlog, ask=_steer_ask,
                                   sess=gs, messages=body.get("messages", []),
                                   workspace_root=workspace_root)


def _ruminating_reply(text: str) -> bool:
    """True when a steer reply's tail is a periodic repetition of one block — the author looping,
    not directing. Pure delegation to the stream watcher's detector (rumination.degenerate_tail):
    short replies can never fire (the window is 2KB and a directive is asked for at <120 words),
    and long-but-varied replies have no short period."""
    from . import rumination
    return rumination.degenerate_tail(text or "")


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
    # A reply that IS one bare JSON object is a role-collapse artifact — the author answering in a
    # judge's verdict schema (measured live: the tool-looped author returned {"done": true,
    # "reason": "complete implementation..."}, which the cleaning below would inject verbatim as a
    # steer). A directive is prose; a lone JSON object is not a directive → safe null.
    fenced = re.sub(r"^```[a-z]*\s*|\s*```$", "", body.strip())
    if fenced.startswith("{") and fenced.endswith("}"):
        try:
            if isinstance(json.loads(fenced), dict):
                return None
        except ValueError:
            pass
    # A REPLY THAT ENDS INSIDE AN UNTERMINATED JSON OBJECT was a structured emission that stopped
    # mid-object, not a directive. Walked on maple-preview 1786218955 call 0065 (finish_reason
    # `stop`, not a length cut): the author wrote a first-person verdict essay — "Looking at this
    # situation, I need to decide if the coder is stuck or making progress… I'll give the imperative
    # directive to fix these concrete issues." — then opened `{ "Fix the ada_handle_resolver.py
    # code: …` and never closed it. cria shipped all of it as `⟦ctx:steer⟧ [REDIRECT]`. Inside the
    # fragment sat the false claim that ended the run ("a list with 2 items is returned instead of
    # 1"); the coder had just reasoned its way to the real bug, deferred to cria, and wrote nothing
    # more before the wall.
    #
    # KEYED ON WHAT FOLLOWS THE BRACE, NOT THE BRACE. A bare unbalanced-`{` test refuses real directives —
    # measured: "You are missing a closing brace. Add { after the if on line 12" and "Replace the
    # literal {handle in the URL" both died. `{` is ordinary code in every brace language and an
    # ordinary placeholder in a URL template, so a rule that reads it as JSON is a Python-corpus
    # artifact that would misfire the moment the task is Go or Java. What is NOT ordinary prose is
    # an unclosed `{` whose very next token is a quoted string — `{ "Fix the …`. Prose after a brace
    # does not open with a quote; a serialized object does. Over the 99 distinct steers cria has
    # delivered across 18 captured sessions this refuses exactly one — call 0065.
    #
    # Refusing the WHOLE reply, not salvaging the prose: the prose is the deliberation the author was
    # told not to emit, and the instruction is inside the fragment. Half a broken emission is not a
    # directive; the caller falls back to its grounded canned text.
    if body.count("{") > body.count("}") and body.rsplit("{", 1)[1].lstrip()[:1] == '"':
        return None
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
    # `NOT_STUCK` is a SENTINEL — the underscore is part of the token. `on[_ ]track` may keep the space
    # form because "on track" is only ever the verdict; "not stuck" is ordinary English a directive says
    # about the coder, and excising it INVERTS the sentence. Measured on
    # ada-handles_mellum2_codex_poff_1785693138 call 0138: the reasoner wrote "You are making genuine
    # progress ... This is not stuck." and the coder was handed "... This is ." as its rescue; the same
    # regex turns "You are not stuck on the import, you are stuck on the missing live test" into "You are
    # on the import, ..." — cria asserting the opposite of what the reasoner ruled.
    # A SENTINEL AT THE END IS A DECISION, NOT A HEDGE. The hedge this function exists for puts the
    # sentinel FIRST — Fabliq's "ON_TRACK. You keep re-fetching; write it now." — and the directive
    # follows it. When the sentinel is LAST, everything before it is the reasoning that produced the
    # decision, and delivering that reasoning ships a verdict as a directive.
    #
    # Walked twice on maple-preview 1786228135. Call 0085 answered, verbatim:
    #     "The coder has already completed the task—files are created, tests pass, and live tests
    #      succeed. No indication of being stuck.\n\nON_TRACK"
    # ON_TRACK means SAY NOTHING. cria stripped it and shipped the sentence before it, so the coder
    # was told it was finished — while cria's own gate said the opposite 23 calls later. Call 0057 is
    # the same shape ("You're making forward progress on all fronts. OUT"), and the reasoner's own
    # thinking there reads "the coder is NOT stuck. I should output ON_TRACK."
    #
    # Position, not phrasing: no word list, and the hedge keeps working. Only a reply whose LAST
    # non-empty line is the bare sentinel is read as a decision.
    _lines = [ln for ln in body.strip().splitlines() if ln.strip()]
    if _lines and re.fullmatch(r"(?i)\W{0,4}(?:on[_ ]track|not_stuck)\W{0,4}", _lines[-1].strip()):
        return None
    _SENTINEL = r"on[_ ]track|not_stuck"
    negated = re.compile(rf"(?i)\b(?:not|never|isn't|aren't)\s+(?:{_SENTINEL})\b")
    kept = [s for s in re.split(r"(?<=[.!?])\s+|\n+", body) if not negated.search(s)]
    directive = re.sub(rf"(?i)\b({_SENTINEL})\b", " ", " ".join(kept))
    directive = re.sub(r"\s+", " ", directive).lstrip(" >-*:.,;").strip()
    # A directive remains once the verdict is stripped → deliver it (Fabliq hedges the verdict + advice);
    # essentially nothing left → a genuine on-track veto, inject nothing. The small floor skips a bare
    # "ok"/"yes" residue without discarding a real short steer.
    return directive if len(directive) >= 8 else None


# ---- THE ANSWER SAYS ON_TRACK; THE THINKING SAYS STUCK ------------------------------------------
#
# `_steer_or_none` above handles every shape the AUTHOR'S ANSWER can take — the hedge, the negation,
# the bare token. It cannot help when the answer is a bare `ON_TRACK` and the reasoning that produced
# it says the opposite, because by then the reasoning is already on the floor. Verbatim from the
# fabliq walk (ada-handles_fabliq_codex_pon_1785721353), call 0213:
#
#   "I believe the coder is stuck and needs help from the user. The appropriate response would be to
#    use the directive `ON_TRACK` to indicate that the coder is not making progress and requires
#    assistance."
#
# Emitted content: `ON_TRACK` — the token that asserts the coder needs NO help. Same run, call 0255,
# whose thinking ends with a finished directive — "Thus we will output: Stop re-running web_fetch and
# instead modify handle_resolver.py line 46 to raise ConnectionError…" — and whose content was again
# the one word. cria read content only, took the veto, sent nothing, and the loop ran 12 more calls.
# Ten calls in that one run.
#
# WHY A QUESTION AND NOT A PATTERN (principle 9's corollary). The trigger below fires on 243 of the
# 1,852 declined steer-author replies that have any thinking at all, across 78 sessions. Ten were read
# in full, and it splits about evenly: five are the real defect (0033 emitted "" with a complete
# diagnosis behind it; 1288's thinking ends "edit test_resolve_handle.py, line 93, change that
# assertion to expect 'resolved_addresses.ada is missing'" and it answered ON_TRACK), and five are a
# reasoner ARGUING the question and landing correctly on-track ("This is genuinely making progress …
# So ON_TRACK is appropriate"). Both halves contain the same words. No window over the sentence
# separates them, and pulling "the directive" out of a rambling trace is a judgment on top of that.
# So the pattern only decides whether ONE focused question is worth a call, and the question decides.
#
# ONE DIRECTION ONLY, structurally. This runs only where `_steer_or_none` already returned None — no
# steer exists at that point, so the recovery can only ever turn SILENCE into a steer. It cannot
# suppress a directive, cannot veto a rescue, and touches no completion verdict. And whatever it
# recovers goes through `_grounded_steer_or_none` like any other authored steer: roleplay markers,
# ungrounded URLs, dictated code, a service the ledger shows answering, a false line citation. The
# outer caps are untouched too — the same-checks
# suppression all gate before author_steer ever calls the model.
#
# A TRIGGER, deliberately over-firing — the same contract as _BLAME_WORDS and _CODE_SHAPED.
_STEER_REASONING_STUCK = re.compile(
    r"(?i)\b(?:(?:is|are|it'?s|coder is) stuck|stuck in a loop|"
    r"not making progress|no forward progress|isn'?t making progress|needs? help|"
    r"needs? assistance|requires? assistance|write (?:a|the) directive|"
    r"should not (?:output|say|emit|use)|must not (?:output|say|emit)|"
    r"not ON_TRACK|instead of ON_TRACK|looping|we must write|need to give a directive)\b")

# How much of the author's thinking the recovery question carries.
# The recovery question carries the author's thinking WHOLE. It used to carry the last 4,000
# characters, on the reasoning that a conclusion is what a model writes LAST — which is cria judging
# relevance on the model's behalf, and #5 leaves no room for it. The reader here IS a model: it does
# its own selecting, and the context floor fits the call.


def _steer_from_reasoning(comp: dict, answer: str, ask, rlog) -> str | None:
    """The directive an ON_TRACK answer discarded, or None — see the long note above for the evidence.

    ``ask(system) -> str`` is the caller's one-shot toolless reasoner. No reasoner, no thinking beyond
    the answer itself, a cut reply, or a trigger that does not fire → None, so the common path costs
    nothing. The recovered reply is read by `_steer_or_none` like any other, which is why the hedge
    and negation handling is not duplicated here."""
    if ask is None or massage.is_truncated(comp):
        return None      # a cut reply is not a directive, and a cut trace is not a conclusion
    # …AND A STREAM CRIA ITSELF KILLED IS NOT AN ANSWER. When a guard aborts a reply mid-stream there
    # is no verdict to have been contradicted: cria stopped the model before it could give one. This
    # ran anyway, and then cria narrated the corpse as a decision.
    #
    # Measured, nemotron-elastic/ruby 0048. cria's prompt to the recovery reasoner: "You were just
    # asked whether a small coding model was stuck, and you answered with the single word ON_TRACK."
    # The reply it refers to ended "reasoning stream ABORTED HERE by the rumination guard", with no
    # content at all. The model never said ON_TRACK; cria did, on its behalf, and then built a steer
    # on the answer it invented (#12 — every sentence cria says about an action comes from the event
    # that produced it, and the abort IS the event here).
    if comp.get(bodykeys.RUMINATION) or (comp.get("choices") or [{}])[0].get("finish_reason") == "rumination":
        rlog.emit("loop.steer_rescue_skipped", level="info", why="stream aborted by a guard")
        return None
    reasoning = _reasoning_of(comp)
    # `_reasoning_of` falls back to `content` for a model with no separate channel (principle 19). If
    # that IS the answer we already read, there is no second signal here and nothing to recover.
    if not reasoning or reasoning.strip() == (answer or "").strip():
        return None
    if not _STEER_REASONING_STUCK.search(reasoning):
        return None
    rlog.emit("loop.steer_answer_contradicted", level="info", answer=_clip(answer, 60))
    recovered = strip_think(ask(prompts.render(
        "steer_reasoning_recover",
        reasoning=reasoning)) or "").strip()
    directive = _steer_or_none(recovered)
    if directive:
        rlog.emit("loop.steer_from_reasoning", level="info", head=_clip(directive, 140))
    return directive


# A steer that CONTAINS a transcript is not a directive — it is the reasoner role-playing the
# session: fake tool calls with invented file content, fake "tool: Wrote …" results, fake command
# output. Injected as ⟦ctx:steer⟧ it reads as fact (observed: the coder copied a steer's INVENTED
# mock addresses verbatim into the shipped file, run 0729-mellum2 call 0157). Deterministic
# markers of transcript syntax — never a judgment call:
# The tool-call TAG dialects come from massage._LEAK_DEBRIS — the one catalog of transcript
# syntax (walked on maple 1785956867 call 0083: a `<tool_call> {"name": …}` steer DELIVERED
# because this arm knew only the `name({` shape; the tag family lived one module away).
_ROLEPLAY_STEER = re.compile(
    r"(?m)(?:\b(?:write_file|edit_file|exec_command|read_file|web_fetch|apply_patch)\s*\(\s*\{"   # tool-call syntax
    r"|^\s*(?:assistant|tool|user)\s*:\s"      # transcript role labels
    r"|⟦ctx:"                                   # a steer must not nest cria's own markers
    r"|" + "|".join(re.escape(mk) for mk in massage._LEAK_DEBRIS) + r")"
)
# The author announcing ITS OWN plans ("I will write resolve.py") — the steer contract is second
# person. SPLIT from the hard-drop arms above (provenance audit 2026-08-04): its evidence is two
# blind-author-era MoE incidents (run 0729-mellum2 call 0059), and as a drop it killed whole steers
# for a pronoun. Now observe-only at the call site, pending a truth sample of its fires.
_ROLEPLAY_FIRSTPERSON = re.compile(r"\b[Ii] will (?:write|create|implement|add|run|fix|build)\b")


def _is_argument_blob(directive: str) -> bool:
    """True when a 'directive' is really a tool call's ARGUMENTS — a bare JSON object or array.

    Walked on ada-handles_nemotron-elastic_codex_pon_1785360304 call 0030, and again in the sibling
    run at 0044. The steer author tried to CALL read_file; its reply content was the argument object,
    and cria injected it verbatim:
        ⟦ctx:steer⟧ { "path": "/tmp/…/ada_handles_resolver.py", "start_line": 1, "end_line": 1 }
    and, at 0030, ~4,000 characters of fabricated grep output carrying an invented schema
    ("holder": an object with an `address`) that the coder then believed and chased for two calls.
    `holder` is a plain string.

    _ROLEPLAY_STEER already hard-drops transcript syntax and `name({` tool-call syntax; a bare
    argument object matches neither — it has no tool name in front of it. The test is EXACT (does the
    whole directive parse as a JSON object/array?), not a judgment, and it is the same direction as
    the guards beside it: a steer that is not a directive is withheld, and the caller falls back to
    the grounded canned redirect or to silence."""
    t = (directive or "").strip()
    if not (t.startswith("{") or t.startswith("[")):
        return False
    return extract_json_object(t) is not None or t.endswith(("}", "]"))


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


# A steer that DICTATES CODE is the highest-damage class measured across the gemma runs: the author
# is the same weak model, its code is usually broken (unbalanced parens, a phantom `Httx`, a `2>&3`
# redirect, `sed -i` the system prompt forbids, an import that cannot resolve), cria's own relay
# flattens the newlines out of it, and the coder transcribes the wreckage verbatim ("The user is
# right" opened 14 of one run's post-steer reasonings). The steer contract is already "name the
# file:line and describe the change in words" — this enforces it: a directive carrying a multi-line
# code block, or a shell command line, is dropped. Prose that merely NAMES an identifier is fine.
# A TRIGGER, not a verdict. It is deliberately allowed to over-fire: its whole job is to decide
# whether the focused question below is worth one call. Telling a QUOTE from a DICTATION is judgment
# — the author's own prompt permits "quoting the real error text or an existing line you have read"
# and forbids "inventing the replacement", and no pattern can separate those. Measured over 1,692
# distinct steers actually delivered to a coder, 264 (16%) are code-shaped, and reading them shows
# most are legitimate quotes of the coder's own failing line.
#
# The old regex WAS the verdict, and it was wrong in both directions. It dropped whole steers on a
# leading `import ` (a quote of the file being discussed), and it fired only twice in the entire
# capture history — while the directive that told the coder to call `pytest.register_pytest_mark("live")`
# (not a real function) sailed through, because that code was inline in prose with no fence and no
# line-leading keyword. Chasing inline code with more pattern is the deterministic-code-doing-a-
# judgment's-job that principle 9's corollary forbids.
# WHETHER A DIRECTIVE CONTAINS CODE, BY SHAPE. This is a TRIGGER — its only job is to decide
# whether one focused reasoner call is worth making, and the reasoner still rules quote-versus-
# dictation — so over-firing is cheap and a miss is not.
#
# It used to be spelled in Python and POSIX: `def `, `import `, `pip install`, `pytest`, `sudo`,
# `sed -i`, `cat `. Java, Rust, Go and Node are half the battery and none of them match any of that,
# so the guard simply never ran on them. Measured, ternary-bonsai/java 0040 — steer: "drop the
# dependency entirely and handle CSV parsing inline in Importer.java"; the task: "Use a third-party
# Java CSV library ... do not write a CSV parser." The steer shipped unchecked and the coder built
# exactly what it said.
#
# The shapes below are language-neutral: a statement terminator or a brace at end of line covers
# C-family and Rust; a call at the start of a line covers everything; a bare word followed by a
# flag-shaped argument covers any shell command in any ecosystem. The Python keywords are kept
# because they cost nothing and still fire first on Python.
_CODE_SHAPED = re.compile(
    r"```"                                              # a fenced block of any kind
    r"|^[ \t]*(?:def |class |import |from [.\w]+ import |return |with |@patch|assert )"   # python
    r"|^[ \t]*\S.*[;{}]\s*$"                            # a statement or brace line: java/rust/go/c/js
    r"|^[ \t]*\w+(?:[.:]{1,2}\w+)*\s*\([^)\n]*\)"       # a call at the head of a line
    r"|^[ \t]*\$?\s*[\w./-]+(?:\s+[\w./=-]+)*\s+--?[\w-]+"  # a command with a flag: `mvn -q test`
    r"|\b\w+(?:\.\w+)+\([^)\n]*\)",                    # an inline dotted CALL: `pkg.fn(arg)`
    re.M)

_DICTATES = "DICTATES"

# A line worth checking for provenance: a code line or a command line. Short fragments and ordinary
# prose are left alone — the question is only ever about a line the coder could paste.
_QUOTABLE_MIN = 12
_INVENTED_MARK = ("[code removed — written by this supervisor, not read from your files or your "
                  "checker output; make the change in your own code]")
# The two shapes, checked differently: a line that IS code, and a call embedded in prose.
_CODE_LINE = re.compile(
    r"^[ \t]*(?:def |class |import |from [.\w]+ import |return |with |@patch|assert )"
    r"|^[ \t]*(?:\$ |sudo |pip install|sed -i|cat |grep -n|python3? -m |pytest )", re.M)
_INLINE_CALL = re.compile(r"\b\w+(?:\.\w+)+\([^)\n]*\)")


def _observed_code(messages: list[dict] | None) -> str:
    """Everything cria has actually SEEN happen — what tools returned and what the coder WROTE.

    THE HAYSTACK WAS THE BUG. This check asks "did the author read this line, or invent it?", and it
    was asked against the whole composed prompt — which carries the defanged transcript, which
    carries `the coder said: …`. So a line the coder merely BELIEVED counted as something cria had
    seen, and the invention shipped with cria's authority behind it.

    Measured, nemotron-elastic/python 0197. The coder's private thinking: "return self._send(201,
    {"error": "internal server error"})? ... That seems odd." cria's steer: "replace the line that
    returns 500 on exception with 201." The coder complied against its own judgement. That line is
    still wrong on disk at orders/app.py:54.

    PROVENANCE, NOT SYNTAX. cria trusts what was RETURNED and what was WRITTEN, never what was SAID:

      * tool results — a compiler error, a test failure, a `read_file` body. This is where the
        coder's own failing line lives, so the case the 2026-08-04 ruling protects (a steer quoting
        the line that is actually failing) still passes.
      * tool-call arguments — the bytes the coder actually put on disk with `write_file`/`edit_file`.
        Code the coder really wrote is real code, whatever it believes about it.

    Excluded is exactly one thing: assistant prose and reasoning. A belief is not an observation."""
    out: list[str] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role in ("tool", "function_call_output") or m.get("type") == "function_call_output":
            c = m.get("content") if m.get("content") is not None else m.get("output")
            if isinstance(c, str):
                out.append(c)
        for tc in m.get("tool_calls") or []:
            args = (tc.get("function") or {}).get("arguments")
            if isinstance(args, str):
                out.append(args)
    return "\n".join(out)


def _strip_invented_code(directive: str, evidence: str) -> tuple[str, int]:
    """The directive with code the author did NOT read replaced by a marker.

    Code survives when it appears in what cria OBSERVED — see :func:`_observed_code` for why that is
    tool results and written bytes, and never the coder's own prose. That is the whole distinction
    the 2026-08-04 ruling rests on: a steer quoting the coder's own failing line is grounded and
    carried the ladder passes; a steer inventing a replacement is the author, and the author is the
    same weak model with no compiler.

    SPANS, not lines. An invented call usually sits inside a sentence that is otherwise a correct
    diagnosis, and deleting the sentence throws away the half worth keeping — so a code-shaped LINE
    is replaced whole, while an inline call embedded in prose loses only the call. Whitespace-
    insensitive, because cria's own relay reflows the directive before the coder sees it.

    Returns (directive, spans_stripped)."""
    if not evidence:
        return directive, 0                       # nothing to check against → change nothing
    haystack = " ".join(evidence.split())
    seen = lambda s: " ".join(s.split()) in haystack        # noqa: E731 — one predicate, used twice
    stripped = 0
    out = []
    for line in directive.splitlines():
        body = line.strip().strip("`")
        if len(body) >= _QUOTABLE_MIN and _CODE_LINE.search(line) and not seen(body):
            stripped += 1
            out.append("    " + _INVENTED_MARK)
            continue
        def _sub(m):
            nonlocal stripped
            if seen(m.group(0)):
                return m.group(0)
            stripped += 1
            return _INVENTED_MARK
        out.append(_INLINE_CALL.sub(_sub, line))
    return "\n".join(out), stripped


def _dictates_code(directive: str, ask=None) -> bool:
    """True when the directive hands the coder CODE TO COPY rather than a description of the change.

    Deterministic pre-filter, then ONE focused question — the pattern the operator's policy calls for:
    a single purposeful model call is not extra inference when it stops the coder thrashing against
    unverified code. Code-shaped text is a cheap fact; whether it is a quote or a dictation is not.

    ``ask(system, user) -> str`` is the caller's one-shot reasoner. With no reasoner (or an answer
    that is not one of the two words) the pre-filter's verdict stands — which is exactly today's
    behaviour, so this can only move steers from dropped to delivered, never the other way."""
    if not _CODE_SHAPED.search(directive):
        return False
    if ask is None:
        return True
    ans = strip_think(ask(prompts.render("steer_dictates_code", directive=directive), "") or "").strip()
    head = ans.upper().split()[0].strip(".,:;`*") if ans.split() else ""
    return head != "DESCRIBES"        # DICTATES, or anything unreadable → the pre-filter stands


# A TRIGGER, deliberately over-firing: its only job is to decide whether one focused question is
# worth a call. Whether a directive LEAPS from "this request failed" to "the service does not work"
# is a judgment, and principle 9's corollary forbids a pattern making it.
_BLAME_WORDS = re.compile(
    r"(?i)\b(?:not (?:a )?(?:working|available|live|real)|does ?n[o']?t (?:support|work|exist|serve)|"
    r"is (?:down|offline|broken|unavailable|deprecated)|no longer (?:works|available|supported)|"
    r"rate[- ]limit|requires? (?:an? )?(?:api[- ]?key|auth|credential)|documentation (?:landing )?page|"
    r"returns? 404 for (?:every|all)|consistently returns? 404|impossible given the api)\b")


# Identifier-shaped tokens: dotted or underscored names of 4+ characters. Language-agnostic on
# purpose — it is "the same token appears in both places", not a per-language symbol grammar (#20).
_IDENTLIKE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}[?!]?")


# A NAME, not a word. The shared-token scan fed the prescribes judge any identifier-shaped run of
# four or more letters, which on a failing build means the vocabulary of failure itself: `error`,
# `compile`, `declared`, `failures`, `annotations`, `orders`, `python3`. Asking "is the directive
# PRESCRIBING `declared`?" is not a question with an answer, and a weak judge answering it wrongly
# refuses the steer.
#
# MEASURED over every fire the guard has ever had — 18 of them, in the cycle-4 walk. At most two
# were correct. It killed "Replace `axed` on line 90 with `taxed`" over the shared word `declared`,
# and "correcting the [bin] section in Cargo.toml" — the exact fixes two cells needed and did not
# get. It also killed "replace `from http.client import HTTPServer` with `from http.server import
# HTTPServer`" and "Edit the line `from .db import db` to `import orders.db as db`".
#
# An API symbol is QUALIFIED or COMPOUND in every language cria meets: it carries a dot, a `::`, an
# underscore, or an internal capital. `decimal.Decimal`, `orders.db`, `NewFromFloat64`,
# `setSkipInitialNewline`, `Cargo.toml` all qualify; the words above do not. Shape, not a stoplist
# (#20) — a list of English words to exclude would be a rule needing an exception list, which is the
# tell that it should have been a question.
def _looks_like_a_symbol(tok: str) -> bool:
    return ("." in tok or ":" in tok or "_" in tok
            or bool(re.search(r"[a-z][A-Z]", tok)))


def _shared_symbols(directive: str, findings: str) -> list[str]:
    """Identifier-shaped tokens present in BOTH texts, longest first.

    Dotted and namespaced names are compared whole AND by part, because a compiler names the member
    (`cannot find symbol: getTotalAmount`) while a directive names the call (`cart.getTotalAmount()`)
    — the same symbol, spelled two ways. Longest-first so the reported hit is the specific name
    rather than an incidental filename that happens to appear in both."""
    def toks(t: str) -> set:
        out = set()
        for run in re.findall(r"[A-Za-z_][A-Za-z0-9_.:?!]*", t or ""):
            out.add(run.strip(".:"))
            out.update(p for p in re.split(r"[.:]+", run) if _IDENTLIKE.fullmatch(p))
        return {x for x in out if len(x) > 3 and _looks_like_a_symbol(x)}
    shared = toks(directive) & toks(findings) - _positional_only(findings)
    shared = {t for t in shared if not _NAMES_A_FAILURE.fullmatch(t)}
    return sorted(shared, key=len, reverse=True)


# AN EXCEPTION CLASS IS WHAT A CHECKER REPORTS, NEVER WHAT IT REJECTS. `LoadError`, `AttributeError`,
# `CsvValidationException` — a directive naming one is quoting the failure, which is the case this
# guard exists to distinguish and kept getting backwards. Two of the guard's eighteen historical
# fires are exactly this, and both killed a correct directive.
_NAMES_A_FAILURE = re.compile(r"\w*(?:Error|Exception|Failure|Warning)$")


# WHERE the checker is pointing, as opposed to WHAT it is rejecting.
_POSITIONAL = (
    re.compile(r"^\s*-->\s*(\S+)", re.M),                          # rustc/cargo's span line
    re.compile(r"^\s*([\w./\\-]+\.\w{1,5}):\d+", re.M),            # file:line: prefixes
    re.compile(r"(?i)(?:can'?t find|cannot find|could not find|no such file|not found)"
               r"[^\n]*?[`'\"]?([\w./\\-]+\.\w{1,5})[`'\"]?", re.M),   # the MISSING thing
)


def _positional_only(findings: str) -> set:
    """Tokens the findings only ever name as a LOCATION, or as the thing that is missing.

    `_shared_symbols` exists to catch a directive telling the coder to use a symbol the checks are
    rejecting. A path is the opposite case: when cargo says

        error: can't find bin `dotkey-toml` at path `…/src/main.rs`
         --> …/Cargo.toml

    the correct directive is *"create `src/main.rs`"*, and both `main.rs` and `Cargo.toml` are shared
    tokens — so the guard was handed the one right answer of the run and refused it. Walked on cycle
    4 cell 24 (`rust-toml-cli x nemotron-elastic`): the reasoner produced exactly that directive at
    call 0051, the judge answered PRESCRIBES at 0052, and the coder got a generic redirect instead
    and never created the file.

    A path a checker says is MISSING is a path a directive is right to prescribe. Only tokens whose
    every occurrence is positional are dropped — one appearance in a real rejection keeps it."""
    positional: set = set()
    for pat in _POSITIONAL:
        for m in pat.finditer(findings or ""):
            tok = m.group(1).strip("`'\"")
            positional.add(tok)
            # …AND EVERY FRAGMENT OF IT. `_shared_symbols` tokenizes on `[A-Za-z_][\w.:?!]*`, which
            # breaks a temp-directory name at its hyphens — so the reported "symbol" from
            # `--> /tmp/suite-orders-api-py_nemotron-elastic_codex_poff_1786953798-qw6tyybl/…` was
            # `elastic_codex_poff_1786953798`, a slice of the workspace path cria itself chose. One
            # of the guard's eighteen historical fires is that token.
            positional.update(p for p in re.split(r"[/\\.\-]", tok) if p)
    out = set()
    for tok in positional:
        elsewhere = [ln for ln in (findings or "").splitlines()
                     if tok in ln and not any(pat.search(ln) for pat in _POSITIONAL)]
        if not elsewhere:
            out.add(tok)
            out.update(p for p in re.split(r"[.:]+", tok) if p)
    return out


def _prescribes_what_the_checks_reject(directive: str, findings: str, rlog, ask) -> str:
    """The symbol a directive tells the coder to USE while the checks name it as the problem — else "".

    THE STRIP CANNOT CATCH THIS, and its own contract is why. `_strip_invented_code` asks "did the
    author READ this or invent it?", and answers from what cria observed — which includes tool
    results. A compiler error is a tool result. So on any "replace X with Y" steer the BROKEN symbol
    X is the best-attested string in the prompt and survives, while the correct replacement Y was
    never observed and is stripped. The strip inverts the fix.

    Delivered to a coder on 2026-08-16: "replace `decimal.NewFromInt64` with [code removed]`)`" —
    that symbol appears 7 times in the same prompt, all of them inside `undefined: …` errors. Two
    more steers the same run said to USE `decimal.NewFromFloat64` while the same prompt carried
    `undefined: decimal.NewFromFloat64` twenty-three times.

    DETERMINISTIC GATHER, REASONED JUDGMENT (#8). Code finds the concrete discrepancy — a token
    present in BOTH the red finding-set and the directive — and one focused question decides whether
    the directive is PRESCRIBING it or merely quoting the failure. Without a reasoner, or on an
    unreadable answer, the directive stands: this may only move steers from delivered to refused
    when a model says so, never on a pattern alone.

    Returns the symbol, or "". The caller refuses the steer outright (#3's safe null) rather than
    rewording it — cria has no better directive to offer, and a wrong one costs more than silence."""
    if not directive or not findings or ask is None:
        return ""
    shared = _shared_symbols(directive, findings)
    if not shared:
        return ""
    ans = strip_think(ask(prompts.render("steer_prescribes_broken", directive=directive,
                                         findings=findings, symbols=", ".join(shared[:8]))) or "").strip()
    head = ans.upper().split()[0].strip(".,:;`*\"'") if ans.split() else ""
    if head != "PRESCRIBES":
        return ""
    hit = next((t for t in shared if t in ans), shared[0])   # longest-first from _shared_symbols
    rlog.emit("loop.steer_prescribes_broken", level="warn", symbol=hit, head=_clip(directive, 120))
    return hit


def _blames_a_service_that_answered(directive: str, sess, messages: list, rlog, ask) -> bool:
    """True when the directive concludes the SERVICE is broken while cria's own ledger holds a 2xx
    for that host.

    The steer author's system prompt already forbids this, in these words: "NEVER attribute the
    failure to an outside cause — authentication, rate limits, permissions, a broken service — that
    the working access disproves; a false cause becomes the coder's belief and every later step
    builds on it." That is a request, not an enforcement, and this is what it costs when a small
    reasoner breaks it.

    Walked on ada-handles_mellum2_codex_poff_1785714194 call 0026, cria's own voice, delivered
    verbatim to the coder at 0027:

        "The Ada Handles API does not support /holders/{address} returning per-holder total_handles —
         it consistently returns 404 ... which is impossible given the API. Fix: handle the 404 and
         return 0 for total_handles. In test_resolve_handle.py, relax the total_handles assertion to
         allow 0."

    Run during the walk: that endpoint returns 200 with total_handles: 15 for the STAKE address the
    code already held. The coder read the steer as the user speaking, wrote the band-aid, rewrote its
    own assertion to expect 0, and the run shipped green over a broken deliverable. The same false
    claim ended two earlier runs on this task.

    Silent when cria has NO successful fetch: then it cannot disprove anything, and abstaining is the
    only honest answer (same contract as :func:`known_routes`). Silent with no reasoner."""
    if not directive or ask is None:
        return False
    if not _BLAME_WORDS.search(directive):
        return False
    ledger = _fetch_ground_truth(messages, sess, header="PAGES ALREADY FETCHED")
    if not ledger.strip() or not _fetch_succeeded_anywhere(sess, messages):
        return False          # nothing answered → cria holds no disproof → not its call to make
    ans = strip_think(ask(prompts.render("steer_blames_the_service",
                                         ledger=ledger, directive=directive)) or "").strip()
    head = ans.upper().split()[0].strip(".,:;`*") if ans.split() else ""
    if head == "BLAMES":
        rlog.emit("loop.steer_blames_service", level="warn", head=_clip(directive, 140))
        return True
    return False


def _fetch_succeeded_anywhere(sess, messages: list) -> bool:
    """Did ANY fetch this session come back 2xx? The disproof this check stands on."""
    merged = _merge_fetches(_extract_fetches(messages), (getattr(sess, "fetched_pages", None) or {}))
    return any(_fetch_succeeded(_fetch_facts(e)[0]) for e in merged.values())


# Absolute paths under SYSTEM roots — the shapes a steer can only be inventing when nothing at that
# path exists. /tmp is deliberately absent (workspaces and spill files legitimately live there), and
# a workspace-internal path is a legitimate create-target, so neither is ever checked by this.
_ABS_SYSTEM_PATH = re.compile(r"(?<![\w./-])(/(?:home|root|usr|etc|opt|srv|var)/[\w./-]{3,})")


def _phantom_system_path(directive: str, workspace_root: str | None) -> str:
    """An absolute system-root path the directive names that does NOT exist — else "".

    Walked 2026-08-04, run ada-handles_gemma4_codex_poff_1785860144 call 0023: a steer told the
    coder "The real OpenAPI spec at /home/user1/.cache/api.handle.me/openapi.json contains…" — a
    path that has never existed on this box — and the coder spent its next turn trying to read it.
    The URL-grounding check is URL-scoped and the citation check is file:line-scoped, so a bare
    fabricated filesystem path passed both. This is the same enforcement family, same shape:
    cria holds the disk, so existence is a fact, not a judgment. A path inside the workspace is
    never checked (it may be a create-target); a SYSTEM path that exists is fine to mention."""
    for m in _ABS_SYSTEM_PATH.finditer(directive or ""):
        path = m.group(1).rstrip(".,;:'\"")
        if workspace_root and path.startswith(str(workspace_root).rstrip("/") + "/"):
            continue
        try:
            if not os.path.exists(path):
                return path
        except OSError:
            continue
    return ""


def _grounded_steer_or_none(directive: str | None, evidence: str, rlog, ask=None,
                            sess=None, messages: list | None = None,
                            workspace_root: str | None = None) -> str | None:
    """The authored steer, or None when it names a URL the evidence cannot support.

    The steer author's own system prompt already says "NEVER invent a file path, directory, command,
    value, or error that does not appear above" — but a prompt is a request, not an enforcement, and a
    small reasoner breaks it. This is the enforcement, and it is deterministic: cria composed the
    evidence, so it can check the claim against it exactly rather than judging it.

    The whole steer is withheld, not just the bad URL: a directive built AROUND an invented route
    ("fetch the response from <invented>, parse the JSON …") is wrong as a whole, and excising the URL
    would leave cria authoring a mutilated instruction — repairing a guess with another guess. The
    callers that need a signal already have a grounded one to fall back to (the canned redirect, the
    raw check truth); a caller with none falls back to silence, which is the correct assist."""
    if not directive:
        return None
    directive = _dedupe_doubled(directive)
    if _ROLEPLAY_STEER.search(directive):
        rlog.emit("loop.steer_roleplay_dropped", level="warn", head=_clip(directive, 120))
        return None
    if _is_argument_blob(directive):
        rlog.emit("loop.steer_argument_blob", level="warn", head=_clip(directive, 120))
        return None
    if _ROLEPLAY_FIRSTPERSON.search(directive):
        # OBSERVE-ONLY (provenance audit, 2026-08-04): the first-person arm's evidence is two
        # blind-author-era MoE incidents, and it killed whole steers for a pronoun (40 unexamined
        # drops on one model in one day). The transcript-syntax arms above remain hard drops —
        # those are self-evidently fiction. This arm logs and delivers, pending the truth sample.
        rlog.emit("loop.steer_roleplay_firstperson", level="info", delivered=True,
                  head=_clip(directive, 120))
    bad = urlgrounding.ungrounded_urls(directive, evidence)
    if bad:
        rlog.emit("loop.steer_ungrounded", level="warn", urls=",".join(bad))
        return None
    phantom = _phantom_system_path(directive, workspace_root)
    if phantom:
        rlog.emit("loop.steer_phantom_path", level="warn", path=phantom, head=_clip(directive, 120))
        return None
    # A FALSE FACT ABOUT A SOURCE CRIA HAS READ. Same enforcement class as the phantom path and the
    # false line citation above: cria stated the shape, so the check is exact, and a steer that
    # contradicts it is refused rather than reworded. This is what separates the maple steer that
    # wrote the shipped bug from the gemma4 steers that carried a 4/4 — both dictate code; only one
    # names a field the ledger denies.
    denied_field = _field_the_ledger_denies(
        directive, _merge_fetches(_extract_fetches(messages or []),
                                  (getattr(sess, "fetched_pages", None) or {})))
    if denied_field:
        rlog.emit("loop.steer_phantom_field", level="warn", field=denied_field,
                  head=_clip(directive, 120))
        return None
    if _dictates_code(directive, ask):
        # OBSERVE-ONLY on the DROP (operator ruling, 2026-08-04) — and the ruling's own reasoning is
        # what this now enforces. The drop's harm evidence came from a BLIND author (empty truth
        # slot, 6/6 runs of invented code); blindness was fixed the same day, and the 08-01 ladder
        # passes were carried by ~15 SIGHTED dictated steers per run. The distinction the ruling
        # turned on is therefore not "does it contain code" but "did the author READ this code or
        # invent it" — and that is checkable, because cria holds the evidence the author was shown.
        #
        # The cross-cohort re-measure the ruling asked for is in: across the six-language battery,
        # dictated implementations destroyed a working state 10 times. nemotron rust 0053 dictated a
        # whole lib.rs whose body returns `current` from an Option fn and puts `return None` after
        # `exit(1)`; 0038's judge "Proposed fix" re-injected a live E0593 and wrote Python
        # triple-quoted strings into Rust. Neither line existed anywhere cria had read.
        #
        # So: quotes survive, inventions are stripped, and the prose ships either way. This is not
        # the blunt drop the ruling rejected — a steer quoting the coder's own failing line is
        # untouched, which is exactly the case the ladder passes were built on.
        # …AGAINST WHAT CRIA OBSERVED, not against the prompt. The prompt carries the coder's own
        # prose, which made a line the coder only believed count as one cria had seen.
        kept, stripped = _strip_invented_code(directive, _observed_code(messages))
        rlog.emit("loop.steer_dictated_code", level="info", delivered=True,
                  stripped=stripped, head=_clip(directive, 120))
        directive = kept
    if sess is not None and _blames_a_service_that_answered(
            directive, sess, messages or [], rlog, (lambda sysm: ask(sysm, "")) if ask else None):
        return None
    if sess is not None and _prescribes_what_the_checks_reject(
            directive, (getattr(sess, "last_gate_flag", "") or "").strip(), rlog,
            (lambda sysm: ask(sysm, "")) if ask else None):
        return None      # the checks say this symbol is the problem — silence beats endorsing it
    ghost = _symbol_not_in_the_file(directive, workspace_root)
    if ghost:
        # cria READ the file; the steer names something that is not in it. Refused, not reworded —
        # the same rule as the phantom path above, one claim class over.
        rlog.emit("loop.steer_phantom_symbol", level="warn", symbol=ghost,
                  head=_clip(directive, 120))
        return None
    made_up = _invented_version(directive, evidence)
    if made_up:
        # The author cannot know a version it was not told; the one it invents is pasted into a
        # manifest and poisons every build after it. See _invented_version for the run this cost.
        rlog.emit("loop.steer_invented_version", level="warn", version=made_up,
                  head=_clip(directive, 120))
        return None
    cite = _false_line_citation(directive, evidence)
    if cite:
        # Same enforcement, next claim class: the author cited a LINE past the file's real length —
        # its own disk list said "68 lines" and the steer said "lines 108-112" (run g1 0034; run g1
        # 0127's misread rode a citation too). cria stated the line count, so the check is exact.
        rlog.emit("loop.steer_false_citation", level="warn", cite=cite)
        return None
    if _steer_auth_refuted(directive, evidence, sess, ask, rlog):
        return None
    return directive


_AUTH_MARKER = re.compile(r"\b40[13]\b|\bunauthori[sz]ed\b|\bforbidden\b", re.I)


def _steer_auth_refuted(directive: str, evidence: str, sess, ask, rlog) -> bool:
    """True when the steer asserts an authentication requirement the session's own record refutes.

    Walked on ada-handles_gemma4_codex_poff_1785866157 steer 0191: "don't add live network calls
    here, they will fail without your API key; keep tests mocked" — for a task that names no key,
    in a session whose every fetch returned HTTP 200 and which had ALREADY resolved handles live
    without a credential. The steer countermanded a deliverable the task itself requires. Same
    guess-shape disease `research._GUESS_SHAPES` refuses in the authored-step channel; here the
    author HAS evidence, so a deterministic drop would misfire on a genuinely authenticated API —
    the F2 pattern applies instead. DETERMINISTIC CODE GATHERS, THE REASONER JUDGES (principle 8):
    the auth shape is only the TRIGGER for spending one call, the network facts are gathered
    exactly (the fetch ledger's statuses, the evidence's own denial markers), and ONE focused
    question rules STANDS or REFUTED. Every failure direction DELIVERS: task mentions auth, no
    reasoner, an unreadable answer — the trigger alone is not proof, and the roleplay retune
    showed what unexamined drops cost. Only a clear REFUTED withholds."""
    if not research.AUTH_SHAPE.search(directive) or ask is None:
        return False
    task = getattr(getattr(sess, "plan", None), "task", "") or ""
    if research.AUTH_SHAPE.search(task):
        return False   # the user's own words raised auth — the claim has a source
    pages = getattr(sess, "fetched_pages", None) or {}
    statuses = {url: str(v[0]) if isinstance(v, (list, tuple)) and v else str(v)
                for url, v in pages.items()}
    facts = [f"- fetched {url}: {st}" for url, st in statuses.items()]
    facts.append("- the task's own text mentions no key, token, or login")
    facts.append("- a 401/403/unauthorized/forbidden DOES appear elsewhere in the session evidence"
                 if _AUTH_MARKER.search(evidence or "")
                 else "- no 401/403/unauthorized/forbidden appears anywhere in the session evidence")
    ans = strip_think(ask(prompts.render("confirm_auth_claim", directive=directive,
                                         facts="\n".join(facts)), "") or "")
    head = ans.upper().split()[0].strip(".,:;`*\"'") if ans.split() else ""
    if head == "REFUTED":
        rlog.emit("loop.steer_auth_refuted", level="warn", head=_clip(directive, 120))
        return True
    return False


# Explicit line citations, still anchored on exact ground truth (the disk list's stated counts):
# `path.py:108`, "lines 108-112 of/in/from path.py", and — walked on
# ada-handles_gemma4_codex_poff_1785866157 (steers 0185/0218/0222) — BARE references ("(line 245)",
# "lines 30 and 98", "lines 9–15, 67–80, AND 95–99") which that run's author used five times past
# the 64-line reality while only the colon form was checked. A bare reference names no file, so it
# is flagged only when it exceeds EVERY stated count — a line number bigger than every file in the
# workspace is false no matter which file it meant. Anything fuzzier would be judgment dressed as
# a rule.
_CITE_COLON = re.compile(r"\b([\w./-]+\.\w{1,4}):(\d{1,5})\b")
_CITE_WORDS = re.compile(r"\blines?\s+(\d{1,5})(?:\s*[-–—]\s*(\d{1,5}))?\s+(?:of|in|from)\s+([\w./-]+\.\w{1,4})\b", re.I)
_CITE_BARE = re.compile(r"\blines?\s+(\d{1,5}(?:\s*[-–—]\s*\d{1,5})?(?:(?:\s*,\s*|\s+and\s+)"
                        r"\d{1,5}(?:\s*[-–—]\s*\d{1,5})?)*)", re.I)
_DISK_LINE = re.compile(r"^FILE\s+(\S+)\s+—\s+[\d,]+\s+bytes,\s+([\d,]+)\s+lines?$", re.M)


# The symbol must be MARKED AS CODE — backticked, or written as a call. "the change in app.py" is
# ordinary prose and must never trip this, because the guard DROPS the steer: a false positive costs
# a legitimate directive, which is the expensive direction.
_SYMBOL_IN_FILE = re.compile(
    r"(?:`([A-Za-z_]\w{2,})`|\b([A-Za-z_]\w{2,})\(\))"
    r"\s+(?:in|from|of|inside)\s+`?([\w./-]+\.\w{1,5})`?")


def _symbol_not_in_the_file(directive: str, workspace_root: str | None) -> str | None:
    """A steer binding an identifier to a named file where that identifier does not appear — or None.

    Same enforcement class as the phantom path and the false line citation beside it: cria can settle
    this against disk, so a steer that contradicts disk is refused rather than reworded. A weak model
    believes cria's assertion over its own reading — told a function lives in a file where it does
    not exist, it invents a plausible one and every later step builds on that.

    Only files that EXIST inside the workspace are checkable; a name cria cannot resolve passes
    silently (#3), and so does an unreadable file. The identifier must be a real word, not a bare
    letter, or ordinary prose would trip it."""
    if not workspace_root:
        return None
    try:
        root = Path(workspace_root).resolve()
    except (OSError, ValueError):
        return None
    for m in _SYMBOL_IN_FILE.finditer(directive):
        symbol, rel = (m.group(1) or m.group(2)), m.group(3)
        if not symbol:
            continue
        try:
            p = (root / rel).resolve()
            if not p.is_relative_to(root) or not p.is_file():
                continue
            body = p.read_text(errors="replace")
        except (OSError, ValueError):
            continue
        if symbol not in body:
            return f"{symbol} in {rel}"
    return None


# A VERSION IS A FACT ABOUT THE WORLD, AND THE AUTHOR CANNOT KNOW ONE IT WAS NOT TOLD.
#
# Shape, not ecosystem (a rule keyed to Go's pseudo-versions is inert on npm and Maven): three or
# more dot-separated numbers, or a `v`-prefixed number, or a version after `@` — which covers semver,
# Go pseudo-versions, gem and wheel versions, Maven coordinates and `pkg@1.2.3` alike. Two-component
# numbers are NOT versions here: `48.58` is a cart total and `3.11` is a language line, and neither
# is something an author invents to be pasted into a manifest.
_VERSION_SHAPED = re.compile(
    r"(?<![\w.-])(?:v\d+(?:\.\d+)+[\w.+-]*|\d+\.\d+\.\d+[\w.+-]*|@\s*v?\d+(?:\.\d+)+[\w.+-]*)")

def _invented_version(directive: str, evidence: str) -> str | None:
    """A version string in the steer that appears NOWHERE in the evidence cria gathered — or None.

    The measured incident, cycle 4 cell 20 (`cart-billing-go x nemotron-elastic`, 15% useful). The
    checks said, verbatim:

        cart.go:8: missing go.sum entry for module providing package
        github.com/shopspring/decimal (imported by cartsvc); to add:
                go get cartsvc

    The author answered with a version it made up — `v0.0.0-20240817123456-001`, a plausible Go
    pseudo-version whose timestamp is the day the run happened — and told the coder four separate
    times to write that literal into `go.mod`:

        "replace it with the exact line `require github.com/shopspring/decimal
         v0.0.0-20240817123456-001`. … Do this now with the edit_file tool."

    It then diagnosed its own defect and repeated it in the same breath: *"Stop editing go.mod with
    invalid version strings … run `go get github.com/shopspring/decimal@v0.0.0-20240817123456`"*. The
    coder obeyed, wrote pseudo-version after pseudo-version, and reached the wall with nothing that
    compiles. The real fix was one grounded word — `go get github.com/shopspring/decimal` — and it
    was sitting in the error message cria had already read.

    This is #5b at its most concrete: a version is not a judgement the author is entitled to make, it
    is a fact about a registry it cannot see. Grounded means the exact token appears in the evidence —
    quoting a version the checks, the disk or the transcript reported is always allowed, which is the
    only way an author should ever have one.

    Refused whole, not stripped: the version IS the instruction in every case measured, so a directive
    with it removed says "edit go.mod to add the required line" and helps nobody. Silence is the safe
    direction (#1).

    WHAT IT BLOCKS IS THE FIRST ONE, and that is the one that matters. Once the coder has pasted the
    invented version into `go.mod` it is genuinely on disk, cria's evidence genuinely contains it,
    and a later steer repeating it passes — correctly, by this rule's own terms. Cell 20's cascade
    was four steers and needed only the first stopped.

    A second rule was written for those repeats and then REMOVED: it asked whether the token's only
    appearances were inside a phrase like `invalid version` or `unknown revision`, which is an
    English exception list doing semantic work in deterministic code (#8) and inert on any registry
    that words its refusal differently (#20). It bought nothing the replay against cell 20's real
    evidence did not already get from the rule above.

    BLAST RADIUS, measured over cycle 4: of **71 distinct steers cria delivered across the 24 runs,
    2 contain a version-shaped token at all**. This rule cannot silence much, which is what makes it
    safe to fail closed."""
    if not directive:
        return None
    ev = evidence or ""
    for m in _VERSION_SHAPED.finditer(directive):
        tok = m.group(0).lstrip("@").strip()
        if not tok:
            continue
        if tok not in ev:
            return tok
    return None


def _false_line_citation(directive: str, evidence: str) -> str | None:
    """A line citation in the steer that exceeds the file's REAL line count as stated by the
    disk list cria itself composed into the evidence — or None. Only files whose count we stated are
    checkable; everything else passes (silence over noise)."""
    counts = {os.path.basename(m.group(1)): int(m.group(2).replace(",", ""))
              for m in _DISK_LINE.finditer(evidence)}
    if not counts:
        return None
    cited: list[tuple[str, int]] = []
    cited += [(m.group(1), int(m.group(2))) for m in _CITE_COLON.finditer(directive)]
    cited += [(m.group(3), max(int(m.group(1)), int(m.group(2) or 0))) for m in _CITE_WORDS.finditer(directive)]
    for f, n in cited:
        known = counts.get(os.path.basename(f))
        if known is not None and n > known:
            return f"{f}:{n} (file has {known} lines)"
    ceiling = max(counts.values())
    for m in _CITE_BARE.finditer(directive):
        n = max(int(d) for d in re.findall(r"\d{1,5}", m.group(1)))
        if n > ceiling:
            return f"line {n} (no listed file has more than {ceiling} lines)"
    return None


# A field the steer tells the coder to read off an API response: `data.get("x")`, `data["x"]`, and
# the same on the handful of names a response is conventionally bound to. Narrow ON PURPOSE — a bare
# backtick is not enough, because a steer legitimately quotes local variables, dict keys the coder
# invented, and column names. The access shape is what marks it as a claim ABOUT THE RESPONSE.
_RESP_VAR = r"(?:data|response|resp|json|payload|body|result|res|r)"
_FIELD_ACCESS = re.compile(rf"\b{_RESP_VAR}\s*(?:\.get\(\s*['\"]([A-Za-z_]\w*)['\"]|\[\s*['\"]([A-Za-z_]\w*)['\"]\s*\])")
# Field names inside a parsed shape entry. Old render: `name(string, …)`,
# `resolved_addresses{ada(string, …)}`. TS render: `  name?: type;` and nested `parent?: {`.
_SHAPE_FIELD = re.compile(r"([A-Za-z_]\w*)\s*[({]")
_TS_FIELD = re.compile(r"^\s*([A-Za-z_]\w*)\??:\s")


def _ledger_field_names(ledger: dict) -> set[str]:
    """Every field name cria actually PARSED out of a fetched response shape — "" when it parsed none.

    Nested names count (`resolved_addresses{ada(…)}` yields both), because a steer naming the inner
    one is telling the truth. Only the shapes block is read; routes and catalogs are paths, not
    fields."""
    names: set[str] = set()
    for entry in (ledger or {}).values():
        shapes = (tuple(entry) + ("", "", ""))[2]
        for line in str(shapes).splitlines():
            if "→" in line:                   # old render: fields follow the arrow
                names.update(m.group(1) for m in _SHAPE_FIELD.finditer(line.split("→", 1)[1]))
                continue
            m = _TS_FIELD.match(line)         # TS render: one `name?: type;` per line
            if m:
                names.add(m.group(1))
    return names


def _field_the_ledger_denies(directive: str, ledger: dict) -> str | None:
    """A response field the steer tells the coder to read that cria's OWN parsed shapes do not have.

    THE VERIFIED ROOT of both maple-preview misses. At call 0029 of run 1786053138 cria injected a
    whole script as a steer, comment and all — "# - address (the resolved Cardano address) ... # -
    total_holders" — and `resolved_address = data.get('address')`. That is the FIRST appearance of
    `data.get('address')` anywhere in the run; the model never proposed it. Neither field exists on
    GET /handles/{handle}; the address is `resolved_addresses.ada` and the holder's count comes from
    a second call to /holders/{address}. cria's own ledger said so, in the same prompt, under the
    words "use these EXACT names and nesting; do not guess". The shipped CLI prints the handle name
    where the address belongs, in BOTH runs.

    This is the discriminator the DICTATES guard cannot make. A steer that dictates code is not the
    problem — the gemma4 4/4 runs were carried by them, and one of those wrote
    `data.get("resolved_addresses", {}).get("ada")`, which is right. The problem is a steer that
    states a FALSE FACT about a source cria has already read (rule 5b). Checked against what cria
    parsed, the good steer passes and the bad one does not.

    SILENT unless cria can actually check: no parsed shapes at all → None, always. A field cria did
    parse → None. Only a field asserted on a response, when cria holds the response's real shape and
    that name is not in it, is refused.

    THE UNION OF ALL ENDPOINTS, not per-endpoint. `address` is a real field — on /holders/{address} —
    so a steer using it against /handles/{handle} passes here even though it is wrong for that route.
    Attributing a field access to a route needs the steer to name the route unambiguously, and
    guessing wrong would refuse a TRUE steer. A miss shows the coder a bad field it may still catch;
    a false refusal leaves it stuck with nothing. Under-refuse, deliberately (#5b, #3)."""
    known = _ledger_field_names(ledger)
    if not known:
        return None                            # nothing parsed → nothing checkable → say nothing
    for m in _FIELD_ACCESS.finditer(directive or ""):
        field = m.group(1) or m.group(2)
        if field and field not in known:
            return field
    return None


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


def _reasoning_of(comp: dict) -> str:
    """The coder's private reasoning from a completion — the split-out ``reasoning_content`` when the
    server provides it, ELSE the message ``content`` (a model that inlines its thinking with no separate
    channel). Mirrors the rumination watcher's ``reasoning or content`` fallback (upstream.py) so the
    watcher isn't silently INERT for any model that doesn't split reasoning out — reading only
    reasoning_content once disabled a whole assist for such models (principle 19)."""
    for ch in comp.get("choices", []):
        msg = ch.get("message") or {}
        r = msg.get("reasoning_content") or msg.get("reasoning") or msg.get("content")
        if isinstance(r, str) and r.strip():
            return r.strip()
    return ""


# THE QUIET-FLAIL STEER IS GONE (operator, 2026-08-13: "I don't like that word list thing. It should
# be removed. The whole steer.").
#
# It decided WHEN TO INTERRUPT THE CODER by matching struggle vocabulary — stuck, failed, error,
# wrong, again — in the coder's own private reasoning. Two of the last four thinking blocks matching
# spent a reasoner call, and if that call produced anything the coder was redirected.
#
# Why the instrument was wrong, not merely mistuned:
#   * it read words the coder did not choose — quoting the pinned task back to itself scored as
#     struggling, in two of the nine fires the walk could check;
#   * it fired on healthy work — a 53% arm rate on one task, and half of the fires that reached the
#     reasoner came back ON_TRACK;
#   * when it fired wrongly the author still had to say something. qwen35/node 0030: cria's own
#     trigger text read "looks like it may be circling", and the directive that came out was "fix the
#     CLI to output \"Invalid handle\" when the handle doesn't contain a dot, as the tests expect" —
#     a requirement no one had asked for, which the coder then built;
#   * tuning it is the tell (#4, #9's corollary). A rule that needs an exception list should have
#     been a question, and the word list IS the exception list.
#
# Removed rather than replaced. The obvious replacement — "no bytes changed on disk across N drives"
# — has never been measured as a stuck signal, and a genuinely stuck coder often does keep varying
# its actions; swapping one unmeasured trigger for another is how four revisions of a similar rule
# each cost a run. The safe direction is REMOVE (#1), and everything that catches a real stall is
# still here: the completion gate, the repetition guard, the wheel-spin probe, the satisfaction
# check, and the coder's own checks.
#
# `_record_reasoning` and the window it kept go with it: nothing else ever read them. The
# answer-contradicts-thinking rescue reads the CURRENT completion, not a window, and is grounded in
# a structural fact (the reply carries a verdict its own thinking denies) rather than a vocabulary.
# `_reasoning_of` stays — the rescue and the captures both use it.

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
_SPILL_SEG = re.escape(webfetch.SPILL_DIR.lstrip("./").rstrip("/"))   # cria names the dir; nothing else spells it
_SEARCH_FILE_RE = re.compile(r"\.?/?" + _SPILL_SEG + r"/search-[\w.\-]+\.txt")


def _search_key(path: str) -> str:
    """ONE canonical key for a spill search file. Both patterns above accept `./tmp/…`, `/tmp/…` and
    `tmp/…`, and the same file arrives spelled differently from the two places it is read: cria writes
    the pointer as `./tmp/read-only/x.txt` and the model calls read_file with `/tmp/read-only/x.txt`.
    Keying a dict on the raw capture made those two different files.

    Walked on ada-handles_mellum2_codex_poff_1785686596: the query lookup missed, so cria told the
    relevance judge `THE SEARCH QUERY THE AGENT USED: (none)`. The judge reasoned "That's not a query
    at all… the search was effectively a null query and the results were noise", ruled it off-target,
    and cria PERMANENTLY DELETED the file — which held github.com/koralabs/handles-public-api, the
    API behind the host the task named, and the docs page on resolving handles to addresses. The
    model gave up in the same turn. cria withheld a query it was holding, then destroyed the answer
    on the strength of the judge's reply to the question it had mangled."""
    return "/" + (path or "").lstrip("./").lstrip("/")
_SEARCH_POINTER_RE = re.compile(r'web_search "([^"]*)"\s*[—-]+\s*results saved to (\.?/?'
                                + _SPILL_SEG + r'/search-[\w.\-]+\.txt)')


def _results_name_the_tasks_host(task: str, results: str) -> str:
    """A host the TASK names that also appears in the search RESULTS, or "".

    The one cross-check cheap enough to stand over a destructive verdict: results that name the very
    domain the user asked about are on-target by construction, whatever a judge says about them.
    Both strings are cria's own, so this is exact rather than a second opinion.

    Hosts only — a bare word the task mentions would match half the web. Requires the host to carry a
    dot and a plausible TLD so "e.g." or a version number can never qualify."""
    if not task or not results:
        return ""
    hosts = set(re.findall(r"\b((?:[\w-]+\.)+[a-z]{2,})\b", task.lower()))
    low = results.lower()
    for h in sorted(hosts, key=len, reverse=True):
        if h.rsplit(".", 1)[0] and h in low:
            return h
    return ""


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
    # A CONCRETE URL IS WORTH ACTING ON EVEN WHEN THE QUERY IS FINE. The judge's own prompt says: "make
    # the recommendation a concrete URL to fetch (the API's .../openapi.json, or the docs page) — the
    # supervisor will fetch it directly." It did not: `on_target` returned first, so a URL handed back
    # alongside a good query was dropped on the floor. Walked on
    # ada-handles_mellum2_codex_poff_1785714194 call 0003: the judge ruled the query on-target AND
    # returned "https://api.handle.me/openapi.json" — the exact live URL the coder then spent six more
    # calls rediscovering on its own at 0009. cria promising a model something it does not do is the
    # same false-fact class as any other, and here it was promising it to its own judge.
    #
    # A search is still a legitimate move, so an on-target query is NOT rewritten — only a URL is acted
    # on, and only through the same host-grounding check below that an off-target one passes.
    if not rec or (on_target and not _looks_like_url(_usable_query(rec) or "")):
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
                                 (f"fetching {url} — the source this task names, read it directly"
                                  if on_target else
                                  f"'{query}' looked off-target for this task — fetching {url} instead"))
    # SURFACE, DO NOT SUBSTITUTE. This rewrote the coder's own search arguments in place, so the
    # question the coder actually asked was never asked at all — and cria's replacement became the
    # record held against it. Doctrine #2's corollary states the rule outright: "cria never
    # SUBSTITUTES its own action for the coder's: surface the fact, steer, and let the coder act."
    #
    # Measured, nemotron-elastic/rust 0006. The plan step in flight was "Read the crates.io TOML
    # crate documentation"; the judge reasoned "That seems off-target: they need to write a tool, not
    # search docs", and cria searched "rust toml dotted key path command line tool" instead. The
    # documentation the step asked for was never fetched, and the saved results held 20 finished
    # tools rather than the API the coder needed.
    #
    # The coder's search runs. cria says what it thinks and lets the coder decide — which is also the
    # only version that survives the judge being wrong, and here the judge was wrong because it was
    # never told what step was in flight.
    _add_note(coder, f"'{query}' may be off-target for this task — '{rec}' would search for what the "
                     f"task actually needs. Your search runs either way; re-run it with that if you agree.")
    rlog.emit("loop.search_query_judged", action="noted", query=query, rec=rec)
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
    outcome = read_gate(gs.gate_plan, probe, rlog)
    # THE READING IS STATE, whatever cria does with the steer. This is the same probe result the
    # completion gate reads (same call id, same plan) and it used to be read here and dropped on the
    # floor, so a gate that flipped green→red on a redirect/wheel-spin turn left last_gate_red False.
    record_gate_state(gs, outcome, gate_error_text(outcome))
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
    authored = "" if author is CANNED else (author("wheel_spin", gs, outcome, body, rlog) or "")
    # `spoke=True` was a LITERAL, so the log said `spoke` on 121 of 121 occasions and could not have
    # said anything else — a tautology wearing a measurement's clothes (#12). What actually varies is
    # who wrote the steer and whether it carries any ground truth, so record THAT: `authored` false
    # with `grounded` false is cria talking with nothing to say, and now it is countable.
    rlog.emit("loop.spin_probe_result", step=step, authored=bool(authored), grounded=bool(truth))
    return authored or canned


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
        v = coder.get(bodykeys.RUMINATION) or {}
        attempt += 1
        # WHICH GUARD, AND ONLY ITS OWN NUMBERS — the same rule the capture header now follows, at
        # the seat that is actually read when someone asks why a call stopped. Four backstops abort a
        # turn and this reported the RUMINATION watcher's two counters for all of them, so a
        # degenerate-run abort logged `hits: None, reasoning_tokens: None`. Seen live mid-cycle-4
        # while answering exactly that question about a 194-second call.
        which = ("degenerate" if v.get("degenerate") else
                 "window_exhausted" if v.get("window_exhausted") else
                 "dead_stream" if v.get("dead_stream") else "rumination")
        counts = {"degenerate": ("chars",), "window_exhausted": ("room", "frames"),
                  "dead_stream": ("chunks",), "rumination": ("hits", "reasoning_tokens")}[which]
        rlog.emit("loop.rumination", step=step, attempt=attempt, guard=which,
                  **{k: v.get(k) for k in counts})
        # TWO detectors abort a turn, and they are not the same failure — so they do not get the same
        # notice. The phrase watcher fires on second-guessing ("actually", "wait") and its notice says
        # stop re-examining. The degenerate-tail backstop (upstream.py) fires on a stream that has
        # locked into repeating one passage, where there is no second-guessing to stop. Rendering the
        # phrase notice for it produced, five times in one walked run, "[RUMINATION GUARD] Your last
        # reasoning pass hit 0 second-guessing phrases … after ~2048 reasoning tokens" — a stated
        # cause of ZERO hits (self-refuting), a character count relabelled as tokens, and advice
        # aimed at the wrong behaviour. Rule 5b: cria states the trigger it actually has.
        # THREE detectors abort a turn now, and a third failure gets a third notice for the reason
        # the comment above gives. A dead stream produced NOTHING — telling it to stop re-examining,
        # or to stop repeating a passage, would name a behaviour that did not happen (5b).
        conv = conv + [{"role": "user", "content": (
            prompts.load("rumination_guard_window") if v.get("window_exhausted") else
            prompts.load("rumination_guard_dead_stream") if v.get("dead_stream") else
            prompts.load("rumination_guard_degenerate") if v.get("degenerate") else
            prompts.render("rumination_guard", hits=v.get("hits", "several"),
                           tokens=v.get("reasoning_tokens", "many")))}]
        rlog.phase = f"{phase}-focus{attempt}"
        coder = massage.apply(
            _parse_completion(coder_chat({**body, "messages": conv}, rlog)), body.get("tools"), rlog)
    coder.pop(bodykeys.RUMINATION, None)  # internal marker — never forward it
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
    _last_write_path_seen = False   # did any pass of this turn actually carry a mid-write cut?
    conv = list(body.get("messages") or [])
    while _cut_off(coder) and attempt < MAX_TRUNCATION_RETRIES:
        path = _truncated_write_path(coder)
        _last_write_path_seen = _last_write_path_seen or path is not None
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
    coder.pop(bodykeys.RUMINATION, None)  # a retry may itself ruminate — never forward the marker
    for ch in coder.get("choices", []):
        if ch.get("finish_reason") == "rumination":
            ch["finish_reason"] = "stop"
    if dropped:  # no hidden guards: the partial write was refused
        # SAY WHICH IT WAS. The retry remedy already distinguishes a self-cut from a cap; these two
        # closing messages did not, so the model got the correct diagnosis on the retry and "your
        # response hit the output limit" on exhaustion — cria contradicting itself about one event.
        # Measured (run 0727-145921): 17 truncations, ALL self-cuts. It matters: told it hit a limit,
        # a model shrinks its content, and a generation that ended early is not fixed by being shorter.
        # …AND SAY WHICH THING IT WAS, TOO. Both wordings above assert a WRITE. When
        # `_truncated_write_path` found none, the loop breaks out at `path is None` — cria's own
        # finding that this was not a write — and then fell into the write wording regardless.
        # Measured over five days: all 17 truncations had `path is None`, so 17 of 17 told the model
        # its last write was refused and that it stopped "partway through writing the file" (#5b).
        was_write = _truncated_write_path(coder) is not None or _last_write_path_seen
        key = ("selfcut_write" if selfcut else "truncated_write") if was_write else "truncated_call"
        _add_note(coder, ("output stopped early mid-write — partial write refused (retry in smaller pieces)"
                          if was_write and selfcut else
                          "output hit the token limit — partial write refused (retry in smaller pieces)"
                          if was_write else
                          "output ended before the call was complete — partial call refused"))
        _refusal_turn(body, prompts.load_map("call_refused")[key])
        # WHICH SENTENCE WENT OUT, in the event that produced it (#12). The `path`/`selfcut` fields on
        # `loop.truncated` describe the DETECTION; nothing recorded the wording, so the incident this
        # branch was written for — 17 of 17 truncations telling the model its WRITE was refused when
        # cria's own `path is None` said it was not a write — was invisible in the log and had to be
        # reconstructed from prompt captures. Now it is one field.
        rlog.emit("loop.truncated_refused", step=step, wording=key, was_write=was_write)
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
    """The files the coder has been TOUCHING, as a LIST — name, byte size, line count, read from
    disk NOW. Contents are deliberately NOT inlined (operator redesign, 07-30): the steer author
    holds read_file/list_dir and gathers its own evidence, exactly like the step critic. Inlining
    was the 210K-prompt incident — a 57K minified spec the coder curl'd to ./api.json flowed in
    whole, TWICE via two path spellings, into a composed two-message prompt the context floor
    cannot shrink (no turns to drop), and the reasoner died silently four calls in a row (run
    0729-gemma4 C1 0062-0065). The line count is load-bearing: '57,588 bytes, 1 line' tells the
    author it is looking at a minified blob to grep, not code to read whole. Deduped on the
    CANONICAL path — `api.json` and `./api.json` are one file."""
    if not root or root == ".":   # "." is cria's OWN dir, never the coder's workspace — never read it
        return ""
    paths: list[str] = []
    seen: set[str] = set()
    for p in list(recent_writes or []) + [spin_path]:
        canon = os.path.normpath(groundtruth.resolve(root, p)) if p else ""
        if p and canon not in seen:
            seen.add(canon)
            paths.append(p)   # keep the coder's own spelling for display
    if not paths:
        return ""
    lines: list[str] = []
    for p in paths:
        try:
            raw = open(groundtruth.resolve(root, p), "rb").read()
            n_lines = raw.count(b"\n") + (0 if raw.endswith(b"\n") or not raw else 1)
            lines.append(f"FILE {p} — {len(raw):,} bytes, {n_lines:,} line{'s' if n_lines != 1 else ''}")
        except OSError:
            lines.append(f"FILE {p} — does NOT exist on disk")
    return "\n".join(lines)


def _completion_of(completion: dict, text: str) -> dict:
    """``completion`` with its message content replaced by ``text`` and its tool_calls cleared.

    How a verdict delivered as a TOOL CALL re-enters a caller that reads verdicts out of message
    content. Every truncation, cleaning and parse step downstream stays exactly as it is; only the
    channel the answer arrived on changes."""
    out = dict(completion)
    choices = []
    for ch in completion.get("choices") or [{}]:
        msg = {**((ch.get("message") or {})), "content": text}
        msg.pop("tool_calls", None)
        choices.append({**ch, "message": msg})
    out["choices"] = choices or [{"message": {"role": "assistant", "content": text}}]
    return out


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


_content_text = massage.content_text  # ONE owner for the string-or-parts-list content shape


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
    # AN INSTALL INTO A SHARED ENVIRONMENT IS NOT WORKSPACE PROGRESS, whatever mutator words ride
    # along on the line. Walked on cycle 4 cell 13 (`shipping-rates-rb x ternary-bonsai`, 10% useful,
    # 34 of 54 calls spent trying to obtain a gem): `mkdir -p vendor/bundle && gem install
    # eu_countries` read as a change on new ground and flushed a repetition window that had been
    # filling for eighteen calls. The walk replayed the run's real 53-call sequence through this
    # guard with the live constants — it fires ZERO times. A local install (`--path vendor/bundle`, a
    # venv, `npm install` with no `-g`) really does populate the project, and dirguard's own two
    # patterns are what tell them apart.
    from . import dirguard as _dg
    if text and _dg.installs_outside_workspace(text):
        return False
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


def session_research_facts(messages: list, sess=None) -> str:
    """The routes AND response field names cria really read from a 2xx document this session, as one
    block for a plan judge — "" when nothing spec-shaped has been fetched.

    Same ledger, same merge and the same abstain-on-empty contract as :func:`known_routes`; that one
    yields routes alone for the route CHECK, this one carries the field names too, because the judges
    are also asked to spot a guessed FIELD name and could not."""
    merged = _merge_fetches(_extract_fetches(messages), (getattr(sess, "fetched_pages", None) or {}))
    return groundtruth.researched_facts(merged)


def _named_gap(findings: str) -> str:
    """cria's most concrete unresolved finding, as a sentence for the coder — or "".

    A STEER MUST NAME SOMETHING. When the completion judges cannot produce a usable verdict, cria
    falls back to `unverified_step`, which names nothing: "This step is not yet verified as complete.
    Keep working: re-check the step's goal against the files on disk." Walked on maple-preview
    1786228135, where the coder received that same paragraph THREE TIMES, verbatim, and answered the
    only way it could — re-read the same five files and re-declare done. Four gate cycles, no bytes
    written.

    In all three cases cria was holding a concrete finding. Its own execution probe had reported "the
    README documents no command that runs handle_resolver.py"; its own offline re-run had reported the
    tests never touch the service. Both went to a judge and neither to the coder.

    NOT "facts outrank prose" (operator, 2026-08-08: a fact about the code is not a fact about the
    task, and only a reasoner relates the two). This fires ONLY where the authored text names nothing
    at all, and it appends rather than replaces — the generic instruction still ships, with something
    actionable attached. Empty when cria holds nothing, which keeps silence the honest answer."""
    f = (findings or "").strip()
    # In a prompt file (#22) and in cria's model-facing voice (#17: never the literal token).
    return ("\n" + prompts.render("named_gap", findings=f)) if f else ""


def _mark_own_notes(session: str) -> str:
    """Tag every line of the serialized session that is cria's OWN earlier output.

    The steer author is handed one flat transcript containing real tool results, the coder's
    speculation, and cria's previous steers — and nothing distinguishes them. mellum2 1786302864
    call 0166 read a claim out of that wall ("the MCP endpoint only supports search_handles"),
    treated it as endpoint evidence, and reversed call 0134's CORRECT directive; 0134 had cited the
    real `tools":[{"name":"get_handle"…}]` response. The claim it believed was the coder's own
    stuck reasoning, quoted back. That reversal began a four-way flip-flop and cost 83 edits.

    A prior steer re-entering as evidence is the worst case, because it is a FEEDBACK LOOP: cria's
    wrong answer becomes the grounds for cria's next wrong answer, with more confidence each round.
    The prompt tells the author to discount anything marked this way; this is what does the marking.
    Keyed on cria's own marker namespace, which is applied at the sites that inject (#12), never on
    wording."""
    if not session:
        return session
    # …INCLUDING THE ONE cria ACTUALLY WRITES INTO THE HISTORY. The three keys were the completion
    # sentinel, the rollup marker and a prior steer — all of which cria injects and then largely
    # replaces, so they are rarely in the span this runs over. The continuation reframe is not like
    # them: cria composes it and the harness stores it AS the conversation, so it is in the history
    # by construction. Measured across one day, 1,926 real prompts: ⟦ctx:continuation⟧ in 526 of
    # them, ⟦ctx:steer⟧ in 150 — and the tag this function exists to add in ZERO. cria's own reframe
    # is precisely the feedback loop described above: cria's account of the work becomes the grounds
    # for cria's next directive, with more confidence each round.
    own = (indicators.SENTINEL, selfcompact.SUMMARY_MARKER, "⟦ctx:steer⟧", CONTINUATION_MARKER)
    out = []
    for line in session.splitlines():
        if any(mark in line for mark in own):
            out.append(f"{line}   [EARLIER NOTE FROM THIS SYSTEM — not evidence]")
        else:
            out.append(line)
    return "\n".join(out)


def _label_spill_entries(disk: str) -> str:
    """Disk-section lines naming a file under cria's own spill dir get the ``spill_note`` label —
    the entry STAYS (the "not listed = does not exist" clause must keep holding), it just stops
    reading as the coder's own file activity.

    WHY, and why only here: the steer author's template heads this section "THE FILES IT HAS BEEN
    CHANGING", and on nemotron-nano 1786243834 the only entry was the spilled openapi reference —
    file activity where the coder had produced nothing, feeding five ON_TRACK verdicts over an
    untouched workspace. The critic's header ("WORKSPACE FILES") claims no authorship, so its
    inventory is left alone.

    BOTH branches of that section are labelled. The first cut did only the `workspace_inventory`
    fallback, while the PRIMARY source (`_fresh_disk_facts`) can list the same spilled file — the
    coder attempts an edit on it, cria refuses, but the refusal still lowers a tool_call that
    `_touched_paths` picks up — and the primary wins whenever it is non-empty. One path and not its
    twin is the failure mode `groundtruth` names in its own docstring.

    The two branches render differently (``  tmp/read-only/x (96221 B)`` vs
    ``FILE ./tmp/read-only/x — 96,221 bytes, 1 line``), so the test is containment of the spill
    directory as a path segment, not a prefix on the stripped line.

    The note says what the DIRECTORY is, never who wrote a given file into it: cria refuses
    SYNTHETIC writes there but cannot stop a raw `curl -o tmp/read-only/…`, so "the coder did not
    write this" is a claim cria cannot always support — and asserting it would be the same rule-5b
    fault this function exists to remove, pointing the other way."""
    note = prompts.load_map("workspace_inventory").get("spill_note", "").strip()
    if not disk or not note:
        return disk
    seg = os.path.normpath(webfetch.SPILL_DIR).strip("/") + "/"
    return "\n".join(f"{line} {note}" if seg in line.replace("\\", "/") else line
                     for line in disk.splitlines())


def _verdict_nudge(obj: dict, done: bool, routes: str = "", *,
                   evidence: str = "", workspace_root: str | None = None, rlog=None) -> str:
    """The coder-facing nudge from a critic verdict dict: the ``reason``, plus the ``proposed_fix`` (a
    concrete next action the critic named) when the step is NOT done — so the coder is handed a move,
    not just a diagnosis. ``proposed_fix`` is meaningless on a pass (nothing to fix), so it is dropped
    when ``done``. Either field may be absent/empty; the fix is appended on its own line when present.

    THE SAME BAR AS A STEER, because it is the same kind of thing. A proposed fix is authored text
    the coder acts on, and it used to face exactly one guard — the route check below — while an
    authored steer faces the whole of :func:`_grounded_steer_or_none`: role-play, argument blobs,
    ungrounded URLs, phantom filesystem paths, phantom response fields. Measured over the captures:
    134 proposed fixes reached the coder across 41 sessions, and replaying them through the steer
    guards with no evidence at all drops 10 for naming a URL — among them
    ``https://github.com/guyp/decimal``, a repository that does not exist, and several docs.rs pages
    the judge invented the shape of. The evidence the judge itself was shown is passed in, so a URL
    it legitimately READ is still allowed through; the check is against what cria composed, exactly.

    ``ask`` is deliberately not threaded: the reasoner-backed arms of that function stay off here, so
    this costs no model call. Only the deterministic guards run. The REASON always survives — the step
    really was not done; only the invented move is dropped."""
    reason = str(obj.get("reason", "")).strip()
    fix = str(obj.get("proposed_fix", "")).strip()
    if done or not fix:
        return reason
    # A `METHOD /path` route is unambiguous — nothing writes "POST /x" about a file it is creating —
    # and a judge learns that spelling from cria's OWN shape ledger. Measured (run 0727-153326): the
    # critic proposed `POST /handles/resolve`, a route in no spec, 12 times; the coder grepped for
    # that literal string across 322 calls on one step.
    if routes and urlgrounding.ungrounded_routes(fix, routes):
        return reason
    if rlog is not None and _grounded_steer_or_none(fix, evidence, rlog,
                                                    workspace_root=workspace_root) is None:
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
