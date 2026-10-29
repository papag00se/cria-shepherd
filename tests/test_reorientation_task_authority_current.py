"""Actual driver/wire task authority, independent of carried-inventory support."""
import copy
import json

import pytest
from cria import assistruntime, loop, tokenratio, upstream, wsview, prompts
from cria.config import Role
from test_generation_driver_policy import setup_driver
from test_localai_tool_template import WRITE
from test_loop import _Rlog

SUMMARY='⟦ctx:continuation⟧ Earlier account: existing.py was built. INSPECT the workspace before doing anything.'
LISTING='Earlier boundary inventory; coverage and freshness unknown:\n  existing.py (13 B)'
CASES=[
 ('negative-task','Do not inspect any files. Make the first requested edit immediately.',None,False,False),
 ('negative-amendment','Inspect the relevant files before editing.','Actually do not inspect; make the edit immediately.',False,False),
 ('positive-inspection','Inspect the relevant files before making changes, then complete the requested edit.',None,True,False),
 ('negative-post-work','Inspect the relevant files before editing.','Actually do not inspect; make the edit immediately.',False,True),
 ('positive-post-work','Do not inspect any files. Make the first requested edit immediately.','Actually inspect the relevant files before making changes.',True,True),
 ('negative-marker','Inspect the relevant files before editing.','⟦ctx:continuation⟧ Actually do not inspect; make the edit immediately.',False,True),
]
@pytest.mark.parametrize('name,task,amendment,allowed,worked',CASES)
def test_current_task_authority_driver_and_wire(tmp_path,monkeypatch,name,task,amendment,allowed,worked):
    root=str(tmp_path)
    (tmp_path/'existing.py').write_text('existing work')
    driver,sess,body=setup_driver()
    driver._ctx.reasoner_role=Role(name='reasoner',backend='local')
    sess.workspace_root=root
    sess.handoff_origin=loop._HandoffOrigin('Earlier account','',False,continuation=SUMMARY)
    body['messages']=[{'role':'user','content':task},{'role':'user','content':SUMMARY}]
    if worked:body['messages'].append({'role':'assistant','content':'Earlier work.'})
    if amendment:body['messages'].append({'role':'user','content':amendment})
    body['tools']=[copy.deepcopy(WRITE)]
    key='sid:current-task-authority'
    driver._store.put(key,sess)
    driver._store.observe_shape_with_ticket(key,loop._history_root(body['messages'])[1],len(body['messages'])+10)
    calls=[];wires=[];answers=[]
    def author(chat,role,system,grounding,log,**kwargs):
        calls.append((system,grounding))
        answer='Inspect relevant files before making changes.' if allowed else 'KEEP_TASK'
        answers.append(answer)
        return answer
    monkeypatch.setattr(loop,'summarize',author)
    monkeypatch.setattr(tokenratio,'record',lambda *a,**kw:None)
    def coder(frame,rlog):
        frame['model']='fixture'
        up=upstream.Upstream('http://unused.invalid',context_window=16000,capture_rendered=False)
        up._props={'chat_template':'fixture'}
        monkeypatch.setattr(up,'_render_prompt',lambda out:json.dumps(out))
        monkeypatch.setattr(up,'_tokenize_prompt',lambda rendered,log:300)
        wires.append(json.loads(up._prep(frame,False,rlog,safety_override=1)[0]))
        return json.dumps(loop._completion_toolcalls([{'id':'next','type':'function','function':{'name':'write_file','arguments':'{"path":"existing.py","content":"work"}'}}])).encode()
    driver._ctx.coder_chat=coder
    token=wsview.bind(wsview.View(root))
    try:
        with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
            result=driver._drive_locked(body,key,None,_Rlog())
    finally:wsview.unbind(token)
    assert len(calls)==1 and len(wires)==1
    text=str(wires[0]['messages'])
    assert task in text and (not amendment or amendment in text)
    steers=[m['content'] for m in wires[0]['messages'] if isinstance(m.get('content'),str) and m['content'].startswith('⟦ctx:steer⟧')]
    if allowed:
        assert steers==[prompts.render('nudge',reason=answers[0])]
    else:assert not steers
    assert result['choices'][0]['message']['tool_calls'][0]['id']=='next'
    if amendment:assert amendment in calls[0][1]


def test_current_source_does_not_grant_history_scope_to_marker_text(monkeypatch):
    from cria import reorientation
    texts=('Task','⟦ctx:continuation⟧ Historical','⟦ctx:continuation⟧ A genuine amendment')
    seen=[]
    def author(request):seen.append(request.grounding);return 'KEEP_TASK'
    result=reorientation.reorient(reorientation.ReorientationInput(True,
      lambda:reorientation.ReorientationFacts(texts,True,'Task',texts[1]),lambda:'Inventory',author,None,_Rlog()))
    assert result.message is None
    records=json.loads(seen[0].split('is_source_owned_historical_continuation]:\n',1)[1].splitlines()[0])
    assert records==[[texts[0],False],[texts[1],True],[texts[2],False]]


@pytest.mark.parametrize('answer',[None,''])
def test_owned_empty_author_keeps_task_without_a_canned_inspection(answer):
    from cria import reorientation
    result=reorientation.reorient(reorientation.ReorientationInput(True,
      lambda:reorientation.ReorientationFacts(('Task',SUMMARY),True,'Task',SUMMARY),
      lambda:LISTING,lambda request:answer,None,_Rlog()))
    assert result.message is None and not result.consumed
