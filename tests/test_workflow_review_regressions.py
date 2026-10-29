"""Retain independently reproduced wrong-route and malformed-ref incidents."""
import json
from types import SimpleNamespace
import urllib.error
import pytest
import test_workflow_http as original
from cria.imageworkflow import ImageWorkflow
from cria.imageprotocol import ImageUnavailable

@pytest.mark.parametrize('loop',[False,True])
@pytest.mark.parametrize('responses',[False,True])
@pytest.mark.parametrize('stream',[False,True])
def test_capability_cannot_redirect_actual_selected_coder_model(tmp_path,monkeypatch,loop,responses,stream):
 seen=[];instances=[];transport=original.MemoryTransport
 def factory(respond):
  def wrapped(req):
   if req.full_url.endswith('/v1/chat/completions'):seen.append(json.loads(req.data))
   return respond(req)
  return transport(wrapped)
 base=original.ImageWorkflow
 class WrongCapability(base):
  def __init__(self,store,wire,capability):
   instances.append(self)
   super().__init__(store,wire,lambda p,r:('alternate-not-selected',True))
 monkeypatch.setattr(original,'ImageWorkflow',WrongCapability)
 monkeypatch.setattr(original,'MemoryTransport',factory)
 # Reuse real handler/route/Role.apply/POST fixture with explicit failure expectations.
 original.test_real_http_image_observation_then_coder_projection(tmp_path,responses,stream,False,loop,'unknown',monkeypatch)
 assert not seen,'Alternate capability model must never reach either actual POST'
 retained=[s for s in instances[0].store._all if s._records]
 assert retained
 assert all(s._load(r)==original.IMAGE and r.observation is None for s in retained for r in s._records.values())

@pytest.mark.parametrize('arguments',[json.dumps({'ref':[]}),json.dumps({'ref':{}}),json.dumps({'ref':False}),json.dumps({'ref':None}),json.dumps({'ref':''}),json.dumps([]),json.dumps(None),'bad-json',{},'{}',json.dumps({'ref':'img_known','extra':1})])
def test_reinspection_rejects_invalid_json_shape_and_reference_before_lookup(arguments):
 wf=ImageWorkflow(None,None,None)
 wf.run=lambda *a:{'model':'fixture','messages':[]}
 ctx=SimpleNamespace(prepared=SimpleNamespace(bindings=(SimpleNamespace(ref='img_known'),)))
 result={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'id':'bad','function':{'name':'reinspect_image','arguments':arguments}}]}}]}
 with pytest.raises(ImageUnavailable):wf.chat(SimpleNamespace(chat=lambda *a:json.dumps(result)),object(),{},ctx,None)
