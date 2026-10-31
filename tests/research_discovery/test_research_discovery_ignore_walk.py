"""Ignore rules never prune real source: a directory is skipped only on PROOF a tool generated it, and the walk names what it skipped."""
import os

import pytest

from cria import ignore, linterprobe
from cria.linterprobe import LinterFinding, LinterReport
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")

def test_a_directory_is_skipped_only_on_proof_that_a_tool_generated_it():
    """Templates pruned an unanchored `lib/`/`build/`: a package the model just wrote vanished from the lint floor and the gate said clean."""
    kids = lambda *n: (lambda: list(n))
    never_listed = []
    assert ignore.generated("node_modules", lambda: never_listed.append(1) or []) and never_listed == []   # the name alone decided it
    assert "pyvenv.cfg" in ignore.generated("handle_resolver", kids("pyvenv.cfg", "bin"))                    # a venv under ANY name
    assert ignore.generated("target", kids("CACHEDIR.TAG", "debug")) and "site-packages" in ignore.generated("deps", kids("site-packages"))
    assert "gems" in ignore.generated("3.2.0", kids("bin", "gems", "specifications"))                        # RubyGems install root
    assert "composer" in ignore.generated("vendor", kids("autoload.php", "composer", "psr"))                 # composer vendor tree
    for name in ("lib", "build", "dist", "out", "target", "env", "vendor", "bin"):
        assert ignore.generated(name, kids("shipping.rb", "rates.rb")) is None, name   # ambiguous with no marker: WALKED
    assert ignore.generated("build", lambda: None) is None   # could not look is not 'yes'
    # half a pair proves nothing: an author's `gems/` or `autoload.php`
    assert ignore.generated("gems", kids("europe.rb")) is None and ignore.generated("src", kids("autoload.php", "Model.php")) is None

def test_the_floor_walk_skips_installed_trees_keeps_the_authors_source_and_names_what_it_skipped(tmp_path):
    write(tmp_path / "myenv", "pyvenv.cfg", "home = /usr\n")
    write(tmp_path / "myenv/lib/python3.12/site-packages/pip", "x.py", "import os\n")
    write(tmp_path / "node_modules/left-pad", "i.py", "x\n")
    write(tmp_path / "lib/handlers", "zones.py", "x = (\n")   # the regression: `lib/` pruned at any depth
    write(tmp_path, "resolver.py", "print(1)\n")
    files, skipped = linterprobe.collect_files_with_skips(str(tmp_path), ["py"])
    assert sorted(os.path.relpath(p, tmp_path) for p in files) == [os.path.join("lib/handlers/zones.py"), "resolver.py"]
    assert sorted(skipped) == ["myenv (contains pyvenv.cfg)", "node_modules (a tool owns this name)"]

@pytest.mark.skipif(os.geteuid() == 0, reason="root can list an unreadable directory")
def test_a_directory_that_cannot_be_listed_is_named_not_dropped(tmp_path):
    write(tmp_path, "app.py", "x = 1\n")
    (tmp_path / "locked").mkdir()
    os.chmod(tmp_path / "locked", 0o000)
    try:
        _, skipped = linterprobe.collect_files_with_skips(str(tmp_path), ["py"])
    finally:
        os.chmod(tmp_path / "locked", 0o755)
    assert skipped == ["locked (could not be listed)"]

def test_a_clean_verdict_names_what_it_did_not_read():
    """#11b: a mechanism may only speak about what it reached."""
    clean = [LinterFinding("python", "py_compile", True)]
    said = LinterReport(findings=clean, skipped_dirs=["node_modules", "myenv"]).probe_digest()
    assert "node_modules" in said and "myenv" in said
    assert "Not checked" not in LinterReport(findings=clean).probe_digest()
