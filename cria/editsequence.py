"""Harness-side authenticated batch markers; no directory-prefix garbage collection."""
from . import ownedfiles

_HD_PY = "__CRIA_PY_EOF__"
EDIT_SEQ_DIR = ".cria-edits-"            # under $TMPDIR (else /tmp) — never in the user's tree
EDIT_SEQ_WAIT_SECONDS = 5     # under the ~10 s a harness's exec yields without a budget (probegate.GATE_POLL_WAIT_S)

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
        if _owned_valid(context) and set(_owned_names(context))=={'.owner'}: _owned_retire(context)
    except OSError:
        pass
    finally:
        _owned_close(context)

'''


def _seq_release(sequence: "tuple") -> str:
    """A refused call completes only its authenticated marker, never a name-shaped file."""
    turn, idx, _preds, participants = sequence
    py = (PROGRAM + '\ntry:\n'
          + f'    _sequence=_seq_open({turn!r},{EDIT_SEQ_DIR!r},{participants!r},time.monotonic()+{EDIT_SEQ_WAIT_SECONDS!r})\n'
          + f'    _seq_done(_sequence,{idx!r})\n'
          + 'except (OSError,ValueError):\n    pass\n')
    return f"python3 - <<'{_HD_PY}'\n{py}{_HD_PY}\n"
