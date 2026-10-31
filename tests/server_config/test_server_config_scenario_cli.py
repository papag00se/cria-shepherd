"""`python -m cria` as a real process and through main(): config -> bind -> serve a turn through a fake model -> stop cleanly; bad invocations refused at the edge."""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from cria import __version__, brave
from cria.__main__ import main
from cria.indicators import MARKER
from test_server_config_http import FakeUpstream, chat_body

OPEN = urllib.request.build_opener().open


def events_in(logs):
    return {e["kind"]: e for f in logs.glob("cria-*.jsonl") for e in map(json.loads, f.read_text().splitlines())}


def test_the_service_boots_from_a_config_file_serves_one_turn_and_stops_cleanly_on_sigterm(tmp_path):
    """Env file + call capture on: /health and /v1/models answer, a chat turn round-trips through the fake model and leaves a capture, only cria's
    allowlisted secret is loaded, and SIGTERM (systemd's stop) exits 0 after logging the interrupt stop."""
    fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    fake.chats, fake.release = [], threading.Event()
    threading.Thread(target=fake.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    (tmp_path / ".env").write_text(f"{brave.API_KEY_ENV}=brave-from-file\nUNRELATED_SECRET=nope\n")
    cfg = tmp_path / "cria.toml"
    cfg.write_text(f'env_file = "{tmp_path / ".env"}"\n[defaults]\nbase_url = "http://127.0.0.1:{fake.server_address[1]}"\n[engagement]\nlevel = 3\n'
                   f'[logging]\ndir = "{tmp_path / "logs"}"\nconsole = false\ncapture_calls = true\ncapture_dir = "{tmp_path / "calls"}"\n')
    env = {k: v for k, v in os.environ.items() if k != brave.API_KEY_ENV} | {"HOME": str(tmp_path), "PYTHONPATH": str(Path(__file__).parents[2])}
    proc = subprocess.Popen([sys.executable, "-m", "cria", "--config", str(cfg), "--port", str(port)], cwd=tmp_path, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):  # boot: poll the port, no fixed sleep
            try:
                health = json.load(OPEN(base + "/health", timeout=2))
                break
            except OSError:
                assert proc.poll() is None, proc.stderr.read()
                time.sleep(0.05)
        assert health == {"status": "ok"} and json.load(OPEN(base + "/v1/models", timeout=5))["data"][0]["id"] == "loaded"
        req = urllib.request.Request(base + "/v1/chat/completions", json.dumps(chat_body("hello cli")).encode(), {"Content-Type": "application/json", "X-Cria-Session-Id": "cli"})
        reply = json.load(OPEN(req, timeout=20))["choices"][0]["message"]["content"]
        assert reply.startswith(MARKER) and reply.endswith("\n\nHi")  # the status banner, then the model's text
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=15) == 0
    finally:
        proc.kill()
        fake.shutdown()
    ev = events_in(tmp_path / "logs")
    assert ev["server.start"]["port"] == port and ev["server.stop"]["reason"] == "interrupt"
    assert ev["env.loaded"]["count"] == 1 and "UNRELATED_SECRET" not in ev["env.loaded"]["vars"]
    assert ev["capture.enabled"] and (tmp_path / "calls" / "cli" / "0001-proxy.json").is_file()


def test_main_refuses_bad_config_and_applies_cli_overrides_then_drains_on_interrupt(tmp_path, monkeypatch, capsys):
    """A missing file and a removed [context] key exit 2 with a message; --port overrides the file; an interrupt (what SIGTERM is routed to) drains streams and logs the stop."""
    assert main(["--config", str(tmp_path / "absent.toml")]) == 2 and "config error" in capsys.readouterr().err
    (tmp_path / "bad.toml").write_text("[context]\ntrigger_compaction = 5\n")
    assert main(["--config", str(tmp_path / "bad.toml")]) == 2 and "trigger_compaction was removed" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out
    (tmp_path / "cria.toml").write_text(f'[logging]\ndir = "{tmp_path / "logs"}"\nconsole = false\n')
    seen = {}

    def interrupted(self):
        seen["handler"] = signal.getsignal(signal.SIGTERM)
        raise KeyboardInterrupt

    old = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr("cria.server.CriaServer.serve_forever", interrupted)
    try:
        assert main(["--config", str(tmp_path / "cria.toml"), "--host", "127.0.0.1", "--port", "0", "--log-level", "debug"]) == 0
        with pytest.raises(KeyboardInterrupt):
            seen["handler"](signal.SIGTERM, None)  # SIGTERM is turned into the same graceful path
    finally:
        signal.signal(signal.SIGTERM, old)
    assert events_in(tmp_path / "logs")["server.start"]["port"] == 0 and events_in(tmp_path / "logs")["server.stop"]["drained_streams"] == 0
