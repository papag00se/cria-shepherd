import json
from types import SimpleNamespace
from cria import config,upstream,privatepaths
from cria.imageassembly import ConfiguredImages
from cria.imageworkflow import current
from cria.server import CriaHandler

def test_text_only_offered_image_tool_keeps_streaming(tmp_path,monkeypatch):
    monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path)
    role=config.Role(name='coder',backend='fixture')
    server=SimpleNamespace(cfg=SimpleNamespace(tools=SimpleNamespace(workspace_image_tool='view_image'),routing=SimpleNamespace(roles={'coder':role})))
    body={'model':'fixture','messages':[{'role':'user','content':'Say hello.'}], 'tools':[{'type':'function','function':{'name':'view_image','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}]}
    context=ConfiguredImages(server,upstream).capture('text-session',body)
    assert context is not None and not context.prepared.bindings
    calls=[]
    class Provider:
        def stream_chat(self,*args):
            calls.append('stream_chat');yield b'data: test\n\n'
        def chat(self,*args):
            calls.append('chat')
            return json.dumps({'id':'text','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'hello'}}]})
    token=current.set(context)
    try:
        list(CriaHandler._image_stream(SimpleNamespace(server=server),Provider(),body,SimpleNamespace(role='coder'),None))
    finally:current.reset(token)
    assert calls==['stream_chat'], 'text-only request buffered: '+repr(calls)
