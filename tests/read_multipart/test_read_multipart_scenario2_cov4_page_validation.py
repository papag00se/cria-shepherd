"""Multipart page assembly and original-stdout verification, walked defect by defect through the public entries (`MultipartRead.accept`,
`verify_original`): every malformed, forged, reordered or contradictory page poisons the assembly and nothing partial is publishable; a
verified stream is handed to inbound ownership only when the producer's record agrees with what the page declared."""
import base64
import hashlib
import json

import pytest

from cria import multipart, resultpacket
from cria.multipart import InvalidPage, MultipartRead
from cria.multipart_reconstruct import BinaryBody, verify_original

TOKEN = "t0k"
SHA = lambda b: hashlib.sha256(b).hexdigest()
LIVE = {"mode": "live", "reason": None, "taken": None, "now": None}
IDENT = [1, 2, 3, 4]


def page(data=b"hello", offset=0, stream=None, **over):
    """One producer page of `stream` (default: just `data`), as the exact stdout line."""
    stream = data if stream is None else stream
    obj = {"v": 1, "token": TOKEN, "outcome": "read", "semantics": "whole", "source_length": len(stream), "source_sha256": SHA(stream),
           "stream_length": len(stream), "stream_sha256": SHA(stream), "offset": offset, "length": len(data), "page_sha256": SHA(data),
           "data": base64.b64encode(data).decode(), "exit_code": 0, "write_outcome": "not_applicable", "snapshot": dict(LIVE)}
    obj.update(over)
    return json.dumps(obj, separators=(",", ":")).encode() + b"\n"


def reading(outcome="read", semantics="whole"):
    return MultipartRead(TOKEN, outcome, semantics)


BAD_PAGES = [
    ("not bytes", "text", "invalid or oversized"), ("no trailing newline", b"{}", "invalid or oversized"),
    ("two lines", b"{}\n{}\n", "invalid or oversized"),
    ("duplicate key", page().replace(b'"v":1', b'"v":1,"v":1'), "duplicate key"),
    ("extra key", page(extra=1), "invalid schema"), ("version 2", page(v=2), "invalid schema"), ("bool version", page(v=True), "invalid schema"),
    ("not an object", b"[1]\n", "invalid schema"),
    ("wrong token", page(token="other"), "correlation"), ("wrong semantics", page(semantics="range"), "correlation"),
    ("unknown outcome", page(outcome="skipped"), "invalid outcome"),
    ("read declares a write outcome", page(write_outcome="not_run"), "invalid write outcome"),
    ("source hash not hex", page(source_sha256="Z" * 64), "lengths or digests"), ("negative offset", page(offset=-1), "lengths or digests"),
    ("bool length", page(stream_length=True), "lengths or digests"), ("short page hash", page(page_sha256="ab"), "lengths or digests"),
    ("non-int exit code", page(exit_code="0"), "lengths or digests"), ("source absent on a normal read", page(source_length=None, source_sha256=None), "lengths or digests"),
    ("snapshot not an object", page(snapshot=None), "invalid snapshot object"),
    ("snapshot missing a key", page(snapshot={"mode": "live"}), "invalid snapshot object"),
    ("snapshot identity malformed", page(snapshot={**LIVE, "taken": [1, 2]}), "snapshot identity"),
    ("snapshot mode unknown", page(snapshot={**LIVE, "mode": "cached"}), "snapshot mode"),
    ("snapshot without a taken identity", page(snapshot={**LIVE, "mode": "snapshot"}), "invalid snapshot object"),
    ("snapshot with a reason", page(snapshot={"mode": "snapshot", "reason": "over_cap", "taken": IDENT, "now": IDENT}), "invalid snapshot object"),
    ("live with an unknown reason", page(snapshot={**LIVE, "reason": "because"}), "invalid snapshot object"),
    ("live claiming an identity", page(snapshot={**LIVE, "now": IDENT}), "invalid snapshot object"),
    ("nonzero first offset", page(offset=1), "noncontiguous"), ("data is not base64", page(data=b"hello").replace(b'"aGVsbG8="', b'"!!!!"'), "digest|length|base64|Incorrect|Invalid"),
    ("length lies", page(length=4), "length or digest"), ("page hash lies", page(page_sha256=SHA(b"other")), "length or digest"),
    ("page runs past the stream", page(stream_length=3), "page extent"),
    ("stream hash lies on completion", page(stream_sha256=SHA(b"other")), "assembled stream digest"),
]


@pytest.mark.parametrize("label,wire,message", BAD_PAGES, ids=[b[0] for b in BAD_PAGES])
def test_a_defective_page_poisons_the_assembly_and_nothing_is_publishable(label, wire, message):
    """Each defect names its cause, closes the assembly for good (a later GOOD page is refused too) and leaves finish() unavailable."""
    assembly = reading()
    with pytest.raises(InvalidPage, match=message):
        assembly.accept(wire)
    with pytest.raises(InvalidPage, match="closed"):
        assembly.accept(page())
    with pytest.raises(InvalidPage, match="incomplete or failed"):
        assembly.finish()


def test_the_request_itself_must_be_a_read_or_read_instead_of_whole_or_range():
    for outcome, semantics in (("write", "whole"), ("read", "tail")):
        with pytest.raises(InvalidPage, match="invalid request"):
            MultipartRead(TOKEN, outcome, semantics).accept(page(semantics=semantics))
    with pytest.raises(InvalidPage, match="correlation"):
        MultipartRead("", "read", "whole").accept(page(token=""))


def test_pages_must_continue_one_stream_and_a_refusal_may_carry_no_source():
    """Two pages of one stream assemble; a replayed offset, a changed stream, a changed exit code or a snapshot flip between pages is refused;
    a refused/error outcome may carry no source at all, and an empty page is only valid at the very end."""
    stream = b"abcdefgh"
    first, second = page(stream[:4], 0, stream), page(stream[4:], 4, stream)
    ok = reading()
    assert ok.accept(first) is False and ok.accept(second) is True and ok.finish() == stream and ok.exit_code == 0 and ok.live_pages
    for label, follow, message in (("replayed offset", first, "noncontiguous"), ("other exit code", page(stream[4:], 4, stream, exit_code=1), "changed"),
                                   ("other stream", page(b"zzzz", 4, b"abcdzzzz"), "changed"),
                                   ("snapshot flips to live→snapshot", page(stream[4:], 4, stream, snapshot={"mode": "snapshot", "reason": None, "taken": IDENT, "now": IDENT}), "changed")):
        broken = reading()
        broken.accept(first)
        with pytest.raises(InvalidPage, match=message):
            broken.accept(follow)
    refused = reading()
    assert refused.accept(page(b"", 0, b"", outcome="error", source_length=None, source_sha256=None, exit_code=2)) is True
    assert refused.result_outcome == "error" and refused.exit_code == 2 and refused.finish() == b""
    early_empty = reading()
    early_empty.accept(first)
    with pytest.raises(InvalidPage, match="page extent"):
        early_empty.accept(page(b"", 4, stream))


def test_a_snapshot_page_reports_whether_the_source_moved_since_it_was_taken():
    """mode snapshot: source_changed compares the LAST page's path identity to the taken one (absent counts as changed); live pages claim nothing."""
    def snap(now):
        return page(snapshot={"mode": "snapshot", "reason": None, "taken": IDENT, "now": now})
    same, moved, gone = reading(), reading(), reading()
    for assembly, wire in ((same, snap(IDENT)), (moved, snap([9, 9, 9, 9])), (gone, snap(None))):
        assembly.accept(wire)
    assert (same.source_changed, moved.source_changed, gone.source_changed) == (False, True, True)
    assert not same.live_pages and not reading().live_pages and not reading().source_changed
    over_cap = reading()
    over_cap.accept(page(snapshot={**LIVE, "reason": "over_cap"}))
    assert over_cap.live_pages and over_cap.snapshot == ("live", "over_cap", None)


RECEIPT = "0123456789abcdef"


def assembled(record_text, outcome="read", result=None, write="not_applicable", semantics="whole", exit_code=0):
    """The page the producer would print for `record_text` as its stream (its outcome defaults to the request's)."""
    wire = page(record_text.encode(), outcome=result or outcome, write_outcome=write, exit_code=exit_code, semantics=semantics)
    assembly = MultipartRead(TOKEN, outcome, semantics)
    assert assembly.accept(wire) is True
    return assembly


def packet(kind, body=b"file body\n", observe=resultpacket.WHOLE):
    return resultpacket.line(RECEIPT, kind, body=body, observe=observe)


@pytest.mark.parametrize("label,build,message", [
    ("a record that does not verify", lambda: assembled("not a packet\n"), "failed verification"),
    ("a record for another receipt", lambda: assembled(resultpacket.line("f" * 16, resultpacket.RAN, body=b"x", observe="whole")), "failed verification"),
    ("a read whose record is a refusal", lambda: assembled(packet(resultpacket.REFUSED)), "read result disagrees"),
    ("a read whose observation is a range, not whole", lambda: assembled(packet(resultpacket.RAN, observe=resultpacket.RANGE)), "read result disagrees"),
    ("read-instead whose record ran", lambda: assembled(packet(resultpacket.RAN), outcome="read-instead", write="not_run"), "read-instead disagrees"),
    ("read-instead with no body", lambda: assembled(resultpacket.line(RECEIPT, resultpacket.REFUSED), outcome="read-instead", write="not_run"), "read-instead disagrees"),
    ("read-instead with the wrong observation", lambda: assembled(packet(resultpacket.REFUSED, observe=resultpacket.RANGE), outcome="read-instead", write="not_run"), "read-instead disagrees"),
    ("an error that claims a read observation", lambda: assembled(packet(resultpacket.RAN), result="error"), "failed outcome conflicts"),
    ("a refusal that claims a read observation", lambda: assembled(packet(resultpacket.REFUSED), result="refused"), "failed outcome conflicts"),
    ("write not_run over a record that ran", lambda: assembled(packet(resultpacket.RAN, observe=""), outcome="read-instead", result="refused", write="not_run"), "write outcome disagrees"),
    ("write unknown over a refusal record", lambda: assembled(packet(resultpacket.REFUSED, observe=""), outcome="read-instead", result="refused", write="unknown"), "unknown write outcome conflicts"),
])
def test_an_original_stream_is_verified_against_what_the_pages_declared(label, build, message):
    with pytest.raises(InvalidPage, match=message):
        verify_original(build(), RECEIPT)


def test_a_verified_original_carries_its_stdout_and_declarations_and_binary_or_non_utf8_is_refused():
    """A whole read and a read-instead refusal (write never ran / unknown) verify and return the exact stdout with the page's declarations; a
    binary body is a BinaryBody (an InvalidPage), and stdout that is not UTF-8 cannot be represented as text at all."""
    ran = packet(resultpacket.RAN)
    got = verify_original(assembled(ran, exit_code=3), RECEIPT)
    assert (got.stdout, got.exit_code, got.outcome, got.write_outcome) == (ran, 3, "read", "not_applicable")
    refusal = packet(resultpacket.REFUSED)
    not_run = verify_original(assembled(refusal, outcome="read-instead", write="not_run"), RECEIPT)
    assert (not_run.stdout, not_run.outcome, not_run.write_outcome) == (refusal, "read-instead", "not_run")
    unknown = verify_original(assembled(packet(resultpacket.RAN, observe=""), outcome="read-instead", result="error", write="unknown", exit_code=1), RECEIPT)
    assert (unknown.outcome, unknown.write_outcome, unknown.exit_code) == ("error", "unknown", 1)
    with pytest.raises(BinaryBody, match="byte-oriented"):
        verify_original(assembled(packet(resultpacket.RAN, body=b"\xff\xfe\x00\x80")), RECEIPT)
    assert issubclass(BinaryBody, InvalidPage)
    raw = MultipartRead(TOKEN, "read", "whole")
    raw.accept(page(b"\xff\xfe"))
    with pytest.raises(InvalidPage, match="not UTF-8"):
        verify_original(raw, RECEIPT)
