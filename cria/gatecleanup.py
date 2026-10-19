"""Private harness gate resources; NEVER infer ownership of workspace output."""
import json
import shlex
from . import ownedfiles

PRIVATE_PREFIX = '.gate-private-'

NAMESPACE_PROGRAM = ownedfiles.DIRECTORY_PROGRAM + r'''
def _gate_namespace(token,parent=None,create=False):
    return _owned_open(token,'%%PREFIX%%',['gate'],time.monotonic()+(5 if create else 0),
                       parent_path=parent,create=create)

def _gate_spool_name(token):
    return '.cria-gate-'+token+'.spool'

def _gate_reader_open(path,token):
    namespace=os.path.dirname(os.path.abspath(path))
    if os.path.basename(namespace)!='%%PREFIX%%'+token or os.path.basename(path)!=_gate_spool_name(token):
        raise ValueError('unowned_transport_namespace')
    context=_gate_namespace(token,os.path.dirname(namespace))
    try:
        descriptor=os.open(_gate_spool_name(token),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=context['fd'])
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError('invalid_transport_file')
        return context,descriptor
    except BaseException:
        _owned_close(context)
        raise

def _gate_done(context,token):
    if not _owned_valid(context): raise ValueError('namespace_identity_changed')
    try:
        value=os.stat(_gate_spool_name(token)+'.done',dir_fd=context['fd'],follow_symlinks=False)
        return stat.S_ISREG(value.st_mode)
    except FileNotFoundError:
        return False

def _gate_reader_wait(context,token,wait_s):
    deadline=time.monotonic()+wait_s
    while not _gate_done(context,token) and time.monotonic()<deadline:
        time.sleep(.2)
    return _gate_done(context,token)

'''.replace('%%PREFIX%%', PRIVATE_PREFIX)

OPERATIONS_PROGRAM = NAMESPACE_PROGRAM + r'''import hashlib,subprocess,sys,shutil

def _gate_create(context,name,data=b''):
    if not _owned_valid(context): raise ValueError('namespace_identity_changed')
    descriptor=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=context['fd'])
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(data)

def _gate_clear(context,descriptor,prefix,removed,failed):
    if not _owned_valid(context):
        failed.append(dict(path=prefix,error='namespace_identity_changed'))
        return
    for name in os.listdir(descriptor):
        relative=prefix+name
        try:
            before=os.stat(name,dir_fd=descriptor,follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode):
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
                try:
                    if _owned_id(os.fstat(child))!=_owned_id(before): raise ValueError('directory_identity_changed')
                    _gate_clear(context,child,relative+'/',removed,failed)
                finally:
                    os.close(child)
                if _owned_id(os.stat(name,dir_fd=descriptor,follow_symlinks=False))!=_owned_id(before):
                    raise ValueError('directory_identity_changed')
                os.rmdir(name,dir_fd=descriptor)
                removed.append(relative+'/')
            else:
                if _owned_id(os.stat(name,dir_fd=descriptor,follow_symlinks=False))!=_owned_id(before):
                    raise ValueError('entry_identity_changed')
                os.unlink(name,dir_fd=descriptor)
                removed.append(relative)
        except FileNotFoundError:
            pass
        except (OSError,ValueError) as error:
            failed.append(dict(path=relative,error=str(error)))

def _gate_aux_cleanup(context):
    removed,failed=[],[]
    try:
        if not _owned_valid(context): raise ValueError('namespace_identity_changed')
        descriptor=os.open('aux',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=context['fd'])
        try:
            identity=_owned_id(os.fstat(descriptor))
            if identity!=context['aux_identity']: raise ValueError('directory_identity_changed')
            _gate_clear(context,descriptor,'aux/',removed,failed)
        finally:
            os.close(descriptor)
        if not _owned_valid(context): raise ValueError('namespace_identity_changed')
        if _owned_id(os.stat('aux',dir_fd=context['fd'],follow_symlinks=False))!=identity:
            raise ValueError('directory_identity_changed')
        os.rmdir('aux',dir_fd=context['fd'])
        removed.append('aux/')
    except (OSError,ValueError) as error:
        failed.append(dict(path='aux',error=str(error)))
    return dict(removed=removed,failed=failed)

def _gate_run_script(context,name,environment,output):
    descriptor=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=context['fd'])
    try:
        path='/dev/fd/'+str(descriptor)
        if _owned_id(os.stat(path))!=_owned_id(os.fstat(descriptor)): raise ValueError('script_identity_changed')
        shell=shutil.which('bash') or shutil.which('sh')
        if shell is None: raise FileNotFoundError('sh')
        return subprocess.run([shell,path],stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,
                              env=environment,pass_fds=(descriptor,)).returncode
    finally:
        os.close(descriptor)

'''

PROGRAM = OPERATIONS_PROGRAM + r'''
mode,token=sys.argv[1:3]
if mode=='launch':
    request=json.load(sys.stdin)
    context=_gate_namespace(token,create=True)
    fingerprint=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest().encode()
    try:
        try:
            _gate_create(context,'.started',fingerprint)
        except FileExistsError:
            marker=os.open('.started',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=context['fd'])
            with os.fdopen(marker,'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read(len(fingerprint)+1)!=fingerprint:
                    raise ValueError('transport_request_changed')
            sys.exit(0)
        _gate_create(context,'request.json',json.dumps(request).encode())
        _gate_create(context,'.cria-gate-'+token+'-cmd.sh',request['body'].encode())
        _gate_create(context,'survey.sh',request['survey'].encode())
        _gate_create(context,_gate_spool_name(token))
        os.mkdir('aux',0o700,dir_fd=context['fd'])
        subprocess.Popen([sys.executable,'-c',_gate_program,'worker',token,context['parent_path']],
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         start_new_session=True,close_fds=True)
    finally:
        _owned_close(context)
elif mode=='worker':
    context=_gate_namespace(token,sys.argv[3])
    try:
        descriptor=os.open('request.json',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=context['fd'])
        with os.fdopen(descriptor,'r') as stream: request=json.load(stream)
        workspace=request['workspace'] or os.getcwd()
        original,scope_errors={},[]
        for directory in request['scope_dirs'] or [workspace]:
            try: original[directory]=_owned_id(os.stat(directory))
            except OSError as error: scope_errors.append(dict(path=directory,error=str(error)))
        context['aux_identity']=_owned_id(os.stat('aux',dir_fd=context['fd'],follow_symlinks=False))
        environment=dict(os.environ)
        environment['CTX_PROBE_AUX']=os.path.join(context['parent_path'],context['name'],'aux')
        output=os.open(_gate_spool_name(token),os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW,dir_fd=context['fd'])
        with os.fdopen(output,'wb',buffering=0) as stream:
            try:
                _gate_run_script(context,'.cria-gate-'+token+'-cmd.sh',environment,stream)
            finally:
                record=_gate_aux_cleanup(context)
                record['failed'].extend(scope_errors)
                for directory,identity in original.items():
                    try:
                        if _owned_id(os.stat(directory))!=identity: raise ValueError('workspace_identity_changed')
                    except (OSError,ValueError) as error:
                        record['failed'].append(dict(path=directory,error=str(error)))
                record['requested_workspace']=request['workspace']
                record['scope']='original-workspace; project-native outputs are not owned auxiliary scratch'
                stream.write(('\n'+request['cleanup_marker']+'\n'+json.dumps(record)+'\n').encode())
                _gate_run_script(context,'survey.sh',os.environ,stream)
        if not _owned_valid(context): raise ValueError('namespace_identity_changed')
        os.unlink('.cria-gate-'+token+'-cmd.sh',dir_fd=context['fd'])
        os.unlink('survey.sh',dir_fd=context['fd'])
        os.unlink('request.json',dir_fd=context['fd'])
        _gate_create(context,_gate_spool_name(token)+'.done')
    finally:
        _owned_close(context)
elif mode=='dispose':
    path=sys.argv[3]
    namespace=os.path.dirname(os.path.abspath(path))
    if os.path.basename(namespace)!='%%PREFIX%%'+token: raise ValueError('unowned_transport_namespace')
    context=_gate_namespace(token,os.path.dirname(namespace))
    try:
        if not _gate_done(context,token): raise ValueError('transport_still_active')
        # Keep the certificate until descendants are gone, so every mutation is
        # bound to the originally allocated directory, not an age/name scan.
        owner=os.open('.owner',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=context['fd'])
        os.close(owner)
        removed,failed=[],[]
        for name in os.listdir(context['fd']):
            if name=='.owner': continue
            item=os.stat(name,dir_fd=context['fd'],follow_symlinks=False)
            if stat.S_ISDIR(item.st_mode): raise ValueError('unsettled_private_scratch')
            if not _owned_valid(context): raise ValueError('namespace_identity_changed')
            os.unlink(name,dir_fd=context['fd'])
        if not _owned_valid(context): raise ValueError('namespace_identity_changed')
        os.unlink('.owner',dir_fd=context['fd'])
        if _owned_valid(context,owner=False): os.rmdir(context['name'],dir_fd=context['parent_fd'])
    finally:
        _owned_close(context)
else:
    raise ValueError('unknown_resource_operation')
'''.replace('%%PREFIX%%', PRIVATE_PREFIX)


def launch_command(runner: str, token: str, workspace: str, body: str, survey: str, marker: str,
                   scope_dirs: tuple[str, ...] = ()) -> str:
    payload = json.dumps(dict(workspace=workspace, body=body, survey=survey, cleanup_marker=marker,
                              scope_dirs=list(scope_dirs)))
    return (runner + ' gate launch ' + shlex.quote(token) + " <<'__CTX_GATE_REQUEST__'\n"
            + payload + '\n__CTX_GATE_REQUEST__\n')


def dispose_command(runner: str, token: str, path: str) -> str:
    return runner + ' gate dispose ' + shlex.quote(token) + ' ' + shlex.quote(path)


def report(text: str | None, expected_workspace: str | None = None) -> tuple[list[str], list[dict]] | None:
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    if expected_workspace is not None and value.get('requested_workspace') != expected_workspace:
        return None
    removed, failed = value.get('removed'), value.get('failed')
    if not isinstance(removed, list) or not all(isinstance(p, str) for p in removed):
        return None
    if not isinstance(failed, list) or not all(isinstance(p, dict)
            and isinstance(p.get('path'), str) and isinstance(p.get('error'), str) for p in failed):
        return None
    return removed, failed
