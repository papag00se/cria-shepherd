"""Every executable location that suite isolation redirects must be usable by the same cell.

The runner used to set install roots without their bin dirs on PATH: npm -g, pip --user console
scripts, and uv tool installs succeeded but a following shell command could not run them. Stock
npm's prefix bin and Python's ~/.local/bin are on this host's PATH, so that was a cria regression.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suite"))
import run  # noqa: E402


def test_every_cell_redirected_bin_dir_is_on_path_and_runs_its_command(tmp_path):
    env = {**os.environ, **run._isolated_installs(tmp_path)}
    bins = run._cell_install_bin_dirs(tmp_path / ".cell-installs")
    assert all(p in env["PATH"].split(os.pathsep) for p in bins)

    # Exercise command discovery, not a string-only PATH assertion. Any package manager that creates
    # its documented executable under one of these roots now has the same property.
    for n, directory in enumerate(bins):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        name = f"cell-command-{n}"
        exe = path / name
        exe.write_text("#!/bin/sh\nprintf '%s' ok\n")
        exe.chmod(0o755)
        got = subprocess.run(["sh", "-c", name], env=env, capture_output=True, text=True, timeout=30)
        assert got.returncode == 0 and got.stdout == "ok", (directory, got.stderr)


def test_cell_commands_win_over_an_ambient_command_with_the_same_name(tmp_path, monkeypatch):
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    name = "cell-command-precedence"
    host = ambient / name
    host.write_text("#!/bin/sh\nprintf '%s' host\n")
    host.chmod(0o755)
    monkeypatch.setenv("PATH", f"{ambient}{os.pathsep}{os.environ['PATH']}")
    env = {**os.environ, **run._isolated_installs(tmp_path)}
    cell = Path(run._cell_install_bin_dirs(tmp_path / ".cell-installs")[0])
    cell.mkdir(parents=True)
    own = cell / name
    own.write_text("#!/bin/sh\nprintf '%s' cell\n")
    own.chmod(0o755)
    got = subprocess.run(["sh", "-c", name], env=env, capture_output=True, text=True, timeout=30)
    assert got.returncode == 0 and got.stdout == "cell"
