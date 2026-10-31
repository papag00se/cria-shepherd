"""Operator-run retention: explicit authority, dry run by default, fail-closed safety."""
import fcntl,hashlib,io,json,os,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from cria import imagepersist,imagestore,retention,writeproxy
from cria.imageprotocol import CoderRoute,ImageUnavailable
from cria.imagestore import ImageStore
from cria.multipart_bridge import Bridge,BridgeError
sys.path.insert(0,str(Path(__file__).parent/'multipart'))
from test_server_integration import shell
from test_workflow_store import IMAGE,TASK

DAY=86400


def run(home,*argv):
    out=io.StringIO();code=retention.main([argv[0],'--home',str(home),*argv[1:]],out=out)
    return code,out.getvalue()


def tree(root):
    return sorted((str(p.relative_to(root)),p.lstat().st_mtime_ns,p.lstat().st_size) for p in root.rglob('*'))


def make_multipart(home,tmp_path,session):
    """A registered, first-page-delivered read, persisted exactly as the bridge does."""
    f=tmp_path/('f-'+hashlib.sha256(session.encode()).hexdigest()[:6]);f.write_text(''.join('%08x\n'%(i*2654435761%2**32) for i in range(5000)))
    tool={'name':'exec_command','schema':{'properties':{'cmd':{'type':'string'}}}}
    tc={'id':'orig-'+hashlib.sha256(session.encode()).hexdigest()[:6],'type':'function','function':{'name':'read_file','arguments':json.dumps({'path':str(f)})}}
    comp={'choices':[{'message':{'tool_calls':[tc]}}]};bridge=Bridge(str(home/'multipart'));log=SimpleNamespace(emit=lambda *a,**k:None)
    writeproxy.translate_outbound(comp,tool,log,injected={'read_file'},workspace_root=str(tmp_path),
        multipart_command=lambda o,e,r:bridge.register(session,o,e,tool,r))
    bridge.bind(session,comp);call=comp['choices'][0]['message']['tool_calls'][0]
    messages=[{'role':'assistant','tool_calls':[call]},{'role':'tool','tool_call_id':call['id'],
        'content':shell(json.loads(call['function']['arguments'])['cmd'])}]
    _,calls,_=bridge.incoming(session,messages)
    messages+=[{'role':'assistant','tool_calls':calls},{'role':'tool','tool_call_id':calls[0]['id'],
        'content':shell(json.loads(calls[0]['function']['arguments'])['cmd'])}]
    return bridge,messages


def make_image(home,key):
    store=ImageStore(home/'images',close_authority=object());s=store.session(key)
    s.select_route(CoderRoute(object(),'m','r',True));s.prepare([{'role':'user','content':[IMAGE]}],TASK)
    return store,s


def age(path,days):
    t=time.time()-days*DAY
    marker=path.parent/(path.name+'.owner.json')
    for p in [path,*(path.rglob('*') if path.is_dir() and not path.is_symlink() else []),*([marker] if marker.exists() else [])]:
        os.utime(p,(t,t),follow_symlinks=False)


def mp(home,sid):return home/'multipart'/(hashlib.sha256(sid.encode()).hexdigest()+'.json')


@pytest.fixture
def home(tmp_path):
    h=tmp_path/'home';h.mkdir(mode=0o700);return h


def exit_process(*sessions):
    for s in sessions:s._hold.close()   # a dead process's flock is gone


def test_list_shows_kind_size_age_state_for_every_entry(home,tmp_path):
    make_multipart(home,tmp_path,'sid:one');_,s=make_image(home,'img-key');exit_process(s)
    age(mp(home,'sid:one'),3)
    code,text=run(home,'list');assert code==0
    lines=text.splitlines()
    assert lines[0].startswith('KIND') and any(l.startswith('multipart') and 'sid:one' in l and '3d' in l and 'unknown' in l for l in lines)
    assert any(l.startswith('image') and 'img-key' in l and 'unknown' in l and 'image-session-' in l for l in lines)
    data=json.loads(run(home,'list','--json')[1]);assert {e['kind'] for e in data['entries']}=={'multipart','image'}
    assert all(e['size']>0 for e in data['entries'])
    assert [e['kind'] for e in json.loads(run(home,'list','--json','--kind','image')[1])['entries']]==['image']


def test_prune_requires_a_selector_and_is_dry_run_by_default(home,tmp_path):
    make_multipart(home,tmp_path,'sid:one');_,s=make_image(home,'k');exit_process(s)
    age(mp(home,'sid:one'),30);age(s._root,30)
    assert run(home,'prune')[0]==2 and run(home,'prune','--apply')[0]==2
    before=(tree(home/'multipart'),tree(home/'images'))
    code,text=run(home,'prune','--older-than','14d');assert code==0
    assert 'DRY RUN' in text and 'would remove 2' in text and 'nothing was removed' in text
    assert before==(tree(home/'multipart'),tree(home/'images'))


def test_apply_removes_only_the_selected_entries(home,tmp_path):
    make_multipart(home,tmp_path,'sid:old');make_multipart(home,tmp_path,'sid:new')
    _,old=make_image(home,'old-img');_,new=make_image(home,'new-img');exit_process(old,new)
    age(mp(home,'sid:old'),30);age(old._root,30);age(old._root.parent/(old._root.name+'.owner.json'),30)
    code,text=run(home,'prune','--older-than','14d','--apply');assert code==0
    assert text.index('APPLY')<text.index('removed multipart')   # the plan is printed before deleting
    assert not mp(home,'sid:old').exists() and mp(home,'sid:new').exists()
    assert not old._root.exists() and new._root.exists()
    assert not (home/'images'/(old._root.name+'.owner.json')).exists()
    # --kind and --session narrow further
    assert run(home,'prune','--session','sid:new','--kind','image','--apply')[0]==0 and mp(home,'sid:new').exists()
    assert run(home,'prune','--session','sid:new','--kind','multipart','--apply')[0]==0 and not mp(home,'sid:new').exists()
    assert new._root.exists()
    assert run(home,'prune','--session','new-img','--apply')[0]==0 and not new._root.exists()


def test_session_prefix_must_be_unambiguous_enough_and_never_matches_everything(home,tmp_path):
    make_multipart(home,tmp_path,'sid:a');make_multipart(home,tmp_path,'sid:b')
    code,text=run(home,'prune','--session','nomatch','--apply');assert 'removed' not in text and mp(home,'sid:a').exists()


def test_live_image_session_is_skipped_even_when_selected(home):
    store,s=make_image(home,'live');age(s._root,60)
    code,text=run(home,'prune','--older-than','1d','--apply')
    assert 'held by a live cria process' in text and s._root.exists()
    assert run(home,'list')[1].count('active')==1
    exit_process(s)
    assert run(home,'prune','--older-than','1d','--apply')[0]==0 and not s._root.exists()


def test_multipart_state_lock_held_by_a_live_process_skips_everything(home,tmp_path):
    make_multipart(home,tmp_path,'sid:x');age(mp(home,'sid:x'),30)
    fd=os.open(home/'multipart'/'.lock',os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX)
    try:
        code,text=run(home,'prune','--older-than','1d','--apply')
        assert 'lock is held by a live cria process' in text and mp(home,'sid:x').exists()
    finally:os.close(fd)
    assert run(home,'prune','--older-than','1d','--apply')[0]==0 and not mp(home,'sid:x').exists()


def test_symlinks_traversal_and_escape_are_refused(home,tmp_path):
    outside=tmp_path/'outside';outside.mkdir();(outside/'precious').write_text('keep')
    images=home/'images';images.mkdir(mode=0o700)
    (images/'image-session-link').symlink_to(outside);(images/'image-session-..x').mkdir(mode=0o700)
    (images/'..').mkdir(exist_ok=True) if False else None
    mpdir=home/'multipart';mpdir.mkdir(mode=0o700)
    victim=outside/'victim.json';victim.write_text('{}')
    (mpdir/('a'*64+'.json')).symlink_to(victim)
    (mpdir/'../escape.json' if False else mpdir/'notes.txt').write_text('stray')
    for p in (images/'image-session-link',mpdir/('a'*64+'.json')):age(p,99)
    code,text=run(home,'prune','--older-than','1d','--session','a'*64,'--apply')
    code2,text2=run(home,'prune','--older-than','1d','--apply')
    for t in (text,text2):assert 'removed' not in t
    assert 'refused' in text+text2
    assert (outside/'precious').read_text()=='keep' and victim.read_text()=='{}'
    assert (images/'image-session-link').is_symlink() and (mpdir/('a'*64+'.json')).is_symlink() and (mpdir/'notes.txt').exists()
    assert 'ignored' in run(home,'list')[1]


def test_symlinked_retention_root_is_refused(home,tmp_path):
    real=tmp_path/'real';real.mkdir(mode=0o700);(real/('b'*64+'.json')).write_text('{}')
    (home/'multipart').symlink_to(real)
    code,text=run(home,'prune','--older-than','0s','--apply')
    assert 'refused' in text and (real/('b'*64+'.json')).exists()


def test_corrupt_multipart_is_reported_and_removed_only_by_explicit_session(home,tmp_path):
    make_multipart(home,tmp_path,'sid:bad');path=mp(home,'sid:bad');path.write_text('{"truncated"');age(path,40)
    assert 'corrupt' in run(home,'list')[1]
    code,text=run(home,'prune','--older-than','1d','--apply')
    assert 'skipped: corrupt' in text and path.exists()
    code,text=run(home,'prune','--session','sid:bad','--apply')
    assert code==0 and not path.exists()


def test_corrupt_image_is_reported_and_removed_only_by_explicit_session(home):
    _,s=make_image(home,'bad');exit_process(s)
    (s._root/imagepersist.STATE_NAME).write_text('{"version":1}');age(s._root,40)
    text=run(home,'list')[1];assert 'corrupt' in text
    code,text=run(home,'prune','--older-than','1d','--apply')
    assert 'skipped: corrupt' in text and s._root.exists()
    code,text=run(home,'prune','--session',s._root.name,'--apply')
    assert code==0 and not s._root.exists() and not (home/'images'/(s._root.name+'.owner.json')).exists()


def test_image_without_owner_marker_is_corrupt_and_never_trusted(home):
    _,s=make_image(home,'nomarker');exit_process(s);(home/'images'/(s._root.name+'.owner.json')).unlink();age(s._root,40)
    code,text=run(home,'prune','--older-than','1d','--apply')
    assert 'skipped: corrupt' in text and s._root.exists()


def test_image_cleanup_seals_marker_before_payload_and_retries_after_partial_deletion(home,monkeypatch):
    _,s=make_image(home,'partial');exit_process(s);age(s._root,40)
    marker=home/'images'/(s._root.name+'.owner.json')
    def partial(directory):
        (directory/imagepersist.STATE_NAME).unlink()
        raise OSError('injected crash during payload deletion')
    real=imagestore.shutil.rmtree;monkeypatch.setattr(imagestore.shutil,'rmtree',partial)
    code,text=run(home,'prune','--older-than','1d','--apply')
    assert code==1 and 'FAILED' in text and 'safe to re-run' in text
    assert s._root.exists() and json.loads(marker.read_text())['closed']   # seal precedes payload deletion
    assert 'closed' in run(home,'list')[1]
    # a later cria cannot restore the half-deleted generation
    with pytest.raises(ImageUnavailable):ImageStore(home/'images',close_authority=object()).restore_session(
        {'owner':'session-images','directory':s._root.name,'generation':s._generation},recovered_leases=())
    monkeypatch.setattr(imagestore.shutil,'rmtree',real)
    assert run(home,'prune','--older-than','1d','--apply')[0]==0
    assert not s._root.exists() and not marker.exists()
    assert 'no retained entries' in run(home,'list')[1]


def test_orphaned_sealed_marker_after_crash_is_retried(home):
    _,s=make_image(home,'orphan');exit_process(s)
    seal='c'*32;imagepersist.seal_marker(s._root,s._generation,seal)
    import shutil;shutil.rmtree(s._root);age(home/'images'/(s._root.name+'.owner.json'),40)
    assert 'closed' in run(home,'list')[1]
    assert run(home,'prune','--older-than','1d','--apply')[0]==0
    assert not (home/'images'/(s._root.name+'.owner.json')).exists()


def anon_state(home,tmp_path):
    bridge,messages=make_multipart(home,tmp_path,'anon:conv');return bridge,messages


def test_multipart_partial_deletion_leaves_only_associations_that_fail_closed_and_is_retryable(home,tmp_path,monkeypatch):
    bridge,messages=anon_state(home,tmp_path)
    indexes=list((home/'multipart').glob('call-*.json'));assert indexes
    for p in [mp(home,'anon:conv'),*indexes]:age(p,30)
    real=os.unlink
    def flaky(name,*a,**k):
        if str(name).startswith('call-'):raise OSError('injected crash after the record was removed')
        return real(name,*a,**k)
    monkeypatch.setattr(retention.os,'unlink',flaky)
    code,text=run(home,'prune','--older-than','1d','--apply');assert code==1 and 'safe to re-run' in text
    assert not mp(home,'anon:conv').exists() and list((home/'multipart').glob('call-*.json'))
    with pytest.raises(BridgeError):Bridge(str(home/'multipart')).resolve_anonymous(messages)   # no trusted half-state
    monkeypatch.setattr(retention.os,'unlink',real)
    assert 'without a session record' in run(home,'list')[1]
    assert run(home,'prune','--older-than','1d','--apply')[0]==0
    assert not list((home/'multipart').glob('call-*.json'))


def test_pruned_under_a_live_conversation_fails_closed_never_a_fabricated_read(home,tmp_path):
    # named session: the harness keeps sending history that names our private continuation calls
    bridge,messages=make_multipart(home,tmp_path,'sid:live');age(mp(home,'sid:live'),30)
    assert run(home,'prune','--session','sid:live','--apply')[0]==0
    with pytest.raises(BridgeError):Bridge(str(home/'multipart')).incoming('sid:live',messages)
    with pytest.raises(BridgeError):bridge.incoming('sid:live',messages)   # even the live in-memory bridge
    # anonymous conversation: the producer-issued call is no longer recognized
    abridge,amessages=anon_state(home,tmp_path)
    assert run(home,'prune','--session','anon:conv','--apply')[0]==0
    with pytest.raises(BridgeError):abridge.resolve_anonymous(amessages)


def test_live_bridge_access_serializes_with_prune_and_then_sees_removal(home,tmp_path):
    bridge,messages=make_multipart(home,tmp_path,'sid:race');age(mp(home,'sid:race'),30)
    entries,_,fds,notes=retention.collect(home,('multipart',),lock_multipart=True)   # prune holds the state lock
    assert not notes;result=[]
    def live():
        try:result.append(bridge.incoming('sid:race',messages))
        except BridgeError as exc:result.append(exc)
    t=threading.Thread(target=live);t.start();t.join(0.4)
    assert t.is_alive()   # the live bridge waits on the shared lock instead of reading half-deleted state
    retention._delete_multipart(fds['multipart'],next(e for e in entries if e.label=='sid:race'))
    retention._close(fds);t.join(5)
    assert not t.is_alive() and isinstance(result[0],BridgeError)


def test_prune_while_live_bridge_hammers_state_never_corrupts_or_fabricates(home,tmp_path):
    bridge,messages=make_multipart(home,tmp_path,'sid:hammer');age(mp(home,'sid:hammer'),30)
    stop=threading.Event();seen=[]
    def hammer():
        while not stop.is_set():
            try:bridge.incoming('sid:hammer',messages);seen.append('ok')
            except BridgeError:seen.append('closed')
    t=threading.Thread(target=hammer);t.start()
    try:
        for _ in range(200):
            if run(home,'prune','--session','sid:hammer','--apply')[1].count('removed multipart'):break
            time.sleep(0.01)
    finally:stop.set();t.join(5)
    assert not mp(home,'sid:hammer').exists() and seen[-1]=='closed'
    assert 'ok' not in seen[seen.index('closed'):]   # once removed it never reads again
