"""A harness that keeps a command alive in a session the way the pinned Codex's `exec_command` and `write_stdin` do (measured against Codex 0.159.3 in this
repository's sandbox policy: tests/harness_primitives/test_codex_gate.py).

* `exec_command` runs `cmd` under `bash -lc`, answers when it ends or when the call's yield time is over: `Process running with session ID N` and what
  it printed so far, and the command goes on in its session (pipes, not a pty: nothing can be written to it);
* `write_stdin` with no characters polls a session: it answers with what the command printed since, at its end or when its own yield time is over;
  an unknown session is `write_stdin failed: Unknown process id N`;
* every exec runs in its own PID namespace whose PID 1 is the command: a process the command left behind (setsid, a double fork) dies when the command
  ends (`unshare --pid --fork --kill-child`), which is what makes a detached supervisor of no use under it.

The yield times are scaled (`exec_yield`, `poll_yield` seconds) so a test of a check that outlives one call takes seconds, not minutes."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

CONTINUATION = {'name': 'write_stdin', 'schema': {'type': 'object', 'required': ['session_id'], 'properties': {
    'session_id': {'type': 'number'}, 'chars': {'type': 'string'}, 'yield_time_ms': {'type': 'number'}}}}
SHELL = {'name': 'exec_command', 'schema': {'type': 'object', 'required': ['cmd'], 'properties': {'cmd': {'type': 'string'}, 'yield_time_ms': {'type': 'number'}}}}


def namespaces_available() -> bool:
    try:
        return subprocess.run(['unshare', '-rpf', '--kill-child', '--mount-proc', 'true'], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class UnifiedExec:
    def __init__(self, cwd, env, exec_yield=1.0, poll_yield=3.0, namespace=True):
        self.cwd, self.env, self.exec_yield, self.poll_yield, self.namespace = str(cwd), env, exec_yield, poll_yield, namespace
        self.sessions, self.next_id, self.log = {}, 1000, []      # the calls it served: (name, arguments)
        self.dir = tempfile.mkdtemp(prefix='unified-exec-')

    def close(self):
        for p, _ in self.sessions.values():
            p.kill()
        shutil.rmtree(self.dir, ignore_errors=True)

    def __call__(self, call):
        name, args = call['function']['name'], json.loads(call['function']['arguments'])
        self.log.append((name, args))
        if name == 'write_stdin':
            return self.poll(args['session_id'], args.get('chars', ''), args.get('yield_time_ms'))
        return self.start(args['cmd'], args.get('yield_time_ms'))

    def start(self, cmd, yield_ms):
        argv = ['bash', '-lc', cmd]
        if self.namespace:
            argv = ['unshare', '-rpf', '--kill-child', '--mount-proc', *argv]
        out = open(os.path.join(self.dir, f'out{self.next_id}'), 'w+b')
        p = subprocess.Popen(argv, cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        sid, self.next_id = self.next_id, self.next_id + 1
        self.sessions[sid] = (p, out)
        return self._answer(sid, p, out, 0, min(self.exec_yield, (yield_ms or 10_000) / 1000), time.monotonic())

    def poll(self, sid, chars, yield_ms):
        if sid not in self.sessions or chars:
            return f'write_stdin failed: Unknown process id {sid}' if sid not in self.sessions else 'write_stdin failed: stdin is closed for this session'
        p, out = self.sessions[sid]
        return self._answer(sid, p, out, getattr(p, 'read_to', 0), min(self.poll_yield, (yield_ms or 5_000) / 1000), time.monotonic())

    def _answer(self, sid, p, out, offset, seconds, began):
        try:
            code = p.wait(seconds)
        except subprocess.TimeoutExpired:
            code = None
        out.seek(offset)
        data = out.read()
        p.read_to = offset + len(data)
        text = data.decode('utf-8', 'replace')
        head = f'Chunk ID: {sid:x}\nWall time: {time.monotonic() - began:.4f} seconds\n'
        if code is None:
            return head + f'Process running with session ID {sid}\nOriginal token count: {len(text) // 4}\nOutput:\n{text}'
        del self.sessions[sid]
        out.close()
        return head + f'Process exited with code {code}\nOriginal token count: {len(text) // 4}\nOutput:\n{text}'


def running(text):
    found = re.search(r'session ID (\d+)', text)
    return int(found.group(1)) if found else None
