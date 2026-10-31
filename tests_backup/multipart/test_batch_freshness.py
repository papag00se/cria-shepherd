import json
from cria import wsview, writeproxy
from test_lifecycle import start
from test_server_integration import shell


def test_mixed_batch_preserves_read_but_withholds_current_authority(tmp_path):
    bridge,messages,text=start(tmp_path)
    peer={'id':'native','type':'function','function':{'name':'exec_command','arguments':json.dumps({'cmd':'printf native > other'})}}
    messages[0]['tool_calls'].append(peer)
    messages.append({'role':'tool','tool_call_id':'native','content':'native'})
    while True:
        projected,calls,_=bridge.incoming('s',messages)
        if not calls: break
        c=calls[0]; messages.append({'role':'assistant','tool_calls':[c]})
        messages.append({'role':'tool','tool_call_id':c['id'],'content':shell(json.loads(c['function']['arguments'])['cmd'])})
    view=wsview.View(str(tmp_path),'sid:batch')
    wsview.bind(view)
    rendered=writeproxy.represent_inbound(projected,workspace_root=str(tmp_path))
    read=[m for m in rendered if m.get('role')=='tool' and m.get('tool_call_id')=='original'][0]
    assert read['content']==text
    assert view.read_observed(str(tmp_path/'f'))==text
    assert view.read(str(tmp_path/'f')) is None
    assert any(m.get('tool_call_id')=='native' and m['content']=='native' for m in rendered)
