"""The chatty-login-shell rig: a REAL `bash -lc` on a REAL PTY whose profile prints noise around the program, wrapped the way the pinned
Codex wraps a result. Shared by the read, write/edit and completion-gate noise tests."""
import os
import pty
import subprocess

MISE = 'mise WARN  GitHub rate limit exceeded. Resets at 2026-10-31 16:32:13 -07:00\n'

def noise(n):
    """`n` bytes of what a chatty login shell (mise, direnv, a noisy profile) prints."""
    return (MISE * (n // len(MISE) + 1))[:n]

def codex_result(raw: bytes, code: int = 0) -> str:
    """The harness's own envelope: whole under 10,000 bytes, else head 5,000 + marker + tail 5,000 behind the cut warning
    (the exact shape of the wave-10 E2EA capture: 17,898 bytes in, head 5,000, `…7898 chars truncated…`, tail 5,000)."""
    tokens = -(-len(raw) // 4)
    head = 'Chunk ID: 3a9c1e\nWall time: 1.1236 seconds\nProcess exited with code %d\nOriginal token count: %d\nOutput:\n' % (code, tokens)
    text = raw.decode('utf-8', 'replace')
    if len(raw) <= 10000:
        return head + text
    return (head + 'Warning: truncated output (original token count: %d)\nTotal output lines: %d\n\n' % (tokens, raw.count(b'\n'))
            + text[:5000] + '…%d chars truncated…' % (len(text) - 10000) + text[-5000:])

def chatty_pty(command, cwd, before_out=0, before_err=0, after=0, env=None, home=None):
    """Run `command` in a REAL `bash -lc` on a REAL PTY whose profile prints noise on stdout and stderr before the program and from an
    EXIT trap after it; returns (raw bytes, exit code). The profile lives in a private HOME under `cwd`; `env` adds variables (a TMPDIR for a gate).
    `home` moves that private HOME out of `cwd` (a test whose workspace must hold nothing but its own files)."""
    home = home or os.path.join(cwd, 'shellhome'); os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, '.bash_profile'), 'w') as f:
        f.write('printf %s "$N_OUT"; printf %s "$N_ERR" >&2; trap \'printf %s "$N_AFTER"\' EXIT\n')
    env = dict(os.environ, HOME=home, N_OUT=noise(before_out), N_ERR=noise(before_err), N_AFTER=noise(after), **(env or {}))
    master, slave = pty.openpty()
    p = subprocess.Popen(['bash', '-lc', command], stdout=slave, stderr=slave, env=env, cwd=cwd); os.close(slave); data = bytearray()
    while True:
        try: chunk = os.read(master, 65536)
        except OSError: break
        if not chunk: break
        data.extend(chunk)
    os.close(master)
    return bytes(data), p.wait()
