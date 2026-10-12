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

#: On a ``CALLER_INSTRUCTIONS`` message: the exact text of the harness's own BASE instructions (the
#: Responses ``instructions`` field — its persona), as distinct from the developer items the user or
#: operator configured (permissions, developer instructions), which are not reducible.  Written by the
#: Responses translation, which knows the part boundaries; read by the coder frame; stripped at the wire.
CALLER_PERSONA = "cria_caller_persona"

#: On the framed coder system message: ``{"start": int, "text": str}`` — where the harness persona sits
#: in that message's content, anchored at an offset after cria's own system text.  A boundary carried by
#: the message's author, so the context floor can reduce that span — and only that span — under window
#: pressure, before it deletes any conversation evidence.  Verified against the content before use.
#: Consumed (and stripped) at the wire.
CALLER_SPAN = "cria_caller_span"

#: A typed missing-file completion remediation owns this coder body.  The loop uses it only as
#: wire-visible provenance for the suspended plan cursor; it must never reach the model server.
COMPLETION_REMEDIATION = "cria_completion_remediation"

#: On the restored-file-text message the coder frame adds (``loop._restored_text_message``): ``{"offered":
#: {rel: sha1}}`` — the files whose current text that message carries.  The wire reads it AFTER the floor
#: (``modelview.settle_restored_text``): a message that survived is delivery, one the floor reduced or dropped
#: is not, and only delivery counts as a whole read.  Stripped from the message at the wire.
RESTORED_FILES = "cria_restored_files"

# --- response-body hints: cria's own annotations on a completion --------------------------------

#: Human-facing notes cria attaches to a completion for the operator's display, stripped before the
#: model ever re-reads them (principle 17: the model never sees the token "cria").
NOTES = "cria_notes"

#: A reply held a fenced call object that massage REFUSED to promote; carries {reason, tool, path} so the
#: loop can tell the coder what did not run (a refusal nobody sees regenerates byte-identically).
#: Popped by the loop where the turn is read; stripped from any completion that reaches the server.
FENCED_REFUSED = "cria_fenced_refused"

#: The rumination guard aborted this turn; carries what it saw. Read by the loop to skip a steer that
#: would otherwise be authored from a truncated thought.
RUMINATION = "cria_rumination"

#: MESSAGE-level (not body): ``(length, sha1)`` of a tool result's own payload, recorded by the producer
#: that appended cria text after it (`writeproxy.append_note`), so the ledger counts only the payload.
#: Stripped from every message at the wire (`Upstream._prep`).
PAYLOAD_BOUNDARY = "cria_payload_boundary"

#: Every key above. The wire strips this set wholesale, so adding a key here is all it takes to keep
#: it off the API — the thing five scattered literals could not guarantee.
ALL = (MERGE_TURNS, OUTPUT_RESERVE, LOST_CALL, PINNED_TASK, CONTEXT_REFIT_NO_CHANGE,
       CALLER_INSTRUCTIONS, CALLER_PERSONA, CALLER_SPAN, RESTORED_FILES, COMPLETION_REMEDIATION, NOTES, RUMINATION, FENCED_REFUSED, PAYLOAD_BOUNDARY)
