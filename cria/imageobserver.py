"""Image semantics consume upstream-owned actual POST/terminal receipts.

No upstream import, preflight observer, transport, model call, or wire owner here.
"""
import json
import threading
from .imageprotocol import Delivery,ImageUnavailable,image_parts,digest

class ObservationCallbacks:
    def __init__(self,session,attempt):
        self.owner_token=object();self._session=session;self._attempt=attempt
        self._active=None;self._seen=set();self._terminal=set();self._result=None
        self._cancelled=False;self._failure=None;self._lock=threading.RLock()

    def started(self,receipt):
        with self._lock:
            if self._cancelled or self._result is not None:raise ImageUnavailable('Image observation dispatch is no longer active')
            if receipt.owner_token is not self.owner_token or type(receipt.dispatch_token) is not object:
                raise ImageUnavailable('Image dispatch has no producer-owned binding')
            if receipt.dispatch_token in self._seen:raise ImageUnavailable('Image dispatch token was reused')
            attempt=self._attempt;route=attempt.route
            if (receipt.provider is not route.provider or receipt.model!=route.model or receipt.role_signature!=route.role_signature):
                raise ImageUnavailable('Actual coder wire route differs from image observation binding')
            if not isinstance(receipt.final_wire,bytes):raise ImageUnavailable('Image delivery requires actual serialized wire bytes')
            try:wire=json.loads(receipt.final_wire)
            except (TypeError,ValueError) as exc:raise ImageUnavailable('Image observation wire is invalid') from exc
            images=image_parts(wire.get('messages') or [])
            user_images=image_parts([m for m in wire.get('messages') or [] if m.get('role')=='user'])
            if wire.get('model')!=receipt.model or len(images)!=1 or user_images!=images or digest(images[0])!=attempt.source_digest:
                raise ImageUnavailable('Actual image wire lost or changed its original occurrence')
            # Exact source spans, not semantic relevance detection. Role lowering may relocate them.
            texts=[]
            for message in wire.get('messages') or []:
                content=message.get('content')
                if isinstance(content,str):texts.append(content)
                elif isinstance(content,list):texts.extend(p.get('text','') for p in content if isinstance(p,dict))
            required=[attempt.request['messages'][0]['content'],attempt.request['messages'][1]['content'][0]['text']]
            if not all(any(span in text for text in texts) for span in required):
                raise ImageUnavailable('Image observation wire lost its governing task or observation instruction')
            with self._session._lock:
                record=self._session._record(attempt.ref)
                if (record.pending!=attempt.nonce or record.source_digest!=attempt.source_digest or record.task_scope!=attempt.task_scope
                        or self._session._route is None or not self._session._route.same(route)):
                    raise ImageUnavailable('Image observation source/attempt is stale')
            self._seen.add(receipt.dispatch_token);self._active=receipt

    def completed(self,receipt,completion,terminal_complete):
        with self._lock:
            if (self._cancelled or receipt is not self._active or receipt.dispatch_token in self._terminal
                    or receipt.owner_token is not self.owner_token):
                raise ImageUnavailable('Image terminal event does not match latest actual dispatch')
            self._terminal.add(receipt.dispatch_token)
            if terminal_complete is not True:
                self._failure=ImageUnavailable('Image observation did not reach a complete terminal event')
                return
            delivery=Delivery.from_wire(self._attempt.nonce,receipt.provider,receipt.role_signature,
                    json.loads(receipt.final_wire),completion,terminal_complete=terminal_complete)
            try:self._result=self._session.complete(self._attempt,delivery)
            except ImageUnavailable as exc:self._failure=exc;raise

    def result(self):
        with self._lock:
            if self._result is None:
                raise self._failure or ImageUnavailable('No completed image observation receipt; original image retained')
            return self._result

    def cancel(self):
        with self._lock:
            if self._cancelled:return
            self._cancelled=True;self._session.cancel(self._attempt)
            # Drop our image-bearing receipt/request references after dispatch ownership ends.
            self._active=None;self._attempt=None;self._session=None
            if self._failure is not None:self._failure=ImageUnavailable(str(self._failure))
