"""The pinned Codex (0.159.3) in the repo's machine-local sandbox, driven against an HTTP endpoint the test controls."""
import json
import os
import subprocess
import threading
import time

import pytest

from suite import run as suite_run


def pinned_codex_available():
    return suite_run.RESTORED_CODEX_BINARY.is_file() and os.access(suite_run.RESTORED_CODEX_BINARY, os.X_OK) and suite_run.SUITE_CODEX_POLICY.is_file()


needs_codex = pytest.mark.skipif(not pinned_codex_available(), reason='requires the pinned Codex 0.159.3 and the machine-local sandbox policy')


class Sandbox:
    """A workspace plus the Codex state directory beside it; `run` launches the pinned Codex in the sandbox policy."""
    def __init__(self, tmp_path, monkeypatch):
        self.workspace = tmp_path / 'workspace'
        self.workspace.mkdir()
        for name in ('.agents', '.aws', '.codex', '.git'):          # protected mount points Codex's sandbox may create itself
            (self.workspace / name).mkdir()
        installs = tmp_path / 'installs'
        installs.mkdir()
        monkeypatch.setattr(suite_run, 'CELL_INSTALLS_DIR', installs)
        self.scratch = suite_run._cell_install_root(self.workspace)
        self.scratch.mkdir()
        self.home = self.scratch / 'codex-home'
        self.home.mkdir()

    def run(self, base_url, prompt='start', timeout=240):
        (self.home / 'config.toml').write_text(
            f'model="fixture"\nmodel_provider="local"\n[model_providers.local]\nname="local"\nbase_url="{base_url}"\nwire_api="responses"\n')
        argv = suite_run._codex_argv(prompt, self.workspace)
        argv[0] = str(suite_run.RESTORED_CODEX_BINARY)
        argv.insert(2, '--skip-git-repo-check')
        version = subprocess.run([argv[0], '--version'], capture_output=True, text=True).stdout.strip()
        assert version == 'codex-cli 0.159.3', version
        return subprocess.run(argv, cwd=self.workspace, env={**os.environ, 'CODEX_HOME': str(self.home), 'TMPDIR': str(self.scratch)},
                              capture_output=True, text=True, timeout=timeout)


    def run_until(self, base_url, done, prompt='start', timeout=240):
        """The pinned Codex as `run` launches it, stopped as soon as `done()` is true (or after `timeout` seconds): a test that wants one thing a scripted
        model makes happen need not wait for Codex to finish by itself. Returns Codex's return code, None when it was stopped."""
        import signal
        (self.home / 'config.toml').write_text(
            f'model="fixture"\nmodel_provider="local"\n[model_providers.local]\nname="local"\nbase_url="{base_url}"\nwire_api="responses"\n')
        argv = suite_run._codex_argv(prompt, self.workspace)
        argv[0] = str(suite_run.RESTORED_CODEX_BINARY)
        argv.insert(2, '--skip-git-repo-check')
        proc = subprocess.Popen(argv, cwd=self.workspace, env={**os.environ, 'CODEX_HOME': str(self.home), 'TMPDIR': str(self.scratch)},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        end = time.monotonic() + timeout
        try:
            while proc.poll() is None and time.monotonic() < end and not done():
                time.sleep(0.25)
            return proc.returncode
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)


def function_calls(request):
    """The tool calls and outputs of a Responses request: [(call_id, arguments JSON, output text or None)]."""
    calls, outputs = {}, {}
    for item in request.get('input') or []:
        if item.get('type') == 'function_call':
            calls[item['call_id']] = item['arguments']
        elif item.get('type') == 'function_call_output':
            out = item.get('output')
            outputs[item['call_id']] = out if isinstance(out, str) else json.dumps(out)
    return [(cid, args, outputs.get(cid)) for cid, args in calls.items()]


class Timeline:
    """Round trips as the model endpoint sees them: from the moment a tool call is sent to the moment Codex's next request
    (carrying its result) arrives. That span is the harness executing the command plus its own turn around it."""
    def __init__(self):
        self.sent, self.seconds, self.lock = None, [], threading.Lock()

    def request_arrived(self):
        with self.lock:
            if self.sent is not None:
                self.seconds.append(time.monotonic() - self.sent)
                self.sent = None

    def reply_sent(self, tool_call):
        with self.lock:
            self.sent = time.monotonic() if tool_call else None
