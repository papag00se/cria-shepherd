import json
import threading
import urllib.request
import pytest
from cria import bodykeys, upstream
from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig
from cria.events import EventLog
from cria.multipart_bridge import Bridge, BridgeError
from cria.server import CriaServer
from test_server_integration import Backend, shell


def _server(tmp_path, backend):
    cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),
        indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); srv=CriaServer(cfg,log,backend)
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    def post(messages):
        req=urllib.request.Request(f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions',
            data=json.dumps({'model':'test-model','messages':messages,'tools':tools}).encode(),
            headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)['choices'][0]['message']
    return srv,thread,log,post


def test_unrepresentable_verified_read_returns_original_carriers_and_no_credit(tmp_path, monkeypatch):
    path=tmp_path/'f'; path.write_text(''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)))
    backend=Backend(str(path)); srv,thread,log,post=_server(tmp_path,backend)
    def reject(body, reads): raise upstream.ReadFitUnknown('fixture', reads)
    monkeypatch.setattr(upstream,'bind_protected_reads',reject)
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    carriers=[]
    try:
        while True:
            msg=post(messages);calls=msg.get('tool_calls') or []
            if not calls:break
            messages.append(msg)
            for call in calls:
                raw=shell(json.loads(call['function']['arguments'])['cmd']);carriers.append(raw)
                messages.append({'role':'tool','tool_call_id':call['id'],'content':raw})
        assert msg['content']=='seen' and not backend.bodies[-1].get(bodykeys.PROTECTED_READS)
        visible=[m['content'] for m in backend.bodies[-1]['messages'] if m.get('role')=='tool']
        assert all(any(v.startswith(raw) for v in visible) for raw in carriers)
        assert any('read transport state could not be verified' in v for v in visible)
        retry=post(messages)
        assert retry['content']=='seen' and not backend.bodies[-1].get(bodykeys.PROTECTED_READS)
        repeated=[m['content'] for m in backend.bodies[-1]['messages'] if m.get('role')=='tool']
        assert all(any(raw in v for v in repeated) for raw in carriers)
    finally:srv.shutdown();srv.server_close();thread.join();log.close()


@pytest.mark.parametrize('failure', ['register', 'register_after_save', 'bind'])
def test_partial_batch_storage_fault_preserves_peer_mutation_without_redrive(tmp_path, monkeypatch, failure):
    a=tmp_path/'a'; b=tmp_path/'b'
    a.write_text(''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(8000)))
    b.write_text(''.join('%08x\n' % (i*2246822519 % 2**32) for i in range(8000)))
    class Batch(Backend):
        def chat(self,body,rlog=None):
            self.bodies.append(body)
            calls=[{'id':'a','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':str(a)})}},
                   {'id':'native','type':'function','function':{'name':'exec_command','arguments':json.dumps({'cmd':'touch marker'})}},
                   {'id':'b','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':str(b)})}}]
            return json.dumps({'id':'fake','object':'chat.completion','created':1,'model':'test-model',
                'choices':[{'index':0,'message':{'role':'assistant','content':None,'tool_calls':calls},'finish_reason':'tool_calls'}]})
    backend=Batch(str(a)); srv,thread,log,post=_server(tmp_path,backend)
    register=Bridge.register; count=[0]
    def fail_second(self,*args,**kwargs):
        count[0]+=1
        if count[0]==2:
            if failure == 'register_after_save': register(self,*args,**kwargs)
            raise BridgeError('injected state I/O')
        return register(self,*args,**kwargs)
    def fail_bind(self,*args,**kwargs): raise BridgeError('injected state I/O')
    if failure.startswith('register'):monkeypatch.setattr(Bridge,'register',fail_second)
    else:monkeypatch.setattr(Bridge,'bind',fail_bind)
    try:
        msg=post([{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read files'}])
        calls=msg['tool_calls']; assert len(calls)==3
        native=[c for c in calls if c['id']=='native'];assert len(native)==1
        assert json.loads(native[0]['function']['arguments'])['cmd']=='touch marker'
        assert not (tmp_path/'marker').exists() and len(backend.bodies)==1
        if failure=='bind':
            assert all('No file content was returned' in shell(json.loads(c['function']['arguments'])['cmd'])
                       for c in calls if c['id']!='native')
        else:
            assert 'No file content was returned' in shell(json.loads(next(c for c in calls if c['id']=='b')['function']['arguments'])['cmd'])
    finally:srv.shutdown();srv.server_close();thread.join();log.close()
