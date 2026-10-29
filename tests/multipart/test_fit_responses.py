import json
import threading
import urllib.request
import pytest
from cria import bodykeys, denial
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import ReadFitUnknown
from test_server_integration import Backend, shell


@pytest.mark.parametrize('stream',[False,True])
def test_responses_fit_unknown_returns_to_coder_preserving_carriers(stream,tmp_path):
    path=tmp_path/'f'; path.write_text(''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)))
    class FitBackend(Backend):
        def chat(self,body,rlog=None):
            reads=body.get(bodykeys.PROTECTED_READS)
            if reads:
                self.bodies.append(body);raise ReadFitUnknown('test_unknown',reads)
            if len(self.bodies)==2:
                self.bodies.append(body)
                return json.dumps({'id':'fake','object':'chat.completion','created':1,'model':'test-model','choices':[{'index':0,'message':{'role':'assistant','content':'seen'},'finish_reason':'stop'}]})
            return super().chat(body,rlog)
    backend=FitBackend(str(path));cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False);srv=CriaServer(cfg,log,backend);t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/responses';tool={'type':'function','name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}
    user=f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file';items=[{'type':'message','role':'user','content':[{'type':'input_text','text':user}]}]
    def post():
        body={'model':'test-model','tools':[tool],'input':items,'prompt_cache_key':'sid','stream':stream}
        req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as r:raw=r.read()
        if not stream:return json.loads(raw)
        events=[json.loads(x[6:]) for x in raw.decode().splitlines() if x.startswith('data: ') and x!='data: [DONE]']
        return next(e['response'] for e in events if e.get('type')=='response.completed')
    try:
        carriers=[]
        while True:
            resp=post();calls=[c for c in resp.get('output',[]) if c.get('type')=='function_call']
            if not calls:break
            items.extend({'type':'function_call','call_id':c['call_id'],'name':c['name'],'arguments':c['arguments']} for c in calls)
            for c in calls:
                out=shell(json.loads(c['arguments'])['cmd']);carriers.append(out)
                items.append({'type':'function_call_output','call_id':c['call_id'],'output':out})
        assert 'seen' in json.dumps(resp) and len(backend.bodies)==3
        result=next(m for m in backend.bodies[-1]['messages'] if m.get('role')=='tool')
        assert all(c in result['content'] for c in carriers) and denial.read_payload(result) is None
        assert 'could not be established' in result['content'] and 'range' not in result['content']
    finally:srv.shutdown();srv.server_close();t.join();log.close()
