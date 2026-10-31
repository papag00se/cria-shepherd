"""Fresh workspace image read crosses the actual HTTP harness boundary twice."""
import base64,copy,json,re,struct,urllib.request,zlib
from types import SimpleNamespace
import pytest
from cria import config,events,upstream,server
from cria.imageworkflow import ImageWorkflow
from cria.imageobserver import ObservationCallbacks
from cria.imageworkspace import ImageWorkspace,WorkspaceImageTool
from cria.imagestore import ImageStore,FreshWorkspaceRead
from memory_http import memory_server,handler_open,MemoryTransport,json_reply,stream_reply
from test_workflow_store import IMAGE,TASK,completion

PATH='/harness-only/workspace/screen.png'
FRESH={'type':'image_url','image_url':{'url':'data:image/png;base64,Q0hBTkdFRA==','detail':'high'}}
TOOL={'type':'function','function':{'name':'view_image','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False}}}

def action(name,args,id='coder-original'):
 return {'id':'actual','model':'fixture','object':'chat.completion','created':1,'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]}

@pytest.mark.parametrize('responses',[False,True])
@pytest.mark.parametrize('stream',[False,True])
@pytest.mark.parametrize('loop',[False,True])
def test_fresh_harness_workspace_reinspection(tmp_path,monkeypatch,responses,stream,loop,configured=False):
 # This fixture is the harness executor. The workflow receives only its HTTP result.
 def png(rgb):
  def chunk(kind,payload):return struct.pack('!I',len(payload))+kind+payload+struct.pack('!I',zlib.crc32(kind+payload)&0xffffffff)
  return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+bytes(rgb)))+chunk(b'IEND',b'')
 source=tmp_path/'harness-workspace'/'screen.png';source.parent.mkdir();source.write_bytes(png((255,0,0)))
 path=str(source)
 def harness_read(message):
  call=message['tool_calls'][0]
  assert call['function']['name']=='view_image'
  assert json.loads(call['function']['arguments'])=={'path':path}
  data=source.read_bytes()
  part={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(data).decode(),'detail':'high'}}
  return {'role':'tool','tool_call_id':call['id'],'content':[{'type':'text','text':'Actual harness image result'},part]},part
 old_bytes=source.read_bytes()
 IMAGE={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(old_bytes).decode(),'detail':'high'}}
 FRESH={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png((0,0,255))).decode(),'detail':'high'}}
 posts=[];observed=[];received=[];replies=[];dispatches=[];terminals=[]
 original_started=ObservationCallbacks.started;original_completed=ObservationCallbacks.completed
 def started(self,receipt):
  dispatches.append(receipt);return original_started(self,receipt)
 def completed(self,receipt,result,terminal):
  terminals.append((receipt,terminal));return original_completed(self,receipt,result,terminal)
 monkeypatch.setattr(ObservationCallbacks,'started',started)
 monkeypatch.setattr(ObservationCallbacks,'completed',completed)
 def respond(req):
  if req.full_url.endswith('/v1/models'):return json_reply({'data':[{'id':'fixture'}]})
  if req.full_url.endswith('/props'):return json_reply({'default_generation_settings':{'n_ctx':16384}})
  assert req.full_url=='http://fixture.invalid/v1/chat/completions',req.full_url
  body=json.loads(req.data);posts.append(body)
  images=[p for m in body['messages'] if isinstance(m.get('content'),list) for p in m['content'] if p.get('type')=='image_url']
  if images:
   observed.append(images)
   assert len(images)==1
   answer=completion(extracted_text='Old layout' if images[0]==IMAGE else 'Changed layout')
  elif len(posts)==1:answer=action('view_image',{'path':path})
  elif len(observed)==1:
   ref=re.search(r'Reinspection reference: (img_[a-f0-9]+)',json.dumps(body)).group(1)
   answer=action('reinspect_image',{'ref':ref},'request-fresh')
  else:
   assert 'Changed layout' in json.dumps(body)
   answer=action('exec_command',{'cmd':'printf verified-fresh'}) if loop else {'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'verified-fresh'}}]}
  replies.append(copy.deepcopy(answer))
  if body.get('stream'):
   choice=answer['choices'][0]
   return stream_reply([('data: '+json.dumps({'id':'actual','model':'fixture','choices':[{'index':0,'delta':choice['message'],'finish_reason':choice['finish_reason']}]})+'\n\n').encode(),b'data: [DONE]\n\n'])
  return json_reply(answer)
 up=upstream.Upstream('http://fixture.invalid',context_window=16384,capture_rendered=False,open_request=MemoryTransport(respond))
 role=config.Role(name='coder',backend='fixture',max_tokens=8192,**({'vision':True,'vision_model':'fixture'} if configured else {}))
 cfg=config.Config(tools=config.ToolsConfig(workspace_image_tool='view_image') if configured else config.ToolsConfig(),server=config.ServerConfig(heartbeat_seconds=0),logging=config.LoggingConfig(dir=str(tmp_path/'logs'),console=False),indicators=config.IndicatorsConfig(enabled=False),routing=config.RoutingConfig(engagement_level=4 if loop else 1,backends={'fixture':config.Backend(name='fixture')},roles={'coder':role},failover={'coding':('coder',)}))
 log=events.EventLog(dir=str(tmp_path/'logs'),console=False)
 if configured:
  from cria import privatepaths
  monkeypatch.setattr(privatepaths,'CRIA_HOME',tmp_path/'private-root')
 srv=memory_server(cfg,log,up)
 monkeypatch.setattr(server.CriaHandler,'_classify',lambda *a,**k:SimpleNamespace(task_type='coding',engagement='task',cached=False))
 store=ImageStore(tmp_path/'private',close_authority=object())
 if not configured:srv.image_workflow=ImageWorkflow(store,upstream,lambda p,r:('fixture',True) if p is up and r is role else (None,None),workspace=ImageWorkspace(WorkspaceImageTool('view_image','path')))
 tools=[copy.deepcopy(TOOL),{'type':'function','function':{'name':'exec_command','parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}}]
 history=[{'role':'user','content':TASK}]
 def post():
  if responses:
   items=[]
   for m in history:
    if m['role']=='assistant' and m.get('tool_calls'):
     items.extend({'type':'function_call','call_id':c['id'],'name':c['function']['name'],'arguments':c['function']['arguments']} for c in m['tool_calls'])
    elif m['role']=='tool':
     parts=[{'type':'input_image','image_url':p['image_url']['url'],'detail':p['image_url']['detail']} if p['type']=='image_url' else {'type':'input_text','text':p['text']} for p in m['content']]
     items.append({'type':'function_call_output','call_id':m['tool_call_id'],'output':parts})
    else:items.append({'role':m['role'],'content':m['content']})
   body={'model':'caller-alias','stream':stream,'input':items,'tools':[{'type':'function',**t['function']} for t in tools]}
  else:body={'model':'caller-alias','stream':stream,'messages':copy.deepcopy(history),'tools':tools}
  request=urllib.request.Request('http://handler.invalid/v1/'+('responses' if responses else 'chat/completions'),data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Cria-Session-Id':'workspace-image'})
  with handler_open(server.CriaHandler,srv,request) as response:data=response.read()
  received.append({'request':copy.deepcopy(body),'response':data.decode()})
  if not stream:
   parsed=json.loads(data)
   if not responses:return parsed['choices'][0]['message'],data
   output=parsed.get('output',[])
  else:
   frames=[json.loads(line[6:]) for line in data.decode().splitlines() if line.startswith('data: ') and line[6:]!='[DONE]']
   if not responses:
    deltas=[c['delta'] for f in frames for c in f.get('choices',[]) if c.get('delta')]
    calls=[{k:v for k,v in c.items() if k!='index'} for d in deltas for c in d.get('tool_calls',[])]
    return {'role':'assistant','tool_calls':calls} if calls else {'role':'assistant','content':''.join(d.get('content') or '' for d in deltas)},data
   complete=[f['response'] for f in frames if f.get('type')=='response.completed']
   assert complete,data
   output=complete[-1]['output']
  calls=[{'id':o['call_id'],'type':'function','function':{'name':o['name'],'arguments':o['arguments']}} for o in output if o.get('type')=='function_call']
  return {'role':'assistant','tool_calls':calls} if calls else {'role':'assistant','content':str(output)},data
 try:
  first,data=post();assert first['tool_calls'][0]['function']['name']=='view_image',data
  assert first['tool_calls'][0]['id'].startswith('imgread_')
  result,part=harness_read(first);assert part==IMAGE
  history.extend([first,result])
  second,data=post();assert 'tool_calls' in second,data
  assert second['tool_calls'][0]['function']['name']=='view_image',data
  assert json.loads(second['tool_calls'][0]['function']['arguments'])=={'path':path}
  assert second['tool_calls'][0]['id']!=first['tool_calls'][0]['id']
  assert len(observed)==1
  source.write_bytes(png((0,0,255)))
  result,part=harness_read(second);assert part==FRESH and source.read_bytes()!=old_bytes
  history.extend([second,result])
  final,data=post();assert b'verified-fresh' in data,data
  assert observed==[[IMAGE],[FRESH]]
  assert len(posts)==5
  assert all(p['model']=='fixture' for p in posts)
  assert len(dispatches)==2 and all(r.provider is up and r.model=='fixture' for r in dispatches)
  assert dispatches[0].dispatch_token is not dispatches[1].dispatch_token
  assert terminals==[(r,True) for r in dispatches]
  assert 'data:image' not in json.dumps(posts[-1])
  if configured:store=srv.image_workflow._workflow.store
  resources=[s for s in store._all if s._records]
  assert len(resources)==1
  records=list(resources[0]._records.values());assert len(records)==2
  assert len({r.ref for r in records})==2
  assert all(isinstance(resources[0].reinspect(r.ref),FreshWorkspaceRead) for r in records)
  assert {resources[0]._load(r)['image_url']['url'] for r in records}=={IMAGE['image_url']['url'],FRESH['image_url']['url']}
  assert all(r.workspace_path==path for r in records)
  assert resources[0].pending_observations==0
  (tmp_path/'handler-captures.json').write_text(json.dumps({'kind':'offline-real-handler-synthetic-backend','http':received,'upstream_requests':posts,'synthetic_backend_replies':replies},indent=2))
 finally:log.close()
