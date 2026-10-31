import json
import threading
import urllib.request
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.multipart_bridge import Bridge
from test_server_integration import Backend, shell


def test_handler_restart_resumes_pending_and_never_leaks_pages(tmp_path):
    path=tmp_path/'f'; text=''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)); path.write_text(text)
    backend=Backend(str(path)); cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=IndicatorsConfig(enabled=False),routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); storage=str(tmp_path/'state')
    def boot():
        srv=CriaServer(cfg,log,backend); srv.multipart_bridge=Bridge(storage)
        t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        return srv,t,f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    srv,t,url=boot(); tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages}).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
    try:
        msg=post()['choices'][0]['message']; call=msg['tool_calls'][0]
        messages.extend([msg,{'role':'tool','tool_call_id':call['id'],'content':shell(json.loads(call['function']['arguments'])['cmd'])}])
        # This response establishes a pending continuation and is durably saved.
        nextmsg=post()['choices'][0]['message']; pending=nextmsg['tool_calls'][0]
        srv.shutdown();srv.server_close();t.join()
        srv,t,url=boot()
        # An HTTP retry after restart must receive the identical pending ID.
        assert post()['choices'][0]['message']['tool_calls'][0]==pending
        messages.extend([nextmsg,{'role':'tool','tool_call_id':pending['id'],'content':shell(json.loads(pending['function']['arguments'])['cmd'])}])
        while True:
            msg=post()['choices'][0]['message']; calls=msg.get('tool_calls') or []
            if not calls: break
            messages.append(msg)
            for call in calls: messages.append({'role':'tool','tool_call_id':call['id'],'content':shell(json.loads(call['function']['arguments'])['cmd'])})
        assert msg['content']=='seen' and len(backend.bodies)==2
        assert [m['content'] for m in backend.bodies[-1]['messages'] if m.get('role')=='tool']==[text]
    finally: srv.shutdown();srv.server_close();t.join();log.close()
