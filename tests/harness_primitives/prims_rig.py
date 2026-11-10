"""Drive the real stubs exactly as a harness does: `bash -lc` of the command `harnessprims.compose` builds, read back through
`harnessprims.read_frame`. No stub is imitated anywhere in these tests."""
import base64
import hashlib
import json
import os
import resource
import secrets
import subprocess
from dataclasses import dataclass

from cria import harnessprims

sha = lambda b: hashlib.sha256(b).hexdigest()
GROUP = 'g' * 32


@dataclass
class Ran:
    frame: harnessprims.Frame | None
    process: subprocess.CompletedProcess
    command: str

    @property
    def header(self):
        return self.frame.header

    @property
    def data(self):
        return self.frame.data

    @property
    def records(self):
        return [json.loads(line) for line in self.data.decode('utf-8', 'surrogateescape').split('\n') if line]


BASH = __import__('shutil').which('bash')       # the harness starts its shell by absolute path; a workspace `bash` on the PATH is not it


def run(stub, args, payload=None, *, cwd, env=None, text=None, safe_path=harnessprims.SAFE_PATH, login=True, nonce=None, fsize=None):
    nonce = nonce or secrets.token_hex(16)
    command = harnessprims.compose(stub, nonce, args, payload, text=text, safe_path=safe_path)
    # `fsize` stands in for a full disk or a quota: no file the command writes may grow past that many bytes (a write returns short, then fails)
    limit = (lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))) if fsize else None
    done = subprocess.run([BASH, '-lc' if login else '-c', command], cwd=str(cwd), env=env, capture_output=True, timeout=60, preexec_fn=limit)
    try:
        frame = harnessprims.read_frame(done.stdout.decode('utf-8', 'surrogateescape'), nonce)
    except harnessprims.FrameUnknown:
        frame = None
    return Ran(frame, done, command)


def write(root, rel, new, ex, *, sp='-', payload=None, staged=False, mk=1, cwd=None, env=None, group=GROUP, fsize=None, ws=None):
    """``ws``: the workspace whose ./tmp/reference holds the staged payload (default: ``root``)."""
    args = [root, rel, ex, sp, sha(new), 1 if staged else 0, mk, group, ws or root]
    return run('write', args, None if staged else (new if payload is None else payload), cwd=cwd or root, env=env, fsize=fsize)


def ls(root, rel='', depth=0, mx=1000, fold=0, skip=(), after='', *, cwd=None, env=None, **more):
    return run('ls', [root, rel, depth, mx, fold, json.dumps(list(skip)), os.fsencode(after).hex()], cwd=cwd or root, env=env, **more)
