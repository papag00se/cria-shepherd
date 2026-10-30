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

import copy
import difflib
import hashlib
import inspect
import json
import os
import posixpath
import fnmatch
import re
import threading
import time
import urllib.parse
import uuid
from collections import Counter
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

from .upstream import UpstreamProtocolError
from .imageworkflow import current as _image_current, review_view as _image_review_view

from . import bodykeys, contextfloor, dirguard, handoffdistill, tokenratio, generation, generationguards, modelview, wsview, stalledwork, groundedaction, writeobservation, pastedfile, livingplan, stepreview, completedwork, completionredrive
from . import callcapture, dedup, denial, editrecovery, execcheck, fetchfacts, filefacts, focustrim, groundtruth, indicators, massage, participation, probediscovery, probegate, probeparse, proberun, prompts, reasoning, selfcompact, shellinput, shellshape, toolmenu, urlgrounding, verifytools, webfetch
from .upstream import CallerContextRetryNoChange, ContextRefitNoChange
from . import admission
from .admission import has_actionable_tools as _has_actionable_tools
from .classify import JUDGE_MAX_TOKENS, _task_key, latest_user_text
from . import jsontext, planner, refusalledger, writeproxy
from .jsontext import extract_json_object, strip_think
from . import research, researchpolicies, shrinkprotection, assistruntime, completionapproval, completionmeasure, completiondiagnosis, completionconfirmation, runnercontract, repositorychecks, evidencesummary, semanticquery
from . import contextrestoration, filepresence, ledgercopies, preamblepolicy, reorientation, steppreparation, system1wiring
from .toolstages import policy_log
from .modulestate import ModuleInput, ModuleState
from .completionreview import (ReviewInput, ReviewResult, ReviewStatus, ReviewTrigger,
                               record_satisfaction as _record_satisfaction)
from .rumination import WINDOW_EXHAUSTED_FRACTION
from .plan import Plan, PlanItem
from .groundtruth import workspace_inventory
from .planner import (_extract_cwd, missing_deliverables, reasoned_noise_indices,
                      surviving_noise_drops)
from .searchloop import first_domain_in, normalize_search
from . import probeclassify
from .shelltool import (_CMD_FIELDS, find_shell_tool, is_shell_tool_name, shell_args,
                        tool_declares_time_budget, with_time_budget, writes_something)
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
MAX_TRUNCATION_RETRIES = generationguards.MAX_TRUNCATION_RETRIES
# Rumination guard retry budget — how many times to re-prompt a reasoning-loop turn to refocus
# before accepting whatever it produced. Same MAX_BAIL_RETRIES ceiling.
MAX_RUMINATION_RETRIES = generationguards.MAX_RUMINATION_RETRIES
# WHEEL-SPINNING trigger (operator, 2026-07-11; windowed 2026-07-12): the same file written this
# many times — ANY content — within the last WRITE_WINDOW forwarded calls → run the gate mid-work
# and INSERT the results into the coder's next turn. No done-claim needed, no judging — pure
# ground truth, aimed at the tiny-edit spiral: the file's indentation is wrong, and the model
# rewrites it ten times changing SOMETHING each time but never the fault, so content-hashing
# (the repetition trigger) can't see it and a consecutive streak undercounts it (reads/tests/
# other-file writes interleave). Byte-identical rewrites trip the (stricter, 3×) repetition
# redirect first; this is the varying-content tier.
WHEEL_SPIN_WRITES = stalledwork.WRITE_THRESHOLD
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

REPEAT_FINGERPRINT_N = stalledwork.REFUSAL_THRESHOLD
REPEAT_WINDOW = stalledwork.REFUSAL_WINDOW
# Writes are counted over a window sized to five full write→read→test cycles (3 calls per
# edit): the canonical tiny-edit spiral interleaves a cat and a pytest between edits, so five
# edits span 13 calls — a 12-call window missed the incident's exact shape by ONE, permanently
# (round 5). Sparser revisits (3+ calls between edits) still age out and stay silent.
WRITE_WINDOW = stalledwork.WRITE_WINDOW
# The write class is ONE predicate (`_is_write_tool`, membership in _WRITE_TOOLS below) — shared by
# the wheel-spin and truncation guards, so a route can't be a write to one and not the other. (A
# loose substring regex was tried and split the two: it mis-classed `write_stdin` as a file write and
# missed nothing the exact set doesn't.)
# Probe re-issues after a history rewrite erased the result. A harness compacting EVERY turn
# would otherwise re-issue forever; past the cap the absent result falls back to fail-open (the
# pre-existing don't-wedge behavior).
MAX_PROBE_REISSUES = repositorychecks.MAX_PROBE_REISSUES
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
# Both `compaction_reframe_dropped*` templates say this in their first sentence (a test pins it): the
# continuation then holds NO model-authored prose, only re-derived ground truth.
_DROPPED_PROSE_LEAD = "the handoff summary from that turn did not survive"
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


@dataclass(frozen=True)
class Confirmation:
    """The approve-path brake's result, including whether it actually inspected a workspace."""
    confirmed: bool
    observed: bool
    reason: str = ""

    def __iter__(self):
        # Keep the established two-value private-call contract for the task satisfaction caller.
        yield self.confirmed
        yield self.reason


@dataclass(frozen=True)
class Verification:
    """A step-critic result plus its actual approve-path confirmation, if one occurred."""
    done: bool
    reason: str
    confirmation: Confirmation | completionconfirmation.Result | None = None
    step_result: stepreview.StepResult | None = None

    def __iter__(self):
        # `_verify` historically returned ``(ok, reason)``; ordinary callers retain that contract.
        yield self.done
        yield self.reason


@dataclass
class GuardState:
    """Cross-turn repetition / wheel-spin guard state: the ground-truth-probe round-trip plus the
    rolling action/write windows. Shared so ONE implementation of the guard drives both paths —
    ``PlanSession`` IS-A ``GuardState`` (the plan loop), and the plan-off direct path keeps a bare
    ``GuardState`` per session. The module-level ``guard_*`` functions operate on this state."""
    externalization_state: object | None = field(default=None, repr=False)
    externalization_offers: dict | None = field(default=None, repr=False)
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
    # INCOMING: when the model READS a spilled search file, judge its relevance
    # (_judge_search_reads); an off-target file goes in ``poisoned_search_files`` so its reads
    # are stripped going forward, and ``search_recommend`` steers the better query.
    judged_search_files: set = None     # spill files already read-judged (don't re-judge)
    poisoned_search_files: set = None   # spill files judged off-target → strip their reads going forward
    search_recommend: str = ""          # the last recommended query to steer
    rehunt_verdicts: MutableMapping[str, bool] | None = None  # Source-owned live judgment/grant cache
    semantic_pending: semanticquery.PendingTurn | None = field(default=None, repr=False)
    web_session: str = ""               # the key webfetch's per-session search/fetch gates are keyed by,
    #                                     so the loop can ask about the pair those gates would act on
    probe_reissues: int = 0  # probes re-issued after a history rewrite erased their result (capped)
    # C28b: a SEPARATE cap for polling the CURRENT plan's still-open transport after a history
    # rewrite (the selected repository reissue hook) — sharing `probe_reissues` with new-gate reissues
    # would either starve a genuine new-gate need or let polling itself wedge a session whose harness
    # compacts EVERY turn (there is no real result to ingest in that path, so the plan's own
    # wall-clock deadline never gets a chance to fire). Bounded on its own, independently.
    probe_poll_reissues: int = 0
    gate_plan: object = None  # probegate.GatePlan for the in-flight gate (maps result → reports)
    recent_writes: list = None  # rolling window: written path (or None) per forwarded tool call
    # …AND THE CALL IDS BEHIND THEM, so a write cria REFUSED can be taken back out. The window is
    # filled from the model's OUTBOUND completion, before anything runs, and a syntax/dirguard
    # refusal is decided later in the lowered command — so a refused write counted as a rewrite.
    # Walked at 20260820T131719: six `write_file cart.go` calls, THREE of them refused ("write_file
    # REFUSED (not written): this would replace a currently-valid cart.go"), `loop.wheel_spinning`
    # fired with `writes: 5`, and the steer told the coder "you have rewritten cart.go repeatedly".
    # `denial.is_denied` already answers this from the prior turn's results (#12, #5b).
    recent_write_ids: list = None
    spin_recheck: str = ""      # a path whose same-turn batch may reach the wheel-spin count once its results are known
    spin_path: str = ""  # the file whose windowed rewrite count tripped wheel-spinning
    spin_probe_due: bool = False  # wheel-spinning tripped → run the gate before the next coder turn
    spin_probe: bool = False  # the in-flight gate is a spin probe (insert results, don't judge)
    action_seq: int = 0  # forwarded-call counter — dates the refusal trigger's last fire
    # WHEN THE REFUSAL TRIGGER LAST FIRED. Its evidence lives in the message history, and a fire
    # cannot flush that — so without this it re-fires on every call until the refusals age out.
    # Replayed on cycle 4 cell 13: 14 redirects over 48 calls instead of one. One intervention
    # consumes the evidence.
    blocked_fired_seq: int = -10_000
    repeat_action: str = ""  # the most recent REFUSED call, as `name args` (for the reasoner)
    # WHAT THE TRIGGER COUNTED. Two routes used to reach this redirect — the same action seen N
    # times, and cria REFUSING N calls — sharing one sentence and one hardcoded 3. Walked on
    # shipping-rates-rb x ternary-bonsai: the refusal route fired, and cria told its own steer author
    # "It keeps repeating the SAME action 3x without the outcome changing: exec_command {which
    # bundler ...}" about a command the coder had issued ONCE. The author wrote that back as "you've
    # already confirmed they're unavailable (three failed attempts)" and, on that premise, ordered
    # the coder to hardcode data the task forbids hardcoding in those words. A count cria reports
    # must be a count cria measured (#12). The repetition route is now gone entirely, so there is one
    # route and one meaning.
    repeat_count: int = 0     # how many of the recent calls cria refused
    redirect_due: bool = False  # refusals tripped → gate + redirect before next coder turn
    redirect_probe: bool = False  # the in-flight gate feeds a reasoner-authored redirect (loop only)
    nudge_reason: str = ""  # a steer to hand the coder on its next work turn
    guidance_history: list[str] = field(default_factory=list)  # delivered observations, never pending orders
    # {note: `action_seq` at its latest successful delivery}. A carried note keeps its exact words —
    # "the CURRENT state of the repo" over a red check — so each one is rendered with its age in the
    # coder's own calls (`_dated_guidance`). No entry = no age is claimed.
    guidance_delivered_seq: dict = field(default_factory=dict)
    # The last gap the PERIODIC completion check named to the coder. Its only job is to stop the
    # same verdict being re-delivered: that check fires on a drive counter, so an unchanged workspace
    # produces an unchanged verdict, and one cycle-2 cell produced twelve consecutive identical ones.
    last_gap_named: str = ""
    # The authoritative survey generation and typed subject behind the last delivered absence.
    # A later identical verdict may re-deliver only when a complete, current harness survey says
    # the workspace changed and still proves this exact task-named file absent.
    last_gap_subject: str = ""
    last_gap_observation: str = ""
    # A verified typed missing-file diagnosis temporarily owns the next coder bodies.  The plan
    # remains intact; only its cursor is withheld until a tool result proves this exact file write
    # landed.  These are durable because a restart must not restore the stale cursor mid-remediation.
    completion_remediation_subject: str = ""
    completion_remediation_reason: str = ""
    # The exact remediation body reached a coder reply with these non-write calls.  Only their
    # matching harness results can earn the one-shot non-terminal follow-up below.
    completion_remediation_nonwrite_ids: tuple[str, ...] = ()
    completion_remediation_nonwrite_seen: bool = False
    nudge_reply: str = ""  # the coder's own no-tool-call reply the pending nudge is ABOUT — re-framed
    # views rebuild history from the harness body, which never saw an internal prose turn, so without
    # this the unexecuted-write nudge says "your last message contained the file's contents" about a
    # message that is not there (nemotron-nano 1786243834 call 0073: told to resend content the frame
    # had dropped, the model re-read the spec a 7th time instead)
    steer_source: str = ""  # human label of which guard produced the pending steer (for the ⟦cria⟧ note)
    coder_turns: int = 0  # acting coder turns since the last gate — drives the PERIODIC check-in
    # THE DRIVE THE PERIODIC STEP CHECK LAST RAN ON. It used to stamp a `coder_turns` TICK, which the
    # gate zeroes every 15 turns: 12 was the only multiple of 12 that counter could hold, so the memo
    # matched forever and the check fired once per SESSION. Same stamp-what-ran shape as
    # `satisfaction_last_drive`, on the same monotonic clock.
    step_checked_drive: int = -1
    drive_count: int = 0  # total drives this session, BOTH drivers — paces the periodic SATISFACTION
    # and STEP checks. Monotonic: nothing resets it, which is the whole reason both read it.
    # THE DRIVE THE OFF-RAMP CHECK LAST ACTUALLY RAN ON, not the last one it was due on. Stamped
    # only when the check executes, so a drive where it was skipped is retried at the next
    # opportunity rather than costing a whole interval. -1 means it has never run.
    satisfaction_last_drive: int = -1
    # The newest authoritative whole-task verdict. A false result is a completion barrier, not just
    # a steer: no completion-shaped output may cross it until a later current verdict is true.
    # Keep its exact accepted evidence separately; it is the ground truth that caused the barrier,
    # never a replacement authored by cria.
    latest_satisfaction: bool | None = None
    latest_satisfaction_evidence: object = None
    # The non-terminal durable-deliverable observer has its own stamp: it must never consume or
    # alter the completion critic's cadence/state.
    deliverable_observation_last_drive: int = -1
    periodic_probe: bool = False  # a periodic check-in gate is in flight (insert its ground truth, no verdict)
    # A periodic check-in whose result was survey-only gets exactly ONE follow-up replan against the
    # now-surveyed view (guard_periodic_replan_after_survey). Set the instant that replan is issued;
    # cleared only when a FRESH periodic check-in starts (guard_periodic_gate), so a second
    # consecutive survey-only result — on the replanned gate itself — stays silent instead of looping.
    periodic_replan_done: bool = False
    runner_reset_signature: str = ""  # one definitive JS runner judgment per unchanged failing gate
    module_state: ModuleState = field(default_factory=ModuleState)
    # Task-stable selection is durable; judgment signatures reset with transient gates.
    pilot_selection: tuple[str, ...] | None = None
    pilot_binding: assistruntime.AssistRuntime | None = field(default=None, repr=False)
    # A scheduled step critic returned done, but its approve-path brake had no surveyed workspace.
    # It is NOT an approval: acquire one bounded survey/gate round, then re-run the critic against
    # that observed view.  Keeping this separate from ``periodic_probe`` matters: that check-in
    # never has step-advance authority.
    periodic_observation: bool = False
    last_gate_red: bool = False  # the most recent gate/check-in found real error-class problems (RED). The
    # plan-off satisfaction judge gates on this: while the deterministic checks already say NOT-done, the
    # LLM done-judge is redundant (both say not-done) and — for a model that can't help emitting a "run the
    # tests" tool call instead of a verdict — pure wasted, always-fail-closed calls. Only spend it on GREEN.
    # STALL tracking (NOT termination — the stall terminator was removed; cria never ends a non-converging
    # session or hands back to a human). A RED-gate streak with the SAME unchanged finding = the coder is
    # stuck on one thing; that drives the REASONED thrash-assist (a concrete unstick step), never a give-up.
    gate_stall: int = 0        # consecutive RED gates with the SAME finding (no progress); reset on change/GREEN
    gate_sig: str = ""         # the last RED finding, to detect an unchanged signature
    # EDITS BETWEEN THE COUNTED ROUNDS (#5b). The thrash trigger used to say the coder "kept editing" —
    # unmeasured: in run 01a12bca the last four RED rounds had no write between them. Every OBSERVED
    # write dispatch is kept (never flushed, unlike recent_writes; the same id may appear more than once);
    # the ones PROVEN not to have run are filtered out at use; each round in the streak stores the landed
    # count at that moment.
    write_call_ids: list = None
    call_counts: Counter = None        # exact multiplicity of EVERY dispatch by call id (writeobservation owns it)
    refused_write_ids: set = None
    stall_edit_marks: list = None
    # Is the write registry LIVE for this session — has a forwarded reply ever been recorded? That is all it
    # says: entries come from cria's own forwarded replies and from the canonical accepted history folded in
    # (`writeobservation`), and compaction cannot take one back out; it does NOT mean the whole conversation is
    # covered. Where it never ran, "no write is on record" would be an absence of bookkeeping, not of writes.
    write_tracking: bool = False
    # len(write_call_ids) when the last gate's verdict was read — the position "since that check" is
    # measured from (`gate_unedited`). None = cria cannot say.
    gate_write_mark: int | None = None
    # The registered write calls whose result was NOT yet known when that verdict was read. Each may
    # still finish after the verdict, so a forwarding position alone cannot say it landed before it.
    gate_pending_write_ids: set | None = None
    # Registered write calls whose result cria has seen, remembered across requests: the window drops old
    # results (harness compaction), and a result no longer in the window is still a result that came back.
    write_result_ids: set | None = None
    last_gate_testless: bool = False  # the last GREEN gate ran NO tests (0 collected / no test probe) — a
    last_gate_skipped: int = 0        # tool-reported SKIPPED count from the last gate's test run — a suite
    # can pass while SKIPPING the checks that matter (0728-m11: live tests skipTest() on the exact 404
    # that proves the resolver broken; "3 passed, 2 skipped" read as green). Same evidence posture:
    # VACUOUS green. Fed to the satisfaction judge as EVIDENCE (not a deterministic block): the judge
    # holds the task and decides whether tests were even part of the ask (a script task is legitimately
    # testless-green; deterministically blocking would wedge it AND push a weak model to fabricate tests).
    # Full three-valued build/source/test evidence from the same authoritative gate event.  Unlike
    # ``last_gate_testless``, an unsupported field can remain unknown all the way to the judge.
    last_gate_participation: object = None
    # Completion-gate-on-"done" state (plan-off path; the loop uses PlanSession's own fields):
    done_probe: bool = False  # a probe verifying a "done" claim is in flight
    pending_done: str = ""  # the coder's held "done" text, forwarded if the gate passes
    # (reason,) for a satisfaction-accepted 'done', held until the gate's result decides
    # which claim the note may open with. Empty when the held text is the coder's own words.
    pending_done_parts: tuple = ()
    # The plan-ON completion backstop's OWN probe id. Deliberately NOT ``done_probe``: the plan-ON
    # periodic satisfaction check also sets done_probe and nothing on the plan path consumes it, so
    # keying the backstop off done_probe read whatever stale result probe_call_id pointed at by the
    # time the plan emptied (audited 2026-08-04). The backstop reads ONLY the probe it issued.
    completion_probe_id: str = ""
    completion_gate_reds: int = 0  # RED results at the completion backstop (ledger visibility; no cap)
    # A completion-gate probe's RESULT has been read since the coder's last forwarded acting turn —
    # green, or couldn't-run after discovery had a surveyed view (the per-step fail-open posture,
    # unchanged); RED and a survey-only bootstrap clear it. The plan-ON
    # completion requires this: walked on ada-handles_ternary-bonsai_codex_poff_1785818931, a replan
    # returned [] with the coder mid-step-1, three LLM judges approved files that were never executed,
    # and the session exited 3/4 with ZERO gates run — pytest would have printed "5 failed". A session
    # must not end on judgment alone while cria never even ATTEMPTED the repo's checks.
    gate_fresh: bool = False
    # Consecutive check readings that came back UNKNOWN for the same stated reason (see repositorychecks._count_unknown).
    gate_unknown_streak: int = 0
    gate_unknown_sig: str = ""
    # A gate planned before the workspace survey can return only that survey.  Once it lands, probe
    # discovery has new facts and completion must wait for one newly planned gate.  Separate from
    # ``gate_fresh`` so an already-surveyed project with no applicable probe keeps the bounded
    # attempted-gate exit, and a harness with no shell keeps its existing no-gate exit.
    gate_replan_required: bool = False
    # N1: the harness holds this session's gate helper program (written by an earlier gate's launch),
    # so later gate calls name it instead of carrying it. Copied from the live plan after every page.
    gate_helpers_ready: bool = False
    leg0_nudged: bool = False  # the no-tools act-first nudge fired once this session
    # NB: there is deliberately NO search-escape state here. cria used to SUBSTITUTE a web_fetch for a
    # search-looping coder's own web_search (streak/volume counters, a convention URL, a domain-root
    # floor when the reasoner punted). Substituting the coder's action is the REDIRECTION class, and the
    # punt-floor was a deterministic fallback behind a reasoner call — both are what the doctrine forbids
    # (principles #1, #2, #4). The search gate still REFUSES a near-duplicate search and steers "read the
    # source you named" — a steer the coder can disregard, not an action taken for it.
    read_ledger_seen: set = None   # tool-call ids already folded into read_files (events apply once, in order)
    read_files: dict = None     # path -> (bytes, "N bytes, M lines"): DURABLE record of the WORKSPACE files the
    # coder has already read. The fetch ledger below survives compaction and this did not, so a
    # compacted coder kept its web history and lost every file it had opened — on
    # shipping-rates-rb x nemotron-elastic 1787432916 it had the gem's source read at call 0091, was
    # guessing gem names from memory by 0094, and collapsed at 0097 repeating "there is a gem called
    # `eu`… I'm not sure" twenty times, with that source on disk in its own workspace throughout.
    # Paths and sizes only — the contents stay where they are, and re-reading one is a single call.
    fetched_pages: dict = None  # url -> (status, routes): DURABLE fetch facts a steer cites after the
    # real result has been floored out of the window (else a steer can't counter a late spiral)
    refused_names: set = None  # coordinates/packages the coder's toolchain REFUSED (refusalledger):
    # DURABLE like fetched_pages, because compaction folds the refusal away and a seat then re-blesses
    # the pin the tools rejected (walked: cart-billing-go 1788241229 0095->0096)
    refusal_events: object = None  # authoritative RefusalLedger: raw spelling, ecosystem, source,
    # event order and exact-success supersession. ``refused_names`` remains its compatibility view.
    stalled_probe: stalledwork.PendingProbe | None = None
    stalled_steer: stalledwork.Steer | None = None
    stalled_delivered: stalledwork.Steer | None = None
    stalled_reply: tuple | None = None  # invocation-local offer/reply, never serialized
    same_checks_relooked: bool = False  # the ONE second look at unchanged findings has been spent
    #                                     (rearms whenever the findings move; see author_steer)


@dataclass
class SurveyBootstrap(GuardState):
    """One private gate round that surveys an unsurveyed workspace before planning."""


@dataclass
class PlanSession(GuardState):
    plan: Plan = field(kw_only=True)  # required; kw_only so it may follow GuardState's defaulted fields
    handoff_origin: _HandoffOrigin | None = None  # producer-owned, never decoded from client text
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
    # A living re-derivation that omitted named deliverables releases its rejected cursor and
    # resumes from the raw task.  Keep the coverage judge's exact typed findings across a restart;
    # this is evidence, not a replacement plan or an authored action.
    replan_uncovered: tuple[str, ...] = ()
    # The reset evidence must survive a restart until it has reached one raw-task coder body.
    # The tuple remains as the typed reason the reset owns cursor suppression; this bit is only the
    # one-shot delivery acknowledgement.
    replan_uncovered_pending: bool = False
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
    generation_errors: list[dict] = field(default_factory=list)
    # (path, sha1 of the block) of every pasted file the text-write judge has ruled on, and its answer —
    # a temperature-0 model re-pastes the same file every turn, and a settled question is not re-asked.
    text_write_judged: dict = field(default_factory=dict)
    pasted_block_other: bool = False   # the pasted-file judge ruled THIS reply's block `OTHER` (not a whole file)
    pasted_prepared: pastedfile.Prepared | None = None
    pasted_pending_nudge: pastedfile.Nudge | None = None
    pasted_delivered_nudge: pastedfile.Nudge | None = None
    pasted_delivery: pastedfile.Delivery | None = None
    pasted_deliveries: dict = field(default_factory=dict)
    pasted_settlements: dict = field(default_factory=dict)
    pasted_consumed: tuple | None = None
    pasted_state_view: object = field(default=None, repr=False)
    living_step_key: str = ''
    living_plan_id: str = ''
    living_task: str = ''
    living_sequence: int = 0
    living_pending: object = None
    living_effects: object = None
    living_raw_reply: dict | None = None
    living_state_view: object = field(default=None, repr=False)
    # (path, sha1 of the content) of every native whole-file write_file that REPLACES most of a file the
    # judge ruled WHOLE_FILE for (`Loop.shrinking_write_check`). Only that positive ruling is remembered.
    shrink_write_judged: dict = field(default_factory=dict)
    # {workspace-relative path: (size, mtime)} of the FIRST complete survey this session received — the
    # baseline a later "unchanged on disk" fact is measured against. None until one lands.
    survey_baseline: dict = None
    # {rel} the FIRST survey listed (folded/incomplete included), minus files the coder's own landed write
    # created before it rode back — what `shrinking_write_check` treats as pre-existing. None until one lands.
    first_survey_files: set = None
    thrash_replanned: bool = False  # the tool-call-thrash re-derive fired once this STEP (anti-churn bound)
    verify_replanned: bool = False  # the verify-fail re-derive fired once this STEP (anti-churn bound)
    leg0_nudged: bool = False  # the no-tools nudge fired once this step (bounds in-process recursion)
    last_gate_flag: str = ""  # previous gate's block-nudge, for convergence/stall detection
    # WHEN that finding-set was gathered, as the forwarded-call counter's value. The block cria
    # renders from `last_gate_flag` is headed "the repo's own checks, MOST RECENT RUN", which is
    # true and reads as CURRENT — and it persists until another gate runs. L5 feed-pipeline-java x
    # ternary-bonsai: a gate found a compile error at 10 minutes; the coder's own `mvn clean
    # compile` returned BUILD SUCCESS at 17.4 minutes; the periodic gate that would have refreshed
    # the finding was cancelled by a compaction (`ran:false, why:history-rewritten`); and the stale
    # block went on asserting the error in 24 of the run's 42 prompts. The coder believed cria over
    # its own compiler, rewrote the file, and re-broke a build that had been green for nine minutes.
    # cria cannot know whether a newer command contradicts a finding — but it does know how old the
    # finding is, and saying so is the difference between a fact and an implication (#5b, #12).
    last_gate_seq: int = 0
    # The coder's OWN runs of a command the last gate also ran, as ``(action_seq, [commands], exit code
    # or None)``, newest last — durable, because the result that proves them is compacted away long
    # before the carried check block is. A block that says "the build fails" is stale the moment the
    # coder's own build says otherwise (phi4 A4 CALLs 0092/0104/0230: a pre-fix failure carried through
    # three compactions after later runs had shown different errors, then success). See `newer_own_run`.
    own_check_runs: list = None
    own_check_seen: set = None
    # Did the last completion gate actually RUN? `guard_gate_verdict` returns None for BOTH a green
    # gate and a gate that could not run, so its callers could not tell them apart and two of the
    # three hardcoded "The repo's automated checks pass". Measured: that wording shipped 80 times,
    # twice in a prompt whose newest check block showed failing tests, while the honest `never_ran`
    # wording the prompt file already carries fired zero times.
    last_gate_ran: bool = False
    # The highest PASSING test count each test COMMAND has reported this session, keyed by command.
    # Regression-only (#2): it exists so cria can state, as a fact from the runner's own tally (#12),
    # that the suite used to pass more tests than it does now. Per command and never summed — see
    # `probegate.gate_passing_by_command` for the run a total cost.
    tests_passed_high: dict = field(default_factory=dict)
    # The (command, was, now) of the last regression stated, for the log line. None until one fires.
    last_regression: tuple | None = None
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
# The live plan sessions kept server-side. Same bound as the shapes, for the same reason and with
# the same eviction: a cria process sees at most a handful of sessions before it restarts (measured
# over 325 process lifetimes: max 4), so this is a backstop against unbounded growth, not a working
# limit. Without it the store reached 494 sessions and 1 MB, re-serialised on every single turn.
_MAX_SESSIONS = 256
# The gate normally fires only on a "done" claim or a guard trip, so an acting-heavy model can edit
# for a long stretch with NO ground truth (it circled on a broken pyproject.toml for ~90 turns). Run
# the checks every N acting coder turns too and INSERT the result (no verdict) so the model sees the
# syntax/lint/test state early, not only when it thinks it's finished.
GATE_EVERY_CODER_TURNS = repositorychecks.GATE_EVERY_CODER_TURNS

# On a plan-ON completion (all steps verified individually), run the WHOLE-TASK satisfaction critic
# before declaring done — a multi-step plan can pass every step yet not actually work (the milestone
# run: each step green, but the resolver 404'd on the wrong endpoint and nothing checked end-to-end).
# When it says not-done, re-open with ONE corrective step and re-drive. Bounded so a task the coder
# genuinely can't finish still completes rather than looping forever (the plan-off path relies on the
# harness stopping; cria DRIVES the plan loop, so it must bound the retries itself).
MAX_COMPLETION_CHECKS = repositorychecks.MAX_COMPLETION_CHECKS
_COMPLETION_FIX_PREFIX = "The task is not yet fully satisfied — fix this before finishing: "

# Periodic SATISFACTION check (plan-off): a long session can finish the work but never STOP — the coder
# keeps inventing completion actions (a .task_complete marker, a hallucinated checkpoint tool) so cria's
# no-tool-call done-detection never triggers. Starting at drive `start`, every `every` drives, the
# reasoner judges the WHOLE user task against the real work; if satisfied cria verifies against the
# repo's checks (the same objective backstop the done-gate uses) and ends the turn. The cadence is
# operator-tunable ([context] satisfaction_check_start / satisfaction_check_every) — different models
# spiral at different rates; either set to 0 DISABLES it.


# HOW LONG A RED GATE MAY HOLD THE WHOLE-TASK QUESTION BACK. Two gates with the same finding-set is
# already the signal `gate_stall` exists to carry; a third says the red is not moving and is therefore
# not evidence that the coder is mid-fix.
RED_HOLDS_SATISFACTION_FOR = 2


def _satisfaction_blocker(*, steer, rewritten: bool, done_probe: bool, gate_red: bool,
                          gate_stall: int = 0) -> str:
    """WHICH condition is holding the satisfaction check back this turn — "" when none is.

    Returns a name rather than a bool so the skip event can say why (#12). The order is reporting
    order only; any one of them is enough to skip, and the first named is the one recorded.

    `gate_red` is the one that LATCHES, and that is what made this worth naming. It is set by
    `record_gate_state` when a gate RAN and found problems, and only a later gate that runs and comes
    back genuinely clean clears it — a gate that could not run leaves it exactly as it was. So a
    session whose checks are red early stays blocked until a clean gate happens to land, and on
    rust-toml-cli x ternary-bonsai (2026-08-19) none ever did: 34 due drives, all skipped, while the
    workspace sat at three of four deliverables with a README that was never written.

    A RED THAT IS NOT MOVING IS NOT A REASON TO WAIT. The block reads "checks are failing, so there
    is obvious work — do not ask the whole-task question yet", and that is true while the coder is
    closing on the red. It is false when the same finding-set comes back gate after gate, and it is
    false from turn one on a whole class of tasks: "fix the failing repository tests" starts red BY
    CONSTRUCTION, so the latch closes on the first gate and never opens.

    Measured on shipping-rates-rb x nemotron-elastic 1787344941: 76 skips, 68 of them `gate-red`,
    `last_ran` stuck at -1 for the entire session. The one mechanism that asks "have you started
    items 2 to 5 yet?" never ran, and express pricing and the README were never begun in 31 minutes.
    `gate_stall` already counts consecutive gates with the SAME finding-set — the fact is in hand, so
    the hold ends when the red stops moving (#12)."""
    if steer:
        return "steer"
    if rewritten:
        return "history-rewritten"
    if done_probe:
        return "done-probe-in-flight"
    if gate_red and gate_stall < RED_HOLDS_SATISFACTION_FOR:
        return "gate-red"
    return ""


def _satisfaction_blocks_completion(sess, *, bounded: bool = False) -> bool:
    """Whether the newest satisfaction evidence bars a completion-shaped response."""
    if getattr(sess, "latest_satisfaction", None) is not False:
        return False
    return not (bounded and getattr(sess, "completion_checks", 0) >= MAX_COMPLETION_CHECKS)


def periodic_check_due(drive_count: int, start: int, every: int, last_ran: int = -1) -> bool:
    """Is a periodic check due? Measured from when it last RAN, never from an absolute modulo.

    `(drive_count - start) % every == 0` made exactly one drive in `every` an opportunity, and the
    caller skips the check on any drive where something else is already steering — a pending steer,
    a harness compaction, an in-flight done-probe, a red gate. Land on a blocked drive and the next
    chance is a whole interval away.

    Measured on rust-toml-cli x ternary-bonsai, 2026-08-17: 54 drives, cadence 17/8, so five
    opportunities — 17, 25, 33, 41, 49. **One fired. Four were eaten by `blocked`.** That run carried
    20 harness compactions and 36 gate runs, so a blocker on any given drive is likely rather than
    rare, and the check the whole off-ramp rests on ran once in 86 calls.

    Since-last-ran retries on the very NEXT unblocked drive instead. It cannot fire more often than
    `every` drives, because the stamp moves only when the check actually runs — so this closes the
    gap without buying a single extra call in the unblocked case.

    THE PERIODIC STEP CHECK HAD THE SAME DEFECT AND NOW SHARES THIS PREDICATE. It triggered on
    `coder_turns % STEP_CHECK_EVERY` — and `coder_turns` is the GATE's countdown, zeroed by
    `guard_periodic_gate` every 15 acting turns. 12 is therefore the only multiple of 12 that counter
    can ever hold, and the once-per-tick memo beside it (`step_checked_turn == coder_turns`) then
    refused every later arrival at 12 for the life of the session.

    READ OFF THE LOGS, 2026-08-18, 177 sessions: **21 `loop.periodic_step_check` events, every one of
    them at `turns=12`, at most one per session.** Not one at 24, 36 or 48. The clearest case is
    01a006c7 — 89 coder calls and 3 completed gate cycles on the step-checked path, and exactly one
    step check. The method's own comment costed itself at "one judge call per twelve turns"; it was
    delivering one per session. One shape, two mechanisms, one predicate now."""
    if start <= 0 or every <= 0:  # disabled
        return False
    if last_ran < 0:
        return drive_count >= start          # the first one is still keyed to `start`
    return drive_count - last_ran >= every


# THRASH-ASSIST threshold (plan-off). When the SAME check error has persisted this many gate cycles (the
# coder is STUCK on one thing, not just churning), replace the raw ground-truth insertion with a REASONED
# thrash-diagnosis + one concrete next step to get the coder UNSTUCK. cria NEVER gives up on a
# non-converging session (the stall terminator + human-escalation were removed — the mission is for the
# model to succeed on its OWN); it just keeps trying to unstick it.
THRASH_STALL_CYCLES = stalledwork.STALL_ROUNDS

# STUCK-STEP re-plan threshold. A step advances ONLY on a genuine pass — there is deliberately no
# advance-on-unverified cap (real failing checks must be fixed, never skipped). But a MISCONCEIVED step
# — a category-error or confused step the weak planner wrote whose CHECKS pass yet whose critic keeps
# judging its INTENT unmet — can never be satisfied, so the coder re-nudges forever (observed live: a
# "extract the JSON schema to obtain field VALUES" step looped 16 min). After this many consecutive
# CRITIC verify-fails on one step (NOT gate/real-error fails), hand the living-plan reasoner the real
# work done so it can RE-DERIVE that step from ground truth (or confirm the work already satisfies it).
# Re-attempted every STUCK_STEP_REPLAN fails so a declining reasoner doesn't burn a call each turn.
STUCK_STEP_REPLAN = livingplan.STUCK_STEP_REPLAN

# STUCK-STEP re-plan threshold for a TOOL-CALL thrash. The above triggers on CRITIC verify-fails, but a
# coder can loop on tool calls for a whole step (write→exec→write…, ignoring the guards' steers) WITHOUT
# ever signalling completion — so verify never runs and that escape never accrues (observed live: 30+
# acting turns on a "create the package directory" step that write_file-vs-mkdir-conflicted, 39 steers
# ignored). After this many ACTING turns on one step without advancing, re-derive the step from ground
# truth too (it may simplify an over-engineered step — e.g. a package scaffold → a flat script). Fired
# periodically (every N turns) so a productive-but-long step that yields an unchanged plan isn't churned.
STEP_THRASH_REPLAN = livingplan.STEP_THRASH_REPLAN


def _note_write_results(gs: GuardState, messages) -> None:
    """Remember which registered write calls have had a result come back (landed or failed). A result counts only
    through the ONE call/result correlation owner (`denial.paired_results`): an orphan, a result that precedes its
    call, a second result or a reused id answers nothing. The raw set is sticky; whether an id still counts is
    decided at use (`writeobservation.answered_ids`)."""
    answered = gs.write_result_ids = getattr(gs, "write_result_ids", None) or set()
    registered = set(getattr(gs, "write_call_ids", None) or [])
    answered |= registered & set(denial.paired_results(messages or []))


def track_gate_progress(gs: GuardState, finding: str, messages=None) -> None:
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
    reaches (#23: one owner).

    ``messages`` is the request history AT MARK TIME: the authoritative results of every write sent
    before this round are in it, so the edits-between-rounds fact is settled from them here (a
    running count taken before a refusal/failed edit was recorded read an edit that never landed as
    one that did)."""
    # Reconcile and settle FIRST: the gate position and the pending set are snapshots of what the registry
    # holds, so anything the history in hand reveals (a collision, a result) must already be in it.
    mark = _register_writes_at_round(gs, messages)
    gs.last_gate_flag = finding or ""
    gs.last_gate_seq = gs.action_seq
    gs.gate_write_mark = len(gs.write_call_ids or []) if gs.write_tracking else None
    # Completion-aware: only a write whose result was already in hand (landed OR failed) AND is attributable to a
    # single dispatch is "before the gate". One with no result yet, or an ambiguous id, may land after it, so it
    # is remembered as outstanding.
    answered = writeobservation.answered_ids(gs, gs.write_result_ids)
    gs.gate_pending_write_ids = (
        {c for c in (gs.write_call_ids or [])[:gs.gate_write_mark] if c not in answered}
        if gs.gate_write_mark is not None else None)
    if not finding:
        gs.gate_stall = 0
        gs.gate_sig = ""
        gs.stall_edit_marks = []
        return
    if finding == gs.gate_sig:
        gs.gate_stall += 1
        gs.stall_edit_marks = list(gs.stall_edit_marks or []) + [mark]
    else:
        gs.gate_stall = 1
        gs.gate_sig = finding
        gs.stall_edit_marks = [mark]


def _is_write_call(tc: dict) -> bool:
    return _write_path(tc.get("function") or {}) is not None


def _observe_history(gs, messages) -> int:
    """Fold the accepted incoming history into the registry (`writeobservation.observe_history`) and return the
    registry length. The one call every history-facing entry point makes: the accepted request before any assist or
    recovery is selected, the gate registrar, and — inside `record` — the history that precedes a forwarded reply."""
    messages = messages or []
    writeobservation.observe_history(writeobservation.HistoryInput(
        messages, frozenset(_unlanded_call_ids(messages)), gs, _note_write_results, _is_write_call))
    return len(gs.write_call_ids)


def _register_writes_at_round(gs: GuardState, messages) -> int:
    """Bring the write registry up to what the history in hand shows and return its length — this round's position.
    The edits that landed between two rounds are the registry entries between their positions that are not
    refused/failed (:func:`thrash_edits_clause`)."""
    return _observe_history(gs, messages)


def thrash_edits_clause(gs: GuardState) -> str:
    """The measured edit count across the RED rounds the stall counted — the clause the thrash trigger
    states instead of claiming the coder "kept editing". Each round's mark is a position in the write
    registry, so the edits BETWEEN two rounds are the entries between their marks that were not
    refused or failed, judged by the freshest refused set."""
    marks = list(getattr(gs, "stall_edit_marks", None) or [])
    fills = prompts.load_map("thrash_edits")
    if len(marks) < 2:
        return fills["thrash_edits_unknown"]
    refused = writeobservation.unlanded_ids(gs)
    ids = getattr(gs, "write_call_ids", None) or []
    per = [sum(1 for cid in ids[a:b] if cid not in refused) for a, b in zip(marks, marks[1:])]
    n = sum(per)
    if n <= 0:
        return fills["thrash_edits_none"]
    idle = 0
    while idle < len(per) and per[-1 - idle] == 0:
        idle += 1
    clause = prompts.fill(fills["thrash_edits_some"], n=n, edits="edit" if n == 1 else "edits")
    if idle:
        clause += prompts.fill(fills["thrash_edits_idle"], k=idle + 1)
    return clause


def _critic_verdict(system: str, user: str, reasoner_chat, reasoner_role, rlog, *,
                    reasoning_off: bool, workspace_root: str = "", verdict_key: str = "",
                    evidence_blocks: list[str] | None = None) -> tuple[dict | None, str]:
    """F37: shared critic answer reading; recovery can only say keep working.

    Empty ``verdict_key`` preserves the step critic's existing wire declaration;
    its recovery key is ``done``. Whole-task judging explicitly declares
    ``satisfied`` even on a toolless retry, so forced closure never asks the wrong
    question. Inspection and lossless evidence remain owned by _judge_completion
    (F33/F71); this function neither clips input nor adds a judge call on success.
    """
    satisfaction = verdict_key == "satisfied"
    key = verdict_key or "done"
    phase = ("satisfaction" if satisfaction else "critic") + ("-noreason" if reasoning_off else "")
    event = "satisfaction" if satisfaction else "verify"
    role = reasoner_role
    if reasoning_off:
        role = replace(role, reasoning="off") if role is not None else None
        system += "\n\n" + prompts.load("judge_toolless_note")
    try:
        comp = _judge_completion(
            reasoner_chat, role, system, user, rlog, phase=phase,
            workspace_root=workspace_root, allow_inspection=not reasoning_off,
            verdict_key=verdict_key, seed_files=True, evidence_blocks=evidence_blocks,
            evidence_intro=None, force_think_off=reasoning_off)
        vtext = _completion_text(comp)
        if role is not None:
            # Use the effective call role, not the original reasoning-ON role.
            # An unopened pre-</think> JSON object is deliberation, not the answer.
            vtext = role.clean_content(vtext)
        if massage.is_truncated(comp):
            # Even a balanced object in a cut reply cannot authorize completion.
            fields = {} if satisfaction else {"chars": len(vtext)}
            rlog.emit(f"loop.{event}_truncated", level="warn", **fields)
            return None, vtext
        obj = extract_json_object(vtext)
        if obj is not None:
            return obj, vtext
        if satisfaction and (bogus := leaked_judge_tool(vtext)):
            rlog.emit("loop.judge_phantom_tool", level="warn", phase=phase, tool=bogus)
        # Preserve the judge's own negative object first, then ask the existing
        # focused negative-only reader about recorded reasoning or answer prose.
        # Never recover an approval, and never second-guess a readable verdict.
        recover = ((lambda sysm: ask_closed(reasoner_chat, reasoner_role, sysm, rlog,
                                            phase=phase + "-recover"))
                   if reasoner_role is not None else None)
        obj = (verdict_from_unclosed(vtext, key, rlog, phase)
               or verdict_from_reasoning(_reasoning_of(comp), key, rlog, phase, recover)
               or verdict_from_reasoning(vtext, key, rlog, phase + "-prose", recover))
        return obj, vtext
    except Exception as e:
        rlog.emit(f"loop.{event}_error", level="warn", error=str(e))
        return None, ""


def _satisfaction_verdict(system: str, user: str, reasoner_chat, reasoner_role, rlog, *, reasoning_off: bool, workspace_root: str = "",
                          evidence_blocks: list[str] | None = None) -> dict | None:
    """Whole-task critic adapter: the shared F37 pipeline, with the satisfied key."""
    obj, _ = _critic_verdict(system, user, reasoner_chat, reasoner_role, rlog,
                            reasoning_off=reasoning_off, workspace_root=workspace_root,
                            verdict_key="satisfied", evidence_blocks=evidence_blocks)
    return obj


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
    if assistruntime.current().rehunt is None:
        return False
    return semanticquery.Judge(summarize, reasoner_chat, reasoner_role, rlog).rehunt(
        semanticquery.QuestionFacts(task, coder_tools), query, prior)


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
    return re.findall(r"\b([a-z_][a-z0-9_]{2,})\b(?=\s*[(:—-]|\s*$)", coder_tools or "", re.M) \
        or re.findall(r"\b([a-z_][a-z0-9_]{2,})\b", coder_tools or "")


def reassess_remaining(reasoner_chat, reasoner_role, task: str, completed: str, remaining: str,
                       evidence: str, rlog, coder_tools: str = "",
                       trigger: str = REPLAN_TRIGGER_ADVANCE, facts: str = "",
                       uncovered: list[str] | None = None, *,
                       policies: planner.PlanningSelection | None = None) -> list[str] | None:
    """Dedicated reasoner call for the LIVING plan: re-derive the REMAINING plan steps from the work
    ACTUALLY done (real tool evidence), so the plan adjusts to reality at each verification instead of
    marching a stale guess. Returns the refined remaining step-text list (may be shorter/reworded/
    reordered, or [] when the evidence shows nothing is left), or ``None`` to leave the plan UNCHANGED —
    the fail-safe on a parse miss / decline / no reasoner, because silently blowing away a plan on a bad
    parse is far worse than carrying a stale step (the step critic still guards every step)."""
    def question(system, user, **kwargs):
        return summarize(reasoner_chat, reasoner_role, system, user, rlog,
                         phase='reasoner', **kwargs)

    return livingplan.reassess_compatibility(
        question=None if reasoner_role is None else question,
        task=task, completed=completed, remaining=remaining, evidence=evidence, log=rlog,
        coder_tools=coder_tools, trigger=trigger, research=facts,
        tool_names=tuple(_tool_names(coder_tools)),
        coverage=missing_deliverables if policies is None else policies.coverage,
        uncovered=uncovered)


# HOW MANY TIMES THE JUDGE ACTUALLY LOOKED, carried on the completion it produced.
#
# A seat whose whole justification is "a judge that must look cannot rubber-stamp a narrative" has to
# be able to tell whether it looked, and the number of inspection rounds is the authoritative event
# for that (#12) — not a guess from the wording of the reply. `_confirm_completion` is the caller
# that needs it; see the note there for the run where a brake confirmed a broken CLI in fifteen
# tokens without opening a single file.
ROUNDS_KEY = "_cria_inspection_rounds"


def _with_rounds(comp: dict, rounds: int) -> dict:
    return {**comp, ROUNDS_KEY: int(rounds)} if isinstance(comp, dict) else comp


def inspection_rounds(comp: dict) -> int:
    """How many rounds of list_dir/read_file this judge spent before answering."""
    return int((comp or {}).get(ROUNDS_KEY) or 0) if isinstance(comp, dict) else 0


def _judge_completion(chat_fn, role, system: str, user: str, rlog, *, phase: str,
                      workspace_root: str = "", max_tokens: int = 8192,
                      force_think_off: bool = False, transcript: list | None = None,
                      answer_now: str | None = None, answer_now_simple: str | None = None,
                      verdict_key: str = "",
                      verdict_schema: str = "",
                      seed_files: bool = False,
                      allow_inspection: bool = True,
                      evidence_blocks: list[str] | None = None,
                      evidence_intro: str | None = "composed_evidence_intro") -> dict:
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
    # A path does not grant inspection reach. Keep this conditional on the ACTUAL menu,
    # including toolless retries/forced rounds and any later floor reduction: no positive
    # availability promise is made here that would need a second wire settlement.
    if workspace_root or verdict_key:  # an inspection/verdict seat; plain authors keep their contract
        system = system + "\n\n" + prompts.load("judge_capability")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if evidence_blocks:
        # Match summarize's composed-call contract: historical evidence is reducible by the
        # ONE context floor; current facts and the active question stay in the final turn.
        # ``evidence_intro`` is a prompt key, or None when the final question already says where the
        # evidence is: with a pinned question the leading intro is NOT protected (the question is), so a
        # separate intro would be the oldest turn and the first the floor sheds.
        messages[1:1] = [
            *([selfcompact.internal_evidence_message(prompts.load(evidence_intro))] if evidence_intro else []),
            *(selfcompact.internal_evidence_message(block) for block in evidence_blocks),
        ]
    workspace_known = bool(workspace_root) and wsview.current(workspace_root).surveyed
    inspectable = workspace_known and allow_inspection
    # HAND IT THE FILES RATHER THAN MAKE IT ASK. The loop below is the judge naming one file, cria
    # reading it, and the whole conversation being re-sent — 1,511 rounds across the captures, 87% of
    # them fetching exactly one file, at a cost that grows with every round (47K -> 62K -> 83K ->
    # 102K chars on one measured steer, its last call alone 247 seconds). Gathering facts is
    # deterministic code's job; judging them is the reasoner's (#8). The tools stay: every readable
    # text file the harness has delivered is carried whole; unavailable bodies are named as unknown.
    # OPT-IN, and the steer author deliberately does not opt in. `6726b8a` removed inlined contents
    # from THAT seat after a 57K curl'd spec went in twice under two path spellings — 115K of a 210K
    # prompt, in a composed two-message call the context floor has no turns to drop from, and the
    # reasoner died four times. Its answer was a LIST plus tools, and it measured out at 210K -> 89K
    # chars with zero dead calls. That decision stands where it was made. Judges are different: the
    # context floor is their only window-fit point, so this site does not preselect or clip files.
    if workspace_known and seed_files:
        seeded = groundtruth.files_for_a_judge(workspace_root)
        if seeded:
            # BEFORE the question, not after it. The files are context; the thing being asked has to
            # be the last thing read. (It also keeps `messages[-1]` the prompt every caller and test
            # reasonably expects it to be.)
            # Just before the question, AFTER any composed history: the floor sheds oldest first, and the
            # current on-disk files must outlast the older record, not be the first thing it removes.
            messages.insert(len(messages) - 1, selfcompact.internal_evidence_message(seeded))
            rlog.emit("loop.judge_files_seeded", phase=phase, chars=len(seeded))
    inspection_start = len(messages) if evidence_blocks else 2
    rounds = 0
    forced_rounds = 0
    while True:
        body: dict = {"stream": False, "temperature": 0, "max_tokens": max_tokens,
                      "messages": list(messages)}
        if evidence_blocks:
            # A forced-answer user turn follows the original question when inspection closes.
            # Preserve that question/fact packet through the existing wire-owned task pin,
            # rather than letting the new last-user turn make it historical and droppable.
            body[bodykeys.PINNED_TASK] = user
        # THE CHARACTER BUDGET IS GONE (operator, 2026-08-19: "get rid of the judge budget, let it go
        # free"). It bounded how much a judge could pull in, and when it tripped cria withdrew the
        # tools mid-look and then DISCARDED whatever the judge said next. Walked on
        # feed-pipeline-java x qwen35, call 0304: the judge had already run `list_dir`, seen there
        # was no REVIEW.md, and reported exactly that — "REVIEW.md does not exist in the workspace
        # (confirmed via list_dir)". cria threw the sentence away and sent the coder the generic
        # "this step is not yet verified" instead. REVIEW.md was never written in 319 calls.
        #
        # The round budget still bounds the loop, so a judge cannot look forever, and the context
        # floor is the one place window-fitting happens (#5). What is removed is the second, blunter
        # bound that made a judge answer before it had finished looking.
        if inspectable and rounds < verifytools.VERIFY_MAX_ROUNDS and not forced_rounds:
            # …AND A WAY TO ANSWER IN THE SAME CHANNEL. Offered tools on one channel and made to
            # answer on another, judges answered where they had been speaking: `<function=satisfied>`,
            # `<function=exec_command>`. cria discarded those and "unverified — keep working" reached
            # a finished workspace (qwen35/ruby 0138 and 9 more). Opt-in by key: the steer author
            # shares this loop and answers in prose.
            body["tools"] = verifytools.tools_for(verdict_key, verdict_schema)   # withdrawn on the forced-answer round
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
        if not (inspectable and calls and rounds < verifytools.VERIFY_MAX_ROUNDS):
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
                            else (answer_now or verifytools.answer_now(verdict_key)))
                # WHY IT STOPPED, and it was not because the reader had seen enough: the reader
                # just asked to look at something and cria did not run it. Only on the FIRST forced
                # round — round 2 exists because round 1 came back unreadable, and its whole design
                # is the shortest ask that resembles nothing the model can call (measured 10/10
                # against 0/10 for a longer one); prefixing prose to it would undo that.
                if forced_rounds == 1:
                    ask_text = verifytools.closing_reason("inspection_closed") + " " + ask_text
                if forced_rounds == 2:
                    rlog.emit("loop.verdict_simplified", phase=phase)
                messages.append({"role": "user", "content": ask_text})
                continue
            if transcript is not None:  # the caller wants the inspection record (e.g. for grounding)
                transcript.extend(messages[inspection_start:])
            return _with_rounds(comp, rounds)
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
                    transcript.extend(messages[inspection_start:])
                return _with_rounds(_completion_of(comp, json.dumps(obj)), rounds)
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
        if rounds == verifytools.VERIFY_MAX_ROUNDS:
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
                             "content": verifytools.closing_reason("rounds_spent", rounds) + " "
                                        + (answer_now_simple or answer_now
                                           or verifytools.answer_now(verdict_key))})


def _consistent_word(text: str) -> bool | None:
    """The confirm judge's one-word verdict, or None when it did not give one.

    Both shapes are read, always: the ask is now a WORD (a JSON demand after five rounds of the
    judge's own tool calls gets another tool call — measured 0/10 vs 10/10 on gemma4), but a model
    that answers with the JSON object anyway is still understood. ternary-bonsai answers every shape
    6/6, so no model can be made worse by the change — the only movement is a model that answered
    NOTHING now answering."""
    # The declared protocol is one word on the first line, with an optional
    # explanation on the next. Preserve Markdown/quote formatting, not prefixes
    # such as CONSISTENTLY or CONSISTENT_UNKNOWN masquerading as that word.
    lines = (text or "").strip().splitlines()
    head = lines[0].strip("*#`\"' ").upper() if lines else ""
    if head == "INCONSISTENT":
        return False
    if head == "CONSISTENT":
        return True
    return None


def _ground_coder_view(messages: list, workspace_root: str) -> list:
    """Return ``messages`` with a single FRESH workspace listing riding at the TAIL — the coder's
    on-disk ground truth in the most-salient slot (the last thing before the model generates),
    re-derived from live disk every coder turn. LISTING ONLY: names + sizes, never file content — a
    blind touch's content grounding is editrecovery's job, and carrying bytes forward is the churn
    ddd74fd removed. Any prior ⟦ctx:files⟧ listing (last turn's footer, a stale compaction copy) is
    folded out first, so exactly ONE authoritative copy remains — the same one-copy rule selfcompact
    already applies to the compacted view (reuses its `_is_files_msg`). Re-derived per turn and never
    written to durable history, so it cannot go stale the way the reverted briefing arm did (a88e905).
    No-op without a workspace root or when the survey is empty/unavailable (`workspace_inventory`
    returns "").

    Placed in `_coder_turn`, the one shared coder core, so BOTH driver halves get it. The listing is
    the focus-free half of ground truth: it asserts what EXISTS, never which file matters, so it can
    ride every turn without steering the model at a file it has rightly moved off (that judgement
    belongs to the model's own next action, which editrecovery grounds).
    """
    inv = workspace_inventory(workspace_root or "", flavor="coder",
                              compacted=selfcompact.body_is_compacted(messages))
    if not inv.strip():
        return messages
    kept = [m for m in messages if not selfcompact._is_files_msg(m)]
    footer = {"role": "user", "content": inv}
    if not kept:
        return [footer]
    # The LAST slot belongs to the current ACTION (a fresh steer/redirect, the task, a tool result) —
    # state must not bury it (action-framed beats rule-framed for a weak model). So the listing rides
    # just ABOVE the last message. The one exception is a trailing tool RESULT: a user message may not
    # be inserted between an assistant tool_call and its result (that orphans the tool at the wire),
    # and a tool result is state not an action, so the listing is appended AFTER it instead.
    if kept[-1].get("role") == "tool":
        return kept + [footer]
    return kept[:-1] + [footer, kept[-1]]


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
    return completionconfirmation.absent_artifact(claim, workspace_root, _confirmation_facts())


def _confirm_applies(claim: str, red_findings: str = "", *, gate_red: bool = False, ask=None,
                     rlog=None, phase: str = "critic-confirm") -> bool:
    """Should the per-STEP confirm brake run on this approved claim at all?

    A red repo check — this call's findings or the session's standing red state — grounds the
    brake whatever the step says. Otherwise, ONE focused reasoner question judges whether carrying
    out the step produces or changes an artifact. A path token cannot settle that: it can be an
    existing input to a read/investigation step as well as a promised output. Every failure
    direction keeps the brake: no reasoner, or an unreadable answer → it runs.

    Scoped to the per-step confirm on purpose. The whole-TASK satisfaction confirm keeps its brake
    unconditionally: a task names its deliverables as NOUNS ("script plus README"), and the brake's
    measured wins there (satisfied with no README on disk) are exactly that shape."""
    if (red_findings or "").strip() or gate_red:
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


# A FILE PATH or a VERSION in a directive — the two classes of invention the walks caught. Both are
# checkable against the text the directive was written FROM, which is what makes them worth checking:
# cria cannot judge whether a paraphrase is faithful, and can always tell whether a name was there.
# THE PATH ARM SWALLOWED A SENTENCE'S FULL STOP AND MATCHED ENGLISH. `lib/shipping/rates.rb.` read
# as invented while the path itself was right there in the source; so did `target/.`. And a slash
# between two words is prose, not a path: `I/O`, `trim/normalise`, `problems/risks`,
# `blank/non-numeric`, `SKU/quantity/price.`. Thirteen of the thirty-two invented-name refusals on
# the re-orientation seat — 41% — were solely one of those two artifacts, each one discarding a whole
# model call and replacing its answer with the canned text.
#
# So a path segment may not END on a separator or a dot, and a bare word/word with no dot and no
# further separator is not a path.
_GROUNDABLE_NAME = reorientation._GROUNDABLE_NAME

# A SLASH BETWEEN WORDS WITH NO DOT ANYWHERE IS PROSE, NOT A PATH. `I/O`, `trim/normalise`,
# `problems/risks`, `blank/non-numeric`, `SKU/quantity/price` — cria cannot tell those from a real
# dotless directory path like `test/fixtures`, and the measured cost of guessing is 41% of this
# seat's refusals thrown away with a whole model call behind each. Abstaining is the safe direction:
# the guard exists to catch an INVENTED FILE, and a file has an extension (#3 — silence over noise).
_PROSE_PAIRING = reorientation._PROSE_PAIRING


def _invented_names(text: str, source: str) -> list[str]:
    """Names in ``text`` that do not appear in ``source`` — a directive's inventions, in order.

    Case-insensitive substring, so a directive may shorten `lib/shipping/rates.rb` to `rates.rb`
    (still grounded) but not lengthen `rates.rb` into `lib/shipping.rb` (not grounded)."""
    return reorientation.invented_names(text, source)


def _workspace_basename_matches(root: str, name: str) -> list[str] | None:
    """Workspace-relative paths whose basename is ``name`` — ``None`` when cria cannot say.

    A judge writes file names in prose, and `groundtruth.resolve` is `os.path.join`, so `feed.csv`
    became `<root>/feed.csv` while the file sat in `data/`. An empty list here means the walk
    covered the tree and the name is genuinely absent; `None` means it did not, and no claim about
    absence may be made from it (#5b, #11b)."""
    if not root or not name:
        return None
    view = wsview.current(root)
    walked = view.walk(root, skip_names=(".git",), skip_hidden=True)
    # …AND NOTHING FOLDED. A folded directory is one the survey listed only as a count, so its files
    # are absent from the walk while `complete` stays True — the sibling in `groundtruth` checks both
    # and says why. Measured against a real 1,169-file run workspace: `complete` True, 7 folded
    # directories, 503 of 1,169 files known. An absence diagnosis is suppressed until this walk is
    # complete; a partial inventory is never converted into "not present".
    if walked is None or not view.listed_everything(root):
        return None
    want = os.path.basename(name)
    return [os.path.relpath(os.path.join(d, n), root)
            for d, _subs, names in walked for n in names if n == want]


def _workspace_subject(root: str, subject: str) -> tuple[str, bool | None, str | None]:
    """Resolve one typed diagnosis subject through wsview.

    Returns ``(workspace-relative path, is_file, complete_body)``. A bare basename may resolve to
    one unique file anywhere in a completely listed workspace. Ambiguous, incomplete,
    outside-workspace and unreadable states remain unknown; they are never absence.
    """
    if not root or not subject:
        return "", None, None
    view = wsview.current(root)
    path = groundtruth.resolve(root, subject)
    # Use the production path algebra even under DirectView tests; DirectView deliberately treats
    # paths literally and therefore does not root a relative subject for us.
    rel = wsview.View(root).rel(path)
    if rel is None:
        return "", None, None
    present = view.isfile(path)
    if present is False and os.path.basename(subject) == subject:
        hits = _workspace_basename_matches(root, subject)
        if hits is None or len(hits) > 1:
            return "", None, None
        if hits:
            rel, path, present = hits[0], groundtruth.resolve(root, hits[0]), True
    body = view.read(path) if present is True else None
    return rel, present, body


_subject_is_exact_in_quote = completiondiagnosis.subject_is_exact_in_quote


def _negative_diagnosis_nudge(obj: dict, *, task: str, action_log: str = "", checks: str = "",
                               participation_facts: str = "", workspace_root: str = "",
                               ask=None, rlog=None, phase: str = "negative-diagnosis",
                               original_task: str | None = None) -> VerdictNudge:
    """Return only a negative diagnosis whose typed provenance survives deterministic checks.

    The caller's completion control remains NOT_DONE whatever this returns. This function controls
    only what may be said to the coder. A typed missing_file/workspace_absence gets one independent
    required-output question against original_task (or task for direct root-task callers); the
    initial judge's quote is not authority. Other kinds retain exact task/evidence source checks.
    File state comes only from wsview. Unsupported or undecidable relationships suppress delivery.
    """
    definition = assistruntime.current().completion_diagnosis
    if definition is None:
        return VerdictNudge()
    result = definition.execute(completiondiagnosis.DiagnosisInput(
        lambda: obj, task, action_log, checks, participation_facts, original_task, phase),
        completiondiagnosis.GroundingServices(
            lambda subject: _workspace_subject(workspace_root, subject), _evidence_blocks, _fix_text, ask, rlog))
    return _diagnosis_nudge(result)


_restates_the_verdict = completionconfirmation.restates_claim


def _cria_measured_facts(sess) -> str:
    """What cria established by RUNNING the repo's checks, for a judge that gets no narrative.

    The network-off reading rides on the GatePlan; the participation report rides on the session's
    last gate reading.  Both are scoped to this session, gathered from the gate event, and silent
    when unavailable (#3)."""
    plan = getattr(sess, "gate_plan", None)
    offline = getattr(plan, "offline_fact", "") or ""
    observed = participation.render_for_judge(
        getattr(sess, "last_gate_participation", None),
        fresh=getattr(sess, "gate_fresh", None))
    return "\n\n".join(part for part in (offline, observed) if part)


@dataclass(frozen=True)
class _ApprovalQuestions:
    """Transport/read services only; selected source definitions own approval."""
    chat: Callable
    role: object
    log: object
    workspace_root: str

    def closed(self, prompt: str, *, phase: str) -> str:
        return ask_closed(self.chat, self.role, prompt, self.log, phase=phase, retry_off=False)

    def clean(self, raw: str) -> str:
        return self.role.clean_content(raw) if self.role is not None else raw

    def object(self, raw: str) -> dict | None:
        return extract_json_object(raw)

    def inspect_tests(self, system: str, user: str) -> str:
        return _completion_text(_judge_completion(
            self.chat, self.role, system, user, self.log, phase="test-e2e-participation",
            workspace_root=self.workspace_root, max_tokens=JUDGE_MAX_TOKENS, force_think_off=True))


def _confirmation_facts():
    return completionconfirmation.Facts(
        surveyed=lambda root: bool(wsview.current(root).surveyed),
        top_names=lambda root: wsview.current(root).listdir(root))


def _confirmation_services(chat, role, log, diagnosis):
    def inspect(request):
        off_role = replace(role, reasoning="off") if role is not None else None
        comp = _judge_completion(chat, off_role, request.system, request.user, log,
            phase=request.phase, force_think_off=request.force_think_off,
            workspace_root=request.workspace_root, answer_now_simple=request.answer_now_simple)
        pending = tuple(call.get("id") or "" for choice in comp.get("choices", [])
                        for call in (choice.get("message") or {}).get("tool_calls") or [])
        return completionconfirmation.InspectionReply(comp, inspection_rounds(comp), pending)

    def diagnose(request):
        if diagnosis is None:
            return ""
        off_role = replace(role, reasoning="off") if role is not None else None
        ask = (_composed_closed_ask(chat, off_role, log, phase=request.phase)
               if role is not None else None)
        result = diagnosis.execute(completiondiagnosis.DiagnosisInput(
            candidate=lambda: request.verdict, task=request.claim, checks=request.checks,
            original_task=request.original_task, phase=request.phase),
            completiondiagnosis.GroundingServices(
                lambda subject: _workspace_subject(request.workspace_root, subject),
                _evidence_blocks, _fix_text, ask, log))
        return str(_diagnosis_nudge(result))

    return completionconfirmation.Services(_confirmation_facts(), inspect,
        completionconfirmation.Readers(_completion_text,
            role.clean_content if role is not None else lambda text: text,
            _consistent_word, verdict_from_unclosed), diagnose)


def _confirm_completion(claim: str, reason: str, workspace_root: str, reasoner_chat, reasoner_role,
                        rlog, *, phase: str, cria_facts: str | Callable[[], str] = "",
                        original_task: str = "", authority=completionconfirmation.Authority.TASK,
                        planning_enabled: bool = False) -> completionconfirmation.Result:
    """The APPROVE-path brake — one narrow, reasoning-off check run ONLY on a done/satisfied verdict:
    is the completion claim CONSISTENT with (a) the fresh on-disk listing and (b) the verdict's own
    reason? Measured need (n=3 in one day, both judges): a judge holding contrary ground truth in its
    prompt ruled from the coder's NARRATIVE — passed "write unit tests" against a complete inventory
    of three tmp spills while citing a test function that exists nowhere (m8); ruled satisfied with
    no README in the listing (m6); attached a full failure analysis to a DONE (m7). The checker sees
    ONLY claim + reason — the coder's summary, the confabulation fuel, is deliberately absent — and
    INSPECTS the workspace itself via the shared read-only tools rather than being handed a pasted
    listing (operator's call, twice over: a real repo's complete listing can be massive, and a judge
    that must look cannot rubber-stamp a narrative). Returns the confirmation plus whether it was
    observed. No workspace to inspect → confirmed (nothing to check against), but unobserved.

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
    evidence — the fail-OPEN on completion principle 13 forbids outright: an incoherent verdict tells
    you the judge did not answer, never what the answer was. The direction is what makes a false
    positive harmless. Should a done-reason ever legitimately describe missing work (clause (b) of
    the checker's own prompt), quoting it back would be a fair veto — and cria's response here is
    still to withhold approval. The only thing lost is the specific wording; the boolean is
    identical. Nothing can advance that would not have advanced before."""
    root = assistruntime.current()
    selection = completionconfirmation.Selection(root.completion_confirmation, root.engagement_level,
                                                 planning_enabled=planning_enabled)
    result = selection.run(authority,
        lambda: completionconfirmation.Input(claim, reason, workspace_root, rlog, phase, authority,
            cria_facts() if callable(cria_facts) else cria_facts, original_task),
        lambda: _confirmation_services(reasoner_chat, reasoner_role, rlog, root.completion_diagnosis))
    if (not isinstance(result, completionconfirmation.Result)
            or not isinstance(result.status, completionconfirmation.Status)
            or result.authority is not authority or not isinstance(result.reason, str)
            or result.confirmed is not (result.status in (completionconfirmation.Status.CONFIRMED,
                                                         completionconfirmation.Status.UNCHECKED))
            or type(result.observed) is not bool
            or result.status is completionconfirmation.Status.CONFIRMED and not result.observed
            or result.status in (completionconfirmation.Status.NOT_SELECTED,
                                 completionconfirmation.Status.UNCHECKED) and result.observed):
        raise ValueError("Completion confirmation replacement must return matching Result")
    return result


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
    if not _is_a_finding(recovered):
        return None
    # Recovery classifies the source; it does not author replacement evidence.  Require the answer
    # after NOT_DONE to be an exact, contiguous quote from the source reasoning.  A paraphrase can be
    # correct and still has no provenance cria can surface as the checker's words.  Case-folding,
    # whitespace normalization and a second condensation call all erase that boundary, so none are
    # permitted here.
    start = text.find(recovered)
    if start < 0:
        rlog.emit("loop.verdict_recovery_unanchored", level="info", phase=phase,
                  chars=len(recovered))
        return None
    # Carry the exact source suffix from the quoted ruling onward.  The following source sentences
    # often contain the actionable diagnosis, and a contiguous slice preserves every byte the judge
    # actually wrote without a second provider paraphrasing it.
    reason = text[start:]
    rlog.emit("loop.verdict_from_reasoning", level="info", phase=phase,
              matched=_clip(recovered, 60), reason=_clip(reason, 120))
    return {flag: False, "reason": reason, "proposed_fix": ""}


def _fill_missing_verdict_flag(obj: dict, flag: str, rlog, phase: str) -> dict | None:
    """Recover only a negative verdict from a keyless object.

    The complete typed diagnosis shape is evidence that the schema's negative branch was intended,
    so the missing flag can be filled as ``False``. Free-form fix prose is not a type discriminator:
    treating it as one was the path by which an unsupported diagnosis acquired control significance.
    Positive completion must be explicit and then pass its normal confirmation brake. Ambiguous
    objects return ``None`` and take the caller's parse-miss/fail-closed path.
    """
    if flag in obj:
        # A readable object is not necessarily a verdict. Validate the original
        # public flag before either consumer can coerce it or infer a missing one.
        return obj if type(obj[flag]) is bool else None
    provenance_fields = {
        "diagnosis_kind", "subject", "task_quote", "evidence_source", "evidence_quote",
    }
    if not provenance_fields.issubset(obj):
        return None
    rlog.emit("loop.verdict_flag_inferred", flag=flag, inferred=False, phase=phase)
    return {**obj, flag: False}


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


class VerdictNudge(str):
    """One accepted satisfaction result with checker evidence and authored action kept separate.

    It remains a ``str`` for the existing coder-facing prompt path, while ``evidence`` and ``action``
    retain the provenance needed by other consumers.  In particular, a corrective ``PlanItem`` uses
    this exact accepted ``action`` rather than re-reading the provider's raw ``proposed_fix``.
    """

    def __new__(cls, evidence: str = "", action: str = "", *, diagnosis_kind: str = "",
                subject: str = ""):
        evidence = (evidence or "").strip()
        action = (action or "").strip()
        action_line = prompts.render("verdict_nudge_action", action=action) if action else ""
        rendered = "\n".join(part for part in (evidence, action_line) if part)
        value = super().__new__(cls, rendered)
        value.evidence = evidence
        value.action = action
        # Typed provenance survives the user-facing rendering.  The delivery scheduler may use
        # only this checked missing-file identity; it never extracts a path from judge prose.
        value.diagnosis_kind = diagnosis_kind
        value.subject = subject
        return value


def judge_satisfaction(task: str, evidence: str, reasoner_chat, reasoner_role, rlog, coder_tools: str = "",
                       workspace_root: str = "", routes: str = "",
                       gate_findings: str = "", messages: list | None = None,
                       sess=None) -> tuple[bool, str, str]:
    """Reasoner critic for the WHOLE user task (task-level, unlike the step-level _verify): is the user's
    original request satisfied by the REAL work (the coder's tool output — ground truth, not its claim)?
    Returns (satisfied, reason). Reasoning-ON first, then reasoning-OFF on a parse miss (the reasoner
    otherwise role-plays the coder and never emits the verdict). Fails CLOSED — an unparseable verdict is
    NOT satisfied, so a session is never ended on the critic's silence."""
    if not task.strip():
        return False, "no task text to judge", ""
    # ONE satisfaction-judge funnel.  Some callers append legacy gate notes before arriving here
    # and one (the re-derived-empty-tail check) does not.  Participation cannot depend on which
    # caller remembered it: add the current event here, byte-identically, unless already present.
    measured_participation = participation.render_for_judge(
        getattr(sess, "last_gate_participation", None),
        fresh=getattr(sess, "gate_fresh", None))
    if measured_participation and measured_participation not in evidence:
        evidence = "\n\n".join(part for part in (evidence, measured_participation) if part)
    system = prompts.load("satisfaction")
    user = prompts.render("satisfaction_user", task=task,
                          evidence=evidence or "(no actions recorded yet)")
    if coder_tools:  # reasoning about the coder's work → give it the coder's tools (see _verify)
        user = user + "\n\n" + prompts.render("reasoner_coder_tools", tools=coder_tools)
    # THE JUDGE IS ASKED THE TASK; THE RECORD RIDES BEFORE IT AS COMPOSED BLOCKS. The action log is the
    # one unbounded input, and in the active user message it was irreducible (A11: 22k estimated tokens
    # into a 16k window, nothing the floor may touch, the verdict failed at the wire both passes). As
    # blocks the floor drops the OLDEST ones, each drop labelled, and the question, the task and the
    # newest actions stay. `user` (whole) remains the string the nudge's grounding checks read.
    blocks = _evidence_blocks(evidence or "(no actions recorded yet)")
    asked = prompts.render("satisfaction_user_composed", task=task)
    if coder_tools:
        asked = asked + "\n\n" + prompts.render("reasoner_coder_tools", tools=coder_tools)
    obj = _satisfaction_verdict(system, asked, reasoner_chat, reasoner_role, rlog, reasoning_off=False,
                                workspace_root=workspace_root, evidence_blocks=blocks)
    if obj is not None:
        obj = _fill_missing_verdict_flag(obj, "satisfied", rlog, "satisfaction")
    if obj is not None:
        # The careful (reasoning-ON) pass produced a clean verdict — the ONLY pass trusted to APPROVE
        # ending the task, because approving requires the verification a reasoning-off judge can't do
        # (catching a placeholder/mocked "solution" — e.g. hardcoding the task's example handles so the
        # unit tests pass while nothing really resolves).
        satisfied = obj["satisfied"]
        if satisfied:
            questions = _ApprovalQuestions(reasoner_chat, reasoner_role, rlog, workspace_root)
            for definition in assistruntime.current().pre_release:
                if isinstance(definition, completionapproval.ParticipationDefinition):
                    source = completionapproval.ParticipationInput(
                        task, lambda: getattr(sess, "last_gate_participation", None), questions, rlog)
                    withheld = "required_test_unverified"
                else:
                    source = completionapproval.ExactFormInput(
                        task, lambda: evidence,
                        lambda a, b: _same_workspace_path(a, b, workspace_root), questions, rlog)
                    withheld = "unverified_step"
                result = definition.execute(source)
                if (not isinstance(result, completionapproval.ApprovalResult)
                        or not isinstance(result.status, completionapproval.ApprovalStatus)):
                    raise ValueError("Completion approval replacement must return ApprovalResult")
                if result.blocks:
                    return False, result.text or prompts.load(withheld), ""
        if satisfied and workspace_root:
            # The approve-path brake (see _confirm_completion): "satisfied" must be consistent with
            # the FRESH on-disk listing and with its own stated reason (m6 ended a run with no README
            # while the listing in the judge's prompt proved its absence).
            confirmation = _confirm_completion(task, str(obj.get("reason") or ""), workspace_root,
                                                 reasoner_chat, reasoner_role, rlog,
                                                 phase="satisfaction-confirm", original_task=task,
                                                 cria_facts=lambda: _cria_measured_facts(sess))
            if confirmation.status is not completionconfirmation.Status.NOT_SELECTED:
                rlog.emit("loop.satisfaction_confirm", confirmed=confirmation.confirmed)
                if not confirmation.confirmed:
                    return False, confirmation.reason, ""
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
        diagnosis_ask = (_composed_closed_ask(reasoner_chat, reasoner_role, rlog,
                                              phase="satisfaction-diagnosis")
                         if reasoner_role is not None else None)
        nudge = _verdict_nudge(obj, satisfied, routes, evidence=user, task=task,
                               original_task=task, action_log=evidence, checks=gate_findings,
                               participation_facts=measured_participation,
                               diagnosis_ask=diagnosis_ask, phase="satisfaction-diagnosis",
                               workspace_root=workspace_root, rlog=rlog,
                               messages=messages, sess=sess)
        return satisfied, nudge, nudge.action
    # No parseable careful verdict (the reasoner over-thought, or leaked a spurious tool call instead of
    # the JSON). A reasoning-OFF retry can RECOVER a verdict, but a reasoning-off judge is a rubber
    # stamp — competent to REJECT, not to APPROVE. So use it only to confirm NOT-satisfied; a
    # "satisfied" that exists ONLY because the careful pass failed is downgraded and we fail CLOSED. A
    # false "done" over fake work is far worse than a few more work turns.
    retry = _satisfaction_verdict(system, asked, reasoner_chat, reasoner_role, rlog, reasoning_off=True,
                                  workspace_root=workspace_root, evidence_blocks=blocks)
    if retry is not None:
        retry = _fill_missing_verdict_flag(retry, "satisfied", rlog, "satisfaction-retry")
    if retry is None:
        # Fail closed — but the CODER-facing reason is a plain instruction, never cria's internal
        # bookkeeping: "unverified (no parseable verdict)" injected as a steer made one model
        # confabulate a meaning for it and leap ahead to another file (run 0729-gemma4 pon2 0243).
        return False, prompts.load("unverified_step") + _named_gap(gate_findings), ""
    if retry["satisfied"]:
        rlog.emit("loop.satisfaction_failclosed", level="info")
        return False, "unverified — the careful check could not confirm completion; keep working", ""
    retry_ask = (_composed_closed_ask(reasoner_chat, reasoner_role, rlog,
                                      phase="satisfaction-retry-diagnosis")
                 if reasoner_role is not None else None)
    nudge = _verdict_nudge(retry, False, routes, evidence=user, task=task,
                           original_task=task, action_log=evidence, checks=gate_findings,
                           participation_facts=measured_participation,
                           diagnosis_ask=retry_ask, phase="satisfaction-retry-diagnosis",
                           workspace_root=workspace_root, rlog=rlog,
                           messages=messages, sess=sess)
    return False, nudge, nudge.action


def observe_task_missing_file(task: str, *, workspace_root: str, reasoner_chat, reasoner_role,
                              rlog) -> VerdictNudge:
    """Observe one task-named whole-file absence without judging completion or check state.

    The caller owns the complete/current survey prerequisite.  This observer cannot clear, re-run,
    or reinterpret checks; false, unreadable, and unsupported answers are silence.  The shared
    negative-diagnosis owner independently grounds required-output status in the original task
    and re-checks current wsview absence before the pre-frame owner can arm a remediation.
    """
    definition = assistruntime.current().completion_diagnosis
    if definition is None:
        return VerdictNudge()
    return _diagnosis_nudge(definition.observe(
        completiondiagnosis.ObservationInput(task, bool(workspace_root and reasoner_chat is not None)),
        _diagnosis_observation_services(definition, workspace_root, reasoner_chat, reasoner_role, rlog)))


def _diagnosis_nudge(result) -> VerdictNudge:
    result = completiondiagnosis._diagnosis_result(result)
    nudge = (VerdictNudge(result.evidence, result.action,
                         diagnosis_kind=result.diagnosis_kind, subject=result.subject)
             if result.status is completiondiagnosis.DiagnosisStatus.GROUNDED else VerdictNudge())
    nudge.diagnosis_result = result
    return nudge


def _diagnosis_observation_services(definition, root, chat, role, log):
    grounding = completiondiagnosis.GroundingServices(
        lambda subject: _workspace_subject(root, subject), _evidence_blocks, _fix_text,
        _composed_closed_ask(chat, role, log, phase="deliverable-observation-requirement")
        if role is not None else None, log)
    return completiondiagnosis.ObservationServices(
        inventory=lambda: workspace_inventory(root),
        judge=lambda system, user: _judge_completion(chat, role, system, user, log,
            phase="deliverable-observation", workspace_root=root, verdict_key="missing_file",
            verdict_schema="observation", seed_files=True),
        truncated=massage.is_truncated, text=_completion_text,
        clean=role.clean_content if role is not None else lambda text: text,
        grounding=grounding, execute=definition.execute)


def _diagnosis_delivery_services(definition, root, log):
    def observation():
        view = wsview.current(root) if root else None
        return view.observation_fingerprint if view is not None else None
    return completiondiagnosis.DeliveryServices(
        observation=observation, event_head=_clip, arm=definition.arm, log=log)


def _diagnosis_lifecycle_services(definition, root, chat, role, log):
    return completiondiagnosis.ObservationLifecycleServices(
        observer=_diagnosis_observation_services(definition, root, chat, role, log),
        delivery=_diagnosis_delivery_services(definition, root, log), due=periodic_check_due,
        observe=definition.observe, deliver=definition.deliver)


def _diagnosis_remediation_services(root="", log=None):
    return completiondiagnosis.RemediationServices(
        _write_path, lambda a, b: _same_workspace_path(a, b, root), _command_text, log)


def satisfaction_done_note(reason: str, *, checks_ran: bool = True) -> str:
    """The completion text forwarded when the satisfaction check accepts a 'done'.

    `checks_ran` decides which claim it opens with, and it has to, because `guard_gate_verdict`
    returns None for a green gate AND for one that could not run — the same fail-open every other
    seat honours. The old wording asserted "verified by the completion check AND THE REPO'S OWN
    CHECKS" in both cases, and in the second case nothing had verified anything: a false fact about
    the world, stated in the session's last message (#5b). The same wording also shipped on the
    no-shell path, where no gate was even composed. Both wordings live in prompts/ (#22); the answer
    comes from `last_gate_ran`, which every gate reader now writes (see record_gate_state).

    THE LIVE-EXECUTION MARKER USED TO RIDE HERE and was removed on 2026-08-18 (operator: "drop the
    'something needs to be ran' assertion altogether — it is more trouble than it is worth"). It
    asked a model whether finishing depended on running a program, and answered YES on 87% of a
    corpus made entirely of build-me-a-CLI tasks — a prior about the suite, not about cria. On a real
    repository that licenses cria to execute something a model picked: a server that binds a port, a
    migration, a deploy script. The suite's own usefulness judge grades "does not build, does not
    run, or produces wrong results" at 10-39, so the observation it existed for is still made — by
    the verifier, after the run, where executing is appropriate. What follows is unchanged:
    the repo's own checks prove a workspace compiles, lints and passes its tests, and none of that
    can tell you the delivered program does anything. Measured across 51 archived runs: 13 (25%)
    contained no entry point at all and not one of those ever scored full marks."""
    words = prompts.load_map("satisfaction_done")
    note = f"{words['checked' if checks_ran else 'unchecked']} {reason}".strip()
    return note


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
    # THE LISTING'S OWN SPELLING, not a lowercased copy. The name goes into a sentence the coder
    # reads — "these files DO exist on disk right now: review.md" — and `REVIEW.md` is what is
    # actually there. Matching stays case-insensitive; only the reported name is the real one.
    present = {m.lower(): m for m in re.findall(r"[\w./-]+\.\w{1,5}", files_list or "")}
    if not present:
        return []
    named = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", briefing or ""):
        m = _DENIES_FILE.search(sent)
        if not m:
            continue
        f = (m.group(1) or m.group(2) or "").lower()
        if not f:
            continue
        hit = next((real for low, real in present.items()
                    if low == f or low.endswith("/" + f)), "")
        if hit and hit not in named:
            named.append(hit)
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
        rlog.emit("context.briefing_denies_disk", steer="briefing-fix", level="warn",
                  files=prompts.named_list(named))
    return briefing + "\n\n" + prompts.fill(
        prompts.load_map("briefing_checks")["files_exist"], files=", ".join(named))


# Past this, a COMPOSED two-message prompt cannot be made to fit by the context floor: the floor's
# lever is dropping whole oldest turns, and a two-message call has none to drop. This is where #5's
# second exception applies — a MODEL-MADE summary, labelled as one — because the alternative that
# used to sit here was a character clip, and the one after that is a judge call that errors out and
# fails closed into the same re-nudge loop the clip was built for.
EVIDENCE_SUMMARY_TRIGGER_CHARS = 48000

# A closed-question judge's evidence rides as COMPOSED BLOCKS of about this many characters, never as one
# protected message. The floor can reduce only whole unprotected turns, so evidence inside the system
# message or the active user message is irreducible: phi4 A11 sent a 22,222-estimated-token satisfaction
# judge and a 17,672-token steer-diagnostic judge into a 16,384-token window with nothing the floor was
# allowed to touch, and both failed at the wire ("Measured input cannot fit the context window without
# losing protected input"). Blocks cut on line boundaries and re-concatenate to the original text.
EVIDENCE_BLOCK_CHARS = evidencesummary.EVIDENCE_BLOCK_CHARS


def _evidence_blocks(text: str, limit: int = EVIDENCE_BLOCK_CHARS) -> list[str]:
    return evidencesummary.blocks(text, limit)


def _summarised_evidence(log: str, chat_fn, role, rlog, *, _consume=None) -> str:
    """Bind one selected evidence lifecycle to the consumer's actual local slot.

    Selection, folding, summary admission and labelling belong to the Source.
    The consumer assembles its packet before settlement; this is not wire ACK.
    No result or definition is cached across invocations or recursive consumers.
    """
    definition = assistruntime.current().evidence_summary
    if definition is None:
        return _consume(log) if _consume is not None else log
    result = definition.execute(evidencesummary.Input(log, summarize, chat_fn, role, rlog))
    if (not isinstance(result, evidencesummary.Result)
            or not all(isinstance(value, str) for value in (result.raw, result.folded, result.selected))
            or result.raw != log or not isinstance(result.selection, evidencesummary.Selection)
            or type(result.folded_actions) is not int or result.folded_actions < 0
            or result.summary is not None and not isinstance(result.summary, str)):
        raise ValueError("Evidence summary replacement must return matching Result")
    slot = result.selected
    consumed = _consume(slot) if _consume is not None else slot
    settled = definition.settle(result, slot)
    if settled is None and result.selection is evidencesummary.Selection.DISABLED:
        return consumed
    if (not isinstance(settled, evidencesummary.Settlement) or settled.result is not result
            or not isinstance(settled.delivered, str) or settled.delivered != slot
            or type(settled.selected_delivered) is not bool
            or settled.selected_delivered != (slot == result.selected)):
        raise ValueError("Evidence summary replacement must return matching Settlement")
    return consumed


def _dedup_evidence(log: str, rlog=None, chat_fn=None, role=None, *, _consume=None) -> str:
    """Compatibility entry for selected evidence, never a separate folding policy.

    The former 24,000-character tail clip lost the write that began a stuck step;
    its replacement retains distinct actions and labels model-made summaries.
    The selected Source owns that choice; final fitting remains at the wire.
    """
    return _summarised_evidence(log, chat_fn, role, rlog, _consume=_consume)


@dataclass(frozen=True)
class RewriteObservation:
    """One Store-owned pending event; never a model-authored or message-derived receipt."""
    key: str
    event_id: str


class LoopStore:
    """The loop's server-side session state: live plans and each session's conversation-root
    SHAPE (structural harness-compaction detection + a one-bit `done` marker). DETECTION state
    only — the completion BRIEFING is never stored here; it rides in the conversation (embedded
    in the closing message) and is re-read from the history the harness sends back.

    ``state_path`` persists shapes and the durable subset of live sessions. Transient
    gates and judgment signatures are not resumed; selection IDs are a task contract
    and survive reconstruction, while executable callables never enter the state file."""

    def __init__(self, state_path: str | None = None) -> None:
        self._sessions: dict[str, GuardState] = {}
        # In-flight pre-plan survey state is not a plan and must not survive a restart.
        self._bootstraps: dict[str, SurveyBootstrap] = {}
        # session key -> {fp, n, pending, done, rewrite_id}: opaque pending identity survives restart.
        # DETECTION state only — the completion briefing itself is never stored server-side; it
        # rides in the conversation (the closing message) and is re-read from history.
        self._shapes: dict[str, dict] = {}
        self._state_path = Path(state_path).expanduser() if state_path else None
        self._lock = threading.Lock()
        self._load()

    def get(self, key: str) -> PlanSession | None:
        with self._lock:
            owner = self._sessions.get(key)
            return owner if isinstance(owner, PlanSession) else None

    def get_guard(self, key: str, *, create: bool = False) -> GuardState | None:
        """Actual process-local task owner, also when no planning driver exists."""
        with self._lock:
            owner = self._sessions.get(key)
            if owner is None and create:
                owner = GuardState()
                self._sessions[key] = owner
                retired = self._bound_sessions_locked()
            else:
                retired = ()
        for departed in retired:
            self._retire_guard(departed)
        return owner

    def get_bootstrap(self, key: str) -> SurveyBootstrap | None:
        with self._lock:
            return self._bootstraps.get(key)

    def put_bootstrap(self, key: str, bootstrap: SurveyBootstrap) -> None:
        with self._lock:
            self._bootstraps.pop(key, None)
            self._bootstraps[key] = bootstrap
            while len(self._bootstraps) > _MAX_SESSIONS:
                self._bootstraps.pop(next(iter(self._bootstraps)))

    def drop_bootstrap(self, key: str) -> None:
        with self._lock:
            self._bootstraps.pop(key, None)

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
            if prev is not None and _stable_session(key):
                sess.handoff_origin = getattr(prev, 'handoff_origin', None)
                previous_refusals = _session_refusals(prev)
                current_refusals = _session_refusals(sess)
                if isinstance(previous_refusals, refusalledger.RefusalLedger):
                    newer = (current_refusals if isinstance(current_refusals, refusalledger.RefusalLedger)
                             else refusalledger.RefusalLedger.from_legacy(current_refusals or set()))
                    sess.refusal_events = previous_refusals.merged(newer)
                    sess.refused_names = sess.refusal_events.active_names()
                elif previous_refusals:
                    if isinstance(current_refusals, refusalledger.RefusalLedger):
                        sess.refusal_events = refusalledger.RefusalLedger.from_legacy(
                            previous_refusals).merged(current_refusals)
                        sess.refused_names = sess.refusal_events.active_names()
                    else:
                        sess.refused_names = set(current_refusals or set()) | set(previous_refusals)
            self._sessions.pop(key, None)          # re-put refreshes recency
            self._sessions[key] = sess
            retired = self._bound_sessions_locked()
            self._save_locked()
        for departed in (([prev] if prev is not None and prev is not sess else []) + retired):
            self._retire_guard(departed)

    def persist(self, key: str) -> None:
        """Re-save after in-place PlanSession mutations (step advanced, nudge recorded) — a cria
        restart mid-plan then RESUMES the plan instead of re-planning blind (the restart-amnesia
        bug: a fresh plan chose new filenames → duplicate near-identical files in the workspace)."""
        with self._lock:
            if key in self._sessions:
                self._save_locked()

    def _bound_sessions_locked(self) -> list[GuardState]:
        """Evict the least recently put sessions past the bound.

        `_shapes` is capped on write AND on load; `_sessions` was capped nowhere, and its only
        eviction site is the plan-ON `loop.done` path, which fired ZERO times in twelve days of
        logs. Measured on the live `loopstate.json`: **494 sessions, every one `in_progress`,
        1,015,017 bytes**, accumulating since 2026-07-27 — 105 of them had already completed the
        plan-off gate. `persist()` runs every turn and re-serialises all of them under the lock:
        4.08 ms to dump plus 3.43 ms to write, per turn, growing linearly, for state that is stale.
        It also keeps every task's text and every step verbatim, forever.

        Bounded the way the shapes beside it are, oldest-put first, so a live session is never the
        one evicted."""
        retired = []
        while len(self._sessions) > _MAX_SESSIONS:
            retired.append(self._sessions.pop(next(iter(self._sessions))))
        return retired

    @staticmethod
    def _retire_guard(owner) -> None:
        # Invalidate through each obligation's actual captured Source owner, never a new selection.
        for offered in (getattr(owner, 'externalization_offers', None) or {}).values():
            delivery = getattr(offered, 'delivery', None) or getattr(offered, 'externalization', None)
            if delivery is not None:
                delivery.cancel()
                delivery.reset()
        owner.externalization_offers = None
        owner.externalization_state = None

    def drop(self, key: str) -> None:
        with self._lock:
            owner = self._sessions.pop(key, None)
            self._save_locked()
        if owner is not None:
            self._retire_guard(owner)

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
        """Compatibility boolean over the same authoritative observation/update."""
        return self.observe_shape_with_ticket(key, fp, n_messages) is not None

    def observe_shape_with_ticket(self, key: str, fp: str, n_messages: int) -> RewriteObservation | None:
        """Record this session's conversation SHAPE; return its pending event ticket — the
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

        The signal is STICKY: a detected rewrite stays pending until its observed delivery is
        acknowledged, or an explicit handled branch calls ``clear_rewrite``. A failed/deferred
        turn doesn't consume it; append-only observations retain the same event identity."""
        if not fp:
            return None
        with self._lock:
            prev = self._shapes.get(key)
            shrank = prev is not None and n_messages < int(prev.get("n") or 0)
            changed = prev is not None and (prev.get("fp") != fp or shrank)
            pending = changed or bool(prev and prev.get("pending"))
            event_id = prev.get("rewrite_id") if prev else None
            assign_id = pending and (changed or not isinstance(event_id, str) or not event_id)
            if assign_id:
                event_id = uuid.uuid4().hex
            first_sight = prev is None
            self._shapes.pop(key, None)  # re-put refreshes recency
            self._shapes[key] = {"fp": fp, "n": n_messages, "pending": pending,
                                 "done": bool(prev and prev.get("done")),
                                 "rewrite_id": event_id}  # identity survives append-only updates/restarts
            while len(self._shapes) > _MAX_SHAPES:
                self._shapes.pop(next(iter(self._shapes)))
            if first_sight or changed or assign_id:
                self._save_locked()
            return RewriteObservation(key, event_id) if pending else None

    def ack_rewrite(self, observed: RewriteObservation | None) -> bool:
        """Commit only the observed event, never a newer or another session's rewrite."""
        if (not isinstance(observed, RewriteObservation)
                or not isinstance(observed.event_id, str) or not observed.event_id):
            return False
        with self._lock:
            shape = self._shapes.get(observed.key)
            if not shape or not shape.get("pending") or shape.get("rewrite_id") != observed.event_id:
                return False
            shape["pending"] = False
            self._save_locked()
            return True

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
            return (isinstance(self._sessions.get(key), PlanSession)
                    or key in self._bootstraps or key in self._shapes)

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
                # BOUNDED ON LOAD TOO, like the shapes above — otherwise a file that grew before the
                # write bound existed carries its whole history back into memory on every start.
                for k, v in list(sessions.items())[-_MAX_SESSIONS:]:
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
                                                    for k, v in self._sessions.items()
                                                    if isinstance(v, PlanSession)}},
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
    planner_enabled: bool = False
    # Periodic SATISFACTION check cadence for the single-item path — start at drive `start`, then every
    # `every` drives (operator-tunable [context]; 0 disables). Only the single-item off-ramps use these.
    satisfaction_check_start: int = 100
    satisfaction_check_every: int = 25
    # The COMPACTOR endpoint's chat for the single-item self-compaction summary — rides the compactor
    # box (compactor_upstream.chat) like the plan-off _summarize did, so a compactor on its own base_url
    # is honored. None → fall back to reasoner_chat (the summarize sampling still uses compactor_role).
    compactor_chat: object = None  # (body, rlog) -> bytes | None
    # THE ENGAGEMENT LADDER, at the two rungs the loop owns. The loop is built at level 4 and above.
    #
    #   assists = False  (level 4, DONE_REFUSALS_ENABLED)  cria answers a completion CLAIM and does
    #       nothing else: the model tries to stop, the repo's checks decide, and cria says what is
    #       still outstanding. No steers, no periodic gate, no periodic satisfaction check, no
    #       detectors, no planner. It never speaks first.
    #   assists = True   (level 5, ASSISTS_ENABLED)        everything the driver knows how to do.
    #
    # THE SPLIT IS THE TRIGGER, NOT THE MACHINERY. The same judge and the same gate are reached from
    # both sides; what decides the rung is who started it. The model tried to stop → level 4. A turn
    # counter fired → level 5. So `done_critic` and the completion probe are 4 while
    # `satisfaction_check` and `periodic_gate` are 5, though they call the same functions.
    assists: bool = True
    pilot_runtime: assistruntime.AssistRuntime = field(default_factory=assistruntime.AssistRuntime)
    # The service's optional trained CPU classifier ([system1]) — ONE immutable runtime shared by every
    # session (it holds no session state). None = every closed question below goes to the reasoner as
    # before. When set it answers ONLY the compaction briefing's PLAN/RETROSPECTIVE lens and the
    # authored directive's DICTATES/DESCRIBES question; scope, fidelity and every other judgment stay
    # with the reasoner. See cria/system1wiring.py.
    system1: system1wiring.Judge | None = None


class _IncompleteCoderTurn(Exception):
    """Private result transfer after guards; incomplete output cannot enter a gate."""
    def __init__(self, completion: dict):
        super().__init__('Coder reply remains incomplete after existing guards')
        self.completion = completion


class _LivingTailView:
    """Source correlation and one-shots backed by the existing driver owner."""
    _fields = {'step_key': 'living_step_key', 'plan_id': 'living_plan_id', 'task': 'living_task',
               'critic_rescue_used': 'verify_replanned', 'thrash_rescue_used': 'thrash_replanned',
               'sequence': 'living_sequence', 'pending': 'living_pending'}
    reset = livingplan.TailState.reset
    fork = livingplan.TailState.fork

    def __init__(self, owner):
        object.__setattr__(self, '_owner', owner)

    def __getattr__(self, name):
        return getattr(self._owner, self._fields[name])

    def __setattr__(self, name, value):
        setattr(self._owner, self._fields[name], value)


class _PastedFileView:
    """Borrow the task's actual memo and transient delivery fields, never copy them."""
    _fields = {'judged': 'text_write_judged', 'other': 'pasted_block_other',
               'unread_fact': 'unread_target_fact', 'prepared': 'pasted_prepared',
               'pending_nudge': 'pasted_pending_nudge', 'delivered_nudge': 'pasted_delivered_nudge',
               'delivery': 'pasted_delivery', 'deliveries': 'pasted_deliveries',
               'settlements': 'pasted_settlements'}

    def __init__(self, owner):
        object.__setattr__(self, '_owner', owner)

    def __getattr__(self, name):
        return getattr(self._owner, self._fields[name], '' if name == 'unread_fact' else None)

    def __setattr__(self, name, value):
        setattr(self._owner, self._fields[name], value)


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

    def visible_context_tokens(self, body: dict, session_key: str, *, fold: bool = False,
                               definitions: tuple[modelview.WireDefinition, ...] | None = None) -> int:
        """Pre-floor size of the conversation the CODER would be shown for this request — the number
        the server reports to the harness as usage (`server._report_context_usage`).

        It is built by the coder's own framing, `_frame_for_item` in the plan-off raw-task form, so
        the report cannot drift from the prompt: cria's coder system prompt + tool hint + the
        harness's caller instructions are IN; the harness agent prompt, cria's gate survey/launch/
        poll plumbing and its results (`probegate.clean_gate_results`) and blanked ⟦cria⟧ status
        turns are OUT. Sized by `modelview.visible_tokens`, the floor's own pre-fit estimate.

        Valid on every turn, including gate-transport turns that make no upstream call (the size
        depends only on the request's messages and the session's gate plan). It is measured BEFORE
        the drive, so it is the conversation the model would need — before `contextfloor.fit`
        trims and before the driver's own self-compaction — and the per-turn steer/facts that a
        coder call appends are not in it. With the planner ON the step prompt is not counted either
        (planner is off by default; a step prompt is a few hundred bytes)."""
        sess = self._store.get(session_key)
        bootstrap = getattr(self._store, "get_bootstrap", lambda _key: None)(session_key)
        gate_plan = (getattr(sess, "gate_plan", None) if sess is not None
                     else getattr(bootstrap, "gate_plan", None))
        runtime = self._ctx.pilot_runtime
        definitions = runtime.wire_folds if definitions is None else definitions
        with assistruntime.bound(runtime):
            base = _required_coder_base(body.get("messages", []), tools=body.get("tools"),
                prior_work=getattr(sess, "prior_work", "") or "", gate_plan=gate_plan,
                workspace_root=getattr(sess, "workspace_root", None), reframe=True,
                suspend_cursor=bool(getattr(sess, "replan_uncovered", False)))
            framed = base.messages
        return modelview.visible_tokens(framed, body.get("tools"), fold=fold, definitions=definitions)

    def _initial_policies(self, session_key: str = '', *, owner=None) -> planner.PlanningSelection:
        state = owner if owner is not None else (self._store.get(session_key)
            or self._store.get_bootstrap(session_key))
        if state is not None:
            _pin_pilot_runtime(state, self._ctx.pilot_runtime)
            return state.pilot_binding.initial_planning
        return self._ctx.pilot_runtime.initial_planning

    def _plan_for(self, messages: list[dict], rlog, session_key: str = "", **frame) -> tuple[Plan | None, planner.PlanOutcome]:
        """Plan with outcome owned by this drive, not the shared Planner instance.

        Test and third-party planner doubles retain the old two-argument contract; only cria's
        Planner knows the optional outcome carrier and the session key (#23: the shared Planner's
        admission-exhaustion counter must be scoped to THIS session, or an unrelated session whose
        task text happens to hash the same is silenced by a give-up that was never its own — see C30).
        """
        outcome = planner.PlanOutcome()
        policies = self._initial_policies(session_key)
        if not self._ctx.planner_enabled or not policies.bindings('experimental-plan-gather'):
            return None, outcome
        source = self._ctx.planner
        if isinstance(source, planner.Planner):
            if assistruntime.current().externalization is not None:
                outcome.externalization_owner = self._store.get_guard(session_key, create=True)
                outcome.current_externalization_owner = lambda: self._store.get_guard(session_key)
            return source.plan_for(messages, rlog, outcome=outcome, session_key=session_key,
                                   policies=policies, **frame), outcome
        return source.plan_for(messages, rlog, **frame), outcome

    def _new_bootstrap(self, session_key: str, messages: list[dict]) -> SurveyBootstrap:
        state = SurveyBootstrap(workspace_root=_extract_cwd(messages) or self._ctx.workspace_root,
                                web_session=session_key)
        _pin_pilot_runtime(state, self._ctx.pilot_runtime, self._store.get_bootstrap(session_key))
        return state

    def _put_session(self, key: str, sess: PlanSession) -> None:
        # Transfer existing provenance before publishing or consuming the bootstrap.
        bootstrap = self._store.get_bootstrap(key)
        _pin_pilot_runtime(sess, self._ctx.pilot_runtime, bootstrap)
        self._store.put(key, sess)
        if bootstrap is not None:
            self._store.drop_bootstrap(key)

    def _decline_bootstrap(self, key: str, completed: SurveyBootstrap | None,
                           outcome: planner.PlanOutcome) -> None:
        # Only a completed factual read followed by a definitive no-successor decision
        # consumes this owner. Deferred/retriable planning and exceptions retain provenance.
        if (completed is not None and not outcome.survey_pending
                and not getattr(self._ctx.planner, "_retriable_failure", False)
                and self._store.get_bootstrap(key) is completed):
            self._store.drop_bootstrap(key)

    def _defer_planner_survey(self, outcome: planner.PlanOutcome, messages: list[dict],
                              body: dict, session_key: str, rlog) -> dict | None:
        """Return the one harness command that can answer a deferred planner read."""
        if not outcome.survey_pending:
            return None
        bootstrap = self._new_bootstrap(session_key, messages)
        probe_tc = guard_gate_op(bootstrap, body, rlog, workspace_root=bootstrap.workspace_root)
        if probe_tc is None:
            return None
        bootstrap.probe_call_id = probe_tc["id"]
        self._store.put_bootstrap(session_key, bootstrap)
        rlog.emit("loop.planner_survey_deferred")
        return _completion_toolcalls([probe_tc])

    def drive(self, body: dict, session_key: str, classification, rlog, *, pasted_delivery=None) -> dict | None:
        """Return the completion (OpenAI dict) cria should send, or ``None`` to fall
        through to the normal proxy (not a plan-driven task)."""
        with self._session_lock(session_key), assistruntime.bound(self._ctx.pilot_runtime):
            # BOTH owners are checked outside the finally that may first-pin new state.
            previous_session = self._store.get(session_key)
            for previous in (previous_session, self._store.get_bootstrap(session_key)):
                if previous is not None:
                    _check_pilot_runtime(previous, self._ctx.pilot_runtime)
            owners = [previous_session] if previous_session is not None else []
            if previous_session is not None:
                self._settle_pasted_results(previous_session, body.get('messages', []))
            def report_owner(owner):
                if not any(known is owner for known in owners):
                    owners.append(owner)
            pasted_offered = False
            try:
                try:
                    try:
                        out = self._drive_locked(body, session_key, classification, rlog,
                                                 _semantic_owner=report_owner)
                    except UpstreamProtocolError as error:
                        sess = self._store.get(session_key)
                        if sess is None or not getattr(error, 'coder_turn', False):
                            raise
                        out = self._protocol_refused(sess, session_key, body, error, rlog)
                except _IncompleteCoderTurn as result:
                    out = result.completion
                    rlog.emit('loop.generation_incomplete', evidence=out.get(generation.EVIDENCE, {}))
                finally:
                    for active in (self._store.get(session_key), self._store.get_bootstrap(session_key)):
                        if active is not None:
                            _pin_pilot_runtime(active, self._ctx.pilot_runtime)
                    self._store.persist(session_key)
                current = self._store.get(session_key)
                if current is not None and not any(owner is current for owner in owners):
                    owners.append(current)
                if out is not None:
                    if current is not None and current.generation_errors:
                        out.setdefault(generation.EVIDENCE, {})['prior_protocol_errors'] = list(current.generation_errors)
                    # The loop's synthesized completions carry only object+choices; a plain
                    # /v1/chat/completions client (non-Codex) needs a well-formed envelope. Codex's
                    # Responses adapter rebuilds its own, so this is for the direct chat clients.
                    out.setdefault("id", f"chatcmpl-{uuid.uuid4().hex}")
                    out.setdefault("created", int(time.time()))
                    out.setdefault("model", body.get("model") or "")
                prepared = []
                for owner in owners:
                    if (owner is current or (current is None and previous_session is None
                                             and not _stable_session(session_key))):
                        prepared.append((owner, _prepare_stalled_reply(owner, out)))
                for owner, pending in prepared:
                    semanticquery.settle_turn(owner, out)
                    _settle_stalled_reply(owner, pending)
                retained_owners = tuple((owner, owner.pasted_prepared, owner.pasted_consumed)
                                        for owner, _pending in prepared)
                living_owners = tuple((owner, owner.living_effects, owner.living_raw_reply)
                                      for owner, _pending in prepared)
                pasted_finished = False
                def finish_pasted(actual, admitted_writes=None):
                    nonlocal pasted_finished
                    if pasted_finished:
                        return
                    pasted_finished = True
                    for owner, original_prepared, original_consumed in retained_owners:
                        self._retain_pasted_reply(owner, actual, admitted_writes,
                            prepared=original_prepared, consumed=original_consumed)
                    for owner, effects, raw_reply in living_owners:
                        if _stable_session(session_key) and self._store.get(session_key) is not owner:
                            owner.living_pending = owner.living_effects = owner.living_raw_reply = None
                            continue
                        self._retain_living_reply(owner, effects, raw_reply, actual, out, rlog)
                    if self._store.get(session_key) is current:
                        self._store.persist(session_key)
                if pasted_delivery is None:
                    finish_pasted(out)
                else:
                    pasted_delivery(finish_pasted)
                pasted_offered = True
                return out
            finally:
                current = self._store.get(session_key)
                if current is not None and not any(owner is current for owner in owners):
                    owners.append(current)
                for owner in owners:
                    semanticquery.discard_turn(owner)
                    owner.stalled_reply = None
                    if not pasted_offered:
                        definition = self._pasted_selection(owner)
                        pending = owner.pasted_prepared
                        if definition is not None and pending is not None:
                            definition.forwarded(self._pasted_state(owner), pending,
                                {'choices': [{'message': {'tool_calls': []}}]})
                        owner.pasted_consumed = None
                        owner.living_pending = None

    def _drive_locked(self, body: dict, session_key: str, classification, rlog,
                      *, _semantic_owner=None) -> dict | None:
        messages = body.get("messages", [])
        # Observe a structural harness rewrite before the tool-less compaction turn is deferred.
        # The pending state is consumed only by a later actionable continuation.
        stable = _stable_session(session_key)
        root_text, root_fp = _history_root(messages)
        rewrite_observation = (self._store.observe_shape_with_ticket(session_key, root_fp, len(messages))
                               if stable else None)
        rewritten = rewrite_observation is not None
        sess = self._store.get(session_key)
        bootstrap = getattr(self._store, "get_bootstrap", lambda _key: None)(session_key)
        if rewritten:
            rlog.emit("loop.history_rewritten", live=sess is not None or bootstrap is not None,
                      n_messages=len(messages))

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
        initial_enabled = (self._ctx.planner_enabled
                           and bool(self._initial_policies(session_key).bindings('experimental-plan-gather')))
        if initial_enabled and find_shell_tool(body.get("tools")) is None:
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
        bootstrap_finished = False

        if bootstrap is not None:
            raw = _read_tool_result(messages, bootstrap.probe_call_id)
            if rewritten:
                recovered = _reissue_repository_checks(_NamedProbeState(bootstrap, "probe_call_id"),
                    body, rlog, workspace_root=bootstrap.workspace_root, rewritten=True)
                if recovered.call is not None:
                    rlog.emit("loop.survey_bootstrap_reissued", attempt=bootstrap.probe_reissues)
                    return _repository_completion(recovered)
            transport_tc = guard_gate_transport(bootstrap, body, rlog, call_id=bootstrap.probe_call_id)
            if transport_tc is not None:
                return _completion_toolcalls([transport_tc])
            outcome = read_gate(bootstrap.gate_plan, raw, rlog)
            # Keep provenance until a successor is published, including planner deferrals.
            bootstrap_finished = True
            messages = probegate.clean_gate_results(messages, bootstrap.gate_plan,
                                                    drop_private_results=True)
            body = {**body, "messages": messages}
            rlog.emit("loop.survey_bootstrap_finished",
                      surveyed=bool(getattr(outcome, "replan_after_survey", False)),
                      transport_unknown=bool(getattr(outcome, "transport_unknown", False)))

        if sess is None:
            # The completion briefing rides IN THE CONVERSATION (embedded in the closing message,
            # see _closing) — cria re-reads it from the history the harness sends back. Nothing is
            # stored server-side; the harness owns the transcript, cria owns the content.
            briefing = _briefing_from_history(messages)
            if not initial_enabled:
                # PLAN-OFF: the whole task is ONE implicit step — synthesize a degenerate 1-item plan
                # and drive it through the single-item path (raw-task framing + the off-ramps). A
                # selected non-coding verdict is NOT ours — proxy it. When classification is
                # disabled, shared admission uses harness capabilities, not a synthetic verdict.
                # A live synthetic session (loaded above) skips this entirely.
                if not admission.starts_driver(body, classification, planning=False):
                    return None
                sess = _plan_off_session(_synthetic_plan(latest_user_text(messages)), briefing)
                # PERSISTENCE (Invariant 3, load-bearing): a stable ``sid:`` key persists + resumes;
                # an unstable ``task:`` key is EPHEMERAL — never ``put`` (re-synthesized each turn),
                # exactly as the plan-off path handed unstable keys a fresh state, so a synthetic session
                # can't leak across unrelated same-prompt conversations (the plan-cache-leak class).
                # A DEGENERATE plan is never mirrored to disk: it's just the raw task. One that gained
                # a reading step is a real plan and mirrors like any other.
                if _stable_session(session_key):
                    self._put_session(session_key, sess)
                else:
                    _pin_pilot_runtime(sess, self._ctx.pilot_runtime, bootstrap)
                    if bootstrap is not None:
                        self._store.drop_bootstrap(session_key)
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
                classified_task = admission.starts_driver(body, classification, planning=True)
                if rewritten and ((was_task and pure_handoff) or classified_task):
                    # Post-compaction continuation: plan the REMAINING work from the harness's summary
                    # via the rewrite frame — never as a fresh task, and never stacking cria's own
                    # briefing on top of the harness summary (two summaries drowned the planner →
                    # the placeholder plan). The summary is NOT always the root: on a harness that
                    # keeps the user messages, the root is still the original task and handing that
                    # over as "the summary" would ask the planner to re-plan the whole job from
                    # scratch, which is the one thing a continuation exists to avoid.
                    summary_text = _rewrite_summary_text(messages, root_text)
                    plan, outcome = self._plan_for(messages, rlog, rewrite_summary=summary_text,
                                                    session_key=session_key)
                    if plan is None:
                        deferred = self._defer_planner_survey(outcome, messages, body, session_key, rlog)
                        if deferred is not None:
                            return deferred
                        return self._decline_bootstrap(session_key,
                            bootstrap if bootstrap_finished else None, outcome)  # rewrite stays sticky
                    # The coder's protected prior-work context: cria's own briefing when we have one
                    # (compact, focused); else the harness summary TAIL, clipped — summaries put the
                    # current state / remaining work at the END, so the head is the droppable part.
                    sess = PlanSession(plan=plan, prior_work=briefing or summary_text)
                    self._put_session(session_key, sess)
                    self._store.clear_rewrite(session_key)  # acted on it
                    rlog.emit("loop.start", id=plan.id, steps=len(plan.items), continued=True, rewritten=True)
                    self._persist_plan(plan, rlog)
                else:
                    if not classified_task and not bootstrap_finished:
                        return None  # a pending rewrite (if any) stays pending for a later task turn
                    # A fresh planner has no synchronous harness channel. Survey a known harness root
                    # before its view-backed gather; no shell and rootless paths retain their old route.
                    view = wsview.current(_extract_cwd(messages) or None)
                    if not bootstrap_finished and view.root and not view.surveyed:
                        bootstrap = self._new_bootstrap(session_key, messages)
                        probe_tc = guard_gate_op(bootstrap, body, rlog,
                                                 workspace_root=bootstrap.workspace_root)
                        if probe_tc is not None:
                            bootstrap.probe_call_id = probe_tc["id"]
                            self._store.put_bootstrap(session_key, bootstrap)
                            rlog.emit("loop.survey_bootstrap_started")
                            return _completion_toolcalls([probe_tc])
                    # A follow-up on a FINISHED session starts from the completion-compaction of the
                    # prior plan (see loop.done), so the planner isn't blind to what it already built —
                    # it plans the new ask ON TOP of the done work, not from the latest sentence.
                    plan, outcome = self._plan_for(messages, rlog, prior_work=briefing,
                                                    session_key=session_key)
                    if plan is None:
                        # A planner read whose body is unknown has queued a wsview survey demand.
                        # It cannot receive that answer while this synchronous request is still
                        # gathering, so return ONE real harness command and start the planner over
                        # only after writeproxy applies its result on the next request.
                        deferred = self._defer_planner_survey(outcome, messages, body, session_key, rlog)
                        if deferred is not None:
                            return deferred
                        if outcome.survey_pending:
                            return None  # no shell means there is no delivery channel; do not fake an answer
                        # Planner gave nothing back even after its own re-draft retries. A gather-overrun
                        # (retriable) will re-plan next turn — let it. But a genuine give-up on a CODING task
                        # must NOT fall to the unguarded proxy (it freewheels and can stop with no reason):
                        # drive the whole task as ONE synthetic guarded step, keeping the gate/guards/steers.
                        if getattr(self._ctx.planner, "_retriable_failure", False) \
                                or not admission.starts_driver(body, classification, planning=False):
                            return self._decline_bootstrap(session_key,
                                bootstrap if bootstrap_finished else None, outcome)
                        sess = _plan_off_session(_synthetic_plan(latest_user_text(messages)), briefing)
                        if _stable_session(session_key):
                            self._put_session(session_key, sess)
                        else:
                            _pin_pilot_runtime(sess, self._ctx.pilot_runtime, bootstrap)
                            if bootstrap is not None:
                                self._store.drop_bootstrap(session_key)
                        rlog.emit("loop.start", id=sess.plan.id, steps=len(sess.plan.items), synthetic=sess.synthetic,
                                  planner_fallback=True)
                    else:
                        sess = PlanSession(plan=plan, prior_work=briefing)
                        self._put_session(session_key, sess)
                        rlog.emit("loop.start", id=plan.id, steps=len(plan.items), continued=bool(briefing))
                        self._persist_plan(plan, rlog)  # mirror to cria's OWN dir (never the workspace)

        # THE KEY WEBFETCH'S PER-SESSION GATES USE, recorded ONCE for both drivers.
        # It is the SAME key the loop drives under (server passes one `sk` to both drive() and the
        # outbound translation), so the search judge asks about exactly the prior those gates would
        # refuse against. It lived inside `_work` — the multi-item driver — which
        # `_plan_off_session` has not reached since 2026-08-19, so on every real run it stayed "".
        # Measured over 12 days: `loop.search_judge_skipped why="no query"` fired 11 times, 11 of 11
        # in synthetic sessions; `loop.search_rehunt_cleared` fired 10 times, 10 of 10 in the
        # non-synthetic sessions that no longer occur, and 0 since. Four readers degraded silently —
        # the rehunt judge, the search-read judge, the "cria chose this URL, not you" note (0 of 253
        # sessions ever carried it), and the spilled-search lookup (#23).
        sess.web_session = session_key

        # PLAN-OFF HAND-BACK: the reading step was the ONLY plan machinery plan-off is entitled to.
        # The moment the current item IS the raw task (the reading step verified, or was never
        # authored and a resume lands here), the session becomes the degenerate single-item drive —
        # raw-task framing, the plan-off off-ramps, no step cage. The flip is one-way and idempotent.
        if (sess.plan_off and not sess.synthetic
                and (cur := sess.plan.current()) is not None and cur.text == sess.plan.task):
            sess.synthetic = True
            rlog.emit("loop.plan_off_handback", id=sess.plan.id)

        if _semantic_owner is not None:
            _semantic_owner(sess)  # actual live owner, including never-persisted task: sessions
        if sess.synthetic:  # degenerate 1-item plan → the single-item driver (raw-task framing +
            # the off-ramps a finite multi-step plan doesn't need). Placed BEFORE the multi-item
            # awaiting_probe branch: the single-item path reads its own probe results internally.
            return self._drive_single_item(sess, body, session_key, rlog, rewritten=rewritten,
                                           rewrite_observation=rewrite_observation)

        if sess.awaiting_probe:  # hand genuine pending ownership to its reader before consuming it
            if sess.periodic_observation:
                sess.awaiting_probe = False
                out = self._periodic_observation_after_probe(sess, session_key, body, rlog)
            else:
                out = self._verify_after_probe(sess, session_key, body, rlog, rewritten=rewritten)
            self._store.clear_rewrite(session_key)  # consumed (probe re-issued or judged)
            return out

        self._store.clear_rewrite(session_key)  # live session: framing is rebuilt each turn anyway
        return self._work(sess, session_key, body, rlog, rewritten=rewritten)

    # ------------------------------------------------------------------ work

    def _coder_turn(self, sess: PlanSession, framed: dict, body: dict, *, step: int, rlog,
                    delivery_receipts=None) -> dict:
        try:
            completion = self._coder_turn_impl(sess, framed, body, step=step, rlog=rlog,
                                               delivery_receipts=delivery_receipts)
            if generation.incomplete(completion):
                raise _IncompleteCoderTurn(completion)
            return completion
        except UpstreamProtocolError as error:
            if delivery_receipts is not None:
                delivery_receipts.clear()
            error.coder_turn = True
            raise

    def _coder_turn_impl(self, sess: PlanSession, framed: dict, body: dict, *, step: int, rlog,
                         delivery_receipts=None) -> dict:
        """ONE guarded coder call — the shared core of BOTH driver halves (``_work`` multi-item and
        ``_drive_single_item`` synthetic/plan-off), so a coder-turn guard can NEVER land in one and
        silently miss the other (the divergence that killed the search-escape on the live path). The
        caller owns the framing (before) and the GATE (after — the ONE thing that legitimately differs:
        multi-step probe/`_verify` vs single `_gate_single_done`); this owns everything between:
        advertise the completion tool → call the coder → normalise a `task_complete` → rumination +
        truncation guards → banner/reasoning hygiene → selected outgoing search policy → shared write
        facts and a pending Source observation. Public retention owns observation/delivery and the required
        forwarded-call clock. Returns the guarded completion ({} on a decode failure — a
        no-tool 'done' the caller's gate then handles)."""
        # The context floor runs later, at the wire, where prose-based preamble detection is too
        # brittle to identify the real task. Carry the session's exact root task as an internal hint;
        # Upstream consumes and strips it before serialization.
        stalled_offer = sess.stalled_reply
        sess.stalled_reply = None
        framed[bodykeys.PINNED_TASK] = getattr(sess.plan, "task", "") or ""
        _add_completion_tool(framed)  # advertise the explicit-done tool for THIS coder call
        rlog.phase = f"coder-s{step}"  # label the call capture with the role + step
        sess.restored_current = {}      # credit is earned per call, from what the wire says it delivered
        pending_paste = sess.pasted_pending_nudge
        if pending_paste is not None and pending_paste.user_turn not in framed.get('messages', []):
            carried = ([{'role': 'assistant', 'content': pending_paste.carried_reply}]
                       if pending_paste.carried_reply else [])
            framed = {**framed, 'messages': list(framed.get('messages', [])) + carried
                      + [pending_paste.user_turn]}
        # The accepted request's evidence, BEFORE any generation, recovery or assist of this request is selected: a
        # refusal or answer that arrives with this history is settled now — an aborted reply forwards nothing, so
        # nothing after it would ever observe it. Idempotent; the forwarded-reply record repeats it harmlessly.
        _observe_history(sess, body.get('messages', []))
        source_chat = self._ctx.coder_chat
        image_context = _image_current.get()
        if image_context is not None:
            selected_provider = getattr(source_chat, 'upstream', None)
            selected_role = self._ctx.coder_role
            def image_chat(prepared, log):
                if not prepared.get('model'):
                    discover = getattr(selected_provider, 'loaded_model', None)
                    selected_model = discover(log) if callable(discover) else None
                    if selected_model:
                        prepared = {**prepared, 'model': selected_model}
                return image_context.workflow.chat(selected_provider, selected_role, prepared, image_context, log, call=source_chat)
            # Request-local wrapper: never mutate the shared LoopContext callable.
            selected_chat = image_chat
        else:
            selected_chat = source_chat
        replies = _CoderReplyReceipts(selected_chat, sess)
        coder = massage.apply(_parse_completion(replies.chat(framed, rlog)), framed.get("tools"), rlog)
        initial_receipt = dict(replies.latest)
        initial_remediation = replies.latest_remediation
        # Initial paste provenance must see what THIS coder actually received,
        # before any auxiliary judge can overwrite the shared log receipt.
        sess.restored_current = dict(initial_receipt)
        offered_paste = pending_paste
        consumed_paste = (offered_paste is not None
                          and offered_paste.user_turn in framed.get('messages', []))

        # BEFORE `_normalize_completion`: a turn that holds ANY call (a task_complete included) is not a
        # turn that pasted a file instead of writing it, and this must run ahead of every guard below so
        # a recovered write is tracked like a native one (truncation, write-streak, refusals).
        coder = self._recover_text_write(sess, coder, framed, body, rlog)
        coder = _normalize_completion(coder, rlog)  # a task_complete call → step 'done' (or dropped)
        replies.record(coder, initial_receipt, remediation=initial_remediation)
        coder = _generation_recovery(coder, framed, replies.chat, rlog,
                                     step=step, phase=f"coder-s{step}",
                                     coder_role=self._ctx.coder_role, gs=sess,
                                     on_completion=replies.record, accepted=body.get('messages', [])).completion
        # Credit follows this retained coder reply, never the last shared log
        # receipt (which auxiliary calls and unsuccessful retries can overwrite).
        sess.restored_current = replies.receipt(coder)
        _strip_completion_banners(coder)  # scrub cria's own banners the coder parroted
        if self._ctx.coder_role is not None:  # strip leaked reasoning from the coder's content when off
            _clean_completion(coder, self._ctx.coder_role)
        # Overlapping searches may earn a new-direction clearance; ordinary searches are untouched.
        # Existing L5 history applicability stays here. Stalled-work policy is separately
        # selected across its whole lifecycle; shared write facts and the forwarded-call clock
        # below are required even when that optional source is absent.
        if not coder.get(massage.LOST_CALL_KEY) and not coder.get(bodykeys.FENCED_REFUSED):
            pasted_result = self._pasted_redrive(sess, coder, body, rlog, step=step,
                                                plan_off=bool(sess.synthetic or sess.plan_off),
                                                consumed=offered_paste if consumed_paste else None)
            if pasted_result is not None and pasted_result.completion is not None:
                coder = pasted_result.completion
        if self._ctx.assists:
            coder = guard_search_query(sess, coder, body, self._ctx.reasoner_chat, self._ctx.reasoner_role,
                                       rlog, _defer=True)
            _track_fetched_pages(sess, body.get("messages", []))  # durable fetch facts for later steers
            _track_refused_names(sess, body.get("messages", []))  # …and coordinates the toolchain refused
            _track_read_files(sess, body.get("messages", []))     # …and the files it opened on disk
            _track_own_checks(sess, body.get("messages", []))     # …and its own re-runs of the gate's checks
        observation = None
        if _has_tool_calls(coder):
            messages = framed.get('messages', [])
            # The ONE registration of this forwarded reply, against the CANONICAL accepted history (the request
            # body before focus/trim/compaction reshaped what the model saw), never the framed copy.
            observed = _record_dispatch(sess, coder, body.get('messages', []))
            if self._ctx.assists:
                observation = _stalled_observation(sess, body.get('messages', []), rlog,
                                                  step=step, observed=observed, sequence_start=sess.action_seq,
                                                  write_messages=messages)
        definition = _stalled_selection(sess)
        steer = stalled_offer[3] if stalled_offer is not None else None
        count = sum(len((ch.get('message') or {}).get('tool_calls') or [])
                    for ch in coder.get('choices', []))
        sess.stalled_reply = (coder, definition, observation, steer, sess.action_seq, count)
        if consumed_paste:
            sess.pasted_consumed = (coder, offered_paste, self._pasted_selection(sess))
        if delivery_receipts is not None:
            delivery_receipts.append((coder, replies.remediation_receipt(coder)))
        return coder

    # -------------------------------------------------- a call cria did not run must be SAID

    def _refused_call_text(self, sess: PlanSession, body: dict, refused: dict) -> str:
        """The coder-facing fact for a fenced call massage refused to promote (``bodykeys.FENCED_REFUSED``):
        which call did not run and the rule that stopped it — plus, when the call named a file that
        exists and the coder has not read, that measured fact. A refusal nobody hears of is the reply
        regenerated byte for byte (phi4 A2 calls 0030/0031/0036/0037)."""
        labels = prompts.load_map("fenced_call_refused")
        tool, path = str(refused.get("tool") or "a tool"), str(refused.get("path") or "")
        reason = labels.get(str(refused.get("reason")), "")
        text = prompts.fill(labels["lead"], tool=f"`{tool}`",
                            at=prompts.fill(labels["at"], path=f"`{path}`") if path else "",
                            reason=prompts.fill(reason, tool=f"`{tool}`") if reason else "it did not qualify")
        root = getattr(sess, "workspace_root", None) or _extract_cwd(body.get("messages", []))
        fact = unread_target_fact(sess, wsview.current(root) if root else None, path,
                                  body.get("messages", [])) if path else ""
        return denial.mark(text + (f"\n\n{fact}" if fact else ""))

    def unread_target_check(self, sess_key: str, messages: list[dict], root):
        """``path -> fact`` for the write lowering, or None when this session does not keep the record
        (assists off: the read ledger is never filled, so "unread" would be a guess — #11b)."""
        if not self._ctx.assists or not root:
            return None
        # LAZY: this is built while the request is being set up, before `drive` has created the session on
        # a first turn; the lowering runs after it, so the lookup happens when a write is actually named.
        def check(path: str) -> str:
            sess = self._store.get(sess_key)
            if sess is None:
                return ""
            return unread_target_fact(sess, wsview.current(root), path, messages)
        return check

    def shrinking_write_services(self, sess_key: str, messages: list[dict], root, rlog):
        """Lazy factual/provider assembly; the selected source policy owns decisions."""
        if not any(d.policy.id == shrinkprotection.DEFINITION.policy.id
                   for d in self._ctx.pilot_runtime.definitions):
            return None
        if not self._ctx.assists or not root or self._ctx.reasoner_chat is None or self._ctx.reasoner_role is None:
            return None

        def session():
            sess = self._store.get(sess_key)
            if sess is None:
                return None
            return shrinkprotection.ShrinkSession(
                sess.first_survey_files, shrinkprotection.ShrinkState(sess.shrink_write_judged))

        def ask(question, *, phase, max_tokens, retry_off):
            return ask_closed(self._ctx.reasoner_chat, self._ctx.reasoner_role, question,
                              rlog, phase=phase, max_tokens=max_tokens, retry_off=retry_off)

        return shrinkprotection.ShrinkServices(session, lambda: wsview.current(root), ask, rlog)

    def shrinking_write_check(self, sess_key: str, messages: list[dict], root, rlog):
        """Compatibility entry for direct callers; production supplies typed services."""
        from functools import partial
        services = self.shrinking_write_services(sess_key, messages, root, rlog)
        return partial(shrinkprotection.check_write, services) if services is not None else None

    @staticmethod
    def _pasted_result(result):
        if (not isinstance(result, pastedfile.Result) or not isinstance(result.status, pastedfile.Status)
                or result.completion is not None and not isinstance(result.completion, dict)
                or result.prepared is not None and not isinstance(result.prepared, pastedfile.Prepared)
                or result.nudge is not None and not isinstance(result.nudge, pastedfile.Nudge)
                or result.delivery is not None and not isinstance(result.delivery, pastedfile.Delivery)
                or result.settlement is not None and not isinstance(result.settlement, pastedfile.Settlement)
                or result.status is pastedfile.Status.NUDGE and result.nudge is None):
            raise ValueError('Pasted file replacement must return a typed Result')
        return result

    def _pasted_state(self, sess):
        if getattr(sess, 'pasted_state_view', None) is None:
            sess.pasted_state_view = _PastedFileView(sess)
        return sess.pasted_state_view

    def _settle_pasted_results(self, sess, messages):
        definition = self._pasted_selection(sess)
        if definition is None:
            return
        state = self._pasted_state(sess)
        for message in messages:
            if message.get('role') != 'tool':
                continue
            cid = message.get('tool_call_id')
            delivery = sess.pasted_deliveries.get(cid)
            if delivery is None:
                continue
            text = str(message.get('content') or '')
            denied = denial.refused(message)
            landed = denial.landed(message)
            self._pasted_result(definition.settle(state, delivery, cid,
                ran=False if denied else True if landed else None, changed=False if denied else None))

    def _retain_pasted_reply(self, sess, retained, admitted_writes=None, *, prepared, consumed):
        definition = self._pasted_selection(sess)
        if definition is None:
            return
        state = self._pasted_state(sess)
        if sess.pasted_consumed is consumed:
            if consumed is not None and consumed[0] is retained and consumed[2] is definition:
                self._pasted_result(definition.nudge_delivered(state, consumed[1], consumed=consumed[1]))
            sess.pasted_consumed = None
        if prepared is None or state.prepared is not prepared:
            return
        kept = []
        root = getattr(sess, 'workspace_root', None) or ''
        for choice in (retained or {}).get('choices', []):
            for call in (choice.get('message') or {}).get('tool_calls') or []:
                cid = call.get('id')
                if cid not in prepared.call_ids:
                    continue
                if admitted_writes is not None:
                    fact = admitted_writes.get(cid)
                    admitted = (fact is not None and fact.content == prepared.content
                                and posixpath.normpath(fact.path) == posixpath.normpath(
                                    posixpath.join(root, prepared.path)))
                else:
                    fn = call.get('function') or {}
                    args = _args_of(fn.get('arguments'))
                    admitted = (fn.get('name') in writeproxy_names
                                and args.get('content', args.get('contents')) == prepared.content
                                and posixpath.normpath(_write_path(fn) or '') == posixpath.normpath(
                                    posixpath.join(root, prepared.path)))
                if admitted:
                    kept.append(call)
        result = definition.forwarded(state, prepared,
            {'choices': [{'message': {'tool_calls': kept}}]})
        self._pasted_result(result)

    def _pasted_evidence(self, sess):
        return pastedfile.Evidence(_completion_text, _has_tool_calls,
            lambda messages: _injected_fence_texts(sess, messages), wsview.current, _extract_cwd,
            lambda messages: _history_root(messages)[0], _subject_is_exact_in_quote,
            lambda view, rel, messages: _coder_has_seen(view, rel, sess, messages),
            lambda view, rel, messages: unread_target_fact(sess, view, rel, messages))

    def _pasted_selection(self, sess):
        runtime = getattr(sess, 'pilot_binding', None) or self._ctx.pilot_runtime
        return runtime.pasted_file

    def _pasted_redrive(self, sess, completion, body, rlog, *, step=None, plan_off=False,
                        consumed=None):
        definition = self._pasted_selection(sess)
        if definition is None:
            return None
        result = definition.redrive(pastedfile.NudgeInput(completion, body.get('messages', []),
            self._pasted_evidence(sess), sess, rlog,
            reading_step=False if plan_off else _is_reading_step(sess, sess.plan.current()),
            step=step, plan_off=plan_off, defer_unread_consumption=True,
            consumed=consumed), self._pasted_state(sess))
        return self._pasted_result(result)

    @staticmethod
    def _pasted_followup(sess, completion):
        pending = sess.pasted_pending_nudge
        consumed = sess.pasted_consumed
        # Pending retains a transport obligation even after its coder frame ran.
        # Re-enter only for a fresh offer, never to consume that same frame again.
        if consumed is not None and consumed[0] is completion and consumed[1] is pending:
            return None
        return pending

    def _pasted_file_unsaved(self, sess: PlanSession, reply: str, body: dict) -> bool:
        # Compatibility query only; production admission and budget live in redrive.
        if self._pasted_selection(sess) is None:
            return False
        other, sess.pasted_block_other = sess.pasted_block_other, False
        return not other and pastedfile.unsaved_text(reply, _injected_fence_texts(sess, body.get('messages', [])))

    def _unexecuted_nudge_text(self, sess: PlanSession, reply: str = '') -> str:
        pending = sess.pasted_pending_nudge
        return pending.text if pending is not None else ''

    # -------------------------------------------------- a file typed into chat → the write it should have been

    def _recover_text_write(self, sess: PlanSession, comp: dict, framed: dict, body: dict, rlog) -> dict:
        """A call-less turn that PASTED a whole file under the file's name becomes that file's write.

        phi4 cannot reliably emit a tool call whose argument holds newlines (the fleet's own
        verification recorded the native write_file failures), so it writes the file in chat — and the
        `unexecuted_write` nudge, which asks it to send the same content as a call, has never got a call
        out of it (A1 run, calls 0022-0038: four replies, one class, no write). This takes the model's
        OWN text and re-shapes it into the call it meant: principle 2 allows nothing more — cria
        writes no code, picks no file, invents no change.

        WHY HERE, AND NOT IN THE MASSAGE CHAIN. Two facts are needed that `massage.apply` does not have:
        the workspace view (to resolve the model's words to ONE real path) and a judge (to settle
        whether the fenced block is the WHOLE file or an excerpt — the same reply carries a 5-line
        `<dependency>` snippet for pom.xml and a 100-line class, and a length/overlap rule for that
        is the semantic-in-code principle 8 forbids). `_coder_turn` is the shared core of both drivers
        and runs the guards after it, so the write is held to everything a native one is
        (`massage.promote_call` replays the lowering passes).

        EVERY GATE IS A REFUSAL, and a refusal is exactly today's behaviour (the nudge). In order:
        a reasoner exists; the turn holds no call, was not cut at the cap, and is not a reading step;
        the reply holds no fenced call object (its actions are already expressed as calls — the
        fenced-envelope recovery refused them, and a second reading would contradict it); the FIRST
        eligible block is closed, at least `UNEXECUTED_WRITE_LINES` long (what the nudge already calls
        "a file, not a snippet"), and the line directly above it names exactly one path; that path is
        ONE file in the workspace view (exact, else a unique suffix/basename match over a complete
        listing) — or a new file whose name the TASK itself contains; the block is neither a quote of
        something the coder was shown nor already the file's content; and the judge answers the
        exact positive token. Only that one block is promoted; the tail (further blocks, invented
        results, a completion claim) is not forwarded and is counted in the event."""
        definition = self._pasted_selection(sess)
        if definition is None:
            return comp
        ask = None
        if self._ctx.reasoner_chat is not None and self._ctx.reasoner_role is not None:
            def ask(question, *, phase, max_tokens, retry_off):
                return ask_closed(self._ctx.reasoner_chat, self._ctx.reasoner_role, question, rlog,
                                  phase=phase, max_tokens=max_tokens, retry_off=retry_off)
        result = definition.execute(pastedfile.RecoveryInput(comp, framed.get('tools'),
            body.get('messages', []), getattr(sess.plan, 'task', '') or '',
            getattr(sess, 'workspace_root', None), _is_reading_step(sess, sess.plan.current()),
            self._pasted_evidence(sess), ask, rlog), self._pasted_state(sess))
        result = self._pasted_result(result)
        return result.completion if result.completion is not None else comp

    def _work(self, sess: PlanSession, key: str, body: dict, rlog, rewritten: bool = False) -> dict:
        # Persist the harness's workspace cwd on the SESSION: a fresh <cwd> updates it, a turn without one
        # (harness compaction) keeps the last-known, and an operator-configured LoopContext root is the
        # final fallback — so the gate/steer target the harness's repo, never cria's own dir. (_ctx.
        # workspace_root is shared across sessions/None in prod; the per-session copy is the live source.)
        sess.workspace_root = _extract_cwd(body.get("messages", [])) or sess.workspace_root or self._ctx.workspace_root
        body = {**body, "messages": self._judge_search_reads(sess, body, rlog)}  # strip off-target search reads
        if sess.done_probe:
            settled = self._settle_task_done_probe(sess, body, key, rlog,
                                                  plan_off=False, rewritten=rewritten)
            if settled is not None:
                return settled
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
                recovered = _reissue_repository_checks(_NamedProbeState(sess, "completion_probe_id"),
                    body, rlog, workspace_root=sess.workspace_root, rewritten=rewritten)
                if recovered.call is not None:
                    return _repository_completion(recovered)
                transport_tc = guard_gate_transport(
                    sess, body, rlog, call_id=sess.completion_probe_id)
                if transport_tc is not None:
                    sess.completion_probe_id = transport_tc["id"]
                    return _completion_toolcalls(
                        [transport_tc], note="verifying — receiving the repo's complete check output")
                sess.probe_call_id, sess.completion_probe_id = sess.completion_probe_id, ""
                sess.probe_reissues = sess.probe_poll_reissues = 0
                errors = guard_gate_verdict(sess, body, rlog)
                if sess.gate_replan_required:
                    probe_tc = guard_gate_replan_after_survey(
                        sess, body, rlog, workspace_root=sess.workspace_root)
                    if probe_tc is not None:
                        sess.completion_probe_id = sess.probe_call_id = probe_tc["id"]
                        return _completion_toolcalls(
                            [probe_tc], note="verifying — running the repo's checks")
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
                    steer = (errors if getattr(sess.gate_plan, "transport_error", "") else
                             prompts.render("gate_fail_steer", errors=errors))
                    return self._renudge(sess, key, body, steer, rlog)
            elif not sess.gate_fresh:
                probe_tc = _requested_repository_probe(sess, body, rlog, workspace_root=sess.workspace_root)
                if probe_tc is not None:
                    sess.completion_probe_id = sess.probe_call_id = probe_tc["id"]
                    rlog.emit("loop.completion_probe", plan_off=False)
                    return _completion_toolcalls([probe_tc], note="verifying — running the repo's checks")
                # no shell tool → the objective gate can't run; the judge below decides alone (fail-open)
            reason = self._reopen_if_unsatisfied(sess, body, rlog)
            if reason is not None:
                # not satisfied → a corrective step is now current; re-drive it (don't complete green-but-wrong)
                return self._work(sess, key, body, rlog)
            # `_reopen_if_unsatisfied` normally cannot return None after a false verdict. Keep
            # the final funnel explicit nonetheless: a completion, briefing, or compactor must
            # never be reachable through a future caller that forgets that contract. The existing
            # bounded plan-on exit remains the one deliberate exception.
            if _satisfaction_blocks_completion(sess, bounded=True):
                return self._renudge(sess, key, body, prompts.render(
                    "done_incomplete",
                    reason=str(getattr(sess, "latest_satisfaction_evidence", "") or prompts.load("done_no_named_gap")),
                    check_state=_check_state_words(sess)), rlog)
            sess.phase = Phase.DONE
            sess.plan.status = "done"
            # Completion compaction: summarize the FINISHED work into a briefing and embed it in
            # the CLOSING MESSAGE — the briefing rides in the conversation (the harness stores it,
            # its compactor summarizes from it, cria re-reads it from history on a follow-up).
            # Never stored server-side; no cross-conversation leak possible. Only the one-bit
            # `done` marker lands in the shape (stable keys), for the post-compaction bypass.
            briefing = self._compact_done(sess, body, rlog)
            closing = self._closing(sess, briefing)
            if _stable_session(key):
                self._store.mark_done(key)
            self._store.drop(key)
            rlog.emit("loop.done", id=sess.plan.id)
            return _completion_final(closing)

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
        review = self._review_task(sess, body, rlog, trigger=ReviewTrigger.PLAN_EXHAUSTED)
        satisfied, reason, fix_action = review.approved, review.reason, review.action
        rlog.emit("loop.done_critic", plan_off=False, satisfied=satisfied, check=sess.completion_checks)
        if satisfied:
            return None
        sess.completion_checks += 1
        reason = reason or prompts.load("done_no_named_gap")
        # The STEP is the judge's proposed ACTION, not its verdict essay: the old framing+reason+fix
        # paragraph became a step verbatim and pinned a run for 118 calls (0729-mellum2) — carrying
        # literal {{…}} braces the coder shipped into a URL, and "or fallback on…" advice. The essay
        # still reaches the coder through the nudge below; the plan gets only something DOABLE. And
        # the accepted action is the same typed value already used in the coder nudge below.
        # NO ACTION, NO STEP. The comment above states the rule — "the plan gets only something
        # DOABLE" — and `or reason` broke it: with no proposed_fix, the judge's VERDICT ESSAY became
        # the plan step, which is the exact shape that pinned a run for 118 calls. Measured over the
        # 19 distinct corrective steps in the captures, 2 are essays; one of them is
        # "So the task is NOT satisfied because: 1. resolve_handle.py … are not in the workspace",
        # appended as a step in the same prompt where cria's own disk read listed those files as
        # present. The essay still reaches the coder — through `nudge_reason` below, which is the
        # channel built for it.
        step_text = fix_action
        if not step_text:
            rlog.emit("loop.completion_fix_absent", level="info", head=_clip(reason, 120))
        else:
            fix = PlanItem(text=_COMPLETION_FIX_PREFIX + step_text)
            if (sess.plan.items and sess.plan.items[-1].text.startswith(_COMPLETION_FIX_PREFIX)
                    and not sess.plan.items[-1].done):  # a DONE corrective step is history, not a slot
                sess.plan.items[-1] = fix      # reuse the one corrective step across re-checks (no plan bloat)
            else:
                sess.plan.items.append(fix)
        sess.plan.status = "in_progress"
        sess.nudge_reason = prompts.render("done_incomplete", reason=reason,
                                           check_state=_check_state_words(sess))
        sess.steer_source = "completion critic (task not fully done)"
        self._persist_plan(sess.plan, rlog)
        return reason

    def _work_item(self, sess: PlanSession, key: str, body: dict, rlog, item, idx: int) -> dict:
        runtime = assistruntime.current()
        act_first = (runtime.completion_act_first if self._ctx.planner_enabled
                     and runtime.engagement_level >= 5 else None)
        # A remediation is released only by the harness's successful result for the exact typed
        # subject, never by the model proposing a write or by a turn that merely inspected it.
        _settle_completion_remediation(sess, body.get("messages", []), rlog)
        _nudge_after_remediation_nonwrite(sess, body.get("messages", []), rlog)
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
        # LEVEL 5 — ASSISTS_ENABLED. The periodic gate is SCHEDULED: a turn counter fires it and the
        # model asked for nothing, which is the same trigger test that puts the periodic satisfaction
        # check at level 5 (see LoopContext.assists). The gate MACHINERY is shared with the level-4
        # completion probe; what decides the rung is who started it.
        if self._ctx.assists:
            periodic = guard_periodic_gate(sess, body, rlog, workspace_root=sess.workspace_root,
                driver=repositorychecks.Driver.STEP, steer=sess.nudge_reason, step=idx)
            if periodic is not None:
                return periodic
        # PERIODIC STEP CHECK. A step moves only when the coder volunteers "done". Ask the real critic
        # on a cadence so a step cannot outlive the run (see the method — additive, fail-closed, same
        # authority).
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
        # LEVEL 5 — ASSISTS_ENABLED. This check is SCHEDULED: a turn counter fires it, the model
        # asked for nothing, and cria volunteers what it thinks is missing. The trigger decides the
        # rung (see LoopContext.assists), so the level is weighed HERE rather than inside the check —
        # `_periodic_satisfaction` has a deliberate contract that `blocked` is its first word, tested
        # against a Loop with no context at all, and a gate in front of that would break it.
        blocker = _satisfaction_blocker(steer=sess.nudge_reason, rewritten=False,
                                        done_probe=sess.done_probe, gate_red=sess.last_gate_red,
                                        gate_stall=sess.gate_stall)
        done_now = None if not self._ctx.assists else self._periodic_satisfaction(
            sess, body, rlog, plan_off=False, blocked=blocker)
        if done_now is not None:
            return done_now
        # A current task-named file absence needs action ownership before the plan cursor is framed.
        # This is a bounded, non-terminal observer with an independent cadence: it neither clears a
        # red gate nor waits for the completion critic to be unblocked.  A pending ordinary steer is
        # deliberately replaced only by a provenance-validated remediation, so the final body has one
        # owner rather than a cursor plus two competing directives.
        diagnosis = assistruntime.current().completion_diagnosis
        if self._ctx.assists and diagnosis is not None:
            observed = diagnosis.observe_scheduled(completiondiagnosis.ScheduledObservationInput(
                sess.plan.task, sess.drive_count, self._ctx.satisfaction_check_start,
                self._ctx.satisfaction_check_every,
                bool(sess.workspace_root and self._ctx.reasoner_chat is not None)), sess,
                _diagnosis_lifecycle_services(diagnosis, sess.workspace_root or "",
                    self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog))
            if not isinstance(observed, completiondiagnosis.ObservationRun):
                raise TypeError("scheduled diagnosis hook must return ObservationRun")
            completiondiagnosis._diagnosis_result(observed.diagnosis)
            completiondiagnosis._remediation_result(observed.delivery,
                (completiondiagnosis.RemediationStatus.NOT_APPLICABLE, completiondiagnosis.RemediationStatus.DELIVERED))
        record_coder_preframe(rlog, sess, item, idx, total, driver="plan_on")
        remediation = bool(sess.completion_remediation_subject)
        msgs = []  # current notes are never offered to historical reducers
        steered = ""
        if (sess.nudge_reason and not (sess.living_effects is not None
                and sess.living_effects[1].clear_nudge)):  # a selected rescue replaces this offered nudge
            if sess.nudge_reply:  # the reply the nudge refers to rides in front of it, as itself
                msgs = msgs + [{"role": "assistant", "content": sess.nudge_reply}]
                sess.nudge_reply = ""
            # The remediation evidence is re-injected below from its durable owner, rather than
            # relying on this one-shot nudge slot.
            if sess.nudge_reason != sess.completion_remediation_reason:
                msgs = msgs + [{"role": "user", "content": prompts.render("nudge", reason=sess.nudge_reason)}]
            sess.nudge_reason = ""
            steered, sess.steer_source = sess.steer_source, ""  # set only for a GUARD steer, not a verify re-nudge
        if remediation:
            msgs = msgs + [{"role": "user", "content": prompts.render(
                "nudge", reason=sess.completion_remediation_reason)}]
        framed, _ = self._prepare_coder_context(sess, body, rlog, synthetic=False,
            index=idx, total=total, item=item.text, notes=msgs)
        _stalled_frame(sess, framed, msgs)
        rlog.emit("loop.item", step=idx, total=total, text=item.text)

        delivery_receipts = [] if remediation and diagnosis is not None else None
        coder = self._coder_turn(sess, framed, body, step=idx, rlog=rlog,
                                  delivery_receipts=delivery_receipts)  # shared retained coder reply
        if steered:  # no hidden guards: surface WHICH guard steered the coder (same note as plan-off)
            _add_note(coder, f"steered the coder — {steered}")
        if _has_tool_calls(coder):
            sess.step_tool_calls += 1  # the coder ACTED this step (the did-real-work leg's signal)
            sess.gate_fresh = False    # independent required evidence freshness
            thrash = self._replan_if_thrashing(sess, key, body, idx, rlog)  # tool-call thrash escape
            if thrash is not None:
                return thrash
            if (delivery_receipts and delivery_receipts[-1][0] is coder
                    and delivery_receipts[-1][1] == sess.completion_remediation_subject):
                _record_remediation_delivery(sess, coder)
            return _forward_acting_coder(sess, coder)  # accepted after the thrash decision

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
        refused = coder.pop(bodykeys.FENCED_REFUSED, None)
        if refused and sess.unexecuted_nudges < MAX_UNEXECUTED_NUDGES:
            sess.unexecuted_nudges += 1
            rlog.emit("loop.fenced_call_refused_said", step=idx, reason=refused.get("reason"),
                      tool=refused.get("tool"), attempt=sess.unexecuted_nudges)
            sess.nudge_reply = "" if massage.is_truncated(coder) else _completion_text(coder)
            return self._renudge(sess, key, body, self._refused_call_text(sess, body, refused), rlog)
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
        pasted_nudge = self._pasted_followup(sess, coder)
        if pasted_nudge is not None:
            sess.nudge_reply = pasted_nudge.carried_reply
            return self._renudge(sess, key, body, pasted_nudge.text, rlog)
        redrive = (act_first.execute(completionredrive.Input(
            completionredrive.Authority.STEP, sess.step_tool_calls, sess, rlog, idx))
            if act_first is not None else None)
        if redrive is not None:
            if not isinstance(redrive, completionredrive.Result):
                raise ValueError('Completion act-first replacement must return Result')
            return self._renudge(sess, key, body, redrive.text, rlog)
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
        participation_facts = participation.render_for_judge(
            getattr(sess, "last_gate_participation", None),
            fresh=getattr(sess, "gate_fresh", None))
        verification = self._verify(item.text, _completion_text(coder), "", evidence, rlog, idx=idx, total=total, key=key,
                                  coder_tools=_coder_tools_summary(body.get("tools")),
                                  routes=known_routes(body.get('messages', []), sess),
                                  sources_read=research.sources_read(
                                      _extract_fetches(body.get('messages', [])), body.get('messages', [])),
                                  workspace_root=sess.workspace_root or "",
                                  gate_red=bool(sess.last_gate_red),
                                  messages=body.get("messages", []), sess=sess,
                                  participation_facts=participation_facts, original_task=sess.plan.task)
        if getattr(verification, 'step_result', None) is not None:
            return self._consume_step_result(sess, key, body, idx, total, rlog, verification)
        ok, reason = verification
        if ok:  # standalone verifier-double compatibility only
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
        selection = researchpolicies.current()
        if selection.spill is None:
            return msgs
        provider_log = rlog  # provider calls require phase/capture state, not an emit-only adapter
        rlog = policy_log(rlog, selection.spill.policy)
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
        # THE QUERY COMES FROM THE RECORD OF THE SPILL, not from re-reading cria's own sentence about
        # it. `webfetch` wrote the file and knew the query at that moment; see the note on
        # `_SEARCH_SPILLED`.
        q_of = {_search_key(f): q
                for f, q in webfetch.spilled_search_files(sess.web_session).items()}
        state = researchpolicies.SpillState(sess.judged_search_files,
                                            sess.poisoned_search_files,
                                            sess.search_recommend)

        def ask(task, query, results):
            _q, on_target, recommendation = judge_search(
                self._ctx.reasoner_chat, self._ctx.reasoner_role, task, query, results, provider_log,
                coder_tools=_coder_tools_summary(body.get("tools")))
            return researchpolicies.SpillVerdict(on_target, recommendation)

        def protected(task, results):
            veto = _results_name_the_tasks_host(task, results)
            if veto:
                rlog.emit("loop.search_poison_refused", level="info", file=f)
            return veto

        out: list[dict] = []
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "tool" and read_file_of.get(m.get("tool_call_id")):
                f = read_file_of[m.get("tool_call_id")]
                key = "content" if m.get("content") is not None else "output"
                path_key = _search_key(f)
                was_poisoned = path_key in state.poisoned
                settled = selection.spill_read(researchpolicies.SpillInput(
                    path_key, lambda: q_of.get(path_key, ""),
                    lambda: search_file_text(sess.workspace_root, f),
                    lambda: latest_user_text(msgs), ask, protected), state)
                sess.search_recommend = state.recommendation
                if settled.reason:
                    rlog.emit("loop.search_judge_skipped", level="info", file=f, why=settled.reason)
                if settled.effect is researchpolicies.Effect.POISONED:
                    if not was_poisoned:
                        rlog.emit("loop.search_read_poison", file=f, rec=settled.recommendation)
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
                    steer = (f" Search instead for: {settled.recommendation}."
                             if settled.recommendation else "")
                    out.append({**m, key: prompts.render("search_read_denied",
                                                         marker=denial.DENIED_MARKER, steer=steer, file=f)})
                    continue
            out.append(m)
        return out

    def _self_compact(self, msgs: list[dict], sess: PlanSession, idx, rlog, *, force: bool = False,
                      pinned_task: str | None = None, protected_prefix: bool = False,
                      frame_tokens: int = 0) -> list[dict]:
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
        selected = next(iter(assistruntime.current().bindings(selfcompact.DEFINITION.policy.stage)), None)
        if selected is None:
            return msgs
        chat_fn = self._ctx.compactor_chat or self._ctx.reasoner_chat
        role = self._ctx.compactor_role or self._ctx.reasoner_role
        inventory_for_writer = workspace_inventory(sess.workspace_root or "", flavor="briefing")
        inventory_for_coder = workspace_inventory(sess.workspace_root or "", flavor="coder")
        gate_plan = getattr(sess, "gate_plan", None)
        gate_flag = (getattr(sess, "last_gate_flag", "") or "").strip()
        checks_fact = selfcompact.checks_input(gate_flag, gate_age(sess))
        root_task = (pinned_task if pinned_task is not None
                     else (getattr(sess.plan, "task", "") or ""))
        task_fact = (prompts.render("compaction_task_fact", task=root_task.strip())
                     if root_task.strip() else "")

        def evidence_for(mm: list[dict], *, newer_messages: list[dict]):
            # One public-content producer for both scopes and both readers. Grounding
            # qualifies the replacement work; it never expands what compact() covers.
            history = selfcompact.compaction_request_parts(
                mm, gate_plan=gate_plan, newer_messages=newer_messages)
            evidence = selfcompact.compaction_request_parts(
                mm, inventory_for_writer, gate_plan, gate_flag, gate_age(sess),
                newer_messages=newer_messages)
            if task_fact:
                # The pinned task was deliberately excluded from ``mm`` so it survives verbatim in
                # the coder view. That also made the briefing writer blind to it: both failed L5
                # cells repeatedly redefined the task as fixing the latest compiler/module blocker.
                history.append(task_fact)
                evidence.append(task_fact)
            return history, evidence

        def apply_role(body):
            if role is not None:
                role.apply(body, internal=True, rlog=rlog)
        # Evidence too big for one writer request is distilled in pieces (handoffdistill), not
        # dropped by the floor. The validators below still read the full transcript.
        distill = handoffdistill.binder(chat_fn, handoffdistill.window_of(chat_fn, rlog),
                                        ROLLUP_MAX_TOKENS, apply_role, rlog)

        def writer_evidence(history, evidence):
            turns = len(history) - (1 if task_fact else 0)
            return distill(evidence, turns) if distill is not None else evidence

        def make_summary(mm: list[dict], *, newer_messages: list[dict]) -> str:
            history, evidence = evidence_for(mm, newer_messages=newer_messages)
            evidence = writer_evidence(history, evidence)
            candidate = summarize(
                chat_fn, role, prompts.load("selfcompact_summary"),
                selfcompact.compaction_ask(), rlog,
                phase="self-compact", max_tokens=ROLLUP_MAX_TOKENS,
                evidence_blocks=evidence)
            if not validate_compaction_briefing(
                    chat_fn, role, candidate, files=inventory_for_writer, checks=checks_fact,
                    transcript_blocks=history, task=root_task, rlog=rlog,
                    system1=self._ctx.system1):
                return ""
            # Deterministic existence correction remains a final additive defense. The semantic
            # symbol matcher is deliberately gone: whether compiler output refutes a briefing is a
            # judgment, now made by the focused validator above rather than token containment.
            return (_briefing_disk_truth(candidate, inventory_for_coder, rlog)
                    + _briefing_gate_ground_truth(sess))

        def refold_summary(text: str, *, newer_messages: list[dict]) -> str:
            # The accumulated summary is model-authored replacement work, not a
            # fresh source of execution truth. Refolding gets the same newer scope.
            refold_history, refold_evidence = evidence_for(
                [{"role": "assistant", "content": text}], newer_messages=newer_messages)
            refold_evidence = writer_evidence(refold_history, refold_evidence)
            candidate = summarize(chat_fn, role, prompts.load("selfcompact_refold"),
                                  _ASK_USER_TURN, rlog, phase="self-compact-refold",
                                  max_tokens=ROLLUP_MAX_TOKENS, evidence_blocks=refold_evidence)
            if not validate_compaction_briefing(
                    chat_fn, role, candidate, files=inventory_for_writer, checks=checks_fact,
                    transcript_blocks=refold_history, task=root_task, rlog=rlog,
                    phase="compaction-refold-validate", system1=self._ctx.system1):
                return ""
            return candidate

        result = selected.execute(selfcompact.RollingInput(
            msgs, make_summary, trigger_tokens=self._ctx.trigger_compaction, force=force,
            # Asked by the engine about the view it would SEND without a new summary, not about the
            # raw history in ``msgs`` (which only grows, so it read as overflow on every later turn).
            floor_pressure=lambda view: self._floor_would_drop(view, rlog, frame_tokens),
            # Common preparation holds required authority outside this historical scope.
            # Standalone compatibility callers still ask the source to publish its task frame.
            # The writer's task_fact above is grounding in either case, not output authority.
            pinned_task="" if protected_prefix else root_task,
            # The coder-flavored files list (operator's design): the compacted view carries the LIST
            # of what exists; read_file is the road back to any content.
            files_list=inventory_for_coder,
            # The RARE fold-of-the-accumulated-summary is independently validated before adoption.
            refold=refold_summary,
            rlog=rlog, with_grounding=True), sess.compact_state)
        sess.compact_state = result.state
        if idx is not None:
            sess.compact_pending = result.force_pending
        if result.applied:
            rlog.emit("context.self_compact", reshape="compact", step=idx, before=len(msgs),
                      after=len(result.messages), boundary=force)
        return result.messages

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
            sess.awaiting_probe = False
            return self._work(sess, key, body, rlog)
        idx = sess.plan.items.index(item) + 1
        total = len(sess.plan.items)
        if sess.periodic_probe:  # M2 parity: a mid-step PERIODIC check-in, NOT a completion gate. Inject any
            # ground-truth error and keep working; NEVER advance the step (the coder didn't claim done). A
            # CLEAN check-in stays silent (guard_periodic_result returns None), so this can't complete a step.
            result = _resume_repository_checks(sess, body, rlog,
                driver=repositorychecks.Driver.STEP, rewritten=rewritten, step=idx,
                reasoner_chat=self._ctx.reasoner_chat, reasoner_role=self._ctx.reasoner_role,
                workspace_root=sess.workspace_root)
            if result.call is not None:
                note = (f"receiving complete check output for step {idx}/{total}"
                        if result.pending_kind is repositorychecks.PendingKind.PAGE
                        else f"periodic check-in for step {idx}/{total} — running checks")
                return _completion_toolcalls([result.call], note=note)
            truth = result.text
            return self._renudge(sess, key, body, truth, rlog) if truth else self._work(sess, key, body, rlog)
        probe = _read_tool_result(body.get("messages", []), sess.probe_call_id)
        recovered = _reissue_repository_checks(sess, body, rlog,
            workspace_root=sess.workspace_root, driver=repositorychecks.Driver.STEP,
            step=idx, rewritten=rewritten)
        if recovered.call is not None:
            note = (f"receiving complete check output for step {idx}/{total} (history was compacted)"
                    if recovered.pending_kind is repositorychecks.PendingKind.REWRITE_POLL
                    else f"re-running checks for step {idx}/{total} (history was compacted)")
            return _completion_toolcalls([recovered.call], note=note)
        transport_tc = guard_gate_transport(sess, body, rlog)
        if transport_tc is not None:
            sess.awaiting_probe = True
            return _completion_toolcalls(
                [transport_tc], note=f"receiving complete check output for step {idx}/{total}")
        sess.awaiting_probe = False  # recovery/checked paging ended; consume the actual pending read
        sess.probe_reissues = sess.probe_poll_reissues = 0  # a result (or the capped fallback) resolves the streak

        # Interpret the gate output through the ported probe modules (floor + probes + git).
        outcome = read_gate(sess.gate_plan, probe, rlog)
        # Guard-probe result (repetition redirect / wheel-spin ground truth) — shared with the
        # plan-off path via guard_probe_steer; the loop supplies its reasoner to author the redirect.
        # It records the reading itself (record_gate_state) before returning, so this early return
        # no longer discards a gate that the guard happened to be reading on the same turn.
        guard_ticket = sess.stalled_probe
        steer = guard_probe_steer(sess, body, rlog, step=idx, author=self._probe_author)
        if steer is not None:
            return self._renudge(sess, key, body, steer, rlog)
        if guard_ticket is not None:
            # A guard reading never becomes a volunteered completion check merely
            # because the selected settlement withheld its optional intervention.
            return self._work(sess, key, body, rlog)
        # The reading is state whichever way this turn goes. Captured BEFORE the mirror overwrites it,
        # because the stall signal is "the same finding as last time" and comparing the new flag with
        # itself is always true.
        prev_flag = sess.last_gate_flag
        record_gate_state(sess, outcome, gate_error_text(outcome), rlog, body.get("messages"))
        if sess.gate_replan_required:
            probe_tc = guard_gate_replan_after_survey(
                sess, body, rlog, workspace_root=sess.workspace_root)
            if probe_tc is not None:
                sess.awaiting_probe = True
                sess.probe_call_id = probe_tc["id"]
                return _completion_toolcalls(
                    [probe_tc], note=f"verifying step {idx}/{total} — running checks")
        participation_facts = participation.render_for_judge(
            getattr(outcome, "participation", None), fresh=getattr(sess, "gate_fresh", None))
        if not outcome.ran:
            # The script never ran (harness declined / no markers). Don't wedge — the pre-existing
            # fail-open: the critic still judges. A broken transport is distinct: the check did run,
            # but its evidence is UNKNOWN, which must never be logged or described as a pass.
            unknown = bool(getattr(outcome, "transport_unknown", False))
            rlog.emit("loop.probe", step=idx, passed=not unknown, gate_ran=False,
                      transport_unknown=unknown)
            digest = gate_error_text(outcome) if unknown else prompts.load("probe_digest_none")
            evidence = self._grounded_evidence(sess, body, rlog)
            verification = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key,
                                      probe_unknown=unknown,
                                      coder_tools=_coder_tools_summary(body.get("tools")),
                                      routes=known_routes(body.get('messages', []), sess),
                                      sources_read=research.sources_read(
                                          _extract_fetches(body.get('messages', [])), body.get('messages', [])),
                                      workspace_root=sess.workspace_root or "",
                                      gate_red=bool(sess.last_gate_red),
                                      messages=body.get("messages", []), sess=sess,
                                      participation_facts=participation_facts, original_task=sess.plan.task)
            if getattr(verification, 'step_result', None) is not None:
                return self._consume_step_result(sess, key, body, idx, total, rlog, verification)
            ok, reason = verification
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
            rlog.emit("loop.gate_stalled", level="warn", step=idx)
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
        # The plan-ON extras on top of the shared mirror (record_gate_state, called above with the
        # reading): the repo-wide regression check, which needs the report and only makes sense on a
        # gate that came back GREEN.
        if not sess.last_gate_red and (lost := passing_test_regression(sess, outcome.report)):
            sess.nudge_reason = sess.nudge_reason or lost
            rlog.emit("loop.tests_regressed", level="warn", step=idx,
                      command=sess.last_regression[0], high=sess.last_regression[1],
                      now=sess.last_regression[2])
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
        verification = self._verify(item.text, sess.pending_coder_text, digest, evidence, rlog, idx=idx, total=total, key=key,
                                  probe_ran=True, probe_blocked=nudge is not None, probe_repair=nudge or '',
                                  coder_tools=_coder_tools_summary(body.get("tools")),
                                  routes=known_routes(body.get('messages', []), sess),
                                  sources_read=research.sources_read(
                                      _extract_fetches(body.get('messages', [])), body.get('messages', [])),
                                  workspace_root=sess.workspace_root or "",
                                  red_findings=red_findings or "",  # grounded in the coder's own runs
                                  gate_red=bool(sess.last_gate_red),
                                  messages=body.get("messages", []), sess=sess,
                                  participation_facts=participation_facts, original_task=sess.plan.task)
        if getattr(verification, 'step_result', None) is not None:
            return self._consume_step_result(sess, key, body, idx, total, rlog, verification)
        ok, reason = verification
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

    def _periodic_observation_after_probe(self, sess: PlanSession, key: str, body: dict, rlog) -> dict:
        """Consume the one survey requested for an unobserved periodic positive.

        The original positive is deliberately discarded.  A survey only makes the workspace
        inspectable; it does not make that old verdict authoritative.  We therefore re-run the
        same critic/confirmation path after the survey and advance only its observed positive.
        """
        item = sess.plan.current()
        if item is None:
            sess.periodic_observation = False
            return self._work(sess, key, body, rlog)
        idx = sess.plan.items.index(item) + 1
        total = len(sess.plan.items)
        raw = _read_tool_result(body.get('messages', []), sess.probe_call_id)
        matched_result = any(message.get('role') == 'tool'
                             and message.get('tool_call_id') == sess.probe_call_id
                             for message in body.get('messages', []))
        if not matched_result:
            # An unrelated result is not an unavailable observation. Preserve the
            # original pending question and repeat only its owned harness call.
            call = next((tc for message in reversed(body.get('messages', []))
                         if message.get('role') == 'assistant'
                         for tc in message.get('tool_calls') or ()
                         if tc.get('id') == sess.probe_call_id), None)
            if call is None:
                tool = find_shell_tool(body.get('tools'))
                command = probegate.continue_transport_command(sess.gate_plan) if sess.gate_plan else ''
                if tool is None or not command:
                    raise ValueError('Pending STEP observation requires its correlated harness result')
                call = repositorychecks._shell_call(_repository_input(body, rlog),
                    _repository_probes(), tool, command)
                sess.probe_call_id = call['id']
            sess.awaiting_probe = True
            return _completion_toolcalls([call], note=f'receiving workspace observation for step {idx}/{total}')
        transport_tc = guard_gate_transport(sess, body, rlog)
        if transport_tc is not None:
            sess.awaiting_probe = True
            return _completion_toolcalls(
                [transport_tc], note=f"receiving workspace observation for step {idx}/{total}")
        raw = _read_tool_result(body.get("messages", []), sess.probe_call_id)
        outcome = read_gate(sess.gate_plan, raw, rlog)
        record_gate_state(sess, outcome, gate_error_text(outcome), rlog, body.get("messages"))
        if sess.gate_replan_required:
            probe_tc = guard_gate_replan_after_survey(
                sess, body, rlog, workspace_root=sess.workspace_root)
            if probe_tc is not None:
                sess.awaiting_probe = True
                sess.probe_call_id = probe_tc["id"]
                return _completion_toolcalls(
                    [probe_tc], note=f"observing step {idx}/{total} — running the repo's checks")
        root = sess.workspace_root or _extract_cwd(body.get("messages", [])) or ""
        if not root or not wsview.current(root).surveyed:
            sess.periodic_observation = False
            rlog.emit("loop.periodic_step_observation_unavailable", level="warn", step=idx,
                      why="no workspace root" if not root else "workspace survey unavailable")
            return self._work(sess, key, body, rlog)
        sess.periodic_observation = False
        rlog.emit("loop.periodic_step_observed", step=idx)
        advanced = self._periodic_step_check(sess, key, body, idx, total, rlog, force=True)
        return advanced if advanced is not None else self._work(sess, key, body, rlog)

    def _periodic_step_check(self, sess: PlanSession, key: str, body: dict, idx: int, total: int, rlog,
                             *, force: bool = False):
        """Every STEP_CHECK_EVERY drives, ask THE STEP CRITIC whether the open step is done.

        A step advances only when the CODER volunteers that it is finished — `_verify` runs on
        `pending_coder_text`, i.e. a turn with no tool call, or `task_complete`. A coder that keeps
        calling tools never volunteers, so the step is immortal and the plan cannot move. Walked
        twice: 1785360304 held "step 1 of 7" for 107 injections and its critic did not run once in
        the final 46 turns — nothing existed that COULD release it, and the run hit the wall clock
        still on step 1; 1785888803 held step 6 from call 0174 past 0215 the same way. MEASURED
        box-wide: 74% of all coder calls sit inside a stretch of 30+ turns with no critic call at all.

        THIS IS NOT A SECOND COMPLETION AUTHORITY — that mistake was made once by the retired
        reading check, where a workspace-blind judge marked six build steps done in three minutes and
        turned a 1.0 into a 0.0. This calls the SAME `_verify` every completion claim goes through: the same
        critic, reading the same workspace inventory and the same check state, behind the same
        `_confirm_completion` brake. The only thing that changes is WHO asked — cria's own
        bookkeeping instead of the model's say-so.

        ADDITIVE and bounded: a negative, unparseable, or unconfirmed result leaves the plan
        untouched. An unobserved positive schedules one workspace observation, then is discarded;
        only a fresh positive whose approve-path brake inspected that surveyed workspace advances."""
        runtime = getattr(sess, 'pilot_binding', None) or self._ctx.pilot_runtime
        if runtime.step_review.definition is None:
            return None
        if not force and not periodic_check_due(sess.drive_count, STEP_CHECK_EVERY, STEP_CHECK_EVERY,
                                                sess.step_checked_drive):
            return None
        item = sess.plan.current()
        if item is None or item.done:
            return None
        # Stamped where the check actually RUNS. A drive with no open step is not an opportunity
        # spent, so it must not move the stamp.
        sess.step_checked_drive = sess.drive_count
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
        participation_facts = participation.render_for_judge(
            getattr(sess, "last_gate_participation", None),
            fresh=getattr(sess, "gate_fresh", None))
        verification = self._verify(
            item.text, prompts.load("periodic_step_claim"),
            prompts.load("probe_digest_none") if not sess.last_gate_ran else "",
            self._grounded_evidence(sess, body, rlog), rlog, idx=idx, total=total, key=key,
            coder_tools=_coder_tools_summary(body.get("tools")),
            routes=known_routes(msgs, sess),
            sources_read=research.sources_read(_extract_fetches(msgs), msgs),
            workspace_root=sess.workspace_root or "",
            red_findings=findings if sess.last_gate_red else "",
            gate_red=bool(sess.last_gate_red),
            messages=msgs, sess=sess,
            participation_facts=participation_facts, original_task=sess.plan.task,
            trigger=stepreview.StepTrigger.SCHEDULED, probe_ran=sess.last_gate_ran)
        step_result = getattr(verification, 'step_result', None)
        review_done = step_result.review_done if step_result is not None else verification.done
        # SAY WHAT IT DID, always — a guard that is silent when it declines cannot be told apart from
        # one that never ran.
        rlog.emit("loop.periodic_step_check", step=idx, done=verification.done, drive=sess.drive_count,
                  turns=sess.coder_turns, reason=_clip(verification.reason or "", 160))
        # The periodic critic has authority only when its own evaluation made it through the
        # approve-path brake after that brake inspected the surveyed workspace.  In particular,
        # `loop.confirm_unchecked` deliberately leaves ordinary coder-claimed advancement fail-open,
        # but it cannot grant this scheduled path new authority.
        confirmation = verification.confirmation
        effect = step_result.effect if step_result is not None else None
        if effect is not None:
            if effect.action is stepreview.StepAction.RENUDGE:
                return self._consume_step_result(sess, key, body, idx, total, rlog, verification)
            if effect.action in (stepreview.StepAction.NONE, stepreview.StepAction.KEEP_WORKING,
                                 stepreview.StepAction.CONTINUE_UNREVIEWED):
                return None
        if ((effect is None or effect.action is stepreview.StepAction.ADVANCE)
                and verification.done and confirmation is not None and confirmation.confirmed
                and confirmation.observed):
            rlog.emit("loop.periodic_step_satisfied", level="warn", step=idx, drive=sess.drive_count,
                      turns=sess.coder_turns, step_text=item.text[:160])
            return self._advance(sess, key, body, idx, total, rlog)
        if ((effect is None and review_done)
                or effect is not None and effect.action is stepreview.StepAction.OBSERVE_WORKSPACE):
            rlog.emit("loop.periodic_step_satisfied", level="warn", step=idx, drive=sess.drive_count,
                      turns=sess.coder_turns, observe_only=True, step_text=item.text[:160])
            # An unobserved positive cannot advance, but it must acquire the missing fact rather
            # than repeatedly re-frame the completed item.  This is one gate/survey round; its
            # result re-enters through `_periodic_observation_after_probe` and is judged anew.
            if confirmation is not None and confirmation.confirmed and not confirmation.observed:
                probe_tc = self._gate_op(body, sess, rlog)
                if probe_tc is not None:
                    sess.periodic_observation = True
                    sess.awaiting_probe = True
                    sess.probe_call_id = probe_tc["id"]
                    rlog.emit("loop.periodic_step_observation_scheduled", step=idx)
                    return _completion_toolcalls(
                        [probe_tc], note=f"observing workspace before verifying step {idx}/{total}")
        return None

    def _advance(self, sess: PlanSession, key: str, body: dict, idx: int, total: int, rlog) -> dict:
        """Mark the current step VERIFIED (a step advances ONLY on a genuine critic pass — there is no
        accept-unverified), update cria's plan mirror, and move on.

        The bar is unchanged: the careful reasoning-ON critic, plus the on-disk _confirm_completion
        brake. What changed (see _verify_after_probe) is that a RED repo-wide gate is now EVIDENCE the
        critic weighs rather than a veto that skipped it — a step may advance while the checks are red
        IF the critic ruled the findings belong to another step's work. That is still a genuine pass;
        it is not a cap, a budget, or an accept-unverified.

        A per-step confirmation is not a newer whole-task satisfaction verdict.  In particular, its
        ``consistent`` answer cannot cross a current negative satisfaction barrier: marking this item
        done would let `_replan_tail` discard the repair the whole-task judge kept open.  Unlike the
        final completion funnel, this edge has no bounded escape; the existing bound is only the
        explicit whole-task completion policy."""
        if _satisfaction_blocks_completion(sess):
            evidence = str(getattr(sess, "latest_satisfaction_evidence", "")
                           or prompts.load("done_no_named_gap"))
            rlog.emit("loop.step_held_satisfaction", step=idx,
                      reason=_clip(evidence, 160))
            return self._renudge(sess, key, body, prompts.render(
                "done_incomplete", reason=evidence, check_state=_check_state_words(sess)), rlog)
        item = sess.plan.current()
        item.done = True
        # A CLEAN status only — never the coder's raw output. The coder's text is unbounded prose (and
        # small models parrot cria's own banners back), which is what leaked "logs" into the plan file.
        item.note = "verified"
        sess.summary = _extend_summary(sess.summary, idx, item.text)
        sess.verify_fails = sess.critic_fails = 0
        sess.pending_coder_text = ""
        sess.step_tool_calls = 0   # fresh step, fresh did-real-work signal
        pasted_definition = self._pasted_selection(sess)
        if pasted_definition is not None:
            self._pasted_result(pasted_definition.cancel(self._pasted_state(sess)))
        sess.pasted_consumed = None
        sess.unexecuted_nudges = 0
        sess.thrash_replanned = False  # a new step-position may earn its own one-shot thrash re-derive
        sess.verify_replanned = False  # ...and its own one-shot verify-fail re-derive
        if sess.living_state_view is not None:
            sess.living_state_view.reset()
        sess.living_effects = sess.living_raw_reply = None
        sess.leg0_nudged = False
        stalled = _stalled_selection(sess)
        if stalled is not None:
            _stalled_result(stalled.reset_step(_StalledWorkView(sess)))
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
            self._replan_tail(sess, body, idx, rlog, session_key=key)  # selected living tail
        if sess.synthetic:
            # A coverage refusal released the old living-plan cursor.  Re-enter through the existing
            # raw-task driver immediately; `_work` would re-cage the task as a synthetic plan step.
            return self._drive_single_item(sess, body, key, rlog)
        self._persist_plan(sess.plan, rlog)  # refresh cria's own plan mirror; advance in-memory
        return self._work(sess, key, body, rlog)

    def _protocol_refused(self, sess: PlanSession, key: str, body: dict, error, rlog) -> dict:
        sess.generation_errors.append(error.response_error)
        if sess.unexecuted_nudges >= MAX_UNEXECUTED_NUDGES:
            rlog.emit('loop.protocol_refusal_bound', error=error.response_error)
            raise error
        sess.unexecuted_nudges += 1
        rlog.emit('loop.protocol_refused', attempt=sess.unexecuted_nudges, error=error.response_error)
        notice = prompts.render('generation_protocol_refused', attempt=sess.unexecuted_nudges)
        return self._renudge(sess, key, body, notice, rlog)

    def _retain_living_reply(self, sess, effects, raw_reply, actual, offered, rlog):
        if actual is None or actual is not offered:
            return
        if effects is not None and sess.living_effects is effects:
            selected, result, plan, plan_id, task, items = effects
            runtime = getattr(sess, 'pilot_binding', None) or self._ctx.pilot_runtime
            if (runtime.living_plan is selected and sess.plan is plan and plan.id == plan_id
                    and plan.task == task
                    and tuple((it.text, it.done, it.note) for it in plan.items) == items):
                if result.reset_failure_counts:
                    sess.verify_fails = sess.critic_fails = 0
                if result.clear_nudge:
                    sess.nudge_reason = ''
                if result.reset_acting_calls:
                    sess.step_tool_calls = 0
                sess.living_effects = None
        if raw_reply is actual and sess.living_raw_reply is raw_reply and sess.replan_uncovered_pending:
            sess.replan_uncovered_pending = False
            sess.living_raw_reply = None
            rlog.emit('loop.replan_uncovered_delivered', missing=', '.join(sess.replan_uncovered))

    def _policy_epoch(self, sess):
        """A value read from current fact authorities, not another event clock."""
        gate = getattr(sess, 'gate_plan', None)
        view = _surveyed_view(sess)
        participation = getattr(sess, 'last_gate_participation', None)
        return (sess.action_seq, id(gate), getattr(gate, 'transport_id', None),
            sess.probe_call_id, getattr(gate, 'transport_path', None),
            len(getattr(gate, 'transport_data', ())), getattr(gate, 'transport_total', None),
            getattr(gate, 'transport_sha256', None), getattr(gate, 'transport_complete', None),
            getattr(gate, 'transport_error', None), sess.last_gate_seq, sess.last_gate_ran,
            sess.last_gate_red, sess.last_gate_flag, sess.gate_fresh,
            sess.last_gate_testless, sess.last_gate_skipped, repr(participation),
            tuple(sorted(sess.write_result_ids or ())), tuple(sorted(sess.refused_write_ids or ())),
            repr(sess.own_check_runs), repr(getattr(sess, 'own_check_seen', None)),
            view.observation_fingerprint if view is not None else None)

    def _living_input(self, sess, body, idx, rlog, trigger):
        runtime = getattr(sess, 'pilot_binding', None) or self._ctx.pilot_runtime
        selected = runtime.living_plan
        def question(system, user, *, coder_tools='', evidence_blocks=None):
            return summarize(self._ctx.reasoner_chat, self._ctx.reasoner_role,
                system, user, rlog, phase='reasoner', coder_tools=coder_tools, evidence_blocks=evidence_blocks)
        services = livingplan.TailServices(
            question if self._ctx.reasoner_chat is not None and self._ctx.reasoner_role is not None else None,
            lambda: livingplan.TailFacts(self._grounded_evidence(sess, body, rlog),
                session_research_facts(body.get('messages', []), sess),
                known_routes(body.get('messages', []), sess)),
            lambda plan: self._persist_plan(plan, rlog), selected.coverage)
        return livingplan.TailInput(sess.plan, f'{sess.plan.id}:{sum(it.done for it in sess.plan.items)}',
            self._policy_epoch(sess), trigger, services, rlog, synthetic=sess.synthetic,
            plan_off=sess.plan_off, critic_fails=sess.critic_fails, acting_calls=sess.step_tool_calls,
            coder_tools=_coder_tools_summary(body.get('tools')),
            tool_names=tuple((tool.get('function') or {}).get('name', '') for tool in body.get('tools') or ()),
            step_index=idx)

    def _replan_tail(self, sess: PlanSession, body: dict, idx: int, rlog, *, trigger=REPLAN_TRIGGER_ADVANCE,
                     session_key=''):
        """LIVING PLAN. A step just verified — hand a dedicated reasoner the real work done and let it
        re-derive the REMAINING (not-done) steps, replacing that tail. Completed steps are immutable
        history; only the not-yet-done steps are rewritten. This is what prunes a step the coder already
        satisfied while doing an earlier one (or that the work made moot) BEFORE it can make the coder
        redo/undo good work. Fail-safe: a parse miss / decline leaves the plan exactly as it was, and an
        'all done' verdict is confirmed by the task critic before it is allowed to empty the plan (the
        pruned steps skip the per-step gate, so completion must clear the same backstop the plan-off
        path uses). Skipped for a synthetic 1-item plan (no tail) and when no reasoner is configured."""
        runtime = getattr(sess, 'pilot_binding', None) or self._ctx.pilot_runtime
        selected = runtime.living_plan
        if selected.definition is None:
            return livingplan.TailResult(livingplan.TailStatus.NOT_SELECTED)
        actual_trigger = (trigger if isinstance(trigger, livingplan.Trigger) else
                          livingplan.Trigger.ADVANCE if trigger == REPLAN_TRIGGER_ADVANCE else
                          livingplan.Trigger.CRITIC_STALLED)
        if sess.living_state_view is None:
            sess.living_state_view = _LivingTailView(sess)
        source = self._living_input(sess, body, idx, rlog, actual_trigger)
        result = selected.run(source, sess.living_state_view)
        if _stable_session(session_key) and self._store.get(session_key) is not sess:
            sess.living_pending = None
            return livingplan.TailResult(livingplan.TailStatus.STALE)
        if not isinstance(result, livingplan.TailResult) or not isinstance(result.status, livingplan.TailStatus):
            raise TypeError('Living plan replacement must return a typed TailResult')
        if result.status is livingplan.TailStatus.EMPTY_PENDING:
            current = self._living_input(sess, body, idx, rlog, actual_trigger)
            approved = None
            if source.evidence_epoch == current.evidence_epoch:
                approved, _, _fix = judge_satisfaction(sess.plan.task, result.confirmation.evidence,
                    self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog,
                    coder_tools=_coder_tools_summary(body.get('tools'), params=False),
                    workspace_root=sess.workspace_root or '',
                    routes=known_routes(body.get('messages', []), sess),
                    messages=body.get('messages', []), sess=sess)
            # Re-read after the confirmation too: the question itself can receive new facts.
            if _stable_session(session_key) and self._store.get(session_key) is not sess:
                sess.living_pending = None
                return livingplan.TailResult(livingplan.TailStatus.STALE)
            result = selected.settle(self._living_input(sess, body, idx, rlog, actual_trigger),
                sess.living_state_view, result.confirmation.token, approved)
            if not isinstance(result, livingplan.TailResult) or not isinstance(result.status, livingplan.TailStatus):
                raise TypeError('Living plan settlement must return a typed TailResult')
        if result.reset_to_raw_task:
            sess.synthetic = sess.plan_off = True
            sess.replan_uncovered = result.missing
            sess.replan_uncovered_pending = True
            sess.steer_source = 'living-plan coverage refusal'
        if result.reset_failure_counts or result.clear_nudge or result.reset_acting_calls:
            sess.living_effects = (selected, result, sess.plan, sess.plan.id, sess.plan.task,
                tuple((item.text, item.done, item.note) for item in sess.plan.items))
        return result

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
        try:
            if sess.synthetic:
                return self._drive_single_item(sess, body, key, rlog)
            return self._work(sess, key, body, rlog)
        except UpstreamProtocolError as error:
            if not getattr(error, 'coder_turn', False):
                raise
            return self._protocol_refused(sess, key, body, error, rlog)

    def _renudge_or_replan(self, sess: PlanSession, key: str, body: dict, reason: str,
                           idx: int, rlog) -> dict:
        """A CRITIC verify-fail (the step's checks are clean but its INTENT is judged unmet) — same as
        _renudge, EXCEPT: when the SAME step has failed the critic STUCK_STEP_REPLAN times, the step may
        be MISCONCEIVED (a confused/category-error step the planner wrote that no coder work can satisfy),
        so re-nudging with the same reason loops forever. Give the living-plan reasoner one grounded shot
        at re-deriving the not-done tail from the REAL work done: if it rewrites/drops the stuck step, we
        re-drive fresh on the new current step; otherwise (declined/unchanged) we fall through to a normal
        re-nudge. NEVER used on a gate/real-error fail — those must be FIXED, not re-derived away."""
        result = self._replan_tail(sess, body, idx, rlog,
            trigger=livingplan.Trigger.CRITIC_STALLED, session_key=key)
        if result.reset_failure_counts or result.reset_to_raw_task:
            if sess.synthetic:
                return self._drive_single_item(sess, body, key, rlog)
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
        result = self._replan_tail(sess, body, idx, rlog,
            trigger=livingplan.Trigger.TOOL_THRASH, session_key=key)
        if result.reset_failure_counts or result.reset_to_raw_task:
            if sess.synthetic:
                return self._drive_single_item(sess, body, key, rlog)
            return self._work(sess, key, body, rlog)
        return None

    def _probe_author(self, condition: str, sess: PlanSession, outcome, body: dict, rlog):
        """Bind facts and shared inspection transport; selected Source owns author/vet decisions."""
        if self._ctx.reasoner_role is None:
            return None
        item = sess.plan.current()
        step_text = item.text if item is not None else sess.plan.task
        return _stalled_author(sess, body, rlog, self._ctx.reasoner_chat, self._ctx.reasoner_role,
            sess.workspace_root, condition=condition, outcome=outcome, step_text=step_text,
            system1=self._ctx.system1)

    def _gate_op(self, body: dict, sess: PlanSession, rlog) -> dict | None:
        """The loop's completion gate — delegates to the shared :func:`guard_gate_op`, passing the
        configured workspace root."""
        return _requested_repository_probe(sess, body, rlog, workspace_root=sess.workspace_root,
            driver=repositorychecks.Driver.STEP,
            step=sess.plan.items.index(sess.plan.current()) + 1 if sess.plan.current() is not None else None)

    # ------------------------------------------------------------------ helpers

    def _reasoner(self):
        """``(chat_fn, role)`` for this Loop, or ``(None, None)``. The evidence builders take it so an
        oversized log can be SUMMARISED rather than clipped (#5's second exception); without one they
        carry the log whole, which is the same safe answer.

        THE ROLE IS THE COMPACTOR'S, because the work this does is compaction. Every one of the four
        callers hands it to `_summarised_evidence`, which calls `summarize(..., phase="compactor")` —
        so the call was LABELLED compactor and SAMPLED as the reasoner. Verified in the captures:
        all 85 compactor request bodies carry `enable_thinking: true` and `temperature: 0.6`, while
        `[roles.compactor]` says `reasoning = "off"`, `temperature = 0.0`. What it cost over 12 days:
        26 of 84 compactor calls (31%) hit `finish_reason=length` at max_tokens, 12 of them returning
        ZERO content after spending the whole budget on reasoning; 31 triggered a no-reason retry
        worth 508,437 input + 212,992 output tokens; two single calls ran 846 s and 761 s to be cut.
        The three sibling sites (`loop.py:2949`, `:2994`, `:3746`) already read `compactor_role or
        reasoner_role` — this is the fourth (#23)."""
        ctx = getattr(self, "_ctx", None)
        return (getattr(ctx, "reasoner_chat", None),
                getattr(ctx, "compactor_role", None) or getattr(ctx, "reasoner_role", None))

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
        def consume(log):
            facts = _fetch_ground_truth(messages, sess, header=CODER_FETCH_HEADER)
            inventory = workspace_inventory(sess.workspace_root)
            return "\n\n".join(part for part in (log, facts, inventory) if part)
        return _dedup_evidence(_work_log(messages, rlog=rlog,
                                          gate_plan=getattr(sess, "gate_plan", None)),
            rlog=rlog, chat_fn=self._reasoner()[0], role=self._reasoner()[1], _consume=consume)

    def _consume_step_result(self, sess, key, body, idx, total, rlog, verification):
        result = verification.step_result
        effect = result.effect
        if effect.action is stepreview.StepAction.ADVANCE:
            if effect.red_gate_advance:
                rlog.emit('loop.gate_red_advance', level='warn', step=idx,
                    findings=sess.last_gate_flag or '', reason=result.reason)
            return self._advance(sess, key, body, idx, total, rlog)
        if effect.action is stepreview.StepAction.RENUDGE:
            sess.verify_fails += effect.verify_failures
            sess.critic_fails += effect.critic_failures
            rlog.emit('loop.step_incomplete', step=idx,
                reason=result.reason if effect.consider_critic_rescue else 'probe failed',
                attempt=sess.verify_fails)
            if effect.consider_critic_rescue:
                return self._renudge_or_replan(sess, key, body, effect.nudge or result.reason, idx, rlog)
            return self._renudge(sess, key, body, effect.nudge or result.reason, rlog)
        return self._work(sess, key, body, rlog)

    def _verify(self, item: str, coder_text: str, probe: str, evidence: str, rlog,
                *, idx: int = 0, total: int = 0, key: str = "", coder_tools: str = "",
                routes: str = "", workspace_root: str = "", red_findings: str = "",
                gate_red: bool = False, sources_read: list | None = None,
                messages: list | None = None, sess=None,
                participation_facts: str = "", original_task: str = "",
                trigger=stepreview.StepTrigger.CLAIM, probe_ran=False, probe_unknown=False,
                probe_blocked=False, probe_repair='') -> Verification:
        runtime = getattr(sess, 'pilot_binding', None) if sess is not None else None
        selected = (runtime or self._ctx.pilot_runtime).step_review
        def source():
            def read(request):
                verdict, raw = self._verdict(request.system, request.user, rlog,
                    reasoning_off=request.reasoning_off, workspace_root=request.workspace_root,
                    evidence_blocks=list(request.evidence_blocks))
                return stepreview.StepAnswer(verdict, raw)
            def confirm(request):
                result = _confirm_completion(request.step, request.reason, request.workspace_root,
                    self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog, phase=request.phase,
                    original_task=request.original_task, cria_facts=request.participation_facts,
                    authority=completionconfirmation.Authority.STEP,
                    planning_enabled=self._ctx.planner_enabled)
                return None if result.status is completionconfirmation.Status.NOT_SELECTED else result
            def diagnose(request):
                ask = ((lambda question: ask_closed(self._ctx.reasoner_chat,
                    self._ctx.reasoner_role, question, rlog, phase=request.phase,
                    max_tokens=JUDGE_MAX_TOKENS, retry_off=False))
                    if self._ctx.reasoner_role is not None else None)
                return _verdict_nudge(request.verdict, request.done, request.routes,
                    evidence=request.user, task=request.step, original_task=request.original_task,
                    action_log=request.action_log, checks=request.checks,
                    participation_facts=request.participation_facts, diagnosis_ask=ask,
                    phase=request.phase, workspace_root=request.workspace_root,
                    rlog=rlog, messages=messages, sess=sess, system1=self._ctx.system1)
            def persist(record):
                _dump_verify(self._run_dir(rlog), record.key, record.index, record.total,
                    record.step, record.system, record.user, record.done, record.reason, response=record.raw)
            off_role = (replace(self._ctx.reasoner_role, reasoning='off')
                        if self._ctx.reasoner_role is not None else None)
            applies = (lambda question: summarize(self._ctx.reasoner_chat, off_role, question,
                _ASK_USER_TURN, rlog, phase='confirm-applies', temperature=0.0) or '') if off_role else None
            services = stepreview.StepServices(read,
                lambda obj, flag, phase: _fill_missing_verdict_flag(obj, flag, rlog, phase),
                confirm, diagnose, persist, VerdictNudge, _named_gap, applies)
            return stepreview.StepInput(item, coder_text, evidence,
                stepreview.ProbeEvidence(probe, red_findings, gate_red, probe_ran,
                    probe_unknown, probe_blocked, probe_repair), services, rlog,
                workspace_root, coder_tools, routes, tuple(sources_read or ()),
                participation_facts, original_task, key, idx, total, trigger)
        result = selected.run(source)
        return Verification(result.done, result.reason, result.confirmation, result)

    def _verdict(self, system: str, user: str, rlog, *, reasoning_off: bool,
                 workspace_root: str = "", evidence_blocks: list[str] | None = None) -> tuple[dict | None, str]:
        """Optional step critic adapter; retain cleaned raw text for the verifier record.

        F37 shares response handling, not the step question or completion authority.
        No planner is enabled here. Empty wire declaration retains the existing
        step-critic body contract; _judge_completion defaults closure to done.
        """
        return _critic_verdict(system, user, self._ctx.reasoner_chat, self._ctx.reasoner_role,
                               rlog, reasoning_off=reasoning_off, workspace_root=workspace_root,
                               evidence_blocks=evidence_blocks)

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

    def _compact_done(self, sess: PlanSession, body: dict, rlog):
        """Compact a FINISHED plan into a work-done briefing (the reasoner), so a follow-up prompt
        on this session starts from a clean, accurate context. Focus is the completed state — files
        and their purpose, how it runs/tests, key facts — not narration or next steps. Grounded in
        the actual coder actions (from the transcript) + the plan, so it names real files, not
        guesses. Best-effort: on any failure, fall back to the running per-step summary / checklist.
        A prior session summary is threaded in so a chain of follow-ups keeps ONE cumulative briefing."""
        runtime = getattr(sess, 'pilot_binding', None) or self._ctx.pilot_runtime
        selected = runtime.completed_work
        if selected.definition is None:
            return None
        def question(request, log):
            return summarize(self._ctx.reasoner_chat, request.role, request.system, request.user,
                log, phase=request.phase, retry_off=request.retry_off)
        source = completedwork.BriefingInput(
            completedwork.CompletionScope(getattr(sess, 'web_session', '') or '',
                (id(sess), self._policy_epoch(sess))), sess.plan, body.get('messages', []),
            completedwork.Services(_work_log, question), rlog, release_authorized=True,
            planner_enabled=self._ctx.planner_enabled, synthetic=sess.synthetic,
            summary=sess.summary, prior_work=sess.prior_work, gate_plan=sess.gate_plan,
            compactor_role=self._ctx.compactor_role, reasoner_role=self._ctx.reasoner_role)
        result = selected.generate(source)
        if not isinstance(result, completedwork.BriefingResult):
            raise TypeError('Completed work replacement must return BriefingResult')
        return selected, source, result, sess

    def _closing(self, sess: PlanSession, briefing=None, *, base=None) -> str:
        """The final message — a clean completion. Every step is VERIFIED: cria advances a step ONLY on a
        genuine pass and re-nudges INDEFINITELY otherwise, so a step is never 'accepted unverified' and
        cria never ends a plan with untrusted work (the removed accept-and-advance/handback path).

        The completion BRIEFING is embedded here, in the enveloped block — this message is the briefing's
        home. The harness stores it in the conversation, its compactor summarizes from it, and cria
        re-reads it from history (``_briefing_from_history``). One summary, carried by the transcript —
        never a server-side copy."""
        base = (f'{indicators.MARKER}plan complete — all {len(sess.plan.items)} steps verified.'
                if base is None else base).strip()
        if briefing is None:
            return base
        selected, producer, result, owner = briefing
        runtime = getattr(sess, 'pilot_binding', None) or self._ctx.pilot_runtime
        if owner is not sess or runtime.completed_work is not selected or sess.plan is not producer.plan:
            return base
        current = replace(producer, scope=completedwork.CompletionScope(producer.scope.session_key,
            (id(sess), self._policy_epoch(sess))), plan=sess.plan)
        closing = selected.embed(base, current, result)
        if not isinstance(closing, completedwork.ClosingResult):
            raise TypeError('Completed work embedding replacement must return ClosingResult')
        return closing.text

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
        if blocked:
            # SAY IT, OR THIS IS UNDIAGNOSABLE. cria recorded nothing when the check did not run, so
            # "it fired once in 86 calls" could not be told from "it was only due once" without
            # reconstructing the drive sequence by hand from the captures afterwards (#12). A lost
            # opportunity is an event, and counting them is how the modulo defect was found.
            #
            # …AND IT MUST NAME WHICH BLOCKER. The event said THAT the check was skipped and not WHY,
            # so `blocked` was a single opaque bit over four independent conditions. Walked on
            # rust-toml-cli x ternary-bonsai (2026-08-19): 50 skips, 34 of them on drives where the
            # check was genuinely due, and answering "which flag" took reading the gate events, the
            # probe events and three call sites by hand. A metric must come from the authoritative
            # event (#12) — the caller now says which condition it saw.
            if rlog is not None:
                rlog.emit("loop.satisfaction_blocked", drive=sess.drive_count,
                          last_ran=sess.satisfaction_last_drive, plan_off=plan_off,
                          why=blocked if isinstance(blocked, str) else "unnamed")
            return None            # BEFORE anything else — see test_blocked_short_circuits
        if not assistruntime.current().review_applies(ReviewTrigger.SCHEDULED):
            return None
        if not periodic_check_due(sess.drive_count, self._ctx.satisfaction_check_start,
                                      self._ctx.satisfaction_check_every,
                                      sess.satisfaction_last_drive):
            return None
        # Stamped BEFORE the work, so a negative still spaces the next judgment.
        sess.satisfaction_last_drive = sess.drive_count
        review = self._review_task(sess, body, rlog, trigger=ReviewTrigger.SCHEDULED)
        satisfied, reason = review.approved, review.reason
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
            diagnosis = assistruntime.current().completion_diagnosis
            if diagnosis is not None:
                # VerdictNudge remains the public text/provenance carrier. Source-produced values
                # retain their original typed status; legacy callers retain their declared evidence.
                gap = getattr(reason, "diagnosis_result", None)
                if gap is None:
                    gap = completiondiagnosis.DiagnosisResult(
                        completiondiagnosis.DiagnosisStatus.GROUNDED if reason else completiondiagnosis.DiagnosisStatus.NOT_APPLICABLE,
                        getattr(reason, "evidence", str(reason or "")), getattr(reason, "action", ""),
                        getattr(reason, "diagnosis_kind", ""), getattr(reason, "subject", ""))
                delivered = diagnosis.deliver(completiondiagnosis.DeliveryInput(
                    gap, completiondiagnosis.DeliveryTrigger.SCHEDULED_REVIEW, plan_off), sess,
                    _diagnosis_delivery_services(diagnosis, sess.workspace_root or "", rlog))
                completiondiagnosis._remediation_result(delivered,
                    (completiondiagnosis.RemediationStatus.NOT_APPLICABLE, completiondiagnosis.RemediationStatus.DELIVERED))
            return None   # never ENDS the session on a not-satisfied verdict — that is unchanged
        probe_tc = _requested_repository_probe(sess, body, rlog, workspace_root=sess.workspace_root)
        if probe_tc is not None:  # verify the repo's checks before ending (same backstop as 'done')
            sess.done_probe = True
            sess.probe_call_id = probe_tc["id"]
            # Held as PIECES, not as prose: the note's opening claim depends on whether the gate
            # actually ran, and that is not known until its result comes back next turn. The
            sess.pending_done_parts = (reason,)
            sess.pending_done = satisfaction_done_note(reason)
            sess.steer_source = "completion check (task satisfied)"
            return _completion_toolcalls([probe_tc],
                                         note="cria completion check: the task looks done — verifying the repo's checks")
        # No shell to verify → end fail-open, and SAY that nothing verified it. This path composes no
        # gate at all, so the "and the repo's own checks" claim was false here every single time.
        briefing = self._compact_done(sess, body, rlog)
        return _completion_final(self._closing(sess, briefing,
            base=satisfaction_done_note(reason, checks_ran=False)))

    def _settle_task_done_probe(self, sess: PlanSession, body: dict, key: str, rlog, *,
                                plan_off: bool, rewritten: bool = False) -> dict | None:
        """One consumer for a held whole-task claim and its exact probe in either mode.

        Transport returns a harness call; rejection parks a nudge for the SAME
        driver's continuation. Only released tasks return final completions.
        Step progress is not inferred from whole-task approval.
        """
        # Plan-on can arm this claim only through scheduled review, which holds
        # its parts with the probe. A legacy stranded boolean is not a claim and
        # must not commandeer the ordinary step-completion backstop.
        if not plan_off and not sess.pending_done_parts:
            sess.done_probe = False
            sess.pending_done = ""
            rlog.emit("loop.orphan_done_probe", plan_off=False)
            return None
        reissue = guard_probe_reissue(sess, body, rlog, rewritten=rewritten,
                                     workspace_root=sess.workspace_root)
        if reissue is not None:
            return reissue
        transport = guard_gate_transport(sess, body, rlog)
        if transport is not None:
            return _completion_toolcalls([transport], note="verifying — receiving the repo's complete check output")
        sess.done_probe = False
        # Consume once; retain pieces only across survey replanning.
        parts, sess.pending_done_parts = sess.pending_done_parts, ()
        errors = guard_gate_verdict(sess, body, rlog)
        if sess.gate_replan_required:
            probe = guard_gate_replan_after_survey(sess, body, rlog, workspace_root=sess.workspace_root)
            if probe is not None:
                sess.done_probe = True
                sess.probe_call_id = probe["id"]
                sess.pending_done_parts = parts
                return _completion_toolcalls([probe], note="verifying — running the repo's checks")
        if errors:
            rlog.emit("loop.gate", plan_off=plan_off, blocked=True)
            if getattr(sess.gate_plan, "transport_error", ""):
                sess.nudge_reason = errors
                sess.steer_source = "completion gate (check evidence unknown)"
            else:
                sess.nudge_reason = prompts.render("gate_fail_steer", errors=errors)
                sess.steer_source = "completion gate (repo checks failed)"
            return None
        critic_reason = ""
        if self._ctx.reasoner_role is not None:
            critic_reason = (self._done_critic_reason(sess, body, rlog) if plan_off else
                             self._done_critic_reason(sess, body, rlog, plan_off=False))
        if critic_reason:
            sess.nudge_reason = prompts.render("done_incomplete", reason=critic_reason,
                                               check_state=_check_state_words(sess))
            sess.steer_source = "completion critic (task not fully done)"
            sess.pending_done = ""
            return None
        if _satisfaction_blocks_completion(sess):
            sess.nudge_reason = prompts.render("done_incomplete",
                reason=str(getattr(sess, "latest_satisfaction_evidence", "") or prompts.load("done_no_named_gap")),
                check_state=_check_state_words(sess))
            sess.steer_source = "completion critic (task not fully done)"
            return None
        rlog.emit("loop.gate", plan_off=plan_off, blocked=False)
        original_held = sess.pending_done
        held, sess.pending_done, sess.leg0_nudged = original_held, "", False
        if parts:
            held = satisfaction_done_note(*parts, checks_ran=bool(sess.last_gate_ran))
        try:
            briefing = self._compact_done(sess, body, rlog)
            closing = self._closing(sess, briefing, base=held or 'Done.')
        except Exception:
            # The actual held claim belongs to this owner until a closing exists.
            # Restore only its original fields; no summary or approval is cached.
            sess.done_probe = True
            sess.pending_done_parts = parts
            sess.pending_done = original_held
            raise
        if _stable_session(key):
            self._store.mark_done(key)
        self._store.drop(key)
        return _completion_final(closing)

    def _drive_single_item(self, sess: PlanSession, body: dict, session_key: str, rlog, *, rewritten: bool = False,
                           rewrite_observation: RewriteObservation | None = None) -> dict | None:
        """The single-item coder turn with the SAME protections the loop gives its coder: the
        repetition/wheel-spin guard (probe → steer), the completion gate on a bare 'done' (verify the
        repo's checks before ending), harness-compaction re-anchoring, and the periodic + done
        satisfaction critic. Cross-turn state lives on the PlanSession (persisted for
        stable keys, ephemeral for ``task:`` keys). Returns the completion to send, or None on decode fail."""
        act_first = assistruntime.current().completion_act_first
        sess.drive_count += 1  # this session's total drives — the periodic satisfaction check keys off it
        sess.workspace_root = _extract_cwd(body.get("messages", [])) or sess.workspace_root or self._ctx.workspace_root  # harness cwd, persisted (see _work)
        body = {**body, "messages": self._judge_search_reads(sess, body, rlog)}  # strip off-target search reads
        if sess.done_probe:
            settled = self._settle_task_done_probe(sess, body, session_key, rlog,
                                                  plan_off=True, rewritten=rewritten)
            if settled is not None:
                return settled
        elif not sess.periodic_probe:
            # Nonperiodic guards retain their separate authority; periodic resume owns its ordering.
            reissue = guard_probe_reissue(sess, body, rlog, rewritten=rewritten, workspace_root=sess.workspace_root)
            if reissue is not None:
                return reissue
            if sess.periodic_probe or sess.awaiting_probe:
                transport_tc = guard_gate_transport(sess, body, rlog)
                if transport_tc is not None:
                    return _completion_toolcalls(
                        [transport_tc], note="verifying — receiving the repo's complete check output")
        # A PERIODIC check-in probe's result → insert the ground truth as a steer (no verdict).
        if sess.periodic_probe:
            result = _resume_repository_checks(sess, body, rlog,
                driver=repositorychecks.Driver.TASK, rewritten=rewritten,
                reasoner_chat=self._ctx.reasoner_chat, reasoner_role=self._ctx.reasoner_role,
                workspace_root=sess.workspace_root or _extract_cwd(body.get("messages", [])))
            if result.call is not None:
                note = ("verifying — receiving the repo's complete check output"
                        if result.pending_kind is repositorychecks.PendingKind.PAGE
                        else result.note or "periodic check-in — running checks")
                return _completion_toolcalls([result.call], note=note)
            truth = result.text
            if truth:
                # C5: if the SAME error has persisted (the coder is STUCK, not just churning), replace the
                # raw ground-truth insertion with a REASONED thrash-diagnosis + one concrete next step (on
                # the routed reasoner). A reasoned unstick on a persistent RED stall — never a give-up.
                stalled = _stalled_selection(sess)
                if stalled is not None:
                    progress = _stalled_result(stalled.progress(stalledwork.ProgressInput(
                        truth, sess.gate_stall, _stalled_author(sess, body, rlog,
                            self._ctx.reasoner_chat, self._ctx.reasoner_role,
                            sess.workspace_root or _extract_cwd(body.get('messages', [])),
                            system1=self._ctx.system1)
                            if self._ctx.reasoner_role is not None else None, rlog),
                        _StalledWorkView(sess)))
                    if progress.steer is not None:
                        truth = _stalled_text(progress.steer)
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
                return _stalled_author(g, b, r, self._ctx.reasoner_chat, self._ctx.reasoner_role,
                    sess.workspace_root or _extract_cwd(b.get('messages', [])),
                    condition=condition, outcome=outcome, system1=self._ctx.system1)
            author = _author if self._ctx.reasoner_role is not None else CANNED
            steer = guard_probe_steer(sess, body, rlog, author=author)
        elif not sess.nudge_reason:  # (a gate-fail steer is already parked — don't double-intervene)
            intervention = guard_intervene(sess, body, rlog, workspace_root=sess.workspace_root)
        if intervention is not None:
            return intervention
        # The reset itself owns the first raw-task body.  Unlike a transient nudge, this is durable:
        # a restart between the coverage refusal and the coder call must not silently drop the exact
        # missing-deliverable evidence.  It is acknowledged only after this body reached the coder.
        reset_delivery = bool(sess.replan_uncovered and sess.replan_uncovered_pending)
        if reset_delivery:
            steer = prompts.render("replan_uncovered_reset",
                                   missing=", ".join(sess.replan_uncovered))
        # PERIODIC SATISFACTION CHECK — the off-ramp for a session that finished but cannot stop.
        # LEVEL 5 — ASSISTS_ENABLED. This check is SCHEDULED: a turn counter fires it, the model
        # asked for nothing, and cria volunteers what it thinks is missing. The trigger decides the
        # rung (see LoopContext.assists), so the level is weighed HERE rather than inside the check —
        # `_periodic_satisfaction` has a deliberate contract that `blocked` is its first word, tested
        # against a Loop with no context at all, and a gate in front of that would break it.
        done_now = None if not self._ctx.assists else self._periodic_satisfaction(
            sess, body, rlog, plan_off=True,
            blocked=_satisfaction_blocker(steer=steer or sess.nudge_reason, rewritten=rewritten,
                                          done_probe=sess.done_probe, gate_red=sess.last_gate_red,
                                          gate_stall=sess.gate_stall))
        if done_now is not None:
            return done_now
        # Resolve the pending note after the scheduled review can produce one, so a
        # grounded negative reaches this coder turn rather than waiting for another request.
        if steer is None and sess.nudge_reason:
            steer, sess.nudge_reason = sess.nudge_reason, ""
        # PERIODIC gate: every N acting turns, run the checks and insert ground truth — only when nothing
        # else is steering this turn (a guard steer / re-anchor takes precedence).
        # LEVEL 5 — ASSISTS_ENABLED, same rule as the other call site: scheduled, so it is an assist.
        if self._ctx.assists:
            periodic = guard_periodic_gate(sess, body, rlog, workspace_root=sess.workspace_root,
                driver=repositorychecks.Driver.TASK, steer=steer, rewritten=rewritten)
            if periodic is not None:
                return periodic
        record_coder_preframe(rlog, sess, sess.plan.current(), 1, 1, driver="plan_off")
        extra = []
        if steer:  # inject the steer into the coder framing this turn
            extra.append({"role": "user", "content": prompts.render("nudge", reason=steer)})
        framed, reoriented = self._prepare_coder_context(sess, body, rlog, synthetic=True,
            notes=extra, rewritten=rewritten, session_key=session_key)
        _stalled_frame(sess, framed, extra)
        comp = self._coder_turn(sess, framed, body, step=1, rlog=rlog)  # SHARED coder turn (see _work)
        if rewritten and rewrite_observation is not None and rewrite_observation.key == session_key:
            self._store.ack_rewrite(rewrite_observation)
        if reset_delivery:
            sess.living_raw_reply = comp
        if reoriented:  # no hidden guards: surface only an executed reorientation
            _add_note(comp, "re-anchored after a harness compaction")
        if steer:  # no hidden guards: surface WHICH guard steered the coder
            _add_note(comp, f"steered the coder — {sess.steer_source or 'guard'}")
            sess.steer_source = ""
        if _has_tool_calls(comp):
            return _forward_acting_coder(sess, comp)
        return self._gate_single_done(sess, comp, framed, body, session_key, rlog,
                                      completion_act_first=act_first)

    def _gate_single_done(self, sess: PlanSession, comp: dict, framed: dict, body: dict, key: str, rlog, *,
                          completion_act_first=None) -> dict:
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
                return _forward_acting_coder(sess, comp)  # retained lost-call reask
        refused = comp.pop(bodykeys.FENCED_REFUSED, None)
        if refused and sess.unexecuted_nudges < MAX_UNEXECUTED_NUDGES:
            sess.unexecuted_nudges += 1
            rlog.emit("loop.fenced_call_refused_said", plan_off=True, reason=refused.get("reason"),
                      tool=refused.get("tool"), attempt=sess.unexecuted_nudges)
            carried = ([] if massage.is_truncated(comp)
                       else [{"role": "assistant", "content": _completion_text(comp)}])
            conv = framed["messages"] + carried + [
                {"role": "user", "content": self._refused_call_text(sess, body, refused)}]
            comp = self._coder_turn(sess, {**framed, "messages": conv}, body, step=1, rlog=rlog)
            if _has_tool_calls(comp):
                return _forward_acting_coder(sess, comp)  # retained refusal reask
        # BEFORE reading this as "thinks it's done": a turn that pasted a whole file did not finish,
        # it failed to emit the call. Same check as the multi-step half — see unexecuted_write().
        pasted_nudge = self._pasted_followup(sess, comp)
        if pasted_nudge is not None:
            carried = ([{'role': 'assistant', 'content': pasted_nudge.carried_reply}]
                       if pasted_nudge.carried_reply else [])
            conv = framed['messages'] + carried + [pasted_nudge.user_turn]
            comp = self._coder_turn(sess, {**framed, "messages": conv}, body, step=1, rlog=rlog)  # SHARED
            if _has_tool_calls(comp):
                return _forward_acting_coder(sess, comp)  # retained pasted-write reask
        redrive = (completion_act_first.execute(completionredrive.Input(
            completionredrive.Authority.TASK, sess.action_seq, sess, rlog))
            if completion_act_first is not None else None)
        if redrive is not None:
            if not isinstance(redrive, completionredrive.Result) or not isinstance(redrive.user_turn, dict):
                raise ValueError('Task act-first replacement must return Result with user turn')
            conv = framed['messages'] + [redrive.user_turn]
            comp = self._coder_turn(sess, {**framed, "messages": conv}, body, step=1, rlog=rlog)  # SHARED
            if _has_tool_calls(comp):
                return _forward_acting_coder(sess, comp)  # retained leg0 reask
        probe = _requested_repository_probe(sess, body, rlog, workspace_root=sess.workspace_root)  # body, NOT framed
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
        if _satisfaction_blocks_completion(sess):
            return self._renudge(sess, key, body, prompts.render(
                "done_incomplete",
                reason=str(getattr(sess, "latest_satisfaction_evidence", "") or prompts.load("done_no_named_gap")),
                check_state=prompts.load_map("done_check_state")["never_ran"]), rlog)
        return comp  # no reasoner AND no shell → can't verify at all; forward the 'done' (Tier-2 fail-open, left)

    def _review_task(self, sess: PlanSession, body: dict, rlog, *, trigger: ReviewTrigger) -> ReviewResult:
        """Bind existing evidence/judge services to the registered state-writing stage.

        The stage owns assembly order and recording. This adapter supplies the same
        original-task, provenance and read-only services the three callers used before.
        Tail-pruning deliberately does not enter this authoritative transition.
        """
        runtime = assistruntime.current()
        if trigger is not ReviewTrigger.SCHEDULED and not runtime.review_applies(trigger):
            raise ValueError("whole-task-review is required for reactive completion at L4/L5")
        def history():
            return _satisfaction_evidence(body.get("messages", []), rlog=rlog,
                chat_fn=self._reasoner()[0], role=self._reasoner()[1],
                gate_plan=getattr(sess, "gate_plan", None),
                workspace_root=getattr(sess, "workspace_root", "") or "",
                origin=getattr(sess, "handoff_origin", None))
        def judge(task, evidence):
            return judge_satisfaction(task, evidence, self._ctx.reasoner_chat, self._ctx.reasoner_role,
                rlog, coder_tools=_coder_tools_summary(body.get("tools"), params=False),
                workspace_root=sess.workspace_root or "",
                routes=known_routes(body.get("messages", []), sess),
                gate_findings=getattr(sess, "last_gate_flag", "") or "",
                messages=body.get("messages", []), sess=sess)
        return runtime.review(ReviewInput(trigger, getattr(getattr(sess, "plan", None), "task", ""),
            history, lambda: _gate_notes(sess), judge, VerdictNudge, rlog), sess)

    def _done_critic_reason(self, sess: PlanSession, body: dict, rlog, *, plan_off: bool = True) -> str:
        """The task-level reasoner critic on a GREEN single-item 'done' (parity with the loop's _verify):
        judge the WHOLE task against the real work + the vacuous-green fact. Returns the critic's CONCRETE
        reason when the task is NOT satisfied — a specific unmet deliverable to steer the coder back with —
        or "" when satisfied. Runs on EVERY green 'done' (NO once-bound): cria never lets a still-
        incomplete task exit early; the model finishes the real work on its own. Fail-CLOSED — an
        undecidable judge counts as not-satisfied (judge_satisfaction already only confirms NOT-done)."""
        review = self._review_task(sess, body, rlog, trigger=ReviewTrigger.CLAIM)
        if review.status is ReviewStatus.UNKNOWN_TASK:
            rlog.emit("loop.done_critic", plan_off=plan_off, satisfied=False, original_task_unknown=True)
            return _unnamed_gap(sess, sess.pending_done)
        satisfied, reason = review.approved, review.reason
        task = sess.plan.task
        rlog.emit("loop.done_critic", plan_off=plan_off, satisfied=satisfied)
        if satisfied:
            return ""
        if not reason:
            # THE DIAGNOSIS WAS SUPPRESSED (the judge's quotes/labels did not survive provenance). A named
            # task file that the workspace view proves absent does not need the judge to have labelled it
            # right: ask the same observer the plan-ON driver runs, whose answer must itself pass the one
            # provenance owner. Only on a complete, current survey; anything else is silence (#11b).
            gap = self._observe_missing_file_on_done(sess, body, task, rlog)
            if gap:
                return gap
        return reason or _unnamed_gap(sess, sess.pending_done)

    def _observe_missing_file_on_done(self, sess: PlanSession, body: dict, task: str, rlog) -> "VerdictNudge":
        """The plan-OFF twin of the plan-ON deliverable observer. Trigger: the model tried to stop and the
        completion check was not satisfied without a usable diagnosis (level 4's trigger — no assist
        schedule involved). Returns the typed `missing_file` nudge or an empty one."""
        definition = assistruntime.current().completion_diagnosis
        if definition is None:
            return VerdictNudge()
        return _diagnosis_nudge(definition.observe_terminal(
            lambda: getattr(getattr(sess, "plan", None), "task", ""),
            bool(sess.workspace_root and self._ctx.reasoner_chat is not None),
            _diagnosis_lifecycle_services(definition, sess.workspace_root or "",
                self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog)))

    def _reasoned_reanchor(self, body: dict, rlog, workspace_root: str = "") -> str:
        """Compatibility author: F49 owns name grounding, not F44 action vetting."""
        definition = next(iter(assistruntime.current().bindings(reorientation.DEFINITION.policy.stage)), None)
        if definition is None:
            return ""
        result = definition.execute(reorientation.ReorientationInput(True,
            lambda: reorientation.ReorientationFacts(tuple(_content_text(m.get("content"))
                for m in body.get("messages", []) if m.get("role") == "user"),
                self._ctx.reasoner_role is not None, _history_root(body.get("messages", []))[0]),
            lambda: workspace_inventory(workspace_root or "", flavor="briefing"),
            reorientation.SummaryAuthor(summarize, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog),
            None, rlog, _composed_closed_ask(self._ctx.reasoner_chat,
                self._ctx.reasoner_role, rlog, phase="reanchor-name-grounding")))
        if result.message is None:
            return ""
        prefix, _slot, suffix = prompts.load("nudge").partition("{{REASON}}")
        return result.message["content"].removeprefix(prefix).removesuffix(suffix)

    def _prepare_coder_context(self, sess, body, rlog, *, synthetic, index=None, total=None,
                               item="", notes=(), rewritten=False, session_key=""):
        """One preparation order; driver scheduling never chooses pipeline placement."""
        runtime = assistruntime.current()
        raw = body.get("messages") or []
        from .upstream import protected_reads, _read_positions
        reads = protected_reads(body)
        read_tail = []
        if reads:
            cut = min(_read_positions(raw, reads))
            read_tail, raw = raw[cut:], raw[:cut]
        # Historical observations enter before every reducer, never as live notes.
        # They make no assertion about current correctness or uncompleted work.
        prior_guidance = getattr(sess, 'guidance_history', ())
        if prior_guidance:
            raw = list(raw) + [{'role': 'user', 'content': prompts.render(
                'guidance_history', observations='\n\n'.join(_dated_guidance(sess, prior_guidance))),
                bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.GUIDANCE_HISTORY}]
        authority = _capture_context_facts(sess, raw)
        base = _required_coder_base(raw, tools=body.get("tools"), prior_work=sess.prior_work,
            workspace_root=sess.workspace_root, gate_plan=getattr(sess, "gate_plan", None),
            suspend_cursor=bool(sess.completion_remediation_subject or sess.replan_uncovered), rlog=rlog)
        # Root authority is a partition, not reducible history rediscovered later.
        # Keep ALL initial user packets in original order. Equal later packets
        # remain independent turns, and markup cannot establish harness origin.
        root_indices = {i + 1 for i in base.root_indices}
        root_messages = [message for position, message in enumerate(base.messages) if position in root_indices]
        root_task = _history_root(raw)[0]
        history = [message for position, message in enumerate(base.messages[1:], start=1)
                   if position not in root_indices]
        if self._ctx.self_compact:
            frame = [base.messages[0], *root_messages]
            history = self._self_compact(history, sess, index, rlog,
                force=bool(not synthetic and sess.compact_pending), pinned_task=root_task,
                protected_prefix=True,
                frame_tokens=contextfloor.est_total(frame, body.get("tools")))
        focus_bindings = runtime.bindings("coder-focus") if self._ctx.focus_trim else ()
        focused = focustrim.focus(focustrim.FocusInput(history), focus_bindings)
        history = focused.messages
        if focused.report.applied:
            rlog.emit("context.focus_trim", reshape="focus-trim", step=index,
                      dropped_calls=focused.report.dropped_calls, dropped_msgs=focused.report.dropped_msgs)
        # Reducers never received these packets, so neither copies nor canonical
        # rolling task publication can duplicate them. All returned context survives.
        history = [base.messages[0], *root_messages, *history]
        workspace = _surveyed_view(sess)
        restore_definition = next(iter(runtime.bindings(contextrestoration.DEFINITION.policy.stage)), None)
        if restore_definition is not None:
            restored = restore_definition.execute(contextrestoration.RestoreInput(
                lambda: workspace,
                lambda: contextrestoration.FileHistory(
                    tuple(path for path, _value in authority.ledger), authority.written_paths,
                    tuple(_extract_whole_reads(history, workspace)),
                    tuple(path for _pos, _tid, path in _write_events_paths(history)),
                    authority.key, dict(authority.touch))))
            if restored.message is not None:
                history = history + [restored.message]
            offered = restored.offered
        else:
            offered = {}
        visible_urls = set(_extract_fetches(history)) & webfetch.visible_urls(getattr(sess, "web_session", None))
        anchor = _render_context_facts(authority, visible_messages=history,
            visible_fetch_urls=visible_urls, restored_offered=offered, workspace=workspace)
        if anchor is not None:
            history = history + [anchor]
        ledger_definition = next(iter(runtime.bindings(ledgercopies.DEFINITION.policy.stage)), None)
        if ledger_definition is not None and anchor is not None:
            history = ledger_definition.execute(ledgercopies.LedgerCopyInput(history,
                lambda: _format_fetches(dict(authority.fetches), "PAGES YOU HAVE ALREADY FETCHED",
                    visible=set(), location=False), rlog)).messages
        current = replace(base, messages=history, task_index=len(root_messages) - 1 if root_messages else None,
                          root_indices=tuple(range(len(root_messages))))
        remediation = bool(sess.completion_remediation_subject)
        step_definition = next(iter(runtime.bindings(steppreparation.DEFINITION.policy.stage)), None)
        steps = (steppreparation.StepSelection.opt_in(step_definition)
                 if self._ctx.planner_enabled and not synthetic else steppreparation.StepSelection())
        if remediation and not synthetic:
            history = steppreparation.with_directive(current, prompts.load("completion_remediation"),
                                                     prompts.load("plan_ack"))
        else:
            history = steps.prepare(steppreparation.StepInput(current, item, sess.summary,
                index, total, step_artifacts_on_disk, getattr(sess, "last_gate_red", False),
                self._ctx.planner_enabled, synthetic)).messages
        reoriented = False
        reorient = next(iter(runtime.bindings(reorientation.DEFINITION.policy.stage)), None)
        if reorient is not None and rewritten:
            origin = getattr(sess, "handoff_origin", None)
            result = reorient.execute(reorientation.ReorientationInput(True,
                lambda: reorientation.ReorientationFacts(tuple(_msg_text_content(m) for m in raw
                    if m.get("role") == "user"), self._ctx.reasoner_role is not None, root_task,
                    next((_msg_text_content(m) for m in raw if m.get("role") == "user"
                        and isinstance(origin, _HandoffOrigin)
                        and origin.matches_continuation(_msg_text_content(m))), "")),
                lambda: _reorientation_inventory(sess, raw, rlog),
                reorientation.SummaryAuthor(summarize, self._ctx.reasoner_chat, self._ctx.reasoner_role, rlog),
                None, rlog, _composed_closed_ask(self._ctx.reasoner_chat,
                    self._ctx.reasoner_role, rlog, phase="reanchor-name-grounding")))
            if result.message is not None:
                history = history + [result.message]
            reoriented = result.message is not None
        framed = {**body, "messages": history + list(notes), "stream": False}
        framed = assistruntime.retain_focus_bindings(framed, focused, focus_bindings)
        framed.pop("model", None)
        if remediation:
            framed[bodykeys.COMPLETION_REMEDIATION] = sess.completion_remediation_subject
        workspace_root = sess.workspace_root or _extract_cwd(raw)
        if workspace_root:
            # One live listing, after reductions and current notes, before role lowering.
            framed["messages"] = _ground_coder_view(framed["messages"], workspace_root)
            _note_survey_baseline(sess, workspace_root)
            _note_first_survey_files(sess, workspace_root, raw)
        # Root identity is a final framing invariant, not an exemption each
        # cleaner/reducer must implement. Rewrites may erase private work, but
        # cannot promote a later user turn into the original root partition.
        framed["messages"] = current.render(framed["messages"])
        if read_tail:
            framed["messages"] = framed["messages"] + read_tail
            _read_positions(framed["messages"], reads)
            framed[bodykeys.READ_FIT_CALLBACKS] = self._protected_read_callbacks(
                sess, rlog, root_task, index=index)
        if self._ctx.coder_role is not None:
            self._ctx.coder_role.apply(framed, rlog=rlog)
        return framed, reoriented

    def _protected_read_callbacks(self, sess, rlog, root_task, *, index=None, guidance=None):
        from .upstream import ReadFitCallbacks, _read_positions, ReadFitUnknown
        def compact(request, reads):
            messages = request.get('messages') or []
            cut = min(_read_positions(messages, reads))
            tail = messages[cut:]
            head, history = [], []
            for message in messages[:cut]:
                if message.get('role') in ('system', 'developer') or contextfloor._request_user(message):
                    head.append(message)
                else:
                    history.append(message)
            if not history:
                return request  # all remaining input is irreducible live authority/result
            if not self._ctx.self_compact:
                return None
            compacted = self._self_compact(history, sess, index, rlog, force=True,
                pinned_task=root_task, protected_prefix=True,
                frame_tokens=contextfloor.est_total(head + tail, request.get('tools')))
            if compacted == history:
                return None  # a declined/unavailable writer is not proof of irreducibility
            replacement = {**request, 'messages': head + compacted + tail}
            _read_positions(replacement['messages'], reads)
            return replacement
        return ReadFitCallbacks(compact, guidance)

    def _floor_would_drop(self, msgs: list[dict], rlog, frame_tokens: int = 0) -> bool:
        """Will the coder request built from ``msgs`` exceed its window, so the floor must DROP
        turns? Rolling memory runs first and should fold them instead (run 1792480002: with every
        early briefing rejected, the floor dropped 45-85 coder turns per call for ~20 minutes).
        ``msgs`` is the view rolling memory would send (its current summary, anchors, unfolded band
        and tail; the raw history only while no summary exists), never the raw history once a
        summary stands in for it.

        Sized as the floor sizes the coder request: the coder's OWN learned density (not another
        request kind's), its reply reserve, and ``frame_tokens`` for the parts the caller keeps
        outside ``msgs`` (system frame, root task, tool list). Unknown window abstains (False)."""
        sizing = self._coder_sizing(rlog)
        if sizing is None:
            return False
        window, reserve, density = sizing
        return (contextfloor.est_total(msgs, None) + frame_tokens) * density + reserve > window

    def _coder_sizing(self, rlog) -> tuple[int, int, float] | None:
        """The coder request's real window, reply reserve and learned density (real tokens per chars/4 estimated
        token) — the floor's own currency. None when the window is unknown or only guessed."""
        owner = getattr(self._ctx.coder_chat, "upstream", None)
        window = handoffdistill.window_of(self._ctx.coder_chat, rlog)
        if not window or owner is None:
            return None
        reserve = contextfloor.reserve_for({
            bodykeys.OUTPUT_RESERVE: getattr(self._ctx.coder_role, "output_reserve", None),
            "max_tokens": getattr(self._ctx.coder_role, "max_tokens", None),
        })
        loaded = owner.loaded_model(rlog) if callable(getattr(owner, "loaded_model", None)) else None
        return window, reserve, tokenratio.observed(loaded or "")

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
    header; else key on the complete initial user prelude, which is stable once
    assistant/tool work starts, even as cria rewrites what it sends the coder.

    The shared root owner retains unproven user banners AND their task. Guessing
    origin from tags lost real requests; using only the first plain banner made
    different tasks in one workspace collide. ``_history_root`` reads the same
    combined text. A later follow-up is history, not a replacement root."""
    if headers is not None:
        sid = headers.get("X-Cria-Session-Id")
        if sid:
            return f"sid:{sid}"
    root = selfcompact.root_text(messages)
    return f"task:{_task_key(root)}" if root is not None else "task:none"


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
    return completedwork.read_history(messages).text


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
        "generation_errors": sess.generation_errors,
        "generation_refusal_count": sess.unexecuted_nudges if sess.generation_errors else 0,
        # A negative satisfaction verdict is completion-critical session state. Persist it so a
        # restart cannot turn the same current evidence into a false completion.
        "latest_satisfaction": sess.latest_satisfaction,
        "latest_satisfaction_evidence": str(sess.latest_satisfaction_evidence or ""),
        "completion_remediation_subject": sess.completion_remediation_subject,
        "completion_remediation_reason": sess.completion_remediation_reason,
        "completion_remediation_nonwrite_ids": list(sess.completion_remediation_nonwrite_ids),
        "completion_remediation_nonwrite_seen": sess.completion_remediation_nonwrite_seen,
        "synthetic": sess.synthetic,  # a resumed single-item session must stay single-item, not
        #                               flip to multi-step framing after a restart
        "plan_off": sess.plan_off,
        "pilot_selection": list(sess.pilot_selection) if sess.pilot_selection is not None else None,
        "replan_uncovered": list(sess.replan_uncovered),
        "replan_uncovered_pending": sess.replan_uncovered_pending,
        # Optional additions preserve old state-file compatibility. The structured stream is what
        # keeps event freshness and success supersession truthful after a service restart; the set
        # remains for readers of the earlier schema.
        "refusal_events": (sess.refusal_events.to_dict()
                           if isinstance(sess.refusal_events, refusalledger.RefusalLedger) else None),
        "refused_names": sorted(sess.refused_names or set()),
    }


def _session_from_dict(d) -> PlanSession | None:
    """Rebuild a resumable PlanSession; None on any shape mismatch (never block startup)."""
    try:
        p = d["plan"]
        plan = Plan(id=str(p["id"]), task=str(p["task"]), created=str(p["created"]),
                    status=str(p.get("status", "in_progress")),
                    items=[PlanItem(text=str(it["text"]), done=bool(it.get("done")), note=it.get("note"))
                           for it in p["items"]])
        ledger = (refusalledger.RefusalLedger.from_dict(d.get("refusal_events"))
                  if isinstance(d.get("refusal_events"), dict) else None)
        legacy = {str(name) for name in (d.get("refused_names") or [])}
        uncovered = tuple(str(item) for item in (d.get("replan_uncovered") or []) if item)
        return PlanSession(plan=plan, summary=str(d.get("summary", "")),
                           generation_errors=list(d.get("generation_errors") or []),
                           unexecuted_nudges=int(d.get("generation_refusal_count", 0)),
                           prior_work=str(d.get("prior_work", "")),
                           verify_fails=int(d.get("verify_fails", 0)),
                           latest_satisfaction=(d.get("latest_satisfaction")
                                                if isinstance(d.get("latest_satisfaction"), bool) else None),
                           latest_satisfaction_evidence=str(d.get("latest_satisfaction_evidence", "")),
                           completion_remediation_subject=str(d.get("completion_remediation_subject", "")),
                           completion_remediation_reason=str(d.get("completion_remediation_reason", "")),
                           completion_remediation_nonwrite_ids=tuple(str(call_id) for call_id in
                                                                     (d.get("completion_remediation_nonwrite_ids") or []) if call_id),
                           completion_remediation_nonwrite_seen=bool(d.get("completion_remediation_nonwrite_seen")),
                           synthetic=bool(d.get("synthetic")),
                           plan_off=bool(d.get("plan_off")),
                           pilot_selection=(tuple(d["pilot_selection"])
                                            if isinstance(d.get("pilot_selection"), list) else None),
                           replan_uncovered=uncovered,
                           # State written before this acknowledgement bit existed has evidence but no
                           # receipt, so it must deliver once rather than silently treating it as spent.
                           replan_uncovered_pending=bool(d.get("replan_uncovered_pending", bool(uncovered))),
                           refusal_events=ledger,
                           refused_names=(ledger.active_names() if ledger is not None else legacy))
    except Exception:  # noqa: BLE001
        return None


def _plan_off_session(plan: Plan, briefing: str) -> PlanSession:
    """The plan-off session. ``synthetic`` means what it has always meant: DEGENERATE — one item,
    whose framing is the RAW TASK, driven by the single-item path (route-unify invariant 2).

    A synthesized plan used to be able to hold a SECOND item, a model-authored reading step. That
    made plan-off a two-step plan, which framed the raw task as "Do ONLY this step (2 of 2)" and put
    a cage around a mode that has no planner. The step is gone (2026-08-19,
    `docs/audits/base-vs-cria-footgun-patterns.md`), so this is one item again, always."""
    return PlanSession(plan=plan, synthetic=True, plan_off=True, prior_work=briefing)


def _synthetic_plan(task: str, clock=None) -> Plan:
    """A degenerate 1-item 'plan' for PLAN-OFF mode: the whole task is ONE implicit step whose item
    text IS the raw task. The PlanSession carries the ``synthetic`` flag (which selects raw-task
    framing + the single-item off-ramps); the Plan itself is an ordinary 1-item Plan. id/created match
    the Planner's convention (clock + task-key) so a resumed synthetic session keeps a stable id. Never
    mirrored to disk (no ``_persist_plan``) — it holds no decomposition, only the user's own words.

    THE READING STEP IS GONE (2026-08-19). A reasoner was asked, on every plan-off coding task,
    whether the task needed something read first, and its answer became a first plan item. Across 174
    captured authorings it answered NONE 42 times, named an EXTERNAL source 30 times, and 102 times
    said some version of "read the files already in the workspace" — the thing a coder does on its
    first turn unprompted, and in several captures had already done inside the same reply. The
    external case was already covered, and covered more generally, by `prompts/coder_system.txt`
    ("RESEARCH & INVESTIGATE FIRST"), which predates the step by eighteen days, costs no model call,
    and reaches every run in both arms.

    What the step cost instead: a second plan item, which is what made plan-off drive through the
    multi-item machinery and pin "Do ONLY this step (1 of 2)" to every coder turn. Measured in
    `docs/audits/base-vs-cria-footgun-patterns.md`: a run whose research step never cleared averaged
    24% (n=5) against 55% (n=55) for one that did — the failure mode is not the step firing, it is the
    step never letting go.

    The incident it was built for stands: run 1785805694 made ZERO web_fetch calls in 237 and wrote a
    resolver, unit tests, a live test and a README against an API it invented whole. What that run
    needed was the general instruction, which it now has."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    return Plan(id=f"{now.strftime('%Y%m%dT%H%M%S')}-{_task_key(task)[:8]}", task=task,
                created=now.isoformat(timespec="seconds"), items=[PlanItem(text=task)])


def _history_root(messages: list[dict]) -> tuple[str, str]:
    """``(text, fingerprint)`` of the conversation's ROOT — the complete initial user
    prelude (the SAME text the ``task:`` fallback ``session_key`` hashes). Once work
    starts, appending follow-ups never changes it. No user text proves harness origin. SOME harnesses replace it on a compaction (the summary becomes the root), which a
    changed fingerprint under a stable ``sid:`` key detects. Codex does NOT: it keeps every user
    message, this one included, and drops the assistant/tool work — so the fingerprint alone can
    never see a Codex compaction and ``observe_shape`` watches the history LENGTH as well.
    ``task:``-keyed sessions never detect rewrites
    (``_stable_session`` gates it): their key derives from this very root, so a rewritten root
    mints a new key and simply looks like a new session (recorded in docs/port-fidelity-audit.md)."""
    text = selfcompact.root_text(messages)
    return (text, hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()) if text is not None else ("", "")


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
    action log and 140 of 370 satisfaction prompts carry at least one. The label goes on
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
    receipt_labels = prompts.load_map("work_log_receipt_labels")
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
    messages = _image_review_view(messages, rlog)
    automatic = probegate.gate_call_ids(messages)
    scrubbed = list(probegate.clean_gate_results(
        _reasoner_session(messages), gate_plan, linked_only=True))
    denied_ids = {tid for m in scrubbed
                  if m.get("role") == "tool" and (tid := m.get("tool_call_id"))
                  and denial.refused(m)}
    # TELEMETRY ONLY: a result with no call id cannot be attributed, so nothing is ever labelled for it and
    # its outcome can never be proven. The count of those that LOOK marked is reported, never acted on.
    unpaired = sum(1 for m in scrubbed
                   if m.get("role") == "tool" and not m.get("tool_call_id")
                   and denial.is_denied(str(m.get("content") or "")))
    labelled = 0
    for m in scrubbed:
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = str(fn.get("arguments", ""))
                if _is_cria_scaffolding(args, automatic=tc.get("id") in automatic):
                    continue
                mark = ""
                if tc.get("id") in denied_ids:
                    mark = " " + DENIED_CALL_LABEL
                    labelled += 1
                # An argument's CR/LF is tool text, not a structural boundary cria may erase.  Keep
                # the existing call-only denial label on the physical `$` frame in that one case.
                frame_mark = mark if mark and ("\n" in args or "\r" in args) else ""
                suffix_mark = "" if frame_mark else mark
                lines.append(f"$ {fn.get('name')}{frame_mark} {args}{suffix_mark}")
                if tc.get("id"):
                    lines.append(prompts.fill(receipt_labels["call"],
                                              call_id=json.dumps(tc["id"], ensure_ascii=False)))
        elif role == "tool":
            # Packet parts are read as text: an observed image is its labelled observation, never a repr of pixels.
            c = (_msg_text_content(m) if isinstance(m.get("content"), list) else str(m.get("content") or ""))
            if c and not _is_cria_scaffolding(
                    c, automatic=m.get("tool_call_id") in automatic, keep_checks=keep_checks):
                if m.get("tool_call_id"):
                    label = prompts.fill(receipt_labels["result"],
                                         call_id=json.dumps(m["tool_call_id"], ensure_ascii=False))
                    lines.append(label)
                lines.append(f"  -> {c}")
    if rlog is not None and (labelled or unpaired):
        rlog.emit("loop.work_log_denied", level="info", labelled=labelled, unpaired=unpaired)
    return "\n".join(lines)


def _is_cria_scaffolding(text: str, *, automatic: bool = False,
                          keep_checks: bool = False) -> bool:
    """Only a producer-owned gate call/result can be internal orchestration.

    Marker bytes are not ownership: a coder's Maven command can print ``EXIT:1``
    and ordinary tool output can quote gate markers. Both must survive verbatim.
    The caller captures gate IDs before cleaning strips their provenance stamp.
    An owned gate's cleaned checker evidence is retained for completion judges,
    but its automatic request must never be attributed to the coder's work.
    """
    return automatic and not (keep_checks and text.lstrip().startswith(probegate.CHECKS_MARKER))


def _satisfaction_evidence(messages: list[dict], rlog=None, gate_plan=None,
                           chat_fn=None, role=None, workspace_root: str = "",
                           origin: _HandoffOrigin | None = None) -> str:
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
    def consume(log):
        # EXACT COUNTS OF THE FILES THE SESSION WROTE OR EDITED, appended after the (possibly
        # deduplicated) log: the escaped-JSON layout hides a file's byte-level shape from the judge.
        # Only the selected exact-form source may measure; other shared evidence stays independent.
        exact = next((d for d in assistruntime.current().pre_release
                      if isinstance(d, completionapproval.ExactFormDefinition)), None)
        measured = (filefacts.render(exact.measure(messages, _completion_measurement_services(workspace_root)))
                    if exact is not None else "")
        if measured:
            log = f"{log}\n\n{measured}"
        # The marker must START a user/system message. A tool can quote the same bytes,
        # but that is its result payload, not a handoff; keep it only in the paired work log.
        # Matching a bare substring in ANY role meant a coder that merely
        # parroted "⟦ctx:rollup⟧" — a marker it reads in its own context every turn — got its own claim
        # hoisted under "treat this as a record of what was already built" and handed to the done-judge as
        # authoritative history.
        summaries = [c.strip() for m in messages
                     if m.get("role") in ("user", "system")
                     and (c := _msg_text_content(m)).lstrip().startswith(
                         (CONTINUATION_MARKER, selfcompact.SUMMARY_MARKER, BRIEFING_OPEN))]
        if not summaries:
            return log
        # These records are heterogeneous. Only the session's actual hardener record
        # identifies a dropped-prose continuation or accepted model account. Unknown
        # history remains visible, but its own headings cannot authenticate it. If the
        # sole floor sheds the introducing source statement, the active question abstains.
        records = []
        for summary in summaries:
            known = isinstance(origin, _HandoffOrigin) and origin.matches_continuation(summary)
            records.append(prompts.render("satisfaction_history_source", record=summary,
                                          source=prompts.load("satisfaction_source_dropped" if known and origin.dropped
                                                              else "satisfaction_source_model" if known
                                                              else "satisfaction_source_unknown")))
        head = prompts.render("satisfaction_history", history="\n\n".join(records))
        tail = prompts.render("satisfaction_recent_actions", actions=log) if log.strip() else ""
        return "\n\n".join(part for part in (head, tail) if part)
    return _dedup_evidence(_work_log(messages, keep_checks=True, rlog=rlog, gate_plan=gate_plan),
                          rlog=rlog, chat_fn=chat_fn, role=role, _consume=consume)


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
        if isinstance(c, str) and denial.unlanded(m) and editrecovery.EDITFAIL in c:
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

# C44 B1 (review 9eaadebe): `server._harden_compaction_reply` prepends this to the compaction REPLY
# whenever no prose survived to ship (a validator rejection, or an empty/garbled writer after its
# own empty-briefing retry) but the deterministic appendices (fetch
# facts, workspace inventory, latest checks) were non-empty and so `summary` below is NOT blank.
# Without it `reframe_compaction` could not tell "a real model account, plus appendices" from "NO
# account, appendices only" and used the same "the handoff below is an ungrounded account" framing
# for both — false over pure re-derived ground truth (#5b; shipping 0084/0141, cart 0079, orders
# 0087/0191, feed 0052/0088 all shipped this way).
#
# C44 R1 (review 9eaadebe, second pass): `reframe_compaction` is the ONE place that INTERPRETS this
# marker, but it only runs at CONTEXT_FIXES and above, for a `user`-role message carrying a
# recognized Codex-preamble compaction turn — a lower engagement level, or a harness that stores the
# reply verbatim under a different role with no Codex preamble at all (C37's OWN harness-agnostic
# recognizer admits that shape on the way OUT), left the marker itself sitting in what the model
# reads. `indicators.strip_prose_dropped_marker` is the unconditional net for every shape
# `reframe_compaction` does not reach, called from `_strip_and_reframe_inbound` at EVERY level and
# from `Upstream._prep` at the wire (#24) — either alone stops it from crossing; both together mean
# no single missed call site can. Defined in `indicators` (a leaf module both `loop` and `upstream`
# can import without a cycle — `loop` already imports `upstream`) so both wire it without one
# importing the other; re-exported here so an existing `loop._PROSE_DROPPED_MARKER` /
# `loop.strip_prose_dropped_marker` reference keeps working unchanged. The spelling itself carries
# no literal "cria" (#17): if some THIRD path is ever missed too, what leaks is an odd bracketed
# token, not the name.
_PROSE_DROPPED_MARKER = indicators.PROSE_DROPPED_MARKER
strip_prose_dropped_marker = indicators.strip_prose_dropped_marker


@dataclass
class _HandoffOrigin:
    """One session's last actual hardener output, not an assertion supplied on the wire."""
    reply: str
    ledger: str
    dropped: bool
    continuation: str = ""
    # The workspace survey exactly as the briefing writer was shown it, rendered in the compaction
    # request itself. The next request's view is rebuilt from the conversation, and the compaction
    # just removed every survey from it, so this is the only listing of the disk the handoff
    # describes (see `_reorientation_inventory`).
    inventory: str = ""
    # The workspace root that listing describes: a listing never travels to another root.
    inventory_root: str = ""

    def matches_summary(self, summary: str) -> bool:
        return summary == self.reply or (self.dropped and summary == self.reply.removeprefix(_PROSE_DROPPED_MARKER + "\n"))

    def matches_continuation(self, text: str) -> bool:
        # Legacy inventory canonicalization changes only the generated footer.
        # That footer is not the handoff or its ledger; compare the exact produced core.
        return bool(self.continuation) and modelview.continuation_core(text).rstrip() == modelview.continuation_core(self.continuation).rstrip()


def _workspace_is_empty(cwd: str) -> bool:
    """True when the advertised workspace does not exist or is empty. The continuation reframe's
    'the files that should already exist / do NOT recreate' claim is then objectively FALSE — the
    drift ROOT: a fresh/restarted session over an empty cwd took that claim at face value and sent
    the model hunting for its 'prior work' in sibling directories (the codex-handles drift).
    Conservative: an unknown cwd ('.'/none — the harness advertised no workspace) or ANY entry at
    all (even hidden) → NOT empty, so a repo with real work keeps the normal 'build on it' reframe."""
    if not cwd or cwd == ".":
        return False
    view = wsview.current(cwd)
    top = view.listdir(cwd)
    if top is not None and view.listed_everything(cwd):
        # ...AND THE LISTING COULD NAME EVERYTHING. `listdir` returns what cria KNOWS, and a survey
        # that folded the root to a count returns `[]` — which read as "empty" for a workspace with
        # 420 files in it. The conservative direction this function already documents applies to a
        # bounded listing exactly as it does to an unanswered one (#11b).
        return not top
    # NOT SURVEYED IS NOT EMPTY. The claim this decides is "the files that should already exist" —
    # calling a workspace nobody has looked at empty would replace one false claim with another, so
    # an unanswered question keeps the normal reframe (the conservative direction this already had
    # for an unreadable directory).
    return False


def reframe_compaction(messages: list[dict], *, origin: _HandoffOrigin | None = None) -> tuple[list[dict], bool]:
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
            # C44 B1: `summary` reads non-blank whenever the deterministic appendices (fetch facts,
            # workspace inventory, checks) survived even though NO model prose did — the common
            # shape (13 of 18 real row-p28 rejections), not the rarer fully-blank one. Detect that
            # from the session's actual hardener output, not a marker copied into prose. Strip the
            # private plumbing marker before the model reads it (#17), and route a confirmed drop so the
            # re-derived ground truth is presented as retained fact, never as "the handoff below is an
            # ungrounded account" (#5b) — that sentence is true only when a model actually wrote one.
            known = isinstance(origin, _HandoffOrigin) and origin.matches_summary(summary)
            prose_dropped = bool(known and origin.dropped)
            # The private spelling is plumbing, NOT authentication. An unknown or
            # model-authored copy cannot select the deterministic source branch.
            if _PROSE_DROPPED_MARKER in summary:
                summary = summary.replace(_PROSE_DROPPED_MARKER, "", 1).lstrip("\n")
            if prose_dropped and summary.strip():
                tmpl = "compaction_reframe_dropped_facts"
            elif prose_dropped or not summary.strip():
                tmpl = "compaction_reframe_dropped"
            else:
                tmpl = template
            # Tag with a ⟦ctx:⟧ marker so classify.latest_user_text skips it — this reframe is cria
            # scaffolding, not the user's task; classifying it flips a coding session onto the reasoner.
            reframe = prompts.render(tmpl, summary=summary, cwd=cwd,
                                     tool_results=prompts.load("continuation_results_reference").strip())
            content = f"{CONTINUATION_MARKER} {reframe}"
            if known:
                origin.continuation = content
            out.append({**m, "content": content})
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
    definition = next(iter(assistruntime.current().bindings(preamblepolicy.DEFINITION.policy.stage)), None)
    if definition is None:
        return m
    return definition.execute(preamblepolicy.PreambleInput(m, wsview.current)).message


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
    return preamblepolicy.workspace_instructions(cwd, relayed, wsview.current).text or None


def _reframe_preamble_text(text: str) -> str | None:
    message = {"role": "user", "content": text}
    framed = reframe_preamble(message)
    return framed["content"] if framed is not message else None


def _is_serialized_plan_cursor(message: dict) -> bool:
    """Whether a replayed message is cria's own active ordered-plan frame.

    Harnesses may preserve an earlier system frame as a user turn.  During remediation that old
    frame is still an active cursor unless removed alongside the newly-built one.  Match the exact
    prompt-file-owned introduction plus its cursor token, never a user mention of a plan.
    """
    content = str(message.get("content") or "") if isinstance(message, dict) else ""
    prefix = prompts.load("step_framing").split("{{COMPLETED}}", 1)[0]
    current = content.startswith(prefix)
    legacy = (content.startswith("You are completing a larger task")
              and "This plan was created by another model" in content)
    return (current or legacy) and ("Prioritize this step (" in content or "Do ONLY this step (" in content)


def record_coder_preframe(rlog, sess: PlanSession, item: PlanItem | None, idx: int, total: int, *, driver: str) -> None:
    """Record the live state immediately before a target coder frame is composed.

    This is evidence only: it reads the already-bound harness survey and session fields, attaches
    the receipt to the request log for the wire owner, and never adds a field or message to the
    model body.  ``None`` preserves every unavailable survey/verdict fact as unknown rather than
    translating it into absence.
    """
    root = getattr(sess, "workspace_root", "") or ""
    view = wsview.current(root) if root else None
    subject = getattr(sess, "last_gap_subject", "") or ""
    observation = getattr(sess, "last_gap_observation", "") or ""
    surveyed = view.surveyed if view is not None else False
    state = {
        "pilot_assists": list(assistruntime.current().selected),
        "driver": driver,
        "cursor": {"index": idx, "total": total, "text": getattr(item, "text", "") if item else ""},
        "wsview": {
            "root": root or None,
            "surveyed": surveyed,
            # ``View.complete`` defaults True before any survey lands.  Completeness is therefore
            # unknown until a harness survey establishes it; recording that default would turn
            # unavailable/mismatched state into a false claim that absence is meaningful.
            "complete": view.complete if surveyed else None,
            "observation_fingerprint": view.observation_fingerprint if surveyed else None,
        },
        "remediation": {
            "armed": bool(getattr(sess, "completion_remediation_subject", "")),
            "subject": getattr(sess, "completion_remediation_subject", "") or None,
            "reason": getattr(sess, "completion_remediation_reason", "") or None,
        },
        "gate": {
            "drive_count": getattr(sess, "drive_count", None),
            "last_gate_red": getattr(sess, "last_gate_red", None),
            "gate_stall": getattr(sess, "gate_stall", None),
            "gate_fresh": getattr(sess, "gate_fresh", None),
            "done_probe": getattr(sess, "done_probe", None),
            "completion_checks": getattr(sess, "completion_checks", None),
        },
        # ``last_gap_subject`` is populated only for the validated missing-file path.  The source
        # is retained as the exact survey generation that justified that typed absence; no subject
        # means this field remains null rather than guessing from rendered nudge prose.
        "absence_verdict": ({"diagnosis_kind": "missing_file", "subject": subject,
                             "workspace_observation_fingerprint": observation or None}
                            if subject else None),
    }
    rlog.coder_preframe = state
    rlog.emit("loop.coder_preframe", state=state)


def _required_coder_base(messages, *, tools=None, prior_work="", workspace_root=None,
                         gate_plan=None, suspend_cursor=False, reframe=False, rlog=None):
    """Required source assembly with an explicit selected note-only menu adapter."""
    runtime = assistruntime.current()
    menu = toolmenu.selected_policies(runtime.definitions)
    def menu_note(menu_tools):
        result = menu.instructions(toolmenu.InstructionInput(menu_tools, messages=None, configured=True), rlog)
        return result.note if result.applied else None
    return steppreparation.assemble_base(steppreparation.BaseInput(
        messages, steppreparation.BaseServices(_strip_cria_file_ops, _msg_text_content,
            lambda message: reframe_preamble(message) if reframe and runtime.engagement_level >= 4 else message,
            _is_serialized_plan_cursor, menu_note=menu_note),
        tools, prior_work, workspace_root, gate_plan, suspend_cursor))


def _frame_for_item(messages: list[dict], item: str, summary: str, idx: int, total: int, prior_work: str = "", tools=None, synthetic: bool = False, gate_plan=None, workspace_root: str | None = None, gate_red: bool = False, remediation: bool = False, suppress_plan_cursor: bool = False) -> list[dict]:
    """Compatibility frame; required assembly and optional step wording have source owners.

    Production supplies explicit config consent in the common preparation path.
    Calling this planned-frame library API is the legacy standalone opt-in.
    """
    runtime = assistruntime.current()
    base = _required_coder_base(messages, tools=tools, prior_work=prior_work,
        workspace_root=workspace_root, gate_plan=gate_plan, reframe=True,
        suspend_cursor=remediation or suppress_plan_cursor)
    if remediation and not synthetic:
        return steppreparation.with_directive(base, prompts.load("completion_remediation"),
                                             prompts.load("plan_ack"))
    definition = next(iter(runtime.bindings(steppreparation.DEFINITION.policy.stage)), None)
    selected = (steppreparation.StepSelection.opt_in(definition) if not synthetic
                else steppreparation.StepSelection())
    return selected.prepare(steppreparation.StepInput(base, item, summary, idx, total,
        step_artifacts_on_disk, gate_red, not synthetic, synthetic)).messages


# A file-looking token in a step's text: `test_resolve_handle.py`, src/main.go, "README.md".
_STEP_ARTIFACT = groundtruth._STEP_ARTIFACT   # defined one level down; see the note there


def _caller_span_hint(persona_at: int, persona: str) -> dict:
    """Where the harness's BASE instructions sit in the coder system message, carried for the context
    floor (principle 24): it may reduce exactly this span, labelled, before it folds any conversation
    turn. The system message is `coder_system + "\\n\\n" + caller + ...`, so the offset is anchored after
    cria's own text, never found by searching. Empty when the caller sent no persona (the caller's
    configured developer items are never in the span)."""
    if persona_at < 0:
        return {}
    return {bodykeys.CALLER_SPAN: {"start": len(prompts.load("coder_system")) + 2 + persona_at,
                                   "text": persona}}


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
            resolved = groundtruth.resolve(root, rel)
        except (OSError, ValueError):
            continue
        if wsview.current(root).isfile(resolved) is True:
            out.append(rel)
    return out


def _repair_note(item: str, workspace_root: str | None, gate_red: bool) -> str:
    """Legacy note view of the selected step owner's additive presence correction."""
    return _item_prompt(item, "", 1, 1, workspace_root, gate_red).removeprefix(
        _item_prompt(item, "", 1, 1, workspace_root, False))


def _item_prompt(item: str, summary: str, idx: int, total: int,
                 workspace_root: str | None = None, gate_red: bool = False) -> str:
    """Standalone planned-frame opt-in; source owns wording and artifact judgment."""
    definition = next(iter(assistruntime.current().bindings(steppreparation.DEFINITION.policy.stage)), None)
    base = steppreparation.BaseFrame([{"role": "system", "content": ""}], "", None,
                                    workspace_root=workspace_root)
    return steppreparation.StepSelection.opt_in(definition).prepare(steppreparation.StepInput(
        base, item, summary, idx, total, step_artifacts_on_disk, gate_red, True)).prompt


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
        shapes = fetchfacts.shapes_text(_fetch_facts(entry)[2])
        if shapes.strip():
            out.append(shapes)
    for m in messages or []:
        if m.get("role") == "tool":
            body = _content_text(m.get("content"))
            if body.strip():
                out.append(body)
    return out


def _resolve_named_file(view, name: str, task: str):
    """``(workspace-relative path, exists)`` for a file name the model WROTE, or the refusal reason.

    ONE file or nothing — the model's words are never turned into a guess: an exact path wins; else a
    suffix match over the listing, which must be unique and which is only trusted when the listing is
    complete (a folded directory might hold a second `Importer.java`). A name that matches nothing is
    a NEW file only when the task itself contains it verbatim — the operator's own words name the
    deliverable, so cria is not choosing a location — and its parent directory is known to exist."""
    rel = view.rel(name)
    if rel is None or not rel:
        return "outside_workspace"
    if view.isdir(rel) is True:
        return "names_a_directory"
    if "/" in rel and view.isfile(rel) is True:
        return rel, True                     # a qualified path that exists IS the file
    # EVERYTHING ELSE needs the whole tree: a bare name is unique only over a COMPLETE, UNFOLDED listing
    # (a folded directory is listed as a count and might hold a second `Importer.java`), a suffix match
    # likewise, and "no such file" — the new-file branch — is only a fact when nothing is hidden. A
    # qualified name on a partial listing is refused for the same reason.
    if not view.complete or view.folded:
        return "listing_incomplete"
    listed = [r for r in (view.rel(e.path) for e in (view.files() or [])) if r]
    hits = [r for r in listed if r == rel or r.endswith("/" + rel)]
    if len(hits) > 1:
        return "ambiguous_path"
    if len(hits) == 1:
        return hits[0], True
    # A NEW file: the task itself must name this very path as a whole token (`REVIEW.md` is not named by
    # a task that says `docs/REVIEW.md`; the same test F7 uses for a task-named subject).
    if not _subject_is_exact_in_quote(rel, task or ""):
        return "unnamed_new_file"
    parent = posixpath.dirname(rel)
    if parent and view.isdir(parent) is not True:
        return "unknown_parent"
    return rel, False


def _coder_has_seen(view, rel: str, sess, messages: list[dict]) -> bool:
    """Does the coder HOLD this workspace file's whole text — a whole read whose result is still in the
    conversation, or its own whole write (the ledger of those is durable: cria composed the bytes)?

    A RANGED READ IS NOT THE FILE, and a read whose result the harness has since compacted away is not
    in the window (phi4 A4 0047: `pom.xml` lines 1-8 of 29, then a whole-file overwrite; seg-10: the
    ledger said "read" over a window with no text in it). The durable read ledger is therefore not
    consulted here — it still serves the ⟦ctx:facts⟧ listing, where "you looked once" is the fact."""
    seen = _extract_whole_reads(messages or [], view)
    seen |= set(_extract_writes(messages or []))
    seen |= set(getattr(sess, "written_files", None) or {})
    # A WHOLE TEXT HANDED TO THE CODER THIS TURN (the ⟦ctx:facts⟧ anchor's restored block) is the whole
    # read the hold asks for: the exact current bytes, in the conversation the coder is answering.
    seen |= set(getattr(sess, "restored_current", None) or {})
    return any(view.rel(p) == rel for p in seen)


def _shell_commands_with_results(messages: list[dict]):
    """``(command text, result text)`` for each shell-family call (a ``cmd``/``command`` argument) whose
    result was returned and was not a refusal — a command the coder actually RAN."""
    for _tid, cmd, res in _shell_runs(messages):
        yield cmd, res


def _shell_runs(messages: list[dict]):
    """:func:`_shell_commands_with_results` with the tool-call id in front."""
    from . import denial
    from . import denial as _den
    paired = set(_den.paired_results(messages))   # canonical call/result pairing: ambiguous results attribute nothing
    calls: dict = {}
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = _args_of(fn.get("arguments") or "")
            cmd = args.get("cmd") if args.get("cmd") is not None else args.get("command")
            if isinstance(cmd, list):
                cmd = " ".join(str(x) for x in cmd)
            if isinstance(cmd, str) and tc.get("id") and "___CRIA_" not in cmd:
                calls[tc["id"]] = cmd
        tid = m.get("tool_call_id") or m.get("call_id")
        if tid in calls and tid in paired:
            c = m.get("content") if m.get("content") is not None else m.get("output")
            if isinstance(c, str) and c.strip() and not denial.refused(m):
                yield tid, calls[tid], c


def _command_names_path(command: str, rel: str) -> bool:
    """Does ``command`` name ``rel`` as a whole path (relative, or as the tail of an absolute one)?"""
    return re.search(rf"(?<![\w.-]){re.escape(rel)}(?![\w/-]|\.\w)", command) is not None


_CAT_FLAGS = frozenset("nAbsvETe")


def _prints_whole_file(command: str, rel: str, view=None) -> bool:
    """Is ``command`` — parsed, never guessed — a plain ``cat [-n…] FILE…`` that prints ``rel`` whole?

    Only that shape: no pipe, redirect, substitution or other program, because anything else may cut,
    filter or write the file, and a command that merely NAMES a path is not a read of it. Commands joined
    by `;`, `&&` or newlines are each judged alone, and a `bash -c "..."` wrapper is looked through.
    Anything unparseable abstains: no credit."""
    import shlex
    for line in command.splitlines():
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            toks = list(lex)
        except ValueError:
            continue
        segs, cur = [], []
        for t in toks:
            if t in (";", "&&"):
                segs.append(cur)
                cur = []
            else:
                cur.append(t)
        segs.append(cur)
        if any(seg[:1] in (["cd"], ["pushd"]) for seg in segs):
            continue                                   # a relative name no longer names the same file
        for seg in segs:
            if len(seg) == 3 and seg[0] in ("bash", "sh") and seg[1] in ("-c", "-lc"):
                if _prints_whole_file(seg[2], rel, view):
                    return True
                continue
            if len(seg) < 2 or seg[0] != "cat":
                continue
            args = seg[1:]
            files = [a for a in args if not (a.startswith("-") and len(a) > 1 and set(a[1:]) <= _CAT_FLAGS)]
            if files and not any(re.search(r"[|<>&;()`$*?\[\]{}~]", a) for a in args) \
                    and any(_is_the_file(f, rel, view) for f in files):
                return True
    return False


def _is_the_file(name: str, rel: str, view=None) -> bool:
    """Does the path a command spells name exactly the workspace file ``rel``: the relative path, `./`
    and it, or an absolute path the view resolves to it. A path that merely ENDS in the name — `sub/pom.xml`,
    `../other/pom.xml`, `/tmp/pom.xml` — is another file."""
    if name == rel or name == "./" + rel:
        return True
    return view is not None and name.startswith("/") and view.rel(name) == rel


def _ran_a_command_naming(messages: list[dict], rel: str, view=None) -> bool:
    """Did the coder run a command that PRINTED the whole of ``rel`` (:func:`_prints_whole_file`)?
    The name is kept for its callers; a command that only mentions the path no longer counts."""
    return any(_prints_whole_file(cmd, rel, view) for cmd, _res in _shell_commands_with_results(messages))


# WHEN TO ASK / WHAT TO SAY, never a verdict (principle 8). A whole-file write over a file of at least
# SHRINK_MIN_LINES non-blank lines is measured two ways. FRAGMENT: the candidate has at most half the file's
# lines and repeats under half its distinct lines — the class put to the judge and held (16 of 1,156 corpus
# writes, 1.4%). REMOVAL: it removes at least half the file's lines whatever the candidate's length — phi4 A9,
# a 69-line rewrite of the 114-line Importer.java that lost summarize/Summary/totals/main — which is only
# reported, as facts on the landed write: a line threshold cannot say whether a whole file is wanted.
# Measured on 1,182 corpus writes: 102 (8.6%) remove >= half the lines; 49 (4.1%) once files the coder
# created are exempt (the distinct-lines variant fires on 126, its extras long additive rewrites).
# Direct compatibility names; the source owner measures and formats these facts.
SHRINK_MIN_LINES = shrinkprotection.SHRINK_MIN_LINES
SHRINK_OPENERS_MAX = shrinkprotection.SHRINK_OPENERS_MAX
shrink_measure = shrinkprotection.shrink_measure
_openers_fact = shrinkprotection.openers_fact


def whole_file_ruling(answer: str) -> str:
    """The ruling of the closed WHOLE_FILE / OTHER question: the answer's FIRST word, exactly (the
    convention `confirm_applies` uses) — a model that answers `WHOLE_FILE` and explains itself is not
    refused for its politeness; `WHOLE_FILE_MAYBE`, `NOT_WHOLE_FILE` and prose that merely mentions the
    word have another first word and are no ruling."""
    head = answer.upper().split()[0].strip(".,:;`*\"'") if answer.split() else ""
    return head if head in ("WHOLE_FILE", "OTHER") else answer.strip().upper()[:40]


def unread_target_fact(sess, view, path: str, messages: list[dict]) -> str:
    """What cria MEASURED about a file a write names, or "" — never an instruction.

    The workspace view must PROVE the file exists (three-valued: an unanswered survey is silence, not
    "exists"), and the session's read/write record plus the conversation must hold no read or write of
    it. This is the structure that separates a rewrite of a file the coder has seen from an
    invention under a real file's name — the same test the pasted-file recovery applies
    (`unread_existing_file`), here said TO the coder instead of silently refusing (phi4 A2: pom.xml,
    980 bytes, never shown; the coder regenerated a write with placeholder content seven times)."""
    if view is None or not getattr(view, "surveyed", False) or not path:
        return ""
    rel = view.rel(path)
    if not rel or view.isfile(rel) is not True:
        return ""
    if _coder_has_seen(view, rel, sess, messages):
        return ""
    # A SHELL COMMAND THAT NAMES THE FILE MAY HAVE READ IT (`cat pom.xml`): cria cannot tell a read
    # from any other use of a path, so it does not claim the coder never looked (#5b, #11b).
    if _ran_a_command_naming(messages, rel, view):
        return ""
    labels = prompts.load_map("unread_target_fact")
    size = view.size(rel)
    return prompts.fill(labels["sized" if size is not None else "unsized"], path=rel, size=size)


def _note_survey_baseline(sess, root) -> None:
    """Remember the first COMPLETE survey's file sizes and mtimes, once per session. An incomplete or
    folded listing is no baseline: a later "unchanged" would be measured against a partial picture."""
    if getattr(sess, "survey_baseline", None) is not None or not root:
        return
    view = wsview.current(root)
    if not view.surveyed or not view.complete or view.folded:
        return
    sess.survey_baseline = {r: (e.size, e.mtime) for e in view.files() or []
                            if (r := view.rel(e.path))}


def _note_first_survey_files(sess, root, messages=()) -> None:
    """Remember, once per session, the files the FIRST survey that landed LISTED — folded or incomplete
    included, because a listed file is proven present (a partial listing only fails to prove absence).

    A file a landed coder `write_file` created before that survey rode back is left out: the first
    survey usually arrives on the result of the coder's first command, so the file that command wrote is in
    the listing without having been there at the start. `shrinking_write_check` reads this as "existed
    before the coder touched anything" — the progress it protects is not the coder's own."""
    if getattr(sess, "first_survey_files", None) is not None or not root:
        return
    view = wsview.current(root)
    if not view.surveyed:
        return
    own = {r for p in _extract_writes(list(messages)) if (r := view.rel(p))}
    sess.first_survey_files = {r for e in view.files() or [] if (r := view.rel(e.path)) and r not in own}


def _measured_gap_facts(sess, reply: str) -> str:
    """What cria MEASURED about a session whose completion check named no gap — never what to do.

    The constant `done_no_named_gap` says nothing the coder can act on, and a call-less coder that is
    handed the same bytes every cycle answers with the same bytes (A1: twelve cycles, one steer). Two
    observations are cria's own and are true now: (1) which of the files the coder READ are byte-for-
    byte unchanged on disk (size and mtime) since the first complete listing, and which changed — from
    the workspace view, so it abstains (says nothing) when no complete baseline or current listing
    exists (#11b); (2) whether the last reply carried fenced code and no call, from the same parse the
    `unexecuted_write` nudge uses. No file, tool or action is named as a thing to do (#2, #5b)."""
    labels = prompts.load_map("done_measured_facts")
    lines = []
    root = getattr(sess, "workspace_root", None)
    base = getattr(sess, "survey_baseline", None)
    view = wsview.current(root) if root else None
    if base and view is not None and view.observation_fingerprint is not None:
        now = {r: (e.size, e.mtime) for e in view.files() or [] if (r := view.rel(e.path))}
        same, moved = [], []
        for rel in sorted({view.rel(p) for p in getattr(sess, "read_files", None) or {}} - {None}):
            if rel in base and rel in now:
                (same if now[rel] == base[rel] else moved).append(f"  {rel} ({now[rel][0]} bytes)")
        if same:
            lines.append(prompts.fill(labels["unchanged"], files="\n".join(same)))
        if moved:
            lines.append(prompts.fill(labels["changed"], files="\n".join(moved)))
    blocks = massage.fenced_file_blocks(reply or "")
    if blocks:
        langs = ", ".join(dict.fromkeys(b["lang"] or "untagged" for b in blocks))
        lines.append(prompts.fill(labels["reply"], count=len(blocks), langs=langs,
                                  lines=sum(1 for b in blocks for l in b["lines"] if l.strip())))
    return (labels["header"] + "\n" + "\n".join(lines)) if lines else ""


def _unnamed_gap(sess, reply: str) -> str:
    """`done_no_named_gap`, plus the facts cria measured (see :func:`_measured_gap_facts`)."""
    facts = _measured_gap_facts(sess, reply)
    base = prompts.load("done_no_named_gap")
    return f"{base}\n\n{facts}" if facts else base


def _is_reading_step(sess, item) -> bool:
    """Is the step in flight the plan-off READING step — the one that produces no files?

    Its own prompt says so in as many words: *"It produces nothing — no script, no tests, no files."*
    cria has always known this deterministically (the hand-back below has used the same test since
    2026-08-04); it just had no name, so no other seat could ask."""
    return bool(getattr(sess, "plan_off", False) and item is not None
                and item.text != getattr(sess.plan, "task", None))


def fence_is_self_quote(fence_lines: list[str], injected_norm: list[str]) -> bool:
    """A fence the coder copied out of what it was SHOWN is not an unsaved file. Walked on
    mellum2 1786196176 calls 0013/0020: two research summaries quoted the ⟦ctx⟧ response-shape
    block (the ```ts schema cria itself injected), the nudge fired both times — "your last
    message contained the file's contents as text" — and the coder, told to persist a file it
    never drafted, tried to overwrite the read-only spec spill. cria HOLDS every string it
    injected, so identity is a comparison, not a judgment: whitespace-normalized containment,
    with a floor so a two-token overlap cannot exempt a real file. ``injected_norm`` is the
    whitespace-stripped haystack. ONE owner: `unexecuted_write` (the nudge) and the text-write
    recovery (`Loop._recover_text_write`) must agree on what a quote is."""
    blob = "".join("".join(l.split()) for l in fence_lines)
    return len(blob) >= 80 and any(blob in inj for inj in injected_norm)


def _pasted_block_paths(reply: str) -> list[str]:
    """The paths the model's own binding line names for the first file-length block of ``reply`` —
    ``[]`` when there is no such block (a block with no line above it names nothing)."""
    for b in massage.fenced_file_blocks(reply or ""):
        if sum(1 for l in b["lines"] if l.strip()) >= UNEXECUTED_WRITE_LINES:
            return massage.binding_paths(b["binding"]) if b["binding"] else []
    return []


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
        return fence_is_self_quote(fence_lines, injected_norm)

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
TASK_COMPLETE_TOOL = admission.TASK_COMPLETE_TOOL


def _tool_name(tc) -> str:
    """The name of a tool CALL or tool SCHEMA (both nest it under `function`)."""
    fn = (tc.get("function") or tc) if isinstance(tc, dict) else {}
    return fn.get("name") or ""


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


def _same_workspace_path(one: str, two: str, root: str | None) -> bool:
    """Whether two tool-path spellings designate one workspace path, without guessing a cwd."""
    if not one or not two:
        return False
    if os.path.normpath(one) == os.path.normpath(two):
        return True
    if not root:
        return False
    return os.path.normcase(os.path.normpath(groundtruth.resolve(root, one))) == \
        os.path.normcase(os.path.normpath(groundtruth.resolve(root, two)))


def _observed_successful_write(messages: list[dict], subject: str, root: str | None) -> bool:
    """True only when a paired tool result confirms a write to ``subject`` landed.

    A forwarded call is intent, not a completed action.  The writeproxy emits its exact ``Wrote
    PATH`` confirmation only after its atomic write succeeds; correlate that authoritative result
    with the original call before releasing a completion remediation.
    """
    return completiondiagnosis.observed_successful_write(
        messages, subject, _diagnosis_remediation_services(root))


def _arm_completion_remediation(sess: GuardState, subject: str, reason: str) -> None:
    """Start a typed remediation with no presumed delivery or observed outcome."""
    definition = assistruntime.current().completion_diagnosis
    if definition is not None:
        completiondiagnosis._remediation_result(definition.arm(sess, subject, reason),
            (completiondiagnosis.RemediationStatus.PENDING, completiondiagnosis.RemediationStatus.NOT_APPLICABLE))


def _record_remediation_delivery(sess: GuardState, coder: dict) -> None:
    """Remember only supported inspection calls from the reply to a remediation body."""
    definition = assistruntime.current().completion_diagnosis
    if definition is not None:
        completiondiagnosis._remediation_result(definition.acknowledge(
            sess, coder, _diagnosis_remediation_services(getattr(sess, "workspace_root", ""))),
            (completiondiagnosis.RemediationStatus.NOT_APPLICABLE, completiondiagnosis.RemediationStatus.ACKNOWLEDGED))


def _nudge_after_remediation_nonwrite(sess: GuardState, messages: list[dict], rlog) -> None:
    """One additive follow-up after a delivered remediation's own non-write result.

    Tool-result identity, rather than a tool-name or prose heuristic, keeps unrelated history and
    undecidable/absent diagnoses silent.  This never settles the remediation: only its matching
    successful write can do that.
    """
    definition = assistruntime.current().completion_diagnosis
    if definition is not None:
        completiondiagnosis._remediation_result(definition.follow_up(
            sess, messages, _diagnosis_remediation_services(getattr(sess, "workspace_root", ""), rlog)),
            (completiondiagnosis.RemediationStatus.NOT_APPLICABLE, completiondiagnosis.RemediationStatus.PENDING,
             completiondiagnosis.RemediationStatus.FOLLOW_UP))


def _settle_completion_remediation(sess: GuardState, messages: list[dict], rlog) -> None:
    """Release a typed missing-file remediation after, and only after, its observed write."""
    definition = assistruntime.current().completion_diagnosis
    if definition is not None:
        completiondiagnosis._remediation_result(definition.settle(
            sess, messages, _diagnosis_remediation_services(getattr(sess, "workspace_root", ""), rlog)),
            (completiondiagnosis.RemediationStatus.NOT_APPLICABLE, completiondiagnosis.RemediationStatus.PENDING,
             completiondiagnosis.RemediationStatus.SETTLED))


def _write_path(fn: dict) -> str | None:
    """The file a single tool call writes; None for non-write calls. Covers the named write tools AND
    a SHELL-native write (redirect/heredoc/`tee`), so the wheel-spin guard counts a model rewriting
    one file straight through the shell the same as a write_file."""
    name = fn.get("name")
    # WHAT THE CODER CALLED, NOT WHAT CRIA LOWERED IT TO. A shell call carrying cria's sentinel is
    # cria's own composition — a heredoc, a curl, and on writes/edits/lists the workspace survey
    # program riding along — and scanning those bytes for a redirect target reads cria's text as the
    # coder's work. The survey contains `if len(files) > FOLD_AT:`; the redirect matcher read that
    # `>` as one and reported `FILE FOLD_AT — does NOT exist on disk` to the model, naming one of
    # cria's own constants as a file (feed-pipeline-java x nemotron-elastic 1787346816). The
    # sentinel holds the call that was actually made, exactly, so ask it (#12).
    lowered = writeproxy._command_of(fn.get("arguments") or "")
    original = writeproxy.original_call(lowered)
    if original is not None:
        fn, name = original, original.get("name")
    elif writeproxy.is_crias_own(lowered):
        # cria's own composition that is nobody's tool call — the gate script. Scanning it for a
        # redirect target reads cria's text as the coder's work; the survey program it carries ends
        # up named as a file the coder wrote (#5b).
        return None
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
# Raw-blob variants for UNPARSEABLE args (a truncated write is exactly when a model is spiralling on
# one file, so the streak guard must still see the target). Quotes and newlines are still escaped
# there, so tolerate a leading backslash-quote — and never quote-mask a raw blob: the JSON string
# delimiters would mask the whole command away.
_REDIRECT_TARGET_RAW_RE = re.compile(r'(?<![-=<>\d])>{1,2}\s*(?!/dev/|&)\\?["\']?([\w./~$-]+)')
_TEE_TARGET_RAW_RE = re.compile(r'\btee\b\s+(?:-a\s+)?\\?["\']?(?!-)([\w./~$-]+)')


def _shell_write_target(args) -> str | None:
    text = _command_text(args)
    if text is None:  # an undecodable JSON FRAGMENT — scan the raw blob, escape-tolerant
        blob = args if isinstance(args, str) else ""
        m = _REDIRECT_TARGET_RAW_RE.search(blob) or _TEE_TARGET_RAW_RE.search(blob)
        return m.group(1) if m else None
    masked = _QUOTED_SPAN_RE.sub("", text)  # drop quoted spans so a `>` inside them isn't a redirect
    m = _REDIRECT_TARGET_RE.search(masked) or _TEE_TARGET_RE.search(masked)
    return m.group(1) if m else None


def _check_pilot_runtime(state: GuardState, runtime: assistruntime.AssistRuntime) -> None:
    if not isinstance(runtime, assistruntime.AssistRuntime):
        raise ValueError("Invalid pilot assist runtime")
    if ((state.pilot_selection is not None and state.pilot_selection != runtime.selected)
            or (state.pilot_binding is not None and state.pilot_binding != runtime)):
        raise ValueError("Pilot assist selection cannot change during an active task")


def _pin_pilot_runtime(state: GuardState, runtime: assistruntime.AssistRuntime,
                       origin: GuardState | None = None) -> None:
    _check_pilot_runtime(state, runtime)
    if origin is not None:
        _check_pilot_runtime(origin, runtime)
    if state.pilot_selection is None:
        state.pilot_selection = (origin.pilot_selection if origin is not None
                                 and origin.pilot_selection is not None else runtime.selected)
    if state.pilot_binding is None:
        state.pilot_binding = (origin.pilot_binding if origin is not None
                               and origin.pilot_binding is not None else runtime)


def _repository_selection(gs: GuardState) -> repositorychecks.Selected:
    # Unknown-origin pending fixtures require consent NOW, not invented historic provenance.
    if (not assistruntime.is_bound() and gs.pilot_selection is None and gs.pilot_binding is None
            and (gs.periodic_probe or gs.awaiting_probe or gs.done_probe)):
        raise ValueError("Pending repository policy use requires an explicitly bound runtime")
    runtime = assistruntime.current()
    _pin_pilot_runtime(gs, runtime)
    return repositorychecks.Selected(runtime.repository_checks)


class _SilentCheckLog:
    def emit(self, event, **fields):
        pass


def _repository_input(body, rlog, *, workspace_root=None, driver=repositorychecks.Driver.TASK,
                      trigger=repositorychecks.Trigger.PERIODIC, steer=None, rewritten=False, step=None):
    return repositorychecks.Input(body, rlog if rlog is not None else _SilentCheckLog(),
        assistruntime.current().engagement_level, workspace_root, driver, trigger, steer, rewritten, step)


def _repository_probes():
    return repositorychecks.ProbeServices(_extract_cwd, probegate.plan_gate)


def _repository_evidence(gs):
    return repositorychecks.EvidenceServices(_read_tool_result, read_gate, gate_error_text,
        lambda findings, messages: track_gate_progress(gs, findings, messages))


def _repository_outcome(outcome, *, consumed=False):
    if (not isinstance(outcome, probegate.GateOutcome)
            or any(type(getattr(outcome, name)) is not bool for name in (
                "ran", "replan_after_survey", "transport_pending", "transport_unknown"))
            or outcome.report is not None and not isinstance(outcome.report, proberun.ProbeReport)
            or outcome.participation is not None and not isinstance(outcome.participation, participation.ParticipationReport)
            or not isinstance(outcome.unran, list) or not isinstance(outcome.swept, list)
            or not isinstance(outcome.refused, str)
            or outcome.offline_ran is not None and type(outcome.offline_ran) is not bool
            or outcome.ran and (outcome.transport_pending or outcome.transport_unknown)
            or consumed and outcome.transport_pending):
        raise ValueError("Repository evidence must be an actual settled GateOutcome")
    return outcome


def _repository_result(result, *, consumed=False, allow_pending=True):
    if not isinstance(result, repositorychecks.Result):
        raise ValueError("Repository check replacement must return Result")
    if (not isinstance(result.status, repositorychecks.Status)
            or result.text is not None and not isinstance(result.text, str)
            or not isinstance(result.note, str)
            or result.pending_kind is not None and not isinstance(result.pending_kind, repositorychecks.PendingKind)
            or result.outcome is not None and not isinstance(result.outcome, probegate.GateOutcome)):
        raise ValueError("Invalid repository check Result")
    if result.outcome is not None:
        _repository_outcome(result.outcome, consumed=consumed)
    if result.status is repositorychecks.Status.PENDING:
        if not allow_pending:
            raise ValueError("Repository completion verdict cannot discard a pending call")
        call = result.call
        if (not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"]
                or call.get("type") != "function" or not isinstance(call.get("function"), dict)
                or not isinstance(call["function"].get("name"), str) or not call["function"]["name"]
                or not isinstance(call["function"].get("arguments"), str)
                or result.pending_kind is None):
            raise ValueError("Pending repository check Result requires an actual call and pending kind")
    elif result.call is not None or result.pending_kind is not None:
        raise ValueError("Nonpending repository check Result cannot carry a call or pending kind")
    if consumed and result.status is not repositorychecks.Status.PENDING:
        if result.outcome is None:
            raise ValueError("Consumed repository check Result requires an actual GateOutcome")
    return result


def _record_repository_evidence(gs, body, rlog):
    raw = _read_tool_result(body.get("messages", []), gs.probe_call_id)
    outcome = read_gate(gs.gate_plan, raw, rlog)
    _repository_outcome(outcome, consumed=True)
    record_gate_state(gs, outcome, gate_error_text(outcome), rlog, body.get("messages"))
    return outcome


def _repository_judgments(gs, body, rlog, *, reasoner_chat=None, reasoner_role=None, workspace_root=None):
    runtime = assistruntime.current()
    def runner(outcome):
        with assistruntime.bound(runtime):
            return runner_reset_steer(gs, outcome, body, rlog, reasoner_chat=reasoner_chat,
                                     reasoner_role=reasoner_role, workspace_root=workspace_root)
    def module(outcome):
        return runtime.module_judgment(_periodic_judgment_input(gs, outcome, body, rlog,
            reasoner_chat=reasoner_chat, reasoner_role=reasoner_role), gs.module_state).steer
    return repositorychecks.JudgmentServices(runner, module)


def _resume_repository_checks(gs, body, rlog, *, driver=repositorychecks.Driver.TASK,
                              rewritten=False, step=None, reasoner_chat=None,
                              reasoner_role=None, workspace_root=None):
    selected = _repository_selection(gs)
    if selected.definition is None:
        # Required transport and factual settlement are not optional judgment/recovery fallbacks.
        if not gs.periodic_probe:
            return repositorychecks.Result(repositorychecks.Status.NOT_SELECTED)
        page = guard_gate_transport(gs, body, rlog)
        if page is not None:
            return repositorychecks.Result(repositorychecks.Status.PENDING, page,
                pending_kind=repositorychecks.PendingKind.PAGE)
        gs.periodic_probe = gs.awaiting_probe = False
        fresh = gs.gate_fresh
        outcome = _record_repository_evidence(gs, body, rlog)
        gs.gate_fresh = fresh
        return repositorychecks.Result(repositorychecks.Status.NOT_SELECTED, outcome=outcome)
    pending = gs.periodic_probe
    return _repository_result(selected.resume(
        lambda: _repository_input(body, rlog, workspace_root=workspace_root, driver=driver,
                                  rewritten=rewritten, step=step), gs, _repository_probes,
        lambda: _repository_evidence(gs), lambda: _repository_judgments(gs, body, rlog,
            reasoner_chat=reasoner_chat, reasoner_role=reasoner_role, workspace_root=workspace_root)),
        consumed=pending)


def _repository_completion(result):
    result = _repository_result(result)
    return _completion_toolcalls([result.call], note=result.note) if result.call is not None else None


class _NamedProbeState:
    """Direct aliases for a caller's existing named pending probe; no copied settlement state."""
    def __init__(self, state, field):
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_field", field)

    def __getattr__(self, name):
        return getattr(self._state, name)

    def __setattr__(self, name, value):
        if name == "probe_call_id":
            setattr(self._state, self._field, value)
            self._state.probe_call_id = value
        else:
            setattr(self._state, name, value)

    @property
    def probe_call_id(self):
        return getattr(self._state, self._field)

    @property
    def done_probe(self):
        return bool(getattr(self._state, self._field))


def _reissue_repository_checks(gs, body, rlog, *, workspace_root=None, rewritten=False,
                               driver=repositorychecks.Driver.TASK, step=None):
    selected = _repository_selection(gs)
    return _repository_result(selected.reissue(lambda: _repository_input(body, rlog,
        workspace_root=workspace_root, driver=driver, rewritten=rewritten, step=step),
        gs, _repository_probes, lambda: _repository_evidence(gs)))


def _requested_repository_probe(gs, body, rlog, *, workspace_root=None,
                                 driver=repositorychecks.Driver.TASK, step=None):
    selected = _repository_selection(gs)
    return _repository_result(selected.admit(lambda: _repository_input(body, rlog,
        workspace_root=workspace_root, driver=driver, trigger=repositorychecks.Trigger.REQUESTED,
        step=step), gs, _repository_probes)).call


def _forward_acting_coder(sess, completion):
    # Only the six accepted coder-return leaves call this; delegation is transparent.
    selected = _repository_selection(sess)
    if selected.definition is not None and selected.definition.observe(sess, acting=True) is not None:
        raise ValueError("Repository check observe replacement must return None")
    sess.gate_fresh = False  # required workspace freshness is independent of the optional clock
    return completion


def guard_gate_op(gs: GuardState, body: dict, rlog, *, workspace_root=None) -> dict | None:
    """Required construction support, including planner surveys when the optional policy is off."""
    return repositorychecks.compose(_repository_input(body, rlog, workspace_root=workspace_root),
                                    gs, _repository_probes())


def guard_gate_replan_after_survey(gs: GuardState, body: dict, rlog, *, workspace_root=None) -> dict | None:
    selected = _repository_selection(gs)
    return _repository_result(selected.replan(
        lambda: _repository_input(body, rlog, workspace_root=workspace_root), gs, _repository_probes)).call


def guard_periodic_replan_after_survey(gs: GuardState, body: dict, rlog, *, workspace_root=None) -> dict | None:
    selected = _repository_selection(gs)
    return _repository_result(selected.replan(
        lambda: _repository_input(body, rlog, workspace_root=workspace_root), gs,
        _repository_probes, periodic=True)).call


def guard_gate_transport(gs: GuardState, body: dict, rlog, *, call_id: str = "") -> dict | None:
    """Required checked-page support, independent of optional policy selection."""
    return repositorychecks.transport(_repository_input(body, rlog), gs, _repository_probes(),
                                      _repository_evidence(gs), call_id=call_id).call


def _refusals_in_window(messages: list[dict] | None) -> tuple[int, str]:
    """How many of the last REPEAT_WINDOW forwarded calls cria itself refused, and the most recent
    refused call's ``name args`` — bounded to REPEAT_ACTION_CHARS.

    A fact cria owns outright: it is what stopped them, so no similarity judgement is needed and none
    is made. THE DESCRIPTION MUST COME FROM A REFUSED CALL. The steer says "cria REFUSED N of its
    recent calls ... the most recent was: X", and X used to be whatever call the coder was making
    when the counter tripped — a call that had not been refused at all. That is a false fact in the
    one seat where a false fact does the most damage (#5b), so the count and the quote now come from
    the same place."""
    tail = [m for m in (messages or [])
            if m.get("role") == "assistant" and m.get("tool_calls")][-REPEAT_WINDOW:]
    refused_ids = denial.refused_call_ids(messages)
    n, last = 0, ""
    for m in tail:
        for tc in m.get("tool_calls") or []:
            cid = tc.get("id")
            if cid is None or cid not in refused_ids:
                continue
            n += 1
            fn = tc.get("function") or {}
            args = fn.get("arguments") or ""
            last = _clip(f"{fn.get('name') or '?'} "
                         f"{args if isinstance(args, str) else json.dumps(args)}",
                         REPEAT_ACTION_CHARS)
    return n, last


class _StalledWorkView:
    """Live aliases onto the actual task owner; no second state or cache."""
    _fields = {name: name for name in (
        'recent_writes', 'recent_write_ids', 'spin_recheck', 'spin_path', 'action_seq',
        'blocked_fired_seq', 'repeat_action', 'repeat_count', 'redirect_due',
        'steered_checks_text', 'same_checks_relooked')}
    _fields.update(spin_due='spin_probe_due', pending_probe='stalled_probe',
                   pending_steer='stalled_steer', last_delivered='stalled_delivered')

    def __init__(self, owner):
        object.__setattr__(self, 'owner', owner)

    def __getattr__(self, name):
        target = self._fields[name]
        value = getattr(self.owner, target, '' if name == 'steered_checks_text' else None)
        if name in ('recent_writes', 'recent_write_ids') and value is None:
            value = []
            setattr(self.owner, target, value)
        return value

    def __setattr__(self, name, value):
        setattr(self.owner, self._fields[name], value)


def _stalled_selection(gs):
    runtime = assistruntime.current()
    _pin_pilot_runtime(gs, runtime)
    return gs.pilot_binding.stalled_work


def _stalled_result(result):
    if (not isinstance(result, stalledwork.Result) or not isinstance(result.status, stalledwork.Status)
            or result.probe is not None and not isinstance(result.probe, stalledwork.PendingProbe)
            or result.steer is not None and not isinstance(result.steer, stalledwork.Steer)):
        raise TypeError('Stalled work replacement must return Result')
    return result


def _grounded_actions(system1=None):
    public = {'guard_ground_truth', 'workspace_inventory'}
    facts = groundedaction.EvidenceServices(**{
        name: globals()[name if name in public else '_' + name]
        for name in groundedaction.EvidenceServices.__annotations__})
    return groundedaction.GroundedActions(facts,
        groundedaction.ProviderServices(summarize, _judge_completion, system1))


def _stalled_author(gs, body, rlog, chat, role, root=None, *, condition='refusal',
                    outcome=None, truth_text='', step_text='', system1=None):
    if chat is None:
        return None
    original = getattr(getattr(gs, 'plan', None), 'task', '') or _history_root(body.get('messages', []))[0]
    evidence = groundedaction.ActionEvidence(original_task=original,
        last_gate_flag=getattr(gs, 'last_gate_flag', ''), gate_plan=getattr(gs, 'gate_plan', None),
        fetched_pages=getattr(gs, 'fetched_pages', None) or {},
        refused_names=frozenset(getattr(gs, 'refused_names', None) or ()),
        refusal_events=getattr(gs, 'refusal_events', None),
        recent_writes=tuple(getattr(gs, 'recent_writes', None) or ()),
        spin_path=getattr(gs, 'spin_path', ''),
        repeat_count=getattr(gs, 'repeat_count', 0), repeat_action=getattr(gs, 'repeat_action', ''),
        gate_stall=getattr(gs, 'gate_stall', 0),
        thrash_edits=thrash_edits_clause(gs))
    seat = groundedaction.AuthorInput(chat, role, root, evidence, body, rlog, condition,
                                     outcome, truth_text, step_text)
    return stalledwork.AuthorServices(original, lambda: getattr(gs, 'last_gate_flag', ''),
        lambda text: _checks_superseded_by_coder_run(body.get('messages', []), text),
        lambda text: _checks_already_visible(body, text), _checks_ran_before,
        _grounded_actions(system1), seat, rlog)


def _stalled_text(steer):
    return ('[REDIRECT]\n' if steer.redirect_envelope else '') + steer.text


def _stalled_frame(gs, framed, notes):
    gs.stalled_reply = None
    definition = _stalled_selection(gs)
    steer = gs.stalled_steer
    if definition is None or steer is None:
        return
    text = prompts.render('nudge', reason=_stalled_text(steer))
    offered = next((m for m in notes if m.get('role') == 'user' and m.get('content') == text), None)
    if offered is not None and any(m is offered and m.get('content') == text
                                   for m in framed.get('messages', [])):
        gs.stalled_reply = (None, definition, None, steer)


def _record_dispatch(gs, coder, messages):
    """Register ONE forwarded completion with the registry's owner and return its snapshot. Every dispatch whose
    result can enter a settlement set — writes and every other tool — is counted here, exactly once; this is the
    only place a dispatch is recorded. Observation and measurement are pure and read the snapshot."""
    calls = tuple(writeobservation.ForwardedCall(tc.get('id'), _write_path(tc.get('function') or {}))
                  for ch in coder.get('choices', [])
                  for tc in (ch.get('message') or {}).get('tool_calls') or [])
    return writeobservation.record(writeobservation.WriteInput(
        calls, messages or [], frozenset(_unlanded_call_ids(messages or [])), gs, _note_write_results,
        _is_write_call))


def _stalled_observation(gs, messages, rlog, *, observed, step=None, sequence_start=None, write_messages=None):
    """A PURE observation of an already-recorded dispatch: it reads ``observed`` and never registers anything."""
    def measure():
        count, last = _refusals_in_window(messages)
        sanction_messages = messages if write_messages is None else write_messages
        sanctioned = frozenset(call.write_path for call in observed.calls
            if call.write_path is not None and editrecovery.rewrite_sanctioned(sanction_messages or [], call.write_path))
        return stalledwork.ObservationFacts(observed.calls, count, last,
                                            observed.unlanded_ids, sanctioned, sequence_start)
    return stalledwork.ObservationInput(measure, rlog, step)


def _prepare_stalled_reply(gs, retained):
    pending, gs.stalled_reply = gs.stalled_reply, None
    if pending is None or pending[0] is None or pending[0] is not retained:
        return None
    _completion, definition, observation, steer, _sequence_start, _call_count = pending
    if definition is not None and observation is not None:
        # The actual framed offer permits observation, not delivery credit. A failing
        # observer must leave the exact pending steer retriable and publish nothing.
        source = replace(observation, offered_steer=steer)
        _stalled_result(definition.execute(source, _StalledWorkView(gs)))
    return pending


def _settle_stalled_reply(gs, pending):
    if pending is None:
        return
    _completion, definition, _observation, steer, sequence_start, call_count = pending
    if definition is not None and steer is not None and gs.stalled_steer is steer:
        _stalled_result(definition.acknowledge(_StalledWorkView(gs), steer))
    gs.action_seq = sequence_start + call_count


def guard_track_refusals(gs: GuardState, coder: dict, rlog, *, step=None, messages=None) -> None:
    """The explicit entry point for "this reply was just forwarded": it registers the dispatch once, then observes."""
    observed = _record_dispatch(gs, coder, messages)
    definition = _stalled_selection(gs)
    if definition is not None:
        _stalled_result(definition.execute(_stalled_observation(gs, messages, rlog, observed=observed, step=step),
                                          _StalledWorkView(gs)))


def _repeat_observation(gs: GuardState) -> dict:
    """The tokens the redirect needs to describe WHAT CRIA SAW — one owner, so the two render sites
    cannot drift and neither can invent a number.

    `observed` is a whole clause rather than a bare count. A fire that somehow counted nothing gets
    the vaguest honest wording and no number at all. Saying less is allowed; saying a number cria did
    not count is not (#5b)."""
    n = gs.repeat_count
    if n > 1:
        observed = f"{n} of your recent calls were refused, so none of them ran"
    elif n:
        observed = "your last call was refused, so it did not run"
    else:
        observed = "you are not getting a new outcome from these actions"
    return {"observed": observed, "repeat_action": gs.repeat_action}


# How much of the repeated action the redirect quotes back. Enough to IDENTIFY it (tool + path +
# the leading args); never enough to re-supply a file body the model would otherwise have to retype.
REPEAT_ACTION_CHARS = 200


def _refused_call_ids(messages: list) -> set:
    """Tool call ids whose result cria PROVED came from its own refusal branch — the call never ran.
    One owner (:func:`denial.refused_call_ids`): the proof is the receipt `represent_inbound` checked, never
    what the result says."""
    return denial.refused_call_ids(messages)


def _unlanded_call_ids(messages: list) -> set:
    """Tool call ids of writes/edits cria PROVED did not change the file: its own refusal branch ran, or its
    edit program reported the edit not applied. A write that never reached disk is not a rewrite (phi4 A4 CALL
    0039: nine refused edits read as "rewritten at least 5 times" while the file was byte-identical). A result
    that merely QUOTES a marker, a reused call id, or a result with no hint is unknown, never unlanded."""
    return denial.unlanded_call_ids(messages)


def guard_track_write_streak(gs: GuardState, coder: dict, rlog, *, step=None, messages=None) -> None:
    guard_track_refusals(gs, coder, rlog, step=step, messages=messages)


def guard_intervene(gs: GuardState, body: dict, rlog, *, step=None, workspace_root=None) -> dict | None:
    definition = _stalled_selection(gs)
    if definition is None:
        return None
    previous_probe = gs.stalled_probe
    result = _stalled_result(definition.admit(stalledwork.AdmissionInput(
        lambda: _requested_repository_probe(gs, body, rlog, workspace_root=workspace_root,
            driver=repositorychecks.Driver.STEP if step is not None else repositorychecks.Driver.TASK,
            step=step), rlog,
        lambda: _refusals_in_window(body.get("messages", [])), step), _StalledWorkView(gs)))
    if result.probe is not None:
        if gs.stalled_probe is not result.probe:
            raise ValueError('Stalled probe must retain its actual pending identity')
        gs.awaiting_probe = True
        if previous_probe is result.probe and gs.probe_call_id != result.probe.call.get('id'):
            # A mutable launch alias cannot replace current owned correlation,
            # including a newer page/reissue already installed by transport.
            return None
        gs.probe_call_id = result.probe.call['id']
        return _completion_toolcalls([result.probe.call], note=(
            "running the repo's checks (repeated action detected)"
            if result.probe.trigger is stalledwork.Trigger.REFUSAL else
            "running the repo's checks (repeated rewrites detected)"))
    if result.steer is not None:
        gs.nudge_reason, gs.steer_source = _stalled_text(result.steer), result.steer.source
    return None


def guard_probe_reissue(gs: GuardState, body: dict, rlog, *, rewritten: bool, workspace_root=None) -> dict | None:
    """A probe cria emitted last turn should have a result this turn. If the harness COMPACTED the
    history (``rewritten``), that result was LOST, not declined — re-issue the gate rather than
    fail-open (accept an unverified 'done') or downgrade to a canned steer. Capped by
    MAX_PROBE_REISSUES. Shared with the loop's _verify_after_probe so BOTH paths recover a
    compaction-lost probe. Returns the re-issued probe completion, or None (result present, not a
    compaction loss, cap hit, or no gate). Leaves the pending flag armed so next turn reads the new
    result the same way.

    C28b: before spending any of that budget, prefer POLLING the current plan if its transport is
    still open (the selected reissue hook) — that costs nothing against
    MAX_PROBE_REISSUES, since it is not a new gate, just another read of the one already in flight.
    """
    selected = _repository_selection(gs)
    return _repository_completion(selected.reissue(
        lambda: _repository_input(body, rlog, workspace_root=workspace_root, rewritten=rewritten),
        gs, _repository_probes, lambda: _repository_evidence(gs)))


# How many DRIVES a step may run before cria asks its own critic whether it is done.
# MEASURED over every captured session (2026-08-05), counting consecutive coder calls between two
# critic calls: n=806 stretches, median 5, p90 56, max 282 — and 149 stretches of 30+ turns hold
# 11,831 of the 15,896 coder calls on the box. 74% OF ALL CODER WORK HAPPENS IN A STRETCH WHERE CRIA
# NEVER ONCE ASKS WHETHER THE STEP IS DONE. 12 sits far above the median, so ordinary work never
# reaches it, and well below the tail this exists for.
#
# COUNTED IN DRIVES SINCE 2026-08-18, not in acting coder turns. The turn counter it used to read is
# the GATE's countdown and the gate zeroes it every 15, which capped this check at one fire per
# session; `drive_count` is the clock nothing resets. A drive is the same event or slightly more
# often than an acting turn (a turn that returns early on a probe or a steer counts as a drive and
# not as an acting turn), so the cadence stays far above the median of 5 either way. The event now
# records both numbers so the exact ratio is a reading rather than an argument.
STEP_CHECK_EVERY = stepreview.STEP_CHECK_EVERY


def guard_periodic_gate(gs: GuardState, body: dict, rlog, *, workspace_root=None,
                        driver=repositorychecks.Driver.TASK, steer=None, rewritten=False, step=None) -> dict | None:
    selected = _repository_selection(gs)
    return _repository_completion(selected.admit(lambda: _repository_input(body, rlog,
        workspace_root=workspace_root, driver=driver, steer=steer, rewritten=rewritten, step=step),
        gs, _repository_probes))


_configured_js_test_failure = runnercontract.failed_declared_runner


class _RunnerStateView:
    """Direct access to the existing transient guard field; construction reads nothing."""
    def __init__(self, guard: GuardState):
        self._guard = guard

    @property
    def signature(self):
        return self._guard.runner_reset_signature

    @signature.setter
    def signature(self, value):
        self._guard.runner_reset_signature = value


def _periodic_judgment_evidence(gs: GuardState, body: dict) -> tuple[str, str]:
    task, _ = _history_root(body.get("messages", []))
    session = selfcompact.serialize(_drop_harness_frame(probegate.clean_gate_results(
        _reasoner_session(body.get("messages", [])), getattr(gs, "gate_plan", None))))
    return task, session


def _runner_contract_input(gs: GuardState, outcome, body: dict, rlog, *,
                           reasoner_chat, reasoner_role, workspace_root) -> runnercontract.RunnerInput:
    ask = None
    if reasoner_chat is not None and reasoner_role is not None:
        def ask(question, **options):
            return ask_closed(reasoner_chat, reasoner_role, question, rlog, **options)
    return runnercontract.RunnerInput(outcome, lambda: gate_error_text(outcome),
        lambda: wsview.current(workspace_root).isdir("node_modules") if workspace_root else None,
        lambda: _periodic_judgment_evidence(gs, body), ask, rlog)


def runner_reset_steer(gs: GuardState, outcome, body: dict, rlog, *,
                       reasoner_chat, reasoner_role, workspace_root: str | None) -> str | None:
    """Judge one red declared-JS test event before pinning its runner interface.

    The detector supplies only observed configuration, exit status, and workspace-directory facts.
    It deliberately does not inspect failure prose or action wording; the reasoner judges whether
    the session has become incompatible interface churn and whether the task carries the stated
    no-node_modules contract.  A missing/unreadable judgment leaves the ordinary checker output
    untouched, toward more work rather than a fabricated reset.
    """
    return runnercontract.run_selected(assistruntime.current().runner_contract,
        lambda: _runner_contract_input(gs, outcome, body, rlog, reasoner_chat=reasoner_chat,
            reasoner_role=reasoner_role, workspace_root=workspace_root), _RunnerStateView(gs)).steer


def _periodic_judgment_input(gs: GuardState, outcome, body: dict, rlog, *,
                             reasoner_chat, reasoner_role) -> ModuleInput:
    """Shared evidence/services at the result stage; gathering is deliberately lazy."""
    def evidence():
        return _periodic_judgment_evidence(gs, body)

    ask = None
    if reasoner_chat is not None and reasoner_role is not None:
        def ask(question):
            return ask_closed(reasoner_chat, reasoner_role, question, rlog,
                              phase="module-state", max_tokens=JUDGE_MAX_TOKENS, retry_off=False)
    return ModuleInput(outcome, lambda: gate_error_text(outcome), evidence, ask, rlog)


def guard_periodic_result(gs: GuardState, body: dict, rlog, *, reasoner_chat=None,
                          reasoner_role=None, workspace_root=None) -> str | None:
    """Read the periodic check-in probe's result and return the error-class GROUND TRUTH to insert
    (file:line findings, or a check that ran and failed) — no verdict, the model keeps working. None
    when no periodic probe is pending, OR when the checks are CLEAN / couldn't run: a periodic check-in
    with nothing to FIX stays silent rather than prod a passing check-in with 'the checks pass but
    that's not proof of correctness', which just makes the model distrust the pass and keep working."""
    result = _resume_repository_checks(gs, body, rlog, reasoner_chat=reasoner_chat,
        reasoner_role=reasoner_role, workspace_root=workspace_root)
    if result.call is not None:
        raise ValueError("Pending repository result must be forwarded by its driver")
    return result.text


# A closed question cria asks a reasoner. THE QUESTION GOES IN THE USER TURN. cria used to put the
# whole thing in `system` and send `user: ""` — walked on maple-preview 1786228135 call 0092, where
# the prompt was `system(2658 chars) + user(0 chars)` and the model answered "We need to parse the
# user's message. It's just a single period." A model looks for the ask where an ask lives; an empty
# user turn is cria asking nothing and grading the answer.
_ASK_USER_TURN = "Answer the question above."


def ask_closed(chat_fn, role, question: str, rlog, *, phase: str, max_tokens: int = 1024,
               retry_off: bool = True, evidence_blocks: list[str] | None = None,
               evidence_intro: str = "composed_evidence_intro") -> str:
    """ONE primitive for every closed question cria puts to a reasoner — reasoning off, temperature
    0, the question in the user turn where the model looks for it. Returns "" on anything unreadable,
    which every caller already treats as "no answer". A caller whose contract permits only one
    actual judgment can disable the otherwise loss-preserving empty-answer retry."""
    return summarize(chat_fn, replace(role, reasoning="off") if role is not None else None,
                     question, _ASK_USER_TURN, rlog, phase=phase, max_tokens=max_tokens,
                     temperature=0.0, retry_off=retry_off, evidence_blocks=evidence_blocks,
                     evidence_intro=evidence_intro) or ""


def _composed_closed_ask(chat_fn, role, rlog, *, phase: str):
    """The closed-question seat for a diagnosis, able to carry the question's unbounded evidence as
    composed blocks (``ask(question, evidence_blocks)``) so the one context floor can reduce it."""
    def ask(question: str, evidence_blocks: list[str] | None = None) -> str:
        return ask_closed(chat_fn, role, question, rlog, phase=phase, max_tokens=JUDGE_MAX_TOKENS,
                          retry_off=False, evidence_blocks=evidence_blocks,
                          evidence_intro="composed_evidence_intro_system")
    ask.composes_evidence = True
    return ask


def validate_compaction_briefing(chat_fn, role, briefing: str, *, files: str, checks: str,
                                  transcript_blocks: list[str], rlog, task: str = "",
                                  phase: str = "compaction-validate", system1=None) -> bool:
    """Fail-closed, independent judgments before model-made session memory is injected.

    One large verdict asked a weak judge to enforce format, task scope, files, checks, uncertainty,
    and omissions over a long transcript. In both failed L5 cells it accepted forward plans and
    claims contradicted in its own prompt. Ask the semantic questions separately: candidate-only
    retrospection, task-scope preservation, then evidence fidelity. Every applicable lens must
    return their exact positive verdict. Callers retain verbatim history (self-compaction) or only
    re-derivable appendices (a harness-owned compaction) on any rejection or unavailable answer.

    ``system1`` (the service's trained classifier, when ``[system1]`` is enabled) answers ONLY the
    first lens — PLAN versus RETROSPECTIVE over the whole briefing. Scope and fidelity still go to the
    reasoner, whose evidence blocks the classifier cannot read. A classifier that cannot answer
    rejects the briefing: the same fail-closed exit an unreadable reasoner verdict takes, with no
    reasoner asked in its place.
    """
    if chat_fn is None or role is None or not briefing.strip():
        if rlog is not None:
            rlog.emit("context.compaction_validation", reshape="validate-rollup", level="warn",
                      accepted=False, reason="judge unavailable")
        return False

    candidate = prompts.render("compaction_candidate", briefing=briefing.strip())
    answers: dict[str, str] = {}

    def judge(lens: str, system_prompt: str, blocks: list[str], accepted_word: str) -> bool:
        answer = summarize(chat_fn, replace(role, reasoning="off"), system_prompt,
                           prompts.load("compaction_validate_ask"), rlog,
                           phase=f"{phase}-{lens}", max_tokens=JUDGE_MAX_TOKENS, retry_off=False,
                           temperature=0.0, evidence_blocks=blocks)
        answers[lens] = answer.strip()[:40]
        return answer.strip().upper() == accepted_word

    # Candidate-only on purpose. In the captured false accepts, an obvious "Next step" section was
    # buried behind 12K-32K tokens of history and the judge overlooked the simplest invariant.
    if system1 is None:
        accepted = judge("retrospective", prompts.load("compaction_validate_retrospective"),
                         [candidate], "RETROSPECTIVE")
    else:
        try:
            answers["retrospective"] = system1wiring.classify(
                system1, "retrospective", briefing.strip(), rlog, seat=phase)
        except system1wiring.Unjudged:
            answers["retrospective"] = "UNJUDGED"
        accepted = answers["retrospective"] == "RETROSPECTIVE"
    task_fact = (prompts.render("compaction_task_fact", task=task.strip()) if task.strip() else "")
    if accepted and task_fact:
        accepted = judge("scope", prompts.load("compaction_validate_scope"),
                         [task_fact, candidate], "PRESERVES")
    # A file the briefing calls present while a COMPLETE survey lists none such is a fact check, not a
    # reading of the transcript: the fidelity verdict below held the incident's claim and passed it.
    if accepted:
        missing = filepresence.contradicted_files(summarize, chat_fn, role, briefing, files, rlog, phase)
        if missing:
            answers["files"] = "ABSENT " + ", ".join(missing)
            accepted = False
    if accepted:
        blocks = list(transcript_blocks)
        if task_fact and task_fact not in blocks:
            blocks.append(task_fact)
        blocks.append(candidate)
        blocks.append(prompts.render("compaction_files_fact", files=files.strip()) if files.strip()
                      else prompts.render("compaction_no_fact", kind="FILESYSTEM INVENTORY"))
        blocks.append(prompts.render("compaction_checks_fact", checks=checks.strip()) if checks.strip()
                      else prompts.render("compaction_no_fact", kind="LATEST CHECK FACTS"))
        accepted = judge("fidelity", prompts.load("compaction_validate"), blocks, "FAITHFUL")
    if rlog is not None:
        rlog.emit("context.compaction_validation", reshape="validate-rollup",
                  level="info" if accepted else "warn", accepted=accepted, answers=answers)
    return accepted


# The compactor/briefing output bound every internal prose-writing call on this primitive uses
# (the JUDGE-verdict siblings carry their own, larger `JUDGE_MAX_TOKENS` — a one-word verdict vs a
# multi-paragraph briefing warrant different budgets, but both are BOUNDED; neither is ever None).
# Named so a second caller that needs the same bound (server._harden_compaction_reply, C41) reads
# the one number rather than copying the literal.
SUMMARIZE_MAX_TOKENS = 8192


def summarize(chat_fn, role, system: str, user: str, rlog, *, phase: str = "compactor",
              max_tokens: int = SUMMARIZE_MAX_TOKENS, retry_off: bool = True, coder_tools: str = "",
              capture: list | None = None, temperature: float | None = None,
              evidence_blocks: list[str] | None = None,
              evidence_intro: str = "composed_evidence_intro") -> str:
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
    # A private outcome from the FIRST pass.  It exists only for the immediate forced-off retry,
    # never in session/global state and never on the API wire (`bodykeys.ALL` is stripped in _prep).
    # The wire, rather than this caller, compares the retry's final serialized bytes.
    context_refit_no_change: ContextRefitNoChange | None = None

    def _one(reasoning_off: bool) -> str:
        nonlocal context_refit_no_change
        messages = [{"role": "system", "content": system}]
        if evidence_blocks:
            # The producer, never the text/position, establishes that these are
            # internal evidence rather than user requests. Keep every payload
            # byte; only the shared floor can reduce it, with a visible label.
            messages.append(selfcompact.internal_evidence_message(prompts.load(evidence_intro)))
            messages.extend(selfcompact.internal_evidence_message(block) for block in evidence_blocks)
        messages.append({"role": "user", "content": user})
        call = {"stream": False, "max_tokens": max_tokens, "messages": messages}
        if phase.startswith(("self-compact", "compactor", "compaction", "harness-compaction")):
            # Only summary work over flattened history learns the summary density; judges,
            # queries and steer authors keep the ordinary key (see upstream._density_key).
            call[bodykeys.DENSITY_KIND] = "summary"
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
        if reasoning_off and context_refit_no_change is not None:
            call[bodykeys.CONTEXT_REFIT_NO_CHANGE] = context_refit_no_change
        try:
            rlog.phase = phase + ("-noreason" if reasoning_off else "")
            received = _parse_completion(chat_fn(call, rlog))
            if capture is not None:
                # Preserve the completion AS RECEIVED. `massage.apply` can promote private
                # reasoning into empty content before `coerce_text_answer` runs; answer-vs-thinking
                # recovery needs the original empty/ON_TRACK answer, not either mutated view.
                capture.append(copy.deepcopy(received))
            # Text-answer coercion can erase malformed call syntax and promote its private
            # reasoning. Keep the existing leak detector's fact before either transform,
            # but honor the role's existing private/public partition first.
            raw_message = ((received.get("choices") or [{}])[0].get("message") or {})
            raw_text = massage.content_text(raw_message.get("content"))
            if role is not None:
                raw_text = role.clean_content(raw_text)
            raw_tool_leak = massage.has_tool_call_leak(raw_text)
            applied = massage.apply(received, None, rlog)
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
            if raw_tool_leak or massage.has_tool_call_leak(text):
                # A leaked/mangled tool call, not prose — fail this pass so the reasoning-off retry
                # fires. Returning it would inject a wall of `<|tool_call>…` garbage as the briefing.
                rlog.emit("summarize.leaked_tool_call", reshape="recover", level="warn", phase=rlog.phase)
                return ""
            if answered_with_tool_call and not reasoning_off:
                rlog.emit("summarize.tool_call_answer", reshape="recover", level="warn", phase=rlog.phase)
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
        except CallerContextRetryNoChange as e:
            # The first attempt's original parsed context error/capture/events already exist.  The
            # wire has just proved this one opt-in retry would be the identical final request, so
            # return the normal unavailable result without a POST.  `_summarised_evidence` keeps
            # its whole source when this is empty.
            rlog.emit("summarize.context_retry_no_change", level="warn", phase=rlog.phase,
                      bytes=len(e.final_wire))
            return ""
        except ContextRefitNoChange as e:
            # Do not infer this from a status, error string, or log record.  Only the wire owner can
            # construct it after parsing a context error and comparing the unsent inner refit bytes.
            if not reasoning_off and retry_off:
                context_refit_no_change = e
            rlog.emit("summarize.error", level="warn", error=str(e))
            return ""
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


def record_gate_state(gs: GuardState, outcome, findings: str, rlog=None, messages=None) -> None:
    """A gate reading becomes session state HERE, and only here. Every reader calls this.

    There were three readers and two of them wrote the state inline, in their own words, with their
    own idea of which fields mattered — and the third, :func:`guard_probe_steer`, wrote NONE of it.
    That third one reads the very same probe result as the completion gate (same call id, same plan)
    and then RETURNED the steer, so on a repetition-redirect or wheel-spin turn the whole reading was
    thrown away: `last_gate_red` kept whatever the PREVIOUS gate said. A gate that went green→red on
    such a turn left cria believing green, which is the completion side of #13 failing open.

    A gate that could not RUN is a neutral non-signal: never red, never green, and it must not touch
    the stall streak (:func:`track_gate_progress` says so in its own words). It still counts as
    ATTEMPTED — the completion backstop's long-standing fail-open — so `gate_fresh` is set. The two
    exceptions are a survey-only bootstrap, which requires a newly planned gate, and incomplete
    transport, which is explicit UNKNOWN. Neither is fresh evidence."""
    repositorychecks.record(_repository_input({"messages": messages}, rlog), gs, outcome, findings,
                            _repository_evidence(gs))


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
    selected = _repository_selection(gs)
    if selected.definition is None:
        _record_repository_evidence(gs, body, rlog)
        return None
    return _repository_result(selected.completion(lambda: _repository_input(body, rlog), gs,
        lambda: _repository_evidence(gs)), consumed=True, allow_pending=False).text


def _gate_test_green(outcome) -> bool:
    """Did the gate's TEST probe exit 0? The offline leg only runs after a green test probe, so this
    is what separates "the leg declined because there was nothing to compare" from "the leg could not
    be set up at all" — the second being the one that needs an operator's eyes."""
    report = getattr(outcome, "report", None)
    if report is None:
        return False
    for cand, res in zip(report.selected or [], report.results or []):
        if cand.kind is probegate.probediscovery.ProbeKind.Test:
            return res.exit_code == 0
    return False


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
    outcome = probegate.interpret_gate(plan, probe_text, rlog)
    if outcome.refused:
        rlog.emit("loop.gate_refused", level="warn", reason=outcome.refused)
    if outcome.swept:
        rlog.emit("loop.gate_swept", paths=len(outcome.swept), sample=outcome.swept[:5])
    if outcome.offline_ran is not None:
        # Operator-facing only, like the refusal above. A gate whose test probe went green and whose
        # network-off leg printed nothing has silently lost the one instrument that tells a mocked
        # suite from a real one — and the leg is gated on a capability probe that performs a bind
        # mount, which is precisely the shape that cost a whole arm before.
        rlog.emit("loop.gate_offline", ran=outcome.offline_ran,
                  test_green=_gate_test_green(outcome))
    return outcome


def gate_error_text(outcome) -> str:
    """The blocking ground truth from a gate outcome: findings, hard failure, or transport UNKNOWN.

    Returns '' when the gate is clean, could not run, or never ran. Transport UNKNOWN is deliberately
    nonempty so every completion path fails closed without mislabeling it as a checker failure.

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
    if getattr(outcome, "transport_unknown", False):
        return probegate.transport_unknown_text(getattr(outcome, "transport_reported", ""))
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
        # "A SPECIFIC LINE COULD NOT BE PARSED" IS A CLAIM, AND IT HAS TO BE TRUE. cria has two
        # readers of one gate: `probegate.guard_ground_truth` keeps raw lines, `parse_output` builds
        # structured findings, and where the second misses what the first kept, one prompt carries
        # both "each is the checker's OWN message and the line it flagged" and "a specific line
        # could not be parsed from the output" — same command, same tally, opposite claims.
        # Measured at 176 prompts across 54 sessions, 5 of them on 2026-08-23.
        #
        # A parser gap is not an unparseable output (#5b). `probeparse.names_a_location` is the one
        # owner of the shape question, so the two readers cannot disagree about whether a line is
        # there — only about whether cria managed to structure it.
        key = ("ground_truth_failed_located"
               if any(probeparse.names_a_location(f) for f in failed)
               else "ground_truth_failed")
        return prompts.render(key, failed="\n".join(failed))
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

    Only paired runs after a producer-owned gate count. Command heads carry scope;
    without them this function abstains. The whole invocation must match, and the
    own-check parser must attribute a successful exit to it. Every carried command
    needs a newer green result; newer red, pending or unknown runs withdraw that
    proof. Tool output containing a tally is never proof of execution on its own.
    """
    from types import SimpleNamespace

    heads = _gate_commands(checks)
    if not heads or len(set(heads)) != len(heads):
        # The finding renderer carries display commands, not a scope identity per head.
        # Repeated heads may describe distinct scopes; one receipt cannot prove both.
        return ""

    def matching_head(fn):
        args = _args_of(fn.get("arguments") or "")
        cmd = args.get("cmd", args.get("command"))
        if (is_shell_tool_name(fn.get("name")) and isinstance(cmd, str)
                and set(args) in ({"cmd"}, {"command"}) and cmd.strip() in heads):
            return cmd.strip()
        return ""

    msgs = messages or []
    automatic = probegate.gate_call_ids(msgs)
    last_gate = max((i for i, m in enumerate(msgs)
                     if isinstance(m, dict)
                     and (m.get("role") == "tool" or m.get("type") == "function_call_output")
                     and (m.get("tool_call_id") or m.get("call_id")) in automatic), default=-1)
    if last_gate < 0:
        return ""             # cannot establish that a coder invocation is newer than the gate
    unlanded = _unlanded_call_ids(msgs)
    mutations, pending = set(), set()
    last_mutation = -1
    for i, message in enumerate(msgs):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                cid = call.get("id")
                fn = call.get("function") or {}
                if cid in automatic or cid in unlanded:
                    continue
                # The path owner cannot enumerate every shell mutation (e.g. mv has no redirect).
                # Any shell invocation outside the exact carried check has uncertain scope/state;
                # require its result before a qualifying check begins, without guessing its verbs.
                uncertain_shell = is_shell_tool_name(fn.get("name")) and not matching_head(fn)
                if _write_path(fn) is not None or _is_write_tool(fn.get("name")) or uncertain_shell:
                    if not cid:
                        return ""       # an unpaired mutation has no observable settlement
                    mutations.add(cid)
                    pending.add(cid)
                    last_mutation = i
        elif message.get("role") == "tool" or message.get("type") == "function_call_output":
            cid = message.get("tool_call_id") or message.get("call_id")
            if cid in mutations:
                pending.discard(cid)
                last_mutation = i
    if pending:
        return ""                       # a write or uncertain shell can still change checked state
    # A check overlapping a write/uncertain shell is not proof about the settled workspace. Keep
    # only invocations after settlement; refused and failed-to-apply calls are excluded by their owner.
    later = msgs[max(last_gate, last_mutation) + 1:]
    returned = {tid: (cmd, res) for tid, cmd, res in _shell_runs(later)}
    outcomes = dict.fromkeys(heads, "")
    compile_class = not _is_test_finding(checks)
    # Order by invocation, not result arrival: an older slow green must not beat a newer red.
    for message in later:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            head = matching_head(call.get("function") or {})
            if not head or call.get("id") in automatic:
                continue
            outcomes[head] = ""       # pending/unknown/red never inherit an older green outcome
            got = returned.get(call.get("id"))
            if got is None:
                continue
            _, result = got
            receipt = SimpleNamespace(last_gate_flag=checks, action_seq=1, last_gate_seq=0)
            _track_own_checks(receipt, [
                {"role": "assistant", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": call.get("id"), "content": result},
            ])
            # The own-check owner parses shell input, pairs receipts, and attributes exit status.
            # A green-looking log without a proven successful check exit is not supersession.
            if not getattr(receipt, "own_check_runs", None) or receipt.own_check_runs[-1][2] != 0:
                continue
            runner, tally = probegate.runner_and_tally(result)
            if (tally and (tally.startswith("0f/") or tally.endswith("/OK"))
                    and (not compile_class or runner in probegate.COMPILES_FIRST)):
                outcomes[head] = tally
    return next(reversed(outcomes.values())) if all(outcomes.values()) else ""


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
    return prompts.fill(labels[key],
                        files=prompts.named_list(paths)).rstrip("\n")


# NO CAP. Every file written since the checks ran is named. It was 3, "the rest are counted, never
# dropped" — and a counted file is a file the coder cannot act on, which is what rule 5's tightening
# on 2026-08-16 settled about disclosed elisions. Paths are a few tokens each and the floor is the
# one place a list may be narrowed.
WRITES_SINCE_GATE_CAP = None


def _writes_since_last_gate(messages: list[dict], cap: int | None = None) -> list[str]:
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
    out = list(reversed(out))
    return out[:cap] if cap else out


def _checks_already_visible(body: dict, checks: str) -> bool:
    """Only the complete offered evidence establishes its own visibility.

    Generic shared framing is not a finding. Alternate renderings may contain
    equivalent evidence, but uncertainty must not suppress the authoritative copy;
    the existing final-wire deduplicator can fold genuine repeated evidence.
    """
    if not checks.strip():
        return True
    return any(isinstance(m.get('content'), str) and checks in m['content']
               for m in body.get('messages') or [])


def _gate_commands(flag: str) -> list[str]:
    """The ``$ command`` heads a gate block names — read from the block cria itself composed."""
    return [m.group(1).strip() for m in re.finditer(r"(?m)^\$ (.+?)(?: — |$)", flag or "")]


def _track_own_checks(sess, messages: list[dict]) -> None:
    """Remember the coder's OWN runs of the commands the last gate ran, with when and how they ended.

    Every shell run is marked seen the first time it is met, whether or not a gate block exists yet, so
    a run from before a gate is never mistaken for one after it. cria's own replay of the checks
    (``⟦ctx:checks⟧``) is not the coder's run."""
    if sess is None:
        return
    if getattr(sess, "own_check_seen", None) is None:
        sess.own_check_seen = set()
    if getattr(sess, "own_check_runs", None) is None:
        sess.own_check_runs = []
    heads = _gate_commands(getattr(sess, "last_gate_flag", ""))
    head_words = {}
    for head in heads:
        parsed = dirguard._input_commands(head, unwrap=False)
        if parsed and len(parsed) == 1:
            head_words[head] = parsed[0][2]
    own_gate = probegate.gate_call_ids(messages or [])   # cria's own gate command, by its provenance stamp
    for tid, cmd, res in _shell_runs(messages):
        if ("s", tid) in sess.own_check_seen:
            continue
        sess.own_check_seen.add(("s", tid))
        if (not heads or tid in own_gate
                or getattr(sess, "action_seq", 0) <= getattr(sess, "last_gate_seq", 0)):
            continue
        # Share the shell owner's code/input and argv boundaries. A redirect or
        # output filter does not turn a check into a different invocation, while
        # quoted text and saved heredoc contents are not executed commands.
        layout = shellinput.layout(cmd)
        substitutions, unknown = shellinput.expansions(layout.shell, shell=True)
        if layout.error or unknown:
            continue
        shell = shellinput.outer_shell(layout.shell, substitutions)
        # This lexical owner cannot distinguish executable groups from array or
        # function definitions. Do not promote stored body text to a run receipt.
        if any(c in "(){}" for _, c in dirguard._unquoted_chars(shell)):
            continue
        parts = dirguard._input_commands(shell, unwrap=False)
        if parts is None:
            continue
        named = [h for h, words in head_words.items()
                 if any(part[2] == words for part in parts)]
        if named:
            # A filter/background shell status is not the check's status; pipefail
            # can also attribute an earlier pipeline member's failure to the shell.
            # Only an exact final foreground command outside a pipeline owns it.
            final = next((part for part in reversed(parts) if part[2]), None)
            owns_status = bool(final and shell[final[0]:final[1]].strip() in named
                               and not shell[final[1]:].strip()
                               and not shell[:final[0]].rstrip().endswith("|"))
            from .resultnotes import exec_envelope
            envelope = exec_envelope(res)
            code = envelope.exit_code if envelope is not None and owns_status else None
            sess.own_check_runs.append((sess.action_seq, named, code))


def newer_own_run(sess) -> str:
    """The carried check block's age against the coder's own LATER evidence: "" when the coder has not
    re-run any of those commands since the gate, else one fact naming the newest such run — which
    commands, how many calls ago, and the exit code when it is the gate command's own. cria does not
    say the run's output is still available (compaction may have removed it) nor restate it."""
    runs = [r for r in (getattr(sess, "own_check_runs", None) or []) if r[0] > getattr(sess, "last_gate_seq", 0)]
    if sess is None or not runs:
        return ""
    seq, cmds, code = runs[-1]
    ago = max(0, getattr(sess, "action_seq", 0) - seq)
    return prompts.fill(prompts.load("checks_note_newer_run"),
                        commands=", ".join(f"`{c}`" for c in cmds),
                        ago=(f"{ago} of your calls before this handoff" if ago
                             else "your latest call before this handoff"),
                        exit=f", and that run exited with code {code}" if code is not None else "")


def gate_unedited(sess) -> bool:
    """True only when cria's own record shows NO file edit/write tool call of the coder's has been
    forwarded since the last gate's verdict was read — and none forwarded earlier whose result was still
    unknown at that moment — unless it is known to have failed.

    This claims what cria observed and nothing about the disk: a shell command can change files and
    is not in the registry (the wording built on this says so). The registry (`write_call_ids`) is
    filled from cria's own outbound completions, so it holds across requests and across compaction,
    and it counts every write-class call (write_file, edit_file/str_replace and native apply_patch
    lowered to it, and shell redirects) — a pending one is a write until its result says it did not
    run. False whenever cria cannot tell: no live registry, no mark, a registry shorter than the mark."""
    if sess is None or not getattr(sess, "last_gate_flag", ""):
        return False
    mark = getattr(sess, "gate_write_mark", None)
    ids = getattr(sess, "write_call_ids", None)
    if mark is None or not getattr(sess, "write_tracking", False) or ids is None or len(ids) < mark:
        return False
    refused = writeobservation.unlanded_ids(sess)
    pending = getattr(sess, "gate_pending_write_ids", None)
    if pending is None:
        return False
    # An outstanding write from before the verdict counts like one after it, unless it is known not to have run.
    return all(cid in refused for cid in list(ids[mark:]) + list(pending))


class GateAge(int):
    """The gate's age in the coder's own calls — an int to every existing reader — that also carries
    whether no edit/write tool call has landed in that time (``unedited``). One value, so the two
    halves of the fact (the writer's input framing and the handoff appendix) cannot decide it twice."""
    unedited: bool = False

    def __new__(cls, age: int, unedited: bool = False):
        obj = super().__new__(cls, age)
        obj.unedited = bool(unedited)
        return obj


def gate_age(sess) -> int:
    """How many of the coder's OWN calls have run since the last gate. 0 when cria cannot say.

    THE PRIMITIVE for both halves of one fact. A gate verdict is pinned into two places — the
    compaction writer's INPUT framing (`selfcompact.checks_input`) and the briefing's OUTPUT
    appendix (`server._last_checks_note`) — and each one says how current it is. They must not be
    able to disagree about the age, so neither of them computes it."""
    if sess is None:
        return GateAge(0)
    return GateAge(max(0, getattr(sess, "action_seq", 0) - getattr(sess, "last_gate_seq", 0)),
                   gate_unedited(sess))


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
    return repositorychecks.passing_test_regression(sess, report)


def _gate_notes(sess) -> str:
    """Ground-truth notes for the satisfaction judge about what the gate's test run actually
    verified (prompts/gate_notes.txt): the C4 vacuous-green (0 collected) and the skipped-count fact
    (0728-m11: live tests skipTest() on the exact failure that proves the deliverable broken, and
    "3 passed, 2 skipped" read as green). Empty when there is nothing to disclose — silence over
    noise, and never a doubt-hedge on a clean run."""
    lines = prompts.load_map("gate_notes")
    observed = participation.render_for_judge(
        getattr(sess, "last_gate_participation", None),
        fresh=getattr(sess, "gate_fresh", None))

    def with_observed(note: str) -> str:
        return "\n\n" + "\n\n".join(part for part in (note.strip(), observed) if part)
    # RED FIRST. A step may now advance over a red gate the step critic attributed to another step's
    # work (_verify_after_probe), so the plan can reach its end with the checks still failing — which
    # was structurally impossible before, and is the one way this change could have opened a
    # fail-OPEN on completion (principle 13). Preserve the observation without inventing currency;
    # stale red is neither proof of a present failure nor proof of a repair.
    if getattr(sess, "last_gate_red", False) and getattr(sess, "last_gate_flag", ""):
        key = 'red' if getattr(sess, 'gate_fresh', False) else 'historical_red'
        return with_observed(prompts.fill(lines[key], findings=sess.last_gate_flag.strip()))
    if getattr(sess, "last_gate_testless", False):
        return with_observed(lines["testless"])
    skipped = getattr(sess, "last_gate_skipped", 0)
    if skipped:
        return with_observed(prompts.fill(lines["skipped"], count=str(skipped)))
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
        return with_observed(lines["green"])
    return with_observed("") if observed else ""


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
        observation = prompts.fill(lines["red"], findings=sess.last_gate_flag.strip())
    elif getattr(sess, "last_gate_testless", False):
        observation = lines["testless"]
    else:
        return ""
    # The harness uses these same age/provenance owners and prompt fragments.
    # Anchor age to creation, not a later read of this frozen rolling increment.
    since = gate_age(sess)
    ages = prompts.load_map("compaction_check_age")
    age = prompts.fill(ages["aged"], calls=str(since)) if since else ages["fresh"]
    stale = (prompts.fill(prompts.load(
        "checks_note_staleness_unedited" if getattr(since, "unedited", False)
        else "checks_note_staleness"), calls=str(since))
        if since >= selfcompact.CHECKS_STALE_AFTER else "")
    return "\n\n" + observation + "\n" + prompts.fill(
        ages["observation"], age=age, staleness=stale + newer_own_run(sess))


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
    if not outcome.ran or probegate.gate_is_partial(outcome) or proberun.unran_probes(outcome.report):
        # …or a section cria selected never came back. Three ways to have read LESS than was asked
        # for, and none of them is a clean signal — the third one used to read as one.
        return ""    # never ran / a probe couldn't launch / a section is missing → stay silent
    return prompts.load("ground_truth_clean")


def guard_canned_redirect(gs: GuardState, outcome) -> str:
    if _stalled_selection(gs) is None:
        return ''
    return stalledwork._redirect(gs.repeat_count, gs.repeat_action, guard_ground_truth(outcome))


# ---- ONE reasoned steer author behind EVERY detector. A detector (repetition / wheel-spin / thrash /
# is a cheap deterministic TRIGGER; the steer itself is always REASONED here, grounded in the real
# session + the churned files' real on-disk bytes + the repo's checks (+ the coder's private reasoning
# when that was the trigger). It replaces the family of canned "stop rewriting / do something different"
# templates that could prescribe a broken tool or be misread as "abandon the file". The reasoner may
# reply ON_TRACK (the detector was a false positive) → we inject nothing (silence over a bad steer).
# One-line description of WHAT tripped, per condition — the only condition-specific text. Grounded in gs
# so the reasoner knows the concrete signal; the rest of the bundle (session/disk/truth) is uniform.
# THE SENTENCES LIVE IN prompts/steer_triggers.txt (#22), and none of them names the supervisor
# (#17) — the refusal line did, and was the last live occurrence of that token in model-facing text.
# The incident each one encodes is recorded beside it in that file.
_STEER_TRIGGER = {
    "refusal": lambda gs, step: prompts.fill(
        prompts.load_map("steer_triggers")["refusal"],
        count=gs.repeat_count, action=gs.repeat_action),
    "wheel_spin": lambda gs, step: prompts.fill(
        prompts.load_map("steer_triggers")["wheel_spin"],
        path=gs.spin_path, writes=WHEEL_SPIN_WRITES),
    "thrash": lambda gs, step: prompts.fill(
        prompts.load_map("steer_triggers")["thrash"], rounds=gs.gate_stall,
        edits=thrash_edits_clause(gs)),
}


# THE DURABLE FETCH LEDGER IS TYPED, NEVER SCANNED: `_extract_fetches` reads the producer's own `rep.fx` and nothing else, so
# there is no header, route or shape reader here — a fetched page, file or command output can quote any of them.

# ONE reader for the ledger tuple, in groundtruth — planner cannot import loop, and both plan
# judges need it. Kept as a module-level name here because a dozen call sites read it.
_fetch_facts = groundtruth.fetch_facts


def _extract_fetches(messages: list[dict]) -> dict:
    """url -> (status, routes, shapes, catalog) for every web_fetch the session really made (last occurrence wins).

    PROVENANCE, NOT RENDERING. A fetched page, a file or a command's output can quote a perfectly valid-looking
    `HTTP 200 · <url>` header and `[API endpoints …]` block, so no text is searched for them. The facts come from:

    * a cria-LOWERED `web_fetch` whose own record proved it ran: the producer's typed `fx` fact (`denial.report`), computed from
      its own parse of the document — and nothing else of that result is read;

    Every other result — a NATIVE `web_fetch` (its bytes stay visible, but no producer declared facts for them), a read, a shell
    command, an unproven or cut lowered fetch — is UNKNOWN here: no header or marker in text is ever read back as a fact."""
    latest: dict[str, tuple[str, str, str, str, str]] = {}
    paired = denial.paired_results(messages)
    names = {tc.get("id"): (tc.get("function") or {}).get("name")
             for m in messages if isinstance(m, dict) and m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])}
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("tool", "function_call_output") and m.get("type") != "function_call_output":
            continue
        tid = m.get("tool_call_id") or m.get("call_id")
        if paired.get(tid) is not m or names.get(tid) not in writeproxy._FETCH_NAMES:
            continue
        proof = denial.proof(m)
        if proof is not None:
            fx = denial.report(m).get("fx") if proof == denial.RAN else None
            if isinstance(fx, dict):
                latest[fx["url"]] = fetchfacts.entry_of(fx)
    return latest


def _merge_fetches(dst: dict, src: dict) -> dict:
    """Merge fetch facts, keeping the RICHER routes AND shapes per URL: a later ``web_fetch(url,
    find=…)`` returns a sub-section WITHOUT the ``[API endpoints]`` / ``[response shape]`` blocks, so
    those are empty — that must not clobber an earlier full outline (they are the whole point of the
    fact: they name /handles/{handle} and resolved_addresses{ada})."""
    for url, entry in src.items():
        status, routes, shapes, catalog = _fetch_facts(entry)
        observed = groundtruth.fetch_observed(entry)
        prev = dst.get(url)
        if prev:
            p_routes, p_shapes, p_catalog = _fetch_facts(prev)[1:]
            routes = routes or p_routes   # preserve the earlier outline when this occurrence had none
            shapes = shapes or p_shapes
            catalog = catalog or p_catalog
            observed = observed or groundtruth.fetch_observed(prev)
        dst[url] = (status, routes, shapes, catalog, observed)
    return dst


# ONE OWNER (research.fetch_succeeded). Two copies of "did this fetch work?" is how the research
# exit ended up reading only the bare-int spelling while every ledger in play carried "HTTP 200".
_fetch_succeeded = research.fetch_succeeded


# `{param}` in a route template stands for one path segment, never a slash.
_ROUTE_PARAM = re.compile(r"\{[^{}/]*\}")


def _route_templates(latest: dict) -> list[str]:
    """Every route the spec defined, across every fetch this session. cria parsed these itself."""
    seen: list[str] = []
    for entry in (latest or {}).values():
        for r in _fetch_facts(entry)[1]:
            r = r.strip()
            if r.startswith("/") and r not in seen:
                seen.append(r)
    return seen


def _param_descriptions(latest: dict) -> dict[str, str]:
    """route template -> the spec's own description of its path parameter, where cria rendered one."""
    out: dict[str, str] = {}
    for entry in (latest or {}).values():
        for shape in _fetch_facts(entry)[2]:             # the spec's own parameter notes, typed on the entry — not scanned out of its text
            if shape.route.startswith("/") and shape.params:
                out.setdefault(shape.route, "; ".join(shape.params).strip())
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


def _format_fetches(latest: dict, header: str = "PAGES YOU HAVE ALREADY FETCHED",
                    visible: set[str] | None = None, absent_out: list | None = None,
                    location: bool = True) -> str:
    """The durable fetch ledger, SPLIT by whether the fetch actually returned anything.

    ``visible`` is the set of URLs whose OWN fetch result is actually present in the messages this
    render is about to be sent alongside (webfetch.visible_urls — the exact-repeat gate's own
    identity). ``None`` means the caller did not check (kept for callers/tests that only care about
    the failed/spilled/no-structure splits, not this fact) and preserves the old assume-present
    behavior; a real ``set`` — possibly empty — makes the "in this conversation above" claim below
    actually true for entries it names true of (Candidate C31).

    ``absent_out``, when given a list, gets ``True`` appended iff at least one entry actually rendered
    the "not in this conversation" note — so a caller (the anchor tail) can scope its own "code
    against THOSE" sentence without re-deriving this fact.

    ``location=False`` renders NEITHER "in this conversation above" NOR "not in this conversation" for
    an unspilled no-structure entry — for a render about to be FROZEN into history a model cannot
    revise (the harness compaction summary, server._harden_compaction_reply). Either claim goes stale
    the moment the model re-fetches or the window moves: cria composed a page-not-visible claim into
    that frozen summary, the model then re-fetched the url, and the live per-turn facts block said
    "in this conversation above" for the SAME url — both now permanent, both read by the coder in the
    same body, contradicting each other (independent review of Candidate C31, repro c31contra.py).
    ``body_at`` for a spilled page is unaffected: the file on disk is a durable fact that does not go
    stale the way "is/is not in THIS conversation" does.

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
    visibility_labels = prompts.load_map("fetch_body_visibility")
    ok, failed = [], []
    any_absent = False  # did any entry actually use the "not in this conversation" note?
    for url, entry in latest.items():
        status, routes, shapes, catalog = _fetch_facts(entry)
        line = f"- {url} \u2192 {status}" + (f"; endpoints: {', '.join(routes)}" if routes else "")
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
        if (_fetch_succeeded(status) and not routes and not shapes and not catalog
                and webfetch.cached_structure(url) is False):
            any_routes = any(_fetch_facts(e)[1] for e in latest.values())
            if any_routes:
                # `no_spec_here` carries ITS OWN location claim ("its body is in the transcript
                # above") baked into the label, separate from the body_inline/body_absent/body_at
                # clause appended below. Left alone, a not-visible page could carry that claim AND
                # "Its body is NOT in this conversation" in the same sentence — self-contradictory
                # (re-review of Candidate C31, repro c31elide.py: 799 coder prompts, 200/200 in
                # Handles C27). Whenever visibility was actually checked, or this render is about to
                # be FROZEN (`location=False`), use the location-free variant so the location clause
                # — or its deliberate absence — is the ONE place this entry says where the body is.
                # `visible is None` (a caller that never checked) keeps the legacy wording verbatim.
                line += (visibility_labels["no_spec_here_no_location"]
                        if (visible is not None or not location) else labels["no_spec_here"])
            else:
                line += labels["no_structure"]
            # …AND SAY WHERE THE CONTENT ACTUALLY IS. The sentence above used to end "whatever it
            # returned is in the transcript", which is false for exactly the pages that most need
            # reading: an oversized doc is SPILLED to a file and the read of that file is then
            # refused, so the one place cria says to look is the one place it is not.
            #
            # Walked on `shipping-rates-rb x ternary-bonsai` 1787111689. cria fetched the rubydoc
            # page for `ISO3166::Country`, spilled it, refused the read — and then told the coder on
            # every later turn that the page held no definitions and its content was in the
            # transcript. Both false: the page defines `in_eu?` with its source, and the content was
            # on disk. The coder guessed `eu_member?`, which does not exist, and that guess is the
            # `country_zone_mapping` failure. cria composed the spill, so it knows the path (#5b).
            spilled = webfetch.spill_path_for(url)
            if spilled:
                line += prompts.fill(labels["body_at"], path=spilled)
            elif not location:
                pass   # frozen render — no claim that a later turn could falsify (see docstring)
            elif visible is None or url in visible:
                line += labels["body_inline"]
            else:
                line += visibility_labels["body_absent"]
                any_absent = True
        # The REAL field names — the half the coder guesses once they scroll away. Keep only the
        # per-endpoint entry lines: the captured block opens with webfetch's OWN header, and emitting
        # that under cria's label prints the same instruction twice.
        entries = [ln.strip() if k == 0 else ln.rstrip()                 # the typed entries' own display, never read back as facts
                   for s in shapes for k, ln in enumerate(fetchfacts.text(s).splitlines())]
        if entries:
            line += f"\n  {labels['fields']}\n" + "\n".join(f"  {e}" for e in entries)
        # A catalogue names WHERE each API's spec lives. Without this the durable ledger recorded the
        # fetch as "HTTP 200, no readable structure" and the hrefs — the only thing a catalogue has —
        # were gone the moment the raw result scrolled out.
        cat = [c.strip() for c in catalog]
        if cat:
            line += f"\n  {labels['descriptions']}\n" + "\n".join(f"  {c}" for c in cat)
        answered = research.fetch_answered(entry)
        if not answered:
            diagnosis = _failed_fetch_diagnosis(url, latest)
            line += f" {diagnosis}" if diagnosis else ""
        (ok if answered else failed).append(line)
    blocks = []
    if ok:
        blocks.append(prompts.fill(labels["ok"], header=header) + "\n" + "\n".join(ok))
    if failed:
        blocks.append(labels["failed"] + "\n" + "\n".join(failed))
    if any_absent and absent_out is not None:
        absent_out.append(True)
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


def _session_refusals(sess):
    """The structured refusal ledger when present, otherwise the legacy set.

    The distinction between ``None`` and an empty ledger matters: an empty structured ledger may be
    the truthful result of a later success superseding its last refusal. Falling back to the old set
    there would resurrect the stale event.
    """
    if sess is None:
        return None
    ledger = getattr(sess, "refusal_events", None)
    if isinstance(ledger, refusalledger.RefusalLedger):
        return ledger
    return getattr(sess, "refused_names", None)


def _track_refused_names(sess, messages: list[dict]) -> None:
    """Track ordered refusal/success provenance and refresh the compatibility name set.

    Tool-call ids de-duplicate the append-only history, while the event sequence survives history
    compaction. A later exact successful coordinate, or an unambiguously successful rerun of the
    exact command that produced the refusal, supersedes it; unrelated successes do not.
    """
    if sess is None:
        return
    ledger = getattr(sess, "refusal_events", None)
    if not isinstance(ledger, refusalledger.RefusalLedger):
        ledger = refusalledger.RefusalLedger.from_legacy(getattr(sess, "refused_names", None) or set())
    ledger.observe(messages)
    sess.refusal_events = ledger
    sess.refused_names = ledger.active_names()


# The read tools by their canonical names — `massage.normalize_tool_names` has already mapped a
# harness's spelling onto these by the time the loop sees a message.
_READ_TOOL_NAMES = ("read_file", "cat_file", "view_file")


def _extract_reads(messages: list[dict]) -> dict:
    """path -> (bytes, "N bytes, M lines") for every workspace read that actually returned content.

    TOOL RESULTS ONLY, the same rule the fetch ledger follows: a read the coder merely SAID it did
    proves nothing, and a refused read returned no content to remember.

    A RANGED READ SAYS SO. The size describes what came BACK, and `read_file` takes `start_line` /
    `end_line` — so a 16-line window on a 237-line file was recorded as "751 bytes, 16 lines" under
    the file's own path, and the ledger then told the coder that was the file. Walked on the sub-40
    pass, feed-pipeline-java x nemotron-elastic (scored 16): at call 0070 the coder acted on it. cria
    composed both halves of that sentence, so it is a false fact of cria's own making (#5b).

    The byte count rides along because it is what decides which reading to KEEP: a later window must
    not replace a whole-file read in the ledger. Largest wins — a window is never larger than the
    file it came out of."""
    out: dict = {}
    for ev in _file_events(messages):
        if ev[2] in ("read", "shell"):      # a shell event is also how an unverifiable result abstains
            _apply_ledger_event(out, ev)
    return out


def _count_lines(text: str) -> int:
    """THE ONE LINE-COUNTING RULE for every count the ledger states — what a read or a write returned (``last``)
    and what the workspace's body holds now (``now``): the lines of ``text`` as `sed -n` numbers them, a final
    newline ending its line rather than starting another. (The read tool strips that newline and a write body
    keeps it, so `count("\\n") + 1` called one file N lines and the same file written N+1.)"""
    return text.count("\n") + (0 if not text or text.endswith("\n") else 1)


def _read_label(start, end, c: str) -> str:
    """What one read RETURNED, in the ledger's words. LINE COUNT ONLY, NO BYTE COUNT. The live
    ⟦ctx:files⟧ listing owns the byte size of every present file, read from os.stat. This ledger
    measured `len(read-result)`, which the read tool returns with the trailing newline stripped — so
    for one unchanged file it said 984 where the listing said 985, in the same prompt. Walked on
    ornith15 x shipping-rates-rb 2026-09-07: that uniform 1-byte gap across every file was the exact
    "the numbers are slightly off, so cria is fabricating" tell the original run weaponised into a
    ~100-turn distrust cascade. One owner for the byte metric; this ledger keeps the per-file fact it
    owns (you looked) and its line count, which never collides.

    A window that ran into the end of the file (asked 1-130 of a 106-line file) IS the file, and says
    so: the count is the lines that came back, never the end of the range asked for."""
    label = f"{_count_lines(c)} lines"
    if not _read_is_whole(start, end, c):
        label = prompts.fill(prompts.load_map("fetched_facts_sections")["read_range"],
                             range=_line_range(start, end), size=label)
    return label


def _raw_read_bytes(start, end, c: str):
    """The byte length of what a read returned WHEN THAT IS THE FILE'S OWN BYTES, else None. Only an unwindowed
    read returns them: a window comes back line-numbered (so even a 1-to-EOF window, which `_read_label` calls
    the plain file, is longer than the file), a harness-cut result is shorter, and a text that held bytes that
    are not UTF-8 was re-encoded larger. ``None`` means "no byte count to compare with the workspace's size"
    (`_dated_count` then claims nothing), never a guess."""
    if start or end or "\ufffd" in c or writeproxy.note_harness_cuts([{"role": "tool", "content": c}]):
        return None
    return len(c.encode("utf-8", "replace"))


class _Counted(str):
    """A ledger label ``"N lines"`` whose basis is a LINE COUNT (a landed edit's echo, ranged reads that cover the
    file) rather than a read's bytes — :func:`_dated_count` can compare it with the workspace's own count."""
    __slots__ = ()


class _Unestablished(str):
    """A ledger label that is NOT the file's state at the coder's latest touch: a window that did not complete
    the file was read (or an edit landed with no size reported) after the whole reading it carries. The text is
    kept for what it was; :func:`_dated_count` never states it as the count when the coder last read or wrote."""
    __slots__ = ()


def _edit_total_pattern():
    """The regex that reads the file's size off cria's own edit echo, cut from the echo templates themselves
    (``{{PATH}} now has {{TOTAL}} lines; …``) so the two cannot drift."""
    tpl = prompts.load("edit_echo")
    mid = tpl.partition("{{PATH}}")[2].partition("{{TOTAL}}")[0]
    after = tpl.partition("{{TOTAL}}")[2].split(";")[0]
    return re.compile(r"^(?P<path>.+?)" + re.escape(mid) + r"(\d+)" + re.escape(after) + ";", re.M)


def _edit_landings(messages: list[dict]):
    """``(position, id, path, total lines or None)`` of every edit that LANDED. The total is the post-edit size the
    edit echo reported for the path — a tool result, never assistant text — or None when no echo carried one."""
    pat = _edit_total_pattern()
    for idx, tid, path, res in _edit_results(messages):
        total = next((int(m.group(2)) for m in pat.finditer(res) if m.group("path").strip() == path), None)
        yield idx, tid, path, total


def _late_landed_ids(messages: list[dict]) -> set:
    """Ids of calls whose OWN program reported its mutation landed but ran before a same-file predecessor of its turn had finished
    (`late`, a typed field of the producer's record — never read off wording). Their position in the history orders nothing: the
    predecessor's completion is not attributable, so what the file holds afterwards is unestablished."""
    return {tid for tid, m in denial.paired_results(messages).items()
            if denial.landed(m) and denial.report(m).get("late")}


def _file_events(messages: list[dict], key=None) -> list:
    """Every read, landed write and landed edit in ``messages``, oldest first: ``(position, id, kind, path,
    nbytes, label, partial)``. One ordered stream, because what the ledger says about a path is its NEWEST
    state — a bigger OLD reading must never outrank a newer smaller one (phi4 A4 CALL 0270: `Importer.java
    (130 lines)` for the 106-line file the coder had since rewritten, `pom.xml (21 lines)` for a 12-line
    one; both numbers were true once, of a file that no longer existed).

    THE BASIS IS THE LATEST TOUCH (O15). A landed edit is a touch (its echo reports the post-edit size), and
    ranged reads that TOGETHER cover line 1 to the end of a file of known size are one whole reading, of that
    size, at the position of the last page (ornith1.5_9b Java B3 0087: `246 lines when you last read or wrote
    it` after the coder read the whole 267-line file in pages and landed two edits). A synthesized whole
    event has id ``("c", tid)``; an edit has ``("e", tid)`` and kind ``edit``."""
    norm = key or (lambda p: p)       # ONE spelling per file BEFORE anything is grouped, invalidated or merged
    raw = []
    for idx, tid, path, start, end, c in _read_results_ordered(messages):
        if c is None:       # the payload's provenance is unverifiable: whatever was known of this path is now unestablished
            raw.append((idx, "shell", tid, norm(path)))
            continue
        raw.append((idx, "read", tid, norm(path), start, end, c))
    # A landed mutation that RAN EARLY (its program's typed `late` report: a predecessor for the same file had not finished when
    # it started) says what its own bytes were, not what the file is: that predecessor may land after it. It is a touch of an
    # unestablished state, like a command whose effect is unknown, never a size.
    late = _late_landed_ids(messages)
    for idx, tid, path, nbytes, label in _write_events(messages):
        raw.append((idx, "shell", tid, norm(path)) if tid in late else (idx, "write", tid, norm(path), nbytes, label))
    for idx, tid, path, total in _edit_landings(messages):
        raw.append((idx, "shell", tid, norm(path)) if tid in late else (idx, "edit", tid, norm(path), total))
    for idx, path, n in _refused_line_counts_ordered(messages):
        raw.append((idx, "refuse", None, norm(path), n))
    for idx, tid, path in _shell_mutations(messages):
        raw.append((idx, "shell", tid, norm(path) if path else None))
    raw.sort(key=lambda e: e[0])
    events = []
    spans: dict = {}            # path -> {"spans": [(a, b)], "eof": line the file ends at (or None), "done": bool}
    known: dict = {}            # path -> size cria's own refusal reported since the path last changed
    for e in raw:
        idx, kind, tid, path = e[:4]
        if kind == "refuse":
            known[path] = e[4]
        elif kind == "shell":
            # A shell command that wrote something: whatever it changed, the pages and sizes gathered so far
            # no longer describe it. An unknown target (None) invalidates every path (the basis is unknown).
            if path is None:
                spans.clear()
                known.clear()
            else:
                spans.pop(path, None)
                known.pop(path, None)
            events.append((idx, ("s", tid), "shell", path, None, None, False))
        elif kind == "write":
            spans.pop(path, None)
            known.pop(path, None)
            events.append((idx, ("w", tid), "write", path, e[4], e[5], False))
        elif kind == "edit":
            spans.pop(path, None)
            known.pop(path, None)
            events.append((idx, ("e", tid), "edit", path, None, _Counted(f"{e[4]} lines") if e[4] is not None else None, False))
        else:
            _k, _t, _p, start, end, c = e[1:]
            whole = _read_is_whole(start, end, c)
            events.append((idx, ("r", tid), "read", path, _raw_read_bytes(start, end, c),
                           _read_label(start, end, c), not whole))
            span = _read_span(start, end, c)
            if span is None:
                continue
            if span[1] is None:
                spans.pop(path, None)
                continue
            st = spans.setdefault(path, {"spans": [], "eof": None, "done": False})
            st["spans"].append((span[0], span[1]))
            if span[2]:
                st["eof"] = span[1]       # the line the file ENDS at — not the end of the contiguous prefix
            covered = 0
            for a_, b_ in sorted(st["spans"]):
                if a_ > covered + 1:
                    break
                covered = max(covered, b_)
            size = st["eof"] if st["eof"] is not None else known.get(path)
            if not whole and not st["done"] and covered and size is not None and covered >= size:
                st["done"] = True
                events.append((idx, ("c", tid), "read", path, None, _Counted(f"{size} lines"), False))
    events.sort(key=lambda e: e[0])
    return events


def _apply_ledger_event(d: dict, ev, key=None) -> None:
    """Fold one event into ``d`` (path -> (nbytes, label)): the newest reading wins. The one exception
    is a WINDOW that did not reach the end of the file — it says nothing about the rest, so it does not
    displace an earlier reading of the whole (the ledger answers "have I looked at this file")."""
    _idx, _id, kind, path, nbytes, label, partial = ev
    if kind == "shell":
        # A command that wrote something (path None: it is not known what): the recorded basis is no longer
        # the file at the latest touch — kept for what it was, never claimed.
        for p in ([key(path) if key else path] if path else list(d)):
            if p in d and not d[p][1].startswith("lines "):
                d[p] = (None, d[p][1] if isinstance(d[p][1], _Unestablished) else _Unestablished(d[p][1]))
        return
    path = key(path) if key else path
    prev = d.get(path)
    if kind in ("write", "edit") and prev is None:
        return                       # a write is not a read; written_files owns it
    if kind == "edit":
        d[path] = (None, label) if label is not None else (None, _Unestablished(prev[1]))
        return
    if partial and prev is not None and not prev[1].startswith("lines "):
        # The window is the coder's latest touch and it does not say how big the whole file is: the whole
        # reading it keeps is no longer the state at the latest touch, and is not claimed to be (O15).
        d[path] = (None, prev[1] if isinstance(prev[1], _Unestablished) else _Unestablished(prev[1]))
        return
    d[path] = (nbytes, label)


def _read_results(messages: list[dict]):
    """``(path, start_line, end_line, result text)`` for every workspace read that returned content —
    the one parse :func:`_extract_reads` and :func:`_extract_whole_reads` share."""
    for _idx, _tid, *rest in _read_results_ordered(messages):
        if rest[-1] is not None:            # None: a provenance that cannot be verified — no file text to parse
            yield tuple(rest)


def _read_results_ordered(messages: list[dict]):
    """:func:`_read_results` with the result message's position and its tool-call id in front."""
    from . import denial
    from . import denial as _den
    paired = set(_den.paired_results(messages))   # canonical call/result pairing: ambiguous results attribute nothing
    calls: dict = {}
    answered_by_read: set = set()
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") in _READ_TOOL_NAMES and tc.get("id"):
                args = _args_of(fn.get("arguments") or "")
                p = _path_of_args(fn.get("arguments") or "")
                if p:
                    calls[tc["id"]] = (p, args.get("start_line"), args.get("end_line"))
            elif fn.get("name") in writeproxy_names and tc.get("id") \
                    and (p := _path_of_args(fn.get("arguments") or "")):
                calls.setdefault(tc["id"], (p, None, None))   # only a read-instead result counts (below)
                answered_by_read.add(tc["id"])
        tid = m.get("tool_call_id") or m.get("call_id")
        if tid in calls and tid in paired:
            c = m.get("content") if m.get("content") is not None else m.get("output")
            unverified = False
            if isinstance(c, str):
                # What cria APPENDED to this result is not the file. The producer recorded where the payload
                # ended over the COMPLETE message (`writeproxy.payload_of`): consume it FIRST, then look inside
                # the payload (a read-instead envelope). A boundary that no longer verifies means the payload
                # is unknown — the ledger abstains (None), it never counts the annotated carrier.
                c = writeproxy.payload_of(m, c)
                unverified = c is None
            if tid in answered_by_read:
                # A write_file the coder sent for a file it never read, ANSWERED with that file (H1):
                # the result is a whole read of the path. Any other result of a write is not a read.
                # ONE OWNER: only a verified body (`denial.read_payload`) is the file's bytes; a refusal that merely
                # quotes a marker, a file body that does, and every unproven result are not.
                c = denial.read_payload(m)
                if c is None:
                    continue
            elif (proven := denial.read_payload(m)) is not None:
                c = proven          # the producer's VERIFIED body (whole file or numbered window) — an EMPTY file included
            elif denial.proof(m) is not None:
                continue            # a cria-lowered read whose body did not verify (cut, rewritten, no record): unknown
            elif unverified:
                pass
            elif not isinstance(c, str) or not c.strip() or not denial.attributable_read(m):
                continue            # cria's own refusal, or a lowered result whose branch is unproven: not file bytes
            yield (idx, tid, *calls[tid], c)


_NUMBERED = re.compile(r"(\d+): ")


def _read_is_whole(start, end, text: str) -> bool:
    """Did this one read return the WHOLE file — no window asked for, or a window that opens at line 1
    and ran into the end. A window from line 50 that reaches the end is the tail, not the file."""
    span = _read_span(start, end, text)
    return span is not None and (span[1] is None or (span[0] <= 1 and span[2]))


def _read_span(start, end, text: str):
    """``(first, last, reached_end)`` — the file lines one read result carries, or None when it carries
    none. No window asked for: the whole file (line 1 to the end). A window is read off its own line
    numbers (`N: text`); it reached the end of the file when it asked for no end line, or came back
    short of the lines it asked for. An 8-line prefix of a 29-line pom.xml reached nothing (phi4 A4
    0047, then overwritten whole)."""
    if not (start or end):
        return (1, None, True)
    first = _NUMBERED.match(text)
    if first is None:
        return None
    n = len(text.rstrip("\n").split("\n"))
    a = int(first.group(1))
    return (a, a + n - 1, not end or n < end - a + 1)


def _refused_line_counts(messages: list[dict]) -> dict:
    """``path -> lines`` from cria's own over-size refusals (newest wins) — see :func:`_refused_line_counts_ordered`."""
    return {p: n for _i, p, n in _refused_line_counts_ordered(messages)}


def _refused_line_counts_ordered(messages: list[dict]):
    """``(position, path, lines)`` from cria's own over-size refusals still in ``messages`` (`large_read_steer`: "X is N
    lines, which is larger than can be returned in one read"), for a read — or a write answered with one.
    The regex is cut from that prompt's own words, so the two cannot drift."""
    from . import denial
    paired = set(denial.paired_results(messages))   # canonical call/result pairing: ambiguous results attribute nothing
    tpl = prompts.load("large_read_steer")
    mid, _, rest = tpl.partition("{{PATH}}")[2].partition("{{LINES}}")
    # The first sentence's shared size phrase also recognizes refusals retained from before
    # the follow-up wording changed; provenance still comes from the paired refusal.
    size_phrase = rest.split("{{")[0].partition(". ")[0]
    pat = re.compile(re.escape(mid) + r"(\d+)" + re.escape(size_phrase))
    calls: dict = {}
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") in _READ_TOOL_NAMES or fn.get("name") in writeproxy_names:
                if tc.get("id") and (p := _path_of_args(fn.get("arguments") or "")):
                    calls[tc["id"]] = p
        tid = m.get("tool_call_id") or m.get("call_id")
        c = m.get("content") if m.get("content") is not None else m.get("output")
        if tid in calls and tid in paired and isinstance(c, str) and denial.refused(m) and (hit := pat.search(c)):
            yield idx, calls[tid], int(hit.group(1))


def _extract_whole_reads(messages: list[dict], view=None) -> set:
    """Paths whose WHOLE text the read results still in ``messages`` carry: one read of no window, or
    windows that together cover line 1 to the end of the file. The end is known when a window came back
    short of its request, from cria's own over-size refusal ("N lines"), or from the workspace ``view``'s
    own copy of the file. A file over one read's
    byte limit can only be read this way — the refusal tells the coder to read it in line ranges — so a
    rule that credited only a single read would hold its rewrite forever. Paths are keyed by
    ``view.rel`` when a view is given, so an absolute and a relative spelling of one file merge."""
    key = (lambda p: view.rel(p) or p) if view is not None else (lambda p: p)
    whole: set = set()
    spans: dict = {}
    lines_of = {key(p): n for p, n in _refused_line_counts(messages).items()}
    for path, start, end, c in _read_results(messages):
        span = _read_span(start, end, c)
        if span is None:
            continue
        k = key(path)
        if span[1] is None:
            whole.add(k)
            continue
        entry = spans.setdefault(k, {"spans": [], "eof": False})
        entry["spans"].append((span[0], span[1]))
        entry["eof"] = entry["eof"] or span[2]
    for k, entry in spans.items():
        covered = 0
        for a, b in sorted(entry["spans"]):
            if a > covered + 1:
                break
            covered = max(covered, b)
        else:
            known = lines_of.get(k) or (_line_count(view, k) if view is not None else 10 ** 9)
            if covered and (entry["eof"] or known <= covered):
                whole.add(k)
    return whole


def _line_count(view, rel: str) -> int:
    """Lines in the view's own copy of ``rel`` (as `sed -n` numbers them); a huge number when it holds none."""
    raw = view.read_bytes(rel)
    return len(raw.decode("utf-8", "replace").splitlines()) if raw is not None else 10 ** 9


def _args_of(args) -> dict:
    """A tool call's arguments as a dict — {} when they are not readable JSON, never a guess."""
    try:
        obj = json.loads(args) if isinstance(args, str) else dict(args or {})
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _line_range(start, end) -> str:
    """The window a ranged read asked for, in the words the ledger prints — one end may be open."""
    if start and end:
        return f"{start}-{end}"
    return f"from {start}" if start else f"up to {end}"


def _extract_writes(messages: list[dict]) -> dict:
    """path -> (bytes, "N bytes, M lines") for every write that actually LANDED.

    THE SIBLING THE LEDGER WAS MISSING. :func:`_extract_reads` records what a read returned, and
    a read says what the file was WHEN READ — wrong once the coder WRITES it. The recorded size stops describing the file and nothing
    ever corrects it, because the ledger only refreshes on a read.

    Measured on all three cells of the 2026-08-28 walk, found independently by nine walkers. go
    0010: `cart.go (894 bytes, 44 lines)` for a file rewritten at 0009. ruby 0036: `rates.rb (984
    bytes, 25 lines)` for a file rewritten at 0026 — and there the stale number CORROBORATED a stale
    copy still in the transcript, so the coder sent an edit whose `old_string` blended the old and
    new versions of one file. go 0097-0116: `go.mod (68 bytes, 5 lines)`, twenty calls after the
    write. The header presents these as facts about the workspace (#5b).

    cria composed the write, so it holds the bytes exactly — nothing is measured on the filesystem
    and nothing is guessed. A refused write is not a write: the same `denial` bar the read side
    already applies, for the same reason (an attempted write is not a write)."""
    out: dict = {}
    for _idx, _tid, path, nbytes, label in _write_events(messages):
        out[path] = (nbytes, label)
    return out


def _shell_mutations(messages: list[dict]):
    """``(position, id, None)`` of every ANSWERED shell command that may have written files, read off the
    shell-mutation owner (`shelltool.writes_something` — the one question writeproxy's staleness ledger asks
    too). The target is always None: a redirect/`tee` parse cannot prove which files a command wrote (several
    `tee` targets, `+` in a name, the tool's own `workdir`), so the caller claims nothing about ANY file.
    Only cria's own gate probes are exempt, and only by the provenance the gate stamped on the call itself
    (`probegate.gate_call_ids`) — never by what the command text says. Output is never read for a count."""
    from . import probegate, shelltool
    own = probegate.gate_call_ids(messages or [])
    calls: dict = {}
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if tc.get("id") and is_shell_tool_name(fn.get("name")) and tc["id"] not in own:
                cmd = _command_text(fn.get("arguments") or "")
                if cmd is None or shelltool.writes_something(fn.get("name"), cmd):
                    calls[tc["id"]] = True            # (a cut-off call: whatever it did is unknown)
        tid = m.get("tool_call_id") or m.get("call_id")
        if tid in calls:
            calls.pop(tid)
            yield idx, tid, None


def _write_events(messages: list[dict]):
    """``(position, id, path, bytes, label)`` for every write that landed — see :func:`_extract_writes`."""
    from . import denial
    from . import denial as _den
    paired = set(_den.paired_results(messages))   # canonical call/result pairing: ambiguous results attribute nothing
    calls: dict = {}
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") in writeproxy_names and tc.get("id"):
                args = _args_of(fn.get("arguments") or "")
                path = _path_of_args(fn.get("arguments") or "")
                body = args.get("content")
                if path and isinstance(body, str):
                    calls[tc["id"]] = (path, body)
        tid = m.get("tool_call_id") or m.get("call_id")
        if tid in calls and tid in paired:
            res = m.get("content") if m.get("content") is not None else m.get("output")
            if not (isinstance(res, str) and denial.landed(m)):
                continue                      # refused or failed — only cria's own typed `landed` record lands a write
            path, body = calls[tid]
            raw = body.encode("utf-8", "replace")
            yield idx, tid, path, len(raw), f"{_count_lines(body)} lines"   # bytes owned by the ⟦ctx:files⟧ listing


def _ledger_key(sess):
    """path -> the ONE key a file goes by: workspace-relative when the workspace is known (the same file
    read as `/abs/ws/pom.xml` and `pom.xml` was two ledger lines, 29 lines and 21 — phi4 A4 CALL 0270)."""
    root = getattr(sess, "workspace_root", None)
    if not root:
        return lambda p: p
    view = wsview.current(root)
    return lambda p: view.rel(p) or p


def _track_read_files(sess, messages: list[dict]) -> None:
    """Accumulate the workspace files the coder has read, durably — the sibling of
    :func:`_track_fetched_pages`, for the half of its research that lives on disk."""
    if sess is None:
        return
    if getattr(sess, "read_files", None) is None:
        sess.read_files = {}
    if getattr(sess, "read_ledger_seen", None) is None:
        sess.read_ledger_seen = set()
    key = _ledger_key(sess)
    if getattr(sess, "file_touch", None) is None:
        sess.file_touch = {}                          # rel -> sequence of the last read / write / landed edit
    events = _file_events(messages, key)
    touched = [(ev[0], ev[1], ev[3]) for ev in events]
    for _pos, tid, path in sorted(touched, key=lambda e: e[0]):
        if tid not in sess.read_ledger_seen and path is not None:
            sess.file_touch[key(path)] = 1 + max(sess.file_touch.values(), default=0)
    for ev in events:
        if ev[1] not in sess.read_ledger_seen:        # each event folds in once, so order is real time
            sess.read_ledger_seen.add(ev[1])
            _apply_ledger_event(sess.read_files, ev, key)
    sess.read_ledger_seen.update(t for _p, t, _x in touched)
    # A file the coder WROTE is one it has seen, and its own write may be compacted away long before it
    # is rewritten — so the record is durable like the reads (`_coder_has_seen`).
    if getattr(sess, "written_files", None) is None:
        sess.written_files = {}
    sess.written_files.update(_extract_writes(messages))


def _ledger_state(sess, messages: list[dict]):
    """``(ledger, events, key)`` — the session's durable read/write ledger with this window's not-yet-folded
    events applied on top (path -> (nbytes, label)), the events themselves, and the path key. One reading of
    "what has this session read or written", shared by the ⟦ctx:facts⟧ ledger and the restored-text block."""
    seen = dict(getattr(sess, "read_files", None) or {})
    key = _ledger_key(sess)
    done = getattr(sess, "read_ledger_seen", None) or set()
    events = _file_events(messages or [], key)
    # Events not yet folded into the durable record apply on top of it, oldest first: the newest thing
    # cria knows about a path is what the ledger says (a write is a new state, not a competing reading).
    for ev in events:
        if ev[1] not in done:
            _apply_ledger_event(seen, ev, key)
    return seen, events, key


def _read_ground_truth(sess, messages: list[dict], restored: dict | None = None) -> str:
    """The workspace files the coder has already read — paths and sizes, never contents.

    Contents are not repeated here: what the coder loses at compaction is the KNOWLEDGE THAT IT HAS ALREADY
    LOOKED, and that is one line per file. The text of a file the coder no longer holds rides in its own
    message (:func:`_restored_text_message`); an entry whose text rides there THIS turn (``restored``) says
    so, and the wire takes that back if the floor shed the block (``modelview.settle_restored_text``)."""
    seen, events, key = _ledger_state(sess, messages)
    if not seen:
        return ""
    labels = prompts.load_map("fetched_facts_sections")
    # ABSENCE, MEASURED — NEVER PRESENCE. The ledger is durable: it outlives the messages it was built
    # from, so "you read this" says nothing about whether the read RESULT is in the window, and the old
    # header told the coder to "look for it above" in a conversation holding no tool result at all
    # (phi4 A2 0042). An entry is marked when no non-refused read result for its path is among the
    # messages this anchor is built for. That claim survives the floor (the floor only removes
    # messages); the opposite one — "its result IS here" — would be true only before it, and an
    # anchor is built before the floor, so it is never said (#5b). The wording names no action.
    # The one presence claim ("its current text is below") is made of a block the wire re-checks.
    live = {key(ev[3]) for ev in events if ev[2] == "read"}
    note = {p: (labels["read_restored"] if p in (restored or {}) else
                "" if p in live else labels["read_out_of_view"]) for p in seen}
    view = _surveyed_view(sess)
    lines = "\n".join(f"- {p} ({_dated_count(view, p, n, size, labels)}){note[p]}"
                      for p, (n, size) in sorted(seen.items()))
    rest = 0
    more = prompts.fill(labels["read_more"], count=rest) if rest else ""
    return "\n\n" + prompts.fill(labels["read_header"], files=lines, more=more)


def _reorientation_inventory(sess, messages: list, rlog) -> str:
    """The workspace listing for the post-compaction orienter.

    This request's own survey when it carries one. Otherwise the survey the briefing writer was shown,
    which cria's own hardener recorded in the compaction request — but only when that hardener produced
    the continuation this request carries (`matches_continuation`) and the listing describes this
    session's workspace root, so another boundary's or another root's listing is never presented as
    this one's. The view is rebuilt per request from the conversation, and a
    compaction removes every survey from it: the orienter's WORKSPACE INVENTORY was empty in 28 of 32
    captured prompts. Walked on ornith1.5_9b / Java overnight run 4 (reasoner 0043): with no listing
    it read the folded `src/  (main)` line as the whole tree, told the coder the inventory named only
    README.md, pom.xml, data/ and target/ — not the Importer.java the session had just rewritten — and
    to re-establish a baseline; the coder restored the seed over its rewrite."""
    current = workspace_inventory(sess.workspace_root or "", flavor="briefing")
    if current:
        rlog.emit("loop.reanchor_inventory", source="current")
        return current
    origin = getattr(sess, "handoff_origin", None)
    summary = next((_msg_text_content(m) for m in reversed(messages) if m.get("role") == "user"
                    and CONTINUATION_MARKER in _msg_text_content(m)), "")
    root = os.path.normpath(sess.workspace_root) if sess.workspace_root else ""
    if (isinstance(origin, _HandoffOrigin) and origin.inventory and origin.matches_continuation(summary)
            and root and os.path.normpath(origin.inventory_root or "") == root):
        rlog.emit("loop.reanchor_inventory", source="boundary")
        return origin.inventory
    rlog.emit("loop.reanchor_inventory", source="none")
    return ""


def _surveyed_view(sess):
    root = getattr(sess, "workspace_root", None)
    view = wsview.current(root) if root else None
    return view if view is not None and getattr(view, "surveyed", False) else None


_WHOLE_COUNT = re.compile(r"\d+ lines")


def _dated_count(view, rel: str, nbytes: int, label: str, labels: dict) -> str:
    """The ledger's size for ``rel`` made true of the workspace NOW. A line count is a fact about the file when
    it was read or written; edits that landed since never refresh it (phi4 A10: "127 lines" beside a ⟦ctx:files⟧
    listing of 9,123 B — the file had 243 lines). The workspace's own size for the file (the number the listing
    prints) is compared with the bytes that reading returned; when they differ the count is DATED, and replaced
    by a measured one when the view holds the current body. A reading of a window, or a workspace nothing is known
    of, is left as it is (it claims nothing about the whole file / nothing can contradict it). A 1-byte gap is the
    read tool's stripped trailing newline, never a change (`_read_label`)."""
    if isinstance(label, _Unestablished):
        # The latest touch (a window, or an edit with no size reported) left no known size: claim nothing about
        # "when you last read or wrote it" — say only what the workspace's own copy says now, or that it is not known.
        now = _current_line_count(view, rel)
        return prompts.fill(labels["read_now_only"], now=now) if now is not None else labels["read_basis_unknown"]
    if view is None or not _WHOLE_COUNT.fullmatch(label):
        return label
    if isinstance(label, _Counted):
        # A basis established as a LINE COUNT (a landed edit's echo, ranged reads that together cover the file):
        # compare the count with the workspace's own, when it holds the current body.
        now = _current_line_count(view, rel)
        if now is None or f"{now} lines" == label:
            return label
        return prompts.fill(labels["read_changed_now"], now=now, then=label)
    size = view.size(rel)
    if nbytes is None or size is None or abs(size - nbytes) <= 1:
        return label
    raw = None if view.may_have_changed else view.read_bytes(rel)
    if raw is not None and len(raw) == size:
        return prompts.fill(labels["read_changed_now"], now=_count_lines(raw.decode("utf-8", "replace")),
                            then=label)
    return prompts.fill(labels["read_changed"], then=label)


def _current_line_count(view, rel: str):
    """Lines in the workspace view's copy of ``rel`` when that copy is the file as it is NOW (the view's own size
    agrees with the body, and no command that may have changed files ran since), else None."""
    if view is None or view.may_have_changed:
        return None
    size, raw = view.size(rel), view.read_bytes(rel)
    if raw is None or size is None or len(raw) != size:
        return None
    return _count_lines(raw.decode("utf-8", "replace"))


def _restored_text_message(sess, messages: list[dict]) -> tuple[dict | None, dict]:
    """``(message, offered)`` — the coder-frame message carrying the CURRENT text of the files this session
    read or wrote whose text is no longer in ``messages``, and ``{rel: sha1}`` of what it carries; or
    ``(None, {})``.

    THE GAP IT CLOSES. A harness compaction folds the history, and the ledger keeps only the knowledge
    that the coder LOOKED. Measured on phi4 / Java A4, A6, A7 (every captured coder call): 45 of 100
    edit_file/write_file calls named a file whose ledger line said "no read result for it is in this
    conversation" (A4 24/51, A6 17/29, A7 4/18) — so the old_string was a guess, or the file was rewritten
    whole from memory (A7 0022: compile error at Importer.java:25, no text of it in the prompt, edit
    anchored on an invented top of file). Every judge prompt of the same run carried the same file's full
    text from the same workspace view (`judge_files`).

    WHICH FILES — the session's own ledger (reads and landed writes), never a keyword or a task name —
    MINUS the ones whose whole text, or whose own whole write, is already in the outgoing messages.
    WHAT BYTES — the view's trusted current body (a survey, the coder's own write or a landed exact
    edit), never a model's account of the file. If the view holds none the demand is queued so the next
    harness-executed survey brings it (cria never opens the path itself, #23c) and nothing is claimed.

    TRUTHFUL UNDER STALENESS (#11b). A command that could have changed files has run since the view was
    last fed: the body may be behind the disk, so nothing is delivered and a fresh body is requested.

    REDUCIBLE, NOT PROTECTED. It is its OWN unprotected message (never part of the ⟦ctx:facts⟧ anchor, which
    the floor keeps whole): under window pressure the floor swaps it for a labelled stand-in naming the
    files BEFORE it shortens a tool result or drops a turn, and the irreducible-input measure that sizes the
    reply room does not count it (reviewed on real post-compaction bodies: reserve 1.7-2.3K fell to
    167-759 tokens while the block rode inside the anchor).

    SIZE. Each file is bounded by the whole-read limit (a file over it is NAMED, not clipped — any clip
    is an undetectable lie), and the block as a whole by one read's worth, most recently touched first, so
    a 16K window is never handed a corpus. What does not fit is named in the block, never dropped silently.

    CREDIT is not decided here. Whether the text REACHED the model is a fact about the wire body, settled
    after the floor (`modelview.settle_restored_text`) and read back in `_coder_turn`; `_coder_has_seen`
    counts only that."""
    definition = next(iter(assistruntime.current().bindings(contextrestoration.DEFINITION.policy.stage)), None)
    if definition is None:
        return None, {}
    def history():
        ledger, _events, key = _ledger_state(sess, messages)
        return contextrestoration.FileHistory(tuple(ledger), tuple(getattr(sess, "written_files", None) or ()),
            tuple(_extract_whole_reads(messages, _surveyed_view(sess))),
            tuple(path for _pos, _tid, path in _write_events_paths(messages)), key,
            getattr(sess, "file_touch", None) or {})
    result = definition.execute(contextrestoration.RestoreInput(lambda: _surveyed_view(sess), history))
    return result.message, result.offered


def _plan_off_tail(base: list[dict], restore: dict | None, facts: dict) -> list[dict]:
    """The plan-off coder view's end: the restored-text block, THEN the facts anchor (the anchor stays the
    last message — the active turn). The ledger names the block rather than a direction because plan-on
    puts them the other way round."""
    return base + ([restore] if restore is not None else []) + [facts]


def _completion_measurement_services(workspace_root: str) -> completionmeasure.MeasurementServices:
    """Shared tool/workspace facts, with workspace access deferred to the selected owner."""
    from . import shelltool
    return completionmeasure.MeasurementServices(
        frozenset(_WRITE_TOOLS), frozenset(writeproxy_names), frozenset(writeproxy._EDIT_NAMES),
        denial.unlanded_call_ids, shelltool.writes_something, writeproxy._command_of,
        _args_of, _path_of_args, lambda a, b: _same_workspace_path(a, b, workspace_root),
        lambda: wsview.current(workspace_root) if workspace_root else None)


def _write_events_paths(messages: list[dict]):
    """``(position, id, path)`` of every landed write in ``messages`` — whose whole text IS there."""
    for idx, tid, path, _n, _label in _write_events(messages):
        yield idx, tid, path


def _edit_events(messages: list[dict]):
    """``(position, id, path)`` of every edit that LANDED in ``messages``."""
    for idx, tid, path, _res in _edit_results(messages):
        yield idx, tid, path


def _edit_results(messages: list[dict]):
    """``(position, id, path, result text)`` of every edit that LANDED in ``messages``."""
    from . import denial as _den
    paired = set(_den.paired_results(messages))   # canonical call/result pairing: ambiguous results attribute nothing
    calls: dict = {}
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") in writeproxy._EDIT_NAMES and tc.get("id"):
                if path := _path_of_args(fn.get("arguments") or ""):
                    calls[tc["id"]] = path
        tid = m.get("tool_call_id") or m.get("call_id")
        if tid in calls and tid in paired:
            res = m.get("content") if m.get("content") is not None else m.get("output")
            if isinstance(res, str) and denial.landed(m):
                yield idx, tid, calls[tid], res


def _render_restored(view, rels: list[str], touch: dict) -> tuple[str, dict, list[str]]:
    """``(text, {rel: sha1 of the text carried}, [every rel the text speaks of])``. A file whose text cannot be
    carried — the view holds no body for it, or a command that may have changed files ran since, so the body
    may be behind the disk — is NAMED as not available (and its body asked for afresh), never left out: the
    block is how the coder learns it holds no copy and must read the file (phi4 A10)."""
    return contextrestoration.render(view, rels, touch)


# NO CAP on the read ledger. It was 20 names out of an ALPHABETICALLY sorted list, so which files
# vanished was arbitrary — a `z*.py` the coder read a moment ago always went first. The count that
# replaced them answers a different question than the ledger's own stated purpose: "the KNOWLEDGE
# THAT IT HAS ALREADY LOOKED" is per-file and is not recoverable from a number.
_READ_LEDGER_CAP = None


@dataclass(frozen=True)
class _ContextFacts:
    """Raw authority, never inferred from a reduced outgoing view."""
    ledger: tuple
    fetches: tuple
    mismatch: str
    written_paths: tuple[str, ...]
    touch: tuple
    key: Callable[[str], str]


def _capture_context_facts(sess, raw: list[dict]) -> _ContextFacts:
    ledger, _events, key = _ledger_state(sess, raw)
    fetches = _merge_fetches(dict(getattr(sess, "fetched_pages", None) or {}), _extract_fetches(raw))
    return _ContextFacts(
        tuple((path, tuple(value)) for path, value in ledger.items()),
        tuple((url, (*_fetch_facts(value), groundtruth.fetch_observed(value))) for url, value in fetches.items()),
        _route_mismatch_fact(fetches, raw, getattr(sess, "workspace_root", "") or ""),
        tuple(getattr(sess, "written_files", None) or ()),
        tuple((getattr(sess, "file_touch", None) or {}).items()), key)


def _render_context_facts(facts: _ContextFacts, *, visible_messages: list[dict],
                          visible_fetch_urls: set[str], restored_offered: dict,
                          workspace, location: bool = True) -> dict | None:
    """Render raw world facts against this outgoing view, without changing admission."""
    absent = []
    fetches = _format_fetches(dict(facts.fetches), "PAGES YOU HAVE ALREADY FETCHED",
                             visible=visible_fetch_urls, absent_out=absent, location=location)
    if facts.mismatch:
        fetches = f"{fetches}\n\n{facts.mismatch}"
    ledger = fetches
    if facts.ledger:
        labels = prompts.load_map("fetched_facts_sections")
        live = {facts.key(ev[3]) for ev in _file_events(visible_messages, facts.key) if ev[2] == "read"}
        lines = []
        for path, (nbytes, size) in sorted(facts.ledger):
            note = (labels["read_restored"] if path in restored_offered else
                    "" if path in live else labels["read_out_of_view"])
            lines.append(f"- {path} ({_dated_count(workspace, path, nbytes, size, labels)}){note}")
        ledger += "\n\n" + prompts.fill(labels["read_header"], files="\n".join(lines), more="")
    if not ledger.strip():
        return None
    tail = prompts.load_map("fetched_facts_sections")["anchor_tail_fetches"] if fetches.strip() else ""
    if tail and absent:
        tail += prompts.load_map("fetch_body_visibility")["anchor_tail_absent_scope"]
    return {"role": "user", "content": prompts.render(
        "fetched_facts_anchor", marker=selfcompact.FACTS_MARKER, ledger=ledger.strip("\n"), tail=tail)}


def _fetched_facts_anchor(sess, messages: list[dict] | None = None, restored: dict | None = None) -> dict | None:
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
    return _render_context_facts(_capture_context_facts(sess, messages or []),
        visible_messages=messages or [],
        visible_fetch_urls=webfetch.visible_urls(getattr(sess, "web_session", None)),
        restored_offered=restored or {}, workspace=_surveyed_view(sess))


# An anchor block is the DESIGNATED single copy of its content: folding it into a pointer at a later
# duplicate would move the content out of the protected head. Mirrors selfcompact._ANCHOR_MARKERS
# (a test asserts sync).
#
# THE DENIAL MARKER IS NOT HERE, and the comment used to claim it was — "plus the denial marker,
# whose repetition IS the signal" — describing a tuple that has never contained it. The code was
# right and the sentence was wrong: `fold_repeated_messages` is aggregate-lossless by design, "n
# pointers plus one full copy, so the coder can still SEE it happened n+1 times, which is itself
# signal when the repeat is a refusal it kept re-earning". Protecting refusals from the fold would
# ship the same 1,529-byte paragraph nine times instead (measured, 20260823T032555 prompt 0084:
# 11.6 KB of a 79.2 KB prompt) while telling the reader exactly as much.
_ANCHOR_MARKERS_FOR_DEDUP = modelview.ANCHOR_MARKERS_FOR_DEDUP


def _elide_ledger_copies(msgs: list[dict], sess, rlog=None) -> list[dict]:
    """ONE copy of the fetch ledger per outbound view. The ⟦ctx:facts⟧ anchor just injected is the
    owner; byte-identical copies elsewhere — the compaction summary's fetch-facts appendix (baked
    in by server._harden_compaction_reply, redundant every call the anchor also rides), and the
    identical field-shape lines inside the original fetched-page result — collapse to a one-line
    pointer. Measured on the maple full walk: the ~2.4KB field block rode up to 3× per prompt.
    Byte-exact, aggregate-lossless, identity when nothing matches (see cria/dedup.py)."""
    definition = next(iter(assistruntime.current().bindings(ledgercopies.DEFINITION.policy.stage)), None)
    if definition is None:
        return msgs
    return definition.execute(ledgercopies.LedgerCopyInput(msgs,
        lambda: _format_fetches(dict(getattr(sess, "fetched_pages", None) or {}),
                               "PAGES YOU HAVE ALREADY FETCHED", visible=set(), location=False), rlog)).messages


def _insert_after_system(msgs: list[dict], anchor: dict) -> list[dict]:
    """Place ``anchor`` right after the leading system/developer message(s) — in the protected head, so it
    is always visible to the model and never reads as the oldest droppable turn."""
    i = 0
    while i < len(msgs) and msgs[i].get("role") in ("system", "developer"):
        i += 1
    return msgs[:i] + [anchor] + msgs[i:]


def _fetch_ground_truth(messages: list[dict], sess=None,
                        header: str = "PAGES YOU HAVE ALREADY FETCHED",
                        absent_out: list | None = None, location: bool = True) -> str:
    """Deterministic FACTS about the web_fetches already made — final status per URL + any endpoint
    routes. Handed to the steer author so a weak reasoner can't echo the coder's hallucination that a
    fetch failed when it actually returned 200 (runG: the coder insisted api.handle.me/openapi.json gave
    a 400; it returned HTTP 200 with 33 endpoints incl. /handles/{handle}, and the steer PARROTED the
    400 — 40 wasted turns). Merges the session's DURABLE facts (kept past the window) with the current
    window, so the correction survives even after the result scrolls out; in-window status wins. ``header``
    re-frames the subject for a non-coder reader (the step critic).

    ``visible`` is computed from webfetch's OWN per-session visibility store — the exact-repeat gate's
    identity — so the ledger's "body is in this conversation above" claim can never diverge from what
    the gate itself would allow to be re-fetched (Candidate C31). ``absent_out`` and ``location`` are
    forwarded to :func:`_format_fetches` — ``location=False`` for a caller about to FREEZE this text
    into history a model cannot revise (see that function's docstring)."""
    latest = _merge_fetches(dict(getattr(sess, "fetched_pages", None) or {}), _extract_fetches(messages))
    visible = webfetch.visible_urls(getattr(sess, "web_session", None))
    out = _format_fetches(latest, header, visible=visible, absent_out=absent_out, location=location)
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
    if not root or not host:
        return False
    view = wsview.current(root)
    tree = view.walk(root, skip_names=execcheck._SKIP_DIRS)
    if tree is None:
        return False
    for dirpath, _dirnames, filenames in tree:
        for name in filenames:
            if not name.endswith((".py", ".js", ".mjs", ".ts", ".go", ".rs", ".rb", ".java", ".php",
                                  ".sh", ".json", ".toml", ".yaml", ".yml")):
                continue
            body = view.read(os.path.join(dirpath, name))
            if body is not None and host in body:
                return True
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
                 system1=None) -> str | None:
    owner = gs if gs is not None else GuardState()
    definition = assistruntime.current().stalled_work
    if definition is None:
        return None
    services = _stalled_author(owner, body, rlog, reasoner_chat, reasoner_role, workspace_root,
        condition=condition, outcome=outcome, truth_text=truth_text, step_text=step_text,
        system1=system1)
    if services is None:
        return None
    return stalledwork._author(services, _StalledWorkView(owner), stalledwork.Trigger(condition),
        truth_text, getattr(owner, 'gate_stall', 0), actions=definition.actions).text


def _ruminating_reply(text: str) -> bool:
    return _grounded_actions()._ruminating_reply(text)


def _steer_or_none(text: str) -> str | None:
    return _grounded_actions()._steer_or_none(text)


_AuthoredActionState = groundedaction._AuthoredActionState


_AuthoredAction = groundedaction._AuthoredAction


def _authored_action(text: str, rlog=None) -> _AuthoredAction:
    return _grounded_actions()._authored_action(text, rlog)

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
    return _grounded_actions()._steer_from_reasoning(comp, answer, ask, rlog)


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
    return _grounded_actions()._is_argument_blob(directive)


def _dedupe_doubled(text: str) -> str:
    return _grounded_actions()._dedupe_doubled(text)


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
    r"|^[ \t]*\w+(?:[.:]{1,2}\w+)*[?!]?\s*\([^)\n]*\)"   # a call at the head of a line
    r"|^[ \t]*\$?\s*[\w./-]+(?:\s+[\w./=-]+)*\s+--?[\w-]+"  # a command with a flag: `mvn -q test`
    r"|\b\w+(?:(?:\.|::)\w+)+[?!]?\s*\([^)\n]*\)",       # an inline CALL: `pkg.fn(a)`, `mod::fn(a)`
    re.M)
# …AND `::` IS NOT DECORATION EITHER. The head-of-line shape has accepted `[.:]{1,2}` since it was
# written; the INLINE one accepted only `.`, so `serde_json::to_string(&value)` sitting mid-sentence
# was invisible — and Rust, C++ and PHP write their calls that way. Measured on
# rust-toml-cli x nemotron-elastic 1787257904: the reasoner authored a directive ending in `;`, the
# guard answered DICTATES, cria's own restater returned the SAME two code lines with " must be true."
# appended, and that four-word suffix moved the `;` off end-of-line. The line-end shape stopped
# matching, the inline shape could not see `::`, and `_dictates_code` then returned False WITHOUT
# MAKING A MODEL CALL — so the reasoned judge never ruled and the raw code shipped. cria's restater
# defeating cria's guard.
#
# …AND THE `[?!]` IS NOT DECORATION. Without it this pattern cannot see `ZONE_BASE.key?(x)`,
# `rec.save!(x)` or `println!("x")` — Ruby's predicate and bang methods, which are the ordinary way
# Ruby is written, and Rust's macros. A detector whose entire job is to be language-agnostic (#20)
# was blind to a whole language's most common call shape.
#
# What that cost, measured on `shipping-rates-rb x ternary-bonsai` 1787111689. cria's [REDIRECT]
# steer shipped two paste-ready lines:
#
#     # Instead of: zone = zone_or_code.is_a?(String) && … ? zone_for(zone_or_code) : zone_or_code
#     # Use this:   zone = ZONE_BASE.key?(zone_or_code) ? zone_or_code : zone_for(zone_or_code)
#
# `_dictates_code` returned False, so `_invented_code_spans` never ran and no
# `loop.steer_dictated_code` event was emitted — the guard was silent because it could not see. The
# model adopted the line verbatim and `test_unknown_zone_rejected`, a REPO test that had been green,
# went red and stayed red: `"moon"` is not a ZONE_BASE key, so it falls through to `zone_for` and
# returns `"international"` instead of raising. One of the run's three final failures.

# THE SENTINEL THE MATCHER ACTUALLY COMPARES AGAINST. The named constant used to be "DICTATES",
# the answer the code never tests for — it fails CLOSED, so anything that is not DESCRIBES stands.
# A constant for the unused half is a drift guard pointing away from the drift: if the prompt's
# wording moved, `DESCRIBES` is the word that would silently stop matching and every steer would be
# delivered. The name is on that one now, and a test ties it to the prompt file.
_DESCRIBES = "DESCRIBES"
# The OTHER legal answer. Not used to decide anything — the verdict falls closed on anything that is
# not DESCRIBES — but naming it is what lets the code tell "the judge ruled" from "the judge said
# something that is not an answer", which are different events and used to look identical.
_DICTATES = "DICTATES"

# A line worth checking for provenance: a code line or a command line. Short fragments and ordinary
# prose are left alone — the question is only ever about a line the coder could paste.
_QUOTABLE_MIN = 12

# How many independently-command lines make a post-compaction re-orientation a SCRIPT rather than a
# directive. Two is a sentence that names a command and then names another; three is a listing.
# Measured over the 59 captured re-orientation notes: at three, exactly the two script-dumps fire.
_REANCHOR_MAX_COMMAND_LINES = 3
_INVENTED_MARK = ("[code removed — written by this supervisor, not read from your files or your "
                  "checker output; make the change in your own code]")
# The two shapes, checked differently: a line that IS code, and a call embedded in prose.
# THE LANGUAGE HALF ONLY. The shell half of this pattern used to live here as a second, weaker
# alternation (`$ `, `sudo `, `pip install`, `sed -i`, `cat `, `grep -n`, `python -m`, `pytest`) and
# it missed the shape that cost a run: `cat > REVIEW.md << 'EOF'` matched none of it, so
# `_strip_invented_code` scored zero, so the restate path never fired and the command shipped
# (feed-pipeline-java x qwen35, 2026-08-19, call 0270). `cria.shellshape` owns that question now, for
# every caller — see its module docstring for why it is a score rather than a predicate.
_CODE_LINE = re.compile(
    r"^[ \t]*(?:def |class |import |from [.\w]+ import |return |with |@patch|assert )", re.M)


def _is_code_line(line: str) -> bool:
    return _grounded_actions()._is_code_line(line)
# EMPTY PARENS ARE A NAME, NOT CODE. `Importer.load()` hands the coder nothing to paste — it says
# WHERE, the way a file path does, and a directive is entitled to name the method it is talking
# about. The argument text is the part that can be invented, so the pattern now requires some.
#
# Walked on the sub-40 pass, feed-pipeline-java x nemotron-elastic (scored 16). The reasoner wrote
# the run's correct fix — delete the five `builder.set…` lines that do not exist on the CSV builder —
# and `_invented_code_spans` counted 2, so the directive was refused. The 2 were `Importer.load()`
# and a `builder.setEscapeCharacter` call whose escape was one character off from the line that IS on
# disk. Either one alone would have shipped it. Whether the NAME exists is a different guard's
# question
# (`_symbol_not_in_the_file`), and that one reads the file.
# …AND THE DOT WAS NEVER THE THING THAT MADE IT CODE. The pattern required a DOTTED name, so a bare
# constructor call carried no dot and was invisible: cria's own reasoner wrote
# `new CSVParser(new StringReader(line), ',', '\\'', true, true, true, null, null)` at
# feed-pipeline-java x nemotron-elastic 0019 and again at 0060, `_invented_code_spans` scored 0, and
# the directive shipped as dictated code with cria's authority behind it. The real constructor —
# named by javac IN THAT SAME PROMPT — takes eight arguments, all chars first, and no Reader at all.
# The coder adopted the shape and the run died on it (36 compile errors; repairing everything else
# still leaves 28). Java, C++, Rust tuple structs and every `new Thing(...)` write calls that way.
#
# The ARGUMENTS are what can be invented, so that is the whole test: a name, and parens with
# something in them. `_QUOTABLE_MIN` now bounds this branch as it already bounds the line branch,
# which is the same "empty parens are a name" rule stated by length instead of by emptiness —
# `m.group(1)`, `sys.exit(0)`, `O(n)` hand the coder nothing to paste. Measured over the captures:
# dropping the dot finds 134,084 more spans, 99.8% of them real code; the floor costs 0.8% of
# today's dotted hits, all of them names with a trivial argument.
_INLINE_CALL = re.compile(r"\b\w+(?:\.\w+)*\(\s*[^)\n\s][^)\n]*\)")


def _unquoted(s: str) -> str:
    return _grounded_actions()._unquoted(s)


_QUOTE_CHARS = {ord(c): None for c in "'\"`\\"}


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
        if len(body) >= _QUOTABLE_MIN and _is_code_line(line) and not seen(body):
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


def _invented_code_spans(directive: str, evidence: str) -> int:
    return _grounded_actions()._invented_code_spans(directive, evidence)


def _dictates_code(directive: str, ask=None, rlog=None, system1=None) -> bool:
    return _grounded_actions(system1)._dictates_code(directive, ask, rlog)


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
# A VERSION IS NOT A NAME. `v1.0.0`, `2.11.0`, `v1.4.0` all carry dots, so the dotted-name test
# accepted them — and a directive that says "replace v1.0.0 with v1.4.0" then shares a "symbol" with
# a `go.mod` line that names the same version, and is refused as prescribing. The shape is exact:
# every segment after the first is digits.
_VERSIONISH = re.compile(r"^v?\d+(?:\.\d+)+$")


def _looks_like_a_symbol(tok: str) -> bool:
    if _VERSIONISH.fullmatch(tok):
        return False
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
        # A PATH IS NOT A SYMBOL, AND NEITHER ARE ITS SEGMENTS. `/` was outside the character class,
        # so `github.com/shopspring/decimal` arrived as three separate runs and `github.com` — which
        # has a dot, so `_looks_like_a_symbol` accepts it — became a shared "symbol". Three of the
        # eleven post-fix judgements were on a bare domain, and the directives they killed were
        # "Run go mod tidy…", "Replace the line github.com/shopspring/decimal v1.0.0 with require…"
        # and "Add the OpenCSV dependency to pom.xml now". The same shape swallowed cria's own run
        # directory: `…/suite-shipping-rates-rb_ternary-bonsai_codex_poff_1787480733-abc/src/main.rs`
        # gave up `bonsai_codex_poff_1787480733` as a symbol, four more times.
        #
        # Reading the slash is the whole fix: a run that contains one is a path or a module
        # coordinate, and neither it nor its parts is a name a checker is rejecting.
        for run in re.findall(r"[A-Za-z_][A-Za-z0-9_.:?!/\\-]*", t or ""):
            if "/" in run or "\\" in run:
                continue
            out.add(run.strip(".:-"))
            out.update(p for p in re.split(r"[.:]+", run) if _IDENTLIKE.fullmatch(p))
        return {x for x in out if len(x) > 3 and _looks_like_a_symbol(x)}
    shared = toks(directive) & toks(findings) - _positional_only(findings)
    shared = {t for t in shared if not _NAMES_A_FAILURE.fullmatch(t)}
    return sorted(shared, key=len, reverse=True)


# AN EXCEPTION CLASS IS WHAT A CHECKER REPORTS, NEVER WHAT IT REJECTS. `LoadError`, `AttributeError`,
# `CsvValidationException` — a directive naming one is quoting the failure, which is the case this
# guard exists to distinguish and kept getting backwards. Two of the guard's eighteen historical
# fires are exactly this, and both killed a correct directive.
# `\w` DOES NOT MATCH A NAMESPACE SEPARATOR, so `LoadError` was filtered and `Gem::LoadError` was
# not — five captured calls asked the judge whether a directive was prescribing Ruby's exception
# class. The test is on the LAST segment, which is where the class name lives in every language that
# has namespaces.
_NAMES_A_FAILURE = re.compile(r"(?:\w+(?:::|\.))*\w*(?:Error|Exception|Failure|Warning)$")


# WHERE the checker is pointing, as opposed to WHAT it is rejecting.
_POSITIONAL = (
    re.compile(r"^\s*-->\s*(\S+)", re.M),                          # rustc/cargo's span line
    # NOT ANCHORED AT COLUMN ZERO. `proberun` renders every finding as `$ <command> — <path>:<line>:
    # <message>`, so the path never starts the line and NOTHING was ever classified positional —
    # measured across all eleven post-fix judgements. The anchor is a word boundary instead.
    re.compile(r"(?:^|[\s(\[`'\"])([\w./\\-]+\.\w{1,5}):\d+", re.M),    # file:line: anywhere
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


def _provider_rejected_name_the_steer_relies_on(
        directive: str, findings: str, rlog, ask) -> str:
    """A shared name whose external provider rejects it and the directive still relies on.

    This is deliberately TWO focused judgments.  Asking a weak classifier whether a whole mixed
    directive is safe made a valid source import and a nonexistent provider member look identical.
    First classify only the checker's LOCATION/SCOPE for one concrete name; only when the provider
    rejects it ask whether the directive uses that name or merely quotes/removes it.  Deterministic
    code still only gathers shared names; neither lexical shape decides the answer (#8).
    """
    if not directive or not findings or ask is None:
        return ""
    for symbol in _shared_symbols(directive, findings):
        status = strip_think(ask(prompts.render(
            "steer_symbol_status", findings=findings, symbol=symbol)) or "").strip()
        status = status.upper().split()[0].strip(".,:;`*\"'") if status.split() else ""
        if status != "PROVIDER_REJECTS":
            continue
        relation = strip_think(ask(prompts.render(
            "steer_prescribes_broken", findings=findings, directive=directive,
            symbol=symbol)) or "").strip()
        relation = relation.upper().split()[0].strip(".,:;`*\"'") if relation.split() else ""
        if relation == "PRESCRIBES":
            if rlog is not None:
                rlog.emit("loop.steer_relies_on_rejected_provider", level="warn",
                          symbol=symbol, head=_clip(directive, 120))
            return symbol
    return ""


def _diagnostic_action_verdict(directive: str, findings: str, refused, rlog, ask, grounding: str='', ask_with_evidence=None) -> str:
    return _grounded_actions()._diagnostic_action_verdict(directive, findings, refused, rlog, ask, grounding, ask_with_evidence)


def _prescribes_a_refused_coordinate(directive: str, refused, rlog, ask) -> str:
    """A dependency coordinate/package the directive tells the coder to ADD/USE while the session's
    own toolchain has REFUSED it — else "".

    The durable sibling of the current-diagnostic compatibility checks. `_shared_symbols` drops any
    token with a `/` ("a path is not a symbol"), so a module coordinate is invisible to the provider
    check, and current findings can disappear at compaction. The ledger (`sess.refused_names`) is durable, so
    the refusal survives the fold that let a seat re-bless `v0.5.0` after the tools rejected it.

    Same #8 split as the symbol guard: `refusalledger.prescribed` is the deterministic TRIGGER (the
    directive names a remembered-refused coordinate), and ONE focused reasoner question — the SAME
    `steer_prescribes_broken` prompt, whose QUOTES branch already covers "remove it" and "supply the
    missing thing" — rules PRESCRIBES vs QUOTES. With no reasoner or an unreadable answer the
    directive STANDS (#4: no deterministic fallback behind an absent reasoner), so this can only move
    a steer from delivered to withheld when a model says the steer tells the coder to USE a
    coordinate that did not resolve."""
    if ask is None:
        return ""
    coord = refusalledger.prescribed(directive, refused)
    if not coord:
        return ""
    question = prompts.render("steer_prescribes_broken",
                              findings=prompts.render("steer_prescribes_refusal_finding",
                                                      coordinate=coord),
                              directive=directive, symbol=coord)
    # Compatibility: this helper historically documented a one-argument closed ask while its unit
    # tests supplied a two-required-argument callback. Inspect the callable instead of catching a
    # TypeError from inside it; the refusal-only production adapter takes exactly one argument.
    try:
        signature = inspect.signature(ask)
    except (TypeError, ValueError):
        # Some extension callables expose no signature. Production's closed adapter accepts one
        # argument, so that remains the conservative default when introspection is unavailable.
        one_argument = True
    else:
        try:
            signature.bind(question)
        except TypeError:
            one_argument = False
        else:
            one_argument = True
    # Keep the call outside the signature probe: a TypeError raised *inside* the provider must not
    # be mistaken for evidence that the callback wants the historical two-argument shape.
    answer = ask(question) if one_argument else ask(question, "")
    ans = strip_think(answer or "").strip()
    head = ans.upper().split()[0].strip(".,:;`*") if ans.split() else ""
    if head == "PRESCRIBES":
        rlog.emit("loop.steer_prescribes_refused", level="warn", coordinate=coord,
                  head=_clip(directive, 120))
        return coord
    return ""


def _blames_a_service_that_answered(directive: str, sess, messages: list, rlog, ask) -> bool:
    return _grounded_actions()._blames_a_service_that_answered(directive, sess, messages, rlog, ask)


def _fetch_succeeded_anywhere(sess, messages: list) -> bool:
    """Did ANY fetch this session come back 2xx? The disproof this check stands on."""
    merged = _merge_fetches(_extract_fetches(messages), (getattr(sess, "fetched_pages", None) or {}))
    return any(research.fetch_answered(e) for e in merged.values())


# Absolute paths under SYSTEM roots — the shapes a steer can only be inventing when nothing at that
# path exists. /tmp is deliberately absent (workspaces and spill files legitimately live there), and
# a workspace-internal path is a legitimate create-target, so neither is ever checked by this.
_ABS_SYSTEM_PATH = re.compile(r"(?<![\w./-])(/(?:home|root|usr|etc|opt|srv|var)/[\w./-]{3,})")


def _phantom_system_path(directive: str, workspace_root: str | None) -> str:
    return _grounded_actions()._phantom_system_path(directive, workspace_root)


def _grounded_steer_or_none(directive: str | None, evidence: str, rlog, ask=None,
                            sess=None, messages=None, workspace_root=None, system1=None) -> str | None:
    definition = assistruntime.current().stalled_work
    if definition is None:
        return directive
    return _grounded_actions(system1)._grounded_steer_or_none(directive, evidence, rlog,
        ask, sess, messages, workspace_root, vet=definition.actions.vet)


def _vet_steer(directive: str | None, evidence: str, rlog, ask=None,
               sess=None, messages=None, workspace_root=None, system1=None) -> tuple[str | None, str]:
    definition = assistruntime.current().stalled_work
    if definition is None:
        return directive, ''
    result = definition.actions.vet(_grounded_actions(system1), groundedaction.CandidateInput(
        directive, evidence, rlog, ask, sess, messages, workspace_root))
    if not isinstance(result, groundedaction.CandidateResult):
        raise TypeError('Stalled action vet must return CandidateResult')
    return result.directive, result.refused_by


_AUTH_MARKER = re.compile(r"\b40[13]\b|\bunauthori[sz]ed\b|\bforbidden\b", re.I)


# The shape a steer takes when it asserts an authentication requirement. It lived in cria.research
# while the authored-step channel shared it; that channel was removed on 2026-08-19 and this is the
# only reader left, so it lives where it is read (#23, one owner). It is a TRIGGER for spending one
# reasoner call, never a verdict — see the function.
AUTH_SHAPE = re.compile(r"(?i)\b(?:authenticated|authentication|auth token|api[- ]?key|bearer token)\b")


def _steer_auth_refuted(directive: str, evidence: str, sess, ask, rlog) -> bool:
    if not isinstance(sess, groundedaction.ActionEvidence):
        task = getattr(sess, 'original_task', None)
        if task is None:
            task = getattr(getattr(sess, 'plan', None), 'task', '') or ''
        pages = getattr(sess, 'fetched_pages', None)
        sess = groundedaction.ActionEvidence(original_task=task,
            fetched_pages={} if pages is None else pages)
    return _grounded_actions()._steer_auth_refuted(directive, evidence, sess, ask, rlog)


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


# The symbol must be MARKED AS CODE — backticked, or written as a call. "the change in app.py" is
# ordinary prose and must never trip this, because the guard DROPS the steer: a false positive costs
# a legitimate directive, which is the expensive direction.
_SYMBOL_IN_FILE = re.compile(
    r"(?:`([A-Za-z_]\w{2,})`|\b([A-Za-z_]\w{2,})\(\))"
    r"\s+(?:in|from|of|inside)\s+`?([\w./-]+\.\w{1,5})`?")


def _symbol_not_in_the_file(directive: str, workspace_root: str | None) -> str | None:
    return _grounded_actions()._symbol_not_in_the_file(directive, workspace_root)


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
    return _grounded_actions()._invented_version(directive, evidence)


# A TOOL'S OWN SYNOPSIS IS NOT EVIDENCE ABOUT THIS REPO. Every command-line tool answers a malformed
# argument by printing the SHAPE of a well-formed one, and the placeholder it prints is version-
# shaped:
#
#     go.mod:4:5: usage: require module/path v1.2.3
#
# `v1.2.3` is go's stand-in for "a version goes here", exactly as `module/path` stands in for the
# module. It is not a version anything publishes.
_SYNOPSIS_LINE = re.compile(r"(?i)(?<![\w-])(?:usage|synopsis)\s*:")


def _grounds_a_version(tok: str, evidence: str) -> bool:
    return _grounded_actions()._grounds_a_version(tok, evidence)


def _resolve_cited(root: str, rel: str) -> str | None:
    """The workspace file a steer means by ``rel``, or None when cria cannot say which.

    A steer cites the file the way a person says it — `test_client.py` for `tests/test_client.py` —
    so the name has to be resolved before it can be checked. EXACTLY ONE match or nothing: two files
    with that basename means cria does not know which was meant, and the old code answered anyway by
    keying a dict on the basename, where the last one silently overwrote the first."""
    view = wsview.current(root)
    if view.isfile(Path(root) / rel) is True:
        return rel
    walked = view.walk(root, skip_names=(".git",), skip_hidden=True)
    if walked is None:
        return None
    want = os.path.basename(rel)
    hits = [os.path.relpath(os.path.join(d, n), root)
            for d, _subdirs, names in walked for n in names if n == want]
    return hits[0] if len(hits) == 1 else None


def _lines_in(root: str | None, rel: str) -> int | None:
    """How many lines are really in the file a steer calls ``rel``, or None when cria cannot say."""
    if not root or not rel:
        return None
    found = _resolve_cited(root, rel)
    if found is None:
        return None
    body = wsview.current(root).read(Path(root) / found)
    if body is None:
        return None
    raw = body.encode("utf-8", "replace")
    return raw.count(b"\n") + (0 if raw.endswith(b"\n") or not raw else 1)


def _false_line_citation(directive: str, workspace_root: str | None, touched: list[str] | None=None) -> str | None:
    return _grounded_actions()._false_line_citation(directive, workspace_root, touched)


# A field the steer tells the coder to read off an API response: `data.get("x")`, `data["x"]`, and
# the same on the handful of names a response is conventionally bound to. Narrow ON PURPOSE — a bare
# backtick is not enough, because a steer legitimately quotes local variables, dict keys the coder
# invented, and column names. The access shape is what marks it as a claim ABOUT THE RESPONSE.
_RESP_VAR = r"(?:data|response|resp|json|payload|body|result|res|r)"
_FIELD_ACCESS = re.compile(rf"\b{_RESP_VAR}\s*(?:\.get\(\s*['\"]([A-Za-z_]\w*)['\"]|\[\s*['\"]([A-Za-z_]\w*)['\"]\s*\])")
def _ledger_field_names(ledger: dict) -> set[str]:
    """Every field name cria actually PARSED out of a fetched response shape — "" when it parsed none.

    Nested names count (`resolved_addresses{ada(…)}` yields both), because a steer naming the inner
    one is telling the truth. They are the entries' own typed `fields` (read from the parsed schema / introspection
    structure by the producer): no rendered shape text is scanned here. Routes and catalogs are paths, not fields."""
    return {name for entry in (ledger or {}).values() for shape in _fetch_facts(entry)[2] for name in shape.fields}


def _field_the_ledger_denies(directive: str, ledger: dict) -> str | None:
    return _grounded_actions()._field_the_ledger_denies(directive, ledger)


def author_redirect(reasoner_chat, reasoner_role, workspace_root, step_text: str,
                    gs: GuardState, outcome, body: dict, rlog, system1=None) -> str:
    return author_steer(reasoner_chat, reasoner_role, workspace_root, gs, body, rlog,
        condition='refusal', outcome=outcome, step_text=step_text,
        system1=system1) or guard_canned_redirect(gs, outcome)


def author_thrash_steer(reasoner_chat, reasoner_role, workspace_root, gs, truth: str,
                        body: dict, rlog, system1=None) -> str:
    return author_steer(reasoner_chat, reasoner_role, workspace_root, gs, body, rlog,
        condition='thrash', truth_text=truth, system1=system1) or truth


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
    if not workspace_root:
        return ""     # never read against cria's OWN cwd, whatever the path claimed
    # The view answers only inside the workspace, which IS the "never read outside" bound.
    return wsview.current(workspace_root).read(Path(workspace_root) / rel.lstrip("./")) or ""


def guard_search_query(sess: GuardState, coder: dict, body: dict,
                       reasoner_chat, reasoner_role, rlog, *, _defer: bool = False) -> dict:
    """Bind selected Source questions to live state and required raw research facts.

    Production stages in place and leaves settlement to public drive retention.
    Standalone compatibility callers retain this local return immediately.
    """
    runtime = assistruntime.current()
    selected = semanticquery.Selection(runtime.rehunt)
    messages = body.get("messages", [])
    source = semanticquery.TurnInput(coder, sess.web_session,
        lambda: semanticquery.QuestionFacts(latest_user_text(messages), _coder_tools_summary(body.get("tools"))),
        semanticquery.Judge(summarize, reasoner_chat, reasoner_role, rlog))
    result = semanticquery.prepare_turn(source, sess, selected)
    if not _defer:
        semanticquery.settle_turn(sess, result)  # standalone caller retains this exact local return
    return result


# Explicit sentinel for a path that genuinely has NO reasoner: it must pass author=CANNED, not omit the
# arg. `author` is REQUIRED (below) so a path can never silently select the degraded canned redirect by
# omission — the failure class the parity audit caught (a shared guard with an optional-degraded default).
CANNED = object()


def guard_probe_steer(gs: GuardState, body: dict, rlog, *, author, step=None) -> str | None:
    definition = _stalled_selection(gs)
    ticket = gs.stalled_probe
    if definition is None or ticket is None:
        return None
    cid = gs.probe_call_id  # owned current launch/reissue/page, never the mutable ticket alias
    if not cid or not any(m.get('role') == 'tool' and (m.get('tool_call_id') or m.get('call_id')) == cid
               for m in body.get('messages', []) if isinstance(m, dict)):
        return None
    raw = _read_tool_result(body.get('messages', []), cid)
    outcome = read_gate(gs.gate_plan, raw, rlog)
    if getattr(outcome, 'transport_pending', False):
        return None
    recorded = False
    def record_reading():
        nonlocal recorded
        if not recorded:
            record_gate_state(gs, outcome, gate_error_text(outcome), None, body.get('messages'))
            recorded = True
    record_reading()  # mandatory facts precede optional policy and its evidence snapshot
    services = (None if author is CANNED else
                author(ticket.trigger.value, gs, outcome, body, rlog))
    if services is not None and not isinstance(services, stalledwork.AuthorServices):
        raise TypeError('Stalled author adapter must return AuthorServices')
    result = _stalled_result(definition.settle(stalledwork.ReturnedProbeInput(ticket,
        record_reading, lambda: guard_ground_truth(outcome), services, rlog, step), _StalledWorkView(gs)))
    if result.steer is None:
        return None
    gs.steer_source = result.steer.source
    return _stalled_text(result.steer)


_CHECK_FILE_LINE = re.compile(r"(?P<path>[^\s:]+\.[A-Za-z0-9_]+):(?P<line>\d+)(?::\d+)?:")


def _same_workspace_file(a: str, b: str, root: str) -> bool:
    """Do two spellings (absolute / workspace-relative) name one path? Compared as paths, never as substrings."""
    if not a or not b:
        return False
    if root:
        a, b = os.path.join(root, a), os.path.join(root, b)
    return os.path.normpath(a) == os.path.normpath(b)


def grounded_rumination_step(gs, messages: list[dict]) -> str:
    """Compatibility projection of source-owned guidance from existing facts."""
    from . import generationguards
    return generationguards.grounded_next_step(messages, _generation_grounding_services(gs, messages))


_ANY_PATH = object()   # a mutation whose targets cannot be fully determined: any file may have changed

_PATCH_ALL_TARGETS_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M)


def _mutation_targets(fn: dict, workspace_root: str | None = None):
    """Every file one call may have changed: a list of paths ([] for a non-write call), or ``_ANY_PATH``
    when the call is a write whose targets cannot be fully determined. Authoritative for the later-write
    test, unlike `_write_path` (one file, a streak-grouping key): a patch names every Add/Update/Delete
    header and Move-to, and a shell command the classifier flags as writing is resolved only when every
    redirect/`tee` target is read from it AND it holds no other mutator — otherwise it is unknown."""
    name = fn.get("name")
    lowered = writeproxy._command_of(fn.get("arguments") or "")
    original = writeproxy.original_call(lowered)
    if original is not None:
        fn, name = original, original.get("name")
    elif writeproxy.is_crias_own(lowered):
        return []
    args = fn.get("arguments") or ""
    if _is_write_tool(name):
        out = []
        if name == "apply_patch":
            try:
                obj = json.loads(args) if isinstance(args, str) else dict(args or {})
            except (json.JSONDecodeError, TypeError, ValueError):
                obj = None
            blob = (obj.get("input") or obj.get("patch") or "") if isinstance(obj, dict) else args
            blob = blob if isinstance(blob, str) else ""
            if not isinstance(obj, dict):
                blob = blob.replace("\\n", "\n")
            out = [(a or b).strip().strip('"') for a, b in _PATCH_ALL_TARGETS_RE.findall(blob)]
        keyed = _path_of_args(args, patch_ok=False)
        if keyed:
            out.append(keyed)
        return out or _ANY_PATH
    if is_shell_tool_name(name):
        text = _command_text(args)
        if text is None:
            return _ANY_PATH   # an undecodable fragment: nothing can be said about its targets
        # No write-target parsing: the call is proven read-only by dirguard's positive allow-list
        # (with no output redirect/tee at all), or ANY file may have changed.
        return [] if dirguard.command_only_reads(text, workspace_root, no_writes=True) else _ANY_PATH
    return []


def _write_paths_after(messages: list[dict], idx: int, workspace_root: str | None = None,
                       skip: frozenset | set = frozenset()):
    """Paths of every write-class call (landed or not) after position ``idx`` — every target of a
    multi-file patch — or ``_ANY_PATH`` for a write whose targets are not fully known. ``skip`` names
    call ids whose result says the call never changed anything (`_unlanded_call_ids`): they are not
    mutations. A call with no result yet is never in it, so it still counts."""
    for m in (messages or [])[idx + 1:]:
        if isinstance(m, dict) and m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                if tc.get("id") in skip:
                    continue
                got = _mutation_targets(tc.get("function") or {}, workspace_root)
                if got is _ANY_PATH:
                    yield _ANY_PATH
                else:
                    yield from got


@dataclass(frozen=True)
class _ObservedCoderRetries(generationguards.RetryServices):
    on_completion: Callable[[dict], None] | None = None

    def retry(self, body, tools):
        completion = super().retry(body, tools)
        if self.on_completion is not None:
            self.on_completion(completion)
        return completion


def _dated_guidance(sess, notes) -> list[str]:
    """Each carried note, prefixed with how many of the coder's own calls have run since its latest
    delivery. The note's words are untouched; the age is what places "the CURRENT state of the repo"
    against the coder's newer results (run04 0065/0097). Unknown or zero age: the note alone."""
    delivered = getattr(sess, 'guidance_delivered_seq', None) or {}
    now = getattr(sess, 'action_seq', 0)
    aged = prompts.load_map('guidance_history_age')['aged']
    out = []
    for note in notes:
        since = now - delivered[note] if note in delivered else 0
        out.append(prompts.fill(aged, calls=since) + '\n' + note if since > 0 else note)
    return out


class _CoderReplyReceipts:
    """Call-local facts linking actual normalized coder replies to final wire reads."""
    def __init__(self, chat, session=None):
        self._chat = chat
        self._session = session
        self.latest = {}
        self.latest_remediation = ""
        self._replies = []

    def chat(self, body, rlog):
        self.latest = {}
        self.latest_remediation = ""
        rlog.restored_on_wire = {}
        subject = body.get(bodykeys.COMPLETION_REMEDIATION, "")
        rlog.guidance_on_wire = []
        raw = self._chat(body, rlog)
        if self._session is not None:
            for note in getattr(rlog, 'guidance_on_wire', ()):
                if note not in self._session.guidance_history:
                    self._session.guidance_history.append(note)
                # Dated at THIS delivery: the forwarded-call counter before this reply's calls.
                self._session.guidance_delivered_seq[note] = getattr(self._session, 'action_seq', 0)
        self.latest = dict(getattr(rlog, "restored_on_wire", None) or {})
        self.latest_remediation = subject
        return raw

    def record(self, completion, receipt=None, *, remediation=None):
        self._replies.append((completion, dict(self.latest if receipt is None else receipt),
                              self.latest_remediation if remediation is None else remediation))

    def receipt(self, completion):
        return next((dict(receipt) for reply, receipt, _ in reversed(self._replies)
                     if reply is completion), {})

    def remediation_receipt(self, completion):
        return next((subject for reply, _, subject in reversed(self._replies)
                     if reply is completion), "")


def _generation_cut_services():
    from . import generationguards
    return generationguards.CutServices(frozenset(_WRITE_TOOLS), frozenset(writeproxy_names), _path_of_args)


def _generation_grounding_services(gs, messages, accepted=None):
    """``messages`` is what the coder SEES (what a read is evidence of); ``accepted`` is the canonical accepted body
    from before focus/trim reshaped it — the one a "did anything change since that read" scan must use, because a
    reshaped copy can have dropped the very call that mutated the file."""
    from . import generationguards
    if gs is None:
        return None
    root = getattr(gs, "workspace_root", None) or _extract_cwd(messages) or ""
    def lines():
        for raw in (getattr(gs, "last_gate_flag", "") or "").splitlines():
            match = _CHECK_FILE_LINE.search(raw)
            if match is not None:
                yield raw, match.group("path"), int(match.group("line"))
    return generationguards.GroundedNoticeServices(
        gate_unedited=lambda: gate_unedited(gs), gate_lines=lines,
        reads=lambda msgs: [generationguards.ReadResult(i, path, start, end, text)
                           for i, _tid, path, start, end, text in _read_results_ordered(msgs)],
        read_span=_read_span,
        same_file=lambda left, right: _same_workspace_file(left, right, root),
        mutated_after=lambda msgs, position, path: _mutated_after_read(
            msgs, position, path, root, msgs if accepted is None else accepted))


def _mutated_after_read(seen, position, path, root, history) -> bool:
    """Could ``path`` have changed since the read at ``seen[position]``? Scanned over ``history`` (the accepted body
    when there is one), from where THAT read's call result sits in it. A read that cannot be located there is
    unknown, which is "may have changed"."""
    if history is not seen:
        tid = (seen[position] or {}).get("tool_call_id") or (seen[position] or {}).get("call_id")
        position = next((i for i, m in enumerate(history) if isinstance(m, dict) and m.get("role") == "tool"
                         and (m.get("tool_call_id") or m.get("call_id")) == tid), None)
        if tid is None or position is None:
            return True
    return any(target is _ANY_PATH or _same_workspace_file(target, path, root)
               for target in _write_paths_after(history, position, root, _unlanded_call_ids(history)))


def _generation_recovery(coder, body, coder_chat, rlog, *, step=None, phase="coder",
                         coder_role=None, gs=None, selected=None, on_completion=None, accepted=None):
    from . import generationguards
    if selected is None:
        selected = generationguards.SelectedGuards.from_definitions(assistruntime.current().definitions)
    return selected.recover(
        generationguards.RecoveryInput(coder, body, step, phase),
        _ObservedCoderRetries(coder_chat, _parse_completion, _add_note, rlog, coder_role,
                              on_completion=on_completion),
        _generation_cut_services,
        lambda: _generation_grounding_services(gs, body.get("messages") or [], accepted))


def guard_rumination(coder: dict, body: dict, coder_chat, rlog, *, step=None, phase: str = "coder",
                     coder_role=None, gs=None) -> dict:
    """Public runaway-only compatibility; decisions belong to the selected source."""
    from . import generationguards
    selected = generationguards.SelectedGuards.from_definitions(assistruntime.current().definitions)
    return _generation_recovery(coder, body, coder_chat, rlog, step=step, phase=phase,
                                coder_role=coder_role, gs=gs,
                                selected=generationguards.SelectedGuards(selected.runaway, None)).completion


def _refusal_turn(body: dict, text: str) -> None:
    """Append a model-facing note to the OUTBOUND conversation so a dropped tool call is visible to the
    coder on its next turn. cria's ⟦cria⟧ notes are human indicators and are stripped before the model,
    so a refusal recorded only there leaves the coder with no result, no error, and no advice — it
    re-sends the same doomed call. Mutates ``body["messages"]`` in place; harmless if absent."""
    msgs = body.get("messages")
    if isinstance(msgs, list) and text:
        msgs.append({"role": "user", "content": text})


def guard_truncation(coder: dict, body: dict, coder_chat, rlog, *, step=None, phase: str = "coder") -> dict:
    """Public cut-only compatibility; recovery and refusal are source-owned."""
    from . import generationguards
    selected = generationguards.SelectedGuards.from_definitions(assistruntime.current().definitions)
    return _generation_recovery(coder, body, coder_chat, rlog, step=step, phase=phase,
                                selected=generationguards.SelectedGuards(None, selected.truncation)).completion


def _truncated_write_path(completion: dict) -> str | None:
    """Compatibility reader using the canonical cut policy's factual services."""
    return generationguards.truncated_write_path(completion, _generation_cut_services())


def _read_tool_result(messages: list[dict], call_id: str) -> str:
    """The harness's result for a tool call cria emitted (e.g. the ground-truth probe),
    found by its call id in the message stream."""
    for m in reversed(messages):
        if m.get("role") == "tool" and m.get("tool_call_id") == call_id:
            return str(m.get("content") or "")
    return ""


# Files whose on-disk facts are READ for the steer author's section. The list itself is not bounded:
# the bound belongs where the printing happens, with the sentence that says how many it left out
# (#R2) — a bare `[-8:]` here made the ninth-oldest file simply cease to exist for the reader.
# NO CAP: every file the coder touched reaches the steer author's disk facts. It was the newest
# 8, so the file a steer most needed to know about could be the one dropped.
TOUCHED_PATHS_CAP = None


def _touched_paths(messages, cap: int | None = None) -> list[str]:
    """Paths the coder actually WROTE this session, recovered from the normalized history's
    assistant tool_calls — the durable record. GuardState's recent_writes window is consumed by
    detector interventions (flushed on purpose), so it alone cannot ground the steer author's
    on-disk section. Newest-last, deduped; ``cap`` keeps only the newest N when a caller asks."""
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
    return seen[-cap:] if cap else seen


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
    # NEWEST FIRST OUT OF THE BOUND, and the bound is counted below. Bounding on the number of lines
    # PRODUCED would count wrong: a file the view knows nothing about contributes no line, so the
    # remainder must come from the paths, not from what could be read about them.
    shown, rest = paths, 0
    lines: list[str] = []
    view = wsview.current(root)
    for p in shown:
        full = groundtruth.resolve(root, p)
        body = view.read(full)
        if body is not None:
            raw = body.encode("utf-8", "replace")
            n_lines = raw.count(b"\n") + (0 if raw.endswith(b"\n") or not raw else 1)
            lines.append(f"FILE {p} — {len(raw):,} bytes, {n_lines:,} line{'s' if n_lines != 1 else ''}")
        elif view.isfile(full) is False:
            lines.append(f"FILE {p} — does NOT exist on disk")
        elif (size := view.size(full)) is not None:
            lines.append(f"FILE {p} — {size:,} bytes")
        # else: cria has not been told about it, and says nothing rather than guessing either way
    if lines and rest > 0:
        # Only ever as the TAIL of a real list. With no lines above it there is nothing for "and N
        # more" to be more THAN, and the caller's own no-files-touched branch is the true answer.
        # THE COUNT IS THE POINT. Reading every file the coder ever touched is what the cap is for,
        # but a list that stops without saying so reads as the whole truth, and the author then
        # reasons about a workspace with the older files deleted from it.
        lines.append(prompts.fill(prompts.load_map("disk_facts")["more"], count=rest))
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




def _flat_values(obj) -> list:
    """Leaf values of a parsed args object, in order — flattens nested lists/dicts (a shell
    call's {"command": ["bash", "-lc", "pytest -q"]} yields the actual words)."""
    if isinstance(obj, dict):
        return [v for val in obj.values() for v in _flat_values(val)]
    if isinstance(obj, list):
        return [v for val in obj for v in _flat_values(val)]
    return [obj]


_QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
# Raw-blob variant for UNPARSEABLE args (truncated JSON): quotes/newlines are still escaped
# there, so tolerate a leading backslash — and never quote-mask raw blobs (the JSON string
# delimiters would mask the entire command away).
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


# The self-compaction rollup's output cap. It was 2,048, added on 2026-07-28 for LATENCY — "at 7
# tok/s it is an 18-minute worst case, and a truncated pass then RETRIES, doubling it" — eleven days
# after the truncation overhaul had raised exactly these caps to 8,192 "so a summary is never itself
# truncated". Rule 6 answers it in as many words: do not shorten output for speed, slow hardware and
# long waits are acceptable, and runaway protection belongs to streaming detection and timeouts, not
# to a short hard cap.
#
# It failed safe rather than shipping half a summary — `summarize` refuses a `finish_reason=length`
# reply and the fold is abandoned — but the cost of that safety is that the floor then drops whole
# turns instead, which is the more expensive loss. 31% of rollups hit it.
ROLLUP_MAX_TOKENS = 8192

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
    return " ".join(", ".join(routes) for routes in (_fetch_facts(e)[1] for e in merged.values()) if routes)


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
    for line in session.splitlines(keepends=True):
        if any(mark in line for mark in own):
            content = line.splitlines()[0]
            ending = line[len(content):]
            out.append(f"{content}   [EARLIER NOTE FROM THIS SYSTEM — not evidence]{ending}")
        else:
            out.append(line)
    return "".join(out)


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
                   evidence: str = "", workspace_root: str | None = None, rlog=None,
                   messages: list | None = None, sess=None, task: str = "",
                   action_log: str = "", checks: str = "", participation_facts: str = "",
                   diagnosis_ask=None, phase: str = "negative-diagnosis",
                   original_task: str | None = None, system1=None) -> VerdictNudge:
    """Build the coder-facing value from a verdict.

    Every production caller supplies ``task``. Positive verdicts keep their completion reason;
    negative ones go through the single typed provenance owner. Missing outputs use an independently
    extracted literal root requirement as the action; generated-step callers pass original_task.
    The no-task arm remains only for older private unit-level callers of this helper; no completion
    path can reach it. ``system1`` is still carried to it by the one live caller that has an app
    context and a step text which could be empty (the step critic), so no live path can reach this
    arm and be answered by a different question than the one the service selected.
    """
    reason = str(obj.get("reason", "")).strip()
    fix = _fix_text(obj)
    if done:
        return VerdictNudge(reason)
    if task:
        return _negative_diagnosis_nudge(
            obj, task=task, original_task=original_task, action_log=action_log, checks=checks,
            participation_facts=participation_facts, workspace_root=workspace_root or "",
            ask=diagnosis_ask, rlog=rlog, phase=phase)
    # Compatibility for private callers that do not yet have task provenance. Production verdict
    # seats always pass ``task`` and therefore cannot enter this free-form path.
    if not fix:
        return VerdictNudge(reason)
    # A `METHOD /path` route is unambiguous — nothing writes "POST /x" about a file it is creating —
    # and a judge learns that spelling from cria's OWN shape ledger. Measured (run 0727-153326): the
    # critic proposed `POST /handles/resolve`, a route in no spec, 12 times; the coder grepped for
    # that literal string across 322 calls on one step.
    if routes and urlgrounding.ungrounded_routes(fix, routes):
        return VerdictNudge(reason)
    # THE SESSION AND THE CONVERSATION, because five of the twelve guards cannot run without them.
    # With `messages=None`, `_observed_code(None)` is "" and `_invented_code_spans` short-circuits on
    # "nothing to check against → nothing is invented" — so the dictated-code arm DELIVERED the fix
    # verbatim and logged `invented=0`, a number that reads as a verdict and was never a check.
    # Replayed against the live code with `messages=None`: `Change line 289 to: req += f"\r\n\r\n..."`
    # ships, `delivered=True invented=0`. Of 25 such log lines, 10 were immediately preceded by a
    # `satisfaction` upstream call — this seat, where the check could not have run.
    #
    # `sess` brings `_field_the_ledger_denies`, `_blames_a_service_that_answered`, the deterministic
    # grounding checks and `_steer_auth_refuted` with it. `ask` stays out, as the docstring says: the
    # reasoner-backed arms remain off here, so this still costs no model call. In particular, the
    # current-diagnostic compatibility guard abstains rather than deleting every proposed fix merely
    # because this caller deliberately has no classifier seat.
    accepted = (_grounded_steer_or_none(fix, evidence, rlog, sess=sess, messages=messages,
                                        workspace_root=workspace_root, system1=system1)
                if rlog is not None else fix)
    return VerdictNudge(reason, accepted or "")


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
    completion = generation.safe_completion(completion)
    choice = (completion.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    model = completion.get("model", "")
    cid = completion.get("id", "")
    created = completion.get("created", 0)

    def chunk(delta: dict, finish=None) -> bytes:
        payload = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                   "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        if generation.EVIDENCE in completion:
            payload[generation.EVIDENCE] = completion[generation.EVIDENCE]
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
