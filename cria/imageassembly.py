"""Production image assembly from operator config and actual source routing.

No client field supplies vision capability. No routing fallback grants it.
"""
import threading
from . import privatepaths
from .imageprotocol import has_images
from .imagestore import ImageStore
from .imageworkspace import ImageWorkspace,WorkspaceImageTool
from .imageworkflow import ImageWorkflow

class ConfiguredCoderVision:
    def __init__(self,server):self.server=server

    def resolve(self,provider,role,applied_body,rlog):
        routing=self.server.cfg.routing
        # The role that actually serves this turn: a question-class turn is served by the
        # reasoner, not the coder, and refusing it for that reason left an image question
        # unanswerable. Capability is still the operator's explicit per-role declaration.
        name=getattr(role,'name',None)
        selected_role=routing.roles.get(name) if isinstance(name,str) else None
        if role is not selected_role or selected_role is None:return None,None
        backend=routing.backends.get(selected_role.backend)
        if backend is None or backend.transport!='http':return None,None
        if selected_role.vision is not True:return None,selected_role.vision
        router=self.server.router
        if router is None:return None,None
        # _resolve is the same authoritative owner used by Router.route; unlike
        # endpoint_for it cannot authorize via local fallback for a missing key.
        resolved=router._resolve(name,rlog)
        if resolved is None:return None,None
        actual_provider,actual_model=resolved
        if (actual_provider is not provider or not actual_model or
                actual_model!=applied_body.get('model') or
                actual_model!=selected_role.vision_model):
            return None,None
        return actual_model,True

class ConfiguredImages:
    def __init__(self,server,wire):
        self.server=server;self.wire=wire;self._lock=threading.RLock();self._workflow=None
        # Only the operator can bind the deployment's native harness contract.
        # A client schema demonstrates compatibility, never source authority.
        tools=getattr(server.cfg,'tools',None)
        native=getattr(tools,'workspace_image_tool',None)
        self.workspace=(ImageWorkspace(WorkspaceImageTool('view_image','path'))
                        if native=='view_image' else None)

    def capture(self,key,body):
        if (not any(has_images(m) for m in body.get('messages',[])) and
                not (self.workspace is not None and self.workspace.supports(body.get('tools')))):
            return None
        with self._lock:
            if self._workflow is None:
                store=ImageStore(privatepaths.CRIA_HOME/'images',close_authority=object())
                self._workflow=ImageWorkflow(store,self.wire,ConfiguredCoderVision(self.server),workspace=self.workspace)
            workflow=self._workflow
        return workflow.capture(key,body)
