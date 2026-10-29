import copy,json
import pytest
from cria import responses,massage,contextfloor,upstream,bodykeys
IMAGE={'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA','detail':'high'}}
class Log:
 phase='coder'
 def emit(self,*args,**kwargs):pass

def request(part=None):return {'model':'fixture','input':[{'type':'message','role':'user','content':[{'type':'input_text','text':'Before'},part or {'type':'input_image',**{'image_url':IMAGE['image_url']['url'],'detail':'high'}},{'type':'input_text','text':'After'}]}]}

def test_response_ordered_image_and_unknown_metadata_explicit():
 raw=request();original=copy.deepcopy(raw)
 assert responses.to_chat_body(raw)['messages'][0]['content']==[{'type':'text','text':'Before'},IMAGE,{'type':'text','text':'After'}]
 assert raw==original

@pytest.mark.parametrize('part',[{'type':'input_image','file_id':'unresolved'},{'type':'input_image','image_url':'data:abc','unknown':{'must':'survive or error'}},{'type':'input_file','file_id':'unresolved'}])
def test_unsupported_parts_are_explicit_errors(part):
 raw=request(part);original=copy.deepcopy(raw)
 with pytest.raises(ValueError):responses.to_chat_body(raw)
 assert raw==original


def test_strict_normalization_keeps_multipart_order_and_original():
 messages=[{'role':'user','content':'first'},{'role':'user','content':[{'type':'text','text':'second'},IMAGE]},{'role':'user','content':'third'}]
 original=copy.deepcopy(messages)
 out=massage.merge_for_alternation(messages)
 assert len(out)==1 and out[0]['role']=='user'
 assert out[0]['content']==[{'type':'text','text':'first'},{'type':'text','text':'\n\n'},{'type':'text','text':'second'},IMAGE,{'type':'text','text':'\n\n'},{'type':'text','text':'third'}]
 assert messages==original


def test_mixed_tool_user_preserves_native_call_attribution_and_role_alternation():
 messages=[{'role':'assistant','content':None,'tool_calls':[{'id':'read','type':'function','function':{'name':'read','arguments':'{}'}}]},
           {'role':'tool','tool_call_id':'read','content':'exact verified result'},
           {'role':'user','content':[IMAGE]}]
 out=massage.merge_for_alternation(messages)
 assert out[0]==messages[0] and out[1]==messages[1] and out[-1]==messages[-1]
 assert out[2]=={'role':'assistant','content':''}
 assert [m['role'] for m in out]==['assistant','tool','assistant','user']


def test_distinct_private_provenance_never_collapses_with_image():
 messages=[{'role':'user','content':[IMAGE],bodykeys.ANNOTATION_SOURCE:bodykeys.AnnotationSource.INVENTORY},
           {'role':'user','content':'Actual task'}]
 out=massage.merge_for_alternation(messages)
 assert out[0]==messages[0] and out[-1]==messages[-1]
 assert out[1]=={'role':'assistant','content':''}


def test_actual_prep_wire_preserves_image_and_strict_alternation(monkeypatch):
 body=responses.to_chat_body(request());body['messages'].insert(0,{'role':'user','content':'Initial task'})
 body[bodykeys.MERGE_TURNS]=True
 up=upstream.Upstream('http://unused.invalid',context_window=8192,capture_rendered=False,engagement_level=0)
 wire=json.loads(up._prep(body,False,Log())[0])
 assert len(wire['messages'])==1 and IMAGE in wire['messages'][0]['content']
 assert bodykeys.MERGE_TURNS not in wire


def test_text_only_metadata_keeps_existing_translation_but_mixed_metadata_errors():
 raw={'model':'fixture','input':[{'role':'assistant','content':[{'type':'output_text','text':'answer','annotations':[]}]}]}
 assert responses.to_chat_body(raw)['messages']==[{'role':'assistant','content':'answer'}]
 mixed=request();mixed['input'][0]['content'][0]['unknown_metadata']='unmapped'
 with pytest.raises(ValueError):responses.to_chat_body(mixed)


def test_json_lookalike_cannot_merge_with_typed_image_provenance():
 messages=[{'role':'user','content':[IMAGE],bodykeys.ANNOTATION_SOURCE:bodykeys.AnnotationSource.INVENTORY},
           {'role':'user','content':'Actual task',bodykeys.ANNOTATION_SOURCE:'inventory'}]
 out=massage.merge_for_alternation(messages)
 assert len(out)==3
 assert out[0][bodykeys.ANNOTATION_SOURCE] is bodykeys.AnnotationSource.INVENTORY
 assert out[-1][bodykeys.ANNOTATION_SOURCE] is messages[-1][bodykeys.ANNOTATION_SOURCE]
