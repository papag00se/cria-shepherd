import json
import threading
import urllib.request

from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig
from cria.events import EventLog
from cria.server import CriaServer
from test_server_integration import Backend, shell


def test_identical_headerless_chats_remain_distinct_across_restart(tmp_path):
    path = tmp_path / 'f'
    text = ''.join('%08x\n' % (i * 2654435761 % 2**32) for i in range(5000)); path.write_text(text)
    class TwoReaders(Backend):
        lock = threading.Lock()
        def chat(self, body, rlog=None):
            with self.lock:
                if len(self.bodies) == 1:
                    self.bodies.clear()
                    result = super().chat(body, rlog)
                    self.bodies.insert(0, {'first': True})
                    return result
                return super().chat(body, rlog)
    backend = TwoReaders(str(path))
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0), logging=LoggingConfig(dir=str(tmp_path / 'logs'), console=False),
                 indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=2))
    log = EventLog(dir=cfg.logging.dir, console=False)
    server = thread = None
    def start():
        nonlocal server, thread
        server = CriaServer(cfg, log, backend); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def stop():
        server.shutdown(); server.server_close(); thread.join()
    tools = [{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    root = f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'
    histories = [[{'role':'user','content':root}] for _ in range(2)]
    def post(messages):
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_address[1]}/v1/chat/completions',
            data=json.dumps({'model':'test-model','messages':messages,'tools':tools}).encode(), headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as response:
            return json.load(response)['choices'][0]['message']
    def execute(messages, msg):
        messages.append(msg)
        for c in msg['tool_calls']:
            messages.append({'role':'tool','tool_call_id':c['id'], 'content':shell(json.loads(c['function']['arguments'])['cmd'])})
    start()
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = list(pool.map(post, histories))
        assert first[0]['tool_calls'][0]['id'] != first[1]['tool_calls'][0]['id']
        for history, msg in zip(histories, first): execute(history, msg)
        stop(); start()
        for history in histories:
            while True:
                msg=post(history)
                if not msg.get('tool_calls'):
                    assert msg['content']=='seen'; break
                execute(history,msg)
        shown = [next(m['content'] for m in b['messages'] if m.get('role')=='tool')
                 for b in backend.bodies if isinstance(b,dict) and b.get('messages') and any(m.get('role')=='tool' for m in b['messages'])]
        assert shown[-2:] == [text, text]
    finally:
        stop(); log.close()
