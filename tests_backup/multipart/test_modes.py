import json
import threading
import urllib.request
import pytest
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from test_server_integration import Backend, shell


@pytest.mark.parametrize('api,stream', [('chat',True),('responses',False),('responses',True)])
def test_real_handler_modes_carry_private_pages(api,stream,tmp_path):
    path=tmp_path/'data'; text=''.join('%08x\n' % ((i*2654435761) % 2**32) for i in range(5000)); path.write_text(text)
    backend=Backend(str(path))
    cfg=Config(server=ServerConfig(host='127.0.0.1',port=0), logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),
        indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); server=CriaServer(cfg,log,backend)
    t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    url=f'http://127.0.0.1:{server.server_address[1]}/v1/'+('chat/completions' if api=='chat' else 'responses')
    tool={'type':'function','name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}
    user=f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'
    messages=[{'role':'user','content':user}]
    items=[{'type':'message','role':'user','content':[{'type':'input_text','text':user}]}]
    def post():
        body=({'model':'test-model','tools':[{'type':'function','function':{k:v for k,v in tool.items() if k!='type'}}],
               'messages':messages,'stream':stream} if api=='chat' else
              {'model':'test-model','tools':[tool],'input':items,'prompt_cache_key':'sid','stream':stream})
        req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r: raw=r.read()
        if not stream: return json.loads(raw)
        events=[json.loads(line[6:]) for line in raw.decode().splitlines() if line.startswith('data: ') and line!='data: [DONE]']
        if api=='responses':
            return next(e['response'] for e in events if e.get('type')=='response.completed')
        calls={}; content=''
        for event in events:
            for choice in event.get('choices') or []:
                d=choice.get('delta') or {}; content+=d.get('content') or ''
                for part in d.get('tool_calls') or []:
                    c=calls.setdefault(part['index'],{'id':'','type':'function','function':{'name':'','arguments':''}})
                    if part.get('id'): c['id']=part['id']
                    for field in ('name','arguments'): c['function'][field]+=(part.get('function') or {}).get(field) or ''
        return {'choices':[{'message':{'role':'assistant','content':content,'tool_calls':list(calls.values())}}]}
    try:
        count=0
        while True:
            result=post()
            if api=='chat':
                msg=result['choices'][0]['message']; calls=msg.get('tool_calls') or []
                if not calls:
                    assert msg['content']=='seen'; break
                messages.append(msg)
            else:
                calls=[{'id':c['call_id'],'type':'function','function':{'name':c['name'],'arguments':c['arguments']}}
                       for c in result.get('output',[]) if c.get('type')=='function_call']
                if not calls:
                    assert 'seen' in json.dumps(result); break
                items.extend({'type':'function_call','call_id':c['id'],'name':c['function']['name'],
                              'arguments':c['function']['arguments']} for c in calls)
            for call in calls:
                output=shell(json.loads(call['function']['arguments'])['cmd']); count+=1
                if api=='chat': messages.append({'role':'tool','tool_call_id':call['id'],'content':output})
                else: items.append({'type':'function_call_output','call_id':call['id'],'output':output})
        assert count>=2 and len(backend.bodies)==2
        seen=[m for m in backend.bodies[-1]['messages'] if m.get('role')=='tool']
        assert len(seen)==1 and seen[0]['content']==text
    finally:
        server.shutdown();server.server_close();t.join();log.close()
