"""A cell's package isolation must not hide the language's OWN standard gems.

`GEM_PATH` REPLACES Ruby's search path rather than extending it, so an isolation env that names only
the cell directory hides `minitest`, `rake` and `bundler`, which ship with Ruby. That has now broken
the Ruby cells TWICE:

  * 2026-08-28, shipping-rates-rb x nemotron-elastic: 24 of 60 calls spent on five ways to load
    minitest, `cannot load such file -- minitest/autorun` in 51 of 61 prompts, cell scored 8.
  * 2026-09-18, shipping-rates-rb x ternary-bonsai-2: the keep-list computed EMPTY because it
    subtracted `Gem.default_dir`, which on this box is where Ruby's own gems live. The coder spent
    its entire first 32 minutes trying to obtain a working minitest — including attempts to install
    into `/usr/lib/ruby/gems`, correctly denied by cria — and wrote none of the five deliverables.

Both times the failure was silent: `_ruby_keep_path` returns `[]` on any trouble, by design, so an
empty keep-list looks exactly like "this box has no Ruby". These tests make the difference visible.

They exercise the REAL environment the runner builds, and actually ask Ruby to load the gem, because
the previous fix was verified by reading `Gem.default_path` and was wrong about what that list means.
Skipped where Ruby is absent, so the suite still runs on a box without it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "suite"))

from suite.run import _cell_install_root, _isolated_installs, _ruby_keep_path  # noqa: E402

_HAS_RUBY = shutil.which("ruby") is not None


@pytest.mark.skipif(not _HAS_RUBY, reason="no ruby on this host")
def test_the_keep_list_is_not_empty_when_ruby_is_installed():
    """The regression itself: Ruby IS here, so the keep-list must name where its gems live.
    Fails before the fix (subtracting Gem.default_dir emptied it), passes after."""
    keep = _ruby_keep_path()
    assert keep, (
        "_ruby_keep_path() is empty while ruby is installed — GEM_PATH will be the cell alone and "
        "minitest/rake/bundler will be invisible to every Ruby cell."
    )


@pytest.mark.skipif(not _HAS_RUBY, reason="no ruby on this host")
def test_a_cell_env_can_load_minitest(tmp_path):
    """The consequence, asked of Ruby rather than inferred: the task says 'fix the failing tests',
    and the tests are minitest."""
    env = {**os.environ, **_isolated_installs(tmp_path)}
    r = subprocess.run(
        ["ruby", "-e", "require 'minitest/autorun'; print 'OK'"],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert r.returncode == 0 and "OK" in r.stdout, (
        f"a cell cannot load minitest under its isolation env.\nstderr: {r.stderr[-600:]}"
    )


@pytest.mark.skipif(not _HAS_RUBY, reason="no ruby on this host")
def test_the_cell_env_still_hides_the_leaked_user_gems(tmp_path):
    """The isolation must still do its job: `Gem.user_dir` is where `--user-install` leaks land
    (`iso_country_codes`, `countries`), and it must NOT be on the cell's search path."""
    user_dir = subprocess.run(
        ["ruby", "-e", "print Gem.user_dir"], capture_output=True, text=True, timeout=60,
    ).stdout.strip()
    assert user_dir, "could not ask ruby for Gem.user_dir"
    assert user_dir not in _ruby_keep_path(), (
        f"the leaked user gem root {user_dir} is on the cell's GEM_PATH — one cell's hand-installed "
        f"gem would be discoverable by every later cell."
    )


@pytest.mark.skipif(not _HAS_RUBY, reason="no ruby on this host")
def test_an_install_still_lands_inside_the_cell(tmp_path):
    """Isolation's other half: GEM_HOME must point into the cell, so nothing this run installs is
    visible to the next one."""
    env = _isolated_installs(tmp_path)
    assert str(_cell_install_root(tmp_path)) in env["GEM_HOME"]
    assert str(tmp_path) not in env["GEM_HOME"]
    home = subprocess.run(
        ["ruby", "-e", "print Gem.dir"], capture_output=True, text=True, timeout=60,
        env={**os.environ, **env},
    ).stdout.strip()
    assert str(_cell_install_root(tmp_path)) in home, f"a gem install would land at {home}, outside its private cell root"
