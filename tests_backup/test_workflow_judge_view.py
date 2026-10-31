"""The completion judge and critics read an observed image as its labelled observation, never as pixels or nothing."""
import copy
from types import SimpleNamespace
from cria import loop
from cria.imagestore import ImageStore
from cria.imageprotocol import CoderRoute
from cria.imageworkflow import SourceImageContext,current
from test_workflow_store import IMAGE,TASK,delivered

class Log:
 def __init__(self):self.events=[]
 def emit(self,name,**kw):self.events.append((name,kw))

def history():
 call={'id':'imgread_1','type':'function','function':{'name':'view_image','arguments':'{"path":"./note.png"}'}}
 return [{'role':'user','content':TASK},{'role':'assistant','content':None,'tool_calls':[call]},
         {'role':'tool','tool_call_id':'imgread_1','content':[copy.deepcopy(IMAGE)]}]

def observed_context(tmp_path,messages):
 session=ImageStore(tmp_path/'private',close_authority=object()).session('judge')
 route=CoderRoute(object(),'actual-selected-vision','sig',True);session.select_route(route)
 prepared=session.prepare(messages,TASK,workspace_sources={(2,0):'./note.png'});ref=prepared.bindings[0].ref
 attempt=session.begin(ref,TASK,route,{'model':route.model})
 session.complete(attempt,delivered(attempt,route))
 return SourceImageContext(SimpleNamespace(),session,prepared,TASK)

def test_work_log_shows_the_observation_of_an_image_tool_result_not_pixels_or_nothing(tmp_path):
 messages=history()
 token=current.set(observed_context(tmp_path,messages))
 try:log=loop._work_log(messages,rlog=Log())
 finally:current.reset(token)
 assert 'Historical coder observation' in log and 'Save\nCancel' in log
 assert 'data:image' not in log and 'AAAA' not in log

def test_work_log_without_an_image_context_never_renders_pixels():
 log=loop._work_log(history(),rlog=Log())
 assert 'data:image' not in log and 'AAAA' not in log
