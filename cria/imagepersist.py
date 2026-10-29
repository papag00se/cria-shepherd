"""Owned private image state; no workspace access or lifecycle authority."""
import json
import os
from pathlib import Path
import tempfile
from .imageprotocol import ImageUnavailable

STATE_NAME='session-state.json'

def _sync(directory):
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def _write(directory,name,value):
    fd,temp=tempfile.mkstemp(prefix='.image-state-',dir=directory)
    try:
        with os.fdopen(fd,'w') as out:
            os.fchmod(out.fileno(),0o600)
            json.dump(value,out,ensure_ascii=False,allow_nan=False)
            out.flush();os.fsync(out.fileno())
        os.replace(temp,Path(directory)/name);_sync(directory)
    finally:Path(temp).unlink(missing_ok=True)


def _read(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as source:return json.load(source)


def write_state(directory,state):_write(directory,STATE_NAME,state)


def read_state(directory):
    try:
        state=_read(Path(directory)/STATE_NAME)
        if not isinstance(state,dict) or state.get('version')!=1:raise ValueError('unknown image state')
        return state
    except (OSError,ValueError) as exc:
        raise ImageUnavailable('Owned image session state is unavailable; retained images were not discarded') from exc


def _marker(directory):return Path(str(directory)+'.owner.json')


def create_marker(directory,generation):
    path=_marker(directory)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as out:
        json.dump({'generation':generation,'closed':None},out);out.flush();os.fsync(out.fileno())
    _sync(path.parent)


def read_marker(directory):
    try:return _read(_marker(directory))
    except FileNotFoundError:return None
    except (OSError,ValueError) as exc:raise ImageUnavailable('Image owner generation seal is unavailable') from exc


def seal_marker(directory,generation,closed):
    previous=read_marker(directory)
    if not previous or previous.get('generation')!=generation or previous.get('closed') not in (None,closed):
        raise ImageUnavailable('Image owner generation changed before cleanup planning')
    path=_marker(directory)
    _write(path.parent,path.name,{'generation':generation,'closed':closed})


def check_marker(directory,generation,closed=None):
    marker=read_marker(directory)
    if (not isinstance(marker,dict) or marker.get('generation')!=generation or
            (closed is not None and marker.get('closed')!=closed)):
        raise ImageUnavailable('Image owner generation/closure seal does not match')
    return marker


def remove_marker(directory,generation,closed):
    if read_marker(directory) is None:
        if Path(directory).exists():raise ImageUnavailable('Image cleanup lost its generation seal')
        return
    check_marker(directory,generation,closed)
    _marker(directory).unlink();_sync(Path(directory).parent)
