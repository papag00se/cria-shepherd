"""Request-local image orchestration. Wire authority is injected, never recreated."""
import json
from . import prompts
from contextvars import ContextVar
from dataclasses import dataclass
from .imageprotocol import CoderRoute,ImageUnavailable,has_images
from .imageobserver import ObservationCallbacks

current = ContextVar('source_image_context', default=None)

@dataclass(frozen=True)
class SourceImageContext:
    workflow: object
    session: object
    prepared: object
    task: str

class ImageWorkflow:
    def __init__(self,store,wire,capability,workspace=None):
        self.store=store;self.wire=wire;self.capability=capability;self.workspace=workspace

    def capture(self,key,body):
        messages=body.get('messages',[])
        if self.workspace is None and not any(has_images(m) for m in messages):return None
        # Identity and task come from original packets, never an observation projection.
        task='\n'.join(p.get('text','') for m in messages if m.get('role')=='user'
                      for p in (m.get('content') if isinstance(m.get('content'),list) else [{'text':m.get('content','')}]))
        session=self.store.session(key)
        sources=self.workspace.resolve(session,messages) if self.workspace else None
        return SourceImageContext(self,session,session.prepare(messages,task,workspace_sources=sources),task)

    def run(self,provider,role,body,context,rlog):
        if context is None or not context.prepared.bindings:return body
        if role is None or provider is None:
            raise ImageUnavailable('Selected coder route is unavailable; original image retained')
        # Only the source routing owner can supply this provider/model capability fact.
        resolver=getattr(self.capability,'resolve',None)
        selected=resolver(provider,role,body,rlog) if callable(resolver) else self.capability(provider,role)
        model,vision=selected if isinstance(selected,tuple) and len(selected)==2 else (None,None)
        if not isinstance(model,str) or not model or vision is not True:
            raise ImageUnavailable('Selected coder vision capability is unknown or unavailable; original image retained')
        if body.get('model')!=model:
            raise ImageUnavailable('Vision capability model differs from actual selected coder model; original retained')
        session=context.session
        lease=session.acquire()
        try:
            self.wire.record_applied_coder_role(body,role)
            route=CoderRoute(provider,model,self.wire.coder_role_signature(body),True)
            session.select_route(route)
            for ref in session.pending(context.prepared):
                self.observe(provider,role,body,context,route,ref,rlog)
            return {**body,'messages':session.project(context.prepared,body.get('messages',[]))}
        finally:lease.release()

    def observe(self,provider,role,body,context,route,ref,rlog):
        attempt=context.session.begin(ref,context.task,route,body)
        callbacks=ObservationCallbacks(context.session,attempt)
        try:
            role.apply(attempt.request,rlog=rlog)
            self.wire.record_applied_coder_role(attempt.request,role)
            if self.wire.coder_role_signature(attempt.request)!=route.role_signature:
                raise ImageUnavailable('Observation role controls changed; original image retained')
            bound=self.wire.bind_coder_route(attempt.request,route)
            bound=self.wire.bind_coder_observer(bound,self.wire.CoderObserverBinding(
                callbacks.owner_token,route.role_signature,callbacks.started,callbacks.completed))
            provider.chat(bound,rlog)
            return callbacks.result()
        finally:callbacks.cancel()

    def chat(self,provider,role,body,context,rlog,call=None):
        prepared=self.run(provider,role,body,context,rlog)
        if context is None:return (call or provider.chat)(prepared,rlog)
        if not context.prepared.bindings:
            raw=(call or provider.chat)(prepared,rlog)
            if self.workspace is None:return raw
            return json.dumps(self.workspace.register(context.session,json.loads(raw),body.get('tools')))
        tool={'type':'function','function':{'name':'reinspect_image','description':prompts.load('image_reinspect_tool'),
            'parameters':{'type':'object','properties':{'ref':{'type':'string'}},'required':['ref'],'additionalProperties':False}}}
        if any((t.get('function') or {}).get('name')=='reinspect_image' for t in prepared.get('tools',[])):
            raise ImageUnavailable('Image reinspection tool conflicts with caller tool')
        prepared={**prepared,'tools':list(prepared.get('tools',[]))+[tool]}
        while True:
            raw=(call or provider.chat)(prepared,rlog)
            parsed=json.loads(raw)
            choices=parsed.get('choices') or []
            if len(choices)!=1:return raw
            message=choices[0].get('message') or {}
            calls=message.get('tool_calls') or []
            own=[c for c in calls if (c.get('function') or {}).get('name')=='reinspect_image']
            if not own:
                if self.workspace is None:return raw
                return json.dumps(self.workspace.register(context.session,parsed,body.get('tools')))
            if len(own)!=len(calls) or choices[0].get('finish_reason')!='tool_calls':
                raise ImageUnavailable('Image reinspection mixed with external actions; original retained')
            results=[]
            for c in own:
                try:args=json.loads(c['function']['arguments'])
                except (KeyError,TypeError,ValueError) as exc:
                    raise ImageUnavailable('Image reinspection arguments are invalid') from exc
                if (not isinstance(args,dict) or set(args)!={'ref'} or
                        not isinstance(args['ref'],str) or not args['ref'] or
                        args['ref'] not in {b.ref for b in context.prepared.bindings}):
                    raise ImageUnavailable('Unknown image occurrence reference')
                from .imagestore import FreshWorkspaceRead
                source=context.session.reinspect(args['ref'])
                if isinstance(source,FreshWorkspaceRead):
                    if self.workspace is None:
                        raise ImageUnavailable('Workspace image reinspection requires a fresh harness image read')
                    if len(own)!=1:
                        raise ImageUnavailable('Workspace reinspection requires one correlated harness read action')
                    action=self.workspace.request(context.session,args['ref'],source.path,body.get('tools'),prepared['model'])
                    rlog.emit('image.workspace_read_requested',ref=args['ref'])
                    return json.dumps(action)
                self.wire.record_applied_coder_role(prepared,role)
                route=CoderRoute(provider,prepared['model'],self.wire.coder_role_signature(prepared),True)
                context.session.select_route(route)
                self.observe(provider,role,prepared,context,route,args['ref'],rlog)
                binding=next(b for b in context.prepared.bindings if b.ref==args['ref'])
                view=context.session.render(context.prepared)
                text=view[binding.message]['content'][binding.part]['text']
                results.append({'role':'tool','tool_call_id':c['id'],'content':text})
            prepared={**prepared,'messages':prepared['messages']+[message]+results}
