"""The completion gate: which of the project's own checks to run, how to read what they said, and what the model is shown of it.

The gate is CONGRUENT across ecosystems (operator direction): there is no privileged per-language floor. ``proberun.select_completion_probes``
returns one ranked candidate list - tier-0 parse/compile checks for every language present (compileall, node --check, php -l, ruby -c by
file presence; cargo check / go build / tsc / mvn-gradle compile / dotnet build / mix compile via their ecosystems' tier<=1 candidates) plus
the top-ranked probe and the top TEST probe. This module:

* :func:`plan_gate` - select the candidates (READ-ONLY workspace inspection) and compose the shell text that runs them
  (:mod:`cria.gatescript`). The plan REMEMBERS what it composed so interpretation does not re-inspect a possibly-changed world.
* :func:`adopt` - take the result of the gate's operation (:mod:`cria.gateops`: the harness ran the text, cria read every output back, one file
  per check) into the plan.
* :func:`interpret_gate` - map the adopted sections onto the upstream ProbeResult contract (:func:`cria.proberun.interpret_probe_output`):
  timeout -> 124, launch failure -> 127/"command not found", findings via the per-tool parsers (tier-0 checks included - every ecosystem's
  parse floor yields file:line).
* :func:`clean_gate_results` - what the MODEL reads of a finished gate in the history: the checks it could retype and cria's rendering of the
  result, taken from the typed result the history carries (``bodykeys.GATE_RESULT``), never from text.

Only a complete, hash-verified reading is handed to the parsers. A check whose output could not be read whole is explicit UNKNOWN and can never
become a clean gate.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from . import bodykeys, denial, dirguard, dedup, gatescript, jsontext, wsview
from . import groundtruth, participation, probediscovery, probeparse, prompts, proberun
from .gateops import GateResult, SectionFact, refusal_reason  # noqa: F401

# Leading ``path:line[:col][:]`` location prefix a linter prints before the diagnostic. Stripping it
# lets probeparse.is_advisory's ANCHORED style-code check (``^W###``/``E###``…) fire on a raw gate
# line — its phrase check is substring so it already works either way.
_LOC_PREFIX = re.compile(r"^\S.*?:\d+(?::\d+)?:?\s+")

from .proberun import ProbeReport
# runner_tally lives in probeparse now (it parses runner OUTPUT, and the tally must be taken at
# parse time while the raw text still exists). Re-exported so existing callers are unmoved.
from .probeparse import COMPILES_FIRST, runner_and_tally, runner_tally  # noqa: F401

# Per-probe wall-clock bound. Was 45 s (codex-local's COMPLETION_PROBE_TIMEOUT), which is fine for a
# syntax floor and far too short for what this gate actually selects: a full test suite, a cold
# `cargo check`, a `tsc` build. That is not merely a slow gate — `completion_block_nudge` fails CLOSED
# on a timed-out hard-failure probe, so a repo whose tests take a minute is permanently
# un-completable: every round re-nudges with "TIMEOUT after 45s" and no edit can ever clear it.
COMPLETION_PROBE_TIMEOUT_S = 240.0

# C28: a harness exec's DEFAULT yield does not have to honor a long wait (Codex clamped/returned early at ~10s in a captured incident, mid-pytest).
# The checks therefore run DETACHED (the `run` stub) and this is how long ONE poll of them waits for the run to be done before answering `running`
# instead of silently going empty-handed. Kept safely under the observed ~10s default.
GATE_POLL_WAIT_S = 8.0

# C28b: chosen at COMPOSE time (from the tool's own schema - never a harness name). A tool whose schema declares an ms-unit time-budget field is
# one a call can ask for more time on (reviewer measured Codex honoring ~30s for such a call), so its poll can wait longer per turn: fewer, cheaper
# polls for a slow gate. A tool with no such field keeps GATE_POLL_WAIT_S.
GATE_POLL_WAIT_LONG_S = 25.0

# The cria-side deadline for the WHOLE run, derived from the plan's OWN composed timeouts, never guessed: every selected probe (and the offline
# re-run leg, when present) is individually bounded by `timeout -k {TIMEOUT_KILL_GRACE_S} {COMPLETION_PROBE_TIMEOUT_S}` and they run SERIALLY, so the
# worst legitimate case is their sum. The run is killed by the harness (the `run` stub's own timeout) GATE_KILL_SLACK_S after that sum; cria waits
# GATE_DEADLINE_SLACK_S. Exceeding the deadline is the ONLY way a running gate becomes terminal UNKNOWN (fail closed, #13).
GATE_KILL_SLACK_S = 30.0
GATE_DEADLINE_SLACK_S = 60.0


@dataclass
class GatePlan:
    """Everything :func:`interpret_gate` needs to replay the output faithfully."""

    workspace: str
    # Probe discovery reads the session-scoped workspace view, never cria's local filesystem.  On
    # the first gate that view may still be empty, so the plan contains no candidates and its only
    # useful result is the survey that follows.  The reader needs to retain that provenance: once
    # the survey lands, this plan is obsolete and a newly discovered gate must run before completion.
    surveyed_before: bool = False
    # Manifest/config reads the view could not answer while this plan was composed. A non-empty set
    # means the candidates below were chosen blind to those files; cria's own survey delivers them,
    # and `interpret_gate` re-selects against it.
    unanswered_reads: frozenset = frozenset()
    script: str = ""        # the shell text the harness runs: the project's own checks (cria.gatescript)
    sections: list = field(default_factory=list)       # the ids of its checks, in order ("probe-0", ..., "offline")
    scope: tuple = ()       # the directories whose identity the run's start and end are compared on
    shown: str = ""         # the checks the coder could retype, one per line: all the model's history keeps of the call
    candidates: list = field(default_factory=list)  # selected ProbeCandidates, in section order
    # Authored default-discovery observations (probediscovery.undiscoverable_tests), not checker output.
    # Computed with the selection, so the clean-gate render reads a fact instead of re-walking the tree.
    untested: list = field(default_factory=list)
    # The subdirectory every real probe had to be run in, when NONE of them could run at the
    # workspace root — "" in the ordinary case. See :func:`_checks_ran_elsewhere`.
    ran_in: str = ""
    # Authored dependency facts (probediscovery.undeclared_gem_sentences), shown with the discovery observations.
    dependency_facts: list = field(default_factory=list)
    # cria-facing observations about the PLAN itself (not about the repo).
    notes: list = field(default_factory=list)
    # THE GATE'S OPERATION (cria.gateops): its id once issued, and what it learned once it is done (`adopt`). A plan whose gate is not done has
    # no result; a result that is not complete says why (`error`, `reported`) and is never read as a pass.
    op: str = ""
    result: "GateResult | None" = None
    error: str = ""         # why the evidence did not arrive, in cria's words (a log line)
    reported: str = ""      # the harness's own last line about why, verbatim: the line a traceback ends with names the exception
    refused: str = ""       # the harness declined to run the gate: its own words
    # The cria-side clock of this gate: when it was composed, how long the harness may run it and how long cria waits (cria.gateops holds the
    # operation's own copy; this is for a plan built without one).
    started: float = field(default_factory=time.monotonic)
    deadline_s: float = 0.0
    # How long ONE poll of this gate may wait for the run to be done, chosen once at compose time from the LAUNCHING tool's own schema.
    poll_wait_s: float = GATE_POLL_WAIT_S
    # The harness's tool for continuing a call it yielded (`shelltool.find_continuation_tool`), when it offers one: the gate then runs in the foreground of
    # its call and cria polls the session; without one a check that outlives its call cannot complete.
    continuation: "dict | None" = None
    # THE OFFLINE FACT THIS PLAN'S LAST CLEAN GATE PRODUCED, so a reader that is not the coder can
    # have it. `_offline_fact` is one sentence cria owns outright — the suite passed, and it passed
    # again with the network taken away — and it reached the coder in 20 prompts of L5
    # handles-cli-node x qwen35 and 0 of the 24 `satisfaction-confirm` prompts, which are the last
    # word before the run is allowed to end. That run shipped a suite whose seven tests all pass
    # before a single assertion runs (an unawaited async runner) and cria approved it. The plan is
    # the one object both the gate that computes the fact and the loop that ends the run already
    # hold (#23: one owner, no new store, no cross-session global).
    offline_fact: str = ""
    # Structured build/source/test reach from THIS plan's interpreted gate event.  Populated only
    # by :func:`interpret_gate`; selection alone never creates participation facts.
    participation: participation.ParticipationReport | None = None
    # THE SESSION'S UNRESOLVED WRITES, from cria's own operation ledger (`ledger.Ledger.unresolved_writes`): ``{operation: target
    # path}`` for each file mutation whose outcome the harness never confirmed and the file could not settle; empty when none.
    marks_paths: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.result is not None and self.result.complete


@dataclass
class GateOutcome:
    ran: bool = False  # False → no section came back; keep don't-wedge semantics
    report: ProbeReport | None = None
    unran: list = field(default_factory=list)  # selected checks whose output never came back — a GAP,
    #                                            not a pass: without this, a cut gate read clean
    refused: str = ""  # the harness REFUSED to run the gate (sandbox policy) — its own words, for the log
    swept: list = field(default_factory=list)  # private scratch the run reclaimed (relative to it)
    # DID THE NETWORK-OFF LEG COME BACK? None = it was never composed (no Test probe). False = it was
    # composed and printed nothing, which means the guard in front of it declined — the online run was
    # red, or the kernel/harness refused the namespace. That second case is the one worth seeing: the
    # leg is guarded by a capability probe that performs a BIND MOUNT, and this repo has already lost a
    # whole 24-cell arm to a verb Codex's sandbox disliked, silently. #12 — a lost instrument is an
    # event, not an absence.
    offline_ran: "bool | None" = None
    # The gate was planned before the workspace survey and this result successfully supplied that
    # survey, but no actual probe section ran.  This is bootstrap state, not a fresh attempted gate:
    # the caller must plan once more against the newly populated view.
    replan_after_survey: bool = False
    participation: participation.ParticipationReport | None = None
    transport_pending: bool = False  # the gate is not done yet
    transport_unknown: bool = False  # its evidence did not arrive whole; never a clean result
    transport_reported: str = ""  # the harness's own last line about why (see GatePlan.reported)
    scope_unknown: bool = False  # the original workspace's identity, or the private scratch, could not be settled
    # Write calls whose reply cria never had and whose completion this gate could NOT establish before its checks ran: ``[(receipt,
    # path, state)]``. A gate that verified a tree some write may still change (or that changed under it) has not verified it.
    unsettled_writes: list = field(default_factory=list)


def _gate_deadline_s(candidate_count: int) -> float:
    """The cria-side deadline (seconds) for a gate with this many timed probes."""
    per = COMPLETION_PROBE_TIMEOUT_S + proberun.TIMEOUT_KILL_GRACE_S
    return max(candidate_count, 1) * per + GATE_DEADLINE_SLACK_S


def adopt(plan: GatePlan, result: "GateResult | None") -> str:
    """Take the gate's result into the plan: ``pending`` (no result yet), ``complete`` or ``unknown``. A result that is not complete is
    explicit UNKNOWN - never a pass - and carries what cria and the harness said about why."""
    if result is None:
        if plan.deadline_s and time.monotonic() - plan.started > plan.deadline_s:
            plan.error = plan.error or "the check exceeded its own composed timeout budget while still running"
            return "unknown"
        return "pending"
    plan.result = result
    if not result.complete:
        plan.error, plan.reported, plan.refused = result.reason, result.reported, result.refusal
        return "unknown"
    return "complete"


def fail(plan: GatePlan, reason: str) -> str:
    """Make this gate's evidence terminally UNKNOWN (the harness no longer offers a shell, the history was rewritten past recovery)."""
    plan.error = reason
    plan.result = None
    return "unknown"


def _checks_ran_elsewhere(workspace: str, candidates: list) -> str:
    """The ONE subdirectory every real check had to run in, or "" — a fact straight off the plan.

    Cycle 4 cell 6, rust-toml-cli x gemma4, a from-scratch task: the model ran `cargo new toml-cli`
    and built a complete, working Rust project inside `toml-cli/`. cria's own gate cd'd into that
    folder for four of its five probes, they all passed, the gate went GREEN, the completion critic
    approved and the session exited normally. The verifier runs `cargo` at the working directory and
    found no `Cargo.toml`: **0 of 4**, on a cell that had scored 4/4 for three cycles running.

    cria was holding the fact the whole time — `working_dir=toml-cli` on every probe it composed —
    and never said it. This is not a judgement about layout (a monorepo puts manifests in
    subdirectories on purpose and is right to); it is the plan read back. It fires only when NO real
    check could run at the root, which is the case where the directory the harness handed the model
    contains no buildable project at all.

    The syntax floor is excluded: it walks files and always runs at the root, so counting it would
    make this permanently silent."""
    if not (workspace or "").strip():
        return ""            # `abspath("")` is the CWD, which would report cria's own directory
    root = os.path.abspath(workspace)
    dirs = set()
    for c in candidates:
        if c.kind is probediscovery.ProbeKind.SyntaxCheck:
            continue                       # walks the tree from the root by construction
        d = os.path.abspath(str(getattr(c, "working_dir", "") or root))
        dirs.add(os.path.relpath(d, root))
    if not dirs or "." in dirs or len(dirs) != 1:
        return ""                          # something ran at the root, or they disagree → say nothing
    where = dirs.pop()
    # A path that climbs OUT of the workspace is not a subdirectory of it, and naming it would point
    # the coder somewhere it is not working.
    return "" if where.startswith("..") or os.path.isabs(where) else where

def plan_gate(workspace: str, session: str = "", rlog=None, *,
              poll_wait_s: float = GATE_POLL_WAIT_S) -> GatePlan:
    """Inspect the workspace read-only and compose the gate script.

    Selection is re-run on EVERY gate (like upstream's ``discover`` per gate run):
    the repo's shape changes as the coder works — a pyproject.toml written in step 2
    must make pytest discoverable by step 3's gate.

    ``workspace`` empty → a MINIMAL gate (git snapshot only, no cd): cria couldn't learn
    the workspace path, so it must not discover against its OWN cwd (that once composed a
    probe over cria's repo itself). The harness's shell already runs in the workspace, so
    the git leg still lands; the checks just abstain (digest says none ran).

    ``poll_wait_s`` (C28b): how long each read of this gate's transport may wait for the `.done`
    marker before answering `running`. The CALLER picks it from the launching tool's own schema
    (``GATE_POLL_WAIT_LONG_S`` when it declares an ms-unit time-budget field, else the default
    ``GATE_POLL_WAIT_S``) — this function only carries it onto the plan so every later poll of the
    SAME transport (:func:`continue_transport_command`) reuses the same value."""
    plan = GatePlan(
        workspace=workspace,
        surveyed_before=bool(wsview.current(workspace or None).surveyed),
        poll_wait_s=poll_wait_s,
    )
    if workspace:
        wsview.take_unanswered_reads(session)        # only the reads THIS plan makes
        view = wsview.current(workspace)
        # Checks may change the very inputs used to select them. Refresh those exact
        # successfully read inputs in the survey AFTER the checks, rather than
        # trusting pre-check bytes on the next request or cycling through blind plans.
        with view.track_body_reads() as discovery_reads:
            plan.candidates = proberun.select_completion_probes(workspace)
        plan.untested = probediscovery.undiscoverable_tests(workspace)
        plan.unanswered_reads = wsview.take_unanswered_reads(session)
        # …and the other half of the same question. `undiscoverable_tests` reports test files a
        # default conventions do not select; this reports matching test files where no test
        # command was composed at all. Both end in the same clean-branch qualifier, because the coder
        # needs the same thing from either: to know that a green gate ran no tests.
        if not any(c.kind is probediscovery.ProbeKind.Test for c in plan.candidates):
            plan.untested += probediscovery.tests_with_no_command(workspace)
        plan.ran_in = _checks_ran_elsewhere(workspace, plan.candidates)
        plan.dependency_facts = probediscovery.undeclared_gem_sentences(workspace)

    # THE WORKSPACE SURVEY IS CRIA'S OWN OPERATION (`cria.surveyops`), asked while the checks run and again after them: this gate only says
    # what it will need. It carries the bodies the judge of this gate will read too: the completion judge is seeded from the view at the
    # moment it is composed; a body the view cannot vouch for is only QUEUED by that read, for a survey that comes too late (see
    # `groundtruth.want_judge_bodies`).
    if workspace:
        groundtruth.want_judge_bodies(workspace)
        # Unknown judge inputs take precedence over refreshes of already-known
        # discovery inputs within the survey's existing bounded FIFO.
        for rel in sorted(discovery_reads.paths):
            view.request_current_body(os.path.join(workspace, rel))
    wsview.want_refresh(session)       # the checks may change the tree, and the judge reads bodies: cria's own survey is asked for (cria.surveyops)
    # THE SESSION'S UNRESOLVED WRITES are known to cria's own ledger (a write whose reply was lost is asked of the file itself, and
    # sent again, before the model is consulted): only a mutation the file could not settle is still open when a gate is planned.
    from .ledger import Ledger
    plan.marks_paths = dict(Ledger().unresolved_writes(session))
    # A COMMAND THE CODER COULD RETYPE IS WORTH SHOWING; A PROGRAM CRIA WROTE IS NOT (see the note above `gate_call_ids`): state it now, while
    # cria still knows. A probe the coder could retype is one line of argv; a manifest check cria composed is a multi-line inline program.
    plan.shown = "\n".join(p for p in (" ".join(c.command) for c in plan.candidates if c.command and not c.composed_by_cria) if p.strip())
    plan.scope = tuple(dict.fromkeys([workspace, *(str(c.working_dir) for c in plan.candidates)])) if workspace else ()
    plan.script, plan.sections = gatescript.compose(plan.candidates, workspace, COMPLETION_PROBE_TIMEOUT_S, plan.scope)
    plan.deadline_s = _gate_deadline_s(len(plan.sections))
    return plan


def unsettled_writes(plan: "GatePlan") -> list:
    """The write calls this gate could not account for: each file mutation the operation ledger holds as unconfirmed (the harness
    never said whether it landed and the file did not say either). Nothing is approved on them; the notice says so."""
    return [(operation, path, "incomplete") for operation, path in (plan.marks_paths or {}).items()]



def issue(ops, session: str, shell_tool: dict, plan: GatePlan) -> "dict | None":
    """Issue the plan's gate through the engine ``ops``: the harness call that starts it, or None when it cannot be issued (nothing was
    recorded). The plan learns its operation."""
    from .opspath import OpsUnavailable
    facts = tuple(SectionFact(c.kind, bool(getattr(c, "composed_by_cria", False)), tuple(getattr(c, "command", None) or ()))
                  for c in plan.candidates)
    try:
        op, calls = ops.issue_gate(session, shell_tool, root=plan.workspace, script=plan.script, sections=plan.sections, timeout=run_seconds(plan),
                                   deadline=plan.deadline_s, wait=plan.poll_wait_s, facts=facts, shown=plan.shown, scope=plan.scope,
                                   continuation=plan.continuation)
    except OpsUnavailable:
        return None
    plan.op = op
    plan.started = time.monotonic()
    return calls[0]


def gate_ref(call: dict) -> str:
    """The id the loop keeps for a gate call it issued: the id of the call the history shows for it once it is done (the harness is
    handed a primitive call under an id of its own, which the projection takes out of the history)."""
    from . import callauth
    op = callauth.op_of(call.get("id"))
    return callauth.display_id(op) if op else str(call.get("id") or "")


def run_seconds(plan: GatePlan) -> float:
    """How long the harness may run the whole gate before it kills it: the sum of the checks' own bounds and a little more; cria waits longer."""
    return plan.deadline_s - GATE_DEADLINE_SLACK_S + GATE_KILL_SLACK_S


def sections_of(plan: "GatePlan | None") -> dict:
    """``{section id: (text, exit status or None)}`` of a gate whose result is complete; nothing otherwise (UNKNOWN is never read as sections)."""
    return dict(plan.result.sections) if plan is not None and plan.complete else {}


def cleanup_of(plan: "GatePlan | None") -> "tuple[list[str], list[dict]] | None":
    """What the gate reclaimed and what it could not settle, or None when the gate has no complete result."""
    return plan.result.cleanup() if plan is not None and plan.complete else None


def _plan_signature(candidates) -> tuple:
    return tuple((tuple(c.command), str(c.working_dir)) for c in candidates)


def gate_is_partial(outcome) -> bool:
    """Some selected evidence is missing, so this gate verified LESS than it was asked to.

    `unran` was recorded and then read by exactly one caller — `_verify_after_probe`, the plan-ON
    per-step gate. `loop.gate` events carrying `probes_run` (the plan-ON reading) per day over the
    log window: 2, 5, 4, 6, 3, 1, 0, 0, 0, 0, 0, 0 — zero on every day since the survey started
    riding the gate result. The three LIVE readers all read `outcome.report` only, and
    `proberun.unran_probes` answers a different question (a probe that launched and returned no exit
    code), so a section cut in transit is not in `results` at all.

    With no reader, `findings` came back "" and `record_gate_state` wrote GREEN — a gate that
    verified a subset reading as a gate that verified everything, which is the completion side of
    #13 failing open. `ran` cannot carry this: it is True as long as ANY section came back. A pending
    or failed page transport is partial for the same reason, before sections may be parsed at all."""
    return bool(getattr(outcome, "unran", None)
                or getattr(outcome, "transport_pending", False)
                or getattr(outcome, "transport_unknown", False)
                or getattr(outcome, "scope_unknown", False)
                or bool(getattr(outcome, "unsettled_writes", None)))


_DELIM_PAIRS = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
_UNMATCHED_RE = re.compile(r"^(.+?):(\d+):.*?\bunmatched\b.*?['\"]([()\[\]{}])")
# `path: … (at line LINE, column COL)` is not a compiler location prefix, so it remains the
# one shape outside probeparse.split_diag's canonical location parser.
_AT_LINE_RE = re.compile(r"^(.+?): .*\(at line (\d+), column \d+\)")


def _finding_location(finding: str) -> "tuple[str, int] | None":
    """The path and line named by a finding, across the location formats cria already parses."""
    parsed = probeparse.split_diag(finding)
    if parsed is not None and parsed[1] is not None:
        return parsed[0], parsed[1]
    at_line = _AT_LINE_RE.match(finding)
    if at_line:
        return at_line.group(1), int(at_line.group(2))
    return None


# A TOOL THAT CAN CHANGE THE WORKSPACE, not a tool that writes A FILE. The staleness ledger counted
# `write_file` and `edit_file` only, so a change made through the shell was invisible to it: on
# cart-billing-go x nemotron-elastic 1787434778 `go mod download` created go.sum, the ledger saw
# nothing, the "these checks ran BEFORE your edit" note never rendered, and the checks block went on
# asserting `missing go.sum entry` as present-tense ground truth for eleven consecutive coder calls —
# with the "the flagged line on disk" annotation re-attached each time, which makes a stale finding
# read as freshly re-verified. Same shape for npm install, go get, cargo add, bundle install.
def _a_command_could_have_changed_things_after(messages: list, start: int) -> bool:
    """Did the coder run a command that could have moved the workspace since the checks ran?

    The ledger above names FILES, and it can only name the ones cria lowered — so a change made
    through the shell is invisible to it. Nothing needs naming here: the question is only whether
    these findings can still be current, and the answer to that is the same for one file or ten."""
    from . import shelltool
    for m in messages[start + 1:]:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            if not shelltool.is_shell_tool_name(name):
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                continue
            cmd = str((args or {}).get("cmd") or (args or {}).get("command") or "")
            if cmd and shelltool.writes_something(name, cmd):
                return True
    return False


def _probe_reran_after_last_change(messages: list, start: int, plan: "GatePlan | None") -> bool:
    """Did the coder re-run one of the gate's own probe commands AFTER the last workspace change?

    That is the one case where ``checks_are_stale``'s "have not been re-run since" is a false fact
    about work the coder just did (#5b) — and its "re-run them" an instruction to repeat the action
    it answers. Matched against the PLAN'S own discovered argv, never a command vocabulary (#20):
    a probe re-run is recognised because the coder's command CONTAINS a probe's joined argv. False
    whenever cria cannot tell (no plan, no candidates, no shell record) — the existing sentence then
    stands unchanged, which is today's behaviour (#13: fail toward the known state).

    A command that both matches a probe AND could write (e.g. ``go build && go get x``) counts as a
    CHANGE, not a re-run — its findings may not reflect its own change, so the stale note stays."""
    from . import shelltool
    probe_strs = [" ".join(c.command) for c in getattr(plan, "candidates", []) or []
                  if getattr(c, "command", None)]
    if not probe_strs:
        return False
    changed = False
    reran = False
    for m in messages[start + 1:]:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                continue
            if name in ("write_file", "edit_file"):
                changed, reran = True, False
                continue
            if not shelltool.is_shell_tool_name(name):
                continue
            cmd = str((args or {}).get("cmd") or (args or {}).get("command") or "")
            if not cmd:
                continue
            if shelltool.writes_something(name, cmd):
                changed, reran = True, False
            elif changed and any(p in cmd for p in probe_strs):
                reran = True
    return reran


def _paths_written_after(messages: list, start: int) -> "frozenset[str]":
    """Basenames of files a LANDED write/edit touched in messages after ``start``.

    The newest gate result is re-annotated at every prompt build, and "the flagged line on disk" is
    read at render time — so a check that ran before an edit gets stamped with the post-edit line.
    Walked on mellum2 1786196176 (0036/0045/0054): pyflakes said line 42 col 61 has `requests`;
    cria's own quote of disk line 42 showed a line with no `requests` — a self-contradictory anchor,
    three times, because the file moved under the still-newest gate. The write ledger in the same
    message list says exactly which files moved; their findings keep the checker's line, unquoted."""
    calls: dict = {}
    changed = set()
    landed_ids = denial.landed_call_ids(messages)     # the typed fact of each write's own program, never its wording
    for m in messages[start + 1:]:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") in ("write_file", "edit_file"):
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    continue
                path = str((args or {}).get("path") or (args or {}).get("file_path") or "")
                if path and tc.get("id"):
                    calls[tc["id"]] = os.path.basename(path)
        if m.get("role") == "tool" or m.get("type") == "function_call_output":
            tid = m.get("tool_call_id") or m.get("call_id")
            c = m.get("content") if m.get("content") is not None else m.get("output")
            if tid in calls and isinstance(c, str) and tid in landed_ids:
                changed.add(calls[tid])
    return frozenset(changed)


# A line that is itself a DIAGNOSTIC — it names a location, or it opens with a severity word. Only
# these are candidates for the advisory filter; everything else in a check's output is the program's
# own text (a traceback's source echo, a failure report's body) and is not cria's to judge.
_SEVERITY_OPENER = re.compile(r"^\s*(?:note|warning|hint|info|convention|refactor|error|E\d{3}|W\d{3}|"
                              r"C\d{4}|R\d{4})\b[: ]", re.I)


def _is_a_diagnostic_line(s: str) -> bool:
    """Does this line NAME A LOCATION or DECLARE A SEVERITY — i.e. is it the checker talking about
    code, rather than the code (or the program's own output) itself?"""
    return (bool(_LOC_PREFIX.match(s)) or bool(_SEVERITY_OPENER.match(s))
            or probeparse.split_diag(s) is not None)


def _with_delimiter_facts(findings: list[str], plan, annotate: bool = True,
                          changed_paths: "frozenset[str]" = frozenset()) -> list[str]:
    """For an unmatched-delimiter finding, append ONE counted fact: the flagged line's actual
    on-disk bytes plus how many openers and closers it holds. Code counts, the model applies —
    a small model provably cannot (run 0729-gemma4: 137 calls failing to remove one ')', its own
    steer author miscounting too). The fact PRESCRIBES NOTHING (operator: cria cannot know whether
    the fix is deleting the extra closer or adding a missing opener). When the flagged line's
    counts BALANCE, the imbalance lives on another line — a single-line count would mislead, so
    stay silent (state the fact or be silent)."""
    import os
    out: list[str] = []
    workspace = getattr(plan, "workspace", "") or ""
    done: set = set()
    for idx, f in enumerate(findings):
        if idx in done:
            continue        # already emitted as part of the diagnostic that owns it
        out.append(f)
        done.add(idx)
        if not workspace:
            continue

        def emit(note: str, _i=idx, _head=f) -> None:
            """cria's line goes AFTER the whole diagnostic, never inside it.

            The findings list is one entry per LINE, and a compiler's diagnostic spans several: Go
            prints `have (int)` / `want (string)` under its error, javac prints `symbol:` and
            `location:`. Appending here put cria's sentence between the error and the rest of its own
            explanation — 132 times in one run, under a header reading "each is the checker's OWN
            message" (#R6). The continuation lines are moved out first, so the checker's text stays
            in one piece and cria's annotation follows it."""
            j = _i + 1
            while j < len(findings) and probeparse.continues_previous(findings[j], _head):
                out.append(findings[j])
                done.add(j)
                j += 1
            out.append(note)
        m = _UNMATCHED_RE.match(f)
        if m:
            path, line_no, d = m.group(1), int(m.group(2)), m.group(3)
            line = _source_line(path, line_no, workspace)
            if line is None:
                continue
            opener = d if d in "([{" else _DELIM_PAIRS[d]
            closer = _DELIM_PAIRS[opener]
            n_open, n_close = line.count(opener), line.count(closer)
            if n_open == n_close:
                continue
            emit(f"  counted fact: line {line_no} on disk is `{line.strip()}` — it contains "
                 f"{n_open} '{opener}' and {n_close} '{closer}'.")
            continue
        # GENERAL case (walked on run 1785904860, ~call 0045): a finding that names a POSITION
        # without quoting the line invites the model to GUESS the line's text — the checker said
        # `pyproject.toml: Invalid value (at line 20, column 9)` and the model edited against an
        # invented `build-backend = "python3"` that was never on disk or in context. Quote the
        # flagged line's real bytes. Same contract as the counted fact: state the fact or be
        # silent (missing file/line → silent; line already quoted in the finding → silent),
        # and PRESCRIBE NOTHING.
        if not annotate:
            continue        # HISTORY — see clean_gate_results; the quote would be read from a
                            # file that has moved on since these findings were produced.
        location = _finding_location(f)
        if location is None:
            continue
        path, line_no = location
        if os.path.basename(path) in changed_paths:
            continue        # the file moved since this check ran — quoting today's line under
                            # yesterday's finding manufactures the contradiction; the finding stands
        # ONLY inside the workspace. An absolute finding can name a stdlib frame
        # (/usr/lib/python3.12/unittest/mock.py:956 in a pytest traceback), and quoting it back
        # presents CPython internals as "a line the repo's own checks flagged" — under a header
        # telling the coder to fix what each one names. Walked: ~10 such annotations per checks
        # block, each duplicating the traceback line printed directly beneath it. The workspace
        # view answers only for paths inside the workspace, so that bound is now the seam itself.
        line = _source_line(path, line_no, workspace)
        if line is None:
            continue
        text = line.strip()
        if not text or text in f:      # nothing to quote, or the finding already shows it
            continue
        if _EXCEPTION_FINDING.search(f):
            # A RAISE SITE IS NOT A DEFECT SITE. This annotation is correct for a LINTER, where the
            # flagged line IS the problem, and actively misleading for a runtime exception, where it
            # is merely where the program stopped — the cause is upstream, in the value that reached
            # it. Under a header ordering the coder to "resolve exactly what it names", quoting the
            # raise site points at the one line that is usually fine. Measured on the six-language
            # battery: the coder rewrote the assertion line repeatedly while the bad value came from
            # a default argument three functions away. cria cannot justify the pointer, so it does
            # not make it (#5b, and #3 — silence over noise).
            continue
        # WHOLE. This quote exists so the model does not GUESS the line, and a cut quote is a
        # partial guess-prompt — which is the failure it was built to prevent. It was a silent cut,
        # then a marked one; marking it does not restore the half that was removed (rule 5).
        emit(f"  the flagged line on disk — line {line_no}: `{text}`")
    return out


# A finding produced by a program CRASHING rather than by a checker inspecting code. Matched on the
# shapes runtimes actually print — an exception class at the HEAD of a located finding's message, a
# traceback frame, an assertion report — not on one language's phrasing. The position matters: a
# compiler diagnostic can mention a type named `SomeException` later in its own sentence (javac's
# `unreported exception …; must be caught or declared`), and that is a source defect, not a runtime
# raise site. The old anywhere-in-line match suppressed the grounded source quote for exactly that.
_EXCEPTION_FINDING = re.compile(
    r"(?im)^\s*(?:Traceback|Exception in thread|goroutine \d+)"
    r"|(?:^|:\d+(?::\d+)?:\s+)(?:[\w.$]+\.)*[A-Z]\w*(?:Error|Exception)\b"
    r"|\bpanic:|\bassertion failed\b|\bpanicked at\b"
    r"|\bat [\w.$]+\([\w.]+\.(?:java|kt|scala):\d+\)")


def _source_line(path: str, line_no: int, workspace: str) -> "str | None":
    """Line ``line_no`` of a workspace file, or None when cria has not been told the file.

    ONE owner for the three annotators that quote a flagged line back to the coder. The bytes come
    from :mod:`cria.wsview` — the harness's filesystem, which is the one the checks ran against.
    A path OUTSIDE the workspace answers None, which is what the stdlib-frame guard wanted anyway.
    """
    import os
    view = wsview.current(workspace)
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(workspace, path))
    # ONLY inside the workspace, stated here rather than left to the view. An absolute finding can
    # name a stdlib frame (/usr/lib/python3.12/unittest/mock.py:956 in a pytest traceback), and
    # quoting it back presents CPython internals as "a line the repo's own checks flagged".
    root = os.path.normpath(workspace).rstrip(os.sep)
    if full != root and not full.startswith(root + os.sep):
        return None
    body = view.read(full)
    if body is None:
        return None
    try:
        return body.splitlines()[line_no - 1]
    except IndexError:
        return None


def _line_on_disk(finding: str, workspace: str) -> "str | None":
    """The on-disk text of the line a ``path:LINE…`` finding flags, or None. Feeds probeparse's
    F811 discriminator (def/class shadow = real bug; import rebinding = advisory) — the file
    access the pure predicate can't do itself."""
    location = _finding_location(finding)
    if location is None or not workspace:
        return None
    return _source_line(*location, workspace)


def _command_for_sid(plan, sid: str) -> str:
    """The plain, model-facing command string for section ``sid`` (``probe-N`` -> candidate N,
    section order), or ``""`` when the plan/index/command is unavailable. Works identically whether
    ``plan.candidates`` holds real ``ProbeCandidate``s (the live gate) or persisted ``_SectionFact``s
    (a rebuilt historical plan, see :func:`_facts_for_transport`) -- both expose the same `.command`
    shape. Naming only -- never used for parsing/classification, which stays on the EXIT code."""
    try:
        idx = int(sid.split("-", 1)[1])
        c = plan.candidates[idx]
    except (AttributeError, IndexError, ValueError, TypeError):
        return ""
    command = getattr(c, "command", None)
    return proberun.display_command(list(command)) if command else ""


def _timeout_note(plan, sid: str, printed: str) -> str:
    """One sentence naming a TIMED-OUT section (EXIT 124): the command when the plan/facts know it,
    else the same generic "a check" base always used -- and what it printed, when it printed
    anything, appended verbatim as CONTEXT. Named EVEN WHEN it printed nothing (reviewer directive,
    C39b): the check ran and was stopped, which is never the same fact as "no usable result at
    all" (the bare could-not-launch case a missing/absent tool still produces).

    Model-facing text lives in ``cria/prompts/*.txt`` (AGENTS.md), never an inline f-string --
    ``checks_timeout``/``checks_timeout_printed`` are the one owner of this wording, reused by the
    legacy could_not_run branch below for its own (unnamed) sections so the phrase is never typed
    twice."""
    label = _command_for_sid(plan, sid)
    command = f"`{label}`" if label else "a check"
    note = prompts.render("checks_timeout", command=command)
    if printed:
        note += " " + prompts.render("checks_timeout_printed", printed=printed)
    return note


def _not_launched_note(plan, sid: str, code: int, printed: str) -> str:
    """One entry for a check that never produced a result. A tool cria launched DIRECTLY (a floor probe) that exits 127 is a fact
    about the machine: it is not installed. Anything else (a declared `npm run test` whose script runs a missing tool also exits 127)
    only says what the exit code says, and shows what the checker printed, so its own words are never replaced."""
    try:
        c = plan.candidates[int(sid.split("-", 1)[1])]
    except (AttributeError, IndexError, ValueError, TypeError):
        c = None
    words = prompts.load_map("checks_not_launched")
    program = proberun._head_program(c.command) if c is not None and getattr(c, "command", None) else ""
    if program and code == proberun.NOT_FOUND_EXIT_CODE and getattr(c, "composed_by_cria", False):
        return prompts.fill(words["absent"], program=f"`{program}`", code=code)
    note = prompts.fill(words["other"], command=f"`{_command_for_sid(plan, sid)}`" if _command_for_sid(plan, sid) else "a check", code=code)
    return note + (" " + prompts.fill(words["printed"], printed=printed) if printed else "")


def _is_hard_failure(plan, sid: str) -> bool:
    """Is section ``sid`` a probe whose non-zero exit is a REAL failure regardless of how its output
    looks? Test / typecheck / build — `plan.candidates` is in section order, so probe-N is candidate N.
    Unknown plan or unparseable id → False (keep the advisory-clean lint behaviour)."""
    # `kind` is a FIELD, not a method. Calling it raised TypeError on every probe, and TypeError was
    # in this function's own `except`, so it swallowed its own defect and returned False forever —
    # proved by executing it: a Test candidate, whose kind IS in _HARD_FAILURE_KINDS, answered False.
    #
    # What that turned off: the branch that reports a non-zero exit as a real failure REGARDLESS of
    # how its output looks. With it dead, a build that fails only on warnings-shaped output — a
    # `-Werror` compile, `#![deny(warnings)]`, `noUnusedLocals` — was summarised to the model as
    # clean, which is the fail-open on missing ground truth (#13) this file exists to prevent.
    #
    # It hid because a DIFFERENT function of the same name in focustrim.py is tested and correct, so
    # the name looked covered.
    #
    # TypeError is deliberately no longer caught: nothing here legitimately raises it, and catching it
    # is what let the bug live.
    try:
        idx = int(sid.split("-", 1)[1])
        kind = plan.candidates[idx].kind
    except (AttributeError, IndexError, ValueError):
        return False
    return kind in proberun._HARD_FAILURE_KINDS

def clean_gate_output(plan: "GatePlan | None", *, annotate: bool = True,
                      changed_paths: "frozenset[str]" = frozenset(),
                      a_command_ran_since: bool = False,
                      checks_reran: bool = False) -> str | None:
    """A finished gate's result (``plan.result``: what each check printed and its measured exit status) → a compact, error-class-only summary
    for the MODEL to read.

    Shown verbatim (and PROTECTED from trimming) the checkers' output buried the one real error under noise AND leaked advisory lint
    (``imported but unused``) the model then chased — even though the gate DIGEST already filters those. This keys on the RELIABLE per-section
    exit code (not fragile text sniffing) and reports one honest state: error-class
    findings; a check that FAILED with no parseable location; checks that could NOT run (launch failure
    / timeout — cria's own setup gap, a neutral non-signal, never a pass); or the checks that ran found
    nothing (their own output and measured exit status, never an authored success verdict).
    Returns ``None`` when there is no complete gate result
    (UNKNOWN claims nothing)."""
    if plan is None or not plan.complete:
        return None
    # This mutable field belongs to THIS interpreted gate event, not to the last clean event that
    # happened to populate the same plan object.  Every non-gate caller leaves it alone; every real
    # gate first makes silence the current fact and only the clean offline branch below may set it.
    # Without the reset, a later red Go gate left an earlier network-off pass in the completion
    # confirmer's prompt — true historically, false as a statement about the current workspace.
    if plan is not None:
        plan.offline_fact = ""
    workspace = getattr(plan, "workspace", "") or ""
    stranded_findings: list[str] | None = None   # scanned at most once, only on a zero-tests signal
    findings: list[str] = []
    dropped_advisories = 0
    could_not_run = False
    not_launched: list[str] = []    # a check that never started is named; it does not erase the checks that did run
    ran_a_check = False
    failed_no_detail = False
    saw_probe = False
    timed_out_output: list[str] = []
    timeout_notes: list[str] = []   # one per genuinely-timed-out (EXIT 124) section, ALWAYS populated
    completed_output: list[str] = []
    zero_collected_output: list[str] = []
    discovery_observations: list[str] = list(getattr(plan, "dependency_facts", None) or [])

    def finish(message: str, *, include_completed: bool = True, include_not_launched: bool = True) -> str:
        # Native zero-collected evidence is independent of the winning diagnostic/timeout branch.
        # Discovery metadata must never replace it; other successful output keeps its clean-branch scope.
        if include_completed and zero_collected_output:
            message += "\n" + prompts.render("checks_completed", results="\n".join(zero_collected_output))
        if not_launched and include_not_launched:
            message += "\n" + "\n".join(not_launched)
        if discovery_observations:
            message += "\n" + prompts.fill(prompts.load_map("discovery_observations")["section"],
                observations="\n".join(dict.fromkeys(discovery_observations)))
        return message + cleanup_note

    # Each check's output and measured status are what the harness wrote for it (one file per check, read back and hash-checked by cria);
    # nothing is searched for in checker output, and the cleanup report is cria's own listing of the private scratch.
    _sections = sections_of(plan)
    cleanup_note = cleanup_fact(plan)
    for sid, (text, code) in _sections.items():
        # The offline re-run is an INSTRUMENT READING, not a check. It is the same suite with the
        # network taken away, so on a genuinely live suite it is SUPPOSED to fail — and this loop
        # would have scraped that failure into the findings and told the coder to go fix passing
        # tests (the false-red class, from the very leg built to expose a false green). Its exit
        # code reaches exactly one reader: _offline_fact. Skipping it also keeps a namespace-less
        # box honest — an empty section can no longer set could_not_run and wedge the whole gate.
        if sid == "offline":
            continue
        saw_probe = True
        # The EXIT sentinel is the reliable signal (the composed probe always prints it). A launch
        # failure (125/126/127) or timeout (124) means the check did NOT complete — never a code error
        # to "fix", never a pass. Sniffing text for "no such file" would misread a real error that just
        # mentions it (a FileNotFoundError, a missing #include) as couldn't-run.
        if code in proberun.LAUNCH_FAILURE_EXIT_CODES:
            not_launched.append(_not_launched_note(plan, sid, code, text.strip()))    # never launched → nothing it could have printed
            continue
        if code is None:
            # The section header arrived but its EXIT sentinel never did: the HARNESS returned (its
            # yield window / output cap) while the check was still running — observed live: a 10s
            # exec yield cut the composed gate mid-pytest ("Process running with session ID …"), and
            # this section previously contributed NOTHING, so a lint-green gate read CLEAN while the
            # tests never finished (the vacuous-green shape). A missing sentinel can ONLY mean a cut
            # stream — the script echoes EXIT:$? unconditionally, so even a missing tool prints 127.
            # Same treatment as a timeout: never a pass, partial output kept as context not findings.
            could_not_run = True
            if text.strip():
                timed_out_output.append(text.strip())
            continue
        if code == proberun.TIMEOUT_EXIT_CODE:
            # A timeout is NOT a launch failure: the command RAN and may already have printed the real
            # error before it stalled. The state stays "couldn't run" (never a pass, and its lines must
            # NOT be scraped as error-class findings — post-timeout output is mostly noise, the false-red
            # class), but what it DID print is kept as CONTEXT rather than discarded.
            #
            # C39b: NAMED, not folded into a bare "no usable result" — even when it printed nothing.
            # An empty timeout and a genuine launch failure (the absent-tool/couldn't-launch case
            # above) are different facts: this command RAN and was stopped; that one never started.
            # Collapsing them told the coder "no signal either way" about a suite that was, in fact,
            # still hanging (the p27 Orders shape this candidate exists for).
            could_not_run = True
            timeout_notes.append(_timeout_note(plan, sid, text.strip()))
            continue
        ran_a_check = True
        # Keep successful/zero-test output as evidence. An exit code describes this command,
        # not the task or another source tree; never replace the checker's words with ours.
        if code == 0 or proberun.is_no_tests_collected(code, output=text):
            completed_output.append(prompts.render("checks_completed_section",
                command=_command_for_sid(plan, sid) or sid, code=code,
                output=text if text else prompts.load("checks_no_output").rstrip("\n")))
        # pytest exit 5 = no tests collected (a fresh/testless project). The runner ran fine and had
        # nothing to assess — a benign non-signal. Skip the section so its "no tests ran" line isn't
        # scraped as an error-class finding AND it doesn't set failed_no_detail; the OTHER probes that
        # ran decide the gate's verdict. saw_probe stays True, so a pytest-only gate reads clean-ish
        # ("checks that ran reported no problems"), never "one of the checks FAILED".
        #
        # UNLESS the disk says otherwise. Measured on maple run 2 (1785973706): a 19KB pytest suite
        # named `pytest_da_resolvers.py` — a name pytest's pattern cannot collect — so "no tests ran"
        # for the run's final 30 minutes while real tests sat on disk, and the benign rule kept the
        # gate silent. Keep the native zero-collected output and separately report default naming
        # observations. A naming mismatch is authored metadata, not a checker's error-class message
        # or proof that an explicit invocation cannot execute the file. The detector is the
        # ONE existing owner (probediscovery's convention table — the g20 mechanism), not a second
        # scanner. Also applied to a PASSING test section whose runner said it collected nothing
        # (go's "[no test files]" exits 0) — a green built on zero tests plus a stranded suite is
        # the same false green.
        if proberun.is_no_tests_collected(code, output=text) or \
                (code == 0 and _zero_tests_marker(text)):
            zero_collected_output.append(completed_output[-1])
            if stranded_findings is None:
                stranded_findings = probediscovery.stranded_test_sentences(workspace) \
                    if workspace else []
            discovery_observations.extend(stranded_findings)
            continue
        # A check that PASSED (exit 0) has, by definition, no error-class problem — its stdout is NOT a
        # diagnosis. Linters/typecheckers print nothing on success, but pytest prints "…. [100%]\nN
        # passed", go test prints "ok", etc. — and the raw-line scraper below would harvest those as
        # "findings" and hand the model "fix them at the reported line: 4 passed" (a false-red that told
        # the model to fix a GREEN suite ~20 times). Skip a passing section entirely; the exit code is
        # the reliable signal (kept: a None code — sentinel lost, unknown — still gets scraped, never
        # silently swallowed).
        if code == 0:
            continue
        had_content = False
        advisory_dropped = 0
        section_findings: list[str] = []
        prev_kept = ""   # consecutive-repeat collapse only — see the note at the append below
        for ln in text.splitlines():
            s = ln.strip()
            if not s:   # blank
                continue
            had_content = True
            # advisory either as a whole line (phrase/prefix forms) or once the location prefix is
            # stripped (bare style code like `foo.py:80:1: E501 …`) — unused-import / style, filtered.
            # For an F811 redefinition the flagged line on disk is the discriminator (def/class
            # shadow = real bug, kept; import rebinding = cleanliness, dropped) — only F811 pays
            # the disk read.
            flagged = (_line_on_disk(s, workspace)
                       if probeparse.F811_PHRASE in s.lower() else None)
            # A DELETION IS KEYED ON STRUCTURE, AND IT IS COUNTED. Two rules used to be missing
            # here. First, this ran the advisory PHRASE test over every raw line of a check's
            # output — including the source echo inside a traceback and the body of a failure
            # report — so a line of the coder's own code containing "unused variable" was deleted
            # from the middle of a block cria ships as "the checker's OWN message". A line is only
            # a candidate for this filter when it IS a diagnostic: it carries a location prefix or
            # a severity word of its own. Second, the drop was silent, so a check whose entire
            # output was advisory read as a check that printed nothing (#R7).
            if _is_a_diagnostic_line(s) and (probeparse.is_advisory(s, flagged)
                                             or probeparse.is_advisory(_LOC_PREFIX.sub("", s), flagged)):
                advisory_dropped += 1
                continue
            # KEEP THE LINE AS THE CHECKER WROTE IT. `s` is the stripped copy — fine for deciding
            # whether to keep a line, wrong to SHIP, because cria ships this block under "each is the
            # checker's OWN message". De-indenting and globally de-duplicating destroys the source
            # echo in a traceback: pytest prints the failing function's body, and a `}` or `)` on its
            # own line is both indentation-bearing AND a repeat of one seen earlier, so it is deleted
            # twice over.
            #
            # Walked on ada-handles_fabliq_codex_pon_1785721353. A reader fed the real pytest output
            # through this function and reproduced cria's exact call-0185 bytes, including:
            #
            #     'total_handles': total_handles
            # except requests.exceptions.RequestException as e:      <- the closing } is GONE
            #
            # The file parses cleanly; `compileall` exited 0 in that same gate. cria manufactured
            # "handle_resolver.py has a syntax error — missing a closing parenthesis", restated it in
            # every prompt for 45 straight calls, and the coder copied the DE-INDENTED text into
            # edit_file old_strings that could never match. Two earlier walks named this their top
            # fix. Dedupe on the stripped form; emit the original.
            #
            # CONSECUTIVE-ONLY, not global — the same walk family, one organ deeper. A GLOBAL `seen`
            # deletes a line because an IDENTICAL line appeared in a DIFFERENT failure block, and two
            # failures that share an assertion are not duplicates: they are two facts. Walked on
            # ada-handles_nemotron-elastic_codex_pon_1785360304 calls 0152/0153/0155, where pytest
            # reported two failing tests whose bodies share `self.assertIsNotNone(result[...])` and
            # `E  AssertionError: unexpectedly None`. Both lines were printed for test_goose and
            # therefore DELETED from test_papagoose, so the coder was handed
            # `test_resolve_handle.py:24: AssertionError` with no assertion and no reason under a
            # header promising "each is the checker's OWN message". The same global rule also ate a
            # docstring's closing `\"\"\"`. Collapsing a line repeated back-to-back is still worth
            # doing (that is the spam this was built for); collapsing across blocks is data loss.
            if s != prev_kept:
                prev_kept = s
                section_findings.append(ln.rstrip())
        # NAMED, NEVER SILENT — but NOT as a finding. A note about cria's own handling must not make
        # an advisory-only check read as a failing one; it rides alongside, on whichever branch the
        # gate takes, so the reader can tell "this check had nothing to say" from "this check said
        # things cria decided were style".
        dropped_advisories += advisory_dropped
        findings.extend(section_findings)
        # a check that exited NON-ZERO but printed NOTHING usable (empty output) still FAILED — don't
        # let it read as clean. If it printed only advisory lines (had_content, no findings), that's an
        # advisory-clean lint exit, NOT a failure — so keying on had_content avoids the footgun.
        if code not in (0, None) and not had_content:
            failed_no_detail = True
        # A non-zero exit whose output is ALL advisory-shaped is an advisory-clean LINT exit (don't send
        # the model chasing style) — but for a TEST/TYPECHECK/BUILD probe it is a real failure whose
        # diagnostics merely look advisory: -Werror, deny(warnings), tsc noUnusedLocals. Reporting that
        # as "no error-class problems" is a false green on a build that did not build. The probe KIND is
        # the grounded distinction, and it is in the plan cria already holds.
        elif code not in (0, None) and not section_findings and _is_hard_failure(plan, sid):
            failed_no_detail = True
    if not saw_probe:               # git-only gate (empty/no-code repo) → NO check ran → not a pass
        could_not_run = True
    findings = _with_delimiter_facts(findings, plan, annotate, changed_paths)
    if findings:                    # a check RAN and found a real error-class problem — foreground it
        # Show EVERY error-class finding — a 40-line clip once hid findings 41+, so the model "fixed"
        # what it saw and claimed done while real errors remained invisible. The context floor
        # (contextfloor.fit) is the one window-aware place a truncation may happen, and only when the
        # physical window forces it — never a blind per-site clip here.
        # NOT "the smallest change that clears it". When the failure is a real defect, the smallest
        # change that CLEARS it is to stop the check asking. Walked on
        # ada-handles_mellum2_codex_poff_1785714194: at 0029 pytest reported `AssertionError: 0 not
        # greater than 0` — a true signal that the deliverable was wrong — and the coder rewrote its
        # own assertion to `assertEqual(result["total_handles"], 0)`. The test then certified the bug
        # and the run shipped green. The phrase landed twice in that one run.
        # ONE OWNER FOR THE SEEDED-TEST RULE, and this is the copy that was missed. The "changing
        # the test so it stops asking is not a fix" clause lived in THREE places — two prompt files
        # and this inline literal. Commit 57c8520 added the carve-out that tells the coder WHICH
        # tests the rule governs ("the tests that were already in the repository when you started…
        # a test YOU wrote earlier in this session is yours") to the two prompt files and could not
        # add it here, because a string in code is not where anyone looks for a prompt (#22).
        #
        # This is the copy that ships. It is in 3,254 captured coder prompts — far more than either
        # sibling. So for a whole cycle the coder was told "changing the test is not a fix" and never
        # told which tests that covered. Walked on cycle 4 cell 7, shipping-rates-rb x qwen35: the
        # model reverted its own test edit once, citing the task, and two calls later rewrote a
        # SEEDED assertion from 15.99 to 32.99 — a test its own `rake test` had reported as passing.
        # …AND SAY WHEN THEY PREDATE THE CODER'S OWN EDIT. The newest gate result is re-shown at
        # every prompt build until a new one exists, so after an edit lands the coder keeps reading a
        # verdict about the file it just changed. Walked on cycle 4 cell 19 (`shipping-rates-rb x
        # nemotron-elastic`): the gate ran at 07:27:41, the correct `>=` fix landed at 07:28:57, and
        # calls 0048-0062 all carried the pre-edit failure. The model reasoned against it twice —
        # "we changed to >=, but maybe the code we edited was not the same as the one running… The
        # only explanation is that the condition is not being evaluated correctly" — then reverted
        # its own correct fix, and on the last action of the run reverted it further. `changed_paths`
        # already knows which files moved; it was only being used to unquote the annotation.
        stale = ""
        if changed_paths:
            # "…have not been re-run since — re-run them" answered the coder's OWN literal re-run of
            # the same checks (walked on cart-billing-go x nemotron-elastic 1788230301: last go.mod
            # edit, then `go vet ./... && go build ./...`, then this sentence over lines identical to
            # that fresh run's output — a false fact instructing the action just taken, a churn loop).
            # When the coder demonstrably re-ran one of the PLAN'S OWN probes after the last change,
            # say the true thing instead: these lines are the older reading; trust the newest output.
            key = "checks_are_stale_rerun" if checks_reran else "checks_are_stale"
            stale = prompts.render(key,
                                   files=", ".join(f"`{p}`" for p in sorted(changed_paths)))
        elif a_command_ran_since:
            # NAMED WHERE cria CAN NAME IT, STATED WHERE IT CANNOT. `go mod download` created go.sum
            # and the file ledger saw nothing, so this note never rendered and the block asserted
            # `missing go.sum entry` as present-tense ground truth for eleven more coder calls.
            stale = prompts.load("checks_are_stale_command")
        msg = prompts.render("checks_error_class",
                             seeded_test_rule=prompts.load("seeded_test_rule").strip(),
                             stale=stale.rstrip("\n"),
                             findings="\n".join(findings + _advisory_note(dropped_advisories)))
        # C39b (f): A REAL FINDING MUST NOT BURY A SIBLING TIMEOUT. `findings` wins the priority
        # order (a concrete diagnostic is the most actionable fact this function can hand back), but
        # returning outright here used to make an unrelated hung check invisible next to it — the
        # coder "fixed" the reported lint error and believed the gate was answered while the real
        # pytest hang (the p27 Orders shape) never surfaced at all. Appended, never merged into
        # `findings` itself (never speak over a tool: the timeout note is cria's OWN sentence, not a
        # checker's line, so it must not ride inside the block `checks_error_class` renders as the
        # checker's verbatim output).
        if timeout_notes:
            msg += "\n" + "\n".join(timeout_notes)
        return finish(msg)
    if failed_no_detail:            # ran, exited non-zero, no usable output → a failure with no location
        msg = CHECKS_MARKER + " " + prompts.load("checks_failed_no_detail")
        if timeout_notes:
            msg += "\n" + "\n".join(timeout_notes)
        return finish(msg)
    if could_not_run and (timeout_notes or timed_out_output):
        # C39b: named, with its command when the plan/facts know it — even when it printed nothing.
        # This supersedes the older uniform "could_not_run and timed_out_output" wording for every
        # TIMEOUT (EXIT 124) section: naming used to require non-empty output, so an empty timed-out
        # pytest read exactly like a genuinely absent tool ("no usable result — no signal either
        # way") — the false neutrality this candidate exists to remove.
        parts = list(timeout_notes)
        if timed_out_output:
            # Regression fix (independent review of f1566336): a SIBLING section whose EXIT
            # sentinel never arrived (`code is None`, a cut stream — not a confirmed `timeout(1)`
            # kill, so it is never named via `_timeout_note`) printed real content, e.g. `E
            # AssertionError: boom`. The first version of this branch returned `timeout_notes`
            # alone the moment ANY section was a confirmed timeout, silently dropping that other
            # section's output — never speak over a tool (#5). Appended with the SAME generic
            # wording the old uniform branch always used for an unnamed section, so nothing here
            # claims a command it does not know.
            parts.append(prompts.render("checks_timeout", command="a check") + " "
                         + prompts.render("checks_timeout_printed",
                                          printed="\n".join(timed_out_output)))
        return finish(CHECKS_MARKER + " " + "\n".join(parts))
    if could_not_run or (not_launched and not ran_a_check):    # nothing ran to a result → cria's own setup gap; stay neutral
        # NOT a pass (never claim clean), NOT a fix request (the model can't fix cria's absent tool),
        # NOT a specific confession — just a non-actionable placeholder so the model relies on itself.
        # Nothing ran to a result, so nothing was lost: the placeholder alone (it is what `_is_no_signal_check` drops from history).
        return finish(CHECKS_MARKER + " " + prompts.load("checks_no_usable_result"), include_not_launched=False)
    # This is evidence, not an authored success verdict. Preserve all completed checker output;
    # only the final wire floor owns size pressure. Scope/zero-test lines must survive even when
    # later discovery metadata changes or a historical transport no longer has its live plan.
    clean = prompts.render("checks_completed", results="\n".join(completed_output))
    # ...but "the checks reported no problems" is half a sentence when NO test ran. g20 (gemma4,
    # ada-handles) returned exactly this line fifty-four times over a project whose unittest classes
    # sat inside resolve_handle.py — unmatched by any naming convention, so no test probe was ever
    # selected — and the completion judge approved on it. The qualifier is a fact about cria's own
    # check (what it looked for, what it found), never a claim that this task needs tests; it stops
    # the moment a matching file exists. Only on the CLEAN branch: where real findings exist the coder
    # has concrete work, and this would be noise on top of it.
    # Keyed on the FILES, not on whether a test command was invoked. A Go project with go.mod and no
    # *_test.go DOES get `go test ./...` — which exits 0 saying "no test files", so the gate reads
    # clean and says nothing. Same vacuous green as g20's Python, reached the other way round. The
    # absence of a test file is the fact either way, and it needs no runner output parsing (cria has
    # no Go/PHP/Ruby toolchain to have verified those strings against).
    untested = list(getattr(plan, "untested", None) or []) if plan is not None else []
    if untested:
        # WHICH SENTENCE IS TRUE depends on whether a test command was composed at all — see
        # prompts/no_tests_found.txt for the run where the wrong one went out over a gate script
        # containing `mvn test`.
        cands = list(getattr(plan, "candidates", None) or [])
        ran_tests = any(c.kind is probediscovery.ProbeKind.Test for c in cands)
        words = prompts.load_map("no_tests_found")
        # NAME WHAT ACTUALLY RAN. The sentence read "the checks above cover syntax and lint only"
        # whatever the plan held — so on a JavaScript project, where the floor is `node --check` and
        # no linter is composed at all, cria claimed a lint pass that never happened. Walked on
        # handles-cli-node x nemotron-elastic 1787348728: the coder shipped a CLI that dies on an
        # undefined variable, `node --check` passed it (a parser cannot see one), the judge read
        # "syntax and lint" as "the code is fine", and the run ended in five minutes. A claim about
        # cria's own coverage is a fact cria holds — it must be read off the plan, never asserted
        # (#12, #5b).
        kinds = {probediscovery.ProbeKind.SyntaxCheck: "syntax",
                 probediscovery.ProbeKind.Lint: "lint",
                 probediscovery.ProbeKind.Typecheck: "type",
                 probediscovery.ProbeKind.BuildCheck: "build",
                 probediscovery.ProbeKind.DependencyCheck: "dependency"}
        ran = [w for k, w in kinds.items() if any(c.kind is k for c in cands)]
        covered = " and ".join([", ".join(ran[:-1]), ran[-1]] if len(ran) > 2 else ran) or "nothing"
        clean += " " + prompts.fill(words["ran_some" if ran_tests else "no_command"],
                                    findings="", covered=covered)
        discovery_observations.extend(untested)
    # WHERE the checks had to run, when none of them could run where the coder is working. A green
    # gate over a project the working directory does not contain is the most expensive green there
    # is — see _checks_ran_elsewhere for the cell it cost.
    if getattr(plan, "ran_in", ""):
        clean += " " + prompts.render("checks_ran_elsewhere", where=plan.ran_in)
    # A suite that passes with the network blocked never touched the API it claims to test. FACT,
    # not verdict (principle 8) — plenty of tasks have no network in them, and which it is here is
    # the judge's call. Only on the CLEAN branch: with real findings the coder already has work.
    offline = _offline_fact(_sections, plan)
    if offline:
        clean += " " + offline
        if plan is not None:
            plan.offline_fact = offline
    for note in _advisory_note(dropped_advisories):
        clean += " " + note
    return finish(clean, include_completed=False)

def _advisory_note(count: int) -> list[str]:
    """cria's own count of what it filtered — one line, or nothing at all.

    A deletion that is not counted is indistinguishable from a check that printed nothing (#R7)."""
    if not count:
        return []
    return [prompts.fill(prompts.load_map("gate_notes")["advisory_dropped"], count=count)]




def gate_passing_tests(report: ProbeReport) -> int:
    """Tool-reported PASSING-test count across this report's Test-kind probes, or -1 when no runner
    printed a tally it recognises.

    Sibling of :func:`gate_ran_tests` and :func:`gate_skipped_count`, and read from the same place:
    the runner's own summary line, via ``runner_tally``, which normalizes twelve runners
    to ``Nf/Np``. -1 rather than 0 for "no tally", so a caller can tell "the runner said nothing"
    from "the runner said zero" — the distinction the completion gate's whole vacuous-green family
    turns on.
    """
    by = gate_passing_by_command(report)
    return sum(by.values()) if by else -1


def gate_passing_by_command(report: ProbeReport) -> dict:
    """Passing-test count per Test-kind probe COMMAND, from each runner's own tally.

    THE SUM IS NOT A SUBJECT. `passing_test_regression` compares this session's high-water tally
    against the current one, and a total over several test commands moves when the SET of commands
    moves — which happens for reasons that have nothing to do with the repo losing a test. A gate
    that ran two test probes and then one reports a collapse the runner never reported.

    Walked on the sub-40 pass, shipping-rates-rb x nemotron-elastic (scored 9): two Test probes
    tallied 7 passing each, the total went 14, a later gate ran one of them, and cria told the coder
    seven passing tests had disappeared. It spent the rest of the run hunting a deleted test that was
    never deleted.

    Keyed by command, each probe is its own subject and its own high-water mark, so the comparison is
    always between two runs of the same command (#12 — the fact comes from the authoritative event,
    and a command is what the runner was reporting about)."""
    if report is None:
        return {}
    kinds = proberun._kind_by_command(report)
    out: dict = {}
    for r in report.results:
        if kinds.get(r.command) is not probediscovery.ProbeKind.Test or r.timed_out:
            continue
        m = re.match(r"(\d+)f/(\d+)p$", r.tally or "")
        if m:
            out[r.command] = out.get(r.command, 0) + int(m.group(2))
    return out

def _offline_fact(sections: dict, plan: "GatePlan | None" = None) -> str:
    """One sentence when the test suite passes with the network taken away — else "".

    TWO signals, and cria only says as much as it has.

    The EXIT CODES gate it. Every test runner on earth exits 0 on pass and non-zero on fail, so exit
    codes read `go test` and `cargo test` — 3 of the suite's 5 task families — exactly as well as
    pytest. That is what let the block go language-agnostic without a tally format per ecosystem.

    The PASSED COUNTS decide how much can be claimed. Exit codes alone are not enough to say "nothing
    in them reaches the real service", because a live test can SKIP instead of fail when the service
    is gone — a two-line try/except that leaves the exit code at 0. Reproduced against a real gate:
    six tests green online, `5 passed, 1 skipped` offline, both exit 0, and the sentence asserted
    that no test touches the service while one of them was hitting it. Operator caught the same hole
    from the other end ("we don't know that all tests are network tests"). So: counts readable on
    both sides and EQUAL → the strong sentence; readable and DIFFERENT → silence, because coverage
    changed and cria cannot tell which half is the truth; not readable → the weaker sentence, which
    claims only what the exit code established.

    ONLY when the suite was GREEN online. Two runs that both FAIL say nothing about mocking — the
    suite is just failing, and on a box with no outbound network the two agree trivially. Caught
    end-to-end while building this: a genuinely live test failed on both sides, the results matched,
    and the draft told the judge the suite never touches the service. That is the false fact rule 5b
    forbids, produced by the very check built to expose one.

    Silent unless cria established it. No offline section (the kernel refused the namespace, so no
    block was applied), no plan to say WHICH probe was the test, a missing sentinel, or any non-zero
    on either side — each one says nothing rather than guess."""
    off = sections.get("offline")
    if not off:
        return ""
    # WHICH probe was the test is a fact the plan holds; without it cria will not guess. The offline
    # leg is composed from this same candidate, so the index is exact, not a search over sections.
    idx = next((i for i, c in enumerate(getattr(plan, "candidates", None) or [])
                if c.kind is probediscovery.ProbeKind.Test), None)
    if idx is None:
        return ""
    online = sections.get(f"probe-{idx}")
    if not online:
        return ""
    online_text, online_code = online
    offline_text, offline_code = off
    if online_code != 0 or offline_code != 0:
        return ""
    on_tally, off_tally = runner_tally(online_text), runner_tally(offline_text)
    # AND THE SKIP COUNT, because for half the fleet the tally cannot move when a test steps aside.
    # The comparison above is the whole mechanism — "a live test can SKIP instead of fail when the
    # service is gone" — and it only works where the total EXCLUDES skips, which is pytest's and
    # jest's convention and nobody else's. minitest's `runs`, phpunit's `Tests:`, surefire's
    # `Tests run:` and gradle's `tests completed` all COUNT the skipped test, so the two tallies
    # match and the strong sentence ships. Reproduced with real ruby, one test that skips when the
    # network is gone:
    #
    #   online  : 2 runs, 2 assertions, 0 failures, 0 errors, 0 skips  -> 0f/2p
    #   offline : 2 runs, 1 assertions, 0 failures, 0 errors, 1 skips  -> 0f/2p   EQUAL
    #
    # and the sentence then reads "nothing in them reaches a service on the internet" about the one
    # test that did not run (#5b). The sentence appears in 5,120 captured prompts. `skipped_count`
    # reads all eight runners' spellings, so asking it is the same question in the dimension the
    # tally cannot see.
    on_skips, off_skips = probeparse.skipped_count(online_text), probeparse.skipped_count(offline_text)
    if on_tally and off_tally:
        if on_tally != off_tally or on_skips != off_skips:
            return ""      # a test stepped aside offline — cria cannot claim the suite is self-contained
        return prompts.render("tests_pass_offline", tally=on_tally)
    if off_skips > on_skips:
        # No readable tally, but the runner still said how many it stepped past, and more of them
        # stepped past offline. That is the same evidence, and it refuses the weaker sentence too.
        return ""
    return prompts.render("tests_pass_offline_uncounted")

def _zero_tests_marker(text: str) -> bool:
    """The runner said it collected nothing — consulted only to decide whether the stranded-test disk
    scan is worth asking for; the scan result, not the marker, is the finding. ONE owner, shared with
    proberun's vacuous-green check, which carried a shorter list of the same phrases (#23)."""
    return probeparse.says_nothing_ran(text)


CHECKS_MARKER = "⟦ctx:checks⟧"
CHECKS_REPEAT_NOTE = (CHECKS_MARKER + " (same result as a later check below — omitted here so the same "
                      "finding isn't repeated across turns)")


def _checks_payload(m) -> tuple[str, str] | None:
    """(key, text) when ``m`` is a ⟦ctx:checks⟧ tool result, else None."""
    if not isinstance(m, dict):
        return None
    key = "content" if m.get("content") is not None else "output"
    c = m.get(key)
    return (key, c) if isinstance(c, str) and c.startswith(CHECKS_MARKER) else None


def _is_no_signal_check(text: str) -> bool:
    """Only our complete placeholder is non-signal; checker quotations remain evidence."""
    return text == CHECKS_MARKER + " " + prompts.load("checks_no_usable_result")


# WHAT THE MODEL MAY SEE OF A GATE, CARRIED AS DATA — not re-derived by matching cria's own text.
#
# A COMMAND THE CODER COULD RETYPE IS WORTH SHOWING; A PROGRAM CRIA WROTE IS NOT. `cargo test`,
# `go vet ./...`, `bundle exec rubocop` come off the project's own tooling and seeing one run is real
# provenance for the finding it produced. The parse floor does not: it is cria's own construction,
# and it is the half that hurt — the TOML check handed a Rust project the Python package `tomli`
# (0/4), and a coder emitted cria's `compileall` line back as its own work. Discovery states which
# is which (`ProbeCandidate.composed_by_cria`); the plan carries only the coder's half (`GatePlan.shown`).
#
# WHICH CALLS ARE CRIA'S OWN GATE is cria's own record, not a property of any text: the projection of a finished gate operation
# (`ops.Ops._project`, from the ledger) marks the assistant message of its call and the tool result that stands for it with
# `AnnotationSource.AUTOMATIC_CHECK`, in process, and puts the typed result on the tool result (`bodykeys.GATE_RESULT`). A command a coder
# types that looks like one is nothing of the kind: a JSON string cannot acquire either.


def is_automatic(m) -> bool:
    """Is this message (an assistant call or its result) cria's own gate, by the in-process mark its projection carries?"""
    return isinstance(m, dict) and m.get(bodykeys.ANNOTATION_SOURCE) is bodykeys.AnnotationSource.AUTOMATIC_CHECK


def _automatic(m) -> bool:
    return isinstance(m, dict) and m.get(bodykeys.ANNOTATION_SOURCE) is bodykeys.AnnotationSource.AUTOMATIC_CHECK


def gate_call_ids(messages: list) -> set:
    """Tool-call IDs of cria's own gate calls: those of the assistant messages the projection of a finished gate marked."""
    return {call["id"] for message in messages
            if isinstance(message, dict) and message.get("role") == "assistant" and _automatic(message)
            for call in message.get("tool_calls") or [] if call.get("id")}


def gate_result_of(message) -> "GateResult | None":
    """The typed result of a finished gate a tool result stands for (only cria's projection puts one there)."""
    found = message.get(bodykeys.GATE_RESULT) if isinstance(message, dict) else None
    return found if isinstance(found, GateResult) else None


def historical_plan(result: GateResult) -> GatePlan:
    """The plan of a gate that is no longer the newest: what rendering a section needs of it (its checks' kind and command, its workspace), from the result."""
    return GatePlan(workspace=result.workspace, op=result.op, result=result, candidates=list(result.facts))


def cria_authored_call_ids(m: dict) -> set:
    """The ids of this turn's tool calls that hold NOTHING: a gate none of whose checks the coder could retype.

    The command was empty and the CALL was left standing, so the model's history read an empty command attributed to the model, answered by cria.
    Measured at 188 prompts, all on 2026-08-22, on the node cell, where every probe is a `node --check` cria composed and so nothing is retypable."""
    if not (_automatic(m) and m.get("role") == "assistant"):
        return set()
    from .toolwire import _command_of
    ids = set()
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        if tc.get("id") and not _command_of(fn.get("arguments")).strip():
            ids.add(tc["id"])
    return ids


def clean_gate_results(messages: list, plan: "GatePlan | None" = None, *,
                       drop_private_results: bool = False, linked_only: bool = False) -> list:
    """Rewrite the gate results of a history (in the model's view) to the cleaned summary. Idempotent; a re-run over already-clean messages
    leaves them untouched. Non-gate messages pass through.

    DROPS non-signal ⟦ctx:checks⟧ turns entirely (with their command call, so nothing orphans — a "no usable result this turn" is pure noise),
    and for provenance-linked gate calls only, COLLAPSES repeats: when the same cleaned ⟦ctx:checks⟧ payload appears more than once, keep only the
    most recent full copy and shorten the earlier identical ones to a one-line back-reference.

    A gate is rendered from the typed result its tool result carries: the newest through the live ``plan`` (every fact the plan holds),
    an older one through the plan its own result rebuilds (its checks and workspace). Older gates stay as readable as they were: the conversation
    holds everything needed even after the session's current plan has moved on. A gate that is UNKNOWN says so, and a newer complete gate in the same
    history makes an older unknown one silence (it contradicted nothing the newer one verified). ``linked_only`` restricts the pass to calls
    cria marked as its own gate."""
    out = []
    gate_ids = gate_call_ids(messages) if linked_only else set()
    drop_ids: set = set()          # tool_call ids whose result we dropped → drop the calling turn too
    # THE CALL WAS CRIA'S AND THE MODEL NEVER MADE IT. When the whole gate is checks cria composed, nothing in its command was the model's,
    # and the empty call used to stay in the model's own history with cria's answer under it. Its RESULT is real ground truth and is kept — as a
    # plain message, which is what it always was.
    own_ids: set = set()
    records = {i: gate_result_of(m) for i, m in enumerate(messages)
               if gate_result_of(m) is not None and (not linked_only or (m.get("tool_call_id") or m.get("call_id")) in gate_ids)}
    states: dict = {}
    for i, found in records.items():
        if plan is not None and plan.op == found.op:
            if plan.result is None:
                adopt(plan, found)
            states[i] = plan
        else:
            states[i] = historical_plan(found)
    last_gate = max(records, default=-1)
    for i, m in enumerate(messages):
        if isinstance(m, dict):
            is_tool = m.get("role") == "tool" or m.get("type") == "function_call_output"
            key = "content" if m.get("content") is not None else "output"
            c = m.get(key)
            if is_tool and i in records:
                tid = m.get("tool_call_id") or m.get("call_id")
                state = states[i]
                plain = {k: v for k, v in m.items() if k != bodykeys.GATE_RESULT}
                if state.complete:
                    c = clean_gate_output(
                        state, annotate=(i == last_gate),
                        changed_paths=_paths_written_after(messages, i) if i == last_gate else frozenset(),
                        a_command_ran_since=(i == last_gate and _a_command_could_have_changed_things_after(messages, i)),
                        checks_reran=(i == last_gate and _probe_reran_after_last_change(messages, i, plan)))
                elif any(j > i and states[j].complete for j in records):
                    # An OLDER gate whose evidence never arrived whole cannot be verified — but a NEWER gate in this very history did verify, and says
                    # what the repo's checks say now. "UNKNOWN" about the superseded run, set beside the complete failing result of the next one, read
                    # as a contradiction (phi4 A2 calls 0031/0037/0043). Only the NEWEST gate's unknown-ness is a fact about the present, so this
                    # one is silence — not "clean": it contributes no result at all, and the newest gate below is untouched.
                    c = None
                else:
                    c = transport_unknown_text(state.reported)
                if c is None or _is_no_signal_check(c):
                    if tid:
                        drop_ids.add(tid)
                    continue
                if tid in own_ids:
                    out.append({"role": "user", "content": c, **(
                        {bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.AUTOMATIC_CHECK} if _automatic(m) else {})})
                else:
                    out.append({**plain, key: c})
                continue
            if drop_private_results and is_tool and (m.get("tool_call_id") or m.get("call_id")) in own_ids:
                drop_ids.add(m.get("tool_call_id") or m.get("call_id"))
                continue
            if m.get("role") == "assistant" and m.get("tool_calls"):
                empties = cria_authored_call_ids(m)
                if empties and len(m["tool_calls"]) == len(empties):
                    own_ids |= empties
                    continue
        out.append(m)
    if drop_ids:  # remove the assistant call(s) whose only result was a dropped no-signal gate probe
        out = [m for m in out if not (isinstance(m, dict) and m.get("role") == "assistant"
               and m.get("tool_calls") and len(m["tool_calls"]) == 1
               and (m["tool_calls"][0].get("id") in drop_ids))]
    if not linked_only:
        return out
    # Keyed on dedup.volatile_key, NOT the raw payload. Two renderings of the same stamped gate
    # finding differ by per-run noise the finding does not depend on, and keying on bytes meant the
    # collapse never fired for them. mellum2 1786051505 carried
    # `resolve_handle.py:92: undefined name 'pytest'` THREE times in one coder prompt — on
    # a file the coder had since cut to 7 lines, so it was hunting a line that no longer existed — and
    # the three copies differed only by a `<urllib.request.Request object at 0x…>` address and
    # `in 0.36s` vs `in 0.28s`.
    def is_gate_check(message: dict) -> bool:
        return (message.get("tool_call_id") or message.get("call_id")) in gate_ids

    last_of: dict[str, int] = {}
    for i, m in enumerate(out):
        p = _checks_payload(m)
        if p is not None and is_gate_check(m):
            last_of[dedup.volatile_key(p[1])] = i
    if any(idx != last_of[dedup.volatile_key(_checks_payload(out[idx])[1])]
           for idx, m in enumerate(out)
           if _checks_payload(m) is not None and is_gate_check(m)):
        for i, m in enumerate(out):
            p = _checks_payload(m)
            if p is not None and is_gate_check(m) and last_of[dedup.volatile_key(p[1])] != i:
                out[i] = {**m, p[0]: CHECKS_REPEAT_NOTE}
    return out


def check_evidence_messages(messages: list, plan: "GatePlan | None" = None) -> list:
    """Keep automatic checks as observations, never actions attributed to the coder.

    The ordinary coder view retains retypable probe commands. A reasoner judging
    progress must also retain who requested them: a green automatic gate after a
    refused action is not a successful action chosen by the coder. Capture ownership
    before cleaning removes the marks; an unmarked identical command stays a
    coder action. Results retain the existing cleaner's exact rendering. The internal
    observation role is consumed by selfcompact.serialize, never sent as a wire role.
    """
    automatic = gate_call_ids(messages)
    cleaned = clean_gate_results(messages, plan)
    if not automatic:
        return cleaned
    out = []
    for message in cleaned:
        calls = message.get("tool_calls") or []
        if message.get("role") == "assistant" and any(c.get("id") in automatic for c in calls):
            if message.get("content"):
                out.append({**message, "tool_calls": []})
            for call in calls:
                if call.get("id") not in automatic:
                    out.append({**message, "content": "", "tool_calls": [call]})
                    continue
                args = jsontext.loads(call["function"]["arguments"])
                command = args.get("cmd", args.get("command", ""))
                if isinstance(command, list):
                    command = "\n".join(str(part) for part in command)
                out.append({"role": "observation", "content": prompts.render(
                    "automatic_check_request", command=command)})
            continue
        identity = message.get("tool_call_id") or message.get("call_id")
        if identity in automatic and (message.get("role") == "tool"
                                      or message.get("type") == "function_call_output"):
            out.append({"role": "observation", "content": prompts.render(
                "automatic_check_result", result=message.get("content", message.get("output", "")))})
        else:
            out.append(message)
    return out


def cleanup_fact(plan: "GatePlan | None") -> str:
    """Keep the gate's own mutation facts separate from native checker lines."""
    record = cleanup_of(plan)
    if record is None:
        return ""                  # a result with no report says nothing about one (a gate cria ran always has it)
    removed, failed = record
    notes = [prompts.load('checks_original_scope')]
    # THE REPORT'S RELATIVE PATHS ARE RELATIVE TO THE PRIVATE SCRATCH DIRECTORY, and every line says so.
    # They were rendered bare (`"aux/"`), which reads as the workspace's own aux/: run 20261027T035849
    # kept its scratch in a workspace aux/, the coder concluded the checker had deleted it (0064, 0097)
    # and a FAITHFUL briefing told it so (0067, carried into the 0084 refold) while the same evidence
    # showed those files still being read. An absolute path (a checked scope directory) is unambiguous
    # and is stated as it is. The exact path text stays JSON-quoted.
    line = prompts.load_map("checks_cleanup_paths")
    if removed:
        notes.append(prompts.render("checks_artifacts_removed", paths="\n".join(
            prompts.fill(line["removed"], path=json.dumps(path)) for path in removed)))
    if failed:
        notes.append(prompts.render("checks_cleanup_failed", failures="\n".join(
            prompts.fill(line["failed_absolute" if os.path.isabs(item["path"]) else "failed_private"],
                         path=json.dumps(item["path"]), error=json.dumps(item["error"]))
            for item in failed)))
    return "\n" + "\n".join(notes) if notes else ""


def sweep_litter(plan: GatePlan) -> list[str]:
    """What the run reclaimed of its private scratch (paths relative to it), as the gate reported it; nothing is removed here."""
    record = cleanup_of(plan)
    root = getattr(plan, "workspace", "") or ""
    if record is None or not root:
        return []
    removed: list[str] = []
    for rel in record[0]:
        # This is only report validation: the removal was the harness's, on the directory cria named.
        if not rel or os.path.isabs(rel) or dirguard.is_external(rel, root):
            continue
        removed.append(rel)
    return removed


def unsettled_text(outcome) -> str:
    """The notice for write calls this gate could not account for (``GateOutcome.unsettled_writes``): which files, and which of the
    the fact left open. Built from the ledger's own record and the call's target path - no judgment, no model."""
    items = list(getattr(outcome, "unsettled_writes", None) or [])
    if not items:
        return ""
    fills = prompts.load_map("gate_unsettled_writes")
    paths = list(dict.fromkeys(path for _receipt, path, _state in items if path))
    named = ", ".join(f"`{p}`" for p in paths) if paths else "an earlier file write"
    lead = prompts.fill(fills["lead"], paths=named)
    return " ".join((lead, fills["unknown"], fills["tail"]))


def transport_unknown_text(reported: str = "") -> str:
    """The notice for a check whose evidence did not arrive. When the harness said why, its own last line rides along
    verbatim (selected from what it printed, never paraphrased) so the coder can act on the real cause."""
    base = prompts.load("probe_transport_unknown")
    return f"{base}\n{prompts.render('probe_transport_reported', reported=reported)}" if reported else base

def interpret_gate(plan: GatePlan, result: "GateResult | None" = None, rlog=None) -> GateOutcome:
    """Replay the gate's result through the ported interpreters. ``result`` is what the gate's operation learned (``None``: ask the plan what it
    holds - nothing yet means the gate is still running)."""
    state = adopt(plan, result) if result is not None else ("unknown" if plan.error else "complete" if plan.complete else adopt(plan, plan.result))
    if state == "pending":
        return GateOutcome(ran=False, transport_pending=True)
    if state == "unknown":
        if rlog is not None:
            rlog.emit("gate.transport_unknown", level="warn", reason=plan.error)
        return GateOutcome(ran=False, transport_unknown=True, transport_reported=plan.reported, refused=plan.refused)
    sections = sections_of(plan)
    unsettled = unsettled_writes(plan)
    if unsettled and rlog is not None:
        rlog.emit("gate.writes_unsettled", level="warn", count=len(unsettled),
                  states=sorted({state for _r, _p, state in unsettled}))
    cleanup_record = cleanup_of(plan)
    scope_unknown = bool(cleanup_record is None or cleanup_record[1])
    if scope_unknown:
        wsview.current().note_unknown_mutation()
    # THE SURVEY IS CRIA'S OWN OPERATION (`cria.surveyops`), asked while the checks ran and again after them (`plan_gate` wants one):
    # the view holds what it delivered by the time this result is read.
    survey_applied = bool(wsview.current().surveyed)
    # THE PLAN WAS COMPOSED BLIND TO A MANIFEST THIS SURVEY JUST DELIVERED. After any command that could have
    # changed the tree, no held body is current, so discovery found no `rake test` / `npm test` and the gate ran only
    # syntax checks; the survey carries the very bodies discovery asked for. Selection is
    # deterministic, so ask it again now: if the checks differ, this gate verified less than it should have.
    survey_changes_plan = bool(
        survey_applied and plan.unanswered_reads and plan.workspace
        and _plan_signature(proberun.select_completion_probes(plan.workspace)) != _plan_signature(plan.candidates))
    replan_after_survey = bool(survey_applied and (not plan.surveyed_before or survey_changes_plan))
    participation_events = []
    # Read the harness's completed cleanup record, including when checks failed.
    swept = sweep_litter(plan)
    # ran is TRUE only if an actual check section came back. An empty / no-code repo yields zero candidates;
    # treating that as "ran" made guard_ground_truth emit a clean "no error-class problems" verdict when NO check
    # actually ran. No probe-* section → ran=False → silence, not a false pass.
    if not any(k.startswith("probe-") for k in sections):
        participation_events = [participation.observe(c, "", None, event_missing=True)
                                for c in plan.candidates]
        plan.participation = participation.report(participation_events)
        return GateOutcome(
            ran=False,
            replan_after_survey=replan_after_survey,
            participation=plan.participation,
            scope_unknown=scope_unknown,
            unsettled_writes=unsettled,
        )
    out = GateOutcome(ran=True, swept=swept, scope_unknown=scope_unknown, unsettled_writes=unsettled,
                      replan_after_survey=survey_changes_plan)

    results = []
    for i, c in enumerate(plan.candidates):
        found = sections.get(f"probe-{i}")
        if found is None:
            # Never ran — the run was cut short or the check's output never came back.
            # Absence must not BLOCK, but it must not read as CLEAN either: `results` silently became a
            # subset of `selected`, and nothing downstream said a check was missing, so a cut gate
            # looked like a passing one. Record the gap so the digest can report it.
            out.unran.append(proberun.display_command(c.command))
            participation_events.append(participation.observe(c, "", None, event_missing=True))
            continue
        raw, code = found
        if code == proberun.NOT_FOUND_EXIT_CODE and c.composed_by_cria:
            # THE GATE'S OWN 127 IS GROUND TRUTH ABOUT THE CODER'S SHELL, for a tool cria composed to launch directly (an
            # eslint/pyflakes/node floor probe): remember it so the next gate does not compose the same absent tool.
            wsview.current().note_program_absent(proberun._head_program(c.command))
        result = proberun.interpret_probe_output(
            c, proberun.display_command(c.command), raw, code, COMPLETION_PROBE_TIMEOUT_S)
        results.append(result)
        participation_events.append(participation.observe(
            c, raw, code, findings=result.findings))
    out.report = ProbeReport(project_type=[], selected=list(plan.candidates), results=results)
    out.participation = participation.report(participation_events)
    plan.participation = out.participation

    if any(c.kind is probediscovery.ProbeKind.Test for c in plan.candidates):
        out.offline_ran = "offline" in sections

    return out
