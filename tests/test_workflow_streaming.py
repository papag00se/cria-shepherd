"""Preserve text streaming and register native image actions before emission."""
import json
from types import SimpleNamespace
import urllib.request
import pytest
from cria import config,events,server,upstream,privatepaths
from memory_http import memory_server,handler_open,MemoryTransport,json_reply,stream_reply
from receiving.fixtures import FakeSocket

TOOLS=[{'type':'function','function':{'name':'view_image','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}]

def frame(delta,finish=None):
 return ('data: '+json.dumps({'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\n').encode()

@pytest.mark.parametrize('mode',['live-text','completed-image-action','unfinished-image-action'])
def test_actual_text_http_stream_stays_live_and_tracks_only_complete_image_actions(tmp_path,monkeypatch,mode):
 monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path/'private')
 client_writes=[];published=[];old_send=FakeSocket.sendall
 def send(sock,data):
  client_writes.append(bytes(data))
  if b'imgread_' in data and b'data:' in data:
   ledgers=list((tmp_path/'private/images').glob('image-session-*/workspace-reads.json'))
   assert ledgers,'Action emitted before private registration'
   published.extend(json.loads(p.read_text()) for p in ledgers)
  return old_send(sock,data)
 monkeypatch.setattr(FakeSocket,'sendall',send)
 posts=[];progress=[]
 def respond(req):
  if req.full_url.endswith('/v1/models'):return json_reply({'data':[{'id':'fixture'}]})
  if req.full_url.endswith('/props'):return json_reply({'default_generation_settings':{'n_ctx':8192}})
  body=json.loads(req.data);posts.append(body);assert body['stream'] is True
  if mode=='live-text':
   def interrupted(error):
    assert any(b'live-prose' in b for b in client_writes),'Text held until upstream termination'
    progress.append(True)
   return stream_reply([frame({'content':'live-prose '*80}),frame({},'stop')],interrupt_at=1,interruption=TimeoutError('fixture after live content'),before_interrupt=interrupted)
  lines=[frame({'tool_calls':[{'index':0,'id':'model-id','type':'function','function':{'name':'view_','arguments':'{"path":'}}]}),frame({'tool_calls':[{'index':0,'function':{'name':'image','arguments':'"/harness/image.png"}'}}]}),frame({},'tool_calls'),b'data: [DONE]\n\n']
  if mode=='unfinished-image-action':return stream_reply(lines,interrupt_at=2,interruption=TimeoutError('fixture before terminal'))
  return stream_reply(lines)
 up=upstream.Upstream('http://fixture.invalid',context_window=8192,capture_rendered=False,open_request=MemoryTransport(respond))
 role=config.Role(name='coder',backend='fixture')  # default UNKNOWN vision must not buffer text
 cfg=config.Config(tools=config.ToolsConfig(workspace_image_tool='view_image'),server=config.ServerConfig(heartbeat_seconds=0),logging=config.LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=config.IndicatorsConfig(enabled=False),routing=config.RoutingConfig(engagement_level=1,roles={'coder':role},backends={'fixture':config.Backend(name='fixture')},failover={'coding':('coder',)}))
 log=events.EventLog(dir=str(tmp_path/'logs'),console=False);srv=memory_server(cfg,log,up)
 monkeypatch.setattr(server.CriaHandler,'_classify',lambda *a,**k:SimpleNamespace(task_type='coding',cached=False))
 body={'model':'fixture','messages':[{'role':'user','content':'Say hello.'}],'tools':TOOLS,'stream':True}
 req=urllib.request.Request('http://handler.invalid/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'source-text'})
 try:
  with handler_open(server.CriaHandler,srv,req) as response:output=response.read()
  assert len(posts)==1 and posts[0]['stream'] is True
  if mode=='live-text':assert progress==[True] and b'live-prose' in output
  elif mode=='completed-image-action':
   assert published and b'imgread_' in output and b'view_image' in output
   assert all(r['result_digest'] is None for d in published for r in d['reads'].values())
  else:
   assert not published and b'imgread_' not in output and b'model-id' not in output
   assert not list((tmp_path/'private/images').glob('image-session-*/workspace-reads.json'))
 finally:log.close()
