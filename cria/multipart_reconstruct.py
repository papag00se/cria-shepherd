"""Verify one reassembled producer stdout through the canonical packet owner.

Do not reimplement the resultpacket parser or invent a tool result. The returned
text is exactly the stream printed by the producer, ready for inbound ownership.
"""
from dataclasses import dataclass
from cria import resultpacket
from .multipart import MultipartRead, InvalidPage


class BinaryBody(InvalidPage):
    pass


@dataclass(frozen=True)
class VerifiedOriginal:
    stdout: str
    exit_code: int
    outcome: str
    write_outcome: str


def verify_original(assembly: MultipartRead, receipt: str) -> VerifiedOriginal:
    raw = assembly.finish()
    try:
        text = raw.decode('utf-8', 'strict')
    except UnicodeDecodeError as exc:
        raise InvalidPage('original stdout is not UTF-8; cannot represent losslessly as text') from exc
    record = resultpacket.read_record(text, 0, receipt)
    if record is None:
        raise InvalidPage('original resultpacket failed verification')
    if record.body is not None:
        try:
            record.body.decode('utf-8', 'strict')
        except UnicodeDecodeError as exc:
            raise BinaryBody('binary body requires an explicit byte-oriented operation') from exc
    if assembly.result_outcome == 'read':
        if record.kind != resultpacket.RAN or (record.body is not None and record.observe != assembly.semantics):
            raise InvalidPage('read result disagrees with original record')
    elif assembly.result_outcome == 'read-instead':
        if record.kind != resultpacket.REFUSED or record.body is None or record.observe != assembly.semantics:
            raise InvalidPage('read-instead disagrees with original record')
    if assembly.result_outcome in ('error', 'refused') and record.observe:
        raise InvalidPage('failed outcome conflicts with read observation')
    if assembly.write_outcome == 'not_run' and record.kind != resultpacket.REFUSED:
        raise InvalidPage('write outcome disagrees with original record')
    if assembly.write_outcome == 'unknown' and record.kind == resultpacket.REFUSED:
        # Passing this record to inbound would prove nonexecution despite the
        # page's explicit unknown. Conflicting declarations fail closed.
        raise InvalidPage('unknown write outcome conflicts with refusal record')
    return VerifiedOriginal(text, assembly.exit_code, assembly.result_outcome, assembly.write_outcome)
