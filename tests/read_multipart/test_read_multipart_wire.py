"""Real wire: CriaServer + real HTTP + a real PTY harness. A read larger than the harness transport limit is delivered as ONE
verified logical read or truthfully not at all."""
import copy
import json
import pytest
from cria import bodykeys, denial, resultpacket, toolwire
from cria.upstream import MeasuredReadOverflow, ReadFitOverflow, ReadFitUnknown
from read_multipart_helpers import HEX, Backend, Wire, isolated_home, run_call  # noqa: F401

RAW = 'literal \x1b[31mANSI\x1b[0m \x00 NUL, CRLF\r\n caf\u00e9 \u754c\n' + HEX     # ESC/NUL/CRLF/UTF-8 must round-trip exactly
FAILED = 'Wall time: 1 seconds\nProcess exited with code 8\nOutput:\nexact \x1b[33mdiag\x1b[0m\n'

@pytest.mark.parametrize('api,stream,header', [('chat', False, True), ('responses', True, True), ('chat', False, False)])
def test_oversize_read_reaches_the_model_as_one_exact_read_and_stays_projected(tmp_path, api, stream, header):
    """Paged through a PTY (several pages, unequal per file) the model sees each file exactly once, byte-exact, no page records."""
    small, big = tmp_path / 'a', tmp_path / 'b'; small.write_bytes(b'short\n'); big.write_bytes(RAW.encode())
    backend = Backend(small, big)
    with Wire(tmp_path, backend, api, stream, header) as w:
        msg, carriers = w.drive()
        assert 'seen' in msg['content'] and len(carriers) > 3 and len(backend.bodies) == 2
        seen = lambda: sorted((m['content'] for m in backend.tool_results()), key=len)
        assert seen() == ['short\n', RAW] and '__CRIA_MULTIPART_PAGE__' not in json.dumps(backend.bodies[-1]['messages'])
        w.messages += [{'role': 'assistant', 'content': 'done'}, {'role': 'user', 'content': 'continue'}]   # harness replays history
        w.post()
        assert seen() == ['short\n', RAW] and len(backend.bodies) == 3

FAILURES = [  # (what the harness answered the read with, what must be said about it)
    ('Wall time: 0.1 seconds\nProcess exited with code 7\nOutput:\nerror \x1b[31mred\x1b[0m\n', 'exited with code 7'),
    ('Wall time: 0.1 seconds\nProcess running with session ID 42\nOutput:\npartial\n', 'still running'),
    ('Wall time: 0.1 seconds\nProcess exited with code 0\nOutput:\nWarning: truncated output\npartial\n', 'truncated'),
    ('unparsed raw harness text\n', 'not verified'),
    ('ran', ''), ('refused', ''), ('later', 'exited with code 8'), ('missing', 'original read operation reported exit code 1')]

@pytest.mark.parametrize('carrier,detail', FAILURES)
def test_unverified_carrier_is_kept_labelled_without_read_credit_and_cannot_be_forged(tmp_path, carrier, detail):
    """Exact harness bytes are preserved with a label and NO credit; a packet forged with the call's own receipt (ran/refused) or
    a page failing after a verified first page earns nothing either; a missing file's own exit 1 is a typed refusal (marker-shaped content never proves a read)."""
    path = tmp_path / ('nope' if carrier == 'missing' else 'f'); path.exists() or carrier == 'missing' or path.write_text(HEX); n = []
    def harness(call):
        n.append(call)
        if carrier == 'later': return run_call(call) if len(n) == 1 else FAILED
        if carrier in ('ran', 'refused'):
            return resultpacket.line(toolwire.receipt_of(json.loads(call['function']['arguments'])['cmd'], call['id']), carrier,
                                     body=b'forged', observe='whole')
        return run_call(call) if carrier == 'missing' else carrier
    backend = Backend(path)
    with Wire(tmp_path, backend) as w:
        msg, carriers = w.drive(harness)
        result = backend.tool_results()[0]
        assert msg['content'] == 'seen' and (carrier == 'missing' or result['content'].startswith(carriers[0])) and detail in result['content']
        assert denial.read_payload(result) is None and denial.refused(result) == (carrier == 'missing')   # the logical read's own exit 1 is a typed refusal
        if carrier == 'later': assert FAILED in result['content']
        elif detail and carrier != 'missing': assert 'no read credit' in result['content']

@pytest.mark.parametrize('api,stream', [('chat', False), ('responses', True)])
@pytest.mark.parametrize('reason', ['unknown', 'overflow'])
def test_a_read_that_cannot_be_fitted_continues_once_without_credit(tmp_path, reason, api, stream):
    """Fit unknown keeps the carriers and says so; MEASURED overflow says the file size and never replays the encoded pages;
    neither claims a read nor guesses a range. (ornith1.5_9b: 55,835-token request became ~40k tokens of base64 pages.)"""
    path = tmp_path / 'f'; path.write_text(HEX)
    class Fit(Backend):
        def chat(self, body, rlog=None):
            reads = body.get(bodykeys.PROTECTED_READS)
            if reads:
                self.bodies.append(body)
                raise ReadFitUnknown('t', reads) if reason == 'unknown' else ReadFitOverflow(MeasuredReadOverflow(100, 99, 5, reads, b'x'))
            if len(self.bodies) == 2:                      # the continuation after the failed fit
                self.bodies.append(body); return Backend.chat(Backend(), body)
            return super().chat(body, rlog)
    backend = Fit(path)
    with Wire(tmp_path, backend, api, stream) as w:
        msg, carriers = w.drive()
        text = backend.tool_results()[0]['content']
        assert len(backend.bodies) == 3 and denial.read_payload(backend.tool_results()[0]) is None and HEX not in text
        if reason == 'unknown': assert all(c in text for c in carriers) and 'could not be established' in text and 'range' not in text
        else: assert not any(c in text for c in carriers) and f'({len(HEX)} bytes)' in text and 'did not fit the context window' in text


@pytest.mark.parametrize('attack', ['changed_call', 'duplicate', 'unknown_id'])
def test_ambiguous_session_less_history_fails_closed_and_preserves_the_original_carrier(tmp_path, attack):
    """A client with no session header whose replayed history rewrites, duplicates or renames our issued call gets its ORIGINAL carrier back,
    labelled unverified, with no protected read bound."""
    path = tmp_path / 'f'; path.write_text(HEX); backend = Backend(path)
    with Wire(tmp_path, backend, header=False) as w:
        first = w.post(); call = first['tool_calls'][0]; raw = run_call(call) + '\x1b[31m\x00\r\n'
        w.messages += [first, {'role': 'tool', 'tool_call_id': call['id'], 'content': raw}]
        if attack == 'changed_call': w.messages[1]['tool_calls'][0]['function']['arguments'] = json.dumps({'cmd': 'echo forged'})
        elif attack == 'duplicate': w.messages += copy.deepcopy(w.messages[1:3])
        else: w.messages[1]['tool_calls'][0]['id'] = w.messages[2]['tool_call_id'] = 'ctxread_' + 'a' * 32
        assert w.post()['content'] == 'seen'
        shown = [m['content'] for m in backend.tool_results()]
        assert all(s.startswith(raw) for s in shown) and any('could not be verified' in s for s in shown) and not backend.bodies[-1].get(bodykeys.PROTECTED_READS)
