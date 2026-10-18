"""Harness-side authenticated batch markers; no directory-prefix garbage collection."""
from . import ownedfiles

PROGRAM = ownedfiles.DIRECTORY_PROGRAM + r'''
def _seq_open(turn,prefix,participants,deadline):
    return _owned_open(turn,prefix,participants,deadline)

def _seq_mark_identity(context,index):
    if not _owned_valid(context): return None
    try:
        descriptor=os.open(str(index),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=context['fd'])
        with os.fdopen(descriptor,'rb') as stream:
            actual=os.fstat(stream.fileno())
            payload=(context['credential']+':'+str(index)).encode()
            if not stat.S_ISREG(actual.st_mode) or stream.read(len(payload)+1)!=payload: return None
            named=os.stat(str(index),dir_fd=context['fd'],follow_symlinks=False)
            return _owned_id(actual) if _owned_id(actual)==_owned_id(named) else None
    except OSError:
        return None

def _seq_missing(context,predecessors):
    return [index for index in predecessors if _seq_mark_identity(context,index) is None]

def _seq_done(context,index):
    try:
        if index not in context['scope'] or not _owned_valid(context): return
        try:
            marker=os.open(str(index),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=context['fd'])
            with os.fdopen(marker,'wb') as stream:
                stream.write((context['credential']+':'+str(index)).encode())
        except FileExistsError:
            if _seq_mark_identity(context,index) is None: return
        observed={value:_seq_mark_identity(context,value) for value in context['scope']}
        if any(identity is None for identity in observed.values()): return
        for value,identity in observed.items():
            if not _owned_valid(context): return
            named=os.stat(str(value),dir_fd=context['fd'],follow_symlinks=False)
            if _owned_id(named)!=identity: return
            os.unlink(str(value),dir_fd=context['fd'])
        if _owned_valid(context) and set(os.listdir(context['fd']))=={'.owner'}:
            os.unlink('.owner',dir_fd=context['fd'])
            if _owned_valid(context,owner=False): os.rmdir(context['name'],dir_fd=context['parent_fd'])
    except OSError:
        pass
    finally:
        _owned_close(context)

'''
