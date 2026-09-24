"""The completion gate's transport: the HARNESS runs and spools one complete script,
then pages its bytes back for the existing probe parsers — cria owns no executors.

The gate is CONGRUENT across ecosystems (operator direction): there is no privileged
per-language floor anymore. ``proberun.select_completion_probes`` returns one ranked
candidate list — tier-0 parse/compile checks for every language present (compileall,
node --check, php -l, ruby -c by file presence; cargo check / go build / tsc /
mvn-gradle compile / dotnet build / mix compile via their ecosystems' tier≤1
candidates) plus the top-ranked probe and the top TEST probe. This module:

* :func:`plan_gate` — select the candidates (READ-ONLY workspace inspection) and
  compose one marker-delimited script: each candidate via
  :func:`cria.proberun.compose_probe_command` (timeout-bounded, uncut,
  EXIT-sentineled). The combined stream is written to a temporary file on the
  harness machine and returned in checked pages over later request/response turns.
  The plan REMEMBERS what it composed so interpretation doesn't re-inspect a
  possibly-changed world.
* :func:`interpret_gate` — split the harness's result into sections and map each onto
  the upstream ProbeResult contract (:func:`cria.proberun.interpret_probe_output`):
  timeout → 124, launch failure → 127/"command not found", findings via the per-tool
  parsers (tier-0 checks included — every ecosystem's parse floor yields file:line).

Only a complete byte count plus SHA-256 is handed to the existing section parser.
A missing, cut, reordered, or malformed transport page is explicit UNKNOWN and can
never become a clean gate.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shlex
import time
from dataclasses import dataclass, field

from . import dirguard, dedup, jsontext, wsview
from . import participation, probediscovery, probeparse, prompts, proberun

# Leading ``path:line[:col][:]`` location prefix a linter prints before the diagnostic. Stripping it
# lets probeparse.is_advisory's ANCHORED style-code check (``^W###``/``E###``…) fire on a raw gate
# line — its phrase check is substring so it already works either way.
_LOC_PREFIX = re.compile(r"^\S.*?:\d+(?::\d+)?:?\s+")

from .proberun import ProbeReport
# runner_tally lives in probeparse now (it parses runner OUTPUT, and the tally must be taken at
# parse time while the raw text still exists). Re-exported so existing callers are unmoved.
from .probeparse import COMPILES_FIRST, runner_and_tally, runner_tally  # noqa: F401

# Marker line delimiting each section of the composed script's output. The id after the
# prefix names the section ("probe-0", "git"). Chosen to never collide with tool output.
SECTION_PREFIX = "___CRIA_GATE_"
SECTION_SUFFIX = "___"
# Section carrying the untracked paths the probes themselves created — cria's own litter, listed by the
# harness's shell and removed by :func:`sweep_litter` on cria's side. A signal for cria, never the model.
LITTER_SECTION = "litter"
# Per-probe wall-clock bound. Was 45 s (codex-local's COMPLETION_PROBE_TIMEOUT), which is fine for a
# syntax floor and far too short for what this gate actually selects: a full test suite, a cold
# `cargo check`, a `tsc` build. That is not merely a slow gate — `completion_block_nudge` fails CLOSED
# on a timed-out hard-failure probe, so a repo whose tests take a minute is permanently
# un-completable: every round re-nudges with "TIMEOUT after 45s" and no edit can ever clear it.
COMPLETION_PROBE_TIMEOUT_S = 240.0

# The raw gate may be arbitrarily larger than one harness result. The harness keeps it in a
# temporary file OUTSIDE the workspace and returns one base64 page per request. 6,000 raw bytes
# encode to 8,000 characters, leaving room for the harness envelope under the observed ~9–10 KiB
# result boundary. This is a TRANSPORT page size, not an evidence budget: every page is requested.
TRANSPORT_CHUNK_BYTES = 6_000
TRANSPORT_PREFIX = "___CRIA_GATE_TRANSPORT_"
TRANSPORT_SUFFIX = "___"
TRANSPORT_END_PREFIX = "___CRIA_GATE_TRANSPORT_END_"
_TRANSPORT_HEREDOC = "__CRIA_GATE_TRANSPORT_PY__"

# C28: a harness exec's DEFAULT yield does not have to honor the 300s budget `with_time_budget`
# asks for (Codex clamped/returned early at ~10s in the captured incident, mid-pytest, with no
# transport opener at all — `inbound-ce7f6c3d-responses.json`, session 01a0d2c3). So the composed
# probe block now runs DETACHED (see `_gate_launch_guard`) and this is merely how long ONE read of
# it waits for a completion marker before answering with a typed "still running" envelope instead of
# silently going empty-handed. Kept safely under the observed ~10s default so the reader's OWN typed
# envelope — running or complete — has time to print before the harness's yield can cut it too.
GATE_POLL_WAIT_S = 8.0

# The cria-side deadline for the WHOLE detached block, derived from the plan's OWN composed
# timeouts, never guessed: every selected probe (and the offline re-run leg, when present) is
# individually bounded by `timeout -k {TIMEOUT_KILL_GRACE_S} {COMPLETION_PROBE_TIMEOUT_S}` inside
# the block and they run SERIALLY, so the worst legitimate case is their sum. The slack absorbs the
# git/litter/survey bookkeeping that isn't under any single probe's own timeout. Exceeding this is
# the ONLY way a running gate becomes terminal UNKNOWN (fail closed, #13) — every other malformed/
# cut/hash/offset check is unchanged.
GATE_DEADLINE_SLACK_S = 60.0

# Supervisor review: the plan-wide deadline (minutes) is the RIGHT bound for a check that is
# genuinely still running \u2014 the reader answers within GATE_POLL_WAIT_S every time, so a typed
# `running` envelope is trustworthy evidence of life. An OPENERLESS result is different: the reader
# always answers inside GATE_POLL_WAIT_S (well under the harness's own yield), so getting NOTHING
# recognizable back means the poll itself was cut, or the reader could not even run (no `python3`,
# a sandbox rejection `refusal_reason` doesn't recognise). That is a channel fact, not a liveness
# fact, and letting it ride the multi-minute deadline would silently retry a genuinely broken
# channel for ~100 cria-only turns before ever saying so. Bounded separately and small: covers the
# captured P18 launch shape (one openerless read) plus one cut poll, and resets the instant a real
# envelope (running or a page) arrives.
GATE_OPENERLESS_MAX = 2


def _transport_marker(transport_id: str, *, end: bool = False) -> str:
    prefix = TRANSPORT_END_PREFIX if end else TRANSPORT_PREFIX
    return f"{prefix}{transport_id}{TRANSPORT_SUFFIX}"


def _transport_reader(path_arg: str, offset: int, transport_id: str, *,
                      wait_s: float = GATE_POLL_WAIT_S) -> str:
    """Harness-side page reader. ``path_arg`` is a shell expression or quoted path.

    Waits up to ``wait_s`` for the sibling ``.done`` marker the detached probe block writes when it
    finishes (see :func:`_gate_launch_guard`) before deciding what to answer: DONE → the existing
    page (unchanged shape: path/offset/total/sha256/data). NOT DONE → a typed "running" envelope
    (same opener/closer, never a data field) so the harness's OWN result always carries a real
    envelope instead of going back empty — the exact P18 shape ("Process running … Output:", no
    marker at all) that made `ingest_transport` terminal on a check that was still alive.

    The final page is read into the helper's memory before the temporary file (and its ``.done``
    marker) is unlinked. If its result is cut in transit, cria sees a missing close/count/hash and
    reports UNKNOWN; it never interprets the prefix as a complete check. Normal completion leaves no
    harness-side artifact.
    """
    program = f'''import base64, hashlib, os, sys, time
path = sys.argv[1]
offset = int(sys.argv[2])
opening = {_transport_marker(transport_id)!r}
closing = {_transport_marker(transport_id, end=True)!r}
done_path = path + ".done"
deadline = time.monotonic() + {wait_s!r}
while not os.path.exists(done_path) and time.monotonic() < deadline:
    time.sleep(0.2)
if not os.path.exists(done_path):
    try:
        started = os.path.getctime(path)
        elapsed = max(0.0, time.time() - started)
    except OSError:
        elapsed = 0.0
    print(opening)
    print("running\\t" + str(round(elapsed, 1)))
    print(closing)
    sys.exit(0)
try:
    total = os.path.getsize(path)
    if offset < 0 or offset > total:
        raise ValueError("offset outside spool")
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
        source.seek(offset)
        chunk = source.read({TRANSPORT_CHUNK_BYTES})
    final = offset + len(chunk) == total
    if final:
        os.unlink(path)
        try:
            os.unlink(done_path)
        except OSError:
            pass
    print(opening)
    print("path\\t" + base64.b64encode(path.encode()).decode())
    print("offset\\t" + str(offset))
    print("total\\t" + str(total))
    print("sha256\\t" + digest.hexdigest())
    print("data\\t" + base64.b64encode(chunk).decode())
    print(closing)
except Exception as exc:
    print(opening)
    print("error\\t" + base64.b64encode(str(exc).encode()).decode())
    print(closing)
'''
    return (f"python3 - {path_arg} {offset} <<'{_TRANSPORT_HEREDOC}'\n"
            f"{program}{_TRANSPORT_HEREDOC}")


def _gate_launch_guard(spool_arg: str, cmd_arg: str, parts: list[str]) -> list[str]:
    """The lines that start the composed probe block DETACHED, idempotently.

    Written to run BEFORE the offset-0 :func:`_transport_reader` call, guarded so re-sending this
    exact block (cria's own retry when it has learned nothing yet — see
    :func:`continue_transport_command`) never launches a second copy: if the spool or its ``.done``
    marker already exists, the probes are already running or already finished and this leg is a
    no-op.

    DETACHED so the harness's own exec yield only bounds the READ, never the check: `setsid` (when
    on PATH) puts the block in a new session with no controlling terminal, so it outlives the harness
    reaping this call's process group; a plain background job is the fallback. Both the launched
    command's own I/O and the surrounding group's are redirected to ``/dev/null``/the spool — an
    inherited pipe end left open in a still-running detached child is exactly what would hang the
    NEXT read of this same call (or a test's `subprocess.run(capture_output=True)`).

    EVERYTHING AFTER THE PROBE BLOCK MUST RUN INSIDE THE SAME DETACHED SESSION TOO — not just the
    probe block itself. The first shape of this function put `setsid` in front of only the probe
    invocation, inside a `( setsid sh cmd ; : > done ; python3 -c unlink ) &` wrapper: `setsid`
    detaches the probe, but the surrounding `( … )` subshell that WAITS for it and then writes the
    ``.done`` marker and unlinks the cmd file stays a member of the HARNESS's own process group. A
    harness that reaps that process group the instant the exec call returns (reproduced on real
    Codex 0.156 against a 14s probe: the spool filled with the probe's own real output, but
    ``.done`` never appeared and the cmd file was never removed) kills that waiting subshell before
    it ever writes the marker — so a gate that used to finish INLINE within the old yield now polls
    all the way to `transport_deadline_s` and ends terminal UNKNOWN, worse than before C28. The fix
    is to make the WHOLE sequence — run, mark done, clean up — the single command `setsid` (or the
    plain fallback) detaches: `$__cria_gate_run -c '<run, mark, clean>' … &`, using `$0` inside that
    inline script for the interpreter name so it is named only once.

    INTERPRETER: `bash` when it is on PATH, else `sh`. Before C28 `parts` ran inline in whatever
    shell the HARNESS itself used to run the whole composed script — Codex's own exec tool is
    `bash -lc`, and probe composition (`proberun.compose_probe_command`, the offline `unshare` leg,
    `wsview.survey_command`) was never written against POSIX `sh` specifically. Detaching into a
    bare `sh` would swap that shell out from under commands that happened to work only because bash
    was running them — a silent behavior change with no `test_gate_script_is_read_only.py`-style
    guard to catch it, since `sh` is frequently a bash symlink on the very machine that would hide
    the regression. `setsid` and the interpreter choice are independent knobs (either may be absent).

    `umask 077` around ONLY the file creation, then RESTORED before the detached launch: the spool
    carries the coder's own check output and the cmd file the composed probe commands, and
    `mktemp`'s own default (owner-only, 0600) is what this replaced — a fixed deterministic name
    must not widen that. But a umask is PROCESS-WIDE and inherited by children: a bare `umask 077`
    with no restore leaked into the detached session and every probe it runs, silently narrowing the
    mode of every file the repo's OWN checks create in the coder's workspace (reviewer evidence: a
    probe's own `umask` printed 0077 instead of the harness's 0022 on real Codex; a check asserting
    an output file's mode 0644 went from green to red). The harness's umask is saved before the
    narrowing and restored immediately after both files exist, so only cria's OWN two files are
    affected and the detached session — hence every probe — inherits the harness's original umask
    unchanged, exactly as it did before C28.

    No `rm`: the Codex sandbox rejects the WHOLE script when it contains one
    (test_gate_script_is_read_only.py); cleanup is `os.unlink` — the launch script unlinks itself
    once the block is done, exactly like the spool is unlinked by the final page read.
    """
    body = "\n".join(parts) if parts else ":"
    tag = "__CRIA_GATE_BODY__"
    # Run the probe body via `$0` (the interpreter name passed as $0 below) so it is named once;
    # then, in the SAME process/session, mark done and unlink the cmd file. All three legs are one
    # `sh -c '…'` argument, so `setsid` (or its absence) covers every one of them, not just the
    # first.
    detached = ('$0 "$1" </dev/null >"$2" 2>&1; : > "$2.done"; '
               'python3 -c "import os, sys; os.unlink(sys.argv[1])" "$1" >/dev/null 2>&1')
    return [
        f"if [ ! -e {spool_arg} ] && [ ! -e {spool_arg}.done ]; then",
        "__cria_gate_umask=$(umask)",
        "umask 077",
        f": > {spool_arg} || exit 98",
        f"cat > {cmd_arg} <<'{tag}'",
        body,
        tag,
        'umask "$__cria_gate_umask"',
        'if command -v bash >/dev/null 2>&1; then __cria_gate_sh="bash"; '
        'else __cria_gate_sh="sh"; fi',
        'if command -v setsid >/dev/null 2>&1; then __cria_gate_run="setsid $__cria_gate_sh"; '
        'else __cria_gate_run="$__cria_gate_sh"; fi',
        f'$__cria_gate_run -c \'{detached}\' "$__cria_gate_sh" {cmd_arg} {spool_arg} '
        f'</dev/null >/dev/null 2>&1 &',
        "disown 2>/dev/null || true",
        "fi",
    ]


@dataclass
class GatePlan:
    """Everything :func:`interpret_gate` needs to replay the output faithfully."""

    workspace: str
    # Probe discovery reads the session-scoped workspace view, never cria's local filesystem.  On
    # the first gate that view may still be empty, so the plan contains no candidates and its only
    # useful result is the survey appended below.  The reader needs to retain that provenance: once
    # the survey lands, this plan is obsolete and a newly discovered gate must run before completion.
    surveyed_before: bool = False
    script: str = ""
    candidates: list = field(default_factory=list)  # selected ProbeCandidates, in section order
    # Test-naming conventions cria searched by and found nothing for (probediscovery.undiscoverable_tests).
    # Computed with the selection, so the clean-gate render reads a fact instead of re-walking the tree.
    untested: list = field(default_factory=list)
    # The subdirectory every real probe had to be run in, when NONE of them could run at the
    # workspace root — "" in the ordinary case. See :func:`_checks_ran_elsewhere`.
    ran_in: str = ""
    # cria-facing observations about the PLAN itself (not about the repo).
    notes: list = field(default_factory=list)
    # Lossless asynchronous transport state. The path names the HARNESS-side spool and is learned
    # only from its first response; cria never opens it. Bytes accumulate in session-scoped plan
    # state until the declared total and hash both verify. Any protocol gap is terminal UNKNOWN.
    transport_required: bool = False
    transport_id: str = field(default_factory=lambda: secrets.token_hex(12))
    transport_path: str = ""
    transport_total: int | None = None
    transport_sha256: str = ""
    transport_data: bytearray = field(default_factory=bytearray)
    transport_complete: bool = False
    transport_error: str = ""
    # C28: the cria-side wall-clock this plan was composed at, and the deadline (in seconds from
    # there) past which a still-"running" transport becomes terminal UNKNOWN rather than being
    # retried forever. `plan_gate` sets `transport_deadline_s` from the plan's own probe timeouts;
    # left at 0.0 (e.g. a hand-built plan in a test, or historical replay in `clean_gate_results`)
    # a running transport is retried without ever timing out on its own — those callers only care
    # whether replay ever reached `transport_complete`, not how long it took.
    transport_started: float = field(default_factory=time.monotonic)
    transport_deadline_s: float = 0.0
    # Consecutive OPENERLESS reads (no envelope at all, not even a typed `running` one) since the
    # last real envelope. Bounded by `GATE_OPENERLESS_MAX`, independently of `transport_deadline_s`
    # \u2014 see the constant's own comment for why the two must not share a bound.
    transport_openerless_streak: int = 0
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


@dataclass
class GateOutcome:
    ran: bool = False  # False → no markers came back; keep don't-wedge semantics
    report: ProbeReport | None = None
    unran: list = field(default_factory=list)  # selected checks whose section never came back — a GAP,
    #                                            not a pass: without this, a truncated gate read clean
    refused: str = ""  # the harness REFUSED to run the gate (sandbox policy) — its own words, for the log
    swept: list = field(default_factory=list)  # untracked paths the probes created, removed by sweep_litter
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
    transport_pending: bool = False  # more checked pages are required before parsing
    transport_unknown: bool = False  # transport ended incomplete/invalid; never a clean result


def _marker(section_id: str) -> str:
    return f"{SECTION_PREFIX}{section_id}{SECTION_SUFFIX}"


def fail_transport(plan: GatePlan, reason: str) -> str:
    """Make this gate's transport terminally UNKNOWN."""
    plan.transport_error = reason
    plan.transport_complete = False
    return "unknown"


def _gate_deadline_s(candidate_count: int) -> float:
    """The cria-side deadline (seconds) for a detached gate block with this many timed probes."""
    per = COMPLETION_PROBE_TIMEOUT_S + proberun.TIMEOUT_KILL_GRACE_S
    return max(candidate_count, 1) * per + GATE_DEADLINE_SLACK_S


def _retry_or_deadline(plan: GatePlan, now: float | None) -> str:
    """``running`` while the plan's own cria-side deadline hasn't passed, else terminal UNKNOWN.

    Shared by two shapes of "the check is still going": the reader's own typed ``running`` envelope,
    and total silence (no opener at all — the captured P18 shape, `inbound-ce7f6c3d-responses.json`:
    a harness exec yield that cut the WHOLE call before the reader printed a byte). Both are read-only
    and idempotent to retry, so neither is made terminal on its own; only running out of the plan's
    own composed timeout budget is (fail closed, #13, with an honest reason — never silently clean).
    """
    elapsed = (now if now is not None else time.monotonic()) - plan.transport_started
    if plan.transport_deadline_s and elapsed > plan.transport_deadline_s:
        return fail_transport(
            plan, "the check exceeded its own composed timeout budget while still running")
    return "running"


def ingest_transport(plan: GatePlan, result_text: str, *, now: float | None = None) -> str:
    """Ingest one harness-returned page: ``pending``, ``running``, ``complete``, ``unknown`` or
    ``legacy``.

    No prefix is ever parsed as evidence. A page is accepted only when both envelope markers are
    present, all fields occur exactly once, its offset is the next byte cria needs, its path/total/
    hash agree with earlier pages, and the decoded chunk stays inside the declared total. Only the
    complete byte string is eligible for :func:`split_sections`.

    ``running`` (C28) is NON-TERMINAL: the detached probe block hasn't finished yet (or the harness
    cut this particular poll before it could say so). It is retried — see
    :func:`cria.loop.guard_gate_transport` — until either a real page arrives or
    :func:`_gate_deadline_s` is exceeded, at which point it becomes terminal UNKNOWN.

    ``legacy`` preserves old gate results already present in a conversation and hand-built parser
    fixtures. A newly composed transport never emits raw section markers outside its base64 page.
    """
    if not plan.transport_required:
        return "legacy"
    if plan.transport_complete:
        return "complete"
    if plan.transport_error:
        return "unknown"
    # Raw marker-delimited results predate this transport and remain readable from history. The
    # current script redirects every such marker into the spool, so a live page cannot take this arm.
    if SECTION_PREFIX in (result_text or "") and TRANSPORT_PREFIX not in (result_text or ""):
        return "legacy"
    opening = _transport_marker(plan.transport_id)
    closing = _transport_marker(plan.transport_id, end=True)
    text = result_text or ""
    start = text.find(opening)
    if start < 0:
        if not text.strip() or refusal_reason(text):
            # GENUINELY ABSENT (no tool message answered this call at all — the harness declined
            # this turn, or a caller asks before any result could exist) and an explicit REFUSAL
            # (the harness's OWN words for why it would not even attempt the script — already
            # vetted, generic sandbox/permission phrasing reused from `refusal_reason`, not a new
            # runner/language keying) are the SAME fact: nothing was ever launched. That is the
            # pre-existing fail-open contract every caller already has — terminal UNKNOWN, not a
            # retry — and stays exactly as it was before C28.
            return fail_transport(plan, "transport page opener did not arrive")
        # A REAL, non-empty reply that still carries no envelope and no refusal wording is the exact
        # P18 shape (`inbound-ce7f6c3d-responses.json`: "Wall time: 30.0008 seconds\nProcess running
        # …") — the harness's own exec yield cut the call before the reader printed a byte. Read-only
        # and idempotent to retry, so this is the ONE existing failure this candidate softens — but
        # ONLY up to GATE_OPENERLESS_MAX consecutive times (see its own comment): the reader answers
        # within GATE_POLL_WAIT_S every time, so repeated total silence means the poll itself is
        # broken, not that the check is merely slow, and that must not ride the multi-minute deadline.
        plan.transport_openerless_streak += 1
        if plan.transport_openerless_streak > GATE_OPENERLESS_MAX:
            return fail_transport(
                plan, "transport page opener did not arrive, repeatedly — the poll itself is broken")
        return _retry_or_deadline(plan, now)
    end = text.find(closing, start + len(opening))
    if end < 0:
        return fail_transport(plan, "transport page was cut before its closing marker")
    if text.count(opening) != 1 or text.count(closing) != 1:
        return fail_transport(plan, "transport page contains duplicate envelope markers")
    body = text[start + len(opening):end].strip("\r\n")
    fields: dict[str, str] = {}
    for line in body.splitlines():
        key, sep, value = line.partition("\t")
        if not sep or key in fields:
            return fail_transport(plan, "transport page contains malformed or duplicate fields")
        fields[key] = value
    if set(fields) == {"running"}:
        # The reader's own typed envelope: it waited, the completion marker still wasn't there, and it
        # said so instead of returning nothing. Never data — bounded by the plan-wide deadline, not
        # the openerless streak: THE POLL ITSELF WORKED (it printed a real envelope), so this is
        # genuine evidence of life, not a broken channel.
        plan.transport_openerless_streak = 0
        return _retry_or_deadline(plan, now)
    if "error" in fields:
        try:
            detail = base64.b64decode(fields["error"], validate=True).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — an unreadable error is still a transport failure
            detail = "harness-side page reader failed"
        return fail_transport(plan, detail)
    if set(fields) != {"path", "offset", "total", "sha256", "data"}:
        return fail_transport(plan, "transport page is missing required fields")
    # A REAL page envelope arrived \u2014 the poll channel works, whatever this page's own contents
    # turn out to validate to below. Reset the openerless streak here, not only on eventual success.
    plan.transport_openerless_streak = 0
    try:
        path = base64.b64decode(fields["path"], validate=True).decode("utf-8")
        offset, total = int(fields["offset"]), int(fields["total"])
        chunk = base64.b64decode(fields["data"], validate=True)
    except (ValueError, UnicodeError):
        return fail_transport(plan, "transport page contains undecodable fields")
    digest = fields["sha256"].lower()
    if (not path or "\x00" in path or "\n" in path or "\r" in path
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        return fail_transport(plan, "transport page path or hash is invalid")
    expected_name = f".cria-gate-{plan.transport_id}."
    if not os.path.basename(path).startswith(expected_name):
        return fail_transport(plan, "transport page named an unexpected spool")
    if offset != len(plan.transport_data) or total < 0 or len(chunk) > TRANSPORT_CHUNK_BYTES:
        return fail_transport(plan, "transport page offset, total, or chunk size is inconsistent")
    if plan.transport_path and path != plan.transport_path:
        return fail_transport(plan, "transport spool changed between pages")
    if plan.transport_total is not None and total != plan.transport_total:
        return fail_transport(plan, "transport total changed between pages")
    if plan.transport_sha256 and digest != plan.transport_sha256:
        return fail_transport(plan, "transport hash changed between pages")
    if offset + len(chunk) > total or (offset < total and not chunk):
        return fail_transport(plan, "transport page made no valid forward progress")
    plan.transport_path = path
    plan.transport_total = total
    plan.transport_sha256 = digest
    plan.transport_data.extend(chunk)
    if len(plan.transport_data) < total:
        return "pending"
    if len(plan.transport_data) != total:
        return fail_transport(plan, "transport delivered more bytes than declared")
    if hashlib.sha256(plan.transport_data).hexdigest() != digest:
        return fail_transport(plan, "transport hash did not match the delivered bytes")
    plan.transport_complete = True
    return "complete"


def transported_result(plan: GatePlan) -> str:
    """The verified complete gate stream as text, or ``""`` until transport completes."""
    if not plan.transport_complete:
        return ""
    return bytes(plan.transport_data).decode("utf-8", "replace")


def continue_transport_command(plan: GatePlan) -> str:
    """The next harness-side page request, or ``""`` when transport cannot continue.

    Once a real page has taught cria the resolved spool path, this is the existing narrow
    offset-based re-read (unchanged shape). Until then — total silence, or only the reader's own
    typed ``running`` envelope so far — cria does not know the path (`${TMPDIR:-/tmp}` is the
    HARNESS's own value, #23c: cria composes, the harness resolves) and cannot compose a narrower
    request, so it re-sends the WHOLE launch script. That is exactly `plan.script`, made idempotent
    for this (:func:`_gate_launch_guard` skips relaunching a block whose spool or ``.done`` marker
    already exists), read-only in effect, and safe to repeat until page 0 lands or the plan's own
    deadline gives up.
    """
    if not plan.transport_required or plan.transport_complete or plan.transport_error:
        return ""
    if not plan.transport_path:
        return plan.script
    return "\n".join([
        _gate_sentinel([]),
        _transport_reader(shlex.quote(plan.transport_path), len(plan.transport_data),
                          plan.transport_id),
    ])


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


def plan_gate(workspace: str, session: str = "", rlog=None) -> GatePlan:
    """Inspect the workspace read-only and compose the gate script.

    Selection is re-run on EVERY gate (like upstream's ``discover`` per gate run):
    the repo's shape changes as the coder works — a pyproject.toml written in step 2
    must make pytest discoverable by step 3's gate.

    ``workspace`` empty → a MINIMAL gate (git snapshot only, no cd): cria couldn't learn
    the workspace path, so it must not discover against its OWN cwd (that once composed a
    probe over cria's repo itself). The harness's shell already runs in the workspace, so
    the git leg still lands; the checks just abstain (digest says none ran)."""
    plan = GatePlan(
        workspace=workspace,
        surveyed_before=bool(wsview.current(workspace or None).surveyed),
        transport_required=True,
    )
    if workspace:
        plan.candidates = proberun.select_completion_probes(workspace)
        plan.untested = probediscovery.undiscoverable_tests(workspace)
        # …and the other half of the same question. `undiscoverable_tests` reports test files a
        # runner will NOT see; this reports test files a runner WOULD see in a project where no test
        # command was composed at all. Both end in the same clean-branch qualifier, because the coder
        # needs the same thing from either: to know that a green gate ran no tests.
        if not any(c.kind is probediscovery.ProbeKind.Test for c in plan.candidates):
            plan.untested += probediscovery.tests_with_no_command(workspace)
        plan.ran_in = _checks_ran_elsewhere(workspace, plan.candidates)

    parts: list[str] = [f"cd {shlex.quote(workspace)} || exit 97"] if workspace else []
    # FIRST, remove what the LAST gate's probes left behind. cria cannot delete on the harness's
    # filesystem itself, so the removal rides on the next script it composes — before the pre-probe
    # `git status` below, so this gate's own untracked-file baseline is taken after the cleanup and
    # the litter is never attributed to the coder.
    if workspace and (rm := litter_removal_command(workspace)):
        parts.append(rm)
    # THE GATE MUST NOT LEAVE STATE BEHIND. It runs the repo's own tests in the LIVE workspace, and a
    # test that writes — a database file, a fixture, an output artifact — leaves that behind for the
    # next gate to trip over. cria then reports a failure it manufactured itself, under the strongest
    # header it has. Measured on the six-language battery: a leftover orders.db from one gate run
    # made the next run's schema assertions fail, and the coder was sent to debug cria's litter.
    #
    # Principle 7 already says cria never pollutes the user's workspace; running tests there is the
    # one place it did. The fix is bounded and needs no per-language knowledge: record the untracked
    # files before the probes, and remove exactly the ones that appeared during them. Tracked files
    # are never touched, and with no git the whole thing abstains rather than guessing.
    #
    # The REMOVAL happens on cria's side (:func:`sweep_litter`), not in this script. A `rm` here is
    # not merely inelegant — the Codex sandbox HARD-REJECTS the whole exec ("rm -f style commands are
    # not permitted"), so an `rm` in the cleanup killed EVERY gate in EVERY language, and the gate
    # abstained silently because a rejected exec returns no probe sections. writeproxy.py:801 records
    # the same sandbox rejection breaking every web_search. cria composes read-only shell; when
    # something must be deleted, cria deletes it itself, under the dirguard's bounds.
    if workspace:
        parts.append("__cria_pre=$(git status --porcelain 2>/dev/null | sed -n 's/^?? //p' | sort)")
    for i, c in enumerate(plan.candidates):
        parts.append(f"echo {_marker(f'probe-{i}')}")
        parts.append(proberun.compose_probe_command(c, COMPLETION_PROBE_TIMEOUT_S))
        if c.kind is probediscovery.ProbeKind.Test:
            # Remember THIS probe's exit code for the offline leg below. compose_probe_command
            # leaves it in __cria_ec, which the next probe overwrites, so it is captured here under
            # a name of its own.
            parts.append(f"{proberun.TEST_EC_VAR}=$__cria_ec")
    # The OFFLINE re-run of the test probe — see proberun.offline_probe_command.
    # Emitted last among the probes so a failure here can never mask a real check result.
    test_c = next((c for c in plan.candidates
                   if c.kind is probediscovery.ProbeKind.Test), None)
    offline = proberun.offline_probe_command(test_c, COMPLETION_PROBE_TIMEOUT_S) if test_c else ""
    if offline:
        parts.append(f"echo {_marker('offline')}")
        parts.append(offline)
    if workspace:
        # Exactly what the probes created, LISTED for cria to remove. The files present now that were
        # not present before; anything git tracks never appears in this list at all.
        parts.append(f"echo {_marker(LITTER_SECTION)}")
        parts.append("__cria_post=$(git status --porcelain 2>/dev/null | sed -n 's/^?? //p' | sort)")
        # POSIX sh only — no process substitution. The harness's shell is not guaranteed to be bash,
        # and a bashism here would fail silently and leave the litter behind.
        parts.append('if [ -z "$__cria_pre" ]; then __cria_new=$__cria_post; '
                     'else __cria_new=$(printf \'%s\\n\' "$__cria_post" | grep -vxF "$__cria_pre"); fi')
        parts.append('printf \'%s\\n\' "$__cria_new"')
    # THE CHANGED-FILES SIGNAL IS GONE, and it never was one. `git status --porcelain | sha1sum` ran
    # on EVERY gate — roughly 1,500 round trips over twelve days of logs — was parsed into
    # `GateOutcome.git_state`, stored on `GuardState.gate_git`, and read by NOTHING: `grep -rn
    # git_state\|gate_git` over the package returns the write, the store and one test assertion.
    # Untouched since the original port on 2026-07-11. Its stated job — "workspace-change signal
    # across gates" — is answered by two live mechanisms that came later, `wsview.may_have_changed`
    # and `_writes_since_last_gate`, both from facts cria already holds.
    #
    # The section marker goes with it: the survey is stripped before `split_sections` runs, so the
    # last real section simply runs to the end of the text, as it would have anyway.
    # THE WORKSPACE SURVEY RIDES HOME WITH THE GATE. This is already a harness round trip, so it
    # costs nothing extra, and it is the one place guaranteed to happen in a session where the
    # harness offers its own file tools and cria lowers nothing. Appended AFTER the last marker and
    # taken back off by `interpret_gate`, so no section ever contains a byte of it.
    #
    # The survey rides inside the same lossless spool. It keeps its own structural tree bound (a
    # folded directory is explicit UNKNOWN), but it no longer competes with probe bytes for one
    # harness result and therefore needs no per-gate byte arithmetic.
    parts.append(wsview.survey_command(session, cd=workspace))
    # STATE IT NOW, while cria still knows. A probe the coder could retype is one line of argv; a
    # manifest check cria composed is a multi-line inline program. The distinction is free here and
    # unrecoverable downstream — see GATE_SENTINEL.
    retypable = [" ".join(c.command) for c in plan.candidates
                 if c.command and not c.composed_by_cria]
    # The harness owns the filesystem and the asynchronous clock. It writes the complete aggregate
    # outside the workspace, then sends only the first checked page now. Later pages are requested by
    # :func:`continue_transport_command`; cria never reaches into the remote machine itself.
    #
    # C28: the spool/launch-script paths are DETERMINISTIC off `plan.transport_id` (cria's own
    # 96-bit-random token, not a guessed value) rather than `mktemp`'s random suffix. cria still
    # cannot know `${TMPDIR:-/tmp}`'s resolved value (#23c — that's the HARNESS's environment), but a
    # fixed name lets `continue_transport_command` retry this exact launch text verbatim while it has
    # learned nothing yet, and `_gate_launch_guard` makes that retry a no-op once the block is started.
    spool = f'"${{TMPDIR:-/tmp}}/.cria-gate-{plan.transport_id}.spool"'
    cmd_file = f'"${{TMPDIR:-/tmp}}/.cria-gate-{plan.transport_id}-cmd.sh"'
    plan.transport_deadline_s = _gate_deadline_s(len(plan.candidates) + (1 if offline else 0))
    plan.script = "\n".join([
        _gate_sentinel(retypable),
        f"__cria_gate_file={spool}",
        f"__cria_gate_cmd={cmd_file}",
        *_gate_launch_guard('"$__cria_gate_file"', '"$__cria_gate_cmd"', parts),
        _transport_reader('"$__cria_gate_file"', 0, plan.transport_id),
    ])
    return plan


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
                or getattr(outcome, "transport_unknown", False))


def split_sections(text: str) -> dict[str, str]:
    """Marker-delimited output → {section_id: body}. Unknown text before the first
    marker is ignored (harness banners etc.)."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(SECTION_PREFIX) and stripped.endswith(SECTION_SUFFIX):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = stripped[len(SECTION_PREFIX):-len(SECTION_SUFFIX)]
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


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
    from cria import selfcompact
    calls: dict = {}
    changed = set()
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
            if tid in calls and isinstance(c, str) and selfcompact.write_landed(c):
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


def clean_gate_output(raw: str, plan: "GatePlan | None" = None, *, annotate: bool = True,
                      changed_paths: "frozenset[str]" = frozenset(),
                      a_command_ran_since: bool = False,
                      checks_reran: bool = False) -> str | None:
    """A raw gate-probe RESULT → a compact, error-class-only summary for the MODEL to read.

    The raw result is cria's internal gate protocol wrapped in the harness's exec noise:
    ``___CRIA_GATE_probe-N___`` section markers, ``EXIT:<n>`` sentinels, a git-hash section, and a
    ``Chunk ID / Process exited / …`` wrapper. Shown verbatim (and PROTECTED from trimming) it buried
    the one real error under plumbing AND leaked advisory lint (``imported but unused``) the model then
    chased — even though the gate DIGEST already filters those. This strips all of it and, keying on the
    RELIABLE per-section EXIT code (not fragile text sniffing), reports one honest state: error-class
    findings; a check that FAILED with no parseable location; checks that could NOT run (launch failure
    / timeout — cria's own setup gap, a neutral non-signal, never a pass); or the checks that ran found
    nothing (framed "no error-class problems", explicitly NOT "done"). Returns ``None`` when ``raw`` is
    not a gate result (untouched)."""
    if SECTION_PREFIX not in (raw or ""):
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
    seen: set[str] = set()
    could_not_run = False
    failed_no_detail = False
    saw_probe = False
    timed_out_output: list[str] = []
    _sections = split_sections(raw)
    for sid, body in _sections.items():
        # `git` is no longer EMITTED (see plan_gate), but a gate result already in a session's
        # history still carries that section, and it must never read as a probe's output.
        if sid in ("git", LITTER_SECTION):  # cria's own bookkeeping — signal for cria, noise for the model
            continue
        # The offline re-run is an INSTRUMENT READING, not a check. It is the same suite with the
        # network taken away, so on a genuinely live suite it is SUPPOSED to fail — and this loop
        # would have scraped that failure into the findings and told the coder to go fix passing
        # tests (the false-red class, from the very leg built to expose a false green). Its exit
        # code reaches exactly one reader: _offline_fact. Skipping it also keeps a namespace-less
        # box honest — an empty section can no longer set could_not_run and wedge the whole gate.
        if sid == "offline":
            continue
        saw_probe = True
        text, code = proberun.scrape_exit(body)
        # The EXIT sentinel is the reliable signal (the composed probe always prints it). A launch
        # failure (125/126/127) or timeout (124) means the check did NOT complete — never a code error
        # to "fix", never a pass. Sniffing text for "no such file" would misread a real error that just
        # mentions it (a FileNotFoundError, a missing #include) as couldn't-run.
        if code in proberun.LAUNCH_FAILURE_EXIT_CODES:
            could_not_run = True    # never launched → there is nothing it could have printed
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
            could_not_run = True
            if text.strip():
                timed_out_output.append(text.strip())
            continue
        # pytest exit 5 = no tests collected (a fresh/testless project). The runner ran fine and had
        # nothing to assess — a benign non-signal. Skip the section so its "no tests ran" line isn't
        # scraped as an error-class finding AND it doesn't set failed_no_detail; the OTHER probes that
        # ran decide the gate's verdict. saw_probe stays True, so a pytest-only gate reads clean-ish
        # ("checks that ran reported no problems"), never "one of the checks FAILED".
        #
        # UNLESS the disk says otherwise. Measured on maple run 2 (1785973706): a 19KB pytest suite
        # named `pytest_da_resolvers.py` — a name pytest's pattern cannot collect — so "no tests ran"
        # for the run's final 30 minutes while real tests sat on disk, and the benign rule kept the
        # gate silent. Same discriminator shape as F811: keep the benign default, read the disk to
        # tell the testless project from the mis-named suite; a stranded test file is a stated,
        # checkable, error-class fact (the files, the runner, its naming rule). The detector is the
        # ONE existing owner (probediscovery's convention table — the g20 mechanism), not a second
        # scanner. Also applied to a PASSING test section whose runner said it collected nothing
        # (go's "[no test files]" exits 0) — a green built on zero tests plus a stranded suite is
        # the same false green.
        if proberun.is_no_tests_collected(code, output=text) or \
                (code == 0 and _zero_tests_marker(text)):
            if stranded_findings is None:
                stranded_findings = probediscovery.stranded_test_sentences(workspace) \
                    if workspace else []
            if stranded_findings:
                findings.extend(f for f in stranded_findings if f not in seen)
                seen.update(stranded_findings)
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
            if not s or s.startswith(proberun.PROBE_EXIT_SENTINEL):   # blank / EXIT:<n> sentinel
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
        return prompts.render("checks_error_class",
                              seeded_test_rule=prompts.load("seeded_test_rule").strip(),
                              stale=stale.rstrip("\n"),
                              findings="\n".join(findings + _advisory_note(dropped_advisories)))
    if failed_no_detail:            # ran, exited non-zero, no usable output → a failure with no location
        return ("⟦ctx:checks⟧ one of the repo's own checks FAILED but printed no parseable location — "
                "run it yourself and read the actual error before continuing. Not done.")
    if could_not_run and timed_out_output:
        # It ran, stalled, and printed something first — hand that over verbatim, labelled for what it
        # is, instead of only "no signal either way".
        return (CHECKS_MARKER + " a check did not finish (timed out) — no verdict either way. It printed "
                "this before it was stopped:\n" + "\n".join(timed_out_output))
    if could_not_run:               # couldn't launch/timed out → cria's own setup gap; stay neutral
        # NOT a pass (never claim clean), NOT a fix request (the model can't fix cria's absent tool),
        # NOT a specific confession — just a non-actionable placeholder so the model relies on itself.
        return "⟦ctx:checks⟧ the automatic checks produced no usable result — no signal either way."
    # Report the clean result as a FACT — no "but this doesn't mean it's correct / doesn't mean done"
    # hedge. That caveat is unactionable doubt (it names nothing to fix) and a weak model latches onto
    # it and spirals; completion is guarded by the actual gate + satisfaction check, not by nagging the
    # coder that a green check might still be wrong. (Operator directive, twice.)
    clean = "⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems."
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
                 probediscovery.ProbeKind.BuildCheck: "build"}
        ran = [w for k, w in kinds.items() if any(c.kind is k for c in cands)]
        covered = " and ".join([", ".join(ran[:-1]), ran[-1]] if len(ran) > 2 else ran) or "nothing"
        clean += " " + prompts.fill(words["ran_some" if ran_tests else "no_command"],
                                    findings=" ".join(untested), covered=covered)
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
    return clean


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
    online_text, online_code = proberun.scrape_exit(online)
    offline_text, offline_code = proberun.scrape_exit(off)
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


_NO_SIGNAL_CHECK = "no usable result"   # the ⟦ctx:checks⟧ non-signal — nothing to act on

# WHAT THE MODEL MAY SEE OF A GATE, CARRIED AS DATA — not re-derived by matching cria's own text.
#
# There used to be nine regexes here and in `wsview`, and their whole job was to answer a question
# cria could answer for free: "is this my own text?". At compose time `plan_gate` knows exactly which
# argv are real probes and which bytes are its own scaffolding; it threw that away into a shell
# script and every reader downstream tried to recover it by pattern.
#
# It does not work, and the failure has a signature: the same matcher was patched THREE TIMES in one
# day — for a wrapper that spans lines, then for cria's own inline programs, then for the litter
# heredoc — each time because cria had grown a new kind of self-authored text the patterns had never
# heard of. Each patch was correct and none of them was the fix (#4: fix upstream, not at the point
# of damage; #12: take the fact from the authoritative event, never from an English match).
#
# So the plan states it. `writeproxy._sentinel` has done exactly this for every lowered tool call
# since it was written, statelessly, and needs no strip patterns at all — this is that pattern,
# applied to the one caller that lacked it.
#
# A COMMAND THE CODER COULD RETYPE IS WORTH SHOWING; A PROGRAM CRIA WROTE IS NOT. `cargo test`,
# `go vet ./...`, `bundle exec rubocop` come off the project's own tooling and seeing one run is real
# provenance for the finding it produced. The parse floor does not: it is cria's own construction,
# and it is the half that hurt — the TOML check handed a Rust project the Python package `tomli`
# (0/4), and a coder emitted cria's `compileall` line back as its own work. Discovery states which
# is which (`ProbeCandidate.composed_by_cria`); the plan carries only the coder's half.
GATE_SENTINEL = "⟦ctx:gate⟧"


def _gate_sentinel(probes: list[str]) -> str:
    """The leading comment line naming the probe commands the model may see. Same shape and the same
    stateless contract as `writeproxy._sentinel`: it rides IN the command, so it survives a restart,
    a compaction and any re-render of the history."""
    payload = base64.b64encode(json.dumps(probes, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"# {GATE_SENTINEL}{payload}"


def gate_probes_of(cmd: str) -> list[str] | None:
    """The probe list a gate command declares, or None when this is not a cria-authored gate."""
    for line in (cmd or "").splitlines():
        s = line.strip()
        if not s.startswith("# " + GATE_SENTINEL):
            continue
        try:
            got = json.loads(base64.b64decode(s[len("# " + GATE_SENTINEL):].encode()).decode("utf-8"))
        except Exception:                       # noqa: BLE001 — an unreadable stamp is not a gate
            return None
        return [str(x) for x in got] if isinstance(got, list) else None
    return None


def gate_call_ids(messages: list) -> set:
    """Tool-call IDs whose command carries a valid gate provenance sentinel.

    The command author records this fact at composition time. Readers must use that fact rather
    than infer ownership from marker-like text a user or an ordinary tool may legitimately emit.
    """
    ids = set()
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw = function.get("arguments")
            try:
                args = jsontext.loads(raw) if isinstance(raw, str) else None
            except (ValueError, TypeError):
                args = None
            if not isinstance(args, dict):
                continue
            for field in ("cmd", "command"):
                value = args.get(field)
                command = (value if isinstance(value, str) else
                           "\n".join(str(part) for part in value) if isinstance(value, list) else "")
                if gate_probes_of(command) is not None:
                    if call.get("id"):
                        ids.add(call["id"])
                    break
    return ids


def _strip_gate_plumbing(cmd: str) -> str:
    """A composed gate command, reduced to the probe commands the model may see.

    Reads the stamp `plan_gate` put there. No patterns, no un-composing, and nothing to teach when
    cria grows a new kind of internal leg — a survey, a litter removal, an offline re-run — because
    none of them is in the list and none of them ever has to be excluded.

    THE HARMS THIS PREVENTS ARE MEASURED. Across the thirteen walked nemotron runs the unstripped
    scaffolding was 3.8% of every byte cria sent one coder (50 copies of a pom checker, 100 of the
    `unshare` offline leg, 850 occurrences of `__cria_`); three separate models copied it back as
    their own command; and the token `cria` reached the model 63 times in a single prompt (#17).

    Not a gate → "". A cria-authored call the model never made has nothing in it for the model.
    """
    probes = gate_probes_of(cmd)
    return "\n".join(p for p in (probes or []) if p.strip())


def cria_authored_call_ids(m: dict) -> set:
    """The ids of this turn's tool calls that, once the gate plumbing is stripped, hold NOTHING.

    `_strip_gate_plumbing` returns "" when no probe in the script is retypable — "a cria-authored
    call the model never made has nothing in it for the model", in its own words. The command was
    emptied and the CALL was left standing, so the model's history read:

        <function=exec_command><parameter=cmd>
        </parameter>
        …
        <tool_response>⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems.

    — an empty command attributed to the model, and cria answering it. Measured at 188 prompts, all
    on 2026-08-22, on the node cell, where every probe is a `node --check` cria composed and so
    nothing is retypable."""
    ids = set()
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments")
        if not isinstance(raw, str):
            continue
        try:
            a = jsontext.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(a, dict):
            continue
        for field in ("cmd", "command"):
            v = a.get(field)
            text = v if isinstance(v, str) else ("\n".join(str(x) for x in v) if isinstance(v, list) else "")
            if gate_probes_of(text) is not None and not _strip_gate_plumbing(text).strip():
                if tc.get("id"):
                    ids.add(tc["id"])
    return ids


def _strip_command_plumbing(m: dict) -> dict:
    """If an assistant tool call carries a gate-scaffolded command, rewrite the command in place to drop
    the plumbing (markers/git-sha/cd-guard). Shape-preserving: str ``cmd`` or list ``command``."""
    tcs = m.get("tool_calls")
    if not tcs:
        return m
    changed = False
    new_tcs = []
    for tc in tcs:
        fn = tc.get("function") or {}
        raw = fn.get("arguments")
        if isinstance(raw, str):
            try:
                a = jsontext.loads(raw)
            except (ValueError, TypeError):
                a = None
            if isinstance(a, dict):
                call_changed = False
                for field in ("cmd", "command"):
                    v = a.get(field)
                    if isinstance(v, str) and gate_probes_of(v) is not None:
                        a[field] = _strip_gate_plumbing(v)
                        call_changed = True
                    elif isinstance(v, list):
                        joined = "\n".join(str(x) for x in v)
                        if gate_probes_of(joined) is not None:
                            a[field] = [_strip_gate_plumbing(joined)]
                            call_changed = True
                if call_changed:
                    tc = {**tc, "function": {**fn, "arguments": json.dumps(a)}}
                    changed = True
        new_tcs.append(tc)
    return {**m, "tool_calls": new_tcs} if changed else m


def clean_gate_results(messages: list, plan: "GatePlan | None" = None, *,
                       drop_private_results: bool = False, linked_only: bool = False) -> list:
    """Rewrite raw gate-probe tool results (in the model's view) to the cleaned summary. Idempotent;
    a re-run over already-clean messages leaves them untouched. Non-gate messages pass through.

    Also STRIPS the gate's command-side plumbing (the ``echo ___CRIA_GATE_…``/``git status|sha1sum``/
    ``cd||exit 97`` scaffolding the coder never authored), DROPS non-signal ⟦ctx:checks⟧ turns entirely
    (with their command call, so nothing orphans — a "no usable result this turn" is pure noise), and

    For provenance-linked gate calls only, COLLAPSES repeats: when the same cleaned ⟦ctx:checks⟧ payload
    appears more than once, keep only the most recent full copy and shorten the earlier identical ones to
    a one-line back-reference. Unstamped model-visible results remain verbatim."""
    out = []
    gate_ids = gate_call_ids(messages) if linked_only else set()
    drop_ids: set = set()          # tool_call ids whose result we dropped → drop the calling turn too
    # THE CALL WAS CRIA'S AND THE MODEL NEVER MADE IT. When the whole gate script is
    # composed-by-cria, `_strip_gate_plumbing` empties the command and the empty call used to stay
    # in the model's own history with cria's answer under it. Its RESULT is real ground truth and
    # is kept — as a plain message, which is what it always was.
    own_ids: set = set()
    # A paged gate occupies several harness turns, but it is one piece of evidence. Retain the first
    # result in each transport as the wire-valid seat for its final rendering and drop the remaining
    # page calls/results. Reassemble and verify OLDER transports from their page envelopes: the
    # conversation still holds every byte/count/hash even after the session's current plan advances.
    # Treating a formerly-complete check as UNKNOWN merely because a newer plan exists would destroy
    # evidence the model had already read. An actually incomplete/invalid history remains UNKNOWN.
    transport_re = re.compile(re.escape(TRANSPORT_PREFIX) + r"([0-9a-f]{24})" +
                              re.escape(TRANSPORT_SUFFIX))
    transport_first: dict[str, int] = {}
    transport_ids: dict[int, str] = {}
    transport_pages: dict[str, list[str]] = {}
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        is_tool = message.get("role") == "tool" or message.get("type") == "function_call_output"
        payload = message.get("content") or message.get("output")
        call_id = message.get("tool_call_id") or message.get("call_id")
        match = (transport_re.search(payload) if is_tool and isinstance(payload, str)
                 and (not linked_only or call_id in gate_ids) else None)
        if match:
            transport_id = match.group(1)
            transport_ids[i] = transport_id
            transport_first.setdefault(transport_id, i)
            transport_pages.setdefault(transport_id, []).append(payload)
    transport_states: dict[str, GatePlan] = {}
    for transport_id, pages in transport_pages.items():
        if plan is not None and plan.transport_id == transport_id:
            # The live bridge already consumed these pages. Re-ingesting them would correctly look
            # like an offset regression, so use its verified session state directly.
            transport_states[transport_id] = plan
            continue
        historical = GatePlan(workspace="", transport_required=True,
                              transport_id=transport_id)
        for page in pages:
            if historical.transport_complete:
                fail_transport(historical, "transport history continued after its final page")
                break
            if ingest_transport(historical, page) == "unknown":
                break
        transport_states[transport_id] = historical
    retained_transport = set(transport_first.values())
    raw_gate_indices = [i for i, m in enumerate(messages)
                        if isinstance(m, dict)
                        and (m.get("role") == "tool" or m.get("type") == "function_call_output")
                        and isinstance(m.get("content") or m.get("output"), str)
                        and SECTION_PREFIX in (m.get("content") or m.get("output"))
                        and (not linked_only
                             or (m.get("tool_call_id") or m.get("call_id")) in gate_ids)]
    last_gate = max([*raw_gate_indices, *retained_transport], default=-1)
    for i, m in enumerate(messages):
        if isinstance(m, dict):
            is_tool = m.get("role") == "tool" or m.get("type") == "function_call_output"
            key = "content" if m.get("content") is not None else "output"
            c = m.get(key)
            if is_tool and i in transport_ids:
                tid = m.get("tool_call_id") or m.get("call_id")
                if i not in retained_transport:
                    if tid:
                        drop_ids.add(tid)
                    continue
                transport_id = transport_ids[i]
                current = plan is not None and plan.transport_id == transport_id
                transport_state = transport_states[transport_id]
                if transport_state.transport_complete:
                    c = clean_gate_output(
                        transported_result(transport_state), plan if current else None,
                        annotate=(i == last_gate),
                        changed_paths=_paths_written_after(messages, i) if i == last_gate else frozenset(),
                        a_command_ran_since=(i == last_gate
                                             and _a_command_could_have_changed_things_after(messages, i)),
                        checks_reran=(i == last_gate
                                      and _probe_reran_after_last_change(messages, i, plan)))
                else:
                    c = prompts.load("probe_transport_unknown")
                if c is None or _NO_SIGNAL_CHECK in c:
                    if tid:
                        drop_ids.add(tid)
                    continue
                if tid in own_ids:
                    out.append({"role": "user", "content": c})
                else:
                    out.append({**m, key: c})
                continue
            # A private survey bootstrap may be refused before it emits a gate marker.  Its raw
            # tool result cannot reach the planner, because its matching assistant call is private.
            tid = (m.get("tool_call_id") or m.get("call_id")) if is_tool else None
            if drop_private_results and tid in own_ids:
                drop_ids.add(tid)
                continue
            if (is_tool and isinstance(c, str) and SECTION_PREFIX in c
                    and (not linked_only or tid in gate_ids)):
                # ANNOTATE ONLY THE NEWEST GATE RESULT. This function re-renders every gate result
                # in the history on EVERY prompt build, and the disk quote is read at render time —
                # so a finding produced five calls ago gets stamped with whatever that line says
                # NOW. Walked three times independently on maple-preview 1785994846: the same
                # `test_resolve_adam.py:54` was annotated `mock_get.assert_called_once_with(` at
                # call 0027, `self.assertEqual(result["address"], "tz1KqTp…")` at 0031, and
                # `f"{API_BASE_URL}/handles/go.handle",` at 0032 — with byte-identical MagicMock ids
                # proving the checks never re-ran in between. The coder read a stale failure carrying
                # a freshly-wrong quote, concluded its landed fix had not landed, un-fixed a correct
                # assertion and re-applied an import it already had. Three calls, on a 15-minute wall.
                # The guard was added the same morning (bdd68bc) to stop the model GUESSING at an
                # unquoted line; on a file that has moved it manufactures the guess instead.
                cleaned = clean_gate_output(
                    c, plan, annotate=(i == last_gate),
                    changed_paths=_paths_written_after(messages, i) if i == last_gate else frozenset(),
                    a_command_ran_since=(i == last_gate
                                         and _a_command_could_have_changed_things_after(messages, i)),
                    checks_reran=(i == last_gate
                                  and _probe_reran_after_last_change(messages, i, plan)))
                if cleaned is not None:
                    if _NO_SIGNAL_CHECK in cleaned:   # no signal → drop the result AND its command turn
                        tid = m.get("tool_call_id") or m.get("call_id")
                        if tid:
                            drop_ids.add(tid)
                        continue
                    if (m.get("tool_call_id") or m.get("call_id")) in own_ids:
                        # Its call is gone (cria composed the whole script, so nothing in it was the
                        # model's), and a result with no call is not a result. Kept whole as a plain
                        # message — the checks block is the ground truth the gate exists to deliver.
                        out.append({"role": "user", "content": cleaned})
                    else:
                        out.append({**m, key: cleaned})
                    continue
            if m.get("role") == "assistant" and m.get("tool_calls"):
                empties = cria_authored_call_ids(m)
                if empties and len(m["tool_calls"]) == len(empties):
                    own_ids |= empties
                    continue
                m = _strip_command_plumbing(m)
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
    # `resolve_handle_and_test.py:92: undefined name 'pytest'` THREE times in one coder prompt — on
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


# A harness that REFUSES to run the gate at all (sandbox policy, no shell, a rejected verb) returns no
# section markers, which interpret_gate correctly reads as "nothing ran" — correct, and completely
# silent. cria then loses its single largest assist on every turn with nothing in the log to say so.
# These are the phrases a refusal carries; matching one turns the silence into one operator-facing warn.
_REFUSAL_PHRASES = (
    "not permitted",
    "rejected:",
    "is not allowed",
    "permission denied",
    "operation not permitted",
    "sandbox",
)


def refusal_reason(result_text: str) -> str:
    """The harness's own words for why it would not run the gate — '' if it doesn't look like a refusal.

    Only consulted when NO section came back: a gate that ran and merely failed is not a refusal."""
    text = (result_text or "").strip()
    if not text:
        return ""
    low = text.lower()
    if not any(p in low for p in _REFUSAL_PHRASES):
        return ""
    # The useful part is the harness's reason, not the multi-kilobyte echo of the script it refused.
    for phrase in _REFUSAL_PHRASES:
        i = low.find(phrase)
        if i >= 0:
            return " ".join(text[max(0, i - 80):i + 160].split())
    return ""


# Litter one gate's probes created, waiting for the NEXT gate script to remove it. Keyed by
# workspace because that is what the removal command needs, and bounded like every other
# per-session store here.
_LITTER_QUEUE: dict[str, list[str]] = {}


def _queue_litter(workspace: str, rels: list[str]) -> None:
    if not workspace:
        return
    if len(_LITTER_QUEUE) > 256:
        _LITTER_QUEUE.clear()
    q = _LITTER_QUEUE.setdefault(workspace, [])
    for r in rels:
        if r not in q:
            q.append(r)
    del q[:-256]


def litter_removal_command(workspace: str) -> str:
    """The shell leg that removes the previous gate's litter, or "" when there is none.

    A `python3` unlink rather than `rm`: the harness sandbox rejects an exec containing `rm` and
    takes every probe in the script down with it, which is how a cleanup once killed every gate in
    every language. Paths are workspace-relative and were already bounded by `sweep_litter`; the
    program refuses an absolute path or a `..` a second time, because this is the leg that deletes.
    """
    q = _LITTER_QUEUE.pop(workspace, None)
    if not q:
        return ""
    prog = ("import os,shutil,sys\n"
            "for rel in " + repr(q) + ":\n"
            "    if os.path.isabs(rel) or '..' in rel.split('/'):\n"
            "        continue\n"
            "    t = os.path.join(os.getcwd(), rel)\n"
            "    try:\n"
            "        if os.path.islink(t) or os.path.isfile(t):\n"
            "            os.unlink(t)\n"
            "        elif os.path.isdir(t):\n"
            "            shutil.rmtree(t)\n"
            "    except OSError:\n"
            "        pass\n")
    return "{ python3 - <<'__CRIA_LITTER__'\n" + prog + "__CRIA_LITTER__\n} >/dev/null 2>&1"


def sweep_litter(plan: GatePlan, sections: dict) -> list[str]:
    """Remove the untracked files the gate's OWN probes created. Returns what was removed.

    The list comes from the harness's shell (git's ``??`` set, before minus after); the removal happens
    here so cria never composes a destructive command — the Codex sandbox rejects the whole exec when it
    sees one, which silently killed every gate (see :func:`plan_gate`).

    Bounded three ways, because this deletes files: git must call the path UNTRACKED (a tracked file can
    never appear), the path must resolve INSIDE the workspace (no absolute paths, no ``..``, no following
    a symlink out), and any failure is skipped rather than escalated. Nothing here guesses."""
    body = (sections or {}).get(LITTER_SECTION)
    root = getattr(plan, "workspace", "") or ""
    if not body or not root:
        return []
    removed: list[str] = []
    queue: list[str] = []
    for rel in (ln.strip() for ln in body.splitlines()):
        # ONE OWNER for "does this path leave the workspace". This used to be a hand-rolled
        # realpath-the-parent dance here, correct but private, while writeproxy asked dirguard a
        # LEXICAL version of the same question and the two disagreed on a symlink pointing out.
        # Both answers were right for their caller and neither had a name, so execcheck and
        # planner_tools — which also act in the workspace — checked nothing at all.
        if not rel or os.path.isabs(rel) or dirguard.escapes_workspace(rel, root):
            continue
        queue.append(rel)
        removed.append(rel)
    # THE REMOVAL HAPPENS ON THE HARNESS'S SIDE, because that is whose filesystem this is. cria used
    # to unlink these paths itself — correct only while the two machines are the same one, and a
    # silent no-op otherwise, which would leave the gate's own litter behind for the next gate to
    # report as the repo's failure. So the paths are QUEUED and the next gate script removes them
    # before it runs anything (see plan_gate). Still not an `rm`: the Codex sandbox hard-rejects the
    # whole exec when it sees one, and a rejected exec kills every probe in the script.
    if queue:
        _queue_litter(plan.workspace, queue)
    return removed


def interpret_gate(plan: GatePlan, result_text: str, rlog=None) -> GateOutcome:
    """Replay the harness's gate output through the ported interpreters."""
    state = ingest_transport(plan, result_text)
    if state in ("pending", "running"):
        # C28: `running` is exactly as non-terminal as `pending` from here — the caller (normally
        # `loop.guard_gate_transport`, which intercepts both before `interpret_gate` is ever reached
        # this turn) re-issues the read-only wait/read instead of treating it as evidence.
        return GateOutcome(ran=False, transport_pending=True)
    if state == "unknown":
        if rlog is not None:
            rlog.emit("gate.transport_unknown", level="warn", reason=plan.transport_error,
                      received=len(plan.transport_data), total=plan.transport_total)
        return GateOutcome(ran=False, transport_unknown=True)
    if state == "complete":
        result_text = transported_result(plan)
    # The workspace survey rode home on this result (see plan_gate). Take it off first — it is
    # cria's own instrumentation, it belongs to no probe, and left in place it would land inside
    # whichever section happened to be open when it started.
    result_text, survey = wsview.strip_survey(result_text)
    survey_applied = False
    if survey:
        # A SURVEY THAT DID NOT LAND IS AN EVENT, NOT AN ABSENCE (#12). `apply_survey` refuses a
        # survey that arrived cut, or that is about a different tree, and refusing is right — but
        # both call sites threw the answer away and `wsview` emits nothing at all, so the one failure
        # this module cannot notice from the outside was also the one nobody was told about. An
        # unsurveyed view is what `_confirm_completion` fails open on and what leaves
        # `linterprobe.collect_files` with no probes to compose.
        survey_applied = wsview.apply_survey(wsview.current(), survey)
        if not survey_applied and rlog is not None:
            rlog.emit("gate.survey_rejected", level="warn", bytes=len(survey),
                      closed=wsview.SURVEY_CLOSE in survey, **wsview.last_reject())
    sections = split_sections(result_text)
    participation_events = []
    # Before anything else: take back what the probes left behind. Runs even when the gate FAILED —
    # a suite that errors halfway still wrote its fixtures, and the next gate would inherit them.
    swept = sweep_litter(plan, sections)
    # ran is TRUE only if an actual check section came back — NOT just the always-present git snapshot.
    # An empty / no-code repo yields zero candidates, so plan_gate composes a git-ONLY script; treating
    # that as "ran" made guard_ground_truth emit a clean "no error-class problems" verdict when NO check
    # actually ran. No probe-* section → ran=False → silence, not a false pass.
    if not any(k.startswith("probe-") for k in sections):
        participation_events = [participation.observe(c, "", None, event_missing=True)
                                for c in plan.candidates]
        plan.participation = participation.report(participation_events)
        return GateOutcome(
            ran=False,
            refused=refusal_reason(result_text),
            replan_after_survey=bool(survey_applied and not plan.surveyed_before),
            participation=plan.participation,
        )
    out = GateOutcome(ran=True, swept=swept)

    results = []
    for i, c in enumerate(plan.candidates):
        body = sections.get(f"probe-{i}")
        if body is None:
            # Never ran — the script was cut short (harness truncation) or the section never came back.
            # Absence must not BLOCK, but it must not read as CLEAN either: `results` silently became a
            # subset of `selected`, and nothing downstream said a check was missing, so a truncated gate
            # looked like a passing one. Record the gap so the digest can report it.
            out.unran.append(proberun.display_command(c.command))
            participation_events.append(participation.observe(c, "", None, event_missing=True))
            continue
        raw, code = proberun.scrape_exit(body)
        result = proberun.interpret_probe_output(
            c, proberun.display_command(c.command), raw, code, COMPLETION_PROBE_TIMEOUT_S)
        results.append(result)
        participation_events.append(participation.observe(
            c, raw, code, findings=result.findings))
    out.report = ProbeReport(project_type=[], selected=list(plan.candidates), results=results)
    out.participation = participation.report(participation_events)
    plan.participation = out.participation

    if any(c.kind is probediscovery.ProbeKind.Test for c in plan.candidates):
        out.offline_ran = bool(sections.get("offline", "").strip())

    return out
