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
from dataclasses import dataclass
from typing import Callable

from .assistcontract import Policy, Reference
from .memoryeffects import Effect

from . import bodykeys, contextfloor, dedup, focustrim, probegate, prompts, selfcompact

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
    return fold_selected(WireInput(messages)).messages


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


def visible_tokens(messages: list[dict], tools, *, fold: bool = False,
                   definitions: tuple[WireDefinition, ...] | None = None) -> int:
    """Pre-floor chars/4 size using the caller's exact wire-fold selection.

    ``fold`` retains the engagement gate: False never executes folding. With
    folding enabled, omitted definitions retain library defaults; explicit ()
    executes none. Pass the same immutable tuple to trial and survivor folding.
    This only estimates: it neither fits a window nor earns delivery credit.
    """
    shown = wire_messages(messages)
    if fold:
        shown = fold_selected(WireInput(shown), definitions).messages
    return contextfloor.est_total(shown, tools)


@dataclass(frozen=True)
class WireInput:
    messages: list[dict]


@dataclass(frozen=True)
class WireDefinition:
    policy: Policy
    # Existing algorithms expose either a count or just the changed view. Neither
    # needs a forwarding policy class or a second implementation to normalize it.
    execute: Callable[[list[dict]], list[dict] | tuple[list[dict], int]]


@dataclass(frozen=True)
class WireResult:
    messages: list[dict]
    effect: Effect
    applied_ids: tuple[str, ...] = ()
    repeated_messages: int = 0


REPEATED_PAYLOADS = WireDefinition(
    Policy("wire-repeated-payloads", "wire-evidence-fold", 3, family_id="F69",
           prompts=("repeated_message_note",),
           services=("surviving-paired-tool-history",),
           hooks=(Reference("cria/upstream.py", "Upstream._prep"),
                  Reference("cria/modelview.py", "visible_tokens")),
           regressions=(Reference("tests/test_context_memory_migration.py", "test_wire_stages_preserve_source_and_selection_without_gathering_on_bypass"),
                        Reference("tests/test_a_repeat_pointer_never_outlives_its_target.py", "test_the_old_order_dangles_somewhere_and_the_wire_never_does"),
                        Reference("tests/test_context_wire_selection.py", "test_wire_uses_exact_selected_fold_without_default_fallback"),
                        Reference("tests/test_context_wire_selection.py", "test_changed_trial_refits_original_unfolded_history_with_identical_budgets")),
           migrated=False), fold_repeats)
REPEATED_CHECKS = WireDefinition(
    Policy("wire-repeated-check-evidence", "wire-evidence-fold", 3, family_id="F69",
           prompts=("repeated_message_note",),
           services=("surviving-check-carriers",),
           hooks=(Reference("cria/upstream.py", "Upstream._prep"),
                  Reference("cria/modelview.py", "visible_tokens")),
           regressions=(Reference("tests/test_context_memory_migration.py", "test_wire_check_runs_fold_only_when_the_later_exact_source_survives"),
                        Reference("tests/test_c13b_the_wire_claims_are_true.py", "test_every_line_a_pointer_replaced_is_shown_in_the_body_sent"),
                        Reference("tests/test_context_wire_selection.py", "test_changed_trial_refits_original_unfolded_history_with_identical_budgets")),
           migrated=False), fold_check_runs)
WIRE_FOLD_STAGE = (REPEATED_PAYLOADS, REPEATED_CHECKS)


def fold_selected(source: WireInput,
                  definitions: tuple[WireDefinition, ...] | None = None) -> WireResult:
    """Fold only selected policies, in explicit order. Empty selection is identity.

    Use the SAME selection for usage sizing and the floor's folded trial. A trial
    is not delivery: discard it if the floor changes messages, refit original
    unfolded input and run again over survivors in Upstream._prep. This stage
    neither fits a window nor settles any claim about the body sent.
    """
    messages = source.messages
    applied = []
    repeats = 0
    for definition in WIRE_FOLD_STAGE if definitions is None else definitions:
        result = definition.execute(messages)
        if isinstance(result, tuple):
            out, count = result
            repeats += count
        else:
            out = result
        if out is not messages and out != messages:
            applied.append(definition.policy.id)
            messages = out
    return WireResult(messages, Effect.REDUCED if applied else Effect.NO_OP,
                      tuple(applied), repeats)


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


# Compatibility import, not another implementation or independently selectable
# assist. Producer and final-wire settlement belong to the same focus definition.
superseded_writes_truth = focustrim.superseded_writes_truth


# The ⟦ctx:current⟧ block of restored file text (`loop._restored_text_message`) and the ledger label that
# points at it (`fetched_facts_sections.read_restored`).  modelview cannot import loop; a test pins the literal.
RESTORED_MARKER = "⟦ctx:current⟧"


@dataclass(frozen=True)
class DeliveryInput:
    messages: list[dict]
    # Original offered hashes, not inferred from model-visible marker text.
    offered: dict[str, str]
    # Paths whose shared workspace view has already queued a harness demand.
    pending_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeliveryResult:
    messages: list[dict]
    effect: Effect
    delivered: dict[str, str]
    pending_paths: tuple[str, ...] = ()


def settle_delivery(source: DeliveryInput) -> DeliveryResult:
    """Final-wire foundation: offered text is not a whole-read credit.

    The producer owns selection/demands. This API gathers nothing and never opens
    a workspace path. Only surviving authenticated message hints earn delivery;
    a labelled floor stand-in earns none. A queued demand remains pending even
    when other files were delivered. Keep this after fit, not in a phase runner.
    """
    messages, delivered = settle_restored_text(source.messages)
    effect = (Effect.DELIVERED if delivered else Effect.REDUCED if source.offered
              else Effect.PENDING if source.pending_paths else Effect.NO_OP)
    return DeliveryResult(messages, effect, delivered, source.pending_paths)


def settle_restored_text(messages: list[dict]) -> tuple[list[dict], dict]:
    """``(messages, {rel: sha1})`` — what the restored-file-text block delivered in THIS body.

    The block is added before the floor, which may reduce it to a stand-in or drop it; the ledger line
    that said "its current text is below" and the whole-read credit for the write hold were both decided
    before that. A claim about the body must be made of the body that is sent (#24), so it is settled here,
    after the floor: a surviving block (the message still carries its ``bodykeys.RESTORED_FILES`` hint)
    delivers exactly what it offered; otherwise nothing was delivered, and every ledger line that said
    otherwise says the plain absence again. Identity when no block was ever offered."""
    from . import bodykeys
    delivered: dict = {}
    for m in messages:
        hint = m.get(bodykeys.RESTORED_FILES) if isinstance(m, dict) else None
        if isinstance(hint, dict):
            delivered.update(hint.get("offered") or {})
    labels = prompts.load_map("fetched_facts_sections")
    below, absent = labels["read_restored"], labels["read_out_of_view"]
    if delivered or not any(isinstance(m, dict) and isinstance(m.get("content"), str)
                            and m.get("role") == "user" and below in m["content"] for m in messages):
        return messages, delivered
    return [({**m, "content": m["content"].replace(below, absent)}
             if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)
             and below in m["content"] else m) for m in messages], delivered
