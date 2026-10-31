"""Invocation ordering on the current survey protocol, without lifecycle/codec prerequisites."""
from copy import deepcopy
import json
import pytest
from cria import denial,wsview,writeproxy
from tests.test_a_result_is_ciras_refusal_only_when_ciras_own_lowering_proved_it import _lower,_run,_history

def native(cid,name='delete_file',args=None):
    return {'role':'assistant','tool_calls':[{'id':cid,'type':'function','function':{'name':name,'arguments':json.dumps(args or {'path':'out.txt'})}}]}

def returned(cid):
    return {'role':'tool','tool_call_id':cid,'content':'native result unchanged\n'}

def acquisition(root,cid,kind='read_file',path='out.txt'):
    token=wsview.bind(wsview.View(str(root),cid))
    try:
        args={'path':path} if kind=='read_file' else {'path':'seed.txt','content':'seed'}
        call=_lower(kind,args,cid=cid,root=str(root),session=cid)
    finally:wsview.unbind(token)
    result=_history(call,_run(call,root))
    if kind=='write_file':assert writeproxy._frame_proofs(result)[cid].survey
    return result

def represent(view,history):
    token=wsview.bind(view)
    try:return writeproxy.represent_inbound(history,workspace_root=view.root)
    finally:wsview.unbind(token)

def test_old_survey_cannot_clear_later_native_mutation(tmp_path):
    target=tmp_path/'out.txt';target.write_text('old')
    old=acquisition(tmp_path,'old','write_file');target.unlink()
    history=[old[0],native('mut'),returned('mut'),old[1]];original=deepcopy(history)
    view=wsview.View(str(tmp_path),'delayed')
    out=represent(view,history)
    assert not view.surveyed or view.may_have_changed
    assert view.observation_fingerprint is None
    assert denial.landed(out[-1]) and out[2]['content']=='native result unchanged\n'
    assert history==original

def test_old_read_never_replaces_newer_post_mutation_body(tmp_path):
    target=tmp_path/'out.txt';target.write_text('old bytes')
    old=acquisition(tmp_path,'old');target.write_text('new bytes');new=acquisition(tmp_path,'new')
    view=wsview.View(str(tmp_path),'later-body')
    out=represent(view,[old[0],native('mut','apply_patch',{'patch':'opaque'}),returned('mut')]+new+[old[1]])
    assert view.read('out.txt')=='new bytes'
    assert [denial.read_payload(m) for m in out if m.get('role')=='tool']==[None,'new bytes','old bytes']

def test_native_effect_withholds_current_body(tmp_path):
    (tmp_path/'out.txt').write_text('old bytes');old=acquisition(tmp_path,'read')
    view=wsview.View(str(tmp_path),'native-effect')
    represent(view,old+[native('mut'),returned('mut')])
    assert view.read('out.txt') is None

@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('same',[False,True])
def test_pure_read_overlap_current_only_when_consistent(tmp_path,reverse,same):
    p=tmp_path/'out.txt';p.write_text('old');old=acquisition(tmp_path,'old')
    if not same:p.write_text('new')
    new=acquisition(tmp_path,'new');results=[old[1],new[1]]
    if reverse:results.reverse()
    view=wsview.View(str(tmp_path),'pure-overlap')
    represent(view,[old[0],new[0]]+results)
    assert view.read('out.txt')==('old' if same else None)

@pytest.mark.parametrize('reverse',[False,True])
def test_independent_overlapping_reads_keep_both_paths(tmp_path,reverse):
    (tmp_path/'one').write_text('one');(tmp_path/'two').write_text('two')
    one=acquisition(tmp_path,'one',path='one');two=acquisition(tmp_path,'two',path='two');results=[one[1],two[1]]
    if reverse:results.reverse()
    view=wsview.View(str(tmp_path),'independent')
    represent(view,[one[0],two[0]]+results)
    assert view.read('one')=='one' and view.read('two')=='two'

def test_serial_observations_still_refresh_normally(tmp_path):
    p=tmp_path/'out.txt';p.write_text('old');old=acquisition(tmp_path,'old');p.write_text('new');new=acquisition(tmp_path,'new')
    view=wsview.View(str(tmp_path),'serial');represent(view,old+new)
    assert view.read('out.txt')=='new'
    represent(view,acquisition(tmp_path,'fresh-survey','write_file'))
    assert view.surveyed and not view.may_have_changed and view.isfile('out.txt') is True

def test_same_batch_pending_writer_withholds_read_then_recovers(tmp_path):
    p=tmp_path/'out.txt';p.write_text('old');writer=acquisition(tmp_path,'writer','write_file')
    p.write_text('new');reader=acquisition(tmp_path,'reader')
    view=wsview.View(str(tmp_path),'pending')
    represent(view,[{'role':'assistant','tool_calls':writer[0]['tool_calls']+reader[0]['tool_calls']},reader[1],writer[1]])
    assert view.read('out.txt') is None
    represent(view,acquisition(tmp_path,'recovery'))
    assert view.read('out.txt')=='new'

def test_existing_derived_body_is_invalidated_by_parent_effect(tmp_path):
    (tmp_path/'sub').mkdir();(tmp_path/'sub/out.txt').write_text('old')
    parent=wsview.View(str(tmp_path),'derived');represent(parent,acquisition(tmp_path,'old',path='sub/out.txt'))
    child=parent.reroot(str(tmp_path/'sub'));assert child.read('out.txt')=='old'
    represent(parent,[native('mut'),returned('mut')])
    assert parent.read('sub/out.txt') is None and child.read('out.txt') is None
