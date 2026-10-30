"""Private session image retention and correlated coder-observation lifecycle.

No model calls, workspace reads, source classification or tool executors live here.
The routing/wire owner supplies actual provider/model/terminal delivery facts.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from . import bodykeys,prompts,imagepersist
from .imageprotocol import CoderRoute,Delivery,ImageUnavailable,digest,parse_observation,observation_request,has_images

@dataclass(frozen=True)
class Binding:
    ref: str
    message: int
    part: int
    source_digest: str

@dataclass(frozen=True)
class PreparedImages:
    token: object
    task: str
    messages: list
    bindings: tuple[Binding,...]

@dataclass(frozen=True)
class Attempt:
    token: object
    ref: str
    nonce: str
    source_digest: str
    task_scope: str
    route: CoderRoute
    request: dict

def _remote(part):
    """True when the retained image part is an http(s) URL reference rather than inline bytes."""
    value=part.get('image_url') if isinstance(part,dict) else None
    url=value.get('url') if isinstance(value,dict) else value
    return isinstance(url,str) and url.lower().startswith(('http://','https://'))

@dataclass(frozen=True)
class FreshWorkspaceRead:
    ref: str
    path: str

@dataclass
class _Record:
    ref: str
    source_digest: str
    filename: Path
    task_scope: str
    workspace_path: str | None = None
    observation: object = None
    observed_model: str = ''
    pending: str | None = None


class ImageSession:
    def __init__(self,root,session_key,*,close_authority,clock=time.monotonic):
        self._lock=threading.RLock();self._token=object();self._closed=False;self._retired=False;self._confirmed_at=None;self._cleanup_complete=False;self._authority=close_authority
        self._root=Path(tempfile.mkdtemp(prefix='image-session-',dir=root));os.chmod(self._root,0o700)
        self._generation=uuid.uuid4().hex;self._close_seal=None;self._cleanup_sealed=False;self._confirmed_wall=None;self._recovered_observations=set()
        self._key=session_key;self._records={};self._occurrences={};self._route=None;self._leases=set();self._attempts={}
        self._clock=clock;self.last_used=clock()
        self._hold=imagepersist.Hold(self._root)
        self._save()
        imagepersist.create_marker(self._root,self._generation)

    def _state(self):
        return {'version':1,'generation':self._generation,'key':self._key,
                'retired':self._retired,'close_seal':self._close_seal,
                'confirmed_wall':self._confirmed_wall,'cleanup_sealed':self._cleanup_sealed,
                'records':[{'ref':r.ref,'source_digest':r.source_digest,'task_scope':r.task_scope,
                    'workspace_path':r.workspace_path,'observed_model':r.observed_model,
                    'observation':None if r.observation is None else {
                        'extracted_text':r.observation.extracted_text,'description':r.observation.description,
                        'uncertainty':r.observation.uncertainty}} for r in self._records.values()],
                'occurrences':[[prefix,index,ref] for (prefix,index),ref in self._occurrences.items()]}

    def _save(self):
        imagepersist.write_state(self._root,self._state())

    def retention_handle(self):
        # Identity for source-owned recovery, not permission to close or delete.
        return {'owner':'session-images','directory':self._root.name,'generation':self._generation}

    @classmethod
    def restore(cls,root,handle,*,close_authority,clock,recovered_leases):
        imagepersist.check_marker(root,handle['generation'])
        hold=imagepersist.Hold(root)
        state=imagepersist.read_state(root)
        if state.get('generation')!=handle['generation']:
            raise ImageUnavailable('Image session generation does not match recovery handle')
        session=object.__new__(cls)
        session._lock=threading.RLock();session._token=object();session._closed=False;session._hold=hold
        session._retired=state.get('retired') is True;session._cleanup_complete=False
        session._root=Path(root);session._key=state['key'];session._generation=state['generation']
        session._authority=close_authority;session._close_seal=state.get('close_seal')
        session._cleanup_sealed=state.get('cleanup_sealed') is True
        session._confirmed_wall=state.get('confirmed_wall')
        session._confirmed_at=(None if session._close_seal is None else
            clock()-max(0,time.time()-session._confirmed_wall))
        session._records={};session._occurrences={};session._route=None
        session._clock=clock;session.last_used=clock();session._attempts={};session._leases=set()
        session._recovered_observations=set()
        for lease_id,kind in recovered_leases:
            if not isinstance(lease_id,str) or not lease_id or lease_id in session._leases:
                raise ImageUnavailable('Invalid recovered image lease identity')
            session._leases.add(lease_id)
            if kind=='image-observation':session._recovered_observations.add(lease_id)
        for data in state['records']:
            ref=data['ref']
            if not isinstance(ref,str) or re.fullmatch(r'img_[0-9a-f]{32}',ref) is None:
                raise ImageUnavailable('Invalid retained image reference')
            record=_Record(ref,data['source_digest'],session._root/(ref+'.json'),data['task_scope'],data['workspace_path'])
            value=data['observation']
            if value is not None:
                from .imageprotocol import Observation
                if set(value)!={'extracted_text','description','uncertainty'} or any(not isinstance(v,str) for v in value.values()):
                    raise ImageUnavailable('Invalid retained image observation')
                record.observation=Observation(**value);record.observed_model=data['observed_model']
            session._load(record);session._records[ref]=record
        for prefix,index,ref in state['occurrences']:
            if ref not in session._records or not isinstance(index,int) or index<0:
                raise ImageUnavailable('Invalid retained image occurrence')
            session._occurrences[(prefix,index)]=ref
        return session

    def recovered_lease(self,lease_id):
        with self._lock:
            if lease_id not in self._leases or not isinstance(lease_id,str):
                raise ImageUnavailable('Recovered image lease is unavailable')
            return ImageLease(self,lease_id)

    def _active(self):
        if self._closed or self._retired or self._confirmed_at is not None:raise ImageUnavailable('Image session is closed, closing or replaced')
        self.last_used=self._clock()

    def _record(self,ref):
        self._active()
        try:return self._records[ref]
        except KeyError as exc:raise ImageUnavailable('Image reference is unavailable in this session') from exc

    def _load(self,record):
        try:
            fd=os.open(record.filename,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd) as retained:part=json.load(retained)
        except (OSError,ValueError) as exc:raise ImageUnavailable('Retained original image is unavailable') from exc
        if digest(part)!=record.source_digest:raise ImageUnavailable('Retained original image no longer matches its source')
        return part

    def _retain(self,part,task_scope,path=None):
        ref='img_'+uuid.uuid4().hex
        filename=self._root/(ref+'.json')
        fd=os.open(filename,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w') as out:
                json.dump(part,out,ensure_ascii=False,allow_nan=False);out.flush();os.fsync(out.fileno())
        except BaseException:
            filename.unlink(missing_ok=True);raise
        record=_Record(ref,digest(part),filename,task_scope,path)
        self._records[ref]=record
        return record

    def select_route(self,route):
        """Call with actual selected/applied coder identity, including normal runs."""
        with self._lock:
            self._active();self._route=route

    def prepare(self,messages,task,*,workspace_sources=None):
        """Capture source occurrences after private-history projection, before reducers.

        workspace_sources must be actual harness provenance, never path-shaped text.
        All unrelated message content/private fields stay structurally identical.
        """
        with self._lock:
            self._active();bindings=[];prefix=hashlib.sha256();task_scope=digest(task)
            sources=workspace_sources or {}
            for i,message in enumerate(messages):
                public={k:v for k,v in message.items() if k not in bodykeys.ALL}
                prefix.update(json.dumps(public,sort_keys=True,ensure_ascii=False,allow_nan=False).encode())
                content=message.get('content')
                if message.get('role') not in ('user','tool') or not isinstance(content,list):continue
                for j,part in enumerate(content):
                    if not isinstance(part,dict) or part.get('type')!='image_url':continue
                    occurrence=(prefix.hexdigest(),j)
                    record=self._records.get(self._occurrences.get(occurrence))
                    source_path=sources.get((i,j))
                    if message.get('role')=='tool' and not source_path:
                        raise ImageUnavailable('Image tool result requires registered harness source provenance')
                    if record is None:
                        record=self._retain(part,task_scope,source_path);self._occurrences[occurrence]=record.ref
                    if record.workspace_path!=source_path:raise ImageUnavailable('Image source provenance changed')
                    if record.task_scope!=task_scope:
                        record.task_scope=task_scope;record.pending=None;record.observation=None
                    bindings.append(Binding(record.ref,i,j,record.source_digest))
            self._save()
            snapshot=[{k:(v if k in bodykeys.ALL else copy.deepcopy(v)) for k,v in m.items()} for m in messages]
            return PreparedImages(self._token,task,snapshot,tuple(bindings))

    def render(self,prepared):
        with self._lock:
            self._active()
            if prepared.token is not self._token:raise ImageUnavailable('Image preparation belongs to a different session')
            out=[{k:(v if k in bodykeys.ALL else copy.deepcopy(v)) for k,v in m.items()} for m in prepared.messages]
            for binding in prepared.bindings:
                record=self._record(binding.ref)
                part=out[binding.message]['content'][binding.part]
                if digest(part)!=binding.source_digest or record.source_digest!=binding.source_digest or record.task_scope!=digest(prepared.task):
                    raise ImageUnavailable('Image source occurrence or task changed during preparation')
                part=self._load(record)  # a published reference must still have its retained source
                if record.observation is None:continue
                obs=record.observation
                source=(prompts.render('image_source_workspace',path=record.workspace_path) if record.workspace_path
                        else prompts.load('image_source_remote' if _remote(part) else 'image_source_attachment'))
                text=prompts.render('image_observation',ref=record.ref,model=record.observed_model,
                     task_scope=record.task_scope,extracted=obs.extracted_text,description=obs.description,
                     uncertainty=obs.uncertainty,source=source)
                out[binding.message]['content'][binding.part]={'type':'text','text':text}
            return out

    def pending(self,prepared):
        with self._lock:
            self.render(prepared)  # validates source, scope and retained bytes
            return tuple(binding.ref for binding in prepared.bindings
                         if self._records[binding.ref].observation is None)

    def project(self,prepared,framed_messages):
        """Outbound view only, AFTER raw task/root identity and frame construction.

        Exact source packets map in original occurrence order. Missing/ambiguous
        copies fail explicitly; private provenance and unrelated frame data survive.
        """
        with self._lock:
            viewed=self.render(prepared)
            def key(message):
                return digest({k:v for k,v in message.items() if k not in bodykeys.ALL})
            originals={}
            for binding in prepared.bindings:
                originals.setdefault(binding.message,[]).append(binding)
            groups={}
            for source_index in originals:
                groups.setdefault(key(prepared.messages[source_index]),[]).append(source_index)
            out=list(framed_messages)
            for signature,source_indices in groups.items():
                candidates=[i for i,m in enumerate(framed_messages)
                            if isinstance(m,dict) and has_images(m) and key(m)==signature]
                if len(candidates)!=len(source_indices):
                    raise ImageUnavailable('Image source occurrence is missing or ambiguous after coder preparation')
                for source_index,target_index in zip(source_indices,candidates):
                    current=framed_messages[target_index]
                    for binding in originals[source_index]:
                        replacement=viewed[source_index]['content'][binding.part]
                        if replacement==prepared.messages[source_index]['content'][binding.part]:continue
                        if out[target_index] is current:
                            out[target_index]={**current,'content':list(current['content'])}
                        out[target_index]['content'][binding.part]=replacement
            return out

    def begin(self,ref,task,route,applied_body):
        with self._lock:
            record=self._record(ref)
            if record.task_scope!=digest(task):raise ImageUnavailable('Image task scope changed')
            if self._route is None or not self._route.same(route):raise ImageUnavailable('Coder route is no longer current')
            part=self._load(record)
            request=observation_request(applied_body,route,task,part)
            nonce=uuid.uuid4().hex;record.pending=nonce
            attempt=Attempt(self._token,ref,nonce,record.source_digest,record.task_scope,route,request)
            self._attempts[nonce]=attempt;self._leases.add(nonce)
            return attempt

    def complete(self,attempt,delivery):
        with self._lock:
            record=self._record(attempt.ref)
            if (attempt.token is not self._token or record.pending!=attempt.nonce or
                record.source_digest!=attempt.source_digest or record.task_scope!=attempt.task_scope or
                self._route is None or not self._route.same(attempt.route)):
                raise ImageUnavailable('Image observation is stale; original remains pending')
            if (not isinstance(delivery,Delivery) or delivery.attempt!=attempt.nonce or
                delivery.provider is not attempt.route.provider or delivery.model!=attempt.route.model or
                delivery.role_signature!=attempt.route.role_signature or delivery.image_digest!=attempt.source_digest):
                raise ImageUnavailable('Image observation delivery did not match actual coder route/source')
            observation=parse_observation(delivery.completion,terminal_complete=delivery.terminal_complete)
            previous=(record.observation,record.observed_model,record.pending)
            record.observation=observation;record.observed_model=delivery.model;record.pending=None
            try:self._save()
            except Exception:
                record.observation,record.observed_model,record.pending=previous
                raise
            self._attempts.pop(attempt.nonce,None);self._leases.discard(attempt.nonce)
            return observation

    def reinspect(self,ref):
        with self._lock:
            record=self._record(ref)
            if record.workspace_path:return FreshWorkspaceRead(ref,record.workspace_path)
            return self._load(record)

    def retain_fresh_workspace_read(self,old_ref,part,task,*,event_id):
        """Caller supplies a fresh harness image result; never opens the workspace path."""
        with self._lock:
            old=self._record(old_ref)
            if not old.workspace_path or not event_id:raise ImageUnavailable('Fresh harness read provenance is required')
            fresh=self._retain(part,digest(task),old.workspace_path)
            self._save()
            return fresh.ref

    def acquire(self):
        """Admission must occur under the shared image/multipart lifecycle fence."""
        with self._lock:
            self._active();token=object();self._leases.add(token)
            return ImageLease(self,token)

    @property
    def pending_leases(self):
        with self._lock:return len(self._leases)

    @property
    def pending_observations(self):
        with self._lock:return len(self._attempts)+len(self._recovered_observations)

    @property
    def ready_to_close(self):
        with self._lock:return self._confirmed_at is not None and not self._leases

    def cancel(self,attempt):
        with self._lock:
            if attempt.token is not self._token:return
            self._attempts.pop(attempt.nonce,None);self._leases.discard(attempt.nonce)
            record=self._records.get(attempt.ref)
            if record is not None and record.pending==attempt.nonce:record.pending=None

    def retire(self):
        """Replacement fences publication; it is NOT proof of resource closure."""
        with self._lock:
            self._retired=True;self._save()

    def confirm_close(self,authority):
        """Only the source-owned shared lifecycle may confirm closure."""
        with self._lock:
            if authority is not self._authority:raise ImageUnavailable('Image closure authority does not match')
            if self._confirmed_at is None:
                self._confirmed_at=self._clock();self._confirmed_wall=time.time();self._close_seal=uuid.uuid4().hex
                try:self._save()
                except Exception:
                    self._confirmed_at=None;self._confirmed_wall=None;self._close_seal=None
                    raise

    def cleanup_descriptor(self):
        """For the trusted durable retry queue, after shared lease-zero fencing."""
        with self._lock:
            if not self.ready_to_close:raise ImageUnavailable('Image resources are not confirmed closed and drained')
            self._cleanup_sealed=True;self._save()
            imagepersist.seal_marker(self._root,self._generation,self._close_seal)
            return {**self.retention_handle(),'closed':self._close_seal}

    def close(self):
        with self._lock:
            if not self.ready_to_close:raise ImageUnavailable('Image resources still have live leases or no confirmed close')
            if self._cleanup_complete:return
            if not self._cleanup_sealed:raise ImageUnavailable('Image cleanup requires its owner-issued durable queue descriptor')
            self._closed=True
            imagepersist.check_marker(self._root,self._generation,self._close_seal)
            try:shutil.rmtree(self._root)
            except FileNotFoundError:pass
            # If deletion raises, retain state for the explicit retry queue.
            imagepersist.remove_marker(self._root,self._generation,self._close_seal)
            self._hold.close()
            self._cleanup_complete=True;self._records.clear();self._occurrences.clear()


class ImageLease:
    def __init__(self,session,token):self._session=session;self._token=token
    def release(self):
        with self._session._lock:
            self._session._leases.discard(self._token);self._session._recovered_observations.discard(self._token)
    def __enter__(self):return self
    def __exit__(self,*args):self.release()


class ImageStore:
    def __init__(self,private_root,*,close_authority,clock=time.monotonic):
        root=Path(private_root);root.mkdir(mode=0o700,parents=True,exist_ok=True)
        info=root.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o700 or info.st_uid!=os.getuid():
            raise ImageUnavailable('Image retention requires an owned private directory')
        if close_authority is None:raise ImageUnavailable('Image lifecycle requires a producer close authority')
        self._root=root;self._clock=clock;self._lock=threading.RLock();self._sessions={};self._all=set();self._authority=close_authority

    def session(self,key,*,replace=False):
        if not key:raise ImageUnavailable('A stable session identity is required for image retention')
        with self._lock:
            previous=self._sessions.get(key)
            if previous is not None and not replace:return previous
            if previous is not None:previous.retire()
            session=ImageSession(self._root,key,close_authority=self._authority,clock=self._clock)
            self._sessions[key]=session;self._all.add(session)
            return session

    def restore_session(self,handle,*,recovered_leases):
        """Shared fence supplies journal-recovered leases before admitting traffic."""
        with self._lock:
            path=self._handle_path(handle)
            try:
                session=ImageSession.restore(path,handle,close_authority=self._authority,
                           clock=self._clock,recovered_leases=recovered_leases)
            except ImageUnavailable:raise
            except (OSError,ValueError,KeyError,TypeError) as exc:
                raise ImageUnavailable('Retained image recovery is incomplete; source images were not discarded') from exc
            existing=self._sessions.get(session._key)
            if existing is not None:
                raise ImageUnavailable('Image resource identity is already active; use its exact handle')
            self._sessions[session._key]=session;self._all.add(session)
            return session

    def _handle_path(self,handle):
        if (not isinstance(handle,dict) or set(handle)!={'owner','directory','generation'} or
            handle['owner']!='session-images' or not isinstance(handle['directory'],str) or
            re.fullmatch(r'image-session-[A-Za-z0-9_-]+',handle['directory']) is None or
            not isinstance(handle['generation'],str) or re.fullmatch(r'[0-9a-f]{32}',handle['generation']) is None):
            raise ImageUnavailable('Invalid owned image retention handle')
        path=self._root/handle['directory']
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o700 or info.st_uid!=os.getuid():
            raise ImageUnavailable('Image retention target is not an owned private session directory')
        return path

    def release(self,session):
        """Exact-instance cleanup only; LRU/drop is not closure authority."""
        with self._lock:
            if session not in self._all:
                if session._cleanup_complete:return
                raise ImageUnavailable('Image session is not owned by this store')
            if not session.ready_to_close:raise ImageUnavailable('Image session is not confirmed closed and drained')
            if self._sessions.get(session._key) is session:self._sessions.pop(session._key)
            session.close();self._all.discard(session)

    def expire_closed(self,session,*,ttl_seconds):
        """Called under the shared fence, never expires a live/LRU entry."""
        if ttl_seconds<0:raise ValueError('ttl_seconds must be nonnegative')
        with self._lock,session._lock:
            if (not session.ready_to_close or self._clock()-session._confirmed_at<ttl_seconds):return False
            self.release(session);return True

    def retry_closed(self,descriptor):
        """Trusted durable queue only; descriptor is never a client/API field."""
        if not isinstance(descriptor,dict) or set(descriptor)!={'owner','directory','generation','closed'}:
            raise ImageUnavailable('Invalid image cleanup descriptor')
        handle={k:v for k,v in descriptor.items() if k!='closed'}
        with self._lock:
            for session in self._all:
                if session._root.name==handle.get('directory'):
                    if (session.retention_handle()!=handle or session._close_seal!=descriptor['closed']):
                        raise ImageUnavailable('Image cleanup descriptor has a stale generation or seal')
                    self.release(session);return
            # Generation marker is outside the deletion target, surviving a partial rmtree.
            name=handle.get('directory');generation=handle.get('generation')
            if (handle.get('owner')!='session-images' or not isinstance(name,str) or
                    re.fullmatch(r'image-session-[A-Za-z0-9_-]+',name) is None or
                    not isinstance(generation,str) or re.fullmatch(r'[0-9a-f]{32}',generation) is None or
                    not isinstance(descriptor['closed'],str) or not descriptor['closed']):
                raise ImageUnavailable('Invalid closed image generation descriptor')
            path=self._root/name
            if not path.exists() and imagepersist.read_marker(path) is None:return
            imagepersist.check_marker(path,generation,descriptor['closed'])
            try:
                self._handle_path(handle)
                shutil.rmtree(path)
            except FileNotFoundError:pass
            imagepersist.remove_marker(path,generation,descriptor['closed'])

    def close(self):
        """Explicit teardown of already confirmed/drained sessions, never implicit closure."""
        with self._lock:
            errors=[]
            for session in list(self._all):
                try:self.release(session)
                except Exception as exc:errors.append(exc)
            if errors:raise ExceptionGroup('Image cleanup failed',errors)
