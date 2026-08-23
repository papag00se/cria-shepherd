"""Plan-off self-compaction — cria manages its OWN context, on its own side.

On a long plan-off (direct-coder) session the harness may never compact, so the coder's
history grows unbounded (observed: 331 messages / ~35K tokens). The context floor keeps it
UNDER the window by DROPPING the oldest turns — which loses the information. Self-compaction
instead SUMMARIZES the old middle into one rolling briefing (reasoner-generated), so the
coder gets a lean, information-PRESERVING view: [system] + anchors + [rollup summary] +
a small verbatim band + the recent tail.

Everything is measured in TOKENS, not message count — the real constraint is the context
window, and a few huge file reads matter more than many tiny turns (the same currency the
floor uses). Structure kept every turn:
  - the leading system message (cria's coder framing),
  - any ANCHOR message (a ⟦ctx:briefing⟧ handoff / a ___CRIA_GATE_ ground truth) — verbatim,
  - ONE ⟦ctx:rollup⟧ summary of the old middle,
  - a small VERBATIM band of old-but-not-yet-folded turns (bounded by RECOMPACT_TOKENS),
  - the recent tail up to KEEP_TAIL_TOKENS verbatim (the live working set).

The summary is THROTTLED: re-generated only when the unfolded band grows past RECOMPACT_TOKENS,
not every turn (one reasoner call amortized over many turns). Boundary splits (an edge landing
between an assistant tool_call and its result) are cleaned by the floor's existing
_strip_orphan_tools downstream — self-compaction runs BEFORE the floor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import jsontext, probegate, prompts, toolargs
from .content_reduce import est_tokens

# Tunables in TOKENS. TRIGGER is operator-tunable via [context] trigger_compaction; the rest are
# code constants (they don't vary by environment).
TRIGGER_TOKENS_DEFAULT = 16384   # start compacting a plan-off view once it exceeds this many tokens
KEEP_TAIL_TOKENS = 6000          # keep the most recent turns verbatim, up to this many tokens
BOUNDARY_KEEP_TAIL_TOKENS = 0    # at a verified STEP BOUNDARY keep NO verbatim tail — the completed step's raw
#                                  turns fold ENTIRELY into the rollup. Nothing is lost: the NEXT step rides in
#                                  the caller's authoritative system message, the original task is pinned
#                                  (⟦ctx:task⟧), the API's real endpoint/fields are anchored, and the rollup
#                                  carries the rest. A verbatim tail here would only re-introduce the finished
#                                  step's distracting signals — the exact thing folding at a boundary clears.
#                                  (Without this, force only lowered the TRIGGER; the completed step stayed
#                                  verbatim in the 6000-tok tail and the view GREW step over step — observed
#                                  live: +14KB / ~350 lines between step 1 and step 2.)
RECOMPACT_TOKENS = 4000          # re-summarize only after the unfolded band grows this much (throttle)
REFOLD_TOKENS = 6000             # when the ACCUMULATED rolling summary itself exceeds this, fold it once
#                                  (rollup-of-a-rollup, deliberately RARE — see the refold tier in compact())
SUMMARY_MARKER = "⟦ctx:rollup⟧"     # tags the injected summary — floor-protected + identifiable
TASK_MARKER = "⟦ctx:task⟧"          # tags the pinned original-task header — the session's north star
FACTS_MARKER = "⟦ctx:facts⟧"        # tags the DURABLE fetch ledger (url→status→endpoints) the loop re-injects
                                    # from cria's own session memory, so the coder keeps the real endpoints it
                                    # already fetched even after the HARNESS compacts the raw result out of its
                                    # own history — else it re-fetches to rediscover them (370-call spec loop).
# (⟦ctx:search⟧ lived here and is gone. It tagged ONE denial — a suppressed search-results read — and
#  the general case is every call cria refuses: cria.denial.DENIED_MARKER now marks all of them, at
#  the sites that decide to refuse. Two markers for one idea is one to keep in sync.)
# cria-SURFACED spec-shape markers — the [API endpoints …] / [response shape …] blocks a web_fetch result
# carries (mirror webfetch.ROUTES_MARKER / SHAPE_MARKER; a test asserts sync). They hold the API's REAL
# endpoint paths + response field names — EXTERNAL ground truth the coder must code against, NOT its own
# mutable identifiers. Anchored so compaction keeps them VERBATIM and the summarizer (which deliberately
# drops identifier names) NEVER folds them — else the exact fields vanish and the coder guesses
# (resolved_addresses → a made-up "cardano_address"), which is a live failure mode.
_SPEC_ROUTES_MARKER = "[API endpoints ("
_SPEC_SHAPE_MARKER = "[response shape —"
# Anchor markers whose messages are ALWAYS kept verbatim — AND, critically, excluded from the
# summarizer input, so cria's OWN prior briefings never become a rollup-of-a-rollup (each round
# summarizing the last round's summary is how a transient hallucination hardened into authoritative
# "Treat this as done" misdirection that inverted the task). ⟦ctx:continuation⟧ (loop's harness-
# compaction reframe) is one such cria-authored summary and MUST be here for the same reason as
# ⟦ctx:briefing⟧. Mirrors loop.BRIEFING_OPEN / loop.CONTINUATION_MARKER / probegate.SECTION_PREFIX
# + webfetch.ROUTES_MARKER / SHAPE_MARKER (selfcompact is low-level; a test asserts sync).
_ANCHOR_MARKERS = ("⟦ctx:briefing⟧", "⟦ctx:continuation⟧", "___CRIA_GATE_", SUMMARY_MARKER, TASK_MARKER,
                   FACTS_MARKER, _SPEC_ROUTES_MARKER, _SPEC_SHAPE_MARKER)


@dataclass
class CompactState:
    summary: str = ""      # the current rolling summary text
    covered: int = 0       # message INDEX the summary represents up to (throttle reference)


def _text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c if isinstance(c, str) else ""


def _msg_tokens(m: dict) -> int:
    t = _text(m)
    for tc in m.get("tool_calls") or []:
        t += " " + str((tc.get("function") or {}).get("arguments") or "")
    return est_tokens(t)


def has_anchor(m: dict) -> bool:
    """Public alias — the harness-compaction path in server.py needs the same exclusion this
    module has always applied to its own summarizer input, and reaching into a private name is how
    two copies of a rule drift apart."""
    return _has_anchor(m)


def _has_anchor(m: dict) -> bool:
    t = _text(m)
    return any(mk in t for mk in _ANCHOR_MARKERS)


def _tail_start(messages: list[dict], head_end: int, budget_tokens: int) -> int:
    """The lowest index i (> head_end) such that messages[i:] fits in ``budget_tokens`` — i.e. the
    recent verbatim working set. Keeps at least one message."""
    acc = 0
    i = len(messages)
    while i > head_end + 1:
        t = _msg_tokens(messages[i - 1])
        if acc + t > budget_tokens:
            break
        acc += t
        i -= 1
    # THE TURN THE MODEL IS ANSWERING IS NEVER THE ONE FOLDED AWAY. The docstring above says "Keeps
    # at least one message" and the loop did not: when the newest message alone exceeds the budget
    # it breaks on its first iteration and returns len(messages) — an EMPTY verbatim tail. That
    # message then lands in `summarizable` and is replaced by the rollup, so the coder is handed a
    # two-message conversation and a summary headed "older turns were elided", about the turn in
    # front of it. Reproduced with a 28 KB file read as the current tool result; any tool result
    # over ~24 KB does it, and at a step boundary the budget is 0 so it happens every time.
    #
    # An oversized present is an overflow for the floor to disclose, not a past to summarise.
    #
    # A budget of ZERO is different and deliberate: at a step boundary the caller means "fold the
    # finished step entirely", supplies the next step in the system message, and keeps no verbatim
    # tail on purpose. That case is left exactly as it was.
    if budget_tokens > 0 and i == len(messages) and len(messages) - 1 > head_end:
        return len(messages) - 1
    return i


# cria's OWN edit-recovery steer (editrecovery.EDIT_MARK — mirrored literal, a test asserts sync).
# Its body is a whole-file "EXACT current content on disk" snapshot that goes STALE by design: the
# live mechanism re-injects the CURRENT content whenever it fires again. Fed whole into the
# summarizer, a weak model preserves it verbatim — measured across 295 rollups: 27 carried a
# fossilized copy, and one prompt (0728-m14 call 0281) held TWO conflicting "EXACT content" claims,
# the rollup's stale one beside the live one. In summarizer INPUT the steer is represented by its
# HEADLINE only — the event survives ("cria provided the file's content after N failed edits"), the
# perishable payload does not.
_EDIT_MARK = "⟦ctx:edit⟧"


def msg_digest(m: dict) -> str:
    """A compact one-line rendering of a message for a summarization transcript: its text plus any
    tool call as ``name(args…)``. Shared by both paths so the rollup input is built the same way."""
    parts = []
    t = _text(m)
    if t.strip():
        if t.lstrip().startswith(_EDIT_MARK):
            t = t.lstrip().splitlines()[0]  # headline only — see _EDIT_MARK above
        parts.append(t)
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        parts.append(f"{fn.get('name', '?')}({str(fn.get('arguments', ''))})")
    return " ".join(p for p in parts if p)


# A HARNESS PREAMBLE BY THE SHAPE OF ITS TAG, not by two literal spellings. It was
# `"<environment_context>" in c or "<user_instructions>" in c` — Codex's two, and nobody else's.
# Cline and Roo send `<environment_details>`; the same idea, a different word.
#
# Both consumers get the question wrong in a way that matters. `contextfloor._protected_mask` picks
# the first NON-preamble user message as the task and protects it — with an unrecognised preamble it
# protects the banner and leaves the real task droppable, which its own docstring records costing
# "53 of 1,475 coder prompts shipped with no task in them, in 8 of 22 sessions". And
# `loop.session_key` keys on the first non-preamble user message: an unrecognised preamble is stable
# across a whole workspace, so every conversation in one repo collides onto ONE `task:` key — which
# `session_key`'s own docstring describes as a fixed bug.
#
# The kernel is the tag NAME: a harness names its preamble for what it is. cria matches an XML-ish
# BLOCK — an opening tag whose name carries `environment`, `instructions`, `system` or `context`,
# and its matching close — which is what every convention observed does.
#
# THE CLOSE IS WHAT KEEPS IT SAFE. A task can legitimately mention such a name: "Fix the bug in
# <Context> so it renders" is a React component, and reading it as a preamble would tell both
# consumers that this message is NOT the task — the exact damage, from the other direction.
# Requiring the closing tag means the match is a block a harness wrapped, not a word a coder typed.
#
# It is still a bound and cria only claims what it reached (#11b): a harness that names its preamble
# something else has its first user message read as the task, which is the right default and is
# exactly what happened before.
_ENV_PREAMBLE_TAG = re.compile(
    r"<\s*([\w.-]*(?:environment|instructions|system|context)[\w.-]*)\s*>"
    r"[\s\S]*?</\s*\1\s*>", re.I)


def is_env_context(m: dict) -> bool:
    """A harness-injected environment/instructions preamble (not the real task) that some
    harnesses prepend as a user message. cria recognizes the known conventions — e.g. Codex's
    `<environment_context>` (cwd/shell/date) and `<user_instructions>` blocks; a harness that
    sends none simply has its FIRST user message treated as the task, which is the right default.

    ONE OWNER. This lived in `loop` while `serialize` below picked the first user-role message with
    no such check, on a comment asserting the harness frame was dropped upstream — which
    `_drop_harness_frame` does not do: it keeps the preamble. So the task the whole transcript is
    judged against was the harness's cwd/shell banner, rendered whole, while the real task was
    treated as ordinary history. loop imports selfcompact and not the reverse, so the owner lives
    here and loop calls it."""
    c = m.get("content")
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    c = c or ""
    return bool(_ENV_PREAMBLE_TAG.search(c))


def serialize(messages: list[dict], defang: bool = False) -> str:
    """The transcript span → one string fed to a model.

    ``defang`` renders the same facts with nothing a model can COPY. Measured over 717 reasoner
    calls in the captures: a prompt demonstrating 0-9 tool-call/output shapes was answered by
    imitating one 1% of the time, 10-29 3%, 30-59 **8%**. The worst case shipped: mellum2
    1786302864 call 0060 was shown tool-call syntax 50 times and tool OUTPUT blocks 24 times, and
    answered with a fabricated `exec_command(...)` plus an invented `Chunk ID`, wall time, exit
    code and `addr1q…` address — which cria then delivered to the coder as a steer, in cria's voice.

    The default rendering is the copyable one: `name({"arg": …})` is a complete template for how to
    open a call, and the harness's `Chunk ID: / Wall time: / Process exited with code / Output:`
    envelope is a complete template for how to fake its result. Defanged, a call reads
    `the coder ran a shell command: pytest -q` and a result reads `→ failed, exit 1: …` — same
    facts, no syntax to continue.

    This is the lesson cria already recorded for the compaction path ("a weak model continues the
    pattern and answers with a tool call, whatever the system prompt says", cria/server.py), where
    the fix was to FLATTEN the history. This path was already flat and still failed, because
    flattening kept the syntax. Flattening was necessary and not sufficient.

    Opt-in, and currently taken only by the steer-author path — the one the 717-call measurement
    covers. The summarizer keeps the verbatim rendering until the same base rate is taken for it
    (#15)."""
    if not defang:
        return "\n".join(f"{m.get('role')}: {msg_digest(m)}" for m in messages)
    # NO LINE NUMBERS. This transcript goes to the steer author, and whatever the author writes goes
    # to the CODER — whose context has no such numbering, because it is cria's private rendering of
    # the author's own view. Numbering the lines invited the author to cite them, and it did:
    # measured on the six-language battery, 15 distinct coder-facing steers referred to "turn 46",
    # "[65]", "turn [15]". One of them ordered "Restore test/test_rates.rb to its previous working
    # state from turn [15]" — an instruction the coder cannot carry out, because turn 15 does not
    # exist anywhere it can see. Every line below already names the file, the command and the error,
    # which ARE things the coder can find, and the lines are in order. Nothing needed the index.
    #
    # No message is privileged any more. This used to single out "the first user-role message" as
    # the one rendered UNCUT, on the belief that the harness frame was dropped upstream — which
    # `_drop_harness_frame` does not do, so on any harness that sends an `<environment_context>`
    # banner the north star was cwd/shell/date. Since nothing here is cut (#5), there is nothing
    # for the exemption to grant, and the wrong assumption goes with it rather than being fixed in
    # place. `is_env_context` remains the one owner of the question for the callers that still ask.
    return "\n".join(line for m in messages if (line := _defanged_line(m)))


# The harness's exec envelope, whose shape is the thing a model copies when it fakes a result.
# `Process exited with code N` is stripped WITH the rest even though the code itself is kept — the
# defanged line already states it as `→ exit N`, so leaving the original both duplicates the fact
# and preserves the exact phrase a model copies when it fabricates a result.
_ENVELOPE = re.compile(r"(?im)^\s*(?:Chunk ID|Wall time|Original token count|Output)\s*:.*$"
                       r"|Process exited with code\s+\d+")
_EXIT = re.compile(r"(?i)Process exited with code\s+(\d+)")


# THE BOUND IS GONE — this block is history, not an instruction.
# It used to keep 200 characters of head and 200 of tail per transcript line, under the old #5,
# whose carve-out read as a blanket licence to bound any prompt cria composes. #5 now reads "cria
# never truncates" for every reader, with de-duplication and a model-made summary as the only
# exceptions, and nothing here clips anything. `_bounded` and the elision marker are deleted; a
# regression test (tests/test_the_transcript_is_never_clipped.py) forbids their return.
#
# Kept because the two failures it records are the reasons the bound was wrong, and both are easy to
# reintroduce. WRONG END: a test runner prints its banner first and its verdict last, so the first
# 400 characters of a run are seed and dots — one run rendered 140 of 140 pytest results to its
# judges as pure banner, and three different commands collapsed to one identical 164-character line,
# after which the steer said "You've run `time mvn exec:java` three times with identical behavior".
# SILENT: with no marker the reader takes the fragment for the whole — a judge shown
# "-> result: … Parallel workers are disabled - turning *" ordered the coder to change that line,
# when the real switch was a field called WORKERS_ENABLED and the verifier reported "0 thread(s)".


def _defanged_line(m: dict) -> str:
    """One transcript entry as PROSE — the facts a supervisor needs, with no copyable syntax.

    NOTHING HERE IS CLIPPED (#5: cria never truncates, and it does not matter that the reader is a
    judge or a steer author rather than the coder). This module used to keep 200 characters of head
    and 200 of tail per line, and it cost three cells of cycle 3 in three different ways: a gate
    result lost the failing test's NAME to cria's own 307-character preamble and the steer named a
    different test; a search result lost every version number and cria invented `v1.32.0`; and the
    flattening below made a reasoner read `cart.go` as one line and call it invalid syntax. Earlier
    still, a task ending "Stop using `float64` for mon" produced an order to DELETE the decimal
    module the task asked for.

    The two allowed exceptions are applied upstream and above, not here: superseded write payloads
    are already STUBBED to their on-disk reference by :func:`stub_old_write_args` (de-duplication),
    and window fit belongs to the context floor, which is lossless-first by construction.

    Every line carries its role prefix; no message is exempt, because no message is cut."""
    role = m.get("role")
    text = _text(m).strip()
    calls = m.get("tool_calls") or []
    if calls:
        bits = []
        for tc in calls:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            try:
                d = jsontext.loads(args) if isinstance(args, str) else (args or {})
            except (ValueError, TypeError, AttributeError):
                d = {}
            detail = "; ".join(f"{k}={v}" for k, v in d.items()) \
                if isinstance(d, dict) else str(args)
            bits.append(f"the coder called {fn.get('name', '?')} — {detail}" if detail
                        else f"the coder called {fn.get('name', '?')}")
        return " / ".join(bits)
    if role == "tool":
        exit_m = _EXIT.search(text)
        body = _program_output(text)
        head = f"→ exit {exit_m.group(1)}" if exit_m else "→ result"
        return f"{head}: {body}" if body else head
    if not text:
        return ""
    who = {"user": "the task/context said", "assistant": "the coder said",
           "system": "the frame said"}.get(role, f"{role} said")
    flat = " ".join(text.split())
    return f"{who}: {flat}"


# The harness prints the program's stdout after a line reading `Output:`. Everything past that
# marker is the program speaking, byte for byte — INCLUDING its blank lines.
_OUTPUT_MARKER = re.compile(r"(?im)^[ \t]*Output[ \t]*:[ \t]*\n")


def _program_output(text: str) -> str:
    """What the program actually printed, with its own blank lines intact — or the cleaned result
    when there is no exec envelope to anchor on.

    AN EMPTY LINE IN stdout IS A VALUE. This used to run the envelope regex over the whole result and
    `.strip()` what was left, which deletes a leading blank line — and a leading blank line is what
    `puts nil` prints.

    Walked on `shipping-rates-rb x ternary-bonsai` 1787111689, the one probe in the run that answered
    the question. The coder ran
    `ruby -e "…; puts c.data[:eu_member]; puts c.name"` and the harness returned:

        Chunk ID: 2abf9d
        Process exited with code 0
        Output:

        France

    The blank line before `France` IS the bug: `data` is string-keyed, so `[:eu_member]` is nil. The
    digest handed to the steer author rendered that whole call as `→ exit 0: France`. The author then
    reasoned "the country lookup works fine in isolation" — a conclusion the deleted line disproves —
    and steered the coder at a different bug. The run ended 3/5 with that one untouched.

    Anchored on the marker rather than on the regex, so the program's output is never re-processed:
    once `Output:` is found, everything after it is passed through and only the envelope's own final
    newline is dropped."""
    m = _OUTPUT_MARKER.search(text or "")
    if m:
        return (text[m.end():]).rstrip("\n")
    return _ENVELOPE.sub("", text or "").strip()


def compaction_request(messages: list[dict], files_list: str = "", gate_plan=None,
                       checks: str = "") -> str:
    """The compactor's user message: the cleaned transcript, the disk, then cria's ask LAST.

    ``gate_plan`` is the live ``probegate.GatePlan``. Every other caller of ``clean_gate_results``
    passes it; this one did not, and the plan is where five facts live — which probe is a hard
    failure (without it, a build that exited non-zero printing only advisory-shaped lines cleans to
    "no error-class problems"), the workspace root that lets a zero-tests result name the stranded
    test file, the untested list, the delimiter facts, and the offline re-run.

    Scope, measured rather than assumed: a RAW gate blob does not currently reach here. Both callers
    filter ``_ANCHOR_MARKERS`` out of the summarizer's input first, and ``___CRIA_GATE_`` is one of
    them — 0 of 70 real self-compact prompts carry a raw marker, and the last gate state is appended
    deterministically instead (``server._last_checks_note``). So this argument changes no output
    today; it exists because the alternative is one caller of four holding a different rule about
    what the cleaner is allowed to be told, which is how the two compaction paths drifted before.

    ``files_list`` is ``groundtruth.workspace_inventory`` — what is on disk RIGHT NOW. Without it
    cria asked a model to describe a workspace it had never been shown, and it filled the gap:
    qwen35/rust 0032 briefed "**Test file created** — `tests/nested_key_lookup.rs` exists", and the
    next prompt's own ground-truth block listed six files, none of them tests/ — that path never
    existed in the run. cria then shipped the invention as ⟦ctx:rollup⟧ and the coder planned against
    it. The existing repair (``loop._briefing_disk_truth``) answers only the opposite direction, a
    briefing that DENIES a file cria can see; it stays exactly as it is. This closes invention at the
    source instead of adding a second corrector after the fact (#1: the bar to ADD is high, and the
    cheapest fix here is giving the writer the fact it was missing).

    Empty string when there is no workspace root — the section is dropped rather than rendered as an
    empty or guessed listing (#5b).

    ONE owner, because having two was the bug. A model obeys the last instruction it reads, so a
    transcript whose final line is the coder's live step ("produce the corrected FULL file in a
    single write_file call") gets obeyed instead of summarized. `da35f4e` fixed that on the harness
    path in server.py; the self-compaction path in loop.py kept the old order and kept failing, and
    on run 20260801T161949 its compactor emitted `write_file({"path": …` and degenerated to
    `v5v5v5…` until the token cap, after which cria adopted a hallucinated unittest file as the
    session summary and the coder believed it.

    Fixing the sibling by copying the two lines would have left a third place to forget. Both callers
    now compose the request here."""
    # SUPERSEDED WRITE BODIES ARE STUBBED HERE TOO. `compact()` already does this to the transcript
    # it EMITS (see the call beside the files list), but the summarizer's INPUT did not — so the
    # model writing the briefing read every old version of every file and put them in it, and the
    # briefing is prompt-LEADING content in the next turn. Measured on the six-language battery,
    # nemotron orders-api-py 0049: the prompt opens with a compacted bullet carrying a full
    # superseded orders/db.py body, and three sentences later the model describes two different
    # versions of the file as "current".
    #
    # One rule, one owner: exactly one verbatim copy of a file region survives, and it is the
    # newest. The bytes of the older ones are on disk, which is the only current version.
    # Evidence, then disk, then the ask — the ask stays LAST for the reason above.
    disk = f"\n\n{files_list.strip()}" if files_list.strip() else ""
    # …AND THE CHECKS, for the reason the disk is here — one step further along the same argument.
    # A writer shown no workspace invents one; a writer shown no BUILD RESULT invents one too, and
    # both halves were being appended to its OUTPUT instead of given to it as input.
    #
    # Walked on feed-pipeline-java x qwen35 1787249436. The briefing at minute 26 says "The build
    # compiles successfully" while its own transcript carries `cannot find symbol / symbol: class
    # Action` eight times and `exited with code 1` twice. The briefing at minute 8 makes the same
    # error in the other direction: it reports a ConcurrentModificationException that had been fixed
    # 99 seconds earlier and never re-run, and the coder burned eight calls disproving it
    # ("the summary says it fails … but my test shows it works"). Dropped and invented are one
    # defect, not two: the writer was asked to work out the build state by READING, which is a fact
    # cria already holds exactly (#8 — deterministic code gathers, the reasoner judges).
    #
    # A VETO ON THE OUTPUT WAS THE OBVIOUS FIX AND IT IS THE WRONG ONE. Refusing a briefing sentence
    # that contradicts the gate treats the symptom and leaves the writer guessing on every sentence
    # nobody thought to check. Given the result up front it has no reason to guess (#4: fix upstream,
    # not at the point of damage).
    #
    # Empty when no gate has spoken or the last one was clean — the section is dropped rather than
    # rendered as an empty or guessed verdict (#5b, #3), the same rule the disk section follows.
    #
    # The RAW verdict comes in and the framing is applied HERE, so both compaction paths cannot
    # disagree about whether their argument is already rendered (#23, one owner).
    known = f"\n\n{checks_input(checks)}" if checks_input(checks) else ""
    return (serialize(stub_old_write_args(probegate.clean_gate_results(messages, gate_plan)))
            + disk + known + "\n\n" + prompts.load("compact_closing_ask"))


def checks_input(flag: str) -> str:
    """The last gate verdict, framed for the compactor's INPUT — "" when no gate has spoken.

    Distinct from the note the same verdict gets as an OUTPUT appendix: that one tells the READER
    what the checks said, this one tells the WRITER not to derive build state from the transcript.
    Same fact, two jobs, so two strings (#22, both in prompt files)."""
    return prompts.render("compact_checks_known", flag=flag.strip()) if (flag or "").strip() else ""


def _summary_msg(summary: str) -> dict:
    # This rolls up MID-work turns (the work is NOT necessarily finished) — unlike the loop's
    # completion compaction, which summarizes genuinely-done work. So it must NOT stamp "treat this as
    # done": that blanket done-assertion drove premature completion and suppressed re-doing needed work
    # (the model coasted to "done" over an unresolved pyproject blocker; a summary saying "I fetched the
    # spec" made it skip re-fetching). Frame it truthfully as CONTEXT, and defer to the live results:
    # anything unfinished/failing/blocked still needs doing.
    # NB: do NOT promise verbatim turns "below". At a verified step boundary the tail budget is
    # BOUNDARY_KEEP_TAIL_TOKENS = 0, so this summary is the LAST message and nothing follows it — the
    # old wording sent the model to look for ground truth that was not there, and the one thing it
    # then had was the summary it had just been told not to trust. Defer to the live workspace, which
    # is always there, instead of to a position in the transcript.
    return {"role": "user", "content": (
        f"{SUMMARY_MARKER} Summary of your earlier turns this session (older turns were elided to keep "
        f"you focused). Use it as CONTEXT so you don't re-derive what you already worked out — but it "
        f"is a summary, NOT a statement that the task is done: anything it describes as unfinished, "
        f"failing, or blocked still needs doing. Where a real tool result or the files on disk "
        f"disagree with it, those are the ground truth — read them rather than trusting this:\n{summary}")}


def _task_msg(task: str) -> dict:
    return {"role": "user", "content": (
        f"{TASK_MARKER} Your ORIGINAL task for this session — keep it as your north star and do NOT "
        f"drift onto tangential work; everything below serves THIS:\n{task}")}


FILES_MARKER = "⟦ctx:files⟧"        # tags the post-compaction workspace files list (caller-supplied)

# --- Rollup echo-guard. The summarizer input is built by serialize() in a FRAME cria authors
# ("role: text", the harness exec envelope, think tags). A weak compactor ECHOES that frame instead
# of summarizing (measured: 20/295 rollups carried raw "Chunk ID" plumbing; p90 rollup 17K, max
# 29.8K). Lines matching cria's OWN frame are BY CONSTRUCTION echo, not summary prose — dropping
# them is deterministic housekeeping of cria's own artifacts, never a judgment on model prose.
_FRAME_ECHO_RE = re.compile(
    r"^(?:(?:system|user|assistant|tool):\s"      # serialize()'s role prefix
    r"|Chunk ID:|Wall time:|Process exited with code|Original token count:"  # exec envelope
    r"|</?think>\s*$"                             # leaked think tags
    r"|<\|im_start\|>|<\|im_end\|>)")          # raw template markers


# A line long enough that matching cria's own ask verbatim cannot be coincidence. Short lines
# ("Do this.", a bare heading) can legitimately collide; a full sentence cannot.
_ECHO_MIN_CHARS = 40


def _ask_sentences(ask: str) -> list[str]:
    """cria's own instruction, split into comparable sentences."""
    out = []
    for raw in re.split(r"(?<=[.!?])\s+|\n", ask or ""):
        t = " ".join(raw.split())
        if len(t) >= _ECHO_MIN_CHARS:
            out.append(t)
    return out


def strip_frame_echo(summary: str, ask: str = "") -> str:
    """Drop summarizer-output lines that echo cria's own serialization frame (see _FRAME_ECHO_RE) or,
    when ``ask`` is given, cria's own INSTRUCTION text. Returns the cleaned summary; a summary that
    was ALL echo comes back empty, and compact() then fails safe exactly as it does on an empty
    summary (fold nothing, keep every turn verbatim).

    The instruction clause is measured, not anticipated. Run 20260801T161949 (mellum2, ada-handles,
    0/4): the compactor at call 0062 produced a briefing that was mostly cria's own ask quoted back
    at itself, and cria injected it whole. Counted in the coder's prompt at 0063 — 68,914 characters,
    of which the continuation block was 54,274 (79%):

        "Do not emit a tool/function call"  x145
        "What you should say instead"       x47

    Both are cria's words, from selfcompact_summary.txt. The coder read them and said so — *"This is
    contradictory. The continuation says 'fix search_handles' which IS writing code. The continuation
    also says 'Do not write code.'"* — and emitted no tool call. It never fully recovered: at 0084,
    twenty calls later, the coder's own answer to the user still ENDED with that block, and the same
    text reappears verbatim at 0089 and 0207. Every compaction after the first collapsed the same
    way (0087, 0118, 0161, 0204).

    cria composed the ask, so this needs no judgment: a line of the "summary" that is cria's own
    sentence is not a summary of anything."""
    drop = _ask_sentences(ask)
    kept = []
    for ln in summary.splitlines():
        t = ln.strip()
        if _FRAME_ECHO_RE.match(t):
            continue
        flat = " ".join(t.split())
        if len(flat) >= _ECHO_MIN_CHARS and any(d in flat or flat in d for d in drop):
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


# --- Older write-args → on-disk references (operator's design, run 0728-m14: post-compaction the
# coder does not need file CONTENT in old turns — the disk + the files list + read_file carry it;
# only the LAST tool call keeps its full arguments). Applies ONLY to the model's OWN write arguments
# (content it emitted, now durably on disk) — tool RESULTS the model read are never touched
# (never-truncate). Mirrors writeproxy's write-tool names; a test asserts sync.
# ONE OWNER (#23). These were three lists in three modules — four names here, six in contextfloor,
# two here — so whether a call counted as a write depended on which module was asked. The one that
# matters for "which write is current" is `toolargs.WHOLE_FILE_WRITES`: a partial edit is not a
# version of a file and may not supersede one.
_WRITE_TOOL_NAMES = toolargs.WRITE_TOOL_NAMES
# `old_string` is here for the same reason the others are: the whole call is historical. Leaving
# it out rendered a past edit as the BEFORE in full and the AFTER as a pointer — the reader
# saw what the code used to be and never what it became. It gets its own wording (see
# compact_view.write_stub_replaced) because a replaced fragment is not a version of the file.
_WRITE_ARG_KEYS = ("content", "new_string", "old_string")
_REPLACED_ARG_KEYS = ("old_string",)
_STUB_MIN_CHARS = 400


# A write that landed confirms in one of two shapes: the raw heredoc token (writeproxy._WROTE,
# pre-render) or the model-facing render of prompts/write_confirm ("Wrote <path>") that transcripts
# actually carry. Anything else — an ⟦ctx:editfail⟧ report, a denial, an error — did NOT reach
# disk. Kept in sync with both owners by tests.
_WROTE_HEAD = "⟦ctx:wrote⟧"


def write_landed(result_text: str) -> bool:
    head = prompts.render("write_confirm", path="").strip()
    t = result_text.lstrip()
    return _WROTE_HEAD in result_text or (bool(head) and t.startswith(head))


def _is_write_call(tc: dict) -> bool:
    """Is this tool call a WRITE? The same `_WRITE_TOOL_NAMES` set the stubber keys on, so "which
    turn is the live working set" and "which arguments get stubbed" can never answer differently."""
    return ((tc or {}).get("function") or {}).get("name") in _WRITE_TOOL_NAMES


def _last_write_index_by_path(msgs: list[dict]) -> dict:
    """path -> index of the LAST write-tool call that targeted it.

    `stub_old_write_args` kept ONE index for the whole span, so every older write was stamped with
    the on-disk wording whatever path it touched. A coder that writes one file three times produced
    three "this exact content is on disk at PATH" stamps for that path, two of them false — measured
    at six stamps and four different byte counts for a single Ruby file in one real prompt (#5b)."""
    out: dict = {}
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        for tc in (m.get("tool_calls") or []):
            # EVERY write call, partial edits included. This index answers "is this the NEWEST call
            # to this path", which is the question the stubber asks — an older `edit_file` is just as
            # historical as an older `write_file` and its payload is folded for the same reason
            # (see the module note on `old_string`). That is a different question from "does this
            # call supersede a whole-file write", which only `toolargs.write_target`'s second value
            # may answer; `focustrim` asks that one, because there it decides a DELETION.
            if not _is_write_call(tc):
                continue
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "")
            except ValueError:
                continue
            if isinstance(args, dict):
                out[str(args.get("path") or args.get("file_path") or "?")] = i
    return out


def _stub_write_args(m: dict, landed=None, idx: int = -1, last_by_path: dict | None = None) -> dict:
    """A COPY of message ``m`` with big write-tool argument bodies replaced by an elision stub.

    ``landed`` maps tool_call_id -> bool (the paired tool result confirmed the write). The on-disk
    stub is a CLAIM — "this exact content is on disk" — and stamping it on a refused edit states a
    false fact (rule 5b): walked on mellum2 1786196176, call 0182's refused new_string was elided as
    "on disk", two reasoner prompts repeated it, and the 0144 steer told the coder the fix had
    landed. A refused write gets the refused stub; an UNKNOWN outcome (no paired result in the span)
    keeps the full text rather than risk either claim. Returns ``m`` unchanged when nothing
    qualifies."""
    changed = False
    new_calls: list = []
    stub_notes: list[str] = []
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or ""
        if fn.get("name") not in _WRITE_TOOL_NAMES:
            new_calls.append(tc); continue
        try:
            args = json.loads(raw)
        except ValueError:
            new_calls.append(tc); continue
        if not isinstance(args, dict):
            new_calls.append(tc); continue
        path = str(args.get("path") or args.get("file_path") or "?")
        outcome = (landed or {}).get(tc.get("id"))
        if outcome is None:
            new_calls.append(tc); continue      # no paired result → no claim in either direction
        if not outcome:
            stub_key = "write_stub_refused"
        elif last_by_path is not None and last_by_path.get(path, idx) != idx:
            stub_key = "write_stub_superseded"   # it landed, then a later write replaced it
        else:
            stub_key = "write_stub"
        notes, touched = [], False
        for key in _WRITE_ARG_KEYS:
            v = args.get(key)
            if isinstance(v, str) and len(v) >= _STUB_MIN_CHARS:
                # A replaced FRAGMENT gets its own sentence — calling it "an earlier version of
                # <path>" would be a small false fact about what the model is looking at.
                words = prompts.load_map("compact_view")
                use = "write_stub_replaced" if key in _REPLACED_ARG_KEYS and stub_key != "write_stub_refused" else stub_key
                # THE SENTENCE DOES NOT GO WHERE A FILE BODY GOES. It used to replace the argument
                # in place, which puts cria's prose in the exact slot a file's content occupies —
                # and models read it as content and wrote it back. `focustrim` records the incident
                # (feed-pipeline-java x qwen35, call 0095: a 357-line file became one line of cria's
                # note, `javac` answered `illegal character: '\u2014'`, recovery was git checkout to
                # the seed) and the operator's ruling on it, 2026-08-19: "There is not supposed to
                # be any elision. It's all or nothing." Reproduced across five more sessions and
                # five languages. So the payload LEAVES, and what cria has to say about it is said
                # in the assistant turn's own prose, beside the call — the same place focustrim puts
                # its note, and a place no file body ever occupies.
                notes.append(prompts.fill(words[use], chars=str(len(v)), path=path))
                del args[key]
                touched = True
        if touched:
            changed = True
            new_calls.append({**tc, "function": {**fn, "arguments": json.dumps(args)}})
            stub_notes.extend(notes)
        else:
            new_calls.append(tc)
    if not changed:
        return m
    out = {**m, "tool_calls": new_calls}
    if stub_notes:
        existing = out.get("content")
        out["content"] = "\n".join(([existing] if isinstance(existing, str) and existing else [])
                                    + stub_notes)
    return out


def _write_outcomes(msgs: list[dict]) -> dict:
    """tool_call_id -> did the paired tool result confirm the write reached disk."""
    landed: dict = {}
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "tool" or m.get("type") == "function_call_output":
            tid = m.get("tool_call_id") or m.get("call_id")
            c = m.get("content") if m.get("content") is not None else m.get("output")
            if tid and isinstance(c, str):
                landed[tid] = write_landed(c)
    return landed


def stub_old_write_args(msgs: list[dict]) -> list[dict]:
    """Post-compaction view of a message span: every write-tool call OLDER than the last tool-call
    turn gets its big argument bodies replaced by an elision stub — the on-disk reference for a
    write that landed, the refused form for one that did not; the LAST tool-call turn keeps its
    full arguments (the live working set). Copies — never mutates the caller's messages."""
    # THE LAST *WRITE*, NOT THE LAST TOOL CALL. "Keep the live working set" means keep the newest
    # thing the coder WROTE; the old rule kept whatever turn happened to be last, and cria's own gate
    # probe is a tool call. When a gate ran last — which is often, it fires on a timer — every write
    # in the span was stubbed and the briefer saw no source at all.
    #
    # Measured, orders-api-py x ternary-bonsai: the route's 2,579 characters were replaced by cria's
    # own `[elided … this exact content is on disk]`, and the briefing then reconstructed the route's
    # behaviour from the task text and the test file's assertions — asserting it returned an `orders`
    # array and a `total_value`, when it returned neither. That sentence rode 37 later prompts.
    # Across cycle 1: 20 briefings assert behaviour of the coder's own work, 9 of them falsely.
    #
    # cria replacing source with cria's own claim, and a model then describing what the source must
    # have done, is the shape of #5b at one remove.
    landed = _write_outcomes(msgs)
    last_write = max((i for i, m in enumerate(msgs)
                      if any(_is_write_call(tc) for tc in (m.get("tool_calls") or []))), default=None)
    last_by_path = _last_write_index_by_path(msgs)
    return [m if (i == last_write or not m.get("tool_calls"))
            else _stub_write_args(m, landed, i, last_by_path)
            for i, m in enumerate(msgs)]


def compact(messages: list[dict], summarize, state: CompactState, *,
            trigger_tokens: int = TRIGGER_TOKENS_DEFAULT, keep_tail_tokens: int = KEEP_TAIL_TOKENS,
            recompact_tokens: int = RECOMPACT_TOKENS, pinned_task: str = "", force: bool = False,
            boundary_keep_tail_tokens: int = BOUNDARY_KEEP_TAIL_TOKENS,
            files_list: str = "", refold=None,
            refold_tokens: int = REFOLD_TOKENS, rlog=None) -> tuple[list[dict], CompactState, bool]:
    """Return (messages, state, applied?). ``summarize(list[dict]) -> str`` folds the old middle into
    a briefing (injected so this is testable without a model). No-op (same list) at/below the token
    trigger, or when there is no middle to compact (the recent tail already spans everything).

    ``force`` (the plan loop passes it at a STEP BOUNDARY) both lowers the trigger AND shrinks the kept tail
    to ``boundary_keep_tail_tokens`` (0 by default → NO verbatim tail) — so the just-verified step's work
    folds ENTIRELY into the ⟦ctx:rollup⟧ (it IS the working-set tail, which a mere trigger drop left verbatim,
    so the view grew step over step). Nothing is lost at a boundary: the next step rides in the caller's
    system message, ``pinned_task`` re-anchors the original task, and anchored messages — a surfaced spec's
    real endpoint/fields (_SPEC_*_MARKER) and cria's own briefings — survive folding VERBATIM. (A boundary
    therefore REQUIRES the caller to pass ``pinned_task``, or the task would fold with the rest.)

    ``pinned_task`` (the conversation's ROOT task, supplied by the caller — it alone can detect the
    task past the harness env-context/reframe) is re-emitted verbatim as a ⟦ctx:task⟧ header on every
    compacted view. Without it the task — a plain user message with no anchor marker — falls into the
    summarizable middle and ERODES across rounds (round 2's rollup summarizes round 1's rollup), which
    is how a plan-off session lost its goal and drifted onto tangential build/deploy work. Pinning it
    keeps the north star authoritative and immune to summary degradation."""
    # At a STEP BOUNDARY keep only a SMALL verbatim tail (boundary_keep_tail_tokens) so the just-finished
    # step's work FOLDS into the rollup; otherwise keep the full working-set tail. force also lowers the
    # trigger so a boundary compacts even below the size trigger (but never a trivial view that fits the tail).
    eff_keep_tail = boundary_keep_tail_tokens if force else keep_tail_tokens
    threshold = eff_keep_tail if force else trigger_tokens
    if sum(_msg_tokens(m) for m in messages) <= threshold:
        return messages, state, False
    head_end = 1 if messages and messages[0].get("role") == "system" else 0
    tail_start = _tail_start(messages, head_end, eff_keep_tail)
    if tail_start <= head_end:
        return messages, state, False

    band_tokens = (sum(_msg_tokens(m) for m in messages[state.covered:tail_start])
                   if head_end <= state.covered <= tail_start else None)
    if not state.summary or band_tokens is None or band_tokens >= recompact_tokens:
        # TRULY ROLLING (operator-driven, first 27B): summarize only the NEW band — the turns past
        # what the existing summary already covers — and APPEND the increment. The old shape
        # re-summarized the ENTIRE middle every round into one REPLACING summary, which (a) squeezed
        # a whole session's folded history into one output budget (the squeeze the operator called
        # ridiculous — it saturated exactly when the session was long enough to need it most), and
        # (b) re-paid the full summarization wall-clock every round (13+ min observed at ~7 tok/s).
        # Incremental: each increment is bounded by the summarizer's output cap, the TOTAL summary
        # grows with the session, and earlier increments are never re-generated. When ``covered`` is
        # unusable (compaction state lost / indices shifted), fall back to the whole middle — the
        # old behavior, correct just slower.
        lo = state.covered if (state.summary and band_tokens is not None) else head_end
        summarizable = [m for m in messages[lo:tail_start] if not _has_anchor(m)]
        if summarizable:
            fresh = strip_frame_echo(summarize(summarizable), prompts.load("selfcompact_summary"))
            # An EMPTY summary must NEVER be adopted. ``summarize`` returns "" on a failed/empty compactor
            # call (it happens — a reasoning model can burn its budget thinking and emit no content), and
            # taking it would advance ``covered`` to tail_start: every folded turn replaced by a rollup
            # header with nothing under it. At a step BOUNDARY (keep NO tail) that is the whole session's
            # work history destroyed by one bad model call — the exact undetectable lie never-truncate
            # exists to prevent. Fail SAFE: fold nothing, keep every turn verbatim, and let the context
            # floor (the one lossless window-fit point) size the request.
            if not fresh.strip():
                return messages, state, False
            combined = (state.summary + "\n\n" + fresh) if (state.summary and lo > head_end) else fresh
            # REFOLD TIER (operator: append-only just moves the unbounded growth into the summary —
            # over a long session the accumulated increments would themselves overtake the window,
            # and the rollup is anchor-protected so nothing else ever shrinks it). When the
            # accumulated summary crosses REFOLD_TOKENS, fold IT once via ``refold``. This is the
            # rollup-of-a-rollup the old code rightly feared — but the fear was doing it EVERY round
            # (compounding degradation); at a ~3× increment threshold it happens once per ~6K summary
            # tokens, bounding degradation to a handful of generations across a whole session. A
            # failed/empty refold keeps the un-refolded text (fail-safe: too long beats gone).
            if refold is not None and est_tokens(combined) >= refold_tokens:
                folded = strip_frame_echo(refold(combined), prompts.load("selfcompact_refold"))
                if folded.strip():
                    combined = folded
            state = CompactState(summary=combined, covered=tail_start)

    covered = max(head_end, min(state.covered, tail_start))
    # Kept verbatim, never elided — but IDENTICAL copies collapse to the first. Each ⟦ctx:denied⟧
    # reply to a repeated whole-spill read re-embeds the spec digest, and the digest contains the
    # _SPEC_*_MARKERs, so every copy classified as an anchor: nemotron-nano 1786243834 carried the
    # same 7,216-char denial SIX times in one 61K step frame (the prompt the coder answered with
    # prose instead of a write). The anchor guarantee is ONE verbatim surviving copy; byte-identical
    # repeats add zero information and drown the frame for a small model.
    anchors, dup_anchors = _dedup_identical([m for m in messages[head_end:covered] if _has_anchor(m)])
    if dup_anchors and rlog is not None:
        # Every sibling dedup in cria emits its count (context.ledger_dedup, context.focus_trim,
        # context.deorphaned); a silent drop makes a future misfire invisible in the run log.
        rlog.emit("context.anchor_dedup", reshape="dedup", dropped=dup_anchors)
    band = messages[covered:tail_start]                                   # old-but-unfolded, verbatim
    # The pinned task leads the compacted view (right after cria's system prompt) so the north star is
    # the first thing the coder reads — never summarized, re-emitted fresh from the caller each turn.
    task = [_task_msg(pinned_task)] if pinned_task.strip() else []
    # The caller-supplied FILES LIST (operator's design): the compacted view carries what EXISTS —
    # names + sizes — not the bytes; read_file is the road back to any content. Refreshed each
    # compaction (any prior copy is filtered out of every kept segment above via _not_stale_files).
    files = ([{"role": "user", "content": files_list}] if files_list.strip() else [])
    working = band + messages[tail_start:]
    working = stub_old_write_args([m for m in working if not _is_files_msg(m)])
    anchors = [m for m in anchors if not _is_files_msg(m)]
    # NO summary, NO rollup header. The empty-summary guard above covers the case where the compactor
    # ANSWERED with nothing; this covers the other way in — a middle made entirely of anchored messages
    # leaves nothing summarizable, `summarize` is never called, and `state.summary` is still "". The
    # header was emitted anyway: a paragraph telling the coder this is its summary of earlier turns and
    # to read the disk where the summary disagrees, followed by nothing. cria asserting a record exists
    # when it holds none, in the message that IS the record.
    rollup = [_summary_msg(state.summary)] if state.summary.strip() else []
    out = messages[:head_end] + task + files + anchors + rollup + working
    return out, state, True


def _dedup_identical(msgs: list[dict]) -> tuple[list[dict], int]:
    """Identical anchor messages collapse to the first occurrence → ``(kept, dropped_count)``.
    Order and bytes of every distinct message are untouched.

    The key is :func:`msg_digest`, which covers the tool CALL as well as the text. Keying on text
    alone would fold two anchors that differ only in their tool_calls, and the survivor's sibling
    call would vanish from the view entirely — anchors are excluded from the summarizer input, so
    nothing downstream would carry it. (Prevalence of that shape today: zero across 17,912 captured
    coder bodies — no anchor message carries tool_calls at all. Keyed correctly anyway, because the
    cost is one function call and the failure is silent.)

    Exact match only: two renderings of the same fact are NOT the same message, and deciding they
    mean the same thing would be a judgment this function must not make."""
    seen: set[str] = set()
    out, dropped = [], 0
    for m in msgs:
        key = msg_digest(m)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(m)
    return out, dropped


def _is_files_msg(m: dict) -> bool:
    """A previously injected ⟦ctx:files⟧ list — stale the moment a newer one exists; filtered so
    exactly ONE (the fresh one) rides each compacted view."""
    c = m.get("content")
    return isinstance(c, str) and c.lstrip().startswith(FILES_MARKER)
