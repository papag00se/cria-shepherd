import copy,json
import pytest
from cria import contextfloor as f,bodykeys
IMAGE={'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA'}}
def pair(content):return [{'role':'assistant','content':'Reading current source','tool_calls':[{'id':'current','type':'function','function':{'name':'read_file','arguments':'{"path":"f.py"}'}}]},{'role':'tool','tool_call_id':'current','content':content}]
def history(content):return [{'role':'user','content':'Task'}]+pair(content)+[{'role':'assistant','content':'old work '*180} for _ in range(12)]+[{'role':'user','content':'Continue'}]
@pytest.mark.parametrize('restored',[False,True])
def test_current_read_full_content_and_issuer_survive_pressure(restored):
 content=json.dumps({'body':['important '+str(i) for i in range(700)]})
 messages=history(content)
 if restored:messages[2][bodykeys.RESTORED_FILES]={'offered':{'f.py':1}}
 original=copy.deepcopy(messages)
 out,_,rep=f.fit(messages,None,window=1800,reserve=300,safety=1,protected_call_ids=('current',))
 assert messages==original
 assert original[1] in out and original[2] in out
 assert rep.over_budget  # the current read is genuinely irreducible at this text window
 assert rep.outputs_reduced==0 and rep.restored_reduced==0

def test_current_pair_counts_as_input_before_output_reserve():
 messages=history('current source '*220)
 core=f._input_core(messages,'',protected_call_ids=('current',))
 assert messages[1] in core and messages[2] in core
 out,_,rep=f.fit(messages,None,window=2400,reserve=2200,safety=1,protected_call_ids=('current',))
 assert messages[1] in out and messages[2] in out
 assert rep.reserve<2200

@pytest.mark.parametrize('ids',[('missing',),('current','current'),('',),['current']])
def test_ambiguous_or_missing_requested_protection_errors(ids):
 with pytest.raises(ValueError):f.fit(history('source'),None,window=4000,reserve=100,protected_call_ids=ids)

def test_duplicate_or_unpaired_current_source_errors():
 messages=history('source');messages.insert(3,copy.deepcopy(messages[2]))
 with pytest.raises(ValueError):f.fit(messages,None,window=4000,reserve=100,protected_call_ids=('current',))

def test_pending_historical_image_never_dropped_and_cost_stays_unknown():
 image={'role':'user','content':[{'type':'text','text':'image instruction '*900},IMAGE],bodykeys.ANNOTATION_SOURCE:bodykeys.AnnotationSource.INVENTORY}
 messages=[{'role':'user','content':'Task'},image]+[{'role':'assistant','content':'old '*600} for _ in range(10)]+[{'role':'user','content':'Continue'}]
 out,_,rep=f.fit(messages,None,window=1000,reserve=200,safety=1)
 assert image in out and rep.over_budget and rep.image_tokens_unknown

def test_image_only_is_unknown_even_when_text_estimate_fits():
 messages=[{'role':'user','content':[IMAGE]}]
 out,_,rep=f.fit(messages,None,window=4096,reserve=200,safety=1)
 assert out==messages and rep.image_tokens_unknown
 assert f.est_total(out,None)==0
