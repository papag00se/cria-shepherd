import json
import pytest
from cria import multipartcontext

@pytest.fixture(autouse=True)
def scoped_multipart():
    with multipartcontext.bound():
        yield
from types import SimpleNamespace
from cria import writeproxy, resultpacket
from cria.multipart_bridge import Bridge
from test_server_integration import shell


def test_authorized_read_instead_keeps_uncapped_fact_through_real_pages(tmp_path):
    path=tmp_path/'target'; path.write_text('original file\n')
    fact='Long exact fact 界 '+('not yet read xyz '*200)
    shell_tool={'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}}
    tc={'id':'original','type':'function','function':{'name':'write_file','arguments':json.dumps({'path':str(path),'content':'replacement'})}}
    completion={'choices':[{'message':{'tool_calls':[tc]}}]}
    bridge=Bridge(); log=SimpleNamespace(emit=lambda *a,**k:None)
    writeproxy.translate_outbound(completion,shell_tool,log,injected={'write_file'},workspace_root=str(tmp_path),
        unread_target=lambda p:fact,
        multipart_command=lambda original,effect,receipt:bridge.register('session',original,effect,shell_tool,receipt))
    bridge.bind('session',completion)
    call=completion['choices'][0]['message']['tool_calls'][0]
    assert 'python3' in json.loads(call['function']['arguments'])['cmd']
    messages=[{'role':'assistant','tool_calls':[call]}]
    pages=0
    while True:
        output=shell(json.loads(call['function']['arguments'])['cmd']); pages+=1
        messages.append({'role':'tool','tool_call_id':call['id'],'content':output})
        projected,calls,facts=bridge.incoming('session',messages)
        if not calls: break
        messages.append({'role':'assistant','tool_calls':calls}); call=calls[0]
    assert pages>=1
    record=resultpacket.read_record(projected[1]['content'],0,bridge_placeholder_receipt(tc))
    assert record and fact in record.pre and record.body==b'original file\n'
    assert len(facts)==1 and facts[0].exact_body==b'original file\n' and facts[0].read_instead
    assert path.read_text()=='original file\n'


def test_owner_authored_rejected_candidate_prefix_is_bound_without_inference(tmp_path):
    import hashlib
    from dataclasses import replace
    from cria import denial, toolstages
    from cria.multipart_bridge import ReadFact
    from cria.server import CriaHandler
    from cria.upstream import protected_reads
    path=tmp_path/'target'; path.write_text('original file\n')
    shell_tool={'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}}
    tc={'id':'original','type':'function','function':{'name':'write_file','arguments':json.dumps({'path':str(path),'content':'candidate ' * 100})}}
    completion={'choices':[{'message':{'tool_calls':[tc]}}]}
    writeproxy.translate_outbound(completion,shell_tool,injected={'write_file'},workspace_root=str(tmp_path),unread_target=lambda p:'already exists')
    call=completion['choices'][0]['message']['tool_calls'][0]
    receipt=bridge_placeholder_receipt(tc)
    pre='⟦ctx:denied⟧ write not run\n'+denial.READ_INSTEAD_MARKER+'\n'
    packet=resultpacket.line(receipt,resultpacket.REFUSED,pre=pre,body=b'original file\n',observe='whole')
    log=SimpleNamespace(emit=lambda *a,**k:None)
    with toolstages.bound(replace(toolstages.defaults(),history=())):
        represented=writeproxy.represent_inbound([{'role':'assistant','tool_calls':[call]}, {'role':'tool','tool_call_id':'original','content':packet}],rlog=log,workspace_root=str(tmp_path))
    assert 'candidate ' in represented[1]['content']
    handler=object.__new__(CriaHandler); handler._multipart_session='s'
    handler.server=SimpleNamespace(multipart_bridge=Bridge())
    data=b'original file\n'; handler._multipart_facts=(ReadFact('original',(len(data),hashlib.sha256(data).hexdigest()),data,True,pre),)
    body={'messages':represented}
    assert handler._bind_multipart_read_facts(body,log)
    read=protected_reads(body)[0]
    assert read.pre != pre and read.model_content==read.pre+data.decode()


def bridge_placeholder_receipt(tc):
    from cria.denial import receipt_for
    return receipt_for(tc['id'],tc['function']['name'],tc['function']['arguments'])
