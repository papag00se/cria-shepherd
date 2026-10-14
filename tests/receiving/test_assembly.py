import contextlib,copy,dataclasses,functools,hashlib,http.client,inspect,json,os,urllib.error,urllib.request
from pathlib import Path
from unittest.mock import patch
import pytest
from cria import __main__ as entry,config,contextfloor,routing,server,upstream,receivecapture as rc
from .fixtures import (Lower,FakeSocket,FaultFile,FinalMeta,Log,wire,
                       BODY,cfg,shared,ORIGINAL_URLOPEN,stdlib_lower)
def tx(root):return rc.Receipt(root/'request.json',request_sha256=hashlib.sha256(b'{}').hexdigest())
def invoke(lower,receipt,request=None,**kw):
 return rc.open_request(request or urllib.request.Request('http://fixture.invalid/start',data=b'{}',method='POST'),timeout=420,receipt=receipt,http_connection=lower.HTTP,https_connection=lower.HTTPS,**kw)
def equality(lower,receipt,root):
 lower.witness(root,receipt)
 assert b''.join(Path(p).read_bytes() for p in receipt.files())==b''.join(s.acquired() for s in lower.sockets)
 assert sum(s.returned for s in receipt.activated)==sum(len(s.acquired()) for s in lower.sockets)
def drive_assembled(u,root,enabled,monkeypatch):
 lower=Lower([wire(b'{"choices":[]}')]);real=rc.open_request;seen=[]
 def supplied(req,*,timeout,receipt=None,**kw):
  seen.append({'data':req.data,'headers':dict(req.header_items()),'receipt':receipt})
  return real(req,timeout=timeout,receipt=receipt,http_connection=lower.HTTP,**kw)
 if enabled:
  assert callable(getattr(u,'_receive_open',None)), 'actual factory omitted receiving owner'
  monkeypatch.setattr(rc,'open_request',supplied)
 else:monkeypatch.setattr(urllib.request,'urlopen',lambda req,timeout:supplied(req,timeout=timeout))
 log=Log();response,estimate,path=u._open_with_refit(copy.deepcopy(BODY),False,log)
 assert response.read()==b'{"choices":[]}'
 response.close();lower.assert_closed()
 assert len(seen)==1;sent=seen[0]['data'];expected={**BODY,'stream':False}
 assert json.loads(sent)==expected
 assert estimate==contextfloor.est_total(expected['messages'],expected.get('tools'))
 (root/'prepared-sent.json').write_text(json.dumps({'sent_hex':sent.hex(),'estimate':estimate,'capture':path,'prepared_is_sent':True,'events':log.events},indent=2)+'\n')
 if enabled:
  t=seen[0]['receipt'];assert t.finished and t.meta.closed and not t.failed
  assert json.loads(Path(path).read_bytes())['body']==expected
  equality(lower,t,root)
 else:assert path is None and seen[0]['receipt'] is None
 return seen
@pytest.mark.parametrize('enabled',[False,True])
def test_real_shared_entrypoint(tmp_path,enabled,monkeypatch):drive_assembled(shared(tmp_path,enabled),tmp_path,enabled,monkeypatch)
@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('keyed',[False,True])
def test_real_server_secondary(tmp_path,enabled,keyed,monkeypatch):
 c=cfg(tmp_path,enabled);u=shared(tmp_path,enabled)
 if keyed:
  monkeypatch.setenv('C21_FIXTURE_API_KEY','supplied-not-secret')
  c=dataclasses.replace(c,routing=dataclasses.replace(c.routing,backends={'secondary':config.Backend('secondary',base_url='http://second.invalid',api_key_env='C21_FIXTURE_API_KEY')}))
 with patch.object(server.ThreadingHTTPServer,'__init__',return_value=None):s=server.CriaServer(c,Log(),u)
 endpoint=s.router.endpoint_for('reasoner');assert endpoint is not u
 assert s.router.endpoint_for('reasoner') is endpoint
 assert endpoint._window==49152
 seen=drive_assembled(endpoint,tmp_path,enabled,monkeypatch)
 if keyed:assert seen[0]['headers']['Authorization']=='Bearer supplied-not-secret'
def test_capture_disabled_installed_policy(tmp_path,monkeypatch):
 lower=Lower([wire(b'existing-policy-result')])
 class Existing(urllib.request.BaseHandler):
  def default_open(self,req):
   connection=lower.HTTP(req.host,timeout=req.timeout)
   connection.request(req.get_method(),req.selector,body=req.data,headers=dict(req.header_items()))
   return connection.getresponse()
 opener=urllib.request.build_opener(Existing());parents=[h.parent for h in opener.handlers]
 monkeypatch.setattr(urllib.request,'_opener',opener)
 # Genuine public urlopen restored ONLY for the in-memory installed policy fixture.
 monkeypatch.setattr(urllib.request,'urlopen',ORIGINAL_URLOPEN)
 u=shared(tmp_path,False);data=b'{}'
 monkeypatch.setattr(u,'_prep',lambda *a,**k:(data,1,None))
 response,estimate,path=u._open_with_refit({},False,Log())
 assert response.read()==b'existing-policy-result' and path is None and estimate==1
 response.close();lower.assert_closed()
 assert len(lower.factories)==1 and len(lower.connects)==1
 assert urllib.request._opener is opener and [h.parent for h in opener.handlers]==parents
def test_automatic_capture_accepts_ordinary_cache(tmp_path,monkeypatch):
 # Correct the rejected stock-cache refusal expectation; custom policies remain separate.
 lower=Lower([wire(b'{"prompt":"labelled"}'),wire(b'ok')])
 stdlib_lower(monkeypatch,lower)
 u=shared(tmp_path,True)
 assert u._render_prompt(BODY)=='labelled'
 installed=urllib.request._opener;parents=[h.parent for h in installed.handlers]
 receipt=tx(tmp_path)
 try:
  response=u._receive_open(urllib.request.Request('http://fixture.invalid'),timeout=1,receipt=receipt)
  assert response.read()==b'ok';response.close()
  assert receipt.finished and receipt.meta.closed and not receipt.failed
  assert urllib.request._opener is installed and [h.parent for h in installed.handlers]==parents
  # This receipt owns chat only, not the preceding ordinary render response.
  assert b''.join(Path(p).read_bytes() for p in receipt.files())==lower.sockets[1].acquired()
  assert sum(s.returned for s in receipt.activated)==len(lower.sockets[1].acquired())
  assert lower.sockets[0].acquired() and len(lower.factories)==2
  lower.assert_closed()
 finally:receipt.finish()
def test_compatible_explicit_owner_preserves_global_policy(tmp_path,monkeypatch):
 installed=urllib.request.build_opener();parents=[h.parent for h in installed.handlers];monkeypatch.setattr(urllib.request,'_opener',installed)
 lower=Lower([wire()]);receipt=tx(tmp_path)
 response=invoke(lower,receipt);assert response.read()==b'ok';response.close()
 equality(lower,receipt,tmp_path);lower.assert_closed()
 assert urllib.request._opener is installed and [h.parent for h in installed.handlers]==parents
def test_bound_handler_not_stolen(tmp_path):
 handler=urllib.request.HTTPRedirectHandler();installed=urllib.request.build_opener(handler);receipt=tx(tmp_path);lower=Lower([wire()])
 try:
  with pytest.raises(ValueError,match='bound handler'):invoke(lower,receipt,handlers=(handler,))
  assert handler.parent is installed and not lower.factories
 finally:receipt.finish()
@pytest.mark.parametrize('code,method,expected',[(301,'POST','GET'),(302,'POST','GET'),(303,'POST','GET'),(307,'GET','GET'),(308,'GET','GET')])
def test_default_redirect_actual_ranges_and_policy(tmp_path,code,method,expected):
 lower=Lower([wire(b'redirect-body',code,b'Location: /next\r\n'),wire(b'final-body')]);receipt=tx(tmp_path)
 req=urllib.request.Request('http://fixture.invalid/start',data=b'body' if method=='POST' else None,method=method,headers={'Content-Type':'application/json','X-Fixture':'carry'})
 req.add_unredirected_header('X-Initial-Only','not-carried')
 try:
  response=invoke(lower,receipt,req)
  assert not receipt.finished and not receipt.meta.closed
  assert receipt.activated[0].closed and len(receipt.activated)==2
  assert response.read()==b'final-body';response.close()
  assert receipt.finished and receipt.meta.closed and not receipt.failed
  second=b''.join(lower.sockets[1].sent)
  assert second.startswith(expected.encode()+b' /next ')
  assert b'X-Fixture: carry' in second and b'X-Initial-Only' not in second
  assert b'Content-Type:' not in second and b'Content-Length:' not in second
  equality(lower,receipt,tmp_path);lower.assert_closed()
 finally:receipt.finish()
@pytest.mark.parametrize('code',[307,308])
def test_redirect_post_error_identity(tmp_path,code):
 lower=Lower([wire(b'unsupported-post',code,b'Location: /next\r\n')]);receipt=tx(tmp_path)
 try:
  with pytest.raises(urllib.error.HTTPError) as got:invoke(lower,receipt)
  error=got.value;assert error.code==code and len(lower.factories)==1
  assert error.read()==b'unsupported-post'
  assert not receipt.finished
  assert not rc.finalize_http_error(error,receipt)
  assert error.closed and receipt.finished and receipt.meta.closed
  equality(lower,receipt,tmp_path);lower.assert_closed()
 finally:receipt.finish()
def test_redirect_loop_genuine_stdlib_limit(tmp_path):
 lower=Lower([wire(b'x',302,b'Location: /start\r\n') for _ in range(6)]);receipt=tx(tmp_path)
 try:
  with pytest.raises(urllib.error.HTTPError) as got:invoke(lower,receipt,urllib.request.Request('http://fixture.invalid/start'))
  assert 'infinite loop' in str(got.value)
  assert len(lower.factories)==urllib.request.HTTPRedirectHandler.max_repeats+1
  got.value.read();rc.finalize_http_error(got.value,receipt)
  equality(lower,receipt,tmp_path);lower.assert_closed()
 finally:receipt.finish()
@pytest.mark.parametrize('deny',['admission','finite','unknown','fatal'])
def test_second_hop_denied_before_factory(tmp_path,deny):
 lower=Lower([wire(b'x',302,b'Location: /next\r\n'),wire(b'never')]);receipt=tx(tmp_path)
 seen=[];observations=[];blocked=[];prior=['retained prior finite wait']
 def admit(req):
  seen.append(req.full_url)
  if req.full_url.endswith('/next') and (deny=='admission' or blocked):
   raise OSError('caller-declared admission/wait denial')
 def observe(req,response):
  observations.append((req.full_url,dict(response.headers)))
  if deny in ('finite','unknown'):blocked.append(deny)
  elif deny=='fatal':receipt.origin.sink=FaultFile(receipt.origin.sink,'close')
 if deny=='finite':
  lower.sockets[0].wire=wire(b'x',302,b'Location: /next\r\nRetry-After: 9000\r\n')
  lower.sockets[0].steps=[len(lower.sockets[0].wire)]
 try:
  with pytest.raises(OSError):invoke(lower,receipt,admit=admit,observe_response=observe)
  assert len(observations)==1 and prior==['retained prior finite wait']
  if deny=='finite':assert observations[0][1]['Retry-After']=='9000'
  assert len(lower.factories)==1 and len(lower.connects)==1
  assert not lower.sockets[1].returned and not lower.sockets[1].sent
  assert receipt.finished and receipt.meta.closed
  lower.assert_closed()
 finally:receipt.finish()
def test_multihop_once_only_headers_and_order(tmp_path):
 lower=Lower([wire(b'a',302,b'Location: /middle\r\n'),wire(b'b',303,b'Location: /end\r\n'),wire(b'c')]);receipt=tx(tmp_path);admissions=[];observations=[]
 def observe(req,response):
  observations.append((req.full_url,response.status));assert not receipt.finished and not receipt.meta.closed
 response=invoke(lower,receipt,admit=lambda req:admissions.append(req.full_url),observe_response=observe)
 assert response.read()==b'c';response.close()
 assert admissions==['http://fixture.invalid/start','http://fixture.invalid/middle','http://fixture.invalid/end']
 assert observations==list(zip(admissions,[302,303,200]))
 equality(lower,receipt,tmp_path);lower.assert_closed()
def test_closed_admission_no_lower_dispatch(tmp_path):
 lower=Lower([wire()]);receipt=tx(tmp_path)
 def deny(req):raise OSError('caller-declared closed endpoint')
 try:
  with pytest.raises(OSError):invoke(lower,receipt,admit=deny)
  assert not lower.factories and not lower.connects and not lower.sockets[0].returned and not lower.sockets[0].sent
  assert receipt.finished and receipt.meta.closed
 finally:receipt.finish()
@pytest.mark.parametrize('method',['read','read1','readline','iteration'])
def test_terminal_late_store_below_public_reads(tmp_path,method):
 head=wire(b'abcd')[:-4];lower=Lower([head+b'abcd'],steps=[[len(head),2,2]]);receipt=tx(tmp_path)
 response=invoke(lower,receipt);fault=FaultFile(receipt.origin.sink,'late');fault.writes=1;receipt.origin.sink=fault
 try:
  with pytest.raises(rc.CaptureFailure) as first:response.read1(2)
  n=len(lower.sockets[0].returned)
  with pytest.raises(rc.CaptureFailure) as again:
   next(response) if method=='iteration' else getattr(response,method)(2)
  assert again.value is first.value and isinstance(first.value.__cause__,OSError)
  assert len(lower.sockets[0].returned)==n and lower.sockets[0].cursor==len(head)+2
  assert fault.attempted==[b'ab'] and fault.success==[]
  with pytest.raises(rc.CaptureFailure):response.close()
  lower.witness(tmp_path,receipt);lower.assert_closed()
  assert receipt.finished and receipt.failed and receipt.meta.closed
 finally:receipt.finish()
@pytest.mark.parametrize('fault',[None,'close','meta','partial','partial-close'])
@pytest.mark.parametrize('refit',[False,True])
def test_http_error_cleanup_before_outward_or_refit(tmp_path,fault,refit,monkeypatch):
 errorbody=json.dumps({'error':{'message':'supplied rejection',**({'n_prompt_tokens':700,'n_ctx':500} if refit else {})}}).encode()
 firstwire=wire(errorbody,400 if refit else 503);head=len(firstwire)-len(errorbody)
 lower=Lower([firstwire,wire(b'clean-refit')],steps=[[head,2,'eof'] if fault in ('partial','partial-close') else [len(firstwire)],[len(wire(b'clean-refit'))]])
 receipts=[];errors=[];preparations=[];real=rc.open_request
 def supplied(req,*,timeout,receipt=None):
  if receipts:
   assert errors[0].closed and receipts[0].finished and receipts[0].meta.closed and not receipts[0].failed
   assert lower.sockets[0]._io_refs==0 and all(r.closed for r in lower.sockets[0].raws)
  if receipt is None:receipt=rc.Receipt(tmp_path/f'baseline-attempt-{len(receipts)}',request_sha256=hashlib.sha256(req.data).hexdigest())
  receipts.append(receipt)
  if fault in ('close','partial-close'):receipt.origin.sink=FaultFile(receipt.origin.sink,'close')
  if fault=='meta':receipt.meta=FinalMeta(receipt.meta,receipt)
  try:return real(req,timeout=timeout,receipt=receipt,http_connection=lower.HTTP)
  except urllib.error.HTTPError as error:errors.append(error);raise
 kwargs={'context_window':49152,'capture_dir':tmp_path/'captures','capture_rendered':False}
 if 'open_request' in inspect.signature(upstream.Upstream).parameters:kwargs['open_request']=supplied
 u=upstream.Upstream('http://fixture.invalid',**kwargs)
 monkeypatch.setattr(urllib.request,'urlopen',lambda req,timeout:supplied(req,timeout=timeout))
 def prep(*a,**kw):
  preparations.append(kw);return (b'{}' if len(preparations)==1 else b'{"refitted":true}'),335,str(tmp_path/f'prepared-{len(preparations)}.json')
 monkeypatch.setattr(u,'_prep',prep)
 primary=None;result=None
 try:
  try:result=u._open_with_refit({'model':'supplied'},False,Log())
  except BaseException as error:primary=error
  # Snapshot before fixture cleanup, including actual error/metadata/lower resources.
  (tmp_path/'outward.json').write_text(json.dumps({'primary':type(primary).__name__ if primary else None,'error_closed':[e.closed for e in errors],'receipt_finished':[t.finished for t in receipts],'meta_closed':[t.meta.closed for t in receipts],'dispatches':len(receipts),'preparations':len(preparations),'partials':[t.partials for t in receipts],'failures':[t.failed for t in receipts]},indent=2)+'\n')
  assert errors and errors[0].closed and receipts[0].finished and receipts[0].meta.closed
  if refit and fault is None:
   assert result is not None and len(receipts)==2 and len(preparations)==2
   assert result[0].read()==b'clean-refit';result[0].close()
  else:
   assert isinstance(primary,upstream.UpstreamError) and primary.__cause__ is errors[0]
   assert primary.code==(400 if refit else 503) and len(receipts)==1 and len(preparations)==1
   if fault in ('partial','partial-close'):assert receipts[0].partials and getattr(errors[0],'__notes__',[])
   elif fault:assert receipts[0].failed and getattr(errors[0],'__notes__',[])
   else:assert primary.response_error['message']=='supplied rejection' and errors[0].response_body==errorbody
  for i,t in enumerate(receipts):lower.witness(tmp_path,t)
  lower.assert_closed()
 finally:
  for e in errors:
   try:e.close()
   except BaseException:pass
  for t in receipts:t.finish(primary)
  if result:
   try:result[0].close()
   except BaseException:pass
@pytest.mark.parametrize('kind',['finite','unknown','opaque','body'])
def test_once_only_waits_preserve_history(tmp_path,kind):
 # Caller owns wait interpretation; test raw delivery/once-only ownership, not a second parser.
 history=[{'Retry-After':'9100'}];calls=[]
 lower=Lower([wire(b'{"retry_after":20}' if kind=='body' else b'ok',200,
                  b'Retry-After: opaque\r\n' if kind=='opaque' else b'Retry-After: 30\r\n')])
 receipt=tx(tmp_path)
 def observe(req,response):
  calls.append(dict(response.headers));history.append(dict(response.headers))
 response=invoke(lower,receipt,observe_response=observe)
 body=response.read();response.close()
 if kind=='body':history.append(body)
 if kind=='unknown':history.append(None)  # caller-declared loss, not an inferred HTTP signal
 assert len(calls)==1 and history[0]=={'Retry-After':'9100'}
 assert calls[0]['Retry-After']==('opaque' if kind=='opaque' else '30')
 if kind=='body':assert history[-1]==b'{"retry_after":20}'
 if kind=='unknown':assert history[-1] is None
 equality(lower,receipt,tmp_path);lower.assert_closed()
@pytest.mark.parametrize('kind',['allowed','finite','opaque','unavailable'])
def test_CONNECT_public_headers_before_TLS(tmp_path,kind,monkeypatch):
 prefix=b'HTTP/1.1 200 Connection established\r\n'+(b'Retry-After: 9000\r\n' if kind=='finite' else b'Retry-After: opaque\r\n' if kind=='opaque' else b'Proxy-Fixture: yes\r\n')+b'\r\n'
 lower=Lower([prefix+wire()],steps=[[len(prefix),len(wire())]]);receipt=tx(tmp_path);observed=[]
 if kind=='unavailable':lower.HTTPS.get_proxy_response_headers=None
 def proxy(headers):
  observed.append(headers)
  if headers is None or 'Retry-After' in headers:raise OSError('caller-declared unknown/wait denial')
 receipt.on_proxy_headers=proxy
 class Context:
  def wrap_socket(self,sock,server_hostname):lower.wraps.append(server_hostname);return sock
 init=urllib.request.HTTPSHandler.__init__
 def supplied(h,*a,**kw):init(h,context=Context(),**{k:v for k,v in kw.items() if k!='context'})
 monkeypatch.setattr(urllib.request.HTTPSHandler,'__init__',supplied)
 monkeypatch.setattr(urllib.request,'getproxies',lambda:{'https':'http://proxy.invalid:8080'})
 req=urllib.request.Request('https://fixture.invalid/start',data=b'{}')
 getter_available=callable(getattr(lower.HTTPS,'get_proxy_response_headers',None))
 try:
  if kind=='allowed' and getter_available:
   response=invoke(lower,receipt,req);assert response.read()==b'ok';response.close()
   assert lower.wraps==['fixture.invalid'] and [s.phase for s in receipt.activated]==['proxy-CONNECT','origin']
   assert observed[0]['Proxy-Fixture']=='yes'
  else:
   with pytest.raises(OSError):invoke(lower,receipt,req)
   assert not lower.wraps and not any(b'POST ' in b for b in lower.sockets[0].sent)
   assert receipt.finished and receipt.meta.closed
  assert len(observed)==1
  if getter_available and kind in ('finite','opaque'):
   assert observed[0]['Retry-After']==('9000' if kind=='finite' else 'opaque')
  else:
   if not getter_available:assert observed==[None]
  equality(lower,receipt,tmp_path);lower.assert_closed()
 finally:receipt.finish()
def test_cancel_no_future_receive(tmp_path):
 head=wire(b'a\nb\n')[:-4];lower=Lower([head+b'a\nb\n'],steps=[[len(head),2,2]]);receipt=tx(tmp_path)
 response=invoke(lower,receipt);assert next(response)==b'a\n';count=len(lower.sockets[0].returned)
 response.close()
 assert len(lower.sockets[0].returned)==count and lower.sockets[0].cursor==len(head)+2
 equality(lower,receipt,tmp_path);lower.assert_closed()
