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

from . import contextfloor, dedup, probegate, prompts

# The messages that carry the repo's own check evidence into the model's view, each rendered by a
# different owner: the compaction continuation freezes the gate's findings into the harness's history
# (`loop.reframe_compaction`), the `⟦ctx:checks⟧` result is the gate's own rendering
# (`probegate.clean_gate_results`), and the trailing `⟦ctx:steer⟧` restates them after the floor has
# run (`loop`). No call site sees all three — which is why the one-copy rule lives HERE, at the wire,
# beside the cleaning that already decides what the model reads (#24). A test pins the literals to
# `loop.CONTINUATION_MARKER` (modelview cannot import loop: loop imports upstream imports this).
EVIDENCE_CARRIERS = ("⟦ctx:continuation⟧", probegate.CHECKS_MARKER, "⟦ctx:steer⟧")


def wire_messages(messages: list[dict]) -> list[dict]:
    """The conversation as the coder-bound wire carries it: cria-authored (stamped) gate calls and
    results cleaned, everything else verbatim. A body without a stamped gate call or repeated check
    evidence is returned as is.
    `Upstream._prep` applies exactly this before the floor, and the usage report measures exactly this.

    ONE COPY OF THE CHECK EVIDENCE. Whatever the check carriers above repeat — the same failure block
    in the continuation and in the steer, the governance paragraph in all three, a build tool's own
    error list printed again under its failure banner — is shown once (the newest copy) and a pointer
    stands where each earlier copy sat. Byte-exact and lossless (`dedup.fold_repeated_runs`); identity
    when nothing repeats, so every other body is byte-identical."""
    if probegate.gate_call_ids(messages):
        messages = probegate.clean_gate_results(messages, linked_only=True)
    messages, _ = dedup.fold_repeated_runs(
        messages, prompts.load("repeated_message_note").strip(), prefixes=EVIDENCE_CARRIERS)
    return messages


def visible_tokens(messages: list[dict], tools) -> int:
    """Pre-floor chars/4 size of ``messages`` + ``tools`` as the model would be shown them."""
    return contextfloor.est_total(wire_messages(messages), tools)
