"""Image reads executed by the harness, correlated to privately issued actions.

No workspace file is opened here. Only a configured harness tool contract can
turn a path into an outbound read; returned pixels remain a fresh occurrence.
"""
import copy
import json
import os
import uuid
from dataclasses import dataclass
from . import imagepersist,bodykeys
from .imageprotocol import ImageUnavailable,digest,has_images

LEGACY_NAME='workspace-reads.json'
LOG_NAME='workspace-reads.log'


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

    # Provenance is an append-only log (`workspace-reads.log`, one JSON line per event: a registered read, or the digest of the
    # first result received for it) kept in memory per session and re-read only if the file is not the size this process left.
    # An earlier release wrote one whole `workspace-reads.json`; it is still read, as the base, and never rewritten.
    def _load(self,session):
        reads={}
        legacy=session._root/LEGACY_NAME
        if legacy.exists():
            try:state=imagepersist._read(legacy)
            except (OSError,ValueError) as exc:
                raise ImageUnavailable('Workspace image read provenance is unavailable') from exc
            if not isinstance(state,dict) or state.get('generation')!=session._generation or not isinstance(state.get('reads'),dict):
                raise ImageUnavailable('Workspace image read provenance is unavailable')
            reads=state['reads']
        good=size=0
        try:
            fd=os.open(session._root/LOG_NAME,os.O_RDONLY|os.O_NOFOLLOW)
        except FileNotFoundError:fd=None
        except OSError as exc:raise ImageUnavailable('Workspace image read provenance is unavailable') from exc
        if fd is not None:
            with os.fdopen(fd,'rb') as source:data=source.read()
            size=len(data)
            for line in data.split(b'\n')[:-1]:   # an unterminated last line was never acknowledged to a caller: dropped
                try:event=json.loads(line)
                except ValueError as exc:raise ImageUnavailable('Workspace image read provenance is unavailable') from exc
                if not isinstance(event,dict) or event.get('generation')!=session._generation or not isinstance(event.get('id'),str):
                    raise ImageUnavailable('Workspace image read provenance is unavailable')
                if 'read' in event:reads[event['id']]=event['read']
                elif event.get('id') in reads and 'digest' in event:reads[event['id']]['result_digest']=event['digest']
                else:raise ImageUnavailable('Workspace image read provenance is unavailable')
                good+=len(line)+1
        return {'reads':reads,'size':size,'good':good}

    def _state(self,session):
        cache=getattr(session,'_workspace_reads',None)
        try:size=(session._root/LOG_NAME).lstat().st_size
        except FileNotFoundError:size=0
        except OSError as exc:raise ImageUnavailable('Workspace image read provenance is unavailable') from exc
        if cache is None or cache['size']!=size or cache['generation']!=session._generation:
            cache=self._load(session);cache['generation']=session._generation
            session._workspace_reads=cache
        return cache

    def _append(self,session,state,events):
        """Make `events` durable (one write), then apply them to the in-memory state."""
        lines=''.join(json.dumps({'generation':session._generation,**e},ensure_ascii=False,allow_nan=False)+'\n' for e in events).encode()
        path=session._root/LOG_NAME;fresh=not path.exists()
        fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            if state['good']!=state['size']:os.ftruncate(fd,state['good'])   # drop the torn tail of a crashed append
            os.write(fd,lines);os.fsync(fd)
            state['size']=state['good']=os.fstat(fd).st_size
        finally:os.close(fd)
        if fresh:imagepersist._sync(session._root)
        for e in events:
            if 'read' in e:state['reads'][e['id']]=e['read']
            else:state['reads'][e['id']]['result_digest']=e['digest']

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
            session._active();state=self._state(session);events=[]
            for call in out['choices'][0]['message']['tool_calls']:
                if (call.get('function') or {}).get('name')!=self.contract.name:continue
                try:args=json.loads(call['function']['arguments'])
                except (TypeError,ValueError,KeyError) as exc:
                    raise ImageUnavailable('Workspace image read arguments are invalid') from exc
                if (not isinstance(args,dict) or set(args)!={self.contract.path_key} or
                        not isinstance(args[self.contract.path_key],str) or not args[self.contract.path_key]):
                    raise ImageUnavailable('Workspace image read needs an exact path-only argument')
                call['id']='imgread_'+uuid.uuid4().hex
                events.append({'id':call['id'],'read':{'call':copy.deepcopy(call),'path':args[self.contract.path_key],
                    'origin_ref':origin_ref,'result_digest':None}})
            self._append(session,state,events)
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
            session._active();state=self._state(session);reads=state['reads'];events=[];seen={}
            issuers={};results={}   # one pass over the messages, never a pass per registered read
            for i,m in enumerate(messages):
                if m.get('role')=='assistant':
                    for c in m.get('tool_calls') or []:
                        if c.get('id') in reads:issuers.setdefault(c['id'],[]).append((i,c))
                elif m.get('role')=='tool' and m.get('tool_call_id') in reads:results.setdefault(m['tool_call_id'],[]).append((i,m))
            for call_id,found in results.items():
                record=reads[call_id];calls=issuers.get(call_id,[])
                if len(calls)!=1 or len(found)!=1 or calls[0][0]>=found[0][0] or calls[0][1]!=record['call']:
                    raise ImageUnavailable('Workspace image read correlation changed or is ambiguous')
                i,result=found[0]
                if not has_images(result):continue  # the harness's own words (a refusal, a missing file) reach the coder as written
                fingerprint=digest({k:v for k,v in result.items() if k not in bodykeys.ALL})
                if record['result_digest'] not in (None,fingerprint):
                    raise ImageUnavailable('Previously received workspace image result changed; request a fresh read')
                if record['result_digest'] is None:events.append({'id':call_id,'digest':fingerprint})
                for j,part in enumerate(result['content']):
                    if isinstance(part,dict) and part.get('type')=='image_url':sources[(i,j)]=record['path']
            for i,message in enumerate(messages):
                if message.get('role')=='tool' and has_images(message):
                    if any((i,j) not in sources for j,p in enumerate(message['content'])
                           if isinstance(p,dict) and p.get('type')=='image_url'):
                        raise ImageUnavailable('Image tool result has no registered harness read provenance')
            if events:self._append(session,state,events)
        return sources
