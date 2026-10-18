import copy,dataclasses,hashlib,http.client,inspect,json,urllib.error,urllib.request
from unittest.mock import patch
from pathlib import Path
import pytest
from cria import __main__ as entry,server,upstream,receivecapture as rc,contextfloor,assistruntime
from .fixtures import Lower,Log,FaultFile,FinalMeta,wire,cfg,BODY,entrypoint
from .test_assembly import tx,invoke
@pytest.mark.parametrize('endpoint',['shared','served-secondary','keyed-secondary'])
def test_real_capture_rendered_and_prepared_sent(tmp_path,endpoint,monkeypatch):
 c=cfg(tmp_path,True);c=dataclasses.replace(c,logging=dataclasses.replace(c.logging,capture_rendered=True))
 u=entrypoint(c);rendered='Supplied template rendering, NOT native template proof.'
 if endpoint!='shared':
  if endpoint=='keyed-secondary':
   monkeypatch.setenv('C21_FIXTURE_API_KEY','supplied-key')
   c=dataclasses.replace(c,routing=dataclasses.replace(c.routing,backends={'secondary':dataclasses.replace(c.routing.backends['secondary'],api_key_env='C21_FIXTURE_API_KEY')}))
  with patch.object(server.ThreadingHTTPServer,'__init__',return_value=None):s=server.CriaServer(c,Log(),u)
  u=s.router.endpoint_for('reasoner')
 assert callable(getattr(u,'_receive_open',None))
 metadata=endpoint!='keyed-secondary'
 lower=Lower(([wire(json.dumps({'prompt':rendered}).encode())] if metadata else [])+[wire(b'final')]);receipts=[];calls=[];real=rc.open_request
 def supplied(req,*,timeout,receipt=None):
  calls.append({'url':req.full_url,'data_hex':req.data.hex(),'headers':dict(req.header_items()),'captured':receipt is not None})
  if receipt is not None:receipts.append(receipt)
  return real(req,timeout=timeout,receipt=receipt,http_connection=lower.HTTP)
 monkeypatch.setattr(urllib.request,'urlopen',lambda req,timeout:supplied(req,timeout=timeout))
 monkeypatch.setattr(rc,'open_request',supplied)
 response,estimate,path=u._open_with_refit(copy.deepcopy(BODY),False,Log())
 assert response.read()==b'final';response.close();lower.assert_closed()
 expected={**BODY,'stream':False};record=json.loads(Path(path).read_bytes())
 assert record['body']==expected and calls[-1]['data_hex']==json.dumps(expected).encode().hex()
 assert estimate==contextfloor.est_total(expected['messages'],expected.get('tools'))
 assert len(calls)==(2 if metadata else 1)
 if metadata:
  assert calls[0]['url'].endswith('/apply-template') and not calls[0]['captured']
  assert Path(path).with_suffix('.prompt.txt').read_text()==rendered
 else:
  assert not Path(path).with_suffix('.prompt.txt').exists()
  assert calls[0]['headers']['Authorization']=='Bearer supplied-key'
 t=receipts[0];assert t.finished and t.meta.closed and not t.failed
 assert b''.join(Path(p).read_bytes() for p in t.files())==lower.sockets[-1].acquired()
 lower.witness(tmp_path,t)
 (tmp_path/'assembly-render.json').write_text(json.dumps({'endpoint':endpoint,'calls':calls,'estimate':estimate,'request_capture':path,'rendered_present':metadata,'receipt_closed':t.finished and t.meta.closed},indent=2)+'\n')
@pytest.mark.parametrize('fault',[None,'close','meta'])
def test_cleanup_before_actual_overflow_owner(tmp_path,fault,monkeypatch):
 body=json.dumps({'error':{'message':'supplied context rejection','n_prompt_tokens':700,'n_ctx':500}}).encode()
 lower=Lower([wire(body,400),wire(b'clean')]);receipts=[];errors=[];timing=[];real=rc.open_request
 def supplied(req,*,timeout,receipt=None):
  if receipt is None:receipt=rc.Receipt(tmp_path/f'baseline-{len(receipts)}',request_sha256=hashlib.sha256(req.data).hexdigest())
  receipts.append(receipt)
  if len(receipts)==1:
   if fault=='close':receipt.origin.sink=FaultFile(receipt.origin.sink,'close')
   if fault=='meta':receipt.meta=FinalMeta(receipt.meta,receipt)
  try:return real(req,timeout=timeout,receipt=receipt,http_connection=lower.HTTP)
  except urllib.error.HTTPError as e:errors.append(e);raise
 kwargs={'capture_dir':tmp_path/'captures','capture_rendered':False,'context_window':49152}
 if 'open_request' in inspect.signature(upstream.Upstream).parameters:kwargs['open_request']=supplied
 u=upstream.Upstream('http://fixture.invalid',**kwargs);runtime=assistruntime.current();original=runtime.capacity.execute;preps=[]
 def overflow(*a,**kw):
  state={'error_closed':errors[0].closed,'finished':receipts[0].finished,'meta_closed':receipts[0].meta.closed,'refs':lower.sockets[0]._io_refs,'raw_closed':all(r.closed for r in lower.sockets[0].raws)}
  timing.append(state);(tmp_path/'pre-real-refit.json').write_text(json.dumps(timing,indent=2)+'\n')
  assert all(state.values()) if state['refs'] else all(v for k,v in state.items() if k!='refs')
  assert state['refs']==0
  return original(*a,**kw)
 def prep(*a,**kw):preps.append(kw);return (b'{}' if len(preps)==1 else b'{"refitted":true}'),335,str(tmp_path/f'prep-{len(preps)}.json')
 selected=dataclasses.replace(runtime.capacity,execute=overflow)
 runtime=dataclasses.replace(runtime,ordered_stages=tuple(selected if d is runtime.capacity else d for d in runtime.ordered_stages))
 monkeypatch.setattr(u,'_prep',prep);monkeypatch.setattr(urllib.request,'urlopen',lambda req,timeout:supplied(req,timeout=timeout))
 result=None;primary=None
 try:
  try:
   with assistruntime.bound(runtime):result=u._open_with_refit({'model':'supplied'},False,Log())
  except BaseException as e:primary=e
  if fault is None:
   assert len(timing)==1 and result is not None and len(receipts)==2
   assert result[0].read()==b'clean';result[0].close()
  else:
   assert isinstance(primary,upstream.UpstreamError) and primary.__cause__ is errors[0]
   assert not timing and len(receipts)==1 and errors[0].closed
   assert receipts[0].finished and receipts[0].meta.closed and receipts[0].failed
  for i,t in enumerate(receipts):
   out=tmp_path/f'receipt-{i}';out.mkdir();lower.witness(out,t)
  lower.assert_closed()
 finally:
  for e in errors:
   try:e.close()
   except BaseException:pass
  for t in receipts:t.finish(primary)
  if result:
   try:result[0].close()
   except BaseException:pass
def test_response_signal_failure_primary_and_secondary(tmp_path):
 lower=Lower([wire(b'body')]);receipt=tx(tmp_path);first=OSError('supplied signal observation failure');calls=[]
 receipt.origin.sink=FaultFile(receipt.origin.sink,'close')
 def observe(req,response):calls.append(response.status);raise first
 try:
  with pytest.raises(OSError) as got:invoke(lower,receipt,observe_response=observe)
  assert got.value is first and calls==[200]
  assert receipt.finished and receipt.meta.closed and receipt.failed and getattr(first,'__notes__',[])
  lower.witness(tmp_path,receipt);lower.assert_closed()
 finally:receipt.finish(first)
def test_non_HTTP_redirect_admission_cannot_be_bypassed(tmp_path,monkeypatch):
 lower=Lower([wire(b'redirect',302,b'Location: ftp://ftp.invalid/file\r\n'),wire(b'never-acquired')]);receipt=tx(tmp_path);admissions=[]
 # Labelled unsupported-protocol fixture: no FTP library, real socket or native owner.
 def supplied_ftp(handler,request):
  connection=lower.HTTP(request.host,timeout=request.timeout)
  connection.request('GET','/file')
  return connection.getresponse()
 monkeypatch.setattr(urllib.request.FTPHandler,'ftp_open',supplied_ftp)
 result=None
 try:
  with pytest.raises(ValueError,match='HTTP/HTTPS'):
   result=invoke(lower,receipt,admit=lambda req:admissions.append(req.full_url))
  assert admissions==['http://fixture.invalid/start','ftp://ftp.invalid/file']
  assert len(lower.factories)==1 and len(lower.connects)==1
  assert not lower.sockets[1].returned and not lower.sockets[1].sent
  assert receipt.finished and receipt.meta.closed
  lower.witness(tmp_path,receipt);lower.assert_closed()
 finally:
  lower.witness(tmp_path,receipt)
  (tmp_path/'admission.json').write_text(json.dumps(admissions)+'\n')
  if result:result.close()
  receipt.finish()
def test_missing_configured_capture_no_lower_dispatch(tmp_path,monkeypatch):
 lower=Lower([wire()]);calls=[];u=upstream.Upstream('http://fixture.invalid',capture_dir=tmp_path/'captures',context_window=49152)
 monkeypatch.setattr(u,'_prep',lambda *a,**k:(b'{}',335,None))
 monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:calls.append('bypass'))
 with pytest.raises(rc.CaptureFailure):u._open_with_refit({'model':'supplied'},False,Log())
 assert not calls and not lower.factories and not lower.sockets[0].returned
