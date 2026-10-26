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

def _owned_listing(descriptor,identity,label):
    # What an authenticated directory holds NOW. A descriptor can keep answering from the moment it was opened on
    # some filesystems (btrfs: entries added afterwards are invisible), so the directory is listed through a FRESH
    # descriptor opened relative to the authenticated one and closed here. Same directory, same inode, checked
    # against ``identity`` — the certificate's for the root, the caller's already-checked one for a nested
    # directory: never a path, never a prefix, nothing widened. The ONLY place a program lists a directory.
    probe=os.open('.',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
    try:
        if _owned_id(os.fstat(probe))!=identity: raise OSError(errno.ESTALE,os.strerror(errno.ESTALE),label)
        return os.listdir(probe)
    finally:
        os.close(probe)

def _owned_names(context):
    return _owned_listing(context['fd'],context['root'],context['name'])

def _owned_abandon(context,allocated_owner):
    # Only a fresh allocation can authorize settlement of an incomplete record.
    # Keep the original descriptors open until every identity check is finished.
    try:
        if not _owned_valid(context,owner=False): return
        if allocated_owner is not None:
            marker=os.stat('.owner',dir_fd=context['fd'],follow_symlinks=False)
            if not stat.S_ISREG(marker.st_mode) or tuple(_owned_id(marker))!=allocated_owner: return
            os.unlink('.owner',dir_fd=context['fd'])
        if _owned_valid(context,owner=False) and not _owned_names(context):
            os.rmdir(context['name'],dir_fd=context['parent_fd'])
    except OSError:
        pass

class _OwnedRetireError(OSError):
    pass

def _owned_drop(parent_fd,name,identity):
    # Remove ``name`` from the parent ONLY while it is still the inode we linked there. True: it is gone (removed now,
    # or already absent). False: something else occupies the name; it is left exactly as found.
    try:
        value=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
    except FileNotFoundError:
        return True
    if not stat.S_ISREG(value.st_mode) or _owned_id(value)!=identity: return False
    os.unlink(name,dir_fd=parent_fd)
    return True

def _owned_hold(context,source,identity):
    # A second, EXCLUSIVE name for ``source`` in the parent (an existing name is never replaced), plus a descriptor on
    # the inode that name holds for as long as the removal lasts. What was linked must be the inode the caller
    # authenticated; otherwise only the name created here is removed and ``source`` is left exactly as found.
    parent=context['parent_fd']
    link=context['name']+'.retiring'+('' if source=='.owner' else source)
    os.link(source,link,src_dir_fd=context['fd'],dst_dir_fd=parent,follow_symlinks=False)
    descriptor=os.open(link,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    current=os.fstat(descriptor)
    if not stat.S_ISREG(current.st_mode) or _owned_id(current)!=identity:
        os.close(descriptor)
        _owned_drop(parent,link,_owned_id(current))
        raise _OwnedRetireError(errno.ESTALE,source+'_identity_changed',context['name'])
    return [source,link,identity,descriptor]

def _owned_restore(context,held,gone,error):
    # The directory could not be removed. Every name taken out of it goes back AS THE SAME INODE (linked from the
    # descriptor verified when it was held — never from a name, never rewritten), then the extra name is removed only
    # while it is still that inode. Anything that cannot be put back, or no longer matches, is left exactly as found
    # and reported together with the original error; nothing is overwritten, adopted or retried.
    problems=[]
    for item in held:
        source,link,identity,descriptor=item
        if item in gone:
            try:
                if os.fstat(descriptor).st_nlink==0:
                    raise OSError(errno.ENOENT,'the original inode no longer has any name (the retiring name was replaced)')
                os.link('/proc/self/fd/'+str(descriptor),source,dst_dir_fd=context['fd'],follow_symlinks=True)
            except OSError as blocked:
                problems.append(source+' was not restored ('+str(blocked)+'); '+link+' left as found')
                continue
        else:
            # Never unlinked from the directory. The extra name is disposable ONLY while the original is still named
            # there; if that name is gone or now belongs to something else, the extra name is the original's last one.
            try:
                current=os.stat(source,dir_fd=context['fd'],follow_symlinks=False)
                named=stat.S_ISREG(current.st_mode) and _owned_id(current)==identity
            except FileNotFoundError:
                named=False
            except OSError:
                named=None
            if not named:
                problems.append(source+' in the directory is '+('unreadable' if named is None else 'no longer the original (left untouched)')+'; the original inode is kept as '+link)
                continue
        try:
            if not _owned_drop(context['parent_fd'],link,identity):
                problems.append(link+' is no longer the held inode and was left in place')
        except OSError as failed:
            problems.append(link+' could not be removed ('+str(failed)+')')
    if problems:
        raise _OwnedRetireError(errno.EEXIST,'not_restored: '+'; '.join(problems)+'; original error: '+repr(error),context['name']) from error

def _owned_retire(context,facts=None):
    # Remove the authenticated directory. The certificate — and each authoritative ``facts`` file the caller verified
    # (name -> identity) — leaves it ONLY for the instant of removal, as a second name for the same inode in the parent,
    # and goes back as that inode if the directory cannot be removed. A writer that lands after the last listing
    # therefore leaves a certified directory (and its completion facts) and an accurate error, so the removal can be
    # repeated; it never leaves an uncertified one. No recovery or retry here. Process death between the first link and
    # the end of this function leaves ``<name>.retiring*`` in the parent and a directory without them; nothing repairs that.
    fd,parent,name=context['fd'],context['parent_fd'],context['name']
    if not _owned_valid(context): raise _OwnedRetireError(errno.ESTALE,'namespace_identity_changed',name)
    held,gone=[],[]
    try:
        try:
            for source,identity in [('.owner',context['owner'])]+sorted((facts or {}).items()):
                held.append(_owned_hold(context,source,identity))
            for item in held[1:]+held[:1]:                              # the facts first, the certificate last
                value=os.stat(item[0],dir_fd=fd,follow_symlinks=False)
                if not stat.S_ISREG(value.st_mode) or _owned_id(value)!=item[2]:
                    raise _OwnedRetireError(errno.ESTALE,item[0]+'_identity_changed',name)
                os.unlink(item[0],dir_fd=fd)
                gone.append(item)
            if not _owned_valid(context,owner=False): raise _OwnedRetireError(errno.ESTALE,'namespace_identity_changed',name)
            os.rmdir(name,dir_fd=parent)
        except BaseException as error:
            _owned_restore(context,held,gone,error)
            raise
        left=[item[1] for item in held if not _owned_drop(parent,item[1],item[2])]
        if left: raise _OwnedRetireError(errno.ESTALE,'directory removed, but '+', '.join(left)+' is not the held inode and was left in place',name)
    finally:
        for item in held: os.close(item[3])

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
