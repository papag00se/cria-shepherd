import json
from cria import denial, resultpacket, toolwire, writeproxy


def test_verified_file_control_bytes_are_not_terminal_cleanup(tmp_path):
    body='unchanged \x1b[31mred\x1b[0m\x00 and CRLF\r\n'
    shell={'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}}
    call={'id':'read','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':'file'})}}
    completion={'choices':[{'message':{'tool_calls':[call]}}]}
    writeproxy.translate_outbound(completion,shell,injected={'read_file'},workspace_root=str(tmp_path))
    lowered=completion['choices'][0]['message']['tool_calls'][0]
    receipt=toolwire.receipt_of(json.loads(lowered['function']['arguments'])['cmd'],'read')
    packet=resultpacket.line(receipt,resultpacket.RAN,body=body.encode(),observe='whole')
    messages=[{'role':'assistant','tool_calls':[lowered]}, {'role':'tool','tool_call_id':'read','content':packet}]
    got=writeproxy.represent_inbound(messages,workspace_root=str(tmp_path))[1]
    assert got['content']==body and denial.read_payload(got)==body


def test_native_terminal_output_still_gets_existing_ansi_cleanup(tmp_path):
    call={'id':'native','type':'function','function':{'name':'exec_command','arguments':json.dumps({'cmd':'printf x'})}}
    messages=[{'role':'assistant','tool_calls':[call]}, {'role':'tool','tool_call_id':'native','content':'\x1b[31mred\x1b[0m\n'}]
    got=writeproxy.represent_inbound(messages,workspace_root=str(tmp_path))[1]
    assert got['content']=='red\n' and denial.read_payload(got) is None
