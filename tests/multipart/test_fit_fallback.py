import json
import threading
import urllib.request
import pytest
from cria import bodykeys, denial
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import ReadFitUnknown, ReadFitOverflow, MeasuredReadOverflow
from test_server_integration import Backend, shell


@pytest.mark.parametrize('stream',[False,True])
@pytest.mark.parametrize('reason',['unknown','overflow'])
def test_fit_failure_continues_once_without_claiming_read_or_guessing_guidance(stream,reason,tmp_path):
    path=tmp_path/'f'; text=''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)); path.write_text(text)
    class FitBackend(Backend):
        def chat(self,body,rlog=None):
            reads=body.get(bodykeys.PROTECTED_READS)
            if reads:
                self.bodies.append(body)
                if reason=='unknown': raise ReadFitUnknown('test_unknown',reads)
                # This is a fixture, not evidence of a real tokenizer/window.
                raise ReadFitOverflow(MeasuredReadOverflow(100,99,5,reads,b'fixture'))
            if len(self.bodies)==2:
                self.bodies.append(body)
                return json.dumps({'id':'fake','object':'chat.completion','created':1,'model':'test-model','choices':[{'index':0,'message':{'role':'assistant','content':'seen'},'finish_reason':'stop'}]})
            return super().chat(body,rlog)
    backend=FitBackend(str(path)); cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); srv=CriaServer(cfg,log,backend); t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'; tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages,'stream':stream}).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r: raw=r.read()
        if not stream:return json.loads(raw)['choices'][0]['message']
        events=[json.loads(x[6:]) for x in raw.decode().splitlines() if x.startswith('data: ') and x!='data: [DONE]'];calls={};content=''
        for event in events:
            for choice in event.get('choices') or []:
                delta=choice.get('delta') or {};content+=delta.get('content') or ''
                for part in delta.get('tool_calls') or []:
                    c=calls.setdefault(part['index'],{'id':'','type':'function','function':{'name':'','arguments':''}})
                    if part.get('id'):c['id']=part['id']
                    for field in ('name','arguments'):c['function'][field]+=(part.get('function') or {}).get(field) or ''
        return {'role':'assistant','content':content,'tool_calls':list(calls.values())}
    try:
        carriers=[]
        while True:
            msg=post(); calls=msg.get('tool_calls') or []
            if not calls: break
            messages.append(msg)
            for c in calls:
                output=shell(json.loads(c['function']['arguments'])['cmd']);carriers.append(output)
                messages.append({'role':'tool','tool_call_id':c['id'],'content':output})
        assert msg['content']=='seen' and len(backend.bodies)==3
        result=next(m for m in backend.bodies[-1]['messages'] if m.get('role')=='tool')
        assert all(output in result['content'] for output in carriers)
        assert denial.read_payload(result) is None and not denial.refused(result)
        assert text not in result['content']
        assert ('could not be established' if reason=='unknown' else 'did not fit after a compaction attempt') in result['content']
        assert 'range' not in result['content'] and 'bytes' not in result['content']
    finally: srv.shutdown();srv.server_close();t.join();log.close()
