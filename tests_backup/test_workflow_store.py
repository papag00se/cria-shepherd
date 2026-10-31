import copy,json,stat
from dataclasses import replace
import pytest
from cria.imagestore import ImageStore,FreshWorkspaceRead
from cria.imageprotocol import CoderRoute,Delivery,ImageUnavailable
from cria import bodykeys

IMAGE={'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA','detail':'high'}}
TASK='Read the button labels and reproduce the layout.'

def completion(**changes):
 data={'viewed':True,'extracted_text':'Save\nCancel','description':'Two adjacent buttons, Save left of Cancel.','uncertainty':'Colors may depend on display.'}
 data.update(changes)
 return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(data)}}]}

@pytest.fixture
def rig(tmp_path):
 store=ImageStore(tmp_path/'private',close_authority=object())
 session=store.session('session-one')
 route=CoderRoute(object(),'actual-selected-vision','actual-role-signature',True)
 session.select_route(route)
 messages=[{'role':'user','content':[{'type':'text','text':TASK},copy.deepcopy(IMAGE)]}]
 prepared=session.prepare(messages,TASK);ref=prepared.bindings[0].ref
 body={'model':route.model,'temperature':0.3,'max_tokens':8192,'tools':[{'name':'unused'}],bodykeys.PINNED_TASK:'original task'}
 yield store,session,route,messages,prepared,ref,body,tmp_path
 for resource in list(store._all):
  for attempt in list(resource._attempts.values()):resource.cancel(attempt)
  resource.confirm_close(store._authority);resource.cleanup_descriptor()
 store.close()

def delivered(attempt,route,answer=None,wire=None,terminal=True):
 return Delivery.from_wire(attempt.nonce,route.provider,route.role_signature,wire or attempt.request,answer or completion(),terminal_complete=terminal)

def test_original_retained_until_completed_actual_coder_observation(rig):
 store,s,route,messages,prepared,ref,body,tmp=rig
 original=copy.deepcopy(messages)
 assert s.render(prepared)==messages
 attempt=s.begin(ref,TASK,route,body)
 assert attempt.request['model']==route.model
 assert attempt.request['temperature']==0.3 and attempt.request['max_tokens']==8192
 assert 'tools' not in attempt.request and bodykeys.PINNED_TASK not in attempt.request
 assert attempt.request['messages'][-1]['content'][-1]==IMAGE
 assert s.render(prepared)==messages
 s.complete(attempt,delivered(attempt,route))
 later=s.render(prepared)
 assert later[0]['content'][0]==messages[0]['content'][0]
 text=later[0]['content'][1]['text']
 assert 'Save\nCancel' in text and 'Historical coder observation' in text and ref in text
 assert 'data:image' not in str(later)
 assert s.reinspect(ref)==IMAGE and messages==original
 same=s.prepare(messages,TASK)
 assert same.bindings==prepared.bindings and s.render(same)==later
 assert not (tmp/'workspace').exists()

@pytest.mark.parametrize('capability',[False,None])
def test_no_vision_or_unknown_keeps_image_and_reports_unavailable(rig,capability):
 _,s,route,messages,prepared,ref,body,_=rig
 route=replace(route,vision=capability);s.select_route(route)
 with pytest.raises(ImageUnavailable,match='capability'):s.begin(ref,TASK,route,body)
 assert s.render(prepared)==messages

@pytest.mark.parametrize('failure',['incomplete','length','tools','refusal','not-viewed','malformed','extra-key','duplicate-key'])
def test_bad_or_incomplete_observation_never_substitutes(rig,failure):
 _,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body);answer=completion();terminal=True
 message=answer['choices'][0]['message']
 if failure=='incomplete':terminal=False
 if failure=='length':answer['choices'][0]['finish_reason']='length'
 if failure=='tools':message['tool_calls']=[{'id':'unexpected'}]
 if failure=='refusal':message['refusal']='Cannot view'
 if failure=='not-viewed':answer=completion(viewed=False)
 if failure=='malformed':message['content']='I think it looks blue'
 if failure=='extra-key':answer=completion(extra='not part of observation')
 if failure=='duplicate-key':message['content']='{"viewed":true,"viewed":false}'
 with pytest.raises(ImageUnavailable):s.complete(attempt,delivered(attempt,route,answer,terminal=terminal))
 assert s.render(prepared)==messages and s.reinspect(ref)==IMAGE

@pytest.mark.parametrize('fault',['provider','model','role','image','nonce','route-changed'])
def test_delivery_correlates_actual_provider_role_model_image_and_attempt(rig,fault):
 _,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body);receipt=delivered(attempt,route)
 if fault=='provider':receipt=replace(receipt,provider=object())
 if fault=='model':receipt=replace(receipt,model='harness-alias')
 if fault=='role':receipt=replace(receipt,role_signature='different applied role')
 if fault=='image':receipt=replace(receipt,image_digest='wrong')
 if fault=='nonce':receipt=replace(receipt,attempt='stale')
 if fault=='route-changed':s.select_route(replace(route,provider=object()))
 with pytest.raises(ImageUnavailable):s.complete(attempt,receipt)
 assert s.render(prepared)==messages

def test_concurrent_latest_attempt_wins_and_old_completion_cannot_publish(rig):
 _,s,route,messages,prepared,ref,body,_=rig
 first=s.begin(ref,TASK,route,body);second=s.begin(ref,TASK,route,body)
 with pytest.raises(ImageUnavailable,match='stale'):s.complete(first,delivered(first,route))
 assert s.render(prepared)==messages
 s.complete(second,delivered(second,route));text=s.render(prepared)[0]['content'][1]['text']
 with pytest.raises(ImageUnavailable):s.complete(first,delivered(first,route,completion(description='outdated')))
 assert s.render(prepared)[0]['content'][1]['text']==text

def test_session_replacement_invalidates_inflight_but_does_not_close_resources(rig):
 store,s,route,_,prepared,ref,body,tmp=rig
 attempt=s.begin(ref,TASK,route,body);directory=s._root
 replacement=store.session('session-one',replace=True)
 assert directory.exists() and s.pending_leases==1
 with pytest.raises(ImageUnavailable):s.complete(attempt,delivered(attempt,route))
 with pytest.raises(ImageUnavailable):replacement.reinspect(ref)
 with pytest.raises(ImageUnavailable):replacement.render(prepared)
 s.cancel(attempt);s.confirm_close(store._authority);s.cleanup_descriptor();store.release(s)
 assert not directory.exists()

def test_same_image_in_another_occurrence_or_session_is_not_cached(rig):
 store,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body);s.complete(attempt,delivered(attempt,route))
 changed=messages+[{'role':'assistant','content':'Earlier work.'},copy.deepcopy(messages[0])]
 view=s.prepare(changed,TASK)
 assert len(view.bindings)==2 and view.bindings[1].ref!=ref
 assert s.render(view)[2]['content'][1]==IMAGE
 other=store.session('another-session')
 with pytest.raises(ImageUnavailable):other.reinspect(ref)

def test_task_change_invalidates_inflight_without_claiming_new_observation(rig):
 _,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body)
 newer=s.prepare(messages,'Inspect the fine print instead.')
 with pytest.raises(ImageUnavailable):s.complete(attempt,delivered(attempt,route))
 with pytest.raises(ImageUnavailable):s.render(prepared)
 assert s.render(newer)==messages

def test_workspace_reinspection_is_a_fresh_harness_read_request(rig):
 _,s,route,messages,_,_,body,tmp=rig
 workspace_messages=[{'role':'user','content':[{'type':'text','text':'Fresh image returned by harness'},copy.deepcopy(IMAGE)]}]
 view=s.prepare(workspace_messages,TASK,workspace_sources={(0,1):'/work/image.png'})
 ref=view.bindings[0].ref
 assert s.reinspect(ref)==FreshWorkspaceRead(ref,'/work/image.png')
 changed={'type':'image_url','image_url':{'url':'data:image/png;base64,BBBB'}}
 newref=s.retain_fresh_workspace_read(ref,changed,TASK,event_id='verified-harness-read-2')
 assert newref!=ref
 attempt=s.begin(newref,TASK,route,body)
 assert attempt.request['messages'][-1]['content'][-1]==changed

def test_private_permissions_cleanup_expiry_and_retained_corruption(tmp_path):
 # The full-suite incident selected session-state.json from an unordered glob;
 # corrupt the exact retained source, not unrelated session metadata.
 clock=[0];store=ImageStore(tmp_path/'private',close_authority=object(),clock=lambda:clock[0]);s=store.session('s')
 view=s.prepare([{'role':'user','content':[IMAGE]}],TASK);ref=view.bindings[0].ref
 file=s._root/(ref+'.json')
 assert stat.S_IMODE(file.stat().st_mode)==0o600 and stat.S_IMODE(s._root.stat().st_mode)==0o700
 file.write_text('{}')
 with pytest.raises(ImageUnavailable):s.reinspect(ref)
 clock[0]=10;directory=s._root
 assert not store.expire_closed(s,ttl_seconds=5) and directory.exists()
 s.confirm_close(store._authority)
 clock[0]=15
 s.cleanup_descriptor()
 assert store.expire_closed(s,ttl_seconds=5) and not directory.exists()
 with pytest.raises(ImageUnavailable):s.render(view)
 store.close()

def test_private_provenance_identity_survives_unchanged(rig):
 _,s,_,messages,_,_,_,_=rig
 token=object();messages[0][bodykeys.RESULT_REPORT]=token
 view=s.prepare(messages,TASK)
 assert s.render(view)[0][bodykeys.RESULT_REPORT] is token


def test_only_actual_confirmed_close_and_drained_leases_permit_cleanup(rig):
 store,s,route,_,prepared,ref,body,_=rig
 request_lease=s.acquire();attempt=s.begin(ref,TASK,route,body)
 assert s.pending_leases==2 and s.pending_observations==1
 with pytest.raises(ImageUnavailable):store.release(s)
 with pytest.raises(ImageUnavailable):s.confirm_close(object())
 s.confirm_close(store._authority)
 with pytest.raises(ImageUnavailable):s.acquire()
 with pytest.raises(ImageUnavailable):store.release(s)
 request_lease.release()
 assert s.pending_leases==1 and s._root.exists()
 s.cancel(attempt)
 assert s.ready_to_close and s._root.exists()  # leaf does not automatically clean up
 s.cleanup_descriptor();store.release(s)
 assert not s._root.exists()


def test_failed_cleanup_retries_and_descriptor_cannot_delete_active_session(rig,monkeypatch):
 from cria import imagestore
 store,s,_,_,_,_,_,_=rig
 with pytest.raises(ImageUnavailable):s.cleanup_descriptor()
 s.confirm_close(store._authority);descriptor=s.cleanup_descriptor()
 real=imagestore.shutil.rmtree;calls=[]
 def fail_once(path):
  calls.append(path)
  if len(calls)==1:raise OSError('injected retention cleanup failure')
  return real(path)
 monkeypatch.setattr(imagestore.shutil,'rmtree',fail_once)
 with pytest.raises(OSError):store.release(s)
 assert s._root.exists() and not s._cleanup_complete
 store.retry_closed(descriptor)
 assert len(calls)==2 and not s._root.exists()
 active=store.session('still-live');bad={'owner':'session-images','directory':active._root.name}
 with pytest.raises(ImageUnavailable):store.retry_closed(bad)
 assert active._root.exists()


def test_late_projection_keeps_raw_root_identity_and_extra_frame_private_provenance(rig):
 from cria import selfcompact
 _,s,route,messages,prepared,ref,body,_=rig
 root_before=selfcompact.root_text(messages)
 attempt=s.begin(ref,TASK,route,body);s.complete(attempt,delivered(attempt,route))
 assert s.pending(prepared)==()
 token=object();framed=[{'role':'system','content':'Real coder frame'},
   {**messages[0],bodykeys.RESULT_REPORT:token},{'role':'assistant','content':'Actual work'},
   {'role':'user','content':'A current source-owned steer'}]
 original=copy.deepcopy(messages)
 projected=s.project(prepared,framed)
 assert projected[0] is framed[0] and projected[-1] is framed[-1]
 assert projected[1][bodykeys.RESULT_REPORT] is token
 assert projected[1]['content'][1]['type']=='text'
 assert messages==original and selfcompact.root_text(messages)==root_before
 assert framed[1]['content'][1]==IMAGE


def test_pending_late_projection_preserves_packets_and_missing_image_errors(rig):
 _,s,_,messages,prepared,ref,_,_=rig
 framed=[{'role':'system','content':'coder'},*messages,{'role':'user','content':'Continue'}]
 result=s.project(prepared,framed)
 assert result==framed and result[1] is framed[1] and s.pending(prepared)==(ref,)
 with pytest.raises(ImageUnavailable):s.project(prepared,[framed[0],framed[-1]])
 with pytest.raises(ImageUnavailable):s.project(prepared,framed+[messages[0]])

def test_remote_url_source_is_labelled_a_reference_not_a_retained_copy(rig):
 _,s,route,_,_,_,body,_=rig
 remote={'type':'image_url','image_url':{'url':'https://example.test/a.png?sig=secret'}}
 messages=[{'role':'user','content':[{'type':'text','text':TASK},remote]}]
 prepared=s.prepare(messages,TASK);ref=prepared.bindings[0].ref
 attempt=s.begin(ref,TASK,route,body)
 s.complete(attempt,delivered(attempt,route))
 text=s.render(prepared)[0]['content'][1]['text']
 assert 'remote URL reference' in text and 'was not fetched' in text
 assert 'retained privately' not in text and 'example.test' not in text and 'secret' not in text
 assert s.reinspect(ref)==remote
