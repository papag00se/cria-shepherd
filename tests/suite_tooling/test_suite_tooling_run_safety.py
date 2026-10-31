"""suite/run.py safety promises: Codex only through the sandboxed launcher, per-cell isolation,
a cell stops only its own process group, throttled runs are annotated, one suite runner at a time."""
import json
import os
import shutil
import signal
import subprocess
import tomllib
from pathlib import Path

import pytest

from suite import preflight, run
from suite.run_guard import other_suite_runners


@pytest.fixture
def policy(tmp_path, monkeypatch):
    path = tmp_path / "policy.toml"
    path.write_text("workspace_sandbox = true\n")
    monkeypatch.setattr(run, "SUITE_CODEX_POLICY", path)
    return path


@pytest.mark.parametrize("text", [None, "workspace_sandbox = false\n", "workspace_sandbox = 1\n",
                                  'workspace_sandbox = "true"\n', "", "[broken",
                                  "workspace_sandbox = true\nextra = true\n"])
def test_missing_or_invalid_policy_refuses_the_launch(tmp_path, policy, text):
    """Missing/malformed/widened machine policy raises instead of yielding an unsandboxed (--yolo) argv."""
    policy.unlink() if text is None else policy.write_text(text)
    with pytest.raises(ValueError, match="policy"):
        run._codex_argv("task", tmp_path)


@pytest.mark.parametrize("workspace", [None, "/", "relative-cell"])
def test_no_implicit_root_or_relative_workspace_grant(policy, workspace):
    """The writable grant is an explicit absolute non-root cell, never cwd or '/'."""
    with pytest.raises(ValueError, match="workspace"):
        run._codex_argv("task", workspace)


def test_codex_argv_grants_write_only_to_the_cell_and_its_install_root(tmp_path, policy, monkeypatch):
    """Filesystem is read-only except the exact cell paths; fresh profile name per launch (no inherited grants)."""
    ws, state = tmp_path / "ws", tmp_path / "state"
    ws.mkdir()
    monkeypatch.setattr(run, "_cell_install_root", lambda _ws: state)
    argv = run._codex_argv("task", ws)
    assert "--yolo" not in argv and 'approval_policy="never"' in argv and argv[-1] == "task"
    profile = tomllib.loads(next(a for a in argv if a.startswith("default_permissions=")))["default_permissions"]
    perms = tomllib.loads(next(a for a in argv if a.startswith("permissions=")))["permissions"]
    assert perms[profile]["filesystem"] == {"/": "read", str(ws): "write", str(state): "write"}
    again = run._codex_argv("task", ws)
    assert next(a for a in again if a.startswith("default_permissions=")) != \
        next(a for a in argv if a.startswith("default_permissions="))


def test_codex_home_is_forced_and_missing_home_fails_closed(tmp_path, monkeypatch):
    """An ambient CODEX_HOME must not repoint the harness; a missing isolated home stops the run."""
    monkeypatch.setattr(run, "SUITE_CODEX_HOME", tmp_path / "no-such-home")
    base = {"CODEX_HOME": "/home/someone/.codex", "KEEP": "1"}
    env = run._codex_env(base)
    assert env["CODEX_HOME"] == str(tmp_path / "no-such-home") and env["KEEP"] == "1"
    assert base["CODEX_HOME"] == "/home/someone/.codex"
    with pytest.raises(RuntimeError):
        run._require_codex_home()


@pytest.mark.skipif(not shutil.which("codex"), reason="needs the local Codex sandbox")
def test_real_codex_sandbox_denies_writes_outside_the_cell(tmp_path, policy, monkeypatch):
    """The argv really sandboxes: outside unlink/write/rename are denied even if config.toml grants write."""
    ws, state, home = (tmp_path / n for n in ("ws", "state", "codex"))
    for d in (ws, state, home):
        d.mkdir()
    monkeypatch.setattr(run, "_cell_install_root", lambda _ws: state)
    (home / "config.toml").write_text('[permissions.cria_suite.filesystem]\n'
                                      + json.dumps(str(tmp_path)) + '="write"\n')
    outside = tmp_path / "sentinel"
    outside.write_text("preserve")
    settings = run._codex_argv("unused", ws)[2:-1]
    profile = tomllib.loads(next(a for a in settings if a.startswith("default_permissions=")))["default_permissions"]
    code = ("import pathlib,sys\np=pathlib.Path(sys.argv[1])\n"
            "for op in (p.unlink, lambda: p.write_text('x'), lambda: p.rename(pathlib.Path.cwd()/'stolen')):\n"
            "    try: op()\n    except OSError: pass\n    else: raise SystemExit('outside mutation allowed')\n"
            "pathlib.Path('inside').write_text('ok')\n")
    res = subprocess.run(["codex", "sandbox", "-P", profile, *settings, "-C", str(ws), "--",
                          "python3", "-c", code, str(outside)],
                         env={**os.environ, "CODEX_HOME": str(home), "TMPDIR": str(state)},
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert outside.read_text() == "preserve" and (ws / "inside").read_text() == "ok"


def _isolated(tmp_path, monkeypatch, ruby=()):
    root = tmp_path / "installs"
    monkeypatch.setattr(run, "_cell_install_root", lambda _ws: root)
    monkeypatch.setattr(run, "_ruby_keep_path", lambda: ["/usr/lib/ruby/gems"])
    monkeypatch.setattr(run, "_ruby_cell_install_dirs", lambda _r: list(ruby))
    return root, run._isolated_installs(tmp_path / "ws")


def test_every_ecosystem_cache_and_install_root_is_inside_the_cell(tmp_path, monkeypatch):
    """Ambient host cache vars (Go/Cargo/Maven/pip/npm/gem) are overridden into the cell root;
    only unrelated JVM options survive. Cargo/Go/Maven runs once failed writing the read-only host dirs."""
    monkeypatch.setenv("GOPATH", "/host/go")
    monkeypatch.setenv("CARGO_HOME", "/host/cargo")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Dkeep=yes -Dmaven.repo.local=/host/m2")
    root, env = _isolated(tmp_path, monkeypatch, ruby=[str(tmp_path / "installs/xdg-data/gem/ruby/3.3.0")])
    for key in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "GEM_HOME", "PYTHONUSERBASE", "npm_config_prefix",
                "GOPATH", "GOMODCACHE", "GOCACHE", "GOBIN", "CARGO_HOME", "CARGO_INSTALL_ROOT"):
        assert Path(env[key]).is_relative_to(root), key
    assert not root.is_relative_to(tmp_path / "ws")           # evidence tree stays clean
    java = env["JAVA_TOOL_OPTIONS"]
    assert "-Dkeep=yes" in java
    assert java.index(json.dumps("-Dmaven.repo.local=" + str(root / "m2/repository"))) > java.index("/host/m2")
    assert json.dumps("-Djava.io.tmpdir=" + str(root / "java-tmp")) in java
    gem_path = env["GEM_PATH"].split(os.pathsep)
    assert gem_path == [str(root / "gem"), str(tmp_path / "installs/xdg-data/gem/ruby/3.3.0"),
                        "/usr/lib/ruby/gems"]      # replaces, not extends: cell + own installs + Ruby's own


def test_cell_install_root_is_private_per_workspace_and_outside_the_workspace(tmp_path):
    """Install state lives under cria's dir keyed by workspace name, never in the task tree."""
    root = run._cell_install_root(tmp_path / "cell-a")
    assert root.is_relative_to(run.CELL_INSTALLS_DIR) and root != run._cell_install_root(tmp_path / "cell-b")
    assert not root.is_relative_to(tmp_path)


def test_cell_installed_commands_run_and_beat_ambient_ones(tmp_path, monkeypatch):
    """Each redirected bin dir is on PATH ahead of the host's: `npm -g`/pip/uv installs are runnable.
    Before the fix installs succeeded but the next shell command could not find them."""
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    monkeypatch.setenv("PATH", f"{ambient}{os.pathsep}{os.environ['PATH']}")
    root, env = _isolated(tmp_path, monkeypatch)
    bins = run._cell_install_bin_dirs(root)
    assert all(b in env["PATH"].split(os.pathsep) for b in bins)
    for n, directory in enumerate(bins):
        name = f"cell-cmd-{n}"
        for where, word in ((Path(directory), "cell"), (ambient, "host")):
            where.mkdir(parents=True, exist_ok=True)
            (where / name).write_text(f"#!/bin/sh\nprintf {word}\n")
            (where / name).chmod(0o755)
        out = subprocess.run(["sh", "-c", name], env={**os.environ, **env}, capture_output=True, text=True)
        assert out.stdout == "cell", (directory, out.stderr)


class _Proc:
    def __init__(self, pid):
        self.pid, self.waited = pid, False

    def wait(self, timeout):
        self.waited = True


def test_stopping_a_cell_signals_only_its_own_group_even_if_the_leader_exited(monkeypatch):
    """SIGINT then SIGKILL to proc.pid's group only (never a process-list sweep of other Codex runs)."""
    sent = []
    monkeypatch.setattr(run.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    proc = _Proc(731)
    run.stop_process_group(proc, grace=0, sleeper=lambda _: None)
    assert sent == [(731, signal.SIGINT), (731, signal.SIGKILL)] and proc.waited


@pytest.mark.parametrize("hits,expect", [(run.THROTTLE_PROMPTS, True), (1, False), (0, False)])
def test_a_run_peppered_with_403s_is_flagged_throttled_but_a_stray_one_is_not(tmp_path, hits, expect):
    """api.handle.me throttled 251 coder prompts across 3 runs that were scored as ordinary failures."""
    for i in range(hits):
        (tmp_path / f"{i:04d}-coder-s1.prompt.txt").write_text("HTTP error 403 for https://x/handles/goose")
    assert bool(run.throttled_mid_run(tmp_path)) is expect
    assert run.throttled_mid_run(None) == ""


def test_other_suite_runner_is_reported_but_never_signalled(tmp_path):
    """The overlap guard only reads /proc; an unowned (paused) runner is listed and left untouched."""
    for pid, argv in ((101, b"python3\0/r/suite/run.py\0"), (102, b"python3\0/r/suite/run.py\0--task\0p\0"),
                      (103, b"python3\0/r/suite/battery_run.py\0")):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "cmdline").write_bytes(argv)
    assert [pid for pid, _ in other_suite_runners(tmp_path, self_pid=101)] == [102]


@pytest.mark.parametrize("target,flagged", [
    (str(run.RUNS_DIR / "suite-handles-cli-node_x_codex_pon_1-abcd"), True),
    ("/tmp/suite-old-run-abcd1234", True),
    ("/home/someone/src/my-project", False),
    (str(run.RUNS_DIR) + "-elsewhere/pkg", False)])
def test_stale_editable_install_into_a_run_workspace_is_flagged(tmp_path, monkeypatch, target, flagged):
    """A `pip install -e` .pth into a (durable RUNS_DIR or /tmp) run workspace poisons later cells; siblings sharing the prefix don't."""
    (tmp_path / "__editable__.x-0.1.pth").write_text(target + "\n")
    monkeypatch.setattr(preflight.site, "getusersitepackages", lambda: str(tmp_path))
    assert bool([f for f in preflight.stale_suite_installs() if f["target"] == target]) is flagged
