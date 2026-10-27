"""Source-owned generation intervention lifecycles, separate from transport integrity.

F48 owns role reasoning detection, per-stream backstops, and abort recovery. F09
owns cut-output notices/retries. Transport parsing, action quarantine and literal
argument assembly remain foundations, not optional success/recovery policies.
No transport, filesystem access, global mutable state, or imports from the driver.
"""
from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Callable, Iterable, Protocol

from . import bodykeys, callliterals, callsyntax, generation, prompts, reasoning
from .assistcontract import ExecutableDefinition, Policy, Reference


RUMINATION_MARKERS = (
    "actually", "wait", "but wait", "hold on", "hmm", "let me reconsider", "on second thought",
    "let me think again", "or maybe", "or perhaps", "rethinking", "reconsider", "going back",
    "scratch that", "nope", "let me re-examine", "let me reexamine", "let me revisit",
    "i'm overthinking", "am i overthinking", "let me start over", "wait no", "actually no",
)
DEFAULT_MARKER_RATE_PER_1K = 10.0
MIN_MARKERS = 6
DEFAULT_REASONING_BUDGET = 4096
DEGENERATE_RUN_CHARS = 2048
MIN_DEGENERATE_REPEATS = 3
DEAD_STREAM_SECONDS = 180.0
DEAD_STREAM_CHUNKS = 400
WINDOW_EXHAUSTED_FRACTION = 0.92
WIDE_RUN_CHARS = 32768
WIDE_EVAL_STRIDE = 2048
WIDE_MIN_CHARS = 8192
WIDE_PROBE_CHARS = 512
WATCH_STRIDE = 400
MAX_RUMINATION_RETRIES = 3
MAX_TRUNCATION_RETRIES = 3
_MARKERS = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in sorted(RUMINATION_MARKERS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def count_markers(text: str) -> int:
    return len(_MARKERS.findall(text or ""))


def estimate_reasoning_tokens(text: str) -> int:
    return len(text or "") // 4


class Detector:
    """Pure role-scoped detector; no stream/session memory can leak between calls."""
    def __init__(self, budget: int, rate_per_1k: float = DEFAULT_MARKER_RATE_PER_1K):
        self.budget = budget if budget and budget > 0 else DEFAULT_REASONING_BUDGET
        self.rate_per_1k = max(float(rate_per_1k), 0.1)

    @classmethod
    def from_reasoning_budget(cls, budget: int | None):
        return cls(budget if budget else DEFAULT_REASONING_BUDGET, DEFAULT_MARKER_RATE_PER_1K)

    def budget_gate(self) -> int:
        return self.budget // 2

    def check(self, reasoning_so_far: str, reasoning_tokens: int) -> dict | None:
        text, tokens = reasoning_so_far, reasoning_tokens
        if tokens < self.budget_gate():
            return None
        hits = count_markers(text)
        dense = hits >= MIN_MARKERS and (hits / max(tokens, 1)) * 1000 >= self.rate_per_1k
        if dense or tokens >= self.budget:
            return {"hits": hits, "reasoning_tokens": tokens, "arm": "second_guessing" if dense else "length"}
        return None


def _smallest_period(text: str) -> int:
    n = len(text)
    if n < 2:
        return n
    fail, k = [0] * n, 0
    for i in range(1, n):
        while k and text[i] != text[k]:
            k = fail[k - 1]
        if text[i] == text[k]:
            k += 1
        fail[i] = k
    return n - fail[n - 1]


def degenerate_tail(text: str, window: int = DEGENERATE_RUN_CHARS) -> bool:
    if len(text) < window:
        return False
    tail = text[-window:]
    return len(set(tail)) == 1 or _smallest_period(tail) <= len(tail) // MIN_DEGENERATE_REPEATS


def degenerate_wide(text: str) -> bool:
    if len(text) < WIDE_MIN_CHARS:
        return False
    tail = text[-WIDE_RUN_CHARS:]
    probe = tail[-WIDE_PROBE_CHARS:]
    prev = tail.rfind(probe, 0, len(tail) - WIDE_PROBE_CHARS)
    if prev < 0:
        return False
    period = len(tail) - WIDE_PROBE_CHARS - prev
    if period < 1 or period * MIN_DEGENERATE_REPEATS > len(tail):
        return False
    run = tail[-period * MIN_DEGENERATE_REPEATS:]
    return all(run[i] == run[i - period] for i in range(period, len(run)))


class Log(Protocol):
    phase: str
    def emit(self, event: str, **fields) -> None: ...


def _event(log: Log, definition, event: str, **fields) -> None:
    log.emit(event, assist_id=definition.policy.id, family_id=definition.policy.family_id, **fields)


class StreamStatus(Enum):
    CONTINUE = "continue"
    ABORT = "abort"


@dataclass(frozen=True)
class StreamResult:
    status: StreamStatus
    verdict: dict | None = None


@dataclass(frozen=True)
class StreamInput:
    window: int | None
    prompt_tokens: int
    window_guessed: bool
    # None for seats such as the reasoner: backstops remain active, phrase/length
    # detection does not. A disabled F48 never constructs or feeds a stream guard.
    watch: Callable[[str, int], dict | None] | None = None


class StreamGuard:
    """One call's counters/tails. The transport supplies only factual frame/read services.

    Feed each parsed, non-error SSE object once (including usage-only objects),
    after the transport has assembled its deltas. On ABORT close the response and
    assemble a quarantined completion with this exact verdict, never action prefixes.
    """
    def __init__(self, source: StreamInput):
        self.room = max(0, (source.window or 0) - source.prompt_tokens) if source.window and not source.window_guessed else 0
        self.watch = source.watch
        self.frames = self.chars = self.watched_len = self.wide_evaled = 0
        self.tail = self.wide_tail = ""
        self.aborted = None

    def feed(self, frame: dict, elapsed: Callable[[], float], reasoning_text: Callable[[], str],
             content_text: Callable[[], str], log: Log) -> StreamResult:
        if self.aborted is not None:
            return StreamResult(StreamStatus.ABORT, self.aborted)
        self.frames += 1
        for choice in frame.get("choices", []):
            delta = choice.get("delta") or {}
            rc = delta.get("reasoning_content") or delta.get("reasoning")
            for frag in (delta.get("content"), rc,
                         *(((tc.get("function") or {}).get("arguments")) for tc in (delta.get("tool_calls") or []))):
                if frag:
                    self.tail = (self.tail + frag)[-DEGENERATE_RUN_CHARS:]
                    self.wide_tail = (self.wide_tail + frag)[-WIDE_RUN_CHARS:]
                    self.chars += len(frag)
        verdict = None
        fields = {}
        if self.room > 0 and self.frames >= self.room * WINDOW_EXHAUSTED_FRACTION:
            verdict = {"window_exhausted": True, "room": self.room, "frames": self.frames}
            fields = dict(verdict)
        elif self.chars == 0 and self.frames >= DEAD_STREAM_CHUNKS:
            verdict = {"dead_stream": True, "chunks": self.frames}
            fields = dict(verdict)
        elif self.chars == 0 and elapsed() >= DEAD_STREAM_SECONDS:
            verdict = {"dead_stream": True, "chunks": self.frames, "seconds": round(elapsed(), 1)}
            fields = dict(verdict)
        # Schedule from generated characters; the bounded evidence ring stops growing.
        if verdict is None and self.chars - self.wide_evaled >= WIDE_EVAL_STRIDE:
            self.wide_evaled = self.chars
            if degenerate_wide(self.wide_tail):
                verdict = {"degenerate": True, "chars": len(self.wide_tail)}
                fields = {**verdict, "wide": True}
        if verdict is None and degenerate_tail(self.tail):
            verdict = {"degenerate": True, "chars": len(self.tail)}
            fields = dict(verdict)
        if self.watch is not None and verdict is None:
            text = reasoning_text() or content_text()
            if len(text) - self.watched_len >= WATCH_STRIDE:
                self.watched_len = len(text)
                verdict = self.watch(text, len(text) // 4)
                if verdict:
                    fields = {"hits": verdict.get("hits"), "reasoning_tokens": verdict.get("reasoning_tokens")}
        if verdict:
            self.aborted = verdict
            _event(log, RUNAWAY, "rumination.abort", steer="rumination", level="warn", **fields)
            return StreamResult(StreamStatus.ABORT, verdict)
        return StreamResult(StreamStatus.CONTINUE)

    def wire_timeout(self, elapsed: float, error: str, log: Log) -> StreamResult:
        # The actual socket deadline remains transport-owned, including when this
        # optional policy is disabled. Only a selected policy converts it to recovery.
        verdict = {"dead_stream": True, "chunks": self.frames, "seconds": round(elapsed, 1), "wire": True}
        self.aborted = verdict
        _event(log, RUNAWAY, "rumination.abort", steer="rumination", level="warn", dead_stream=True, wire=True,
               chunks=self.frames, seconds=verdict["seconds"], error=error)
        return StreamResult(StreamStatus.ABORT, verdict)


class RecoveryStatus(Enum):
    """Generation-local outcomes, never evidence that the user's task is done."""
    UNCHANGED = "unchanged"
    RECOVERED = "recovered"
    EXHAUSTED = "exhausted"
    IDENTICAL = "identical-retry-withheld"
    REFUSED = "refused"


@dataclass(frozen=True)
class RecoveryResult:
    completion: dict
    status: RecoveryStatus
    # Existing guard-iteration count, not a reconstructed provider-call count:
    # the identical-retry arm counts the iteration whose request it withholds.
    attempts: int = 0


@dataclass(frozen=True)
class RecoveryInput:
    completion: dict
    body: dict
    step: int | None = None
    phase: str = "coder"


class Role(Protocol):
    reasoning: str | None
    think_protocol: str


@dataclass(frozen=True)
class RetryServices:
    chat: Callable[[dict, Log], bytes]
    parse: Callable[[bytes], dict]
    add_note: Callable[[dict, str], None]
    log: Log
    coder_role: Role | None = None

    def retry(self, body: dict, tools) -> dict:
        # massage imports runtime registrations; do not pull that graph into the
        # source definition module while those registrations are being built.
        from . import massage
        return massage.apply(self.parse(self.chat(body, self.log)), tools, self.log)


@dataclass(frozen=True)
class ReadResult:
    position: int
    path: str
    start: int | None
    end: int | None
    text: str


@dataclass(frozen=True)
class GroundedNoticeServices:
    # These adapters only read existing checker/history facts; no judge or policy callbacks.
    gate_unedited: Callable[[], bool]
    gate_lines: Callable[[], list[tuple[str, str, int]]]
    reads: Callable[[list[dict]], list[ReadResult]]
    read_span: Callable[[int | None, int | None, str], tuple[int, int | None] | None]
    same_file: Callable[[str, str], bool]
    # True includes unknown mutation targets. Never treat unknown as an unchanged file.
    mutated_after: Callable[[list[dict], int, str], bool]


def grounded_next_step(messages: list[dict], services: GroundedNoticeServices | None) -> str:
    if services is None or not services.gate_unedited():
        return ""
    for raw, path, line in services.gate_lines():
        for item in services.reads(messages):
            if not services.same_file(item.path, path):
                continue
            span = services.read_span(item.start, item.end, item.text)
            if span is None:
                continue
            last = span[1] if span[1] is not None else len(item.text.rstrip("\n").split("\n"))
            if not span[0] <= line <= last or services.mutated_after(messages, item.position, path):
                continue
            return prompts.render("rumination_next_step_grounded", finding=raw.strip(), path=f"`{item.path}`", line=line)
        return ""
    return ""


def recover_runaway(source: RecoveryInput, services: RetryServices,
                    grounding: GroundedNoticeServices | None = None) -> RecoveryResult:
    coder, body, log = source.completion, source.body, services.log
    attempt, conv, last_notice, last_sent = 0, list(body.get("messages") or []), None, None
    status = RecoveryStatus.UNCHANGED
    while callsyntax.is_ruminating(coder) and attempt < MAX_RUMINATION_RETRIES:
        verdict = coder.get(bodykeys.RUMINATION) or {}
        attempt += 1
        which = ("degenerate" if verdict.get("degenerate") else "window_exhausted" if verdict.get("window_exhausted")
                 else "dead_stream" if verdict.get("dead_stream") else "rumination")
        counts = {"degenerate":("chars",), "window_exhausted":("room", "frames"), "dead_stream":("chunks",),
                  "rumination":("hits", "reasoning_tokens")}[which]
        _event(log, RUNAWAY, "loop.rumination", step=source.step, attempt=attempt, guard=which,
               **{key:verdict.get(key) for key in counts})
        grounded = grounded_next_step(conv, grounding)
        fill = {"rumination_next_step":grounded} if grounded else {}
        text = (prompts.render("rumination_guard_window", percent=int(WINDOW_EXHAUSTED_FRACTION * 100)) if verdict.get("window_exhausted") else
                prompts.load("rumination_guard_dead_stream") if verdict.get("dead_stream") else
                prompts.load("rumination_guard_degenerate") if verdict.get("degenerate") else
                prompts.render("rumination_guard_length", tokens=verdict.get("reasoning_tokens", "many"), **fill) if verdict.get("arm") == "length" else
                prompts.render("rumination_guard", hits=verdict.get("hits", "several"), tokens=verdict.get("reasoning_tokens", "many"), **fill))
        notice = {"role":"user", "content":text}
        conv = (conv[:-1] if attempt > 1 and conv and conv[-1] is last_notice else conv) + [notice]
        if last_sent is not None and conv == last_sent:
            _event(log, RUNAWAY, "loop.rumination_retry_identical", level="warn", attempt=attempt, arm=verdict.get("arm", ""))
            status = RecoveryStatus.IDENTICAL
            break
        last_sent, last_notice = list(conv), notice
        log.phase = f"{source.phase}-focus{attempt}"
        retry_body = {**body, "messages":conv}
        role = services.coder_role
        if role is not None and getattr(role, "reasoning", None) not in (None, "off"):
            retry_body["chat_template_kwargs"] = dict(retry_body.get("chat_template_kwargs") or {})
            reasoning.apply_reasoning(retry_body, "off", role.think_protocol, log)
            _event(log, RUNAWAY, "loop.rumination_reasoning_off", attempt=attempt, guard=which, protocol=role.think_protocol)
        coder = services.retry(retry_body, body.get("tools"))
    still_aborted = callsyntax.is_ruminating(coder)
    if status is not RecoveryStatus.IDENTICAL:
        status = RecoveryStatus.EXHAUSTED if still_aborted else RecoveryStatus.RECOVERED if attempt else RecoveryStatus.UNCHANGED
    _strip_abort(coder)
    if attempt:
        services.add_note(coder, f"reasoning loop detected — aborted and refocused ({attempt}×)")
    return RecoveryResult(coder, status, attempt)


def _strip_abort(completion: dict) -> None:
    # The wire already quarantines real aborts. An injected provider must not
    # release actions by clearing a local marker either; do not reclassify an
    # already-quarantined reply or add evidence to a normal/no-op completion.
    if completion.get(bodykeys.RUMINATION) and any(
            (choice.get("message") or {}).get("tool_calls") for choice in completion.get("choices", [])):
        generation.safe_completion(completion)
    completion.pop(bodykeys.RUMINATION, None)
    for choice in completion.get("choices", []):
        if choice.get("finish_reason") == "rumination":
            choice["finish_reason"] = "stop"


def cut_off_calls(completion: dict) -> list[tuple[str, str]]:
    calls = [call.get("function") or {} for choice in completion.get("choices", [])
             for call in (choice.get("message") or {}).get("tool_calls") or []]
    for prefix in (completion.get(generation.EVIDENCE) or {}).get("call_prefixes", []):
        calls.append({"name":prefix.get("name"), "arguments":prefix.get("arguments")})
    return [(str(fn.get("name") or ""), fn.get("arguments") or "") for fn in calls]


def args_complete(args: str) -> bool:
    try:
        return isinstance(json.loads(args), dict)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class CutServices:
    write_tools: frozenset[str]
    whole_write_tools: frozenset[str]
    path_of_args: Callable[..., str | None]


def cut_target(coder: dict, services: CutServices) -> tuple[str, str, str | None, bool, int]:
    calls = cut_off_calls(coder)
    if not calls:
        return "", "", None, False, -1
    cut = [i for i, (_, args) in enumerate(calls) if not args_complete(args)]
    i = (cut or [len(calls) - 1])[-1]
    name, args = calls[i]
    path = services.path_of_args(args, patch_ok=name == "apply_patch") if name in services.write_tools else None
    return name, args, path, args_complete(args), i


def whole_file_cut(coder: dict, services: CutServices) -> bool:
    name, _, _, complete, _ = cut_target(coder, services)
    return name in services.whole_write_tools and not complete


def truncated_write_path(coder: dict, services: CutServices) -> str | None:
    for name, args in cut_off_calls(coder):
        if name in services.write_tools:
            path = services.path_of_args(args, patch_ok=name == "apply_patch")
            if path:
                return path
    return None


def _describe(name: str, args: str, services: CutServices) -> str:
    path = services.path_of_args(args, patch_ok=name == "apply_patch") if name in services.write_tools else None
    where = f" on `{path}`" if path else ""
    state = "arguments complete" if args_complete(args) else "arguments cut off at the limit"
    return f"`{name}`{where} ({len(args)} characters, {state})"


def also_withheld(coder: dict, services: CutServices) -> str:
    idx = cut_target(coder, services)[4]
    others = [_describe(name, args, services) for i,(name,args) in enumerate(cut_off_calls(coder)) if i != idx]
    return prompts.fill(prompts.load_map("truncation_withheld")["also"], others="; ".join(others)) if others else ""


def length_cut_notice(coder: dict, path: str, tokens: int | None, services: CutServices) -> str:
    used = f"{tokens} tokens" if tokens else "the output-token limit"
    name, _, cut_path, _, _ = cut_target(coder, services)
    if whole_file_cut(coder, services):
        return prompts.render("truncation_guard", path=cut_path or path, limit=used, tool=name, also=also_withheld(coder, services))
    prose = sum(len(str((choice.get("message") or {}).get("content") or "")) for choice in coder.get("choices", []))
    calls = "; ".join(_describe(name, args, services) for name,args in cut_off_calls(coder))
    return prompts.fill(prompts.load_map("truncation_withheld")["withheld"], used=used, prose=prose, calls=calls)


def drop_tool_calls(completion: dict) -> None:
    """Required action quarantine, not an optional assist. Never recovers or executes evidence."""
    generation.safe_completion(completion)
    for choice in completion.get("choices", []):
        (choice.get("message") or {}).pop("tool_calls", None)


def required_quarantine(completion: dict) -> dict:
    """Always applied, even with both optional policies disabled. No notices/retries.

    Malformed/partial argument parsing is required protocol integrity, not optional
    rumination/truncation detection. Transport errors still raise at their owner.
    """
    generation.safe_completion(completion)
    if callliterals.has_incomplete_tool_args(completion):
        drop_tool_calls(completion)
    return completion


def _refusal_turn(body: dict, text: str) -> None:
    if isinstance(body.get("messages"), list) and text:
        body["messages"].append({"role":"user", "content":text})


def recover_truncation(source: RecoveryInput, services: RetryServices, cuts: CutServices) -> RecoveryResult:
    coder, body, log = source.completion, source.body, services.log
    def cut_off(completion):
        return callsyntax.is_truncated(completion) or callliterals.has_incomplete_tool_args(completion)
    if not callsyntax.is_truncated(coder) and callliterals.has_incomplete_tool_args(coder) and cut_target(coder, cuts)[2] is None:
        _event(log, TRUNCATION, "loop.incomplete_tool_call_dropped", step=source.step)
        also = also_withheld(coder, cuts)
        drop_tool_calls(coder)
        services.add_note(coder, "tool call was cut off mid-arguments — partial call refused")
        _refusal_turn(body, prompts.load_map("call_refused")["incomplete_args"] + also)
        return RecoveryResult(coder, RecoveryStatus.REFUSED)
    attempt, conv = 0, list(body.get("messages") or [])
    while cut_off(coder) and attempt < MAX_TRUNCATION_RETRIES:
        path = truncated_write_path(coder, cuts) if callsyntax.is_truncated(coder) else cut_target(coder, cuts)[2]
        also = also_withheld(coder, cuts)
        n = (coder.get("usage") or {}).get("completion_tokens")
        tokens = n if isinstance(n, int) else None
        selfcut = not callsyntax.is_truncated(coder)
        _event(log, TRUNCATION, "loop.truncated", steer="truncation", step=source.step, attempt=attempt + 1,
               path=path, output_tokens=tokens, selfcut=selfcut)
        if path is None:
            break
        attempt += 1
        log.phase = f"{source.phase}-continue{attempt}"
        whole = whole_file_cut(coder, cuts)
        remedy = ((prompts.render("truncation_guard_selfcut", path=cut_target(coder, cuts)[2] or path, also=also) if whole else
                   prompts.fill(prompts.load_map("truncation_withheld")["selfcut"], tool=cut_target(coder, cuts)[0],
                                path=cut_target(coder, cuts)[2] or path, also=also)) if selfcut else
                  length_cut_notice(coder, path, tokens, cuts))
        conv = conv + [{"role":"user", "content":remedy}]
        coder = services.retry({**body, "messages":conv}, body.get("tools"))
    dropped = cut_off(coder)
    if dropped:
        _event(log, TRUNCATION, "loop.truncated_dropped", step=source.step)
        selfcut = not callsyntax.is_truncated(coder)
        closing_target = cut_target(coder, cuts)[2] if selfcut else truncated_write_path(coder, cuts)
        was_write = closing_target is not None or (cut_target(coder, cuts)[0] in cuts.write_tools if selfcut else
                                                 any(name in cuts.write_tools for name,_ in cut_off_calls(coder)))
        closing_whole = was_write and whole_file_cut(coder, cuts)
        closing_also = also_withheld(coder, cuts)
        drop_tool_calls(coder)
    _strip_abort(coder)
    if dropped:
        key = (("selfcut_write" if closing_whole else "selfcut_edit") if selfcut else "truncated_write") if was_write else "truncated_call"
        services.add_note(coder, ("reply incomplete — actions withheld" if generation.incomplete(coder) else
                                 "output stopped early mid-write — partial write refused (retry in smaller pieces)" if was_write and selfcut else
                                 "output hit the token limit — partial write refused (retry in smaller pieces)" if was_write else
                                 "output ended before the call was complete — partial call refused"))
        _refusal_turn(body, prompts.load("generation_incomplete_refused") if generation.incomplete(coder) else
                      prompts.load_map("call_refused")[key] + closing_also)
        _event(log, TRUNCATION, "loop.truncated_refused", step=source.step,
               wording="generation_incomplete_refused" if generation.incomplete(coder) else key, classification=key, was_write=was_write)
    elif attempt:
        services.add_note(coder, f"steered to incremental writes ({attempt}×)")
    status = (RecoveryStatus.EXHAUSTED if dropped and attempt >= MAX_TRUNCATION_RETRIES else
              RecoveryStatus.REFUSED if dropped else RecoveryStatus.RECOVERED if attempt else RecoveryStatus.UNCHANGED)
    return RecoveryResult(coder, status, attempt)


@dataclass(frozen=True)
class RunawayDefinition:
    policy: Policy
    execute: Callable[[RecoveryInput, RetryServices, GroundedNoticeServices | None], RecoveryResult]
    detector: Callable[[int | None], Detector]
    stream: Callable[[StreamInput], StreamGuard]


@dataclass(frozen=True)
class TruncationDefinition:
    policy: Policy
    execute: Callable[[RecoveryInput, RetryServices, CutServices], RecoveryResult]


RUNAWAY = RunawayDefinition(
    Policy("generation-runaway-guard", "generation-recovery", 4, family_id="F48",
           prompts=("rumination_guard_window", "rumination_guard_dead_stream", "rumination_guard_degenerate",
                    "rumination_guard_length", "rumination_guard", "rumination_next_step_grounded"),
           state="pure role detector; per-call stream tails/counters and local retry notices; reset for every call",
           services=("parsed-stream-frames", "measured-window", "monotonic-time", "accumulated-generation-text",
                     "checker-read-mutation-facts", "coder-provider", "completion-reader", "human-note"),
           hooks=(Reference("cria/server.py", "CriaServer.__init__"), Reference("cria/upstream.py", "Upstream.chat_watched"),
                  Reference("cria/loop.py", "guard_rumination")),
           regressions=(Reference("tests/test_generation_guard_policies.py", "test_stream_abort_authority"),
                        Reference("tests/test_generation_guard_policies.py", "test_runaway_recovery_parity"),
                        Reference("tests/test_generation_guard_policies.py", "test_clock_and_wire_timeouts_have_their_own_facts"),
                        Reference("tests/test_generation_guard_policies.py", "test_quarantined_exhaustion_keeps_original_reply_and_event_bytes"),
                        Reference("tests/test_generation_guard_policies.py", "test_selected_replacements_are_called_in_order_and_keep_distinct_results")), migrated=False),
    recover_runaway, Detector.from_reasoning_budget, StreamGuard)
TRUNCATION = TruncationDefinition(
    Policy("generation-cut-output-recovery", "generation-recovery", 4, family_id="F09",
           prompts=("truncation_guard_selfcut", "truncation_guard", "truncation_withheld", "call_refused", "generation_incomplete_refused"),
           state="per-call bounded retries only; final refusal appended to the caller's conversation",
           services=("tool-family-facts", "argument-path-reader", "coder-provider", "completion-reader", "human-note"),
           hooks=(Reference("cria/loop.py", "guard_truncation"),),
           regressions=(Reference("tests/test_generation_guard_policies.py", "test_truncation_recovery_parity"),
                        Reference("tests/test_generation_guard_policies.py", "test_disabled_recovery_still_quarantines_actions"),
                        Reference("tests/test_generation_guard_policies.py", "test_final_cut_call_controls_wording_and_other_calls_remain_evidence"),
                        Reference("tests/test_generation_guard_policies.py", "test_truncation_exhaustion_refuses_the_final_reply_without_synthetic_success")), migrated=False),
    recover_truncation)
DEFINITIONS = (RUNAWAY, TRUNCATION)


@dataclass(frozen=True)
class RecoveryStagesResult:
    completion: dict
    runaway: RecoveryResult | None
    truncation: RecoveryResult | None


@dataclass(frozen=True)
class SelectedGuards:
    """Task-stable stage binding; primary must use this at transport AND retry hooks.

    Explicit None means disabled, never the legacy watch=None (which means no
    reasoning scanner, while other selected F48 stream backstops still run).
    """
    runaway: RunawayDefinition | None
    truncation: TruncationDefinition | None

    def __post_init__(self):
        for definition, expected, kind, hooks in (
                (self.runaway, RUNAWAY, RunawayDefinition, ("execute", "detector", "stream")),
                (self.truncation, TRUNCATION, TruncationDefinition, ("execute",))):
            if definition is not None and (
                    not isinstance(definition, kind) or definition.policy != expected.policy
                    or any(not callable(getattr(definition, hook)) for hook in hooks)):
                raise ValueError("Invalid generation executable contract: " + expected.policy.id)

    @classmethod
    def from_definitions(cls, definitions: Iterable[ExecutableDefinition]) -> "SelectedGuards":
        """Project Root's actual selection; never select, enable or supply defaults.

        Unrelated Root definitions are not generation bindings. Known bindings
        must retain their exact typed policy contract, while all executable
        hooks (including replacements) retain their original object identity.
        """
        chosen = {}
        ids = (RUNAWAY.policy.id, TRUNCATION.policy.id)
        for definition in definitions:
            identifier = definition.policy.id
            if identifier not in ids:
                if isinstance(definition, (RunawayDefinition, TruncationDefinition)):
                    raise ValueError("Unknown generation executable contract: " + identifier)
                continue
            if identifier in chosen:
                raise ValueError("Duplicate generation executable: " + identifier)
            chosen[identifier] = definition
        return cls(chosen.get(ids[0]), chosen.get(ids[1]))

    def detector(self, output_reserve: Callable[[], int | None], *, applicable: bool = True) -> Detector | None:
        """Build a role detector only through its selected definition, lazily.

        Inapplicable seats may still use selected stream backstops with watch=None.
        No detector, reserve input, stream input or role state is gathered here
        when F48 is disabled or the reasoning detector is inapplicable.
        """
        if self.runaway is None or not applicable:
            return None
        return self.runaway.detector(output_reserve())

    def stream(self, source: Callable[[], StreamInput]) -> StreamGuard | None:
        return self.runaway.stream(source()) if self.runaway is not None else None

    def recover(self, source: RecoveryInput, services: RetryServices, cuts: Callable[[], CutServices],
                grounding: Callable[[], GroundedNoticeServices | None] = lambda:None) -> RecoveryStagesResult:
        coder = source.completion
        runaway = truncation = None
        if self.runaway is not None:
            runaway = self.runaway.execute(source, services, grounding())
            coder = runaway.completion
        if self.truncation is not None:
            truncation = self.truncation.execute(RecoveryInput(coder, source.body, source.step, source.phase), services, cuts())
            coder = truncation.completion
        required_quarantine(coder)
        return RecoveryStagesResult(coder, runaway, truncation)
