"""Private persisted image references and source-fenced cleanup recovery."""
import copy,json
from dataclasses import replace
import pytest
from cria.imagestore import ImageStore,FreshWorkspaceRead
from cria.imageprotocol import CoderRoute,ImageUnavailable
from test_workflow_store import IMAGE,TASK,completion,delivered


def create(tmp_path,*,workspace=False):
 root=tmp_path/'private';authority=object();store=ImageStore(root,close_authority=authority)
 session=store.session('owned-resource-generation');route=CoderRoute(object(),'actual-model','actual-role',True)
 session.select_route(route);messages=[{'role':'user','content':[IMAGE]}]
 source={(0,0):'/harness/work/image.png'} if workspace else None
 prepared=session.prepare(messages,TASK,workspace_sources=source)
 return root,store,session,authority,route,messages,prepared,prepared.bindings[0].ref


def close(store,session,authority):
 for attempt in list(session._attempts.values()):session.cancel(attempt)
 session.confirm_close(authority);descriptor=session.cleanup_descriptor()
 store.release(session)
 return descriptor


def test_original_ref_and_completed_observation_recover_without_model_authority(tmp_path):
 root,oldstore,old,authority,route,messages,prepared,ref=create(tmp_path)
 attempt=old.begin(ref,TASK,route,{'model':route.model});old.complete(attempt,delivered(attempt,route))
 expected=old.render(prepared);handle=json.loads(json.dumps(old.retention_handle()))
 recovered_store=ImageStore(root,close_authority=object())
 recovered=recovered_store.restore_session(handle,recovered_leases=())
 assert recovered.reinspect(ref)==IMAGE
 view=recovered.prepare(messages,TASK)
 assert view.bindings[0].ref==ref and recovered.render(view)==expected
 assert recovered._route is None
 with pytest.raises(ImageUnavailable):recovered.complete(attempt,delivered(attempt,route))
 close(recovered_store,recovered,recovered_store._authority)


def test_recovery_requires_explicit_recovered_handler_and_image_leases_to_drain(tmp_path):
 root,_,old,_,_,_,_,ref=create(tmp_path)
 handle=old.retention_handle();new=ImageStore(root,close_authority=object())
 session=new.restore_session(handle,recovered_leases=(('handler-after-recovery','handler'),('image-after-recovery','image-observation')))
 assert session.pending_leases==2 and session.pending_observations==1
 assert session.reinspect(ref)==IMAGE
 session.confirm_close(new._authority)
 with pytest.raises(ImageUnavailable):session.cleanup_descriptor()
 session.recovered_lease('handler-after-recovery').release()
 assert session.pending_leases==1 and session.pending_observations==1
 session.recovered_lease('image-after-recovery').release()
 assert session.pending_leases==0 and session.pending_observations==0
 descriptor=session.cleanup_descriptor();new.retry_closed(descriptor)
 assert not session._root.exists()


def test_workspace_provenance_recovery_still_requires_fresh_harness_read(tmp_path):
 root,_,old,_,_,_,_,ref=create(tmp_path,workspace=True)
 store=ImageStore(root,close_authority=object());session=store.restore_session(old.retention_handle(),recovered_leases=())
 assert session.reinspect(ref)==FreshWorkspaceRead(ref,'/harness/work/image.png')
 close(store,session,store._authority)


def test_closed_generation_descriptor_survives_partial_cleanup_and_restart(tmp_path,monkeypatch):
 from cria import imagestore,imagepersist
 root,store,session,authority,_,_,_,_=create(tmp_path)
 session.confirm_close(authority);descriptor=json.loads(json.dumps(session.cleanup_descriptor()))
 real=imagestore.shutil.rmtree
 def partial(directory):
  (directory/imagepersist.STATE_NAME).unlink()
  raise OSError('injected partial directory deletion')
 monkeypatch.setattr(imagestore.shutil,'rmtree',partial)
 with pytest.raises(OSError):store.release(session)
 assert session._root.exists() and imagepersist.read_marker(session._root)['closed']==descriptor['closed']
 monkeypatch.setattr(imagestore.shutil,'rmtree',real)
 restarted=ImageStore(root,close_authority=object());restarted.retry_closed(descriptor)
 assert not session._root.exists() and imagepersist.read_marker(session._root) is None
 restarted.retry_closed(descriptor)  # durable retries are idempotent

@pytest.mark.parametrize('fault',['generation','close-seal','path','unconfirmed'])
def test_cleanup_recovery_never_targets_active_or_replaced_generation(tmp_path,fault):
 root,store,session,authority,_,_,_,_=create(tmp_path)
 session.confirm_close(authority);descriptor=session.cleanup_descriptor()
 bad=copy.deepcopy(descriptor)
 if fault=='generation':bad['generation']='0'*32
 if fault=='close-seal':bad['closed']='forged seal'
 if fault=='path':bad['directory']='../workspace'
 if fault=='unconfirmed':bad={**session.retention_handle(),'closed':None}
 restarted=ImageStore(root,close_authority=object())
 with pytest.raises(ImageUnavailable):restarted.retry_closed(bad)
 assert session._root.exists()
 store.release(session)


def test_active_generation_cannot_mint_cleanup_descriptor_or_be_expired(tmp_path):
 _,store,session,authority,_,_,_,_=create(tmp_path)
 assert not store.expire_closed(session,ttl_seconds=0)
 with pytest.raises(ImageUnavailable):session.cleanup_descriptor()
 with pytest.raises(ImageUnavailable):store.release(session)
 with pytest.raises(ImageUnavailable):session.confirm_close('client JSON closure claim')
 assert session._root.exists()
 close(store,session,authority)


def test_unsealed_cleanup_descriptor_cannot_bypass_durable_planning(tmp_path):
 _,store,session,authority,_,_,_,_=create(tmp_path)
 session.confirm_close(authority)
 with pytest.raises(ImageUnavailable):store.release(session)
 assert session._root.exists()
 close(store,session,authority)


def test_corrupt_private_index_fails_explicitly_without_deleting_retained_source(tmp_path):
 from cria import imagepersist
 root,_,old,_,_,_,_,ref=create(tmp_path)
 file=old._records[ref].filename
 (old._root/imagepersist.STATE_NAME).write_text('{"version":1,"generation":"'+old._generation+'"}')
 restarted=ImageStore(root,close_authority=object())
 with pytest.raises(ImageUnavailable):restarted.restore_session(old.retention_handle(),recovered_leases=())
 assert file.exists()


def test_closed_descriptor_must_be_issued_before_cleanup_even_after_restart(tmp_path):
 root,_,old,authority,_,_,_,_=create(tmp_path)
 old.confirm_close(authority)
 forged={**old.retention_handle(),'closed':old._close_seal}
 restarted=ImageStore(root,close_authority=object())
 with pytest.raises(ImageUnavailable):restarted.retry_closed(forged)
 assert old._root.exists()
 descriptor=old.cleanup_descriptor();restarted.retry_closed(descriptor)
 assert not old._root.exists()
