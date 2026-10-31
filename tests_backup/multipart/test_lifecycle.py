import json
from types import SimpleNamespace
import pytest
from cria import writeproxy
from cria.multipart_bridge import Bridge, BridgeError
from test_server_integration import shell


def start(tmp_path, storage_dir=None, session='s'):
    p=tmp_path/'f'; p.write_text(''.join('%08x\n' % (i*2654435761 % 2**32) for i in range(5000)))
    shell_tool={'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}}
    tc={'id':'original','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':str(p)})}}
    completion={'choices':[{'message':{'tool_calls':[tc]}}]}; bridge=Bridge(storage_dir); log=SimpleNamespace(emit=lambda *a,**k:None)
    writeproxy.translate_outbound(completion,shell_tool,log,injected={'read_file'},workspace_root=str(tmp_path),
        multipart_command=lambda original,effect,receipt:bridge.register(session,original,effect,shell_tool,receipt))
    bridge.bind(session,completion); call=completion['choices'][0]['message']['tool_calls'][0]
    messages=[{'role':'assistant','tool_calls':[call]}, {'role':'tool','tool_call_id':'original',
        'content':shell(json.loads(call['function']['arguments'])['cmd'])}]
    return bridge,messages,p.read_text()


def test_exact_retry_returns_identical_private_continuation(tmp_path):
    bridge,messages,_=start(tmp_path)
    first=bridge.incoming('s',messages)
    second=bridge.incoming('s',messages)
    assert first==second and len(first[1])==1


def test_restart_replays_validated_pages_and_repeats_same_continuation(tmp_path):
    storage=str(tmp_path/'state')
    bridge,messages,text=start(tmp_path,storage)
    _,calls,_=bridge.incoming('s',messages)
    restarted=Bridge(storage)
    assert restarted.incoming('s',messages)[1]==calls
    while calls:
        c=calls[0]; messages.append({'role':'assistant','tool_calls':[c]})
        messages.append({'role':'tool','tool_call_id':c['id'],'content':shell(json.loads(c['function']['arguments'])['cmd'])})
        restarted=Bridge(storage)
        projected,calls,facts=restarted.incoming('s',messages)
    assert facts[0].exact_body.decode()==text
    assert all(__import__('stat').S_IMODE(p.stat().st_mode)==0o600 for p in (tmp_path/'state').iterdir())


def test_corrupt_or_symlink_state_fails_closed_repeatedly(tmp_path):
    storage=str(tmp_path/'state'); bridge,messages,_=start(tmp_path,storage)
    bridge.incoming('s',messages)
    state=next((tmp_path/'state').glob('*.json'))
    state.write_text('{"truncated"')
    for _ in range(2):
        with pytest.raises(BridgeError): Bridge(storage).incoming('s',messages)
    state.unlink(); state.symlink_to(tmp_path/'foreign')
    with pytest.raises(BridgeError): Bridge(storage).incoming('s',messages)


def test_durable_continuation_status_never_infers_close_from_history(tmp_path):
    storage=str(tmp_path/'state'); bridge,messages,_=start(tmp_path,storage)
    assert bridge.continuation_state('s').pending == ('original',)
    _,calls,_=bridge.incoming('s',messages)
    assert Bridge(storage).continuation_state('s').pending == (calls[0]['id'],)
    messages.extend([{'role':'assistant','tool_calls':calls}, {'role':'tool','tool_call_id':calls[0]['id'],
        'content':'Wall time: 0.1 seconds\nProcess running with session ID 7\nOutput:\n'}])
    bridge.incoming('s',messages)
    status=Bridge(storage).continuation_state('s')
    assert status.pending==() and status.running_unknown==(calls[0]['id'],) and status.undelivered==('original',)


def test_two_bridge_instances_serialize_same_session_delivery(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    storage=str(tmp_path/'state'); _,messages,_=start(tmp_path,storage)
    a,b=Bridge(storage),Bridge(storage)
    with ThreadPoolExecutor(max_workers=2) as pool:
        x=pool.submit(a.incoming,'s',messages); y=pool.submit(b.incoming,'s',messages)
        assert x.result()==y.result()


def test_no_unfenced_expiry_api(tmp_path):
    bridge, messages, _ = start(tmp_path, str(tmp_path / 'state'))
    assert not hasattr(bridge, 'expire_abandoned')
    assert not hasattr(bridge, 'abandon_session')
    assert Bridge(str(tmp_path / 'state')).incoming('s', messages)[1]


def test_valid_json_with_tampered_pending_command_is_never_executed(tmp_path):
    storage=str(tmp_path/'state'); bridge,messages,_=start(tmp_path,storage)
    bridge.incoming('s',messages)
    state=next((tmp_path/'state').glob('*.json'))
    obj=json.loads(state.read_text()); entry=obj['entries'][0]
    entry['calls'][entry['pending']]['function']['arguments']=json.dumps({'cmd':'touch stolen'})
    state.write_text(json.dumps(obj))
    with pytest.raises(BridgeError): Bridge(storage).incoming('s',messages)


def test_failed_carrier_survives_restart_exactly_without_fabricated_credit(tmp_path):
    storage=str(tmp_path/'state'); bridge,messages,_=start(tmp_path,storage)
    failed='Wall time: 1 seconds\nProcess exited with code 7\nOutput:\nexact error \x1b[31mred\x1b[0m\n'
    messages[1]['content']=failed
    first=bridge.incoming('s',messages)
    assert first[1]==[] and first[2]==() and first[0][1]['content'].startswith(failed)
    restarted=Bridge(storage)
    again=restarted.incoming('s',messages)
    assert again[1]==[] and again[2]==() and again[0][1]['content'].startswith(failed)
    assert 'exited with code 7' in again[0][1]['content']


def test_initial_retry_never_repeats_an_unowned_mutating_batch_call(tmp_path):
    import hashlib
    bridge,messages,_=start(tmp_path)
    entry=bridge.sessions['s']['original']
    native={'id':'native','type':'function','function':{'name':'exec_command','arguments':json.dumps({'cmd':'touch changed'})}}
    completion={'choices':[{'message':{'tool_calls':[entry.calls['original'],native]}}]}
    history=[{'role':'user','content':'original prompt'}]
    fingerprint=hashlib.sha256(json.dumps(history,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).digest()
    bridge.bind('s',completion,fingerprint)
    with pytest.raises(BridgeError): bridge.incoming('s',history)


def test_changed_record_for_prior_page_fails_closed(tmp_path):
    bridge,messages,_=start(tmp_path)
    _,calls,_=bridge.incoming('s',messages)
    call=calls[0]; messages.append({'role':'assistant','tool_calls':[call]})
    messages.append({'role':'tool','tool_call_id':call['id'],'content':shell(json.loads(call['function']['arguments'])['cmd'])})
    messages[1]['content']+='extra'
    with pytest.raises(BridgeError): bridge.incoming('s',messages)


def test_history_compaction_retires_completed_projection(tmp_path):
    bridge,messages,text=start(tmp_path)
    while True:
        projected,calls,facts=bridge.incoming('s',messages)
        if not calls: break
        c=calls[0]; messages.append({'role':'assistant','tool_calls':[c]})
        messages.append({'role':'tool','tool_call_id':c['id'],'content':shell(json.loads(c['function']['arguments'])['cmd'])})
    assert len(facts)==1 and facts[0].exact_body.decode()==text
    # Same completed request may retry with identical verified facts.
    assert bridge.incoming('s',messages)==(projected,[],facts)
    later=messages+[{'role':'assistant','content':'done'},{'role':'user','content':'continue'}]
    projected,calls,facts=bridge.incoming('s',later)
    from cria import resultpacket
    receipt=bridge.sessions['s']['original'].spec.receipt
    assert not calls and not facts and resultpacket.read_record(projected[1]['content'],0,receipt).body.decode()==text
    compacted=[{'role':'user','content':'new compacted history'}]
    assert bridge.incoming('s',compacted)==(compacted,[],())
    # History omission alone is not delivery proof.
    assert 's' in bridge.sessions
    # This simulates the real successful model-wire settlement callback.
    bridge.settle_on_delivery('s', ['original'])
    assert bridge.incoming('s',compacted)==(compacted,[],())
    assert 's' in bridge.sessions  # delivery plus history omission still is not closure
