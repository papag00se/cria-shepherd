"""cria's PRIVATE keys on the request and response body — one owner, one spelling each.

These are not the API's fields. They are hints cria puts on a body so a later stage can read an
earlier stage's intent: the role layer says "this model needs its turns merged", the wire consumes
it and strips it before serialization. Principle 24 is built on that pattern — an invariant that must
hold on the wire is carried as a body hint and enforced at `Upstream._prep`, never at a call site.

WHY THIS MODULE EXISTS. Five keys were spelled seventeen times across six modules, and only two of
them had a constant. `"cria_output_reserve"` was a bare literal written in `config`, read in
`contextfloor`, and stripped in `upstream` — three modules agreeing by memory. A typo in any one of
them does not raise: the writer writes a key nobody reads, the reader reads a key nobody wrote, the
stripper leaves cria's own field on the wire. The hint silently does nothing, which is the exact
failure mode principle 24 was written after.

It also broke an import cycle. `config` needed `MERGE_TURNS_KEY` from `massage`, `massage` imports
`writeproxy`, `writeproxy` imports `config` — so the constant was fetched through a function-local
import with a comment naming the cycle it was dodging. A leaf module with no imports of its own ends
that: every stage can name a key without depending on any other stage.

A key here is cria-internal by definition. If it can reach the model server, it is a bug — the wire
strips every one of them (`Upstream._prep`).
"""

# --- request-body hints: an earlier stage's intent, read by a later one -------------------------

#: The role wants consecutive same-role turns merged before serialization. Opt-in per model, so a
#: model that does not need it ships a byte-identical body. Consumed and stripped at the wire.
MERGE_TURNS = "cria_merge_turns"

#: How much of the window the role wants left free for the answer — distinct from `max_tokens`, which
#: is the runaway backstop (principle 6). Written by the role, read by the context floor.
OUTPUT_RESERVE = "cria_output_reserve"

#: A historical tool_call whose result never arrived, recorded so the repair at the wire can find it.
LOST_CALL = "cria_lost_call"

#: An exact user packet to protect at the context floor: normally the conversation's verbatim
#: root task, or an internal judge's task/current-facts/question packet. The owner supplies its
#: text so later user-role closers cannot displace it and no preamble-wording guess is needed.
PINNED_TASK = "cria_pinned_task"

#: A typed wire-owner outcome from a parsed context rejection whose inner refit would have resent
#: identical final bytes.  ``summarize`` carries it only into its one forced-off retry; the wire
#: compares that retry's final bytes and consumes it before a POST.  It is deliberately an object,
#: not a status/text flag, so only ``Upstream._open_with_refit`` can originate the provenance.
CONTEXT_REFIT_NO_CHANGE = "cria_context_refit_no_change"

#: A system/developer message originated from a Responses caller's instructions, not harness persona.
#: Kept through proxy/framing, then stripped from the message object at the wire.
CALLER_INSTRUCTIONS = "cria_caller_instructions"

#: `dedup.fold_repeated_messages` wrote this pointer message and carries the ORIGINAL content it
#: replaced, so `Upstream._prep` can re-verify the pointer's promise (a byte-identical full copy
#: rides later in the same body) against the FINAL wire body and restore the original if a later
#: stage broke the promise. Consumed and stripped by `dedup.verify_pointers`, called from the wire.
DEDUP_POINTER = "cria_dedup_pointer"

#: A typed missing-file completion remediation owns this coder body.  The loop uses it only as
#: wire-visible provenance for the suspended plan cursor; it must never reach the model server.
COMPLETION_REMEDIATION = "cria_completion_remediation"

# --- response-body hints: cria's own annotations on a completion --------------------------------

#: Human-facing notes cria attaches to a completion for the operator's display, stripped before the
#: model ever re-reads them (principle 17: the model never sees the token "cria").
NOTES = "cria_notes"

#: The rumination guard aborted this turn; carries what it saw. Read by the loop to skip a steer that
#: would otherwise be authored from a truncated thought.
RUMINATION = "cria_rumination"

#: Every key above. The wire strips this set wholesale, so adding a key here is all it takes to keep
#: it off the API — the thing five scattered literals could not guarantee.
ALL = (MERGE_TURNS, OUTPUT_RESERVE, LOST_CALL, PINNED_TASK, CONTEXT_REFIT_NO_CHANGE,
       CALLER_INSTRUCTIONS, COMPLETION_REMEDIATION, NOTES, RUMINATION, DEDUP_POINTER)
