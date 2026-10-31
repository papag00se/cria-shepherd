import copy,json
import pytest
from cria.imagestore import ImageStore
from cria.imageworkspace import ImageWorkspace,WorkspaceImageTool
from cria.imageprotocol import ImageUnavailable
from test_workflow_workspace_http import TOOL,IMAGE,PATH,FRESH,action

@pytest.fixture
def setup(tmp_path):
 s=ImageStore(tmp_path/'private',close_authority=object()).session('one')
 w=ImageWorkspace(WorkspaceImageTool('view_image','path'))
 c=w.register(s,action('view_image',{'path':PATH}),[TOOL])
 m=c['choices'][0]['message'];cid=m['tool_calls'][0]['id']
 history=[{'role':'user','content':'Look at the workspace image'},m,{'role':'tool','tool_call_id':cid,'content':[copy.deepcopy(IMAGE)]}]
 return s,w,history

@pytest.mark.parametrize('fault',['unknown_id','path','issuer_missing','duplicate_result','duplicate_call','result_before_call'])
def test_registered_source_correlation_rejects_spoof_and_ambiguity(setup,fault):
 s,w,history=setup
 if fault=='unknown_id':history[-1]['tool_call_id']='client-claim'
 elif fault=='path':history[1]['tool_calls'][0]['function']['arguments']=json.dumps({'path':'/different'})
 elif fault=='issuer_missing':history.pop(1)
 elif fault=='duplicate_result':history.append(copy.deepcopy(history[-1]))
 elif fault=='duplicate_call':history.insert(1,copy.deepcopy(history[1]))
 else:history[1],history[2]=history[2],history[1]
 with pytest.raises(ImageUnavailable):w.resolve(s,history)
 assert not s._records

def test_changed_result_requires_new_harness_action_and_new_reference(setup):
 s,w,history=setup
 sources=w.resolve(s,history);old=s.prepare(history,'Look',workspace_sources=sources)
 assert w.resolve(s,history)==sources
 mutated=copy.deepcopy(history);mutated[-1]['content']=[copy.deepcopy(FRESH)]
 with pytest.raises(ImageUnavailable):w.resolve(s,mutated)
 ref=old.bindings[0].ref
 emitted=w.request(s,ref,PATH,[TOOL],'actual-model')
 fresh_message=emitted['choices'][0]['message'];fresh_id=fresh_message['tool_calls'][0]['id']
 history.extend([fresh_message,{'role':'tool','tool_call_id':fresh_id,'content':[copy.deepcopy(FRESH)]}])
 new=s.prepare(history,'Look',workspace_sources=w.resolve(s,history))
 assert len(new.bindings)==2 and new.bindings[0].ref!=new.bindings[1].ref
 assert s._load(s._records[ref])==IMAGE
 assert s._load(s._records[new.bindings[1].ref])==FRESH


def test_session_replacement_cannot_inherit_other_generation_reads(setup,tmp_path):
 s,w,history=setup
 other=ImageStore(tmp_path/'other',close_authority=object()).session('one')
 with pytest.raises(ImageUnavailable):w.resolve(other,history)


def test_exact_pending_read_survives_source_owned_session_recovery(setup):
 s,w,history=setup
 recovered=type(s).restore(s._root,s.retention_handle(),close_authority=s._authority,clock=s._clock,recovered_leases=())
 assert w.resolve(recovered,history)=={(2,0):PATH}

@pytest.mark.parametrize('fault',['not_offered','ambiguous','required_other_arg','malformed_args','incomplete'])
def test_read_registration_faults_cannot_publish_action(setup,fault):
 s,w,_=setup;tools=[copy.deepcopy(TOOL)];c=action('view_image',{'path':PATH})
 if fault=='not_offered':tools=[]
 elif fault=='ambiguous':tools*=2
 elif fault=='required_other_arg':tools[0]['function']['parameters']['required'].append('extra')
 elif fault=='malformed_args':c['choices'][0]['message']['tool_calls'][0]['function']['arguments']='bad'
 else:c['choices'][0]['finish_reason']='length'
 with pytest.raises(ImageUnavailable):w.register(s,c,tools)

@pytest.mark.parametrize('args',['["path"]','[]','null','"path"','{"path":[]}','{"path":{}}','{"path":null}','{"path":false}','{"path":""}'])
def test_malformed_native_path_arguments_are_typed_unavailable(setup,args):
 s,w,_=setup;c=action('view_image',{'path':PATH})
 c['choices'][0]['message']['tool_calls'][0]['function']['arguments']=args
 with pytest.raises(ImageUnavailable):w.register(s,c,[TOOL])

@pytest.mark.parametrize('words',['view_image is not allowed because you do not support image inputs',
                                  [{'type':'text','text':'No such file: ./note.png'}]])
def test_harness_text_failure_of_an_issued_read_passes_through_instead_of_failing_the_request(setup,words):
 s,w,history=setup
 history[-1]['content']=copy.deepcopy(words)
 assert w.resolve(s,history)=={}
 assert history[-1]['content']==words
 prepared=s.prepare(history,'Look',workspace_sources={})
 assert not prepared.bindings
