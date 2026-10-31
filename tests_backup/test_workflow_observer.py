import json
from dataclasses import dataclass,replace
import pytest
from test_workflow_store import rig,completion,IMAGE,TASK
from cria.imageobserver import ObservationCallbacks
from cria.imageprotocol import ImageUnavailable

@dataclass(frozen=True)
class Receipt:
 owner_token: object
 dispatch_token: object
 provider: object
 model: str
 role_signature: str
 final_wire: bytes

def receipt(callback,attempt,route,**changes):
 value=Receipt(callback.owner_token,object(),route.provider,route.model,route.role_signature,json.dumps(attempt.request).encode())
 return replace(value,**changes)


def test_final_post_receipt_and_terminal_are_both_required(rig):
 _,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body);callback=ObservationCallbacks(s,attempt)
 with pytest.raises(ImageUnavailable):callback.result()
 assert s.render(prepared)==messages
 posted=receipt(callback,attempt,route);callback.started(posted)
 assert s.render(prepared)==messages
 callback.completed(posted,completion(),True)
 assert callback.result().extracted_text=='Save\nCancel'
 assert s.render(prepared)!=messages and s.pending_observations==0
 callback.cancel()

@pytest.mark.parametrize('fault',['owner','provider','model','role','missing-image','changed-image','missing-task'])
def test_untrusted_route_or_missing_source_cannot_mint_observation(rig,fault):
 _,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body);callback=ObservationCallbacks(s,attempt)
 posted=receipt(callback,attempt,route)
 if fault=='owner':posted=replace(posted,owner_token=object())
 if fault=='provider':posted=replace(posted,provider=object())
 if fault=='model':posted=replace(posted,model='harness-alias')
 if fault=='role':posted=replace(posted,role_signature='claimed role')
 if fault in ('missing-image','changed-image','missing-task'):
  wire=json.loads(posted.final_wire)
  if fault=='missing-image':wire['messages'][-1]['content'].pop()
  if fault=='changed-image':wire['messages'][-1]['content'][-1]['image_url']['url']='data:image/png;base64,BBBB'
  if fault=='missing-task':wire['messages'][-1]['content'][0]['text']='unrelated task'
  posted=replace(posted,final_wire=json.dumps(wire).encode())
 with pytest.raises(ImageUnavailable):callback.started(posted)
 assert s.render(prepared)==messages
 callback.cancel()


def test_failed_first_post_then_changed_refit_receipt_can_complete(rig):
 _,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body);callback=ObservationCallbacks(s,attempt)
 first=receipt(callback,attempt,route);callback.started(first);callback.completed(first,None,False)
 assert s.pending_observations==1 and s.render(prepared)==messages
 second=receipt(callback,attempt,route);callback.started(second)
 with pytest.raises(ImageUnavailable):callback.completed(first,completion(),True)
 callback.completed(second,completion(),True)
 assert callback.result().description and s.pending_observations==0


def test_no_receipt_incomplete_or_cancel_preserves_original(rig):
 _,s,route,messages,prepared,ref,body,_=rig
 attempt=s.begin(ref,TASK,route,body);callback=ObservationCallbacks(s,attempt)
 posted=receipt(callback,attempt,route);callback.started(posted);callback.completed(posted,None,False)
 with pytest.raises(ImageUnavailable):callback.result()
 callback.cancel()
 assert s.pending_observations==0 and s.render(prepared)==messages
 with pytest.raises(ImageUnavailable):callback.completed(posted,completion(),True)
