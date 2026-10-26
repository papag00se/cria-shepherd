"""A tool call cria REFUSED — marked where the refusal is AUTHORED, and rendered so a judge can
tell the CALL did not happen.

THE DEFECT THIS EXISTS FOR. cria lowers a refused synthetic tool call to a ``printf`` of its own
refusal text, so the harness hands that text back as the tool's result. ``loop._work_log`` then
renders it as ``  -> <refusal text>``, byte-identical to a real result, and ``prompts/verify.txt``
tells the step critic in cria's own words that "each ``-> ...`` line is what it returned". So the
judge is told cria's sentence is the coder's tool's answer — cria stating a false fact about the
world in its own voice (principle 5b). Measured 2026-08-03 over the 127 captured sessions: 216 of
537 step-critic prompts carrying an action log render at least one refusal that way, and 140
of 370 satisfaction prompts (38%).

WHERE THE MARK GOES, AND WHY IT IS NOT A MATCHER. The mark is applied at the site that DECIDES to
refuse — ``writeproxy._refusal_command`` (the one owner of a lowered refusal), the two read-size
guards, ``webfetch._guard_msg`` for its repeat-gate keys, and the search-read denial in
``loop._judge_search_reads``. Nothing downstream ever asks what a result SAYS. A wording matcher
would be the same class of mistake this fixes: it would fire on a page that quotes the refusal and
miss the next refusal anyone writes. The sibling ``⟦ctx:search⟧`` marker did exactly this and said
why; this generalizes it, and that marker is gone (one owner, not two).

WHAT THE LABEL MAY SAY — the whole rule, learned by getting it wrong. The label names the CALL and
nothing else: *this call did not run*. It must say NOTHING about whether the text beneath it is
real. A first attempt labelled the body "not content the tool returned" and landed on top of a
spilled document's REAL endpoint list and response field names — the ``[API endpoints (33): …]``
block ``selfcompact`` anchors verbatim precisely because it IS the API's real answer, carried by
the ``fetch_repeat_spilled`` refusal. That told the judge to discard its only real evidence: a
bigger false fact than the one being fixed. Everything under a refusal may be genuine ground truth
and often is — a repeat-fetch refusal carries the document's outline, a spill-read steer carries
the file's real routes. cria may say the call did not run, because it knows that; it may not say
what the words below are worth.

WHICH FACTS NOW HANG ON THE MARK, AND WHAT PROVES IT. The mark began as disclosure; it is also the
evidence behind shared facts that GATE wording and assists: whether a write landed (`gate_unedited`, the
grounded rumination notice, the thrash edit count, the work ledger, the context floor's modified-file note) and
whether an edit recovery directive may be composed. So the mark alone — text any command can print and any file can
quote — cannot be the proof. The proof is the BRANCH, declared by POSITION (`cria.resultpacket`): every compiled leaf
prints one typed ASCII record at stdout offset 0 (`ran` / `refused` / `unapplied` / `landed` / `uncertain`) under a receipt
`translate_outbound` derives per call and declares in the LEADING line of the call's stored command; `represent_inbound`
reads exactly the record at that position of an unambiguously paired result, only if it carries that receipt, records the
proven outcome as a message-level hint every reader asks (`outcome`, `refused`, `landed`, `unlanded`, `unlanded_call_ids`)
— never the wording — and removes exactly that record. A file's bytes (a whole read, a read-instead answer) ride INSIDE the
record with their length and digest, so what a read returned is verified, not found. A payload quoting records, receipts,
markers or surveys is just the opaque tail and keeps every byte. Absent or lost record means unknown, never "did not
run". The call and the body stay separate truths: the record proves WHICH BRANCH PRINTED the result (the call did not
run) and, separately, whether the file was returned; the words beneath may be genuine ground truth.

DIRECTION (#13). Unknown withholds. A refusal that cannot be proven is read as "may have run", so no write is
assumed unlanded, no step advances and no notice claims "nothing landed" on the strength of a quotation; the
only ruling a PROVEN refusal moves is from "the tool proved this" toward "the tool never ran", the safe
direction. What is parsed is cria's own receipt and call/result correlation (`paired_results`, exactly one call
and exactly one result after it); what is never parsed is the model's, a command's or a file's wording.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
from collections import Counter

from . import bodykeys, payloadboundary, resultpacket

# ⟦ctx:…⟧ namespace, never the proper noun (#17). It rides in the refusal text the coder reads —
# the same channel and the same shape as every other context marker in that stream.
DENIED_MARKER = "⟦ctx:denied⟧"

# A write_file the coder named for a file it never read is answered with that file's bytes. The marker
# sits on its own line between cria's fact and the file's content: it is how a reader of the history
# knows the result of a WRITE call is a READ of the path (H1). Absent when the read could not be returned.
READ_INSTEAD_MARKER = "⟦ctx:read-instead⟧"


def _opens_with(text: str, prefix: str) -> bool:
    """``text`` opens with ``prefix`` AS A HEADER: the prefix is followed by whitespace or ends the text. A body
    that merely STARTS with the marker's characters (a path named ``⟦ctx:denied⟧.txt``) is not a header."""
    return text.startswith(prefix) and (len(text) == len(prefix) or text[len(prefix)].isspace())


def mark(text: str) -> str:
    """``text`` opened by cria's own refusal header, :data:`DENIED_MARKER`. While a lowering is being composed
    (:func:`receipt_scope`) the refusal branch that prints it first prints its ``refused`` record, so the branch is
    attributable (see the record protocol above).

    Idempotence is on that OPENING header only. A marker inside the BODY — a path, a quoted file, even at the very
    start of a path — is part of the body: it never stands in for the header and is never removed. Empty text is
    left empty: a refusal with nothing to say is not a refusal."""
    if not text:
        return text
    lead = frame(REFUSED)
    if lead and text.startswith(lead):
        return text
    body = text if _opens_with(text, DENIED_MARKER) else f"{DENIED_MARKER} {text}"
    return lead + body


def is_denied(text: str) -> bool:
    """True when ``text`` — a string cria COMPOSED in-process — is marked as a call that did not run.

    This reads wording, so it answers only about text cria itself authored a moment ago (the authoring
    site deciding whether to lower a refusal). It must NEVER be asked of a tool result: a command's own
    output, or a file's bytes, can quote the marker. Readers of results use :func:`outcome`."""
    return bool(text) and DENIED_MARKER in text


# --- WHICH BRANCH RAN: a typed RECORD at stdout offset 0 (the protocol lives in `resultpacket`) --------------------
#
# A result that merely CONTAINS a marker, a frame or a survey block proves nothing: a native command can `echo` them, a
# file or a fetched page quotes them — even with the call's own receipt, which is derived from the call's id, name and
# arguments and so can appear in data. So proof is POSITIONAL and DECLARED, never found: every compiled leaf prints one
# ASCII JSON record FIRST (`resultpacket`), `represent_inbound` reads exactly the record at the start of the stdout of an
# UNAMBIGUOUSLY PAIRED call (one call, one result after it) whose stored sentinel declares the receipt, and records the
# proven outcome as a message hint (`bodykeys.RESULT_OUTCOME`, overwriting whatever the client sent). Whatever follows
# the declared records is an opaque tail, never parsed. No record first => UNKNOWN, bytes untouched. A branch that may
# already have changed the target prints an `uncertain` record. The receipt is derived from the call (no server state,
# survives a restart); it is a correlation token between cria and its own commands, not a security boundary.
REFUSED = resultpacket.REFUSED      # cria's own refusal branch ran: the call did not run
UNAPPLIED = resultpacket.UNAPPLIED  # cria's edit program reported that the edit was not applied
RAN = resultpacket.RAN              # a real payload-bearing branch ran (carries no outcome of its own)
LANDED = resultpacket.LANDED        # cria's own write/edit program reported the mutation LANDED
UNCERTAIN = resultpacket.UNCERTAIN  # cria's own write/edit program could not tell whether the target changed
UNKNOWN = "unknown"                 # a cria-LOWERED call whose branch could not be proven: neither refused nor a real read
_KINDS = resultpacket.KINDS

_ACTIVE: contextvars.ContextVar[str] = contextvars.ContextVar("cria_denial_receipt", default="")
_DECLARATION: contextvars.ContextVar["Declaration | None"] = contextvars.ContextVar("cria_denial_declaration", default=None)


class Declaration:
    """What the compiler of ONE lowered call declares for the sentinel (set while it composes, read once afterwards)."""
    def __init__(self) -> None:
        self.survey = False


def canonical_arguments(arguments) -> str:
    """The ONE serialization of a call's arguments, shared by the sentinel that stores them and the receipt derived from them:
    a string is itself, anything else (a dict an adapter built) is its JSON text. The receipt is recomputed from the STORED
    string, so both sides must agree on this function — there is no second spelling and no guessing which was meant."""
    return arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)


def receipt_for(call_id, name, arguments) -> str:
    """The receipt for one lowered call — a pure function of what the sentinel also carries."""
    args = canonical_arguments(arguments)
    return hashlib.sha256(f"{call_id}\x00{name}\x00{args}".encode("utf-8", "replace")).hexdigest()[:16]


@contextlib.contextmanager
def receipt_scope(token: str, declaration: "Declaration | None" = None):
    """Everything composed inside prints this call's records and may declare into ``declaration``."""
    reset = _ACTIVE.set(token or "")
    reset_decl = _DECLARATION.set(declaration)
    try:
        yield token
    finally:
        _DECLARATION.reset(reset_decl)
        _ACTIVE.reset(reset)


def unframed():
    """Compose a leaf that runs INSIDE a branch which already printed its own record (a refusal that goes on to
    answer with the file): a second record there would sit in the middle of what the model reads."""
    return receipt_scope("", _DECLARATION.get())


def active_receipt() -> str:
    return _ACTIVE.get()


def declare_survey() -> None:
    """The command being composed will carry a survey record (the sentinel declares it; see `resultpacket`)."""
    if _ACTIVE.get() and (d := _DECLARATION.get()) is not None:
        d.survey = True


def frame(kind: str, token: str | None = None, *, rep: dict | None = None) -> str:
    """One record line for ``kind`` under the active (or given) receipt (with the producer's typed reports ``rep``); empty
    when no lowering is being composed."""
    token = _ACTIVE.get() if token is None else token
    assert kind in _KINDS
    return resultpacket.line(token, kind, rep=rep) if token else ""


def ran_command() -> str:
    """The shell statement that prints the body-less ``ran`` record (``""`` outside a lowering), for a real payload
    leaf: ``printf ...; cat file``."""
    return resultpacket.static_command(_ACTIVE.get(), RAN)


def read_payload(message) -> str | None:
    """The exact file text a PROVEN whole read returned, or None. The producer's record carried the bytes with their
    length and digest; `represent_inbound` verified them and stamped ``bodykeys.READ_OBSERVATION = (chars, digest)`` for
    the text it placed LAST in the tool's payload. This re-verifies that exact span inside the payload's outer boundary
    (`resultnotes.payload_of`) — position and digest, never a search for the text — so a reducer, redaction or note that
    changed the bytes loses the credit. The ONE owner of "was the file returned, and what was it": ``""`` is a real
    answer (an empty file); None is unknown."""
    if not isinstance(message, dict) or message.get("role") != "tool":
        return None
    obs = message.get(bodykeys.READ_OBSERVATION)
    content = message.get("content") if message.get("content") is not None else message.get("output")
    if not (isinstance(obs, (tuple, list)) and len(obs) == 2 and isinstance(obs[0], int) and isinstance(obs[1], str)
            and isinstance(content, str)):
        return None
    payload = payloadboundary.payload_of(message, content)
    n = obs[0]
    if payload is None or not 0 <= n <= len(payload):
        return None
    text = payload[len(payload) - n:]
    return text if text_digest(text) == obs[1] else None


def returned_text(message) -> str | None:
    """The text a READ result may stand as the file's (or window's) bytes, or None — THE ONE rule every positive read-fact
    reader shares (the loop ledger, the research ledger): a cria-lowered read counts only through its VERIFIED body
    (`read_payload`); a lowered result whose body did not verify (cut, rewritten, no record) is UNKNOWN and returns None; a
    NATIVE result (no cria record to consult) is the harness's own text. Never a refused or unproven lowering's bytes."""
    if not isinstance(message, dict) or message.get("role") != "tool":
        return None
    if (verified := read_payload(message)) is not None:
        return verified
    if proof(message) is not None:
        return None
    content = message.get("content") if message.get("content") is not None else message.get("output")
    if isinstance(content, list):
        content = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else None


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def outcome(message) -> str | None:
    """What cria proved about this tool-result message, or None (unknown — never "it ran")."""
    if not isinstance(message, dict) or message.get("role") != "tool":
        return None
    value = message.get(bodykeys.RESULT_OUTCOME)
    return value if value in (REFUSED, UNAPPLIED) else None


def proof(message) -> str | None:
    """The raw hint on a tool result: ``refused`` / ``unapplied`` / ``ran`` (the lowering's own real branch
    printed its frame) / ``unknown`` (a cria-lowered call that could not be proven), or None (a native result:
    cria authored nothing there)."""
    if not isinstance(message, dict) or message.get("role") != "tool":
        return None
    value = message.get(bodykeys.RESULT_OUTCOME)
    return value if value in (REFUSED, UNAPPLIED, RAN, LANDED, UNCERTAIN, UNKNOWN) else None


def attributable_read(message) -> bool:
    """May this tool result stand as the BYTES of the file it names? Never when cria's own refusal produced it, and
    never when it is a cria-lowered result whose branch could not be proven (the legacy own oversize refusal that
    exits 0 and carries no frame, a read whose proof was lost): unknown is not positive either."""
    return proof(message) not in (REFUSED, UNAPPLIED, UNCERTAIN, UNKNOWN)


def report(message) -> dict:
    """The producer's typed reports on this result (`resultpacket.REPORT_KEYS`), ``{}`` when it declared none. Set only by
    `represent_inbound` from the first record of a proven call; a client-sent value is overwritten."""
    if not isinstance(message, dict) or message.get("role") != "tool":
        return {}
    value = message.get(bodykeys.RESULT_REPORT)
    return value if isinstance(value, dict) else {}


def landed(message) -> bool:
    """Did cria's OWN write/edit program report the mutation landed? (A typed record, never a line found in output.)"""
    return proof(message) == LANDED


def refused(message) -> bool:
    return outcome(message) == REFUSED


def unlanded(message) -> bool:
    return outcome(message) is not None


def paired_results(messages) -> dict:
    """``call id -> its result message`` for every id whose call/result pairing is unambiguous: exactly ONE call
    and exactly ONE result name it, and the result comes AFTER the call. A reused id, a second result, a result
    with no call in view, or a result that precedes its call cannot say which call it answers, so it is absent —
    never assumed. The ONE owner of call/result correlation: proofs, answers and refusals all read it."""
    calls: Counter = Counter()
    call_at: dict = {}
    results: Counter = Counter()
    result_at: dict = {}
    for pos, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                cid = tc.get("id") if isinstance(tc, dict) else None
                if cid:
                    calls[cid] += 1
                    call_at.setdefault(cid, pos)
        elif m.get("role") == "tool":
            cid = m.get("tool_call_id") or m.get("call_id")
            if cid:
                results[cid] += 1
                result_at[cid] = (pos, m)
    return {cid: result_at[cid][1] for cid in result_at
            if calls.get(cid) == 1 and results.get(cid) == 1 and call_at[cid] < result_at[cid][0]}


def _unambiguous(messages, want) -> set:
    """Call ids whose unambiguously paired result carries the wanted proven outcome."""
    return {cid for cid, m in paired_results(messages).items() if want(m)}


def refused_call_ids(messages) -> set:
    """Ids of calls whose own refusal branch cria PROVED ran (the call did not)."""
    return _unambiguous(messages, refused)


def landed_call_ids(messages) -> set:
    """Ids of write-class calls whose OWN program reported, in its typed first record, that the mutation landed. THE one
    accessor for every reader that asks 'did this write land?' — none reads the rendered confirmation or any marker."""
    return _unambiguous(messages, landed)


def unlanded_call_ids(messages) -> set:
    """Ids of write-class calls cria PROVED did not change anything: its own refusal branch ran, or its edit
    program reported the edit not applied. ONE owner for every reader that asks 'did this land?'."""
    return _unambiguous(messages, unlanded)
