"""The code cria asks a harness to run: seven fixed stubs, the only harness-side programs (the standing order in AGENTS.md).

The source below is NORMATIVE and equals the code blocks of docs/harness-primitives.md section 5 byte for byte
(tests/harness_primitives/test_stub_source.py reads that document and compares). Changing a stub, or adding one, is a
change to that document and to the registry in docs/harness-programs.md in the same commit.

A stub makes no decisions: it does one mechanical thing to the path cria names and prints one framed result. cria
composes the call (`compose`), authenticates it (`callauth`) and reads the result (`read_frame`); nothing here parses a
marker out of text for authority.
"""
import base64
import hashlib
import json
import re
import shlex
import zlib
from dataclasses import dataclass

# `env` is called by absolute path: found through the harness `PATH` it could be a workspace entry (an activated `.venv/bin`).
ENV = '/usr/bin/env'
# What `python3` is looked up through: system directories only, never a relative entry. `[harness] safe_path` overrides it.
SAFE_PATH = '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin'
# One frame is read whole before it is decoded; nothing larger is accepted (docs/harness-primitives.md section 4).
FRAME_LIMIT = 1 << 20
# The harness keeps a result whole up to this many bytes and cuts the middle beyond it (multipart.STDOUT_LIMIT).
PAGE_BYTES = 10_000
# Largest raw payload one call carries: 60,000 base64 bytes + a 2.6 KB stub stay under COMMAND_ARG_BUDGET (64 KiB).
CHUNK_BYTES = 45_000

_PRELUDE = r'''import sys,os,json,base64,hashlib,zlib
N=sys.argv[1]
def out(h,b=b""):
    h["n"]=len(b);h["h"]=hashlib.sha256(b).hexdigest()
    z=zlib.compress(b,6)
    if len(z)<len(b):h["z"]=1;b=z
    w=sys.stdout.write
    w("CTX1 "+N+" "+json.dumps(h,separators=(",",":"))+"\n")
    if b:w(base64.b64encode(b).decode()+"\n")
    w("CTX1 "+N+" END\n");sys.stdout.flush();sys.exit(0)
'''

_PATH = r'''def at(r,p,mk=0):
    fd=os.open(r,os.O_RDONLY|os.O_DIRECTORY)
    ps=[x for x in p.split("/") if x]
    if "." in ps or ".." in ps:raise OSError(22,"bad path")
    for x in ps[:-1]:
        if mk:
            try:os.mkdir(x,511,dir_fd=fd)
            except FileExistsError:pass
        d=os.open(x,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=d
    return fd,(ps[-1] if ps else ".")
'''

_READ = r'''import stat
try:
    fd,nm=at(sys.argv[2],sys.argv[3]);o=int(sys.argv[4]);l=int(sys.argv[5])
    f=os.open(nm,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd);s=os.fstat(f)
    if not stat.S_ISREG(s.st_mode):out(dict(ok=0,err="notfile",mode=s.st_mode))
    h=hashlib.sha256();b=b"";p=0
    with os.fdopen(f,"rb") as g:
        for c in iter(lambda:g.read(1<<20),b""):
            h.update(c);lo=max(o,p);hi=min(o+l,p+len(c))
            if hi>lo:b+=c[lo-p:hi-p]
            p+=len(c)
    out(dict(ok=1,size=p,fsize=s.st_size,fsha=h.hexdigest(),mtime=s.st_mtime_ns,ino=s.st_ino,dev=s.st_dev,mode=s.st_mode,off=o),b)
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
'''

_WRITE = r'''import stat,fcntl
rt,rel,ex,sp,nw,st,mk,gr=sys.argv[2:10];pf=".ctx"+gr[:16]+".part";tf=".ctx"+N[:16]+".tmp";fd=t=None
try:
    fd,nm=at(rt,rel,mk=="1");fcntl.flock(fd,fcntl.LOCK_EX)
    if st=="0":b=base64.b64decode(sys.stdin.read())
    else:
        with os.fdopen(os.open(pf,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd),"rb") as g:b=g.read()
    try:
        o=os.open(nm,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd);s=os.fstat(o)
        if not stat.S_ISREG(s.st_mode):out(dict(ok=0,err="notfile"))
        with os.fdopen(o,"rb") as g:old=g.read()
    except FileNotFoundError:s=old=None
    cur=hashlib.sha256(old).hexdigest() if s else None
    if (ex=="-" and s) or (ex not in("-","*") and cur!=ex):out(dict(ok=0,err="stale",sha=cur))
    if sp=="-":new=b
    else:
        new=b"";p=q=0
        for a,e,m in json.loads(sp):new+=old[p:a]+b[q:q+m];p=e;q+=m
        new+=old[p:]
    if hashlib.sha256(new).hexdigest()!=nw:out(dict(ok=0,err="newsha"))
    try:os.unlink(tf,dir_fd=fd)
    except FileNotFoundError:pass
    t=os.open(tf,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,438,dir_fd=fd);os.write(t,new);os.fsync(t)
    if s:
        try:os.fchown(t,s.st_uid,s.st_gid)
        except OSError:pass
        os.fchmod(t,stat.S_IMODE(s.st_mode))
        n=os.stat(nm,dir_fd=fd,follow_symlinks=False)
        if (n.st_ino,n.st_size,n.st_mtime_ns)!=(s.st_ino,s.st_size,s.st_mtime_ns):out(dict(ok=0,err="stale",sha=None))
    if ex=="-":os.link(tf,nm,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False);os.unlink(tf,dir_fd=fd)
    else:os.rename(tf,nm,src_dir_fd=fd,dst_dir_fd=fd)
    t=None;os.fsync(fd)
    if st=="1":os.unlink(pf,dir_fd=fd)
    out(dict(ok=1,landed=1,size=len(new),sha=nw))
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
finally:
    if t is not None:
        try:os.unlink(tf,dir_fd=fd)
        except OSError:pass
'''

_PUT = r'''import stat
try:
    rt,rel,gr,off,mk=sys.argv[2:7];fd,nm=at(rt,rel,mk=="1")
    g=os.open(".ctx"+gr[:16]+".part",os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,384,dir_fd=fd);q=os.fstat(g)
    if not stat.S_ISREG(q.st_mode) or q.st_nlink!=1:raise OSError(22,"bad staging file")
    os.pwrite(g,base64.b64decode(sys.stdin.read()),int(off));out(dict(ok=1,staged=os.fstat(g).st_size))
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
'''

_LS = r'''import stat
try:
    rt,rel,dp,mx,fold,skip,af=sys.argv[2:9];dp=int(dp);mx=int(mx);fold=int(fold);skip=json.loads(skip);af=os.fsdecode(bytes.fromhex(af));R=[];q=[]
    k=lambda m:"l" if stat.S_ISLNK(m) else "d" if stat.S_ISDIR(m) else "f" if stat.S_ISREG(m) else "o"
    fd,nm=at(rt,rel);s=os.stat(nm,dir_fd=fd,follow_symlinks=False)
    if k(s.st_mode)=="d":q=[(rel.strip("/"),1)]
    else:R=[[k(s.st_mode),rel,s.st_size,s.st_mtime_ns,stat.S_IMODE(s.st_mode)]+([os.readlink(nm,dir_fd=fd)] if k(s.st_mode)=="l" else [])]
    while q and len(R)<mx:
        d,n=q.pop(0);fd,_=at(rt,d+"/x");es=sorted((e for e in os.scandir(fd) if e.name>af),key=lambda e:e.name)
        if fold and sum(not e.is_dir(follow_symlinks=False) for e in es)>fold:R.append(["x",d,len(es),0,0]);continue
        for e in es:
            t=e.stat(follow_symlinks=False);c=k(t.st_mode);p=(d+"/" if d else "")+e.name
            R.append([c,p,t.st_size if c=="f" else 0,t.st_mtime_ns,stat.S_IMODE(t.st_mode)]+([os.readlink(e.name,dir_fd=fd)] if c=="l" else [1] if c=="d" and e.name in skip else []))
            if c=="d" and e.name not in skip and (dp<1 or n<dp):q.append((p,n+1))
    out(dict(ok=1,done=int(not q and len(R)<=mx)),"\n".join(json.dumps(r) for r in R[:mx]).encode())
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
'''

_RM = r'''import stat
def rt_(fd,n):
    for e in list(os.scandir(fd)):
        if e.is_dir(follow_symlinks=False):
            c=os.open(e.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);rt_(c,e.name);os.close(c);os.rmdir(e.name,dir_fd=fd)
        else:os.unlink(e.name,dir_fd=fd)
try:
    rt,rel,md,ex=sys.argv[2:6];fd,nm=at(rt,rel);s=os.stat(nm,dir_fd=fd,follow_symlinks=False)
    if md=="f":
        if ex!="*":
            with os.fdopen(os.open(nm,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd),"rb") as g:c=hashlib.sha256(g.read()).hexdigest()
            if c!=ex:out(dict(ok=0,err="stale",sha=c))
        os.unlink(nm,dir_fd=fd)
    elif md=="d":os.rmdir(nm,dir_fd=fd)
    else:
        c=os.open(nm,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);rt_(c,nm);os.close(c);os.rmdir(nm,dir_fd=fd)
    out(dict(ok=1,removed=1))
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
'''

_RUN = r'''import time,subprocess,shutil,stat
md,tmp,tok,tmo,wait,cwd,keep=sys.argv[2:9];tmo=float(tmo);wait=float(wait);d=os.path.join(tmp,".ctx-run-"+tok);W=lambda n:os.path.join(d,n);sh=shutil.which("bash") or shutil.which("sh");E=dict(l.split("=",1) for l in base64.b64decode(os.environ["CTX_ENV"]).decode("utf-8","surrogateescape").split("\0") if "=" in l)
try:
    if md!="start":
        s=os.lstat(d)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&63:raise OSError(13,"not our run directory")
    if md=="start":
        os.mkdir(d,448)
        with open(W("s.sh"),"wb") as f:f.write(sys.stdin.buffer.read())
        if os.fork()==0:
            os.setsid()
            if os.fork()==0:
                z=os.open(os.devnull,os.O_RDWR);[os.dup2(z,i) for i in(0,1,2)]
                with open(W("out"),"wb") as o:
                    p=subprocess.Popen([sh,W("s.sh")],cwd=cwd or None,env=E,stdin=z,stdout=o,stderr=subprocess.STDOUT,start_new_session=True);to=0
                    try:c=p.wait(tmo)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,9);c=p.wait();to=1
                open(W("done.tmp"),"w").write(json.dumps(dict(exit=c,timeout=to,size=os.path.getsize(W("out")))));os.rename(W("done.tmp"),W("done"))
            os._exit(0)
        os.wait()
    e=time.monotonic()+wait
    while not os.path.exists(W("done")) and time.monotonic()<e:time.sleep(.05)
    if not os.path.exists(W("done")):out(dict(ok=1,state="running",dir=d))
    r=json.load(open(W("done")));h=hashlib.sha256();b=b""
    with open(W("out"),"rb") as g:
        for c in iter(lambda:g.read(1<<20),b""):
            h.update(c);b+=c if len(b)<6000 else b""
    r.update(ok=1,state="done",dir=d,osha=h.hexdigest(),head=min(6000,r["size"]))
    if keep!="1" and r["size"]<=6000:
        for n in("s.sh","out","done"):os.unlink(W(n))
        os.rmdir(d);r["removed"]=1
    out(r,b[:6000])
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
'''

_SEARCH = r'''import re,signal
def T(*a):raise TimeoutError("regex")
signal.signal(signal.SIGALRM,T);signal.alarm(10)
try:
    rt,pat,fl,mx,mf=sys.argv[2:7];mx=int(mx);mf=int(mf);rx=re.compile(pat,int(fl));R=[]
    for rel in json.loads(sys.stdin.read()):
        try:
            fd,nm=at(rt,rel);g=os.open(nm,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd);s=os.fstat(g)
            if s.st_size>mf:R.append(["s",rel,s.st_size]);continue
            with os.fdopen(g,"rb") as f:txt=f.read().decode("utf-8","surrogateescape")
        except OSError as e:R.append(["!",rel,e.errno]);continue
        for i,l in enumerate(txt.split("\n"),1):
            if rx.search(l):R.append(["m",rel,i,l])
            if len(R)>=mx:break
        if len(R)>=mx:R.append(["#"]);break
    out(dict(ok=1),"\n".join(json.dumps(r) for r in R).encode())
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
'''

STUBS = {
    'read': _PRELUDE + _PATH + _READ,
    'write': _PRELUDE + _PATH + _WRITE,
    'put': _PRELUDE + _PATH + _PUT,
    'ls': _PRELUDE + _PATH + _LS,
    'rm': _PRELUDE + _PATH + _RM,
    'run': _PRELUDE + _RUN,
    'search': _PRELUDE + _PATH + _SEARCH,
}

_NONCE = re.compile(r'[0-9a-f]{32}\Z')
_COMMENT_MAX = 160


class FrameUnknown(ValueError):
    """The result holds no usable frame for this call: it did not run to completion, was cut, or was altered.
    UNKNOWN is never "did not run" and never "ran": the caller decides what an unknown result means for its operation."""


@dataclass(frozen=True)
class Frame:
    header: dict
    data: bytes


def compose(stub: str, nonce: str, args=(), payload: bytes | None = None, *, comment: str = '',
            safe_path: str = SAFE_PATH, text: str | None = None) -> str:
    """The one harness command for a primitive call (docs/harness-primitives.md section 2): a display comment, a cleared
    environment with a fixed `PATH`, the fixed stub as one quoted `-c` word, then the nonce and quoted arguments. `payload`
    (the `write` and `put` stubs) rides on stdin as one line of base64; `text` (the `run` stub's script, the `search` stub's
    JSON list of paths) rides on stdin as written. Everything
    is a pure function of its inputs, so a retried request composes the identical command."""
    if stub not in STUBS or not _NONCE.match(nonce):
        raise ValueError('unknown primitive or malformed nonce')
    if safe_path != safe_path.strip() or not safe_path or any(not p.startswith('/') for p in safe_path.split(':')):
        raise ValueError('safe_path must be absolute system directories')
    head = shlex.quote(safe_path)
    # `run` hands the user's own environment to the project's commands, but not to the supervisor's interpreter: it starts under `env -i`
    # and receives the environment as one base64 value (NUL-separated entries) that only the command it starts reads.
    prefix = (f'{ENV} -i PATH={head} CTX_ENV="$({ENV} -0 | /usr/bin/base64 | /usr/bin/tr -d \'\\n\')"'
              if stub == 'run' else f'{ENV} -i PATH={head}')
    words = ' '.join(shlex.quote(str(a)) for a in (nonce, *args))
    command = f"{prefix} \\\n  python3 -I -S -c '{STUBS[stub]}' {words}"
    if payload is not None:
        body, terminator = base64.b64encode(payload).decode(), 'CTX_EOF'
    elif text is not None:
        body, terminator = text, 'CTX_EOF'
        while terminator in body.split('\n'):
            terminator = 'CTX_EOF_' + hashlib.sha256((terminator + body).encode()).hexdigest()[:12]
    else:
        body = terminator = None
    if body is not None:
        command += f" <<'{terminator}'\n{body}\n{terminator}"
    shown = ''.join(c for c in comment.splitlines()[0] if c.isprintable())[:_COMMENT_MAX] if comment.strip() else ''
    return (f'# {shown}\n' if shown else '') + command


def read_frame(text: str, nonce: str) -> Frame:
    """The one frame for `nonce` in a harness result (docs/harness-primitives.md section 4), or FrameUnknown.

    Only lines that start with `CTX1 <nonce> ` count; text before or after the frame (a noisy login shell, the harness's own
    envelope) is ignored and never given authority. Exactly one header, optionally one payload line, exactly one END; the
    decoded payload must match the header's length and sha-256. CRs a pty added are removed first."""
    lines = text.replace('\r', '').split('\n')
    tag = 'CTX1 ' + nonce + ' '
    marked = [(i, line) for i, line in enumerate(lines) if line.startswith(tag)]
    ends = [i for i, line in marked if line == tag + 'END']
    heads = [(i, line) for i, line in marked if line != tag + 'END']
    if len(heads) != 1 or len(ends) != 1:
        raise FrameUnknown('no single frame for this call' if not (heads or ends) else 'cut or repeated frame')
    start, headline = heads[0]
    try:
        header = json.loads(headline[len(tag):])
    except ValueError as exc:
        raise FrameUnknown('unreadable frame header') from exc
    n, digest = header.get('n') if isinstance(header, dict) else None, header.get('h') if isinstance(header, dict) else None
    if type(n) is not int or not 0 <= n <= FRAME_LIMIT or not isinstance(digest, str):
        raise FrameUnknown('frame header lacks a length and digest')
    if ends[0] != start + (2 if n else 1):
        raise FrameUnknown('frame is not header, payload, end')
    data = b''
    if n:
        try:
            data = base64.b64decode(lines[start + 1], validate=True)
            if header.get('z') == 1:
                inflater = zlib.decompressobj()
                data = inflater.decompress(data, n + 1)
                if inflater.unconsumed_tail or not inflater.eof:
                    raise FrameUnknown('payload larger than its header says')
        except (ValueError, zlib.error) as exc:
            raise FrameUnknown('payload does not decode') from exc
    if len(data) != n or hashlib.sha256(data).hexdigest() != digest:
        raise FrameUnknown('payload does not match its length and digest')
    return Frame(header, data)
