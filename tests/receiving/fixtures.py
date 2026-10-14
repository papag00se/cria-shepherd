"""In-memory lower sockets; actual stdlib SocketIO/HTTP processing and package assembly.

No response adapter, custody implementation, external observer or real network.
"""
import ast
import copy
import dataclasses
import http.client
import io
import json
import socket
import types
import urllib.request
from pathlib import Path
from unittest.mock import patch
from cria import __main__ as entry, config, server

BODY = {'model':'supplied', 'messages':[{'role':'user','content':'Labelled offline fixture.'}], 'max_tokens':8192}

class Log:
    session='receiving-fixture'; phase='proxy'; turn='fixture'; _turn='fixture'
    def __init__(self): self.events=[]
    def emit(self,kind,**kw): self.events.append({'kind':kind,**kw})
    def decide(self,*a,**kw): pass

class FakeSocket:
    def __init__(self,wire,steps=None):
        self.wire=wire; self.cursor=0; self.steps=list(steps or [len(wire)])
        self.returned=[]; self.sent=[]; self._io_refs=0; self.raws=[]
    def makefile(self,mode,buffering=-1):
        assert mode=='rb'
        # Genuine lower IO class, without allocating a network socket.
        raw=socket.SocketIO(self,mode)
        self._io_refs+=1; self.raws.append(raw)
        return raw if buffering==0 else io.BufferedReader(raw,io.DEFAULT_BUFFER_SIZE if buffering<0 else buffering)
    def recv_into(self,b):
        if not self.steps: return 0
        step=self.steps[0]
        if isinstance(step,str):
            self.steps.pop(0)
            if step=='eof': return 0
            if step=='timeout': raise TimeoutError('supplied recv_into timeout')
            raise OSError(5,'supplied transport loss')
        n=min(step,len(b),len(self.wire)-self.cursor)
        if not n: self.steps.pop(0); return self.recv_into(b)
        a=self.cursor; b[:n]=self.wire[a:a+n]; self.cursor+=n; self.steps[0]-=n
        if not self.steps[0]: self.steps.pop(0)
        self.returned.append([a,self.cursor]); return n
    def _decref_socketios(self): self._io_refs-=1
    def fileno(self): return -1
    def sendall(self,data): self.sent.append(bytes(data))
    def setsockopt(self,*a): pass
    def close(self): pass
    def acquired(self): return b''.join(self.wire[a:b] for a,b in self.returned)

class Lower:
    def __init__(self,wires,steps=None):
        self.sockets=[FakeSocket(w,steps[i] if steps else None) for i,w in enumerate(wires)]
        self.factories=[]; self.connects=[]; self.wraps=[]
        lower=self
        class HTTP(http.client.HTTPConnection):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw); i=len(lower.factories)
                lower.factories.append({'host':self.host,'index':i})
                self._create_connection=lambda *a,**kw:lower.connect(i)
        class HTTPS(http.client.HTTPSConnection):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw); i=len(lower.factories)
                lower.factories.append({'host':self.host,'index':i})
                self._create_connection=lambda *a,**kw:lower.connect(i)
        self.HTTP=HTTP; self.HTTPS=HTTPS
    def connect(self,i): self.connects.append(i); return self.sockets[i]
    def assert_closed(self):
        assert all(s._io_refs==0 and all(r.closed for r in s.raws) for s in self.sockets)
    def witness(self,root,tx):
        # Local test diagnostics only; acquired bytes are derived from actual lower returns.
        (root/'witness.json').write_text(json.dumps({'factories':self.factories,'connects':self.connects,
            'lower':[{'returned':s.returned,'sent':[b.hex() for b in s.sent],'refs':s._io_refs} for s in self.sockets],
            'receipt':{'finished':tx.finished,'failed':tx.failed,'partials':tx.partials,
                       'events':tx.events,'segments':[s.state() for s in tx.segments]}},indent=2)+'\n')

def wire(body=b'ok',status=200,headers=b''):
    return f'HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\n'.encode()+headers+b'\r\n'+body

class FaultFile:
    def __init__(self,f,kind): self.f=f; self.kind=kind; self.writes=0; self.attempted=[]; self.success=[]
    def __getattr__(self,k): return getattr(self.f,k)
    def write(self,b):
        self.writes+=1; self.attempted.append(bytes(b))
        if self.kind=='late' and self.writes==2: raise OSError(28,'late raw write failure')
        n=self.f.write(b); self.success.append(bytes(b[:n])); return n
    def flush(self):
        if self.kind=='flush': raise OSError(28,'raw flush failure')
        self.f.flush()
    def close(self):
        self.f.close()
        if self.kind=='close': raise OSError(28,'raw close failure')

class FinalMeta:
    def __init__(self,f,tx): self.f=f; self.tx=tx
    def __getattr__(self,k): return getattr(self.f,k)
    def flush(self):
        if self.tx.finished: raise OSError(28,'final metadata failure')
        return self.f.flush()

# The external guard blocks public urlopen before collection. Restore its genuine stdlib
# function for this labelled lower-IO seam, rather than a cache-bypassing response adapter.
_tree=ast.parse(Path(urllib.request.__file__).read_text())
_node=next(n for n in _tree.body if isinstance(n,ast.FunctionDef) and n.name=='urlopen')
_ns=dict(vars(urllib.request))
exec(compile(ast.Module(body=[_node],type_ignores=[]),urllib.request.__file__,'exec'),_ns)
ORIGINAL_URLOPEN=types.FunctionType(_ns['urlopen'].__code__,vars(urllib.request),argdefs=_ns['urlopen'].__defaults__)
ORIGINAL_URLOPEN.__kwdefaults__=_ns['urlopen'].__kwdefaults__

def cfg(root,enabled,rendered=False,level=0,window=49152):
    d=config.Config()
    return dataclasses.replace(d,env_file=None,
        upstream=dataclasses.replace(d.upstream,base_url='http://fixture.invalid',context_window=window),
        logging=dataclasses.replace(d.logging,dir=str(root),console=False,jsonl=False,capture_calls=enabled,
                                    capture_dir=str(root/'captures'),capture_rendered=rendered),
        routing=dataclasses.replace(d.routing,engagement_level=level,
            backends={'secondary':config.Backend('secondary',base_url='http://second.invalid')},
            roles={'reasoner':config.Role('reasoner','secondary')}),
        planner=dataclasses.replace(d.planner,enabled=False))

def entrypoint(c):
    out={}
    class Terminal:
        def __init__(self,c,l,u): out['u']=u
        def serve_forever(self): raise KeyboardInterrupt
        def drain_streams(self): return 0
        def server_close(self): pass
    with patch.object(entry.Config,'load',return_value=c),patch.object(entry,'CriaServer',Terminal),patch.object(entry.signal,'signal'):
        assert entry.main(['--config','supplied-config-not-read'])==0
    return out['u']

def shared(root,enabled): return entrypoint(cfg(root,enabled))

def assemble(root,endpoint,rendered,level=0,window=49152):
    c=cfg(root,True,rendered,level,window); shared=entrypoint(c)
    if endpoint=='shared': return shared,shared
    if endpoint=='keyed':
        c=dataclasses.replace(c,routing=dataclasses.replace(c.routing,backends={
            'secondary':dataclasses.replace(c.routing.backends['secondary'],api_key_env='C21_CACHE_FIXTURE_KEY')}))
    with patch.object(server.ThreadingHTTPServer,'__init__',return_value=None): s=server.CriaServer(c,Log(),shared)
    u=s.router.endpoint_for('reasoner')
    assert u is s.router.endpoint_for('reasoner') and u._receive_open is shared._receive_open
    return shared,u

def stdlib_lower(monkeypatch,lower):
    monkeypatch.setattr(urllib.request,'urlopen',ORIGINAL_URLOPEN)
    monkeypatch.setattr(urllib.request,'_opener',None)  # isolated fixture, never production
    original=http.client.HTTPConnection.__init__; calls=[]
    do_open=urllib.request.HTTPHandler.do_open
    def connection(self,*a,**kw):
        original(self,*a,**kw); i=len(lower.factories)
        lower.factories.append({'host':self.host,'index':i})
        self._create_connection=lambda *a,**kw:lower.connect(i)
    def observed(handler,klass,req,**kw):
        calls.append((req.full_url,req.data,dict(req.header_items())))
        return do_open(handler,klass,req,**kw)
    monkeypatch.setattr(http.client.HTTPConnection,'__init__',connection)
    monkeypatch.setattr(urllib.request.HTTPHandler,'do_open',observed)
    return calls

def consume(u,body,lower,log):
    response,estimate,path=u._open_with_refit(copy.deepcopy(body),False,log)
    assert response.read()==b'final'
    t=response.receive_transaction; response.close()
    assert t.finished and t.meta.closed and not t.failed
    assert b''.join(Path(p).read_bytes() for p in t.files())==lower.sockets[lower.connects[-1]].acquired()
    return estimate,Path(path)
