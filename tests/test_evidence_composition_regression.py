"""Real producer/reader boundary: source custody and one existing floor."""
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from cria import assistruntime,config,evidencesummary as es,livingplan,loop,stepreview as sp,bodykeys
from cria.upstream import Upstream
from test_optional_step_policy import make

RAW='$ exec_command {"cmd":"emit-record"}\n[tool call id: "large"]\n[tool result call id: "large"]\n  -> Process exited with code 0\nOutput:\n'+'X'*60000
class Log:
 phase='';session='composition'
 def __init__(self):self.events=[]
 def emit(self,event,**fields):self.events.append((event,fields))

def reader(window,content):
 log=Log();calls=[];up=Upstream('https://offline.invalid',api_key='unused',context_window=window,capture_rendered=False)
 def chat(body,rlog):
  wire,_,_=up._prep({**body,'model':'offline'},False,rlog);calls.append(json.loads(wire))
  return json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':content}}]}).encode()
 return log,calls,chat

@pytest.mark.parametrize('window',[16384,49152])
def test_real_step_policy_dispatches_without_a_writer_and_preserves_records(window):
 log,calls,chat=reader(window,'{"done": false, "reason": "", "proposed_fix": ""}')
 role=config.Role(name='reasoner',backend='offline',reasoning='on')
 driver=loop.Loop.__new__(loop.Loop);driver._ctx=SimpleNamespace(reasoner_chat=chat,reasoner_role=role)
 source,_,records,_,diagnoses,_=make([])
 def read(request):
  verdict,raw=driver._verdict(request.system,request.user,log,reasoning_off=request.reasoning_off,
      workspace_root=request.workspace_root,
      **({"evidence_blocks":list(request.evidence_blocks)} if hasattr(request,"evidence_blocks") else {}))
  return sp.StepAnswer(verdict,raw)
 source=replace(source,step='Inspect the emitted record.',evidence=RAW,log=log,services=replace(source.services,read=read))
 with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
  result=sp.review_step(source)
 assert result.status is sp.StepStatus.REJECTED and len(calls)==1
 text=''.join(m.get('content','') or '' for m in calls[0]['messages'])
 assert calls[0]['messages'][-1]['content'].endswith('Inspect the emitted record.')
 assert RAW in records[0].user and diagnoses[0].action_log==RAW
 if window==49152: assert RAW in text
 else: assert '⟦ctx:compacted⟧' in text
 assert 'cria_annotation_source' not in json.dumps(calls)

@pytest.mark.parametrize('window',[16384,49152])
def test_real_legacy_tail_consumer_dispatches_empty_pending_not_task_release(window):
 log,calls,chat=reader(window,'[]')
 role=config.Role(name='reasoner',backend='offline',reasoning='on')
 with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
  result=loop.reassess_remaining(chat,role,'Inspect record and write report.','- Inspect record',
        '- Write report',RAW,log)
 assert result==[] and len(calls)==1
 text=''.join(m.get('content','') or '' for m in calls[0]['messages'])
 final=calls[0]['messages'][-1]['content']
 assert 'Inspect record and write report.' in final and '- Inspect record' in final and '- Write report' in final
 if window==49152: assert RAW in text
 else: assert '⟦ctx:compacted⟧' in text
 assert 'cria_annotation_source' not in json.dumps(calls)

def test_one_lossless_line_splitter_preserves_long_lines_blank_bytes_and_unicode():
 raw='\n雪\n'+'x'*20000+'\n\nlast\n'
 assert ''.join(es.blocks(raw))==raw
 assert loop._evidence_blocks(raw)==es.blocks(raw)

@pytest.mark.parametrize('window',[16384,49152])
def test_legitimate_step_approval_keeps_exact_successful_tool_evidence(window):
 raw='$ exec_command {"cmd":"check"}\n[tool call id: "positive"]\n[tool result call id: "positive"]\n  -> Process exited with code 0\nOutput:\n3 passed\n'
 log,calls,chat=reader(window,'{"done": true, "reason": "3 passed", "proposed_fix": ""}')
 role=config.Role(name='reasoner',backend='offline',reasoning='on')
 source,_,records,_,_,_=make([])
 def read(request):
  verdict,reply=loop._critic_verdict(request.system,request.user,chat,role,log,reasoning_off=request.reasoning_off,
      **({'evidence_blocks':list(request.evidence_blocks)} if hasattr(request,'evidence_blocks') else {}))
  return sp.StepAnswer(verdict,reply)
 source=replace(source,step='Run the check.',evidence=raw,log=log,services=replace(source.services,read=read))
 with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
  result=sp.review_step(source)
 assert result.status is sp.StepStatus.APPROVED and result.effect.action is sp.StepAction.ADVANCE
 assert raw in ''.join(m.get('content','') or '' for m in calls[0]['messages'])
 assert raw in records[0].user
 assert calls[0]['messages'][-1]['content'].endswith('Run the check.')
