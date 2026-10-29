"""Multipart consumer; no executor.

Producer contract: one ASCII JSON line per harness result. Source identity and
selected-stream identity must agree on every page; offsets are stream offsets.
A caller MUST NOT publish any page or grant read credit until finish() succeeds.
"""
from __future__ import annotations
import base64
import hashlib
import json
from dataclasses import dataclass, field

STDOUT_LIMIT = 10_000


class InvalidPage(ValueError):
    pass


class BridgeError(ValueError):
    pass


@dataclass(frozen=True)
class UnverifiedCarrier:
    """Request-private provenance for exact tool-result display, not credit."""
    pass


def _pairs(items):
    d = {}
    for key, value in items:
        if key in d:
            raise InvalidPage('duplicate key')
        d[key] = value
    return d


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _nat(value):
    return type(value) is int and value >= 0


@dataclass
class MultipartRead:
    token: str
    outcome: str
    semantics: str
    offset: int = 0
    identity: tuple | None = None
    result_outcome: str | None = None
    exit_code: int | None = None
    write_outcome: str | None = None
    _parts: list[bytes] = field(default_factory=list, repr=False)
    _failed: bool = False
    _complete: bool = False

    def accept(self, wire: bytes) -> bool:
        """Consume exactly the stdout record, not a searched marker or envelope.

        Returns true only on verified completion. A failure poisons the whole
        assembly; no prefix remains publishable, including after a later retry.
        """
        if self._failed or self._complete:
            raise InvalidPage('assembly is closed')
        try:
            return self._accept(wire)
        except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
            self._failed = True
            self._parts.clear()
            raise InvalidPage(str(exc)) from exc

    def _accept(self, wire):
        if not isinstance(wire, bytes) or len(wire) > STDOUT_LIMIT or not wire.endswith(b'\n') or b'\n' in wire[:-1]:
            raise InvalidPage('invalid or oversized stdout')
        obj = json.loads(wire[:-1].removesuffix(b'\r').decode('ascii'), object_pairs_hook=_pairs)
        keys = {'v','token','outcome','semantics','source_length','source_sha256',
                'stream_length','stream_sha256','offset','length','page_sha256','data',
                'exit_code','write_outcome'}
        if not isinstance(obj, dict) or set(obj) != keys or type(obj['v']) is not int or obj['v'] != 1:
            raise InvalidPage('invalid schema')
        if obj['token'] != self.token or not self.token or obj['semantics'] != self.semantics:
            raise InvalidPage('correlation or semantics mismatch')
        if self.outcome not in ('read','read-instead') or self.semantics not in ('whole','range'):
            raise InvalidPage('invalid request')
        if obj['outcome'] not in (self.outcome, 'refused', 'error'):
            raise InvalidPage('invalid outcome')
        valid_write = ('not_run', 'unknown') if self.outcome == 'read-instead' else ('not_applicable',)
        if obj['write_outcome'] not in valid_write:
            raise InvalidPage('invalid write outcome')
        no_source = obj['source_length'] is None and obj['source_sha256'] is None
        source_valid = _nat(obj['source_length']) and _hash(obj['source_sha256'])
        if (not source_valid and not (no_source and obj['outcome'] in ('refused', 'error'))
            or not all(_nat(obj[k]) for k in ('stream_length','offset','length','exit_code'))
            or not all(_hash(obj[k]) for k in ('stream_sha256','page_sha256'))):
            raise InvalidPage('invalid lengths or digests')
        identity = (obj['source_length'],obj['source_sha256'],obj['stream_length'],obj['stream_sha256'],
                    obj['outcome'],obj['exit_code'],obj['write_outcome'])
        if self.identity is not None and identity != self.identity:
            raise InvalidPage('snapshot or stream changed')
        if obj['offset'] != self.offset:
            raise InvalidPage('noncontiguous page')
        data = base64.b64decode(obj['data'], validate=True)
        if len(data) != obj['length'] or hashlib.sha256(data).hexdigest() != obj['page_sha256']:
            raise InvalidPage('page length or digest mismatch')
        end = self.offset + len(data)
        if end > obj['stream_length'] or (not data and end != obj['stream_length']):
            raise InvalidPage('invalid page extent')
        self.identity = identity
        self.result_outcome = obj['outcome']
        self.exit_code = obj['exit_code']
        self.write_outcome = obj['write_outcome']
        self.offset = end
        self._parts.append(data)
        if end == obj['stream_length']:
            joined = b''.join(self._parts)
            if hashlib.sha256(joined).hexdigest() != obj['stream_sha256']:
                raise InvalidPage('assembled stream digest mismatch')
            self._complete = True
        return self._complete

    def finish(self) -> bytes:
        if self._failed or not self._complete:
            raise InvalidPage('incomplete or failed assembly')
        return b''.join(self._parts)
