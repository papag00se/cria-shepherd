"""Dependency surface (ground truth read from the resolved source) and the missing-dependency note (asks the disk)."""
import os

import pytest

from cria import depsurface, probeparse, proberun, prompts
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")
GO_SRC = ("package decimal\n\ntype Decimal struct {\n\tvalue *big.Int\n}\n\n"
          "func NewFromString(value string) (Decimal, error) {\n\treturn Decimal{}, nil\n}\n\n"
          "func (d Decimal) Round(places int32) Decimal {\n\treturn d\n}\n\n"
          "func (a *decimal) Round(nd int) {}\n\nfunc lowerCaseHelper() int {\n\treturn 0\n}\n")
GO_DOC = '''package cronish // import "example.com/cronish"

Package pkg is a stand-in for robfig/cron's shape.

CONSTANTS

const (
	Second = 1 << iota
	Minute
	Dow
)
    Predefined schedules.

TYPES

type Entry struct {
	ID   int
	Next int64
}
    Entry describes a scheduled job.

func New() *Entry
'''

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path

def test_a_surface_is_the_real_source_or_nothing(home):
    """No cache, unknown ecosystem or missing coordinate abstain (never an invented surface); the scan keeps only
    exported, byte-exact signature lines of non-test files, and is never labelled complete."""
    assert depsurface.gather("go", "example.invalid/x", "v1.0.0") is None
    assert depsurface.gather("rust", "toml", "0.8.23") is None and depsurface.gather("ruby", "countries", "3.1.0") is None
    assert [depsurface.gather(*a) for a in (("cobol", "w", "1.0"), ("go", "", "v1"), ("go", "github.com/x/y", ""), ("jvm", "no-colon", "1.0"))] == [None] * 4
    mod = home / "go/pkg/mod/example.invalid/nonexistent@v1.4.0"
    write(mod, "decimal.go", GO_SRC)
    write(mod, "decimal_test.go", "package decimal\nfunc TestSomething() {}\n")
    surface = depsurface.gather("go", "example.invalid/nonexistent", "v1.4.0")
    assert not surface.complete and "decimal_test.go" not in surface.sources
    assert set(surface.lines) == {"type Decimal struct {", "func NewFromString(value string) (Decimal, error) {",
                                  "func (d Decimal) Round(places int32) Decimal {"}   # unexported receiver/name excluded
    assert all(line in GO_SRC.splitlines() for line in surface.lines)
    assert str(mod) in surface.read_hint and "read_file" in surface.read_hint
    write(home / "go/pkg/mod/github.com/!c!o!r!p", "!widget@v1.0.0/widget.go", "package widget\nfunc New() int { return 0 }\n")
    assert depsurface.gather("go", "github.com/CORP/Widget", "v1.0.0") is not None   # uppercase is escaped the way go does
    write(home / ".cargo/registry/src/index.crates.io-x/toml-0.8.23/src", "lib.rs",
          "pub struct Value;\nimpl Value {\n    pub fn from_str(s: &str) -> Value { todo!() }\n    fn private_helper() {}\n}\n")
    rust = depsurface.gather("rust", "toml", "0.8.23")
    assert not rust.complete and any("pub fn from_str" in l for l in rust.lines)
    assert not any("private_helper" in l or "parse_str" in l for l in rust.lines)
    write(home / "ws/vendor/bundle/gems/countries-3.1.0/lib", "countries.rb", "class Country\n  def in_eu?\n  end\nend\n")
    assert any("in_eu?" in l for l in depsurface.gather("ruby", "countries", "3.1.0", workspace_root=str(home / "ws")).lines)

def test_go_doc_selection_keeps_grouped_consts_and_struct_fields_and_demands_a_balanced_parse():
    """A column-0-only filter dropped Second..Dow and Entry's fields while the note still claimed completeness."""
    lines, well_formed = depsurface._select_go_doc_blocks(GO_DOC)
    assert well_formed and "const (" in lines and "type Entry struct {" in lines
    joined = "\n".join(lines)
    assert all(m in joined for m in ("Second", "Minute", "Dow", "ID   int", "Next int64", "func New() *Entry"))
    assert "stand-in" not in joined and "Predefined" not in joined
    assert depsurface._select_go_doc_blocks("const (\n\tSecond = 1\n")[1] is False

@pytest.mark.parametrize("args", [("go", "../secret", "v1.0.0"), ("go", "..%2F..%2Fsecret", "v1.0.0"), ("rust", "../../etc", "1.0.0"),
                                  ("rust", "toml", "../../etc"), ("ruby", "../../etc", "1.0.0"), ("jvm", "../../etc:passwd", "1.0.0"),
                                  ("jvm", "org.apache.commons:../../../etc", "1.10.0")])
def test_a_manifest_coordinate_cannot_escape_its_cache_root(home, args):
    """Manifest coordinates are untrusted data; a file that would satisfy the escaped path genuinely exists."""
    write(home / "go/pkg", "secret.go", "package s\nfunc Leak() {}\n")
    assert depsurface.gather(*args) is None
    root = home / "cacheroot"
    (root / "a/b").mkdir(parents=True)
    (home / "outside").mkdir()
    os.symlink(home / "outside", root / "link")
    assert depsurface._safe_child(str(root), "link") is None and depsurface._safe_child(str(root), "link", "..", "outside") is None
    assert depsurface._safe_child(str(root), "a", "b") == os.path.realpath(root / "a/b")
    assert depsurface.gather("jvm", "org.apache.commons:" + str(home / "secret"), "1.10.0") is None   # absolute artifact resets os.path.join

def test_only_direct_dependencies_are_declared(tmp_path):
    """A lockfile lists the whole transitive graph; indirect / dependencyManagement / property versions are not claimed."""
    write(tmp_path, "go.mod", "module x\nrequire github.com/a/direct v1.4.0\nrequire github.com/t/thing v0.0.1 // indirect\n"
                              "require (\n\tgithub.com/b/direct v2.0.0\n\tgithub.com/b/indirect v0.0.2 // indirect\n)\n")
    write(tmp_path, "Cargo.toml", '[dependencies]\ntoml = "0.8"\n[dependencies.serde_json]\nversion = "1"\n')
    write(tmp_path, "Gemfile.lock", "GEM\n  specs:\n    countries (3.1.0)\n      i18n_data (~> 0.13.0)\n    i18n_data (0.13.1)\n\n"
                                    "PLATFORMS\n  ruby\n\nDEPENDENCIES\n  countries\n")
    pom = ("<project><dependencyManagement><dependencies><dependency><groupId>com.example</groupId><artifactId>pinned</artifactId>"
           "<version>9.9.9</version></dependency></dependencies></dependencyManagement><dependencies><dependency>"
           "<groupId>org.apache.commons</groupId><artifactId>commons-csv</artifactId><version>1.10.0</version></dependency>"
           "<dependency><groupId>g</groupId><artifactId>a</artifactId><version>${a.version}</version></dependency></dependencies></project>")
    write(tmp_path, "pom.xml", pom)
    assert depsurface.declared_coordinates(str(tmp_path)) == [("go", "github.com/a/direct", "v1.4.0"), ("go", "github.com/b/direct", "v2.0.0"),
                                                              ("ruby", "countries", "3.1.0"), ("jvm", "org.apache.commons:commons-csv", "1.10.0")]
    write(tmp_path, "Cargo.lock", '[[package]]\nname = "toml"\nversion = "0.8.23"\n\n[[package]]\nname = "serde"\nversion = "1.0.1"\n')
    assert ("rust", "toml", "0.8.23") in depsurface.declared_coordinates(str(tmp_path))   # needs Cargo.toml AND the lock...
    (tmp_path / "Cargo.toml").unlink()
    assert not [c for c in depsurface.declared_coordinates(str(tmp_path)) if c[0] == "rust"]   # ...never the lock alone
    assert depsurface.declared_coordinates("") == depsurface.declared_coordinates(None) == []

REAL_OUTPUT = {
    "ruby": ("cannot load such file -- countries (LoadError)", "countries"),
    "python": ("ModuleNotFoundError: No module named 'requests'", "requests"),
    "node": ("Error: Cannot find module 'commander'", "commander"),
    "rust": ("error[E0463]: can't find crate for `toml`", "toml"),
    "go": ("cart.go:5:2: no required module provides package github.com/arithmetic/decimal; to add it:\n\tgo get x", "github.com/arithmetic/decimal"),
    "java": ("Could not resolve dependencies for project x: org.apache.commons:commons-csv:jar:1.10.0", "org.apache.commons:commons-csv:jar:1.10.0"),
}

def rep(root, message, findings=True):
    c = proberun.probediscovery.ProbeCandidate(
        kind=proberun.probediscovery.ProbeKind.Test, command=["rake", "test"], working_dir=root, confidence=1, expected_value=1,
        cost=proberun.probediscovery.ProbeCost.Cheap, mutates_code=False, may_hang=False, may_need_services=False, reason="t")
    f = [probeparse.Finding(file="lib/rates.rb", line=1, message=message)] if findings else []
    return proberun.ProbeReport(project_type=["x"], selected=[c], results=[proberun.ProbeResult("rake test", 1, message, f)])

def test_each_ecosystems_missing_dependency_is_classified_named_and_noted():
    """A 'your dependency is not loadable' reads as 'your code is wrong' to a weak model; the name stops where the sentence does."""
    for eco, (line, name) in REAL_OUTPUT.items():
        assert probeparse.dependency_missing(line) == (eco, name), eco
        note = proberun.dependency_note(rep("", f"exited 1: {line}", False))
        assert name in note and "not the code that uses it" in note and "the fix is the name" in note, eco
        assert "cria" not in note.lower()
    for quiet in ("exited 1: cart.go:12:2: undefined: foo", "test_rates.rb:15: Expected: 0.0 Actual: 7.24"):
        assert proberun.dependency_note(rep("", quiet, False)) == ""
    assert probeparse.dependency_missing("Importer.java:[3,26] package org.apache.commons.csv does not exist") is None   # may be a typo

def test_the_note_asks_the_disk_before_describing_an_install(tmp_path):
    """cell 19 shipping-rates-rb: 'installed with --install-dir' described an install that never happened (every install was refused)."""
    miss = "cannot load such file -- unaccent (LoadError)"
    def gate(files, dirs=()):
        root = tmp_path / f"p{len(list(tmp_path.iterdir()))}"
        root.mkdir()
        [write(root, f, "x\n") for f in files]
        [(root / d).mkdir(parents=True) for d in dirs]
        return proberun.completion_block_nudge(rep(str(root), miss)) or ""
    assert "not installed anywhere" in gate(["Gemfile"]) and "--install-dir" not in gate(["Gemfile"])
    # `mkdir -p vendor/bundle/gems/x` writes no files: an empty tree is not an install
    assert "not installed anywhere" in gate(["Gemfile"], dirs=["vendor/bundle/gems/eu_countries"])
    bundler = gate(["Gemfile", "Gemfile.lock"])
    assert "only on the load path under bundler" in bundler and "GEM_HOME" not in bundler
    assert "installed with --install-dir" in gate(["Gemfile", "vendor/bundle/gems/countries-1.0/lib/countries.rb"])
    line = lambda eco, root: prompts.fill(proberun.dependency_line(eco, str(root)), name="axios")
    for eco, files, said in (("node", ["package.json"], "no node_modules/"), ("node", ["node_modules/axios/index.js"], "own node_modules"),
                             ("python", ["app.py"], "no virtualenv or site-packages"),
                             ("python", [".venv/lib/python3.12/site-packages/requests/__init__.py"], "cannot be imported")):
        d = tmp_path / f"{eco}{len(files[0])}"
        [write(d, f, "x\n") for f in files]
        assert said in line(eco, d), (eco, files)
    # no workspace, or one cria cannot read, keeps the general line that names no install mechanism
    assert line("ruby", "") == line("ruby", "/nonexistent-xyz") and "only sees gems on ruby's load path" in line("ruby", "")

def test_a_require_that_resolves_to_the_projects_own_file_is_named_not_called_a_missing_gem(tmp_path):
    """shipping-rates-rb 1787465385: lib/europe.rb shadowed the gem; three voices said 'not installed' and cost eight installs."""
    write(tmp_path, "lib/europe.rb", "require 'europe/version'\n")
    note = proberun.dependency_note(rep(str(tmp_path), "exited 1: cannot load such file -- europe/version (LoadError)", False), str(tmp_path))
    assert "lib/europe.rb" in note and "resolves to" in note and "the fix is the file, not the install" in note
    assert "resolves to" not in proberun.dependency_note(rep(str(tmp_path), "exited 1: cannot load such file -- nowhere_at_all (LoadError)", False), str(tmp_path))
    assert probeparse.resolves_to_workspace_file("europe", "") == ""
    # a gem's own bin stub inside the install tree is the install, not a shadow; a real lib/ file still is
    write(tmp_path, "vendor/cache/bin/minitest", "#!/usr/bin/env ruby\n")
    assert probeparse.resolves_to_workspace_file("minitest/autorun", str(tmp_path)) == ""
    write(tmp_path, "lib/minitest.rb", "module Minitest\nend\n")
    assert probeparse.resolves_to_workspace_file("minitest", str(tmp_path)) == os.path.join("lib", "minitest.rb")
    write(tmp_path, "shipping/__init__.py", "")
    assert proberun.dependency_note(rep(str(tmp_path), "exited 1: ModuleNotFoundError: No module named 'shipping'", False), str(tmp_path)) == ""
