"""A suite checkpoint must not freeze a client with an unconsumed generated action.

Run1792338837 paused the client before 0031's completed native call arrived; on
resume an equivalent request advanced the driver to a periodic check instead.
That incident is why checkpoints no longer pause the client at all (2026-10-26): the monitor copies the
workspace while the client keeps running, so there is no frozen client, no parked request and no retry.
Exercise the real HTTP producer, per-cell adapter, process and monitor.
No Codex/model/network service is launched: the coder endpoint is a CPU fixture.

The adapter-level tests below (`quiesce`/`resume`/`cancel`) cover transport behavior the runner no longer
invokes at a checkpoint; `cancel` remains the terminal path, and `quiesce` is retained, unused by the runner.
"""
import http.client
import json
import socket
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from cria import server
from cria.assistprofiles import RANK4_ABLATION_DISABLED
from cria.config import AssistConfig, Config, IndicatorsConfig, LoggingConfig, Role, RoutingConfig, ServerConfig
from cria.events import EventLog
from suite import milestones, run
from suite.sampling_adapter import RateLimitGate, SamplingAdapter
from test_server import _CLASSIFY_JSON


CLIENT = r'''
import http.client,json,pathlib,sys,time
host,port,root=sys.argv[1],int(sys.argv[2]),pathlib.Path(sys.argv[3])
body={'model':'fixture','stream':True,'prompt_cache_key':'checkpoint-fixture',
 'input':[{'role':'user','content':'Implement the requested artifact.'}],
 'tools':[{'type':'function','name':'exec_command','parameters':{'type':'object',
 'properties':{'cmd':{'type':'string'}},'required':['cmd']}}]}
def request(value):
 c=http.client.HTTPConnection(host,port,timeout=.15)
 try:
  c.request('POST','/v1/responses',json.dumps(value),{'Content-Type':'application/json'})
  r=c.getresponse()
  if r.status>=400:
   r.read(); raise OSError('retryable checkpoint admission '+str(r.status))
  while True:
   line=r.readline()
   if not line: raise OSError('incomplete SSE')
   if line.startswith(b'data: '):
    event=json.loads(line[6:])
    if event.get('type')=='response.completed': return event['response']
 finally: c.close()
first=request(body)
call=next(v for v in first['output'] if v['type']=='function_call')
(root/'received.json').write_text(json.dumps(call))
body['input'] += [call,{'type':'function_call_output','call_id':call['call_id'],'output':'action observed'}]
errors=[]
for attempt in range(3):
 try:
  second=request(body); break
 except OSError as e: errors.append(str(e))
else: raise RuntimeError(errors)
(root/'finished.json').write_text(json.dumps({'errors':errors,'response':second}))
'''


def test_a_checkpoint_during_an_in_flight_response_freezes_nothing_and_loses_no_action(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    coder, classifier = Mock(), Mock()
    classifier.chat.return_value = _CLASSIFY_JSON
    def reply(*_args, **_kwargs):
        entered.set()
        assert release.wait(10)
        # Make the next acknowledged request eligible for the real periodic gate.
        owner = application.loop._store.get('sid:checkpoint-fixture')
        owner.coder_turns = 14
        return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{
            'role':'assistant','content':'Inspect the artifact.', 'tool_calls':[{
                'id':'original-action','type':'function','function':{
                    'name':'exec_command','arguments':'{"cmd":"echo action"}'}}]}}]}).encode()
    coder.chat_watched.side_effect = reply
    monkeypatch.setattr(server.Router, 'endpoint_for',
                        lambda _router, role: classifier if role == 'classifier' else coder)
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0, heartbeat_seconds=.02),
        assists=AssistConfig(profile='rank4-ablation'),
        # The L5-only ablation retains L1 classification: supply its answer so this
        # fresh request enters the real driver before exercising checkpoint delivery.
        routing=RoutingConfig(engagement_level=5, roles={
            name:Role(name=name, backend='local') for name in ('coder', 'classifier')}),
        logging=LoggingConfig(dir=str(tmp_path/'logs'), capture_dir=str(tmp_path/'calls'), console=False),
        indicators=IndicatorsConfig(enabled=False))
    log = EventLog(dir=cfg.logging.dir, console=False)
    application = server.CriaServer(cfg, log, Mock())
    serving = threading.Thread(target=application.serve_forever, daemon=True)
    serving.start()
    ws, task = tmp_path/'workspace', tmp_path/'task'
    ws.mkdir(); task.mkdir(); (task/'prompt.txt').write_text('Implement the requested artifact.')
    monkeypatch.setattr(milestones, 'ROOT', tmp_path/'checkpoints')
    outcome, errors = [], []
    verdict = json.dumps(dict(usefulness_percent=0, decision='continue', reason='Inspected source.',
                              material_changes='No implementation yet.', evidence=['snapshot'],
                              requirements=[dict(requirement='artifact', status='not_started', evidence='snapshot')],
                              pace_reason='Early.'))
    try:
        with SamplingAdapter({'temperature':0}, RateLimitGate(tmp_path/'rate'),
                             target=application.server_address) as adapter:
            proc = subprocess.Popen([sys.executable,'-c',CLIENT,*map(str,adapter.server.server_address),str(ws)],
                start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            control = run.HarnessControl(proc, adapter)
            pacing = run.MilestonePacing(time.time()-900,15,2)
            def monitor():
                try:
                    outcome.append(run.monitor_milestones(proc,pacing,'fixture',ws,task,stop=control.stop))
                except BaseException as error: errors.append(error)
            monitoring = threading.Thread(target=monitor, daemon=True)
            try:
                assert entered.wait(5)
                monitoring.start()
                packet = milestones.ROOT/'fixture.015min/packet.txt'
                deadline = time.monotonic()+5
                while not packet.exists() and time.monotonic()<deadline: time.sleep(.02)
                # The checkpoint was cut while the client is mid-response; nothing was stopped or parked.
                assert packet.exists() and not release.is_set()
                assert open(f'/proc/{proc.pid}/stat').read().rpartition(') ')[2].split()[0] != 'T'
                assert adapter._parked==0 and not adapter._paused
                milestones.verdict_path(milestones.ROOT/'fixture.015min').write_text(verdict)  # recorded whenever the agent gets to it
                release.set()
                monitoring.join(10)
                assert not monitoring.is_alive() and not errors, errors
                assert json.loads((ws/'received.json').read_text())['call_id']=='original-action'
                stdout, stderr = proc.communicate(timeout=5)
                assert proc.returncode==0, (stdout,stderr)
                finished=json.loads((ws/'finished.json').read_text())
                assert finished['errors']==[]   # incident: no parked request, no 503, no retry of an equivalent request
                assert coder.chat_watched.call_count==1  # the real periodic gate answers the next request, no new coder action
                events = [json.loads(line) for line in log.path.read_text().splitlines()]
                classifier.chat.assert_called_once()
                assert not any(event['kind'].startswith(('route.classify_error', 'route.classify_unparsed'))
                               for event in events)
                received = [event for event in events if event['kind']=='request.recv']
                assert len(received)==2  # the original request and its follow-up; nothing else ever reached the producer
                assert all(event['assist_profile']=='rank4-ablation' and
                           set(event['pilot_assists'])==set(application.pilot_runtime.selected) and
                           not set(event['pilot_assists']) & set(RANK4_ABLATION_DISABLED) for event in received)
                assert cfg.planner.enabled is False
                assert outcome[0][0]=='exited' and outcome[0][1][0]['status']=='judged'
                policy=json.loads((milestones.ROOT/'fixture.015min/policy.json').read_text())
                assert 900<=policy['actual_active_seconds']<905  # cut at the due time: nothing waited for a safe moment
                assert 'actual active elapsed' in (milestones.ROOT/'fixture.015min/packet.txt').read_text()
            finally:
                release.set(); control.stop()
                if monitoring.ident: monitoring.join(5)
    finally:
        application.shutdown(); application.server_close(); serving.join(); log.close()


@pytest.fixture
def echo_endpoint():
    observed = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_POST(self):
            observed.append(self.rfile.read(int(self.headers['Content-Length'])))
            body=json.dumps({'ordinal':len(observed)}).encode()
            self.send_response(200)
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
    endpoint=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=endpoint.serve_forever,daemon=True); thread.start()
    try: yield endpoint.server_address, observed
    finally: endpoint.shutdown(); endpoint.server_close(); thread.join()


def post(adapter, raw=b'{ "input": "equal new intent", "stream": false }'):
    connection=http.client.HTTPConnection(*adapter.server.server_address,timeout=5)
    try:
        connection.request('POST','/v1/responses',raw,{'Content-Type':'application/json'})
        reply=connection.getresponse()
        return reply.status,reply.read()
    finally: connection.close()


def test_noop_adapter_keeps_bytes_and_generates_legitimate_equal_requests(echo_endpoint,tmp_path):
    target,observed=echo_endpoint
    with SamplingAdapter(None,RateLimitGate(tmp_path/'rate'),target=target) as adapter:
        first,second=post(adapter),post(adapter)
    assert [json.loads(value[1])['ordinal'] for value in (first,second)]==[1,2]
    assert observed==[b'{ "input": "equal new intent", "stream": false }']*2
    assert not adapter.injected


@pytest.mark.parametrize('terminal',[False,True])
def test_all_parked_requests_reject_without_forward_or_ambiguous_replay(echo_endpoint,tmp_path,terminal):
    target,observed=echo_endpoint
    with SamplingAdapter(None,RateLimitGate(tmp_path/'rate'),target=target) as adapter:
        ready=[]
        pausing=threading.Thread(target=lambda:ready.append(adapter.quiesce(lambda:True)))
        pausing.start()
        with adapter._admission:
            assert adapter._admission.wait_for(lambda:adapter._paused,timeout=3)
        results=[]
        clients=[threading.Thread(target=lambda:results.append(post(adapter))) for _ in range(3)]
        for client in clients: client.start()
        with adapter._admission:
            assert adapter._admission.wait_for(lambda:adapter._parked==3,timeout=3)
        pausing.join(3)
        assert ready==[True] and not observed
        if terminal: adapter.cancel()
        else: adapter.resume()
        for client in clients: client.join(3)
        assert len(results)==3 and all(status==503 for status,_body in results)
        assert not observed
        status,_body=post(adapter)
        assert status==(503 if terminal else 200)
        assert len(observed)==(0 if terminal else 1)


def test_disconnected_parked_client_retires_without_forward_or_thread_error(echo_endpoint,tmp_path,capfd):
    target,observed=echo_endpoint
    with SamplingAdapter(None,RateLimitGate(tmp_path/'rate'),target=target) as adapter:
        ready=[]
        pausing=threading.Thread(target=lambda:ready.append(adapter.quiesce(lambda:True)))
        pausing.start()
        with adapter._admission:
            assert adapter._admission.wait_for(lambda:adapter._paused,timeout=3)
        connection=socket.create_connection(adapter.server.server_address)
        connection.sendall(b'POST /v1/responses HTTP/1.1\r\nHost: local\r\nContent-Length: 2\r\n\r\n{}')
        with adapter._admission:
            assert adapter._admission.wait_for(lambda:adapter._parked==1,timeout=3)
        connection.close()
        pausing.join(3); adapter.resume()
        with adapter._admission:
            assert adapter._admission.wait_for(lambda:adapter._parked==0 and adapter._inflight==0,timeout=3)
    assert ready==[True] and not observed
    assert 'Exception occurred' not in capfd.readouterr().err


def test_cancel_unblocks_quiescence_and_never_forwards_a_queued_intent(echo_endpoint,tmp_path):
    target,observed=echo_endpoint
    with SamplingAdapter(None,RateLimitGate(tmp_path/'rate'),target=target) as adapter:
        results=[]
        pausing=threading.Thread(target=lambda:results.append(adapter.quiesce(lambda:True)))
        pausing.start()
        with adapter._admission:
            assert adapter._admission.wait_for(lambda:adapter._paused,timeout=3)
        adapter.cancel(); pausing.join(3)
        assert not pausing.is_alive() and results==[False]
        assert post(adapter)[0]==503
    assert not observed


def test_natural_exit_closes_admission_before_surviving_child_grace_and_capture(echo_endpoint,tmp_path,monkeypatch):
    target,observed=echo_endpoint
    original_stop=run.stop_process_group
    calls=tmp_path/'terminal-calls'; calls.mkdir()
    child_code=r'''
import http.client,json,os,pathlib,signal,sys,time
root=pathlib.Path(sys.argv[1]); host=sys.argv[2]; port=int(sys.argv[3])
if os.fork()==0:
 signal.signal(signal.SIGINT,signal.SIG_IGN)
 (root/'child-ready').touch()
 while not (root/'terminal-grace').exists(): time.sleep(.005)
 c=http.client.HTTPConnection(host,port,timeout=3)
 c.request('POST','/v1/responses','{}',{'Content-Type':'application/json'})
 r=c.getresponse(); r.read(); (root/'child-status').write_text(str(r.status)); c.close()
 while True: time.sleep(1)
while not (root/'child-ready').exists(): time.sleep(.005)
'''
    with SamplingAdapter(None,RateLimitGate(tmp_path/'rate'),target=target) as adapter:
        proc=subprocess.Popen([sys.executable,'-c',child_code,str(tmp_path),*map(str,adapter.server.server_address)],
                              start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        control=run.HarnessControl(proc,adapter)
        def grace(_seconds):
            (tmp_path/'terminal-grace').touch()
            deadline=time.monotonic()+3
            while not (tmp_path/'child-status').exists() and time.monotonic()<deadline:
                time.sleep(.005)
            assert (tmp_path/'child-status').read_text()=='503'
            assert not observed
            # A CPU fixture finishing during grace must still be included after reaping.
            session=calls/'20261018-fixture'; session.mkdir()
            (session/'0001-coder.json').write_text('{"seq":1,"phase":"coder","body":{"messages":[]}}')
            (session/'0001-coder.response.json').write_text('{"choices":[]}')
        monkeypatch.setattr(run,'stop_process_group',lambda owned:original_stop(owned,grace=0,sleeper=grace))
        try:
            assert proc.wait(timeout=5)==0  # natural leader exit, real owned child still lives
            cutoff,sessions,snapshot=run.shutdown_and_capture(calls_dir=calls,before_sessions=set(),
                                                               stop=control.stop)
            assert len(sessions)==1 and snapshot['complete'] and len(snapshot['entries'])==1
            assert (sessions[0]/'0001-coder.response.json').stat().st_mtime<=cutoff
        finally:
            adapter.cancel()
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass


def test_a_checkpoint_never_signals_the_harness_with_or_without_an_admission_adapter(tmp_path, monkeypatch):
    signals=Mock()
    monkeypatch.setattr(run.os,'killpg',signals)
    ws,task=tmp_path/'ws',tmp_path/'task'
    ws.mkdir(); task.mkdir(); (task/'prompt.txt').write_text('Implement.')
    monkeypatch.setattr(milestones,'ROOT',tmp_path/'checkpoints')
    calls=[]
    proc=Mock(); proc.poll.side_effect=lambda: (calls.append(1), None if len(calls)<3 else 0)[1]
    monkeypatch.setattr(run.time,'sleep',lambda _seconds:None)
    terminal,judgments=run.monitor_milestones(proc,run.MilestonePacing(time.time()-900,15,2),'nosig',ws,task,stop=Mock())
    assert terminal=='exited' and [j['status'] for j in judgments]==['pending']
    signals.assert_not_called()


def test_exit_coincident_with_parked_request_is_not_reported_as_a_frozen_live_client(echo_endpoint,tmp_path):
    target,observed=echo_endpoint
    with SamplingAdapter(None,RateLimitGate(tmp_path/'rate'),target=target) as adapter:
        ready=[]
        # Emulate poll() changing to exited exactly when the next request parks.
        pausing=threading.Thread(target=lambda:ready.append(adapter.quiesce(lambda:not adapter._parked)))
        pausing.start()
        with adapter._admission:
            assert adapter._admission.wait_for(lambda:adapter._paused,timeout=3)
        status,_body=post(adapter)
        pausing.join(3)
        assert ready==[False] and status==503
    assert not observed


def test_natural_exit_during_quiescence_unparks_without_a_new_forward(echo_endpoint,tmp_path):
    target,observed=echo_endpoint
    with SamplingAdapter(None,RateLimitGate(tmp_path/'rate'),target=target) as adapter:
        assert adapter.quiesce(lambda:False) is False
        assert post(adapter)[0]==200
    assert len(observed)==1
