"""Real handler HTTP parsing, routing, translation, actual upstream POST/terminal."""
import copy,json,urllib.request
import pytest
from cria import config,events,upstream,server
from cria.imageworkflow import ImageWorkflow
from cria.imagestore import ImageStore
from memory_http import memory_server,handler_open,MemoryTransport,json_reply,stream_reply
from test_workflow_store import IMAGE,TASK,completion
from types import SimpleNamespace

@pytest.mark.parametrize('failure',['none','unknown','invalid_observation'])
@pytest.mark.parametrize('loop',[False,True])
@pytest.mark.parametrize('reinspect',[False,True])
@pytest.mark.parametrize('responses',[False,True])
@pytest.mark.parametrize('stream',[False,True])
def test_real_http_image_observation_then_coder_projection(tmp_path,responses,stream,reinspect,loop,failure,monkeypatch,configured=False):
 posts=[]
 def respond(req):
  if req.full_url.endswith('/v1/models'):return json_reply({'data':[{'id':'fixture'}]})
  if req.full_url.endswith('/props'):return json_reply({'default_generation_settings':{'n_ctx':16384}})
  assert req.full_url.endswith('/v1/chat/completions'),req.full_url
  body=json.loads(req.data);posts.append(body)
  answer=completion() if len(posts)==1 or (reinspect and len(posts)==3) else {'id':'answer','object':'chat.completion','created':1,'model':'fixture','choices':[{'index':0,'message':{'role':'assistant','content':'The buttons are Save and Cancel.'},'finish_reason':'stop'}]}
  if failure=='invalid_observation' and len(posts)==1:answer=completion(viewed=False)
  if reinspect and len(posts)==2:
   import re
   ref=re.search(r'img_[a-f0-9]+',json.dumps(body))
   assert ref,body
   answer={'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'view-again','type':'function','function':{'name':'reinspect_image','arguments':json.dumps({'ref':ref.group()})}}]}}]}
  if loop and len(posts)==(4 if reinspect else 2):
   answer['choices'][0]['message']['tool_calls']=[{'id':'external-read','type':'function','function':{'name':'exec_command','arguments':json.dumps({'cmd':'printf Save'})}}]
   answer['choices'][0]['finish_reason']='tool_calls'
  if body.get('stream'):
   return stream_reply([('data: '+json.dumps({'id':'answer','model':'fixture','choices':[{'index':0,'delta':answer['choices'][0]['message'],'finish_reason':'stop'}]})+'\n\n').encode(),b'data: [DONE]\n\n'])
  return json_reply(answer)
 transport=MemoryTransport(respond)
 up=upstream.Upstream('http://fixture.invalid',context_window=16384,capture_rendered=False,open_request=transport)
 role=config.Role(name='coder',backend='fixture',max_tokens=8192,**({'vision':None if failure=='unknown' else True,'vision_model':'fixture'} if configured else {}))
 cfg=config.Config(server=config.ServerConfig(heartbeat_seconds=0),logging=config.LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=config.IndicatorsConfig(enabled=False),routing=config.RoutingConfig(engagement_level=4 if loop else 1,backends={'fixture':config.Backend(name='fixture')},roles={'coder':role},failover={'coding':('coder',)}))
 log=events.EventLog(dir=str(tmp_path/'logs'),console=False)
 if configured:
  from cria import privatepaths
  monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path/'private-root')
 srv=memory_server(cfg,log,up)
 # Source-owned classification fixture; routing/Role.apply/HTTP/wire are real.
 monkeypatch.setattr(server.CriaHandler,'_classify',lambda *a,**k:SimpleNamespace(task_type='coding',engagement='task',cached=False))
 if not configured:srv.image_workflow=ImageWorkflow(ImageStore(tmp_path/'private',close_authority=object()),upstream,lambda p,r:('fixture',failure!='unknown') if p is up and r is role else (None,None))
 if responses:
  body={'model':'fixture','stream':stream,'input':[{'role':'user','content':[{'type':'input_text','text':TASK},{'type':'input_image','image_url':IMAGE['image_url']['url'],'detail':'high'}]}]}
 else:body={'model':'fixture','stream':stream,'messages':[{'role':'user','content':[{'type':'text','text':TASK},copy.deepcopy(IMAGE)]}]}
 if loop:
  body['tools']=[{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
 retention_root=tmp_path/('private-root/images' if configured else 'private')
 if configured and failure=='unknown':body.update({'vision':True,'vision_model':'fixture'})
 original=copy.deepcopy(body)
 req=urllib.request.Request('http://handler.invalid/v1/'+('responses' if responses else 'chat/completions'),data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'image-http'})
 try:
  try:
   with handler_open(server.CriaHandler,srv,req) as response:output=response.read()
  except __import__('urllib.error',fromlist=['HTTPError']).HTTPError as error:
   output=error.read()
   if failure=='none':raise
  if failure!='none':
   assert b'error' in output or b'response.failed' in output,output
   assert len(posts)==(0 if failure=='unknown' else 1)
   assert list(retention_root.glob('image-session-*'))
   from cria.imageworkflow import current
   assert current.get() is None
   return
  assert b'Save' in output,output
  assert len(posts)==(4 if reinspect else 2),posts
  assert 'data:image' in json.dumps(posts[0])
  assert 'data:image' not in json.dumps(posts[1])
  assert 'Save\\nCancel' in json.dumps(posts[1])
  if reinspect:
   assert 'data:image' in json.dumps(posts[2])
   assert 'data:image' not in json.dumps(posts[3])
   assert any(m.get('tool_call_id')=='view-again' for m in posts[3]['messages'])
  assert body==original
  store=srv.image_workflow._workflow.store if configured else srv.image_workflow.store
  resources=[session for session in store._all if session._records]
  assert resources and all(session.pending_observations==0 for session in resources)
  # No lifecycle cleanup: resources remain retained after the handler returns.
  assert list(retention_root.glob('image-session-*'))
 finally:log.close()
