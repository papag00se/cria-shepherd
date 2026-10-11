"""The ONE owner of "how big is the conversation the MODEL is shown".

Two numbers about a request used to be conflated, and the harness acted on the wrong one:

* what the HARNESS sent — the whole inbound history, including cria's own completion-gate plumbing
  (survey/launch/poll calls with 2-12 KB arguments, ~8.6 KB base64 result pages) and its ⟦cria⟧
  status turns; and
* what the MODEL reads — the same history after cria strips that plumbing from its view
  (``probegate.clean_gate_results``) and replaces the harness's agent prompt with cria's own coder
  prompt (``loop._frame_for_item``).

Usage reported to a harness at L1-L5 is the second. A harness compacts when the reported size crosses
its trigger; the gate plumbing is not the model's context and must not make it compact (phi4's 16K
window: 31 of 31 over-trigger reports were followed by a Codex compaction, 37 in one run, while the
model-visible prompt never exceeded ~10.5K tokens). This module owns the cleaning step both the wire
(`Upstream._prep`) and the report apply, so the number cannot drift from the prompt.

The size is the context floor's OWN pre-fit estimate (`contextfloor.est_total`, chars/4 of messages +
tool schema) — the size the model would need BEFORE `contextfloor.fit` trims anything. It is
deliberately not multiplied by `tokenratio` (a conservative, rise-fast safety factor for the floor,
whose EWMA reads ~1.6 on tiny judge calls) — that would report a larger number than the model's real
token count; phi4's coder frames measure 10,388 est vs ~10,553 real (1.02x).
"""
from __future__ import annotations

import re

from . import contextfloor, dedup, probegate, prompts, selfcompact

# The messages that carry the repo's own check evidence into the model's view, each rendered by a
# different owner: the compaction continuation freezes the gate's findings into the harness's history
# (`loop.reframe_compaction`), the `⟦ctx:checks⟧` result is the gate's own rendering
# (`probegate.clean_gate_results`), and the trailing `⟦ctx:steer⟧` restates them after the floor has
# run (`loop`). No call site sees all three — which is why the one-copy rule lives HERE, at the wire,
# beside the cleaning that already decides what the model reads (#24). A test pins the literals to
# `loop.CONTINUATION_MARKER` (modelview cannot import loop: loop imports upstream imports this).
CONTINUATION = "⟦ctx:continuation⟧"
EVIDENCE_CARRIERS = (CONTINUATION, probegate.CHECKS_MARKER, "⟦ctx:steer⟧")


def wire_messages(messages: list[dict]) -> list[dict]:
    """The conversation as the coder-bound wire carries it: cria-authored (stamped) gate calls and
    results cleaned, everything else verbatim. A body without a stamped gate call or repeated check
    evidence is returned as is.
    `Upstream._prep` applies exactly this before the floor, and the usage report measures exactly this.

    The one-copy fold is a SEPARATE step (:func:`fold_evidence`) because it may only run once the floor
    has decided what survives (see `Upstream._prep`)."""
    if probegate.gate_call_ids(messages):
        messages = probegate.clean_gate_results(messages, linked_only=True)
    return messages


# An anchor block is the DESIGNATED single copy of its content: folding it into a pointer at a later
# duplicate would move the content out of the protected head. `loop.BRIEFING_OPEN` is the one literal
# mirrored here (modelview cannot import loop); `loop._ANCHOR_MARKERS_FOR_DEDUP` is this tuple and a
# test pins the literal.
BRIEFING_OPEN = "⟦ctx:briefing⟧"
ANCHOR_MARKERS_FOR_DEDUP = (selfcompact.FACTS_MARKER, selfcompact.TASK_MARKER,
                            selfcompact.SUMMARY_MARKER, BRIEFING_OPEN, CONTINUATION)


def fold_repeats(messages: list[dict]) -> tuple[list[dict], int]:
    """ONE COPY OF EACH BYTE-IDENTICAL user/tool PAYLOAD (newest wins; `dedup.fold_repeated_messages`).
    It lives at the wire, after the floor, for the same reason `fold_check_runs` does: it ran at the loop
    call site BEFORE the floor, the floor then dropped the surviving newest copy, and the pointer
    ("read the full copy below") outlived its target (phi4/Java A6 call 0005: repeat_dedup folded 1 and
    the same call's floor trimmed ~4k tokens; no copy was left). (#24: a pointer must never outlive its
    target in the body actually sent.)"""
    return dedup.fold_repeated_messages(
        messages, prompts.load("repeated_message_note").strip(), protect=ANCHOR_MARKERS_FOR_DEDUP)


def repeat_pointers(messages: list[dict]) -> int:
    """How many whole-message repeat pointers ``messages`` carries (for reporting what a wire pass folded,
    including a fold the floor's sizing trial already applied)."""
    note = prompts.load("repeated_message_note").strip()
    return sum(1 for m in messages if isinstance(m, dict) and m.get("content") == note)


def fold_evidence(messages: list[dict]) -> list[dict]:
    """Every wire-side fold: repeated payloads (`fold_repeats`) and the check carriers' runs
    (`fold_check_runs`). The sizing form the floor trial and `visible_tokens` use."""
    return fold_check_runs(fold_repeats(messages)[0])


def fold_check_runs(messages: list[dict]) -> list[dict]:
    """ONE COPY OF THE CHECK EVIDENCE. Whatever the check carriers above repeat — the same failure
    block in the continuation and in the steer, the governance paragraph in all three, a build tool's
    own error list printed again under its failure banner — is shown once (the newest copy) and a
    pointer stands where each earlier copy sat. Byte-exact and lossless (`dedup.fold_repeated_runs`);
    identity when nothing repeats. Context surgery: callers run it at CONTEXT_FIXES and above only,
    and never BEFORE the floor — a pointer must not outlive the copy it points at."""
    out, _ = dedup.fold_repeated_runs(
        messages, prompts.load("repeated_message_note").strip(), prefixes=EVIDENCE_CARRIERS)
    return out


def visible_tokens(messages: list[dict], tools, *, fold: bool = False) -> int:
    """Pre-floor chars/4 size of ``messages`` + ``tools`` as the model would be shown them. ``fold``
    is the engagement gate's answer (CONTEXT_FIXES and above), so the number is the wire's."""
    shown = wire_messages(messages)
    return contextfloor.est_total(fold_evidence(shown) if fold else shown, tools)


# The continuation names, at the moment it is rendered, the paired tool results the harness handed
# over. By the time the body is serialized the floor, the gate cleaning and the orphan repair have
# all had their say, so what that list promises ("their full original output remains in their paired
# tool messages") can be false of the body the model actually receives: phi4 A2 call 0043 listed five
# call ids and the body held one pair; call 0020 listed three and held none (#5b). So the list is
# made true HERE, at the last point before serialization (#24): only ids whose assistant call AND
# tool result are both in the outgoing messages stay on it; none left says so.
RETAINED_HEADER = "Retained authoritative paired tool results ("
_PAIRED_LINE = re.compile(r"^- paired tool result \(call id: ([^)\s]+)\)$")


def _paired_ids(messages: list[dict]) -> set[str]:
    called: set[str] = set()
    answered: set[str] = set()
    for m in messages:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict) and isinstance(tc.get("id"), str):
                called.add(tc["id"])
        if m.get("role") == "tool" and isinstance(m.get("tool_call_id"), str):
            answered.add(m["tool_call_id"])
    return called & answered


def retained_results_truth(messages: list[dict]) -> list[dict]:
    """``messages`` with every continuation's list of retained paired tool results made true of
    THIS body. The same list when each listed id is paired in the body (or nothing is listed)."""
    out = None
    paired = None
    for i, m in enumerate(messages):
        c = m.get("content") if isinstance(m, dict) else None
        if not (m.get("role") == "user" and isinstance(c, str) and c.startswith(CONTINUATION)):
            continue
        at = c.rfind(RETAINED_HEADER)
        if at < 0:
            continue
        head_end = c.find("\n", at)
        if head_end < 0:
            continue
        lines = c[head_end + 1:].split("\n")
        listed = [(ln, _PAIRED_LINE.match(ln)) for ln in lines]
        n = 0
        while n < len(listed) and listed[n][1]:
            n += 1
        if n == 0:
            continue                                    # "(none)" or nothing listed: nothing to correct
        if paired is None:
            paired = _paired_ids(messages)
        kept = [ln for ln, mt in listed[:n] if mt.group(1) in paired]
        if len(kept) == n:
            continue
        rest = "\n".join(lines[n:])
        if kept:
            section = c[at:head_end + 1] + "\n".join(kept)
        else:
            section = prompts.load("continuation_no_retained_results").strip()
        if out is None:
            out = list(messages)
        out[i] = {**m, "content": c[:at] + section + (("\n" + rest) if rest else "")}
    return out if out is not None else messages
