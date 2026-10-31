import json
from datetime import datetime, timezone
from email.utils import format_datetime
import pytest
from suite.sampling_adapter import RateLimitGate, inject_sampling, SamplingAdapter


def test_full_history_and_unknown_request_fields_survive_sampling():
    body={'model':'phi4', 'input':[{'role':'user','content':'α\n'*20000}],
          'tools':[{'type':'function','name':'echo'}], 'unknown': {'nested': ['keep']}}
    raw=json.dumps(body).encode()
    changed=json.loads(inject_sampling(raw, {'temperature':0.0}))
    assert changed == {**body,'temperature':0.0}
    assert json.loads(raw) == body


@pytest.mark.parametrize('knobs', [{'enable_thinking':True}, {'temperature':True}, {'top_k':'20'},
                                   {'temperature':float('nan')}, {'instructions': 'do work'}])
def test_only_explicit_finite_numeric_sampling_is_allowed(knobs):
    with pytest.raises(ValueError):
        inject_sampling(b'{}', knobs)


@pytest.mark.parametrize('headers,body,delay', [
    ({'Retry-After':'13'}, b'', 13),
    ({'Retry-After':format_datetime(datetime.fromtimestamp(1020, timezone.utc), usegmt=True)}, b'',20),
    ({'X-RateLimit-Reset-After':'21'}, b'',21),
    ({'X-RateLimit-Reset':'1030'}, b'',30),
    ({}, b'{"error":{"retry_after":17}}',17),
    ({}, b'{"error":{"message":"Please retry in 2m3s."}}',123),
])
def test_shared_gate_waits_across_instances_without_early_retry(tmp_path, headers, body, delay):
    clock=[1000.]
    sleeps=[]
    def sleep(seconds):
        sleeps.append(seconds); clock[0]+=seconds
    first=RateLimitGate(tmp_path, now=lambda:clock[0], sleep=sleep)
    first.observe(headers, 429, body)
    second=RateLimitGate(tmp_path, now=lambda:clock[0], sleep=sleep)
    second.wait()
    assert clock[0] >= 1000+delay
    assert sum(sleeps) >= delay


def test_google_retry_info_and_structured_rate_limit(tmp_path):
    clock=[1000.]
    gate=RateLimitGate(tmp_path, now=lambda:clock[0], sleep=lambda t: clock.__setitem__(0,clock[0]+t))
    gate.observe({},429,b'{"error":{"details":[{"@type":"google.rpc.RetryInfo","retryDelay":"12s"}]}}')
    gate.wait(); assert clock[0] == 1012
    gate.observe({'RateLimit':'"requests";r=0;t=21'},200)
    gate.wait(); assert clock[0] == 1033


def test_positive_remaining_reset_headers_do_not_delay_healthy_calls(tmp_path):
    gate=RateLimitGate(tmp_path,now=lambda:1000.,sleep=lambda _:pytest.fail('healthy delay'))
    gate.observe({'X-RateLimit-Remaining':'9','X-RateLimit-Reset':'1030',
                  'X-RateLimit-Reset-After':'30'},200)
    gate.wait()


def test_real_http_forwards_full_sse_and_error_once(tmp_path):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import http.client,threading
    seen=[]
    response='event: response.output_text.delta\ndata: {"delta":"α\\n"}\n\ndata: [DONE]\n\n'.encode()
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200 if len(seen)==1 else 429)
            self.send_header('Content-Type','text/event-stream' if len(seen)==1 else 'application/json')
            self.end_headers()
            self.wfile.write(response if len(seen)==1 else b'{"error":{"retry_after":30}}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        body={'input':[{'role':'user','content':'α\n'*100000}],'model':'phi4','tools':[]}
        gate=RateLimitGate(tmp_path)
        with SamplingAdapter({'temperature':0.0},gate,target=server.server_address) as adapter:
            assert adapter.server.server_address[0]=='127.0.0.1'
            for index in range(2):
                conn=http.client.HTTPConnection(*adapter.server.server_address)
                conn.request('POST','/v1/responses',json.dumps(body),{'Content-Type':'application/json'})
                reply=conn.getresponse()
                assert reply.status==(200 if index==0 else 429)
                assert reply.read()==(response if index==0 else b'{"error":{"retry_after":30}}')
                conn.close()
            assert seen==[{**body,'temperature':0.0}]*2
            assert len(adapter.injected)==2
        assert json.loads(gate.path.read_text())['not_before'] > gate.now()+28
    finally:
        server.shutdown();server.server_close();thread.join()
