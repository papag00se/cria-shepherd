import json
import threading
import urllib.request
import pytest
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from test_server_integration import Backend, shell


@pytest.mark.parametrize('header', [True, False])
def test_real_handler_preserves_two_read_batch_with_unequal_page_counts(tmp_path, header):
    a=tmp_path/'a'; a.write_text('short\n')
    b=tmp_path/'b'; text=''.join('%08x\n' % ((i*2654435761) % 2**32) for i in range(6000)); b.write_text(text)
    class Batch(Backend):
        def chat(self, body,rlog=None):
            self.bodies.append(body)
            if len(self.bodies)==1:
                msg={'role':'assistant','content':None,'tool_calls':[{'id':str(i),'type':'function','function':{'name':'read_file','arguments':json.dumps({'path':str(p)})}} for i,p in enumerate((a,b))]}
                fin='tool_calls'
            else: msg={'role':'assistant','content':'seen'};fin='stop'
            return json.dumps({'id':'fake','object':'chat.completion','created':1,'model':'test-model','choices':[{'index':0,'message':msg,'finish_reason':fin}]})
    backend=Batch(str(a)); cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); srv=CriaServer(cfg,log,backend); t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read both'}]
    def post():
        headers={'Content-Type':'application/json'}
        if header: headers['X-Cria-Session-Id']='sid'
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages}).encode(),headers=headers)
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        while True:
            msg=post()['choices'][0]['message']; calls=msg.get('tool_calls') or []
            if not calls: break
            messages.append(msg)
            for c in calls: messages.append({'role':'tool','tool_call_id':c['id'],'content':shell(json.loads(c['function']['arguments'])['cmd'])})
        results={m['tool_call_id']:m['content'] for m in backend.bodies[-1]['messages'] if m.get('role')=='tool'}
        assert sorted(results.values(), key=len)==['short\n',text] and len(backend.bodies)==2
        if header: assert set(results)=={'0','1'}
    finally: srv.shutdown();srv.server_close();t.join();log.close()
