# Harness primitives — the only code cria asks a harness to run

**Status: design of record (phase 1 of the standing order in [`AGENTS.md`](../AGENTS.md)). Written 2026-11-10 against HEAD `89be90d8`.** **Phase 3 implemented it (2026-11-10): `cria/harnessprims.py`, `cria/callauth.py`, `cria/ledger.py`, `cria/ops.py`; `list_dir` is the first route; §10 ends with what phase 3 ran. Phase 4 added the reads (§8.7) and Phase 5 the writes and edits (§8.1-8.5; `cria/writeops.py`; §8.2's checker mechanism differs from the text below, see the note there); Phase 6 added the workspace survey and the initial inventory (§8.9; `cria/surveyops.py`, `cria/inventoryops.py`; the text of §8.9 is corrected where the build differed); Phase 6b added grep/glob (`cria/searchops.py`), the answers that save a file (`cria/answerops.py`: oversize output, the fetch spill, the search results) and the unread-write probe (`cria/probeops.py`; §8.8-§8.10 describe what was built).** The seven stubs in §5 were prototyped in a scratch directory and exercised against a real filesystem; §10 lists what was run. The stub source in §5 is **normative**: the shipped bytes equal it (`tests/harness_primitives/test_stub_source.py` reads this file and compares), and any change to a stub, or any new stub, is a change to this file in the same commit ([`harness-programs.md`](harness-programs.md) holds the registry and the size budget).

Companion: [`harness-programs.md`](harness-programs.md) — what ships today, what each piece becomes, round-trip costs, threat-model check, migration phases, decisions for the operator.

## 1. The rules this contract enforces

These restate the standing order ("cria's logic stays in cria") as checkable constraints.

| # | Constraint | How the design meets it |
|---|---|---|
| C1 | **Fixed text.** A harness program is one of the stubs in §5, sent unchanged. Data rides as arguments or stdin, never as generated code. | Seven stubs, 1.1–2.6 KB each, 12.8 KB in total (today: about 104 KB of distinct program text, shipped in 15–57 KB combinations per call). |
| C2 | **No decisions in the harness.** No syntax tables, no exact-match logic, no queues, no marker or receipt authentication. | Every stub takes everything it needs from its arguments. The only comparisons are mechanical (hash equals the hash cria sent; path component is a symlink). |
| C3 | **Isolated.** Nothing is imported from, or resolved through, the workspace or ambient interpreter configuration. | `env -i PATH=<system dirs> python3 -I -S -c '<stub>'` (§2). Prototype-verified against a workspace that shadows `hashlib`, `os`, `json`, … and plants a `python3` first on `PATH`. |
| C4 | **Contained.** No symlink is followed below the root cria names; no `..`. | Directory-descriptor-relative opens with `O_NOFOLLOW` on every component (§3). The harness sandbox stays the primary boundary. |
| C5 | **Authenticated by cria, not by text.** | Call ids are keyed MACs over the exact command; every frame is anchored by a keyed nonce; results are consumed only for ids cria verifies (§6). No marker, receipt or first-line comment carries authority. |
| C6 | **Small and not growing.** | Per-stub and total budgets in `harness-programs.md` §4; growth needs a registry decision. |
| C7 | **Visible.** A human reading the harness transcript sees an ordinary command whose program text is short, constant and readable. | Same bytes every call, so one review covers all calls; a one-line display comment names the operation. |
| C8 | **No hidden state in the harness.** | The only harness-side state is the target file itself and, for long-running commands, one private directory per run (§5.6). cria keeps all bookkeeping (§6, §8). |

## 2. How a primitive call is composed

```
# edit_file src/a.py                                  <- display comment (for the human; never parsed for authority)
/usr/bin/env -i PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin \
  python3 -I -S -c '<STUB SOURCE, §5>' <nonce> <arg>... [<<'CTX_EOF'
<payload>
CTX_EOF]
```

`run` is the one exception to `env -i` (it must hand the user's own environment to the project's commands):

```
/usr/bin/env CTX_PATH="$PATH" PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin python3 -I -S -c '<run stub>' <nonce> start "${TMPDIR:-/tmp}" ...
```

* **`/usr/bin/env`, by absolute path.** `env` found through the harness `PATH` could be a workspace entry (an activated `.venv/bin`, `node_modules/.bin`) that receives the nonce in its arguments: the review of phase 3 (B1) showed a planted `bin/env` printing a frame cria accepted. Every composed command, and the candidate-safety check, starts with `/usr/bin/env` (`harnessprims.ENV`); a harness without it answers 127 with no frame and the call is UNKNOWN.
* **`env -i PATH=<safe>`** clears the environment (`PYTHON*`, `LD_*`, `BASH_ENV`, …) and fixes where `python3` is looked up. The safe path is a config value (`[harness] safe_path`, default as shown); it contains system directories only, never a relative entry. `-I` alone is not enough: with a workspace `bin` first on `PATH`, `python3 -I` still ran the planted interpreter in the prototype control (§10).
* **`python3 -I -S -c`**: `-I` (isolated) keeps the current directory and script directory out of `sys.path` and ignores `PYTHON*` variables and the user site; `-S` skips `site`, so no `.pth` file or `sitecustomize` runs. The program arrives as an argument, so there is no file in the workspace to plant, replace or hash-pin.
* **Quoting.** No stub contains a single quote, so each is one `'...'` word. Arguments are quoted with `shlex.quote`. The display comment is written with control characters removed and is cut at the first line break; it is never read back for any purpose.
* **Payload.** Bytes for `write` and `put` go on stdin through a quoted heredoc as **one line of base64**: no argument-size limit applies to stdin itself, the payload exists once in the command, and base64 can never contain the terminator (it has no `_`). `run`'s script and `search`'s JSON list of paths are plain text on stdin (those stubs read it as text, not base64); cria checks no line equals the terminator and derives `CTX_EOF_<12 hex of the text's sha-256>` otherwise (deterministic: a retried request composes the identical command). `harnessprims.compose(stub, nonce, args, payload=bytes | text=str, comment=, safe_path=)` builds all of it.
* **`${TMPDIR:-/tmp}`** is expanded by the harness shell and passed as an argument (cria never assumes the harness's temp directory; principle 23c).
* **No interpreter, no primitive.** If `python3` is missing the call exits 127 with no frame. cria reports file tools as unavailable. There is no shell fallback and no inline fallback (a fallback would be a second, unreviewed implementation).
* **Interpreter floor:** Python 3.7+ (`os.scandir(fd)`, `os.pwrite`, dir-fd opens).
* **Command size.** The whole command is one `bash -lc` argument, capped at 128 KiB by the kernel (`MAX_ARG_STRLEN`). cria's budget stays at the existing `COMMAND_ARG_BUDGET` = 64 KiB. §7 covers payloads that do not fit.

## 3. Paths: what cria decides, what the stub enforces

Every filesystem primitive takes `ROOT` and `REL`.

* `ROOT` is an absolute directory **cria** chose from facts it holds: the workspace root the harness announced, or `/` for any other absolute path (a declared root, a dependency cache, or at external-permission levels `read`/`write` a path the model named *after* `dirguard` has approved it). It is never the directory part of such a path: the stub follows a symlink in `ROOT` itself, so a link anywhere in an outside path must sit *below* ROOT, where every component is opened without following (phase 3 review M2: `ext/z -> ~/.cria` listed cria's home when ROOT was `ext/z`). The model never supplies `ROOT` directly; it supplies text that cria turns into a `ROOT` and a `REL`.
* `REL` is the remainder, `/`-separated, with no empty, `.` or `..` component (the stub rejects them with EINVAL).
* The stub opens `ROOT` as given (a symlink in the `ROOT` string itself is followed; cria chose it), then opens each component of `REL` with `O_DIRECTORY|O_NOFOLLOW` relative to the previous descriptor, and the final name with `O_NOFOLLOW`. A symlink anywhere below `ROOT` therefore fails (`ELOOP` or `ENOTDIR`), and a link swapped in after cria looked cannot redirect the operation, because every step is relative to a descriptor already held.

| Question | Decided by | When |
|---|---|---|
| Is the path inside the workspace or a declared root? Is it `~/.cria`, a spill directory, a reference file? Is the external-directory level satisfied? | cria (`dirguard`, `outboundpolicies`, lexical, no filesystem access) | Before any call is issued |
| Is any component below `ROOT` a symlink? Is the target a regular file? | The stub (kernel refuses; no policy) | At the moment of the operation |
| What does a refused symlink mean for the coder (link to where? inside the workspace?) | cria: on `ELOOP`/`ENOTDIR` it issues one `ls` (stat) call for the real cause, never a guess, then resolves the link **itself** (lexically, relative to the link's directory), re-runs its own containment checks on the resolved path, and either re-issues against the resolved path or refuses with the true reason | Rare error path (+1 round trip) |
| Is the file the one cria expects? | The stub compares hashes cria sent; cria decides what a mismatch means | Every write and delete |

Today's behaviour (write and edit programs `realpath` the target and write *through* a symlink to wherever it points; reads follow links) is replaced by "refuse, then cria resolves and re-checks". Hard links are not symlinks and are not detected here; the sandbox is the boundary for them.

## 4. Output framing

Every stub prints exactly one frame to stdout and exits 0 (a failing operation is a frame with `ok:0`; a missing frame means the program did not run to completion):

```
CTX1 <nonce> <header JSON, ASCII, one line>
<payload: base64 of the bytes (zlib-compressed first when that is smaller), one line>     <- absent when there is no payload
CTX1 <nonce> END
```

Header fields common to all stubs: `ok` (0/1), `n` (payload length in bytes **after** decompression), `h` (sha-256 of those bytes), `z:1` when the payload was compressed. Failures: `err` (the Python exception class name, or a stub-specific word such as `stale`) and `errno`.

How cria reads it (`cria/harnessprims.py`, phase 3):

1. It accepts a result only for a call id it verifies (§6). The result text is searched for lines that start with `CTX1 <that call's nonce> ` (and nothing else). Exactly one header line followed by exactly one END line must exist; otherwise the result is **UNKNOWN** (never "did not run", never "ran").
2. Text before or after the frame (a noisy login shell, the harness's own envelope) is ignored; it is never parsed and never given authority.
3. CR is stripped (a pty may expand LF). The payload line is decoded, decompressed with a hard output bound of `n`, and must match `n` and `h`. A cut result fails this check and is re-requested at a smaller size (the existing refetch ladder in `probegate` moves into cria's frame reader unchanged: 1,500 / 750 / 375 bytes).
4. cria bounds what it will accept before it decodes: `n` ≤ its frame limit (1 MiB), decompression uses `zlib.decompressobj().decompress(data, n + 1)`. (Implemented in `harnessprims.read_frame`; a result that fails any rule is recorded as an unknown frame and the step is asked again smaller: `ops.LS_MAX` = 1000 / 400 / 150 / 50 / 20 records for `ls`.)
5. Page size: the harness cut limit is the existing `STDOUT_LIMIT` = 10,000 bytes per result. A frame carries at most about 7 KB of compressed bytes. At the measured median compression of 2.7x on source text (439 files of this repository, p10 2.2x, p90 3.3x) one page holds 16–20 KB of source. For `ls` (phase 3, measured through the shipped stub): 15–29 bytes of frame per record on real directories (this repository's `cria/`, `/usr/lib`), about 3.5 on regular names, so one frame holds roughly 350–650 real entries and `MAX` is the only knob: a directory beyond one frame is returned as its first entries with `done:0` ("unknown beyond this point", never "absent"), and cria asks again with `AFTER` = the last name it received until the listing is complete (one call per frame; operator-approved in phase 4, step 0).

## 5. The stubs

The program sent is the **prelude** `A`, then (for every stub except `run`) the path helper `B`, then the stub body, concatenated in that order, one `-c` argument. Sizes are the bytes sent.

| Stub | Verb | Sent size | Arguments after the nonce |
|---|---|---|---|
| `read` | return a byte range of a file and its identity | 1,803 B | `ROOT REL OFF LEN SK` |
| `write` | replace or create a file atomically, compare-and-swap | 3,112 B | `ROOT REL EX SP NEW ST MK G WS` + stdin |
| `put` | stage one chunk of a payload too big for one command | 1,370 B | `WS G OFF` + stdin |
| `ls` | stat a path, or list a tree, without following links | 2,122 B | `ROOT REL DEPTH MAX FOLD SKIP AFTER` |
| `rm` | delete a file, an empty directory or an owned tree | 1,709 B | `ROOT REL MODE EX` |
| `run` | run a command with a timeout, detached, output to a file | 2,371 B | `MODE TMP TOK TIMEOUT WAIT CWD KEEP` + stdin |
| `search` | regex search over a file list cria chose | 1,752 B | `ROOT PATTERN FLAGS MAX MAXFILE SKIP` + stdin |

Total 14,239 B. `search` is conditional on decision D3 in `harness-programs.md`.

### 5.0 Prelude `A` (all stubs) and path helper `B` (all but `run`)

```python
import sys,os,json,base64,hashlib,zlib
N=sys.argv[1]
def out(h,b=b""):
    h["n"]=len(b);h["h"]=hashlib.sha256(b).hexdigest()
    z=zlib.compress(b,6)
    if len(z)<len(b):h["z"]=1;b=z
    w=sys.stdout.write
    w("CTX1 "+N+" "+json.dumps(h,separators=(",",":"))+"\n")
    if b:w(base64.b64encode(b).decode()+"\n")
    w("CTX1 "+N+" END\n");sys.stdout.flush();sys.exit(0)
```

```python
def at(r,p,mk=0):
    fd=os.open(r,os.O_RDONLY|os.O_DIRECTORY)
    ps=[x for x in p.split("/") if x]
    if "." in ps or ".." in ps:raise OSError(22,"bad path")
    for x in ps[:-1]:
        if mk:
            try:os.mkdir(x,511,dir_fd=fd)
            except FileExistsError:pass
        d=os.open(x,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=d
    return fd,(ps[-1] if ps else ".")
```

### 5.1 `read`

`read N ROOT REL OFF LEN SK` returns bytes `[A, A+LEN)` where `A = OFF` when `SK` is 0, and otherwise `A = OFF` plus the byte just after the `SK`-th newline of the file (so `SK = S-1` and `OFF = 0` start at line `S`; `OFF` then pages within that window). The header says where it started (`off` = `A`, null when the file has fewer than `SK` newlines) and how many lines the file has (`ln`: newline count, plus one when the file does not end in a newline), counted in the same pass that streams the file for its hash. It also returns, always, the identity of the file as read: `size` (bytes actually streamed), `fsize` (size at open; a difference means the file changed while it was read, and cria re-reads), `fsha` (sha-256 of the **whole** file, streamed), `mtime` (ns), `ino`, `dev`, `mode`. `LEN=0` returns the identity only (a stat plus hash). Refuses non-regular files (`err:notfile`, with `mode`) without blocking on them (`O_NONBLOCK`; a FIFO answers instantly).

```python
import stat
try:
    fd,nm=at(sys.argv[2],sys.argv[3]);o=int(sys.argv[4]);l=int(sys.argv[5]);k=int(sys.argv[6])
    f=os.open(nm,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd);s=os.fstat(f)
    if not stat.S_ISREG(s.st_mode):out(dict(ok=0,err="notfile",mode=s.st_mode))
    h=hashlib.sha256();b=b"";p=t=0;e=b"";a=None if k>0 else o
    with os.fdopen(f,"rb") as g:
        for c in iter(lambda:g.read(1<<20),b""):
            h.update(c);q=0
            while a is None:
                i=c.find(b"\n",q)
                if i<0:break
                q=i+1;k-=1
                if not k:a=p+q+o
            t+=c.count(b"\n");e=c[-1:]
            if a is not None:
                lo=max(a,p);hi=min(a+l,p+len(c))
                if hi>lo:b+=c[lo-p:hi-p]
            p+=len(c)
    out(dict(ok=1,size=p,fsize=s.st_size,fsha=h.hexdigest(),mtime=s.st_mtime_ns,ino=s.st_ino,dev=s.st_dev,mode=s.st_mode,off=a,ln=t+(p>0 and e!=b"\n")),b)
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
```

### 5.2 `write`

`write N ROOT REL EX SP NEW ST MK G`, payload on stdin as base64 when `ST=0`.

* `EX` is what must be true of the target when the swap happens: `-` it does not exist; `*` no condition; 64 hex digits, the whole file's current sha-256.
* `SP` is `-` (the payload is the whole new file) or a JSON list `[[a,b,m],...]` meaning: replace `old[a:b]` with the next `m` payload bytes, ranges ascending and disjoint, applied to the file cria read (so `EX` must be a hash). This is how an edit sends only the changed bytes instead of re-sending the file.
* `NEW` is the sha-256 of the **result**. The stub builds the result, refuses (`err:newsha`) if it does not hash to `NEW`, and only then writes. A truncated, corrupted or mis-assembled payload can therefore never land.
* `ST=1` takes the payload from the staging file written by `put` calls with the same `G` (a 32-hex per-operation token) instead of stdin. The staging file is `WS/tmp/reference/.ctx<G16>.part`: the guarded folder cria already owns, never the destination's directory. `WS` is the workspace root.
* `MK=1` creates missing parent directories.

Steps: walk to the parent with no-follow opens → `flock` the parent directory (serialises cooperating cria writers) → read the target through its descriptor → check `EX` (else `err:stale` with the current `sha`, nothing written) → build and verify the result → **a whole staged payload (`ST=1`, `SP=-`) is the file that lands: it must be a regular file with one link, its mode and owner are set, it is `fsync`ed and `rename`d (or `link`ed) from `WS/tmp/reference` onto the target. A target on another filesystem than that folder fails with `EXDEV` and nothing is written, and there is no copy fallback (operator, 2026-11-10). A staged splice (`ST=1`, `SP` a list) and any payload sent on stdin are written** to a sibling temp file `.ctx<nonce16>.tmp` (`O_EXCL`; a stale file of the same name from a killed run is unlinked first) **in a loop until every byte is written** (one `write(2)` may take fewer bytes than asked: a full disk, a quota, a file-size limit; a call that takes none, or fails, fails the whole call with the temp file removed and the target untouched, so a truncated file is never renamed into place), `fsync` → copy mode and owner of the old file → re-`stat` the target and refuse (`stale`) if its inode, size or mtime moved since it was read → `rename` over the target, or `link`+`unlink` for `EX=-` (an atomic no-replace create) → `fsync` the directory → remove the staging file. Any error removes the temp file. A filesystem without hard links answers the `link` with an error (`EPERM`/`ENOTSUP`) and nothing is written; cria reports it, and may retry with `EX=*` only after a fresh stat showed the path absent (a decision made in cria, not a fallback in the stub).

Properties cria relies on: a write is **idempotent** (re-issuing the same call after it landed answers `stale` with `sha == NEW`, which cria reads as "landed"); a payload cannot land unless it hashes to `NEW`; replacing a file keeps its mode and owner (a change from today's whole-file write, which reset mode to `0666 & ~umask`).

```python
import stat,fcntl
rt,rel,ex,sp,nw,st,mk,gr,ws=sys.argv[2:11];pn=".ctx"+gr[:16]+".part";tf=".ctx"+N[:16]+".tmp";fd=t=u=sd=None;c=0
try:
    fd,nm=at(rt,rel,mk=="1");fcntl.flock(fd,fcntl.LOCK_EX)
    if st=="0":b=base64.b64decode(sys.stdin.read())
    else:
        sd,_=at(ws,"tmp/reference/"+pn);u=os.open(pn,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=sd);q=os.fstat(u)
        if not stat.S_ISREG(q.st_mode) or q.st_nlink!=1:raise OSError(22,"bad staging file")
        with os.fdopen(os.dup(u),"rb") as g:b=g.read()
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
    if u is not None and sp=="-":t,sf,sn=u,sd,pn
    else:
        try:os.unlink(tf,dir_fd=fd)
        except FileNotFoundError:pass
        t=os.open(tf,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,438,dir_fd=fd);c=1;v=memoryview(new);sf,sn=fd,tf
        while v:
            w=os.write(t,v)
            if w<1:raise OSError(5,"short write")
            v=v[w:]
    os.fsync(t)
    if s:
        try:os.fchown(t,s.st_uid,s.st_gid)
        except OSError:pass
        os.fchmod(t,stat.S_IMODE(s.st_mode))
        n=os.stat(nm,dir_fd=fd,follow_symlinks=False)
        if (n.st_ino,n.st_size,n.st_mtime_ns)!=(s.st_ino,s.st_size,s.st_mtime_ns):out(dict(ok=0,err="stale",sha=None))
    else:m=os.umask(0);os.umask(m);os.fchmod(t,438&~m)
    if ex=="-":os.link(sn,nm,src_dir_fd=sf,dst_dir_fd=fd,follow_symlinks=False);os.unlink(sn,dir_fd=sf)
    else:os.rename(sn,nm,src_dir_fd=sf,dst_dir_fd=fd)
    c=0;os.fsync(fd)
    if u is not None and sp!="-":os.unlink(pn,dir_fd=sd)
    out(dict(ok=1,landed=1,size=len(new),sha=nw))
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
finally:
    if c:
        try:os.unlink(tf,dir_fd=fd)
        except OSError:pass
```

### 5.3 `put`

`put N WS G OFF` writes one chunk at byte offset `OFF` of the staging file `.ctx<G16>.part` (mode 0600, no-follow, one link) in `WS/tmp/reference` (created if missing, no link followed) and answers its current size. It does not know the destination: the target is the `write`'s business. Chunks may arrive in any order and in parallel (disjoint ranges); re-sending a chunk is harmless. A chunk is written in a loop until every byte is down (`pwrite` loop, as in `write`); a short write fails the call (`ok:0`), it never answers a size that is not the chunk's end. The final `write ... ST=1` verifies the assembled bytes against `NEW` before anything lands.

```python
import stat
try:
    ws,gr,off=sys.argv[2:5];fd,nm=at(ws,"tmp/reference/.ctx"+gr[:16]+".part",1)
    g=os.open(nm,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,384,dir_fd=fd);q=os.fstat(g)
    if not stat.S_ISREG(q.st_mode) or q.st_nlink!=1:raise OSError(22,"bad staging file")
    v=memoryview(base64.b64decode(sys.stdin.read()));o=int(off)
    while v:
        w=os.pwrite(g,v,o)
        if w<1:raise OSError(5,"short write")
        v=v[w:];o+=w
    out(dict(ok=1,staged=os.fstat(g).st_size))
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
```

### 5.4 `ls`

`ls N ROOT REL DEPTH MAX FOLD SKIP AFTER`. `REL` empty means `ROOT` itself. A non-directory yields one record (so this is also `stat`). A directory is listed breadth-first, sorted by name, never following links. `DEPTH` 1 lists one level, 0 is unlimited. `MAX` caps records; `done:1` in the header says the listing is complete, `done:0` means "unknown beyond this point", never "absent". `FOLD` N>0: a directory with more than N non-directory entries is not listed, one `x` record gives its entry count instead. `SKIP` is a JSON list of directory names that are reported but not entered (their record carries a trailing `1`). `AFTER` is a name given as the lowercase hex of its bytes (empty: no filter): only entries whose name sorts after it are listed. Hex, because a name need not be UTF-8 and a command must be: a name with an undecodable byte (a lone surrogate once cria has it as text) is a cursor the harness can carry. It is the resume cursor of `DEPTH 1` listings (cria asks for the next page with `AFTER` = the last name it received, `FOLD` 0); with `FOLD` set it would count only the entries after the name, so the two are not combined.

Payload: one JSON array per line, `[type, path, size, mtime_ns, mode, extra?]`, `type` ∈ `f d l o x`, `path` relative to `ROOT`, `extra` = link text for `l`, `1` for a skipped directory. JSON escapes make every file name (newlines, invalid UTF-8 as lone surrogates) round-trip.

```python
import stat
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
```

### 5.5 `rm`

`rm N ROOT REL MODE EX`: `MODE f` unlinks a file (and, if `EX` is a hash, only when the content still hashes to it), `d` removes an empty directory, `t` removes a tree without following any link below it (a symlink as `REL` fails). cria uses `t` only for run directories it created (§5.6) and `f` for files it wrote (staging leftovers, spill files). It never deletes a path it has not itself issued: ownership is the call ledger (§6), not a name scan.

```python
import stat
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
```

### 5.6 `run`

`run N MODE TMP TOK TIMEOUT WAIT CWD KEEP`, script text on stdin for `MODE=start`.

* `start` allocates `TMP/.ctx-run-<TOK>` with `mkdir` (mode 0700; `EEXIST` refuses, so a retried start never adopts someone else's directory; cria answers a lost start with `wait` instead), writes the script to `s.sh`, forks twice with `setsid` so the harness reaping its process group cannot cut the run, and the grandchild runs `bash s.sh` in `CWD` with stdin from `/dev/null` and stdout+stderr into `out`, killing the whole process group at `TIMEOUT` seconds. It writes `done` (`{exit, timeout, size}`) atomically when the run ends. The child gets the user's own environment (`PATH` is restored from `CTX_PATH`); only the supervisor's interpreter is isolated.
* Both modes then wait up to `WAIT` seconds for `done` and answer `state:"running"` (with `dir`) or `state:"done"` with `exit`, `timeout`, `size`, `osha` (sha-256 of the whole output), `head` and a payload of the first ≤ 6,000 output bytes. With `KEEP=0` and a fully inline result the stub deletes the directory it created. Otherwise cria pages the rest with `read` (`ROOT=dir`, `REL=out`) and removes the directory with `rm t` (on every path: a verdict, a deadline, an unreadable page, a cut or lost reply; the directory's name is derived from the token cria chose, so a lost reply needs no `dir` to be removed).

Why this cannot live in cria: the command has to run where the files are, outlive a harness exec that returns after ~10 s, and be bounded by a timeout that does not depend on any connection to cria. Authority: exactly the harness's, including whatever the project's own checks do (running the project's tests *is* running project code; the supervisor's isolation protects the supervisor, not the child).

```python
import time,subprocess,shutil,stat
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
```

### 5.7 `search`

`search N ROOT PATTERN FLAGS MAX MAXFILE SKIP`, stdin is a JSON list of relative paths **chosen by cria** (from a listing, after its own generated-directory and ignore logic). Each file is opened with the same no-follow walk and matched line by line with Python `re` (the regex dialect `grep` already offers the model today). Records: `["m", path, lineno, line]`, `["s", path, size]` (over `MAXFILE`, not read), `["!", path, errno]`, and a final `["#"]` when the page is full. `SKIP` (phase 6b, operator-approved after the heavy-file measurement: harness-programs.md §7, "Phase 6b result") skips the first `SKIP` matching lines (counted over the whole list, in file order) and `MAX` counts the matches returned after them, so a file with any number of matches is read as consecutive pages `[SKIP, SKIP+MAX)`: a page with `["#"]` is full, the first page without it is the last. Errors and over-size notes are not counted and repeat on every page. The harness never decides which files to search and never filters output.

```python
import re,signal
def T(*a):raise TimeoutError("regex")
signal.signal(signal.SIGALRM,T);signal.alarm(10)
try:
    rt,pat,fl,mx,mf,sk=sys.argv[2:8];mx=int(mx);mf=int(mf);sk=int(sk);rx=re.compile(pat,int(fl));R=[];n=0
    for rel in json.loads(sys.stdin.read()):
        try:
            fd,nm=at(rt,rel);g=os.open(nm,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd);s=os.fstat(g)
            if s.st_size>mf:R.append(["s",rel,s.st_size]);continue
            with os.fdopen(g,"rb") as f:txt=f.read().decode("utf-8","surrogateescape")
        except OSError as e:R.append(["!",rel,e.errno]);continue
        for i,l in enumerate(txt.split("\n"),1):
            if rx.search(l):
                n+=1
                if n>sk:R.append(["m",rel,i,l])
            if n>=sk+mx:break
        if n>=sk+mx:R.append(["#"]);break
    out(dict(ok=1),"\n".join(json.dumps(r) for r in R).encode())
except Exception as e:out(dict(ok=0,err=type(e).__name__,errno=getattr(e,"errno",None)))
```

## 6. Authentication without text markers

**What is authenticated.** (a) that a command in the harness's history was issued by cria, byte for byte; (b) that a result belongs to that call; (c) that the result text inside it came from the stub's own frame.

**Secret and derivations** (`cria/callauth.py`, phase 3). One 32-byte key `K`, created on first use at `~/.cria/harness-call.key` (mode 0600, `O_EXCL`), never placed in a command, log, capture or body; capture redaction treats it as a known secret. For an operation `op` (12 random hex digits chosen by cria) and step number `s`:

```
nonce(op, s)   = HMAC-SHA256(K, "nonce" | op | s)[:16].hex()              # appears in the command; deterministic, unguessable
group(op)      = HMAC-SHA256(K, "group" | op)[:16].hex()                   # names staging files; deterministic across restarts
call_id(op, s) = "ctx_" + op + "_" + s + "_" + HMAC-SHA256(K, "call" | op | s | sha256(command_bytes))[:8].hex()   # ≤ 38 chars; Chat tool_call_id limit is 40
```

The nonce and the command are pure functions of `(op, s, arguments)`, so a retried HTTP request, or a request replayed after a restart, produces the identical command and id.

**Verification** (`callauth.verify(call)`): the id must match `^ctx_[0-9a-f]{12}_[0-9]{1,4}_[0-9a-f]{16}$`; the command string is recovered from the assistant tool call in the harness's history (the existing `shell_args` inverse); the MAC is recomputed over exactly those bytes and compared with `hmac.compare_digest`. A command that differs by one byte (a harness that rewrites commands, a hand-edited transcript) fails. A call whose id fails is an ordinary model-or-harness call: never re-presented as anything else, never given a typed outcome.

**Pairing.** The result belongs to the call only if the harness's own pairing (`tool_call_id` / `call_id`) names a verified id, exactly one result carries that id, and that result holds exactly one frame for that call's nonce with matching `n`/`h`/END (§4). Several results for one id, or none, or a cut frame mean UNKNOWN and the operation proceeds on that basis (§8.5).

**Outbound renaming.** Any model-authored tool call whose id begins `ctx_` is given a neutral new id before it leaves cria, so the verified namespace is only ever cria's.

**What each party can and cannot do**

| Party | Can | Cannot, and why |
|---|---|---|
| The model | Author commands, including ones that print `CTX1 <anything>`. | Create a verified id (no `K`). Make cria read its output as a primitive result: results are parsed only for verified ids and only for that call's nonce. See the nonce: it never enters the model's context (private calls are projected out); if it did, it would sit in a command with an unverifiable id. |
| A repository file, dependency or fetched page | Contribute bytes. Those bytes sit **inside** the base64 payload of a frame (or `run`'s `out` file, paged through `read`), so they cannot form a header or END line, and they are never searched for markers. | Run before the stub: the interpreter is `python3 -I -S` found through a fixed `PATH` with an empty environment, and the stub is not a file. A file named `hashlib.py`, a planted `python3`, `PYTHONPATH`, `sitecustomize` all failed to execute in the prototype (§10). |
| Output of a command the model ran | Print frame-shaped text. | It belongs to a call with a different id and nonce, so it is plain output. |
| A running project process (a test the gate launched), or any code running as the same user in the same process namespace as a call | Read another process's command line (`/proc/<pid>/cmdline`: the nonce is in argv) and write to that process's stdout (`/proc/<pid>/fd/1`). **Reproduced** (phase 3 review): a process stopped the stub with SIGSTOP, wrote a frame to its `fd/1` and killed it, and `read_frame` accepted the forged listing. **Measured inside the pinned Codex 0.159.3 in this repository's sandbox policy** (`test_codex_primitives.py::test_sandbox_trust_boundary`): each exec runs in its own PID namespace (5 processes visible: the sandbox launcher, the shell and the command), so a process of *another* call is not visible, but a process of the *same* call is, and `echo x >> /proc/<child>/fd/1` worked on it. | Forge a result for a call it is not part of, **under that sandbox**: the other calls' processes are not visible to it. It can forge the result of the call it runs inside, which is the gate's `run` (project code by design, whose output cria treats as the project's, never as the state of cria's own files). **cria does not protect against concurrent same-user code that shares a process namespace with a primitive call**; a harness without a PID namespace per call gives a project process the nonce of any concurrent call. The compare-and-swap (§8.4) still detects file tampering between cria's read and its write. |
| **Any harness command, and so the model** | Read `~/.cria/harness-call.key` **when the sandbox lets the harness read `$HOME`**. Measured in the same sandbox policy: `$HOME` and `~/.cria` are readable (a 0600 file of the same user is readable) and **not writable** (`touch` answers "Read-only file system"). Capture redaction only matches the key as one contiguous hex string, so `xxd -p`, `base64` or `od` of the file gets past it. | With the key alone: forge a result that verifies. A verified id is also a ledger entry (`~/.cria/ops`, written only by cria), and `neutralize` renames any `ctx_` id the model authors, so a command the model writes is never a verified call. **With write access to `~/.cria`** (a workspace at or above `$HOME`, a sandbox that allows it, or full-access mode) **everything is forgeable**: the key, the ledger and the files cria trusts. |
| A hostile **harness**, user shell profile, or the `env`/`python3` binaries | Anything, with the harness's own authority. | Out of scope; nothing cria can do inside the harness defends against the harness. The guarantee is: results reflect the stub's execution unless the harness's own execution environment is compromised. |

**What cria protects against, and what it does not.** cria protects against *text*: what the model writes, what a repository file, a fetched page or a command's output contains. None of it is authority: a result is accepted only for an id cria derived from a key the model's text cannot contain, as the one frame carrying that call's nonce, and recorded in a ledger only cria writes. cria does **not** protect against code running as the same user that shares a process namespace with a call, nor against a harness that lets its commands read the key *and* write `~/.cria`. **The sandbox must deny the harness access to `~/.cria`** (at least write access, preferably read): the repository's pinned-Codex policy denies the write, not the read, which leaves the key readable and unforgeable-with. Hardening the read side (a policy that hides `~/.cria`, or a key held outside `$HOME`) is the operator's decision; cria cannot make it from inside the harness.

**What closes the old forgeries.** The old receipt was `sha256(call_id, name, arguments)[:16]`, all of it visible to the model and a repo file could print it; the old markers (`# ⟦ctx:tool⟧…`, `# ⟦ctx:gate⟧…`) were authority by text at the first line. In this design a typed outcome is a field of cria's own ledger entry, set only after steps (a)-(c) above; text in a file, a command, a fetched page or the model's output is data everywhere.

**The ledger** (`cria/ledger.py`, implemented in phase 3; phase 4 added the records `blob`, `settle` and `withhold`). Bookkeeping lives in cria: for every operation, its model call (id, name, arguments), the steps issued (id, command hash), the frames received, the outcome (`landed`, `refused`, `unapplied`, `uncertain`, `read`, …) and the **final text the model was told**. It is an append-only JSON-lines file per session, `~/.cria/ops/<sha256(session key)>.jsonl` (private directory opened without following links, mode 0700, file 0600, `flock` and `fsync` per append; the home's own path may run through a symlink, the ledger directory may not). Seven record types, folded in order and incrementally on every request: `op` (the model's call, the operation kind and the guard facts it was issued under), `step` (number, tool-call id, sha-256 of the command, what it is and the arguments that re-derive it), `frame` (header and decoded payload of the verified result; the first one wins), `final` (typed outcome and the exact text the model was told; for a read also the verified source identity, what the text is, the prose before it, a note after it), `blob` (a text steps refer to by hash), `settle` (the model's wire accepted a verified read) and `withhold` (the wire measured a verified read and refused it). **Restart:** nothing else holds operation state. A request that dies between two appends is asked again; every record is a pure function of the key and what came before, so the retry appends what is missing and re-emits the identical calls (ids and commands included). A step whose result arrives after a restart is verified against the key (MAC over the command in the history) and the ledger (same id, same command hash) like any other. A torn last line is skipped and the next append starts a fresh line. A ledger that cannot be opened privately, or a key that is not a private 32-byte file, issues nothing (the model is told the listing is unavailable) and verifies nothing. The history shown to the model is rebuilt from the harness's history plus the ledger (§8.12): the model sees its own call and cria's final text, never the primitive calls. If the ledger entry for a verified call is missing (state removed, store unreadable) the history shows the honest primitive calls, labelled, and no outcome is claimed.

## 7. Large payloads and size limits

Measured at HEAD, not assumed: a lowered command over the kernel limit fails before it runs ("Argument list too long", `E2BIG`). The prototype reproduced it with `bash -lc` and a 147 KB command (§10). The harness's own wrapper makes the usable limit lower; the smallest refused spill at HEAD was 123,848 bytes. cria's existing `COMMAND_ARG_BUDGET` of 64 KiB is kept.

* **One call** carries up to **45,000 raw payload bytes** (60,000 base64 bytes + a 2.6 KB stub + ~0.4 KB arguments ≈ 63 KB). The prototype landed exactly 45,000 random bytes in one 62,905-byte command.
* **Larger payload** (whole-file writes, fetched documents, spill files): cria cuts the payload into 45,000-byte chunks and issues, in one reply, up to 16 `put` calls (disjoint offsets, any order); when their frames are back it issues the one `write ... ST=1`, which verifies the assembled bytes against `NEW` before it renames. ⌈chunks ÷ 16⌉ + 1 round trips: two for any payload up to 720,000 bytes. A 300,000-byte file was staged out of order and landed with its hash intact in the prototype. This removes today's disclosed cut of fetched documents at 46,080 bytes (`SPILL_CONTENT_MAX`): nothing is truncated.
* **Retry safety.** `put` is idempotent; the final `write` is idempotent (a reply lost after it landed answers `stale` with `sha == NEW`, a staging file consumed by a landed write answers `FileNotFoundError`, and cria then reads the target's hash). A killed run can leave `WS/tmp/reference/.ctx<hex>.part` (and `.ctx<hex>.tmp` beside the target): cria removes exactly the names it derives from its own ledger (`group(op)`, `nonce(op, s)`) with `rm f`, and it **sweeps the staging folder** (`cria/stagesweep.py`): with the first chunks of a staged payload it lists `WS/tmp/reference` (`ls`, in the same wave) and, with the next wave, removes with `rm f` each name of exactly the staging shape `.ctx<16 hex>.part` that is not its own and is stale: the staging name of an operation of this session's ledger that has ended, or a name older than 24 hours (another session's, or one whose ledger is gone). It touches nothing else. Nothing about the staging files is hidden or specially named: they are ordinary files in the folder cria owns.
* **Edits** send only the changed bytes (`SP`), so an edit of one line is ≈ 3 KB whatever the file size. Whole-file `write_file` sends the model's own content once.
* **Results** are bounded the other way: a frame is ≤ 10,000 bytes, so reads page (§8.7).

## 8. How each current feature is preserved in cria

Everything below runs in the cria process (new modules named in `harness-programs.md` §7).

### 8.1 Exact-match edit (and byte fidelity)

1. cria needs the file's bytes: from its **session byte cache** (`path → bytes, sha-256, size, mtime_ns, ino`, filled by any `read` result and any landed write, bounded LRU, 16 MiB) or by `read` (§8.7).
2. `cria/editapply.py` is the port of today's `_EDIT_PY`, as a pure function on bytes: `apply_edit(content: bytes, old: str, new: str) -> Applied | Failure`. It keeps, unchanged: decoding as UTF-8 with `surrogateescape` and re-encoding the same way (an undecodable byte survives as itself); the "CRLF throughout and no `\r` in old/new" rule that maps LF to CRLF; the exact single match; the whitespace-flexible token match with its indentation rule; the failure facts (`identical`, `multi`, `multi_flex`, `anchor` with line, `phantom`, `close`, `no_anchor`, `would_break`) that `editrecovery` already turns into the monotonic directive; the echo window (`first`, `last`, `total`, `flex`, `empty`, `segs`, `dup`). The facts become Python values instead of base64 JSON; the `editrecovery` renderers consume them as they do today.
3. The result is a byte splice list. cria issues `write` with `EX = sha-256 of the bytes it applied the edit to`, `SP = splice list`, `NEW = sha-256 of the result` (computed in cria, so the stub's check is end to end).
4. `Failure` outcomes never touch the harness. A landed write updates the cache with the new bytes.

Fixtures: the existing cases in `tests/write_edit/` (CRLF file, lone `\r`, non-UTF-8 byte, flexible match, indentation, multi-match, near-miss, phantom) move to unit tests of `apply_edit` with identical expected results.

### 8.2 Syntax validation ("refuse to replace a file that parses with content that does not")

The table moves to `cria/syntaxcheck.py`, and its tool rows are **the table `probediscovery` already owns** (`syntax_floor_candidates`: `node --check`, `php -l`, `ruby -c`): the validator's own comment says it duplicated that knowledge only because the harness program could not import it; one table now serves both. Where each check runs:

| Extension | Where | How |
|---|---|---|
| `.py` `.pyi` | in cria | `compile(text, path, "exec")` |
| `.json` | in cria | `json.loads` |
| `.xml` | in cria | `xml.etree.ElementTree.fromstring` (cria's expat; documents over 1 MiB are not checked: UNKNOWN) |
| `.toml` | in cria | `tomllib.loads` |
| `.rb` | harness, `run` | `ruby -c` fed on stdin |
| `.js` `.mjs` `.cjs` | harness, `run` | `node --check` on stdin |
| `.php` | harness, `run` | `php -l` on stdin |
| `.go` | harness, `run` | `gofmt -e` on stdin |

For the four harness-side languages cria composes a short `run` script whose only content is the checker invocation with the candidate on its standard input, for example for Ruby:

```
env -u NODE_OPTIONS -u NODE_PATH -u RUBYOPT -u RUBYLIB -u RUBYGEMS_GEMDEPS -u PHPRC -u PHP_INI_SCAN_DIR ruby -c <<'CTX_IN_<random hex>'
<candidate file text>
CTX_IN_<random hex>
```

(`node --check`, `php -l` and `gofmt -e` replace `ruby -c`; cria picks heredoc terminators that occur in neither the file nor the outer payload.) The candidate bytes are fed on the tool's standard input (verified: `ruby -c`, `node --check`, `php -l` and `gofmt -e` all read a script from stdin and report syntax errors), so **no temp file is created anywhere**, unlike today's `_VALIDATE_FN`.

> **As shipped (Phase 5) this is one mechanism different, on evidence.** Standard input changes what is parsed and what is said: `node --check` on stdin is always CommonJS (a valid `.mjs` with `import` fails with `Cannot use import statement outside a module`; run on a file named `.mjs` it passes), and the tools name stdin differently (`-`, `[stdin]`, `Standard input code`, `<standard input>`) so neither the file-name replacement nor the line coordinate (`_at`) works. `cria/syntaxcheck.py` therefore sends one fixed shell script per candidate: `cd` to the run's own private directory (the script's directory, created by `run` with mode 0700 and removed with it), write the candidate there as `cand<ext>` (`base64 -d`, exact bytes), run the checker's command line on that copy with `NODE_OPTIONS NODE_PATH RUBYOPT RUBYLIB RUBYGEMS_GEMDEPS PHPRC PHP_INI_SCAN_DIR` unset (`gofmt`'s formatted output to `/dev/null`), and remove the copy in a `trap`. The copy's name is replaced by the file's by cria. Candidates are checked first and the file's current bytes only when the candidate fails (one check per landing, not two). The extra costs and limits are in `harness-programs.md` §7, Phase 5 result. The two checks (old bytes, new bytes) go out in parallel in one reply; the old bytes' verdict is cached by `(sha, extension)`. A tool that is missing (exit 127) or times out (20 s) is UNKNOWN and never refuses. Error text keeps today's treatment (the checker's real lines, `-`/`[stdin]` replaced by the file's base name, `Line N of the content you sent is: …` from `_at`, which moves into `syntaxcheck.py` as a pure function).

What is lost: (1) for `.py`, the check runs under **cria's** Python (3.11+), not the project's interpreter; the project-interpreter compile still happens in the completion gate (`python3 -m compileall`). A file that parses only under another interpreter version is UNKNOWN (no refusal), never wrongly refused. (2) For `.rb/.js/.php/.go` the candidate text rides in the check command, so those writes cost one extra round trip and about the file's size again in the harness transcript (decision D4 in `harness-programs.md` offers skipping the pre-write check for them, leaving the gate's parse check). Nothing else is lost.

### 8.3 Concurrency: the per-directory lock, the ordering queue, batches

Today a batch of edits runs concurrently in the harness, so a lock plus a done-mark queue per file orders them (`editsequence`, `completionmarks`, `ownedfiles`: about 27 KB of distinct program text, shipped inside every write and edit). The new rule is structural:

* **cria never has two writes to one path in flight.** cria groups every file mutation of a model turn by `(ROOT, path)` into one `FileGroup`, in the order the model sent them. It issues **one read (or none, when the cache is warm) and one write** for the group: the edits and whole-file writes are applied in order to a working copy in cria; each model call gets its own outcome (applied, or its failure facts); the single `write` carries the combined splice. A `write f; edit f` batch is `apply(write) then apply(edit)` on the working copy. The phi4 / Java A11 case (thirty edits in one turn) becomes one read and one write.
* Different files are independent and are issued in parallel in the same reply; the harness may run them in any order or at once.
* An earlier turn's write whose reply never arrived is **not** invisible to the next turn: the next turn's read-modify-write is guarded by the compare-and-swap below, and the lost write is resolved by re-reading the file (§8.5).
* The `flock` on the directory in `write`/`put` serialises cooperating cria writers that were issued from different sessions at the same moment; it is not what the design depends on (CAS is).

### 8.4 The read-modify-write race and compare-and-swap

`EX` is the sha-256 of the bytes cria applied the edit to. If anything changed the file since (a model shell command, an editor, a test run, another cria session), `write` answers `stale` with the file's current hash and writes nothing: cria re-reads and re-applies the edit to the current content (one extra round trip), or, when the edit no longer applies, reports the failure facts for the current content. Two properties: no update is lost, and a stale cache is harmless (the optimistic path costs one round trip when the cache is right, two when it is wrong). The remaining window is between the stub's last stat and its `rename`, microseconds: a non-cooperating writer that renames over the file inside it is overwritten. This narrows the race to that window; it cannot be closed from the harness side without taking the writer's lock. Prototype: 16 concurrent writers each tried to apply a different edit to the same base; exactly one landed, 15 got `stale`, and the file held exactly that one edit (§10).

### 8.5 Completion marks and lost-reply detection

Replaced by the ledger plus idempotence. A step whose id is in the history with no result, a cut or malformed frame, or a `running` envelope is UNKNOWN. For a write step cria re-issues **the identical call**: if it had landed, the answer is `stale` with `sha == NEW`, which cria records as `landed`; if it had not, it lands now; if the file has any other hash the file changed under the writer and the operation is re-planned from a fresh read. For read, `ls`, `search`, `put` the same re-issue is harmless. For a `run` the retried `start` fails with `EEXIST` and cria sends `wait` for the same token. There is no per-write program, no private marks directory and no `/proc` liveness probe. The completion gate (cria-side) asks the ledger for operations with unresolved write steps before it launches and resolves them first; the "unsettled writes" notice keeps its wording and is computed from the ledger.

### 8.6 Interplay with the harness's own output cap and compaction

A frame is ≤ 10,000 bytes, as today's pages. The harness keeps every frame in its transcript, so these bytes count toward the harness's compaction trigger exactly as today's page records do; what changes is that the commands (the 90% of one measured request that cria's programs used to be, `harness-programs.md` §1 and §5.1) shrink to 1.5–3 KB. If the harness compacts the history and drops a call, its ledger entry is simply not referenced by the history, as today: an operation whose calls are not in the current history is abandoned (the model asks again).

### 8.7 Reads, pages and snapshots (implemented in phase 4: `cria/readops.py`, `cria/filecache.py`; behaviour in [`reads-and-retention.md`](reads-and-retention.md))

`read_file` is `read(OFF=0, LEN=L0)` where `L0` is the first page (16,000 raw bytes, sized afterwards from the compression the last sizable frame showed; a warm cache sends `LEN=0`, identity only). The first frame reports `size` and `fsha` for the whole file, so cria knows the file's size before it fetches the rest:

* **Fits in one page:** done. cria hashes the bytes itself and compares with `fsha`.
* **Needs more pages:** the remaining ranges go out in one reply, at most 8 per reply (a window deep in a file doubles its reach each reply). Every frame carries `fsha` and `fsize`; the assembly is accepted only if all `fsha` agree, `size == fsize` in every frame and the assembled bytes hash to `fsha`. A change between pages is detected; the read starts again once, and a second change is reported to the model (`⟦ctx:read-source-changed⟧`, no read credit). **There is no snapshot**: equal hashes are one file state. A frame the harness cut is asked again at half the size.
* **Too big for the model's window:** a whole read whose chars/4 estimate exceeds the measured window (no frame, no safety factor: a strict lower bound) is answered from the first frame without transporting the file, unless that first page holds no newline (it may be one enormous line, whose measured shape the note needs from the whole file). Borderline files are fetched and decided at the wire as before: `ReadFitOverflow` withholds the verified read in the ledger (`withhold`) and the model is told. No new threshold, except that cria never transports a file larger than it will hold (16 MiB, `filecache.CAP_BYTES`), which is answered the same way.
* **Range reads** (`start_line`/`end_line`): cria asks for the window with `SK`, numbers the lines `N: text` itself and applies the "past end of file" and inverted-range answers. A warm cache sends one `LEN=0` call and serves the bytes only when `fsha` and `size` equal the cached ones. With `SK` (operator-approved after the phase 4 measurement) a window is asked with `SK = start - 1` and is one or two frames wherever it sits; the prefix is never transported for a window.
* The model-visible text of every read result is produced by cria and is the same text the model got before, except the wording changes listed in harness-programs.md §7 (nothing private is in its context, so the sentences about omitted transport pages are gone).

### 8.8 Oversize output and saved files (built in phase 6b: `cria/answerops.py`, `cria/searchops.py`)

`_bounded_tool_stdout` wrapped cria's own commands in a Python program that measured stdout and saved over-limit output to `./tmp/reference/stdout-<sha>.txt` (the directory is `webfetch.SPILL_DIR`), and `_spill_command` saved a fetched document through a shell heredoc of base64 (cut at 46,080 bytes). Both are deleted. cria holds the complete answer in-process (a listing, search matches, a fetched page, Brave's results), measures it with `externalization.stdout_size` (bytes plus one per line feed: the way a pty returns them), and when it is over `STDOUT_MAX_BYTES` (10,000; 9,000 for a listing) saves the complete text with `write` (`put` waves of at most 16 chunks of 45,000 bytes, then one committing `write`, as §7) at `./tmp/reference/stdout-<sha-256 of the text>.txt` and answers with the existing pointer. A fetched document too large to inline and a search's full results are saved the same way under the names `webfetch` gives them (`_spill_name`, `search_spill_name`), **whole**: nothing is cut. An answer that stands on its own is one `say` call. This remains the one deliberate cria artifact in the user's tree (the model must be able to grep it) and keeps its guards (`spill_edit_refusal`). The write goes through the no-follow walk, so a `tmp` or `tmp/reference` symlink in the workspace cannot redirect it (the old search spill used `os.makedirs` + `open(T, "w")` and followed links). The save is true only when the harness confirmed it (the frame's hash equals the one cria sent); the stored fact is a field of the ledger's final record and the externalization offers settle from it.

### 8.9 Survey, initial inventory, ctags, search

* **Workspace survey** (`wsview`, **built in phase 6**: `cria/surveyops.py`): the view is built from a typed `wsview.Survey` that cria computes from the frames of `ls`, `read` and `run` calls. `ls` walks the tree: one `DEPTH 0` call when it fits one frame, else directory by directory (up to 16 calls a reply, `FOLD` = `FOLD_AT`, `SKIP` = `.git` and every name a build-output rule could fold); cria applies the rules that lived in the old program: a skipped directory beside its ecosystem manifest is named as an output, otherwise walked with a call of its own; a folded directory is UNKNOWN inside, never absent; a name that is not one line of UTF-8 is left out and its directory is not whole; the walk stops after `TREE_MAX_ENTRIES` entries and says so. Requested bodies are `read` pages (`BLOB_FILES_MAX`, `BLOB_BYTES_MAX`, `BLOB_FILE_MAX`; what could not be handed back is `refused`: a size, absent, unreadable). "Which program does the coder's shell resolve" and "does this path outside the workspace exist" are one `run` of shell text (`probe_script`: no decision in it; the versioned-name fallback is the glob `name+([0-9])*([0-9.])` over `$PATH`). **It does not ride on another call** (the design said it would ride as extra calls in the reply of the write step): a survey is an operation of its own, asked on cria's cadence at the start of a request and issued instead of calling the model, after the landed write it follows (§ the phase 6 result in `harness-programs.md`), and applied to the view where it sat in the history.
* **Initial inventory** (`initial_inventory`, **built in phase 6**: `cria/inventoryops.py`): `ls` (`DEPTH 0` or by directory with the `AFTER` cursor, `FOLD` 0, `SKIP` = `groundtruth._INVENTORY_EXCLUDE`) replaces the walker. **The design's claim that per-file `blank`/`digest` are not collected was wrong**: the unread-write rule decides before any read and treats an unknown blank state as "admit" (`Loop.unread_target_check`; commit `5a7ea116`, the `ruby-verify3-0012` capture), so the facts were gathered at Phase 6 (a `read` per file, bounded to 100). **Phase 6b made them lazy (§8.10):** the inventory is names, sizes and symbols and reads no file; every item carries `blank: None`.
* **ctags**: kept, **as the real `ctags` binary run through `run`, not as a cria program**, as shell text (`inventoryops.ctags_script`, 507 B plus one line per file name; it excludes the ten libxml2 parsers and gives ctags its run directory as `TMPDIR`: docs/harness-programs.md, "ctags and `--_interactive=sandbox`"): the absolute paths `/usr/bin/ctags`, `/bin/ctags`, `/usr/local/bin/ctags` only, a `--version` that says "Universal Ctags", then `env -i … --options=NONE --output-format=json --pattern-length-limit=1 --sort=no -f - -L -` in the workspace with the file names on stdin (at most 20,000 bytes of names per run, runs in parallel). The 5.5 KB Python indexer driver (interactive JSON protocol, per-file change detection, timeouts) is deleted. What is lost: the `--_interactive=sandbox` mode's restriction of ctags to protocol-supplied files, and a file whose name holds a line break (no symbols, still listed). Output is read in cria (JSON lines; names, kinds and scopes only); a missing or non-Universal ctags is `symbol_indexer_error` `"indexer not found"`, a failing or timed-out one `"indexer failed: …"`, exactly as now (symbols unavailable, never invented).
* **grep / glob** (**built in phase 6b**: `cria/searchops.py`): cria lists with `ls` (the whole path in one `DEPTH 0` call when it fits one frame, else directory by directory), applies `ignore.generated` to each directory's own listing and the glob rules in-process, and for `grep` sends the chosen files to `search` in batches (the pattern validated in cria with `re.compile`, run by the harness's `re`). `glob` needs no second call. The 5.3 KB walker and the shipped `inspect.getsource(ignore.generated)` are deleted. What the stub's shape forces, found by building it: (a) a reply is one frame (about 10,000 bytes), so a file with more matches than one frame holds is read as consecutive pages with `SKIP` (a page is full when it says `["#"]`; a batch of several pages is read again where it began and where it ended, and must answer the same); (b) a line that is not UTF-8 is an error only if it matches; (c) the stub splits a file's text on line feeds, so a file that ends with one has an empty last "line" a pattern like `^$` matches: cria asks that file's line count (`read`) and drops the match past it.

### 8.10 The unread-write hold and read-instead

The hold decision (existing non-blank file, never read or changed since read, L5) is cria's today and stays so. What changes is only the answer: instead of lowering the write to a read program, cria issues the ordinary `read` for the path, and the model's `write_file` call is answered with the read-instead text plus the file bytes (`⟦ctx:read-instead⟧` prose is unchanged, but it is cria's text in the ledger, not a record parsed out of stdout). A single-target `apply_patch` held the same way is answered with the same read. When the model retries the write, cria already has the bytes (cache) and the write is one round trip with `EX` = the hash it read.

**The lazy question (built in phase 6b: `cria/probeops.py`, `cria/readfacts.py`).** What an existing file *is* (empty or whitespace-only text, text with something in it, not text) and its hash are not gathered by the inventory. When a write or edit names an existing file and nothing known settles it (credit first; then the view and the inventory: missing, blank), the rule answers `UnreadProbe` and cria asks the file: the model's call and the ones after it in the reply are taken out of the reply, held in a ledger operation of kind `probe`, and one `read` of the first 512 bytes goes to the harness instead (a second, of the whole file, only when those are whitespace). The model never sees the probe. When the answer is back the held calls are handed to the loop once (`Ops.release`), the loop notes the facts and lowers them again with no model call: a non-blank unread file is answered with the file, a blank or missing one is written, a file that is not text or could not be read is admitted with `state_unknown` naming the fact. A file is asked at most once. Cost: +1 harness call and +1 round trip per guarded write whose state is unknown (+2/+2 when the first bytes are whitespace); a file the coder has been shown, or the inventory does not list, is not asked.

### 8.11 The completion gate and probes

| Piece | Where it lives |
|---|---|
| Choosing probes (`probediscovery`, `proberun.select_completion_probes`), composing each probe's command line (`compose_probe_command`: `cd`, `timeout -k`, `</dev/null`, exit sentinel), the offline re-run text (`unshare -rnm`, read-only bind), parse floor one-liners (`_TOML_CHECK` 349 B, `_JSON_CHECK` 201 B, `_XML_CHECK` 201 B) | cria composes **shell text**; it is data to `run`, readable in the transcript, and is project code by design. Unchanged. |
| Running it detached with a timeout and an output file | `run` (§5.6), the only harness-side program the gate needs |
| Paging the spool back, size/hash verification, retries, the `running`/deadline logic, section splitting, parsing, cleanup report | cria: pages are `read` calls on `ROOT=<run dir> REL=out` (up to 8 per reply, hash from `osha`), the deadline is cria's clock |
| Aux scratch for probes (`CTX_PROBE_AUX`, pycache redirect) | The script creates `$dir/aux` itself (`mkdir`) and cria removes the run directory with `rm t` after the last page; a random 128-bit run token replaces the `ownedfiles` certificate/identity machinery (a directory created by our own `mkdir` under an unguessable name is ours) |
| Survey after the checks, completion marks | extra calls (`ls`, `read`) issued after `done`; the ledger resolves writes (§8.5) |
| `helper` install leg, content-hash loader, 57.5 KB helper | deleted |

What cannot move and stays harness-side: starting the command in `CWD` with `stdin=/dev/null`, merging stdout and stderr into a file, killing its process group at the deadline, and writing the completion fact. That is `run`.

### 8.12 What the model sees (replacing `represent_inbound`, `privatenames`, `modelview`'s private-name pass)

`ops.project(messages)` is one function, called at the one place the old re-presentation passes are called today (`server.py` `_setup_translation`, `Upstream._prep` through `modelview.wire_messages`):

1. Find every assistant tool call whose id verifies (§6). Group them by operation using the ledger.
2. Remove the private step calls and their results from the model's view.
3. Present the model's **original** call (its own id, name and arguments, from the ledger) followed by one result whose text is the ledger's final text for it, in the model's original order.
4. Calls with an unverifiable `ctx_` id, or verified calls whose ledger entry is missing, are shown as the honest primitive commands, with no outcome claimed. Nothing is reconstructed from a first line, a comment, or a declaration in the command text, so the "forged declaration rewrites the history" path (security finding 4) does not exist, and `privatenames.restore_wire`'s legacy-declaration reconstruction is deleted.
5. The typed outcome facts every reader asks for (`denial.landed`, `refused`, `unlanded_call_ids`, `read_payload`, the read-observation hint) keep their API; their source changes from "parse a record out of stdout" to the ledger entry. No reader's contract changes, which is what keeps phases 4-7 small.

## 9. Behaviour changes this design makes on purpose

1. Whole-file `write_file` over an existing file **keeps its mode and owner** (today it resets to `0666 & ~umask`; only edits preserved it).
2. A symlink in a write/edit/read path is **refused and re-resolved by cria** instead of being followed (writes went *through* links, reads followed them).
3. Fetched documents are no longer cut at 46,080 bytes (chunked `put`/`write`; **done in phase 6b**: the pointer says IN FULL and `spill_extent_cut` is gone).
4. Over-window reads are answered from the first frame, without transporting the file.
5. `list_dir` is rendered by cria from `ls` records instead of the raw `ls -la` text; it keeps one line per entry and the same refusal/overflow behaviour. **The line is** `<type><rwxrwxrwx> <size right-aligned to 10> <UTC YYYY-MM-DD HH:MM> <name>[ -> <link text>]` (type `-` file, `d`, `l`, `?` other; a directory's size is `0`; a control character in a name is its escape, an undecodable byte `\xNN`, so one line is one entry), sorted by name, with no `.`/`..` and no `total` line; an empty directory is `<path>: empty directory`; a non-directory path is one line named as the model named it; a failure is `ls: cannot access '<path>': <the kernel's message for the errno the stub reported>`. Owner/group names and link counts are not shown. Over 9,000 bytes (`externalization.stdout_size`, bytes plus newlines) the whole listing is saved to `./tmp/reference/stdout-<sha256>.txt` through `write` (`put` waves past 45,000 bytes) and the model gets the existing pointer.
6. `.rb/.js/.php/.go` syntax checks cost one extra round trip; `.py` checks use cria's interpreter (§8.2).
7. `ctags` symbols come from the plain CLI (§8.9).
7a. (phase 6) A large inventory no longer ends with a `python3` pager the model is told to run; the sentence points at its own listing and search tools. A symlinked workspace root is followed (the root is the one cria chose). An unreadable directory is `not whole` in the survey as well.
7b. (phase 6b) A line that is not UTF-8 is an error only if it matches (it made its whole file unreadable); a saved oversize result no longer begins with a typed record and is named by the hash of its text; a file with more matches than one frame holds is read as pages (`SKIP`, operator-approved), complete; the inventory carries no per-file facts (they are asked at write time).
8. Sessions that began before the cut-over are not re-presented (decision D2).

## 10. What was run to write this (scratch prototype, not in the repo)

All against the real stub text in §5, invoked exactly as in §2 through `bash -lc`, on Linux with Python 3.14.7, in a scratch tree outside any workspace:

* **Isolation.** Workspaces that shadow standard-library modules, each shadow writing a marker file outside the tree, with a `bin/python3` that writes a marker, `PATH` with that `bin` first and `PYTHONPATH` (and `PYTHONSTARTUP`) pointing at the workspace. First tree: `hashlib base64 json zlib os sys subprocess fcntl stat time` plus `sitecustomize`; second tree: those without `sitecustomize` plus `encodings re io codecs`. `read` (first tree) and `write`, `ls`, `run` (second tree) all returned correct frames and **no marker file was created**. Controls in the same tree: plain `python3 -c` ran the planted `python3`; `python3 -I -c` with a clean `PATH` was safe; `python3 -I -c` with the workspace `bin` first on `PATH` ran the planted `python3` (so `-I` alone is insufficient and `env -i PATH=` is required).
* **Containment.** Reading or writing through a final-component symlink → `errno 40`; through a symlinked directory component → `errno 20`; `..` → `errno 22`; a FIFO → `notfile` without blocking; a symlink to a directory as `rm t` target → refused. Outside files unchanged in every case.
* **Write semantics.** New file; `EX=-` over an existing file → `stale`; correct CAS; stale CAS; splice edit; wrong `NEW` → `newsha`, file untouched; mode `0750` kept; `mk` creates parents / absent `mk` fails with `errno 2`; CRLF and `\xff\xfe` bytes written exactly; a staged 300,000-byte file written as 7 chunks out of order and landed with matching hash and no leftover files; commit replay after landing → `FileNotFoundError` on the staging file (cria then reads the hash).
* **Concurrency.** 16 processes editing the same base through `write` at once: 1 landed, 15 `stale`, no other error, file equals the one landed edit.
* **Limits.** A 110,000-byte payload (147 KB command) failed in `bash -lc` with `Argument list too long`; a 45,000-byte payload (62,905-byte command) landed.
* **`ls`/`rm`/`run`/`search`.** Sorted BFS walk with names containing newlines; `SKIP`, `FOLD`, `MAX` (`done:0`); symlink records with link text; `rm t` of a tree containing a symlink to an outside directory removed the link only; `run` with exit code, detached long run (`wait 1` returned `running` after 1.0 s, `wait` later returned `done`), timeout kill, 20,000-byte output (head 6,000, whole-output hash), the child saw the user's `PATH` and variables while the supervisor ran from the safe path; `search` with `\d`, symlink refused, missing file reported.
* **Not run in phase 1:** a real sandboxed Codex (phase 3 acceptance, below), macOS or Windows, a harness that rewrites commands, Python older than 3.14, a non-ASCII or non-UTF-8 locale beyond the C-locale default that `env -i` produces. The prototype's byte counts are the ones in §5.

Syntax-on-stdin facts (§8.2) were checked directly: `ruby -c`, `node --check`, `php -l`, `gofmt -e` each reported a syntax error for a script given on standard input.

### What phase 3 ran (2026-11-10, `tests/harness_primitives/`)

Against the shipped constants, not scratch copies:

* **Source:** the stubs equal §5's code blocks byte for byte (12,761 B at phase 3, 13,311 B after the review fixes; per-stub registry budgets hold; no stub holds a single quote).
* **Isolation and containment:** the prototype's tests, lifted: a workspace shadowing 16 stdlib modules plus `sitecustomize`, a planted `python3` first on `PATH` and `PYTHONPATH`/`PYTHONSTARTUP` at the workspace ran against all seven stubs and through a real `list_dir`: no marker was created. The controls hold (plain `python3 -c` and `python3 -I -c` under a planted `PATH` do run the planted interpreter). Containment: `..`, a final-component link (`ELOOP`), a link in the directory path (`ENOTDIR`), a FIFO and a directory, for `read`, `write`, `ls`, `rm`, `search`; outside files unchanged.
* **Write semantics:** CAS, splice, wrong `NEW`, mode kept, byte-exact CRLF and `\xff`, `mk`, a 300,000-byte payload staged out of order and replayed (the consumed staging file answers `FileNotFoundError`, then `read`'s `fsha` shows it landed), 16 concurrent writers (one lands, 15 `stale`), 45,000 raw bytes in one command; `run`: exit, detached, timeout kill, 20,000-byte output, token reuse refused, the child's own environment.
* **Frames and authentication:** nine alterations of a real frame (cut, duplicated, flipped, wrong nonce, ...) are all UNKNOWN; a frame for another nonce is plain output; a payload that inflates past its declared length is refused before it is inflated; a file *named* like a complete frame with the right nonce is data inside the payload; a result for an id cria never issued, for a command changed by one byte, delivered twice, or carrying another call's nonce is not taken; a model-authored `ctx_` id is renamed before the harness sees it; a key that is not private verifies nothing.
* **Restart:** cria killed between issue and result, between the listing and its save, and a request asked again after its answer was lost (the identical continuation, recorded once); a deleted ledger leaves the labelled honest command.
* **Real pinned Codex 0.159.3 in the repo's sandbox policy:** every stub ran; the commands came back byte for byte (the MACs depend on it); a 45,000-byte payload (62,905-byte command) landed and a 110,080-byte payload (147 KB command) failed with `Argument list too long` before running, so the 64 KiB budget is the right side of the line; scripted model -> real `CriaServer` -> real Codex -> real stubs delivered a `list_dir` result and a spilled listing with no private text in any model-bound body. Round-trip latency: `docs/harness-programs.md` §5.2.

### What phase 5 ran (2026-11-11, `tests/harness_primitives/`, `tests/write_edit/`)

Against the shipped constants and real directories, through the real engine, a real `CriaServer` and the pinned Codex:

* **Characterisation** (`test_write_characterization.py`): 131 cases of `write_file` / `edit_file` against the capture of the route that preceded this one; 123 are byte for byte the same model-visible text, 8 are intended differences with the reason recorded beside each.
* **Engine scenarios** (`test_write_edit_primitives.py`, `test_write_edit_lost_replies.py`, `test_write_edit_sequencing.py`): payload size classes 44,999 / 45,000 / 45,001 / 300,000 / 719,999 / 720,001 bytes (one command, then `put` waves of at most 16 chunks and one hash-checked `write`; no command over the 64 KiB budget; the staging file gone), a path that cannot be carried, a restart between the read and the write, two writers of one file (no update lost), a link in a directory component (inside followed by cria, outside refused, nothing created outside), a staged write through a link (resolved by cria and landed at the link's target, or refused in the words for a link that leaves the workspace; no staging file left in either directory), the four lost-reply shapes of a landed write (judged by the file, no second write sent), a write that never ran (sent again, the same write but for its nonce), a write the file never confirms (`uncertain`), compare-and-swap on a file changed between the read and the write, a plan from memory that would call an edit a miss (decided on the file instead), thirty edits of one file in one turn (one read, one write, thirty answers), Ruby's checker through the `run` stub (`cand.rb` and the run directory never visible, nothing left in the harness temp directory), the survey riding the landing write into the view.
* **Isolation** (`tests/shell_safety/test_shell_safety_harness_python_isolation.py`): a whole write, an edit and a refused candidate in a workspace that shadows eight stdlib modules (including `sitecustomize`), with `PYTHONPATH` and the user base at the workspace and a planted `python3` and `env` first on `PATH`: they land and answer as anywhere and nothing planted runs.
* **Pinned Codex 0.159.3, sandbox policy, scripted model → real `CriaServer` → real stubs** (`test_codex_write_edit.py`): a new file, an overwrite, a cold edit, a would-break edit and a miss, thirty edits to one file in one turn, 45,000-byte, 150 KB and 300 KB writes (staged by `put`, committed by one `write`), a write through a link inside the workspace and one through a link out of it (the file outside untouched), no `.ctx*` litter, no private text (`CTX1`, `ctx_`, `python3`, `-I -S`, `harness-call`, `CTX_EOF`, `env -i`) in any body the model received. Latency per round trip: `write` 1.4 KB median 74 ms, 45,000 bytes 82 ms, splice edit 80 ms.

### What phase 6 ran (2026-11-11, `tests/harness_primitives/`, `tests/loop_orientation/`)

Against the shipped constants, real directories and real bash (`tests/survey_fixtures.py` runs the engine's calls where the files are), through a real `CriaServer` and the pinned Codex 0.159.3:

* **Survey:** one call when the tree fits a frame and waves when it does not (a 1,600-file tree: 18 calls in 3 round trips of at most 16 calls); `FOLD_AT` folds, the entry bound drains the rest as unknown; build outputs on their manifest's proof and `.git` never entered; names with a line break or an undecodable byte left out and their directory not whole; links listed and never followed (a body read through a link is refused), an unreadable directory unknown; bodies of one page, of several pages (25,600 bytes), too large, absent, a directory; programs (including the versioned-name fallback and a name that is quoted data) and outside paths from the coder's own `PATH`; a frame the harness cut asked again smaller; a fresh engine per request gives the same survey; a hostile workspace (planted `python3`, `env`, `ctags`, `sh`, `base64`, shadowed `hashlib`/`os`/`json`/…/`sitecustomize`, `PYTHONPATH`, `PYTHONSTARTUP`, with the planted binaries first on `PATH`) runs none of it; through the server the survey follows the write that landed, the model is asked twice and sees none of it, and the harness's replay of the history asks nothing twice.
* **Inventory:** ctags present (nine languages), missing, not Universal, failing, with workspace `.ctags`/`.ctags.d` and a hostile `CTAGS`; a 9 MiB source with 20,001 symbols indexed where it lives and returned whole; empty, whitespace-only, Unicode-whitespace, binary, invalid-UTF-8, whitespace-then-text and 5,000-byte all-whitespace files; links skipped and reported, excluded directories, an unreadable directory, a symlinked root; restart and a cut frame; the 4,001-file tree (25 directories and a 1,500-file one) in pages: path order, 100 files with facts, no call per file; a hostile workspace; the bootstrap through the real `Loop`; the first coder turn through both public APIs with a real shell.
* **Pinned Codex:** the inventory of the Ruby seed through the sandbox (9 calls, 2 round trips, 0.36 s, nothing left in the workspace or the scratch directory, nothing private in any body the model received) and a survey after a landing write.

### What phase 6b ran (2026-11-11, `tests/harness_primitives/`, `tests/server_config/`, `tests/write_edit/`)

Against the shipped constants, real directories and real bash, through a real `CriaServer` and the pinned Codex 0.159.3:

* **Characterisation** (`test_search_characterization.py`): 105 cases of `grep` / `glob` / `web_fetch` / `web_search` against the capture of the route that preceded this one; 96 are byte for byte the same model-visible text and disk, 9 are intended differences with their assertions (harness-programs.md §7).
* **Engine** (`test_search_ops.py`, `test_answer_ops.py`, `test_probe_ops.py`): order of the walk, batches, the frame ladder, pages of a heavy file (20,000 matches), a page cut and asked as halves, a file changing between pages, restart between any two steps, cut and forged replies, a hostile workspace (planted `python3`/`env`/`sh`/`printf`, shadowed stdlib, `PYTHONPATH`), links in the path and in the saved path, saves of 100 B to 800 KB byte for byte through `put` waves (no command over the 64 KiB budget, no staging file left), the offers settling from the ledger in chat, responses and streamed responses, the search key never in a command, what a file is in ten shapes, the held calls released once.
* **Real server** (`test_server_config_unread_probe.py`): inventory, probe, the held write answered with the seed, the second write; the model asked twice; no private text in any body it received.
* **Pinned Codex 0.159.3** (`test_codex_search_spill.py`): the real server and the real Codex over a tree and two pages; round-trip latency of `ls` / `search` / the 512-byte `read` / a 45,000-byte `put`: 65 / 67 / 65 / 74 ms median (harness-programs.md §7, "Phase 6b result").
