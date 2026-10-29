import json
from types import SimpleNamespace
from cria import outputpolicies, writeproxy, toolwire, multipartcontext


def test_alias_registration_comes_from_private_normalizer_not_arbitrary_shell(tmp_path):
    with multipartcontext.bound():
        _check_alias(tmp_path)


def _check_alias(tmp_path):
    shell={'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}}
    tools=[{'type':'function','function':{'name':'exec_command','parameters':shell['schema']}}]
    def completion(call): return {'choices':[{'message':{'tool_calls':[call]}}]}
    call={'id':'x','type':'function','function':{'name':'cat_file','arguments':json.dumps({'file_path':'f','start':'2'})}}
    c=completion(call); rlog=SimpleNamespace(emit=lambda *a,**k:None)
    outputpolicies.normalize_tool_calls(c,tools,rlog)
    registered=[]
    writeproxy.translate_outbound(c,shell,rlog,injected=set(),workspace_root=str(tmp_path),
        multipart_command=lambda tc,effect,receipt: registered.append((tc,effect,receipt)) or 'printf PAGE')
    tc,effect,receipt=registered[0]
    assert tc['function']['name']=='read_file' and json.loads(tc['function']['arguments'])=={'path':'f','start_line':2}
    lowered=c['choices'][0]['message']['tool_calls'][0]
    declaration=toolwire._declaration(json.loads(lowered['function']['arguments'])['cmd'],'x')
    assert declaration['rcpt']==receipt and declaration['name']=='read_file'
    # A caller-authored shell string that quotes the same sentinel has no private intent.
    spoof=completion({'id':'other','type':'function','function':lowered['function'].copy()})
    registered.clear()
    writeproxy.translate_outbound(spoof,shell,rlog,injected=set(),workspace_root=str(tmp_path),
        multipart_command=lambda *a: registered.append(a) or 'printf PAGE')
    assert registered==[]
