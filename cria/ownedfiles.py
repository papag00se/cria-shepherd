"""Shared resource programs sent to the harness; no harness filesystem I/O here."""

TEMP_SUFFIX = '.tmp-partial'

ATOMIC_REPLACE_PROGRAM = r'''import errno,os,stat,tempfile

class _TargetMutationUncertain(OSError):
    pass

def _atomic_replace(path, data, preserve=False):
    path=os.fspath(path)
    parent=os.path.dirname(path) or '.'
    fd,tmp=tempfile.mkstemp(prefix='.atomic-',suffix='%%SUFFIX%%',dir=parent)
    identity=os.fstat(fd)
    committed=False
    target_attempted=False
    def owned():
        try: current=os.lstat(tmp)
        except FileNotFoundError: return False
        return stat.S_ISREG(current.st_mode) and (current.st_dev,current.st_ino)==(identity.st_dev,identity.st_ino)
    try:
        try:
            with os.fdopen(fd,'wb') as stream:
                fd=None
                count=stream.write(data)
                if count!=len(data): raise OSError(errno.EIO,os.strerror(errno.EIO),tmp)
                stream.flush()
                if preserve:
                    source=os.stat(path)
                    os.fchmod(stream.fileno(),source.st_mode&0o7777)
                    try: os.fchown(stream.fileno(),source.st_uid,source.st_gid)
                    except OSError: pass
                else:
                    mask=os.umask(0); os.umask(mask)
                    os.fchmod(stream.fileno(),0o666&~mask)
            if not owned(): raise OSError(errno.ESTALE,os.strerror(errno.ESTALE),tmp)
            target_attempted=True
            os.replace(tmp,path)
            committed=True
        finally:
            if fd is not None: os.close(fd)
            if not committed and owned(): os.unlink(tmp)
    except OSError as error:
        if target_attempted: raise _TargetMutationUncertain(*error.args) from error
        raise

'''.replace('%%SUFFIX%%', TEMP_SUFFIX)

# One credentialed directory capability for batch markers and gate scratch.
# Creation is exclusive; reuse authenticates its actual descriptors and scope.
# Missing/foreign certificates never authorize adoption, truncation or cleanup.
DIRECTORY_PROGRAM = r'''import errno,json,os,stat,time

def _owned_id(value):
    return [value.st_dev,value.st_ino]

def _owned_valid(context, owner=True):
    try:
        if _owned_id(os.fstat(context['parent_fd']))!=context['parent']: return False
        if _owned_id(os.stat(context['parent_path'],follow_symlinks=False))!=context['parent']: return False
        if _owned_id(os.fstat(context['fd']))!=context['root']: return False
        root=os.stat(context['name'],dir_fd=context['parent_fd'],follow_symlinks=False)
        if not stat.S_ISDIR(root.st_mode) or root.st_mode&0o077 or root.st_uid!=os.geteuid(): return False
        if _owned_id(root)!=context['root']: return False
        if owner:
            marker=os.stat('.owner',dir_fd=context['fd'],follow_symlinks=False)
            if not stat.S_ISREG(marker.st_mode) or _owned_id(marker)!=context['owner']: return False
        return True
    except OSError:
        return False

def _owned_abandon(context,allocated_owner):
    # Only a fresh allocation can authorize settlement of an incomplete record.
    # Keep the original descriptors open until every identity check is finished.
    try:
        if not _owned_valid(context,owner=False): return
        if allocated_owner is not None:
            marker=os.stat('.owner',dir_fd=context['fd'],follow_symlinks=False)
            if not stat.S_ISREG(marker.st_mode) or tuple(_owned_id(marker))!=allocated_owner: return
            os.unlink('.owner',dir_fd=context['fd'])
        if _owned_valid(context,owner=False) and not os.listdir(context['fd']):
            os.rmdir(context['name'],dir_fd=context['parent_fd'])
    except OSError:
        pass

def _owned_open(credential,prefix,scope,deadline,*,parent_path=None,create=True):
    if not credential or '/' in credential or credential in ('.','..'): raise ValueError(credential)
    parent_path=os.path.realpath(parent_path or os.environ.get('TMPDIR') or '/tmp')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    parent=os.open(parent_path,flags)
    descriptor=None
    context=None
    allocated_owner=None  # immutable allocation authority, never an authentication observation
    created=False
    try:
        name=prefix+credential
        if create:
            try:
                os.mkdir(name,0o700,dir_fd=parent)
                created=True
            except FileExistsError:
                pass
        descriptor=os.open(name,flags,dir_fd=parent)
        context=dict(parent_fd=parent,parent_path=parent_path,fd=descriptor,name=name,
                     credential=credential,scope=list(scope),parent=_owned_id(os.fstat(parent)),
                     root=_owned_id(os.fstat(descriptor)))
        def record(owner):
            return dict(credential=credential,namespace=prefix,scope=context['scope'],parent=context['parent'],
                        root=context['root'],owner=owner)
        if created:
            marker=os.open('.owner',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=descriptor)
            allocated_owner=tuple(_owned_id(os.fstat(marker)))
            with os.fdopen(marker,'wb') as stream:
                stream.write(json.dumps(record(list(allocated_owner)),sort_keys=True).encode())
        while True:
            try:
                marker=os.open('.owner',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
                with os.fdopen(marker,'rb') as stream:
                    marker_stat=os.fstat(stream.fileno())
                    if not stat.S_ISREG(marker_stat.st_mode): raise ValueError(name)
                    candidate=dict(context,owner=_owned_id(marker_stat))
                    expected=json.dumps(record(candidate['owner']),sort_keys=True).encode()
                    if stream.read(len(expected)+1)==expected and _owned_valid(candidate): return candidate
            except FileNotFoundError:
                pass
            if time.monotonic()>=deadline: raise PermissionError(errno.EACCES,os.strerror(errno.EACCES),name)
            time.sleep(.05)
    except BaseException:
        if created and context is not None: _owned_abandon(context,allocated_owner)
        if descriptor is not None: os.close(descriptor)
        os.close(parent)
        raise

def _owned_close(context):
    os.close(context['fd'])
    os.close(context['parent_fd'])

'''
