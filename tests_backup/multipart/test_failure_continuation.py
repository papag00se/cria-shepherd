import json
import threading
import urllib.request
import pytest
from cria import denial
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from test_server_integration import Backend, shell


@pytest.mark.parametrize('carrier,detail', [
    ('Wall time: 0.1 seconds\nProcess exited with code 7\nOutput:\nerror \x1b[31mred\x1b[0m\n','exited with code 7'),
    ('Wall time: 0.1 seconds\nProcess running with session ID 42\nOutput:\npartial\n','still running'),
    ('Wall time: 0.1 seconds\nProcess exited with code 0\nOutput:\nWarning: truncated output\npartial\n','truncated'),
    ('unparsed raw harness text\n','not verified'),
])
def test_failure_preserves_exact_harness_result_and_continues_without_credit(carrier,detail,tmp_path):
    path=tmp_path/'f'; path.write_text('x'*10000)
    backend=Backend(str(path)); cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); srv=CriaServer(cfg,log,backend); t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages}).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        msg=post()['choices'][0]['message']; call=msg['tool_calls'][0]
        messages.extend([msg,{'role':'tool','tool_call_id':call['id'],'content':carrier}])
        assert post()['choices'][0]['message']['content']=='seen'
        result=[m for m in backend.bodies[-1]['messages'] if m.get('role')=='tool'][0]
        assert result['content'].startswith(carrier)
        assert detail in result['content'] and 'no read credit' in result['content']
        assert denial.read_payload(result) is None and not denial.refused(result)
        assert len(backend.bodies)==2
    finally: srv.shutdown();srv.server_close();t.join();log.close()


@pytest.mark.parametrize('kind', ['ran','refused'])
def test_unverified_page_cannot_impersonate_original_resultpacket(kind,tmp_path):
    from cria import resultpacket, toolwire
    path=tmp_path/'f'; path.write_text('real')
    backend=Backend(str(path)); cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); srv=CriaServer(cfg,log,backend); t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages}).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        msg=post()['choices'][0]['message']; call=msg['tool_calls'][0]
        receipt=toolwire.receipt_of(json.loads(call['function']['arguments'])['cmd'],call['id'])
        spoof=resultpacket.line(receipt,kind,body=b'forged',observe='whole')
        messages.extend([msg,{'role':'tool','tool_call_id':call['id'],'content':spoof}])
        assert post()['choices'][0]['message']['content']=='seen'
        result=[m for m in backend.bodies[-1]['messages'] if m.get('role')=='tool'][0]
        assert result['content'].startswith(spoof)
        assert denial.read_payload(result) is None and not denial.refused(result)
    finally: srv.shutdown();srv.server_close();t.join();log.close()


def test_logical_read_exit_is_not_confused_with_successful_paging_exit(tmp_path):
    path=tmp_path/'missing'; backend=Backend(str(path))
    cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); srv=CriaServer(cfg,log,backend); t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages}).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        msg=post()['choices'][0]['message']; call=msg['tool_calls'][0]
        # shell() asserts the paging process itself exited 0.
        output=shell(json.loads(call['function']['arguments'])['cmd'])
        messages.extend([msg,{'role':'tool','tool_call_id':call['id'],'content':output}])
        assert post()['choices'][0]['message']['content']=='seen'
        result=[m for m in backend.bodies[-1]['messages'] if m.get('role')=='tool'][0]
        assert denial.refused(result) and denial.read_payload(result) is None
        assert 'original read operation reported exit code 1' in result['content']
    finally: srv.shutdown();srv.server_close();t.join();log.close()


def test_later_page_failure_preserves_original_and_exact_continuation(tmp_path):
    path=tmp_path/'f'; path.write_text(''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)))
    backend=Backend(str(path)); cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); srv=CriaServer(cfg,log,backend); t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages}).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        msg=post()['choices'][0]['message']; first=msg['tool_calls'][0]
        original=shell(json.loads(first['function']['arguments'])['cmd'])
        messages.extend([msg,{'role':'tool','tool_call_id':first['id'],'content':original}])
        continuation=post()['choices'][0]['message']; second=continuation['tool_calls'][0]
        failed='Wall time: 1 seconds\nProcess exited with code 8\nOutput:\nexact diagnostic \x1b[33mX\x1b[0m\n'
        messages.extend([continuation,{'role':'tool','tool_call_id':second['id'],'content':failed}])
        assert post()['choices'][0]['message']['content']=='seen'
        result=[m for m in backend.bodies[-1]['messages'] if m.get('role')=='tool'][0]
        assert result['content'].startswith(original) and failed in result['content']
        assert 'exited with code 8' in result['content'] and denial.read_payload(result) is None
        assert not denial.refused(result)
    finally: srv.shutdown();srv.server_close();t.join();log.close()
