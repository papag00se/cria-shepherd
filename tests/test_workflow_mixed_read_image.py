"""One real HTTP request: assembled protected read + observation + fit/settlement."""
import contextlib,copy,io,json,random,urllib.request
from dataclasses import replace
from types import SimpleNamespace
import pytest
from cria import config,events,upstream,server,privatepaths,writeproxy,filecommands,multipartcontext,bodykeys
from cria.multipart_bridge import Bridge
from memory_http import memory_server,handler_open,MemoryTransport,json_reply,stream_reply
from test_workflow_store import IMAGE,TASK,completion


def harness_page(call):
    # Execute ONLY the exact producer-owned Python read program in this fixture,
    # on the external harness side. No runtime executor is added to the server.
    cmd=json.loads(call['function']['arguments'])['cmd']
    source=cmd.split("<<'__CRIA_MULTIPART_PAGE__'\n",1)[1].rsplit('\n__CRIA_MULTIPART_PAGE__',1)[0]
    raw=io.BytesIO();out=io.TextIOWrapper(raw,encoding='utf-8')
    with contextlib.redirect_stdout(out):exec(compile(source,'harness-owned-multipart-read','exec'),{'__name__':'__main__'})
    out.flush();data=raw.getvalue().decode();out.detach()
    return data

@pytest.mark.parametrize('mode',['fit','unknown','overflow'])
@pytest.mark.parametrize('responses',[False,True])
@pytest.mark.parametrize('stream',[False,True])
def test_mixed_image_and_assembled_read_actual_http(tmp_path,monkeypatch,mode,responses,stream):
    monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path/'private')
    rng=random.Random(32)
    text='literal \x1b[31mred\x1b[0m\x00 CRLF\r\n'+''.join('%08x\n'%rng.getrandbits(32) for _ in range(3000))
    path=tmp_path/'input';path.write_text(text)
    bridge=Bridge(str(tmp_path/'registry'));sid='sid:mixed-image-read'
    shell={'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}}
    original={'id':'protected-original','type':'function','function':{'name':'read_file','arguments':json.dumps({'path':str(path)})}}
    issued={'choices':[{'message':{'role':'assistant','tool_calls':[original]}}]}
    with multipartcontext.bound():
        writeproxy.translate_outbound(issued,shell,injected={'read_file'},workspace_root=str(tmp_path),
            multipart_command=lambda original,effect,receipt:bridge.register(sid,original,effect,shell,receipt))
        bridge.bind(sid,issued)
    root={'role':'user','content':[{'type':'text','text':TASK},copy.deepcopy(IMAGE)]}
    history=[root,issued['choices'][0]['message']];carriers=[]
    while True:
        c=history[-1]['tool_calls'][0];raw=harness_page(c);carriers.append(raw)
        history.append({'role':'tool','tool_call_id':c['id'],'content':raw})
        page=json.loads(raw)
        if page['offset']+page['length']==page['stream_length']:break
        _projected,calls,facts=bridge.incoming(sid,history)
        assert calls and not facts
        history.append({'role':'assistant','content':None,'tool_calls':calls})
    assert len(carriers)>1
    posts=[];renders=[];tokenized=[];observations=[];read_events=[];compactions=[];bind_checks=[];prep_checks=[]
    bind=server.CriaHandler._bind_multipart_read_facts
    def bound(handler,body,rlog):
        ok=bind(handler,body,rlog)
        reads=body.get(bodykeys.PROTECTED_READS)
        bind_checks.append({'ok':ok,'facts':[type(f).__name__ for f in getattr(handler,'_multipart_facts',())],'bound':len(reads or ()),'session':getattr(handler,'_multipart_session',None)})
        if reads:
            assert reads[0].model_content==text and reads[0].exact_body==text.encode()
            wrapped=[]
            for read in reads:
                observe=read.observe
                def seen(accepted,observe=observe):
                    read_events.append((len(posts),accepted));observe(accepted)
                wrapped.append(replace(read,observe=seen))
            body[bodykeys.PROTECTED_READS]=tuple(wrapped)
            if mode=='overflow':
                def compact(body,reads):compactions.append(True);return body
                body[bodykeys.READ_FIT_CALLBACKS]=upstream.ReadFitCallbacks(compact)
        return ok
    monkeypatch.setattr(server.CriaHandler,'_bind_multipart_read_facts',bound)
    def respond(req):
        url=req.full_url
        if url.endswith('/v1/models'):return json_reply({'data':[{'id':'fixture'}]})
        if url.endswith('/props'):return json_reply({'chat_template':'offline-native-fixture','default_generation_settings':{'n_ctx':49152}})
        if url.endswith('/apply-template'):
            wire=json.loads(req.data);renders.append(wire)
            assert 'data:image' not in json.dumps(wire),'Image step must not use text-native measurement'
            if mode=='unknown':return json_reply({'error':'fixture native unavailable'},status=404)
            return json_reply({'prompt':json.dumps(wire)})
        if url.endswith('/tokenize'):
            tokenized.append(json.loads(req.data)['content'])
            return json_reply({'tokens':[1]*(60000 if mode=='overflow' else 100)})
        assert url=='http://fixture.invalid/v1/chat/completions'
        wire=json.loads(req.data);posts.append(wire)
        has_image='data:image' in json.dumps(wire)
        if has_image:
            observations.append(wire)
            assert not any(m.get('role')=='tool' for m in wire['messages'])
            assert True not in [a for _,a in read_events]
            return json_reply(completion())
        answer={'id':'actual','model':'fixture','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'mixed-delivered'}}]}
        if wire.get('stream'):
            return stream_reply([('data: '+json.dumps({'choices':[{'index':0,'delta':{'content':'mixed-delivered'},'finish_reason':'stop'}]})+'\n\n').encode(),b'data: [DONE]\n\n'])
        return json_reply(answer)
    transport=MemoryTransport(respond)
    up=upstream.Upstream('http://fixture.invalid',context_window=49152,capture_rendered=False,engagement_level=2,open_request=transport)
    original_prep=up._prep
    def prep(body,*a,**k):
        prep_checks.append({'keys':[str(key) for key in body], 'reads':len(body.get(bodykeys.PROTECTED_READS) or ())})
        return original_prep(body,*a,**k)
    monkeypatch.setattr(up,'_prep',prep)
    role=config.Role(name='coder',backend='fixture',max_tokens=8192,vision=True,vision_model='fixture')
    cfg=config.Config(server=config.ServerConfig(heartbeat_seconds=0),logging=config.LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=config.IndicatorsConfig(enabled=False),routing=config.RoutingConfig(engagement_level=2,roles={'coder':role},backends={'fixture':config.Backend(name='fixture')},failover={'coding':('coder',)}))
    log=events.EventLog(dir=str(tmp_path/'logs'),console=False);srv=memory_server(cfg,log,up);srv.multipart_bridge=bridge
    monkeypatch.setattr(server.CriaHandler,'_classify',lambda *a,**k:SimpleNamespace(task_type='coding',cached=False))
    tools=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
    if responses:
        items=[]
        for m in history:
            if m['role']=='user':items.append({'role':'user','content':[{'type':'input_text','text':TASK},{'type':'input_image','image_url':IMAGE['image_url']['url'],'detail':'high'}]})
            elif m['role']=='assistant':items.extend({'type':'function_call','call_id':c['id'],'name':c['function']['name'],'arguments':c['function']['arguments']} for c in m['tool_calls'])
            else:items.append({'type':'function_call_output','call_id':m['tool_call_id'],'output':m['content']})
        body={'model':'fixture','stream':stream,'prompt_cache_key':'mixed-image-read','input':items,'tools':[{'type':'function',**t['function']} for t in tools]}
    else:body={'model':'fixture','stream':stream,'messages':copy.deepcopy(history),'tools':tools}
    incoming=copy.deepcopy(body)
    req=urllib.request.Request('http://handler.invalid/v1/'+('responses' if responses else 'chat/completions'),data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'mixed-image-read'})
    try:
        with handler_open(server.CriaHandler,srv,req) as response:output=response.read()
        (tmp_path/'debug-mixed.json').write_text(json.dumps({'bind':bind_checks,'prep':prep_checks,'events':read_events}))
        assert b'mixed-delivered' in output,output
        assert len(posts)==2 and len(observations)==1 and renders
        assert bind_checks[0]['bound']==1
        assert body==incoming
        final=posts[-1];assert 'data:image' not in json.dumps(final)
        result=next(m for m in final['messages'] if m.get('role')=='tool')
        bridge.incoming(sid,history) # Reload persisted authoritative state.
        entry=bridge.sessions[sid]['protected-original']
        if mode=='fit':
            assert result['content']==text and tokenized
            assert entry.settled and entry.fallback_kind is None
            assert read_events[-1]==(2,True)
        else:
            assert all(raw in result['content'] for raw in carriers)
            assert not entry.settled and entry.fallback_kind==mode
            assert True not in [accepted for _,accepted in read_events]
            assert 'could not be established' in result['content'] if mode=='unknown' else 'fit' in result['content']
            if mode=='overflow':assert compactions==[True] and len(tokenized)>=2
        assert 'cria_protected_reads' not in json.dumps(final) and '_multipart_unverified' not in json.dumps(final)
        (tmp_path/'mixed-http-capture.json').write_text(json.dumps({'kind':'offline-mixed-protected-read-image','mode':mode,'wire':posts,'native_requests':renders,'read_events':read_events,'response':output.decode()},indent=2))
    finally:log.close();transport.assert_closed()
