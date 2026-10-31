"""A gem the model INSTALLS in a Ruby cell must be loadable in that same cell.

Sibling of test_a_ruby_cell_can_still_load_rubys_own_gems: same root cause (GEM_PATH REPLACES the
search path, it does not extend it), different missing entry. That test guards Ruby's OWN gems
(minitest/rake); this guards the cell's OWN installs.

On this box `gem install` defaults to `--user-install`, landing in `Gem.user_dir` (derived from the
XDG_DATA_HOME the cell sets -> root/xdg-data/gem/ruby/<api>), NOT in GEM_HOME. If GEM_PATH names only
`root/gem` + Ruby's own gems, the just-installed gem is invisible and `require` raises LoadError.
Walked 2026-09-19, shipping-rates-rb x ternary-bonsai-2: the coder understood the one-line fix at
turn 7, then spent turns 8-45 unable to load the EU gem it installed and ran out of budget as it
finally began writing -> scored 0, a measurement of this bug, not the model.

Exercises the REAL environment run.py builds and actually asks Ruby to load the gem (the previous
generation of this bug was 'verified' by reading Gem paths and was wrong about what they mean).
Skipped where Ruby is absent or offline, so the suite still runs on a box without Ruby.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suite"))
import run  # noqa: E402


def _ruby() -> str | None:
    from shutil import which
    return which("ruby")


@pytest.mark.skipif(_ruby() is None, reason="Ruby not installed on this box")
def test_a_gem_installed_in_the_cell_can_be_required_in_the_cell():
    with tempfile.TemporaryDirectory() as ws:
        env = {**os.environ, **run._isolated_installs(ws)}
        # The cell's own user-install dir must be named on GEM_PATH.
        assert any("xdg-data" in p and "gem" in p for p in env["GEM_PATH"].split(os.pathsep)), \
            "the cell's own gem user-dir is not on GEM_PATH"
        inst = subprocess.run(["gem", "install", "--quiet", "paint"],
                              env=env, capture_output=True, text=True, timeout=180)
        if inst.returncode != 0:
            pytest.skip(f"gem install unavailable/offline: {inst.stderr.strip()[:120]}")
        got = subprocess.run(["ruby", "-e", 'require "paint"; print "OK"'],
                             env=env, capture_output=True, text=True, timeout=30)
        assert got.stdout.strip() == "OK", \
            f"a gem installed in the cell did not load: {got.stderr.strip()[:200]}"


@pytest.mark.skipif(_ruby() is None, reason="Ruby not installed on this box")
def test_the_fix_does_not_hide_rubys_own_gems():
    # Guard against reintroducing the 9ac6654 regression while adding the cell dir.
    with tempfile.TemporaryDirectory() as ws:
        env = {**os.environ, **run._isolated_installs(ws)}
        # `require "minitest"` (not /autorun) so we don't trigger minitest's at_exit runner, which
        # would append its own report to stdout.
        got = subprocess.run(["ruby", "-e", 'require "minitest"; print "OK"'],
                             env=env, capture_output=True, text=True, timeout=30)
        assert got.stdout.strip() == "OK", \
            f"Ruby's own minitest no longer loads: {got.stderr.strip()[:200]}"
