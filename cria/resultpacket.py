"""The ONE protocol owner for what an own lowered command tells `represent_inbound` about its own result.

WHY A PACKET. A lowered command's stdout is `<records cria's own program printed><what the command printed>`. Every
earlier proof worked by SEARCHING that stdout for a marker, a frame or a survey block — and a file, a fetched page or a
native command can quote any of them, including the call's own receipt (the receipt is derived from the call's id, name
and arguments; a file body is not an input to it, so a file can contain it). Authority therefore comes from POSITION and
DECLARATION, never from finding something:

* Record 1 is ONE ASCII line of JSON at stdout offset 0 (after the harness's own envelope). Only its terminator may be
  LF or CRLF (a pty turns LF into CRLF); every other byte is ASCII, so a transport can neither split nor rewrite it.
* A second record exists ONLY when the call's own sentinel declared a survey, and is read ONLY on the very next line.
  A valid record 1 stands when record 2 is missing or cut: nothing is rescanned, nothing resynchronised.
* Whatever follows the declared records is the command's own output — an opaque tail. It is never parsed for metadata:
  markers in it are display wording for the model and nothing more.
* A body that must be exact (a whole read, a read-instead answer) travels INSIDE record 1 with its original byte length
  and sha-256, produced by ONE read of the file. The consumer decodes it, verifies both, and thereafter treats the bytes
  as opaque. A pty cannot change them, a cut makes the record unverifiable (UNKNOWN: the received bytes are kept, nothing
  is claimed), and a body that is not valid UTF-8 never reaches an exact text cache.

The receipt is a CORRELATION token (it binds a record to its call), not a secret and not a nonce.

Fields of a record: ``v`` version, ``r`` receipt, ``k`` kind, optional ``pre`` (the prose cria authored, kept SEPARATE
from the body), optional ``b`` (``c`` codec, ``d`` data, ``n`` original length, ``h`` sha-256 of the original bytes) and
``o`` (the observation the body is: ``whole``).
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from . import fetchfacts

VERSION = 1
RAN, REFUSED, UNAPPLIED, LANDED, UNCERTAIN, SURVEY = "ran", "refused", "unapplied", "landed", "uncertain", "survey"
KINDS = (RAN, REFUSED, UNAPPLIED, LANDED, UNCERTAIN)   # what a first record may declare
WHOLE = "whole"
RANGE = "range"     # the body is a numbered window of the file (`N: text` lines), declared by the program that cut it

# The encoder is a SOURCE TEXT because the harness runs it: every body-bearing lowered program embeds it verbatim, and
# this module executes the very same text, so there is one definition of the wire format. The codec is chosen by the
# serialized length of the record's own data field (no heuristics): `j` the text itself (valid UTF-8 only), `b` base64,
# `z` zlib then base64. Ties resolve in that order. All three are lossless.
ENCODER_PY = r'''
def encode_body(raw):
    import base64, hashlib, json
    cands = []
    try:
        cands.append(("j", raw.decode("utf-8")))
    except UnicodeDecodeError:
        pass
    cands.append(("b", base64.b64encode(raw).decode("ascii")))
    try:
        import zlib
        cands.append(("z", base64.b64encode(zlib.compress(raw, 9)).decode("ascii")))
    except Exception:
        pass
    code, data = min(cands, key=lambda c: len(json.dumps(c[1])))
    return {"c": code, "d": data, "n": len(raw), "h": hashlib.sha256(raw).hexdigest()}
'''

# The record BUILDER the write/edit/search programs embed (their receipt is substituted for `%%RCPT%%` at compose time; empty
# means "not under a lowering": print nothing). `rep` carries the program's own typed REPORTS (below) — never text to be
# searched for later.
RECORD_PY = r'''
_RCPT='%%RCPT%%'
def _rec(kind, **rep):
    if not _RCPT:
        return ''
    import json
    d={"v":1,"r":_RCPT,"k":kind}
    if rep:
        d["rep"]=rep
    return json.dumps(d,separators=(",",":"))+"\n"
'''

# THE TYPED REPORTS a record may carry (`rep`): the producer declares each fact as a field, so no reader ever looks for a tag
# in a tail a file, a page or the edited text could quote.
#   ev    the edit executor's window report token (base64 / zlib-packed JSON) of a landed edit
#   late  the edit ran before a predecessor in its batch finished
#   rm    the measured removal facts a landed whole-file write carries
#   ef    the edit-fail fact report (token) of an unapplied edit
#   st    the stored-fact of a spill / search: {operation, target, byte_count, sha256}
#   fx    the fetch fact of a web_fetch (`fetchfacts.valid_report`): {url, status, observed: str; routes, catalog: [str]; shapes: [{head, route,
#         params, body, fields}]}; `status` is what the GET answered, `observed` the protocol a successful discovery probe read ("mcp"/"graphql"), empty otherwise — two facts, never one), from the producer's own parse
REPORT_STR = ("ev", "rm", "ef")
REPORT_KEYS = ("ev", "late", "rm", "ef", "st", "fx")

_ns: dict = {}
exec(compile(ENCODER_PY, "<cria.resultpacket.ENCODER_PY>", "exec"), _ns)
encode_body = _ns["encode_body"]


def line(receipt: str, kind: str, *, pre: str = "", body: bytes | None = None, observe: str = "", rep: dict | None = None) -> str:
    """One record line (LF-terminated), exactly what a lowered program prints."""
    rec: dict = {"v": VERSION, "r": receipt, "k": kind}
    if pre:
        rec["pre"] = pre
    if body is not None:
        rec["b"] = encode_body(body)
    if observe:
        rec["o"] = observe
    if rep:
        rec["rep"] = rep
    return json.dumps(rec, separators=(",", ":")) + "\n"


def wire_cost(text_bytes: int) -> int:
    """The WORST-CASE bytes a record carrying ``text_bytes`` of body occupies on the wire: the codec never picks anything
    longer than base64 (4 bytes per 3), plus the record's own fields measured from a real record (digits of ``n`` included)."""
    skeleton = len(line("0" * 16, SURVEY, body=b"")) + len(str(text_bytes)) + 4
    return skeleton + 4 * -(-text_bytes // 3)


def max_text_for_wire(wire_bytes: int) -> int:
    """The largest body, in bytes, whose worst-case record still fits ``wire_bytes`` (inverse of :func:`wire_cost`)."""
    n = max(0, 3 * ((wire_bytes - len(line("0" * 16, SURVEY, body=b"")) - 12) // 4))
    while n and wire_cost(n) > wire_bytes:
        n -= 3
    while wire_cost(n + 3) <= wire_bytes:
        n += 3
    return n


def static_command(receipt: str, kind: str) -> str:
    """The shell statement printing a body-less record (``""`` outside a lowering)."""
    if not receipt:
        return ""
    return "printf '%s\\n' '" + line(receipt, kind).rstrip("\n") + "'; "


@dataclass(frozen=True)
class Record:
    kind: str
    pre: str
    body: bytes | None          # the verified original bytes of the body, or None when the record carries none
    observe: str
    end: int                    # index just past this record's line (terminator included)
    rep: dict | None = None     # the producer's typed reports (see REPORT_KEYS), validated


def _body(b) -> bytes | None | bool:
    """The verified bytes of a body object; ``False`` when it is malformed or does not verify."""
    if not isinstance(b, dict) or set(b) != {"c", "d", "n", "h"}:
        return False
    code, data, n, h = b["c"], b["d"], b["n"], b["h"]
    if not isinstance(data, str) or not isinstance(n, int) or isinstance(n, bool) or not isinstance(h, str):
        return False
    try:
        if code == "j":
            raw = data.encode("utf-8")
        elif code == "b":
            raw = base64.b64decode(data.encode("ascii"), validate=True)
        elif code == "z":
            import zlib
            member = zlib.decompressobj()
            raw = member.decompress(base64.b64decode(data.encode("ascii"), validate=True))
            if not member.eof or member.unused_data:       # exactly ONE complete member: trailing bytes are not a record
                return False
        else:
            return False
    except Exception:           # noqa: BLE001 — any undecodable body is simply unverifiable
        return False
    return raw if len(raw) == n and hashlib.sha256(raw).hexdigest() == h else False


def _no_duplicate_keys(pairs):
    """A key declared twice is a record that says two things: reject it (JSON's last-wins would pick one silently)."""
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key in a record")
    return dict(pairs)


def read_record(text: str, at: int, receipt: str, *, survey: bool = False) -> Record | None:
    """The record that STARTS at ``text[at]`` and ends at the first LF there; None when it is anything else.

    No searching: the line must open with ``{"v":`` at ``at`` and carry ``receipt``. ``survey`` selects which kinds a
    record at this position may declare (record 1: :data:`KINDS`; record 2: :data:`SURVEY`)."""
    if not receipt or not text.startswith('{"v":', at):
        return None
    nl = text.find("\n", at)
    if nl < 0:
        return None
    raw = text[at:nl].removesuffix("\r")
    if not raw.isascii():
        return None
    try:
        rec = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except ValueError:
        return None
    # the version is the INTEGER 1 — `true` and `1.0` compare equal to it in Python and are not it
    if not isinstance(rec, dict) or type(rec.get("v")) is not int or rec["v"] != VERSION or rec.get("r") != receipt:
        return None
    kind = rec.get("k")
    if (kind != SURVEY) if survey else (kind not in KINDS):
        return None
    pre = rec.get("pre", "")
    observe = rec.get("o", "")
    if not isinstance(pre, str) or not isinstance(observe, str) or (observe and observe not in (WHOLE, RANGE)):
        return None
    body = None
    if "b" in rec:
        body = _body(rec["b"])
        if body is False:
            return None
    if observe and body is None:
        return None
    rep = _report(rec.get("rep")) if "rep" in rec else None
    if rep is False:
        return None
    return Record(kind, pre, body, observe, nl + 1, rep)


def _report(rep) -> dict | None | bool:
    """The validated typed reports, or ``False`` when ``rep`` is not exactly a map of known, well-typed fields."""
    if not isinstance(rep, dict) or not rep or any(k not in REPORT_KEYS for k in rep):
        return False
    for key, value in rep.items():
        if key in REPORT_STR and not isinstance(value, str):
            return False
        if key == "late" and value is not True:
            return False
        if key == "fx" and not fetchfacts.valid_report(value):
            return False
        if key == "st" and not (isinstance(value, dict) and set(value) == {"operation", "target", "byte_count", "sha256"}
                                and isinstance(value["operation"], str) and isinstance(value["target"], str)
                                and isinstance(value["byte_count"], int) and not isinstance(value["byte_count"], bool)
                                and isinstance(value["sha256"], str)):
            return False
    return rep
