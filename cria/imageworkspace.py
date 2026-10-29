"""Image reads executed by the harness, correlated to privately issued actions.

No workspace file is opened here. Only a configured harness tool contract can
turn a path into an outbound read; returned pixels remain a fresh occurrence.
"""
import copy
import json
import uuid
from dataclasses import dataclass
from . import imagepersist,bodykeys
from .imageprotocol import ImageUnavailable,digest,has_images

@dataclass(frozen=True)
class WorkspaceImageTool:
    name: str
    path_key: str

class ImageWorkspace:
    def __init__(self,contract):
        if type(contract) is not WorkspaceImageTool or not contract.name or not contract.path_key:
            raise ValueError('A source-owned workspace image tool contract is required')
        self.contract=contract

    def _offered(self,tools):
        matches=[t for t in tools or [] if t.get('type')=='function' and
                 (t.get('function') or {}).get('name')==self.contract.name]
        if len(matches)!=1:raise ImageUnavailable('Fresh workspace image read tool is unavailable or ambiguous')
        schema=matches[0]['function'].get('parameters') or {}
        if (schema.get('type')!='object' or
            (schema.get('properties',{}).get(self.contract.path_key) or {}).get('type')!='string' or
            any(k!=self.contract.path_key for k in schema.get('required',[]))):
            raise ImageUnavailable('Harness image read tool cannot accept a path-only read')
        return matches[0]

    def supports(self,tools):
        try:self._offered(tools)
        except ImageUnavailable:return False
        return True

    def _state(self,session):
        path=session._root/'workspace-reads.json'
        if not path.exists():return {'generation':session._generation,'reads':{}}
        try:state=imagepersist._read(path)
        except (OSError,ValueError) as exc:
            raise ImageUnavailable('Workspace image read provenance is unavailable') from exc
        if state.get('generation')!=session._generation or not isinstance(state.get('reads'),dict):
            raise ImageUnavailable('Workspace image read provenance is unavailable')
        return state

    def _save(self,session,state):
        imagepersist._write(session._root,'workspace-reads.json',state)

    def register(self,session,completion,tools,*,origin_ref=None):
        """Persist an actual outgoing image read before returning it to the harness."""
        choices=completion.get('choices') or []
        if len(choices)!=1:return completion
        choice=choices[0];message=choice.get('message') or {}
        calls=message.get('tool_calls') or []
        relevant=[c for c in calls if (c.get('function') or {}).get('name')==self.contract.name]
        if not relevant:return completion
        if choice.get('finish_reason')!='tool_calls' or message.get('role')!='assistant':
            raise ImageUnavailable('Workspace image read has no completed coder tool action')
        self._offered(tools)
        out=copy.deepcopy(completion)
        with session._lock:
            session._active();state=self._state(session)
            for call in out['choices'][0]['message']['tool_calls']:
                if (call.get('function') or {}).get('name')!=self.contract.name:continue
                try:args=json.loads(call['function']['arguments'])
                except (TypeError,ValueError,KeyError) as exc:
                    raise ImageUnavailable('Workspace image read arguments are invalid') from exc
                if (not isinstance(args,dict) or set(args)!={self.contract.path_key} or
                        not isinstance(args[self.contract.path_key],str) or not args[self.contract.path_key]):
                    raise ImageUnavailable('Workspace image read needs an exact path-only argument')
                call['id']='imgread_'+uuid.uuid4().hex
                state['reads'][call['id']]={'call':copy.deepcopy(call),'path':args[self.contract.path_key],
                    'origin_ref':origin_ref,'result_digest':None}
            self._save(session,state)
        return out

    def request(self,session,ref,path,tools,model):
        self._offered(tools)
        from .imagestore import FreshWorkspaceRead
        source=session.reinspect(ref)
        if not isinstance(source,FreshWorkspaceRead) or source.path!=path:
            raise ImageUnavailable('Workspace reinspection source changed')
        completion={'object':'chat.completion','model':model,'choices':[{'index':0,'finish_reason':'tool_calls',
            'message':{'role':'assistant','content':None,'tool_calls':[{'type':'function','id':'unpublished',
            'function':{'name':self.contract.name,'arguments':json.dumps({self.contract.path_key:path},ensure_ascii=False)}}]}}]}
        return self.register(session,completion,tools,origin_ref=ref)

    def resolve(self,session,messages):
        """Bind actual received result packets only to our own exact issued read."""
        sources={}
        with session._lock:
            session._active();state=self._state(session);changed=False
            for call_id,record in state['reads'].items():
                issuers=[(i,c) for i,m in enumerate(messages) if m.get('role')=='assistant'
                         for c in m.get('tool_calls') or [] if c.get('id')==call_id]
                results=[(i,m) for i,m in enumerate(messages) if m.get('role')=='tool' and m.get('tool_call_id')==call_id]
                if not results:continue
                if len(issuers)!=1 or len(results)!=1 or issuers[0][0]>=results[0][0] or issuers[0][1]!=record['call']:
                    raise ImageUnavailable('Workspace image read correlation changed or is ambiguous')
                i,result=results[0]
                if not has_images(result):raise ImageUnavailable('Harness image read returned no supported image; original retained')
                fingerprint=digest({k:v for k,v in result.items() if k not in bodykeys.ALL})
                if record['result_digest'] not in (None,fingerprint):
                    raise ImageUnavailable('Previously received workspace image result changed; request a fresh read')
                if record['result_digest'] is None:record['result_digest']=fingerprint;changed=True
                for j,part in enumerate(result['content']):
                    if isinstance(part,dict) and part.get('type')=='image_url':sources[(i,j)]=record['path']
            for i,message in enumerate(messages):
                if message.get('role')=='tool' and has_images(message):
                    if any((i,j) not in sources for j,p in enumerate(message['content'])
                           if isinstance(p,dict) and p.get('type')=='image_url'):
                        raise ImageUnavailable('Image tool result has no registered harness read provenance')
            if changed:self._save(session,state)
        return sources
