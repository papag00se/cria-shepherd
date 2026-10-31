"""Actual upstream POST/terminal observer with image-owned semantics, memory HTTP only."""
import json
import pytest
from cria import upstream,config,bodykeys
from cria.imageprotocol import CoderRoute,ImageUnavailable
from cria.imagestore import ImageStore
from cria.imageobserver import ObservationCallbacks
from memory_http import MemoryTransport,json_reply,stream_reply
from test_workflow_store import IMAGE,TASK,completion

class Log:
 phase='coder-image-observation';session='image-joint'
 def __init__(self):self.events=[]
 def emit(self,name,**kw):self.events.append((name,kw))

@pytest.mark.parametrize('mode',['buffered','watched','stream'])
@pytest.mark.parametrize('collapsed_strict',[False,True])
def test_actual_wire_observer_drives_only_correlated_completed_image_substitution(tmp_path,mode,collapsed_strict):
 posts=[];metadata=[]
 def respond(req):
  if req.full_url.endswith('/props'):return json_reply({'chat_template':'fixture','default_generation_settings':{'n_ctx':16384}})
  if req.full_url.endswith('/v1/models'):return json_reply({'data':[{'id':'fixture'}]})
  if req.full_url.endswith('/apply-template') or req.full_url.endswith('/tokenize'):
   metadata.append(req.full_url);raise AssertionError('Text-native endpoints cannot establish image fit')
  assert req.full_url.endswith('/v1/chat/completions')
  wire=json.loads(req.data);posts.append(wire)
  content=completion()['choices'][0]['message']['content']
  if wire.get('stream'):
   frame={'choices':[{'delta':{'content':content},'finish_reason':'stop'}]}
   return stream_reply([('data: '+json.dumps(frame)+'\n\n').encode(),b'data: [DONE]\n\n'])
  return json_reply(completion())
 transport=MemoryTransport(respond)
 up=upstream.Upstream('http://fixture.invalid',context_window=16384,capture_rendered=False,open_request=transport)
 role=config.Role(name='coder',backend='fixture',reasoning='on',temperature=0.2,max_tokens=8192,collapse_system_prompt=collapsed_strict,merge_consecutive_turns=collapsed_strict)
 source={'model':'fixture','messages':[{'role':'user','content':[IMAGE]}]}
 role.apply(source);upstream.record_applied_coder_role(source,role)
 route=CoderRoute(up,'fixture',upstream.coder_role_signature(source),True)
 authority=object();store=ImageStore(tmp_path/'private',close_authority=authority);session=store.session('source-session')
 session.select_route(route);prepared=session.prepare(source['messages'],TASK);ref=prepared.bindings[0].ref
 request_lease=session.acquire();attempt=session.begin(ref,TASK,route,source)
 role.apply(attempt.request);upstream.record_applied_coder_role(attempt.request,role)
 assert upstream.coder_role_signature(attempt.request)==route.role_signature
 callbacks=ObservationCallbacks(session,attempt)
 binding=upstream.CoderObserverBinding(callbacks.owner_token,route.role_signature,callbacks.started,callbacks.completed)
 body=upstream.bind_coder_route(attempt.request,route)
 body=upstream.bind_coder_observer(body,binding)
 log=Log()
 try:
  up._prep(body,False,log)  # preparation alone cannot mint a delivered observation
  assert session.render(prepared)==prepared.messages
  with pytest.raises(ImageUnavailable):callbacks.result()
  if mode=='buffered':up.chat(body,log)
  elif mode=='watched':up.chat_watched(body,log)
  else:list(up.stream_chat(body,log))
  assert len(posts)==1 and not metadata
  if collapsed_strict:
   roles=[m['role'] for m in posts[0]['messages'] if m['role']!='system']
   assert all(left!=right for left,right in zip(roles,roles[1:]))
  assert callbacks.result().extracted_text=='Save\nCancel'
  assert 'data:image' not in json.dumps(session.render(prepared))
  assert session.reinspect(ref)==IMAGE and session.pending_observations==0 and session.pending_leases==1
  assert bodykeys.CODER_OBSERVER not in posts[0] and bodykeys.CODER_ROUTE not in posts[0]
  assert any(event=='context.image_fit_unknown' for event,_ in log.events)
  assert not any(event in ('context.measured','context.calibrated') for event,_ in log.events)
  transport.assert_served()
 finally:
  callbacks.cancel();request_lease.release();session.confirm_close(authority);session.cleanup_descriptor();store.close()


def test_unknown_route_cannot_send_original_or_publish_observation(tmp_path):
 sent=[];transport=MemoryTransport(lambda req:sent.append(req))
 up=upstream.Upstream('http://fixture.invalid',context_window=16384,capture_rendered=False,open_request=transport)
 body={'model':'fixture','messages':[{'role':'user','content':[IMAGE]}]}
 with pytest.raises(ImageUnavailable):up.chat(body,Log())
 assert not sent

def test_harness_tool_controls_do_not_change_the_role_signature_of_the_toolless_observation():
 # Codex sends parallel_tool_calls with every request; the observation request drops it with the tools.
 role=config.Role(name='coder',backend='fixture',reasoning='auto',temperature=0.2)
 source={'model':'fixture','messages':[{'role':'user','content':[IMAGE]}],'tools':[{'type':'function','function':{'name':'x'}}],
         'tool_choice':'auto','parallel_tool_calls':True,'response_format':{'type':'text'},'reasoning_effort':'none'}
 role.apply(source);upstream.record_applied_coder_role(source,role)
 route=CoderRoute(object(),'fixture',upstream.coder_role_signature(source),True)
 from cria.imageprotocol import observation_request
 request=observation_request(source,route,TASK,IMAGE)
 role.apply(request);upstream.record_applied_coder_role(request,role)
 assert upstream.coder_role_signature(request)==route.role_signature

def test_wire_reasoning_convention_rewrite_does_not_change_the_role_signature():
 # Upstream._prep rewrites reasoning_effort into chat_template_kwargs in place before dispatch validation.
 asked={'model':'fixture','messages':[],'temperature':0.2,'reasoning_effort':'none'}
 rewritten={'model':'fixture','messages':[],'temperature':0.2,'chat_template_kwargs':{'enable_thinking':False}}
 assert upstream.coder_role_signature(asked)==upstream.coder_role_signature(rewritten)
 assert upstream.coder_role_signature(asked)!=upstream.coder_role_signature({**rewritten,'chat_template_kwargs':{'enable_thinking':True}})
 assert upstream.coder_role_signature({**asked,'reasoning_effort':'high'})==upstream.coder_role_signature(
     {**rewritten,'chat_template_kwargs':{'enable_thinking':True}})
