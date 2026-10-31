"""`python -m cria` start-up refusals and overrides through main(): a missing prompt file stops the boot (exit 2, names it on stderr), an enabled
System 1 that cannot load stops it with a logged reason, `--host/--port/--log-level` land on the running server, and a configured env file that
supplies nothing is a warning, not silence."""
import json
import signal

import pytest

from cria import prompts
from cria.__main__ import main
from cria.server import CriaServer


def events(logs):
    return [json.loads(line) for f in sorted(logs.glob("cria-*.jsonl")) for line in f.read_text().splitlines()]


def write_cfg(tmp_path, extra=""):
    (tmp_path / "cria.toml").write_text(f'{extra}\n[logging]\ndir = "{tmp_path / "logs"}"\nconsole = false\n')
    return ["--config", str(tmp_path / "cria.toml")]


def test_a_boot_with_a_referenced_prompt_missing_is_refused_before_a_server_exists(tmp_path, monkeypatch, capsys):
    built = []
    monkeypatch.setattr(prompts, "validate_referenced", lambda log: ["renamed_one", "renamed_two"])
    monkeypatch.setattr(CriaServer, "__init__", lambda self, *a, **k: built.append(1))
    assert main(write_cfg(tmp_path)) == 2
    assert "missing prompt file(s): renamed_one, renamed_two" in capsys.readouterr().err and built == []


def test_an_enabled_classifier_that_cannot_load_refuses_the_boot_and_says_why_in_the_log(tmp_path, capsys):
    argv = write_cfg(tmp_path, f'[system1]\nenabled = true\nbundle_dir = "{tmp_path / "no-bundle"}"')
    assert main(argv) == 2
    assert "not a directory" in capsys.readouterr().err
    refused = [e for e in events(tmp_path / "logs") if e["kind"] == "system1.startup_refused"]
    assert len(refused) == 1 and refused[0]["level"] == "error" and "not a directory" in refused[0]["error"]
    assert not [e for e in events(tmp_path / "logs") if e["kind"] == "server.start"]


def test_a_configured_env_file_that_supplies_nothing_is_a_warning_and_the_interrupt_stop_is_logged(tmp_path, monkeypatch):
    """An env file whose variables are all outside cria's allowlist loads 0 and says so at warn level (a daemon silently starting without its key
    was the failure this logs); the interrupt drain is still logged as the stop."""
    (tmp_path / ".env").write_text("UNRELATED=1\n")
    old = signal.getsignal(signal.SIGTERM)

    def serve(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(CriaServer, "serve_forever", serve)
    try:
        assert main(write_cfg(tmp_path, f'env_file = "{tmp_path / ".env"}"') + ["--port", "0"]) == 0
    finally:
        signal.signal(signal.SIGTERM, old)
    logged = events(tmp_path / "logs")
    loaded = [e for e in logged if e["kind"] == "env.loaded"]
    assert len(loaded) == 1 and loaded[0]["count"] == 0 and loaded[0]["level"] == "warn" and "UNRELATED" not in loaded[0]["vars"]
    assert [e["reason"] for e in logged if e["kind"] == "server.stop"] == ["interrupt"]
