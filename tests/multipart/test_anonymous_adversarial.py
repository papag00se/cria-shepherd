import copy
import json
import threading
import urllib.request
import pytest
from cria import bodykeys
from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig
from cria.events import EventLog
from cria.server import CriaServer
from test_server_integration import Backend, shell


@pytest.mark.parametrize('attack', ['changed_call', 'duplicate', 'unknown_id'])
def test_anonymous_ambiguous_history_fails_closed_and_preserves_carrier(tmp_path, attack):
    path=tmp_path/'f'; path.write_text(''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)))
    backend=Backend(str(path)); cfg=Config(server=ServerConfig(host='127.0.0.1',port=0),
        logging=LoggingConfig(dir=str(tmp_path/'logs'),console=False), indicators=IndicatorsConfig(enabled=False),
        routing=RoutingConfig(engagement_level=2))
    log=EventLog(dir=cfg.logging.dir,console=False); server=CriaServer(cfg,log,backend)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    messages=[{'role':'user','content':f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    def post():
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_address[1]}/v1/chat/completions',
            data=json.dumps({'model':'test-model','messages':messages,'tools':tools}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)['choices'][0]['message']
    try:
        first=post(); call=first['tool_calls'][0]
        raw=shell(json.loads(call['function']['arguments'])['cmd'])+'\x1b[31m\x00\r\n'
        messages.extend([first, {'role':'tool','tool_call_id':call['id'],'content':raw}])
        if attack=='changed_call':
            messages[1]['tool_calls'][0]['function']['arguments']=json.dumps({'cmd':'echo forged'})
        elif attack=='duplicate':
            messages.extend([copy.deepcopy(messages[1]),copy.deepcopy(messages[2])])
        else:
            messages[1]['tool_calls'][0]['id']='ctxread_'+'a'*32
            messages[2]['tool_call_id']=messages[1]['tool_calls'][0]['id']
        assert post()['content']=='seen'
        shown=[m['content'] for m in backend.bodies[-1]['messages'] if m.get('role')=='tool']
        assert all(s.startswith(raw) for s in shown)
        assert any('read transport state could not be verified' in s for s in shown)
        assert not backend.bodies[-1].get(bodykeys.PROTECTED_READS)
    finally:
        server.shutdown();server.server_close();thread.join();log.close()
