import json
import os
import pty
import subprocess
import threading
import urllib.request
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.loop import completion_to_sse


class Backend:
    def __init__(self, path):
        self.path = path
        self.bodies = []
    def loaded_model(self, rlog=None): return 'test-model'
    def chat(self, body, rlog=None):
        self.bodies.append(body)
        if len(self.bodies) == 1:
            msg = {'role':'assistant','content':None,'tool_calls':[{'id':'original','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':self.path})}}]}
            finish = 'tool_calls'
        else:
            msg = {'role':'assistant','content':'seen'}; finish = 'stop'
        return json.dumps({'id':'fake','object':'chat.completion','created':1,'model':'test-model',
                           'choices':[{'index':0,'message':msg,'finish_reason':finish}]})
    def stream_chat(self, body, rlog=None):
        yield from completion_to_sse(json.loads(self.chat(body,rlog)))


def shell(command):
    master, slave = pty.openpty()
    p = subprocess.Popen(['bash','-c',command], stdout=slave, stderr=subprocess.PIPE)
    os.close(slave); data=bytearray()
    while True:
        try: chunk=os.read(master,65536)
        except OSError: break
        if not chunk: break
        data.extend(chunk)
    os.close(master)
    err=p.stderr.read(); assert p.wait() == 0,err
    assert len(data)<=10000
    return data.decode()


def test_real_chat_handler_read_pages_before_model(tmp_path):
    path=tmp_path/'file'; text='literal \x1b[31mANSI\x1b[0m and \x00 control\r\n' + ''.join('%08x\n' % ((i*2654435761) % 2**32) for i in range(7000)); path.write_bytes(text.encode())
    backend=Backend(str(path))
    cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),
        logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False),
        indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False)
    server=CriaServer(cfg,log,backend)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    url=f'http://127.0.0.1:{server.server_address[1]}/v1/chat/completions'
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req=urllib.request.Request(url,data=json.dumps({'model':'test-model','tools':tools,'messages':messages}).encode(),
            headers={'Content-Type':'application/json','X-Cria-Session-Id':'sid'})
        with urllib.request.urlopen(req,timeout=10) as r: return json.load(r)
    try:
        calls=0
        while True:
            response=post(); message=response['choices'][0]['message']
            if calls == 0:
                retry=post()['choices'][0]['message']
                assert retry['tool_calls']==message['tool_calls'] and len(backend.bodies)==1
            if not message.get('tool_calls'):
                assert message['content']=='seen'; break
            messages.append(message)
            for call in message['tool_calls']:
                output=shell(json.loads(call['function']['arguments'])['cmd'])
                messages.append({'role':'tool','tool_call_id':call['id'],'content':output})
                calls+=1
        assert calls >= 2 and len(backend.bodies)==2
        model_messages=backend.bodies[-1]['messages']
        results=[m for m in model_messages if m.get('role')=='tool']
        assert len(results)==1 and results[0]['content']==text
        assert all('__CRIA_MULTIPART_PAGE__' not in json.dumps(m) for m in model_messages)
        calls_visible = [c['id'] for m in model_messages if m.get('role')=='assistant' for c in m.get('tool_calls') or []]
        assert calls_visible == ['original']
        # Subsequent harness turns replay the original page history; private
        # paging records must stay projected after the first model response.
        messages.append(message)
        messages.append({'role':'user','content':'continue'})
        assert post()['choices'][0]['message']['content'] == 'seen'
        replayed = backend.bodies[-1]['messages']
        assert [m['content'] for m in replayed if m.get('role')=='tool']==[text]
        assert all('__CRIA_MULTIPART_PAGE__' not in json.dumps(m) for m in replayed)
    finally:
        server.shutdown();server.server_close();thread.join();log.close()
