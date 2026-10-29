"""Actual Upstream._prep + HTTP handler; native tokenizer explicitly unavailable."""
import json
import threading
import urllib.request
import pytest
from memory_http import MemoryTransport, json_reply
from cria import denial
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream
from test_server_integration import shell


@pytest.mark.parametrize('session_header', [True, False])
def test_real_final_wire_native_unavailable_continues_without_read_credit(tmp_path, session_header):
    path=tmp_path/'f'; path.write_text(''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)))
    chats=[]; template_requests=[]
    def response(req):
        url=req.full_url
        if url.endswith('/v1/models'):return json_reply({'data':[{'id':'fixture'}]})
        if url.endswith('/props'):return json_reply({'chat_template':'fixture','default_generation_settings':{'n_ctx':49152}})
        if url.endswith('/apply-template'):
            template_requests.append(json.loads(req.data));return json_reply({'error':'fixture unavailable'},status=404)
        if url.endswith('/tokenize'):raise AssertionError('unavailable template must not tokenize')
        if url.endswith('/v1/chat/completions'):
            data=json.loads(req.data);chats.append(data)
            msg=({'role':'assistant','content':None,'tool_calls':[{'id':'original','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':str(path)})}}]}
                 if len(chats)==1 else {'role':'assistant','content':'seen'})
            return json_reply({'id':'fake','object':'chat.completion','created':1,'model':'fixture','choices':[{'index':0,'message':msg,'finish_reason':'tool_calls' if len(chats)==1 else 'stop'}]})
        raise AssertionError(url)
    transport=MemoryTransport(response)
    upstream=Upstream('http://fixture.invalid',context_window=49152,capture_rendered=False,engagement_level=2,open_request=transport)
    cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False);srv=CriaServer(cfg,log,upstream);t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions';tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        headers={'Content-Type':'application/json'}
        if session_header: headers['X-Cria-Session-Id']='sid'
        req=urllib.request.Request(url,data=json.dumps({'model':'fixture','tools':tools,'messages':messages}).encode(),headers=headers)
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        carriers=[]
        while True:
            msg=post()['choices'][0]['message']; calls=msg.get('tool_calls') or []
            if not calls:break
            messages.append(msg)
            for c in calls:
                raw=shell(json.loads(c['function']['arguments'])['cmd']);carriers.append(raw)
                messages.append({'role':'tool','tool_call_id':c['id'],'content':raw})
        assert msg['content']=='seen' and template_requests and len(chats)==2
        result=next(m for m in chats[-1]['messages'] if m.get('role')=='tool')
        assert all(raw in result['content'] for raw in carriers)
        assert 'could not be established' in result['content']
        assert '_multipart_unverified' not in json.dumps(chats[-1])
        assert 'cria_protected_reads' not in json.dumps(chats[-1])
    finally:srv.shutdown();srv.server_close();t.join();log.close();transport.assert_closed()
