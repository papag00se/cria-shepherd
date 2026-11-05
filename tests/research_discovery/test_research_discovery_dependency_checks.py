"""Undeclared dependencies are answered by each ecosystem's STANDARD tool (deptry, knip/depcheck, Bundler); absent tool = no check."""
import pytest

from cria import probediscovery as pd, probeparse, proberun, toolpath
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")


def programs(monkeypatch, *present):
    monkeypatch.setattr(toolpath, "resolved", lambda name: name if name in present else "")


def dep_checks(root):
    return [c for c in pd.dependency_floor_candidates(root) if c.kind is pd.ProbeKind.DependencyCheck]


def py_project(tmp_path):
    write(tmp_path, "pyproject.toml", '[project]\nname = "x"\ndependencies = []\n')
    write(tmp_path, "src/app.py", "import requests\n")


def test_python_runs_deptry_when_installed_or_launchable_and_never_otherwise(tmp_path, monkeypatch):
    py_project(tmp_path)
    programs(monkeypatch, "deptry")
    [c] = dep_checks(tmp_path)
    assert c.command == ["deptry", "."] and c.tier() == 1 and c.is_safe() and c.composed_by_cria is False
    programs(monkeypatch, "uvx")
    assert dep_checks(tmp_path)[0].command == ["uvx", "deptry", "."]
    programs(monkeypatch, "pipx")
    assert dep_checks(tmp_path)[0].command == ["pipx", "run", "deptry", "."]
    programs(monkeypatch)                              # no deptry, no uvx, no pipx: no check at all
    assert dep_checks(tmp_path) == []
    programs(monkeypatch, "deptry")
    (tmp_path / "pyproject.toml").unlink()             # nothing declares dependencies: nothing for deptry to read
    assert dep_checks(tmp_path) == []


def test_the_gate_selects_the_dependency_check_and_shows_deptrys_own_lines(tmp_path, monkeypatch):
    py_project(tmp_path)
    programs(monkeypatch, "deptry")
    assert any(c.kind is pd.ProbeKind.DependencyCheck for c in proberun.select_completion_probes(str(tmp_path)))
    out = ("src/app.py:1:8: DEP001 'requests' imported but missing from the dependency definitions\n"
           "src/app.py:3:1: DEP003 'urllib3' imported but it is a transitive dependency\nFound 2 dependency issues.\n")
    result = probeparse.parse_output("deptry .", probeparse.family_of(["deptry", "."]), 1, out, "")
    assert [f.message for f in result.findings] == [
        "DEP001 'requests' imported but missing from the dependency definitions",
        "DEP003 'urllib3' imported but it is a transitive dependency"]


def test_ruby_with_a_gemfile_loads_the_tests_under_bundler_when_rake_is_outside_the_bundle(tmp_path, monkeypatch):
    programs(monkeypatch)
    write(tmp_path, "Gemfile", "source 'https://rubygems.org'\ngem 'minitest'\n")
    write(tmp_path, "Rakefile", "require 'rake/testtask'\nRake::TestTask.new do |t|\nend\n")
    write(tmp_path, "lib/rates.rb", "require 'countries'\n")
    [c] = dep_checks(tmp_path)
    assert c.command[:3] == ["bundle", "exec", "ruby"] and "test/**/test_*.rb" in c.command[-1]
    write(tmp_path, "Gemfile", "gem 'rake'\n")          # rake bundled: build_ruby already runs `bundle exec rake test`
    assert dep_checks(tmp_path) == []


def test_ruby_without_a_gemfile_states_the_one_fact_and_stdlib_and_own_files_are_not_gems(tmp_path):
    write(tmp_path, "lib/rates.rb", "require 'json'\nrequire 'net/http'\nrequire_relative 'x'\nrequire 'countries'\nrequire 'rates/core'\n")
    write(tmp_path, "lib/rates/core.rb", "require 'httparty/request'\n")
    [fact] = pd.undeclared_gem_sentences(tmp_path)
    assert fact == ("The Ruby code requires `countries`, `httparty`, which are not the project's own files or Ruby's standard "
                    "library, and the project has no Gemfile declaring any gem.")
    write(tmp_path, "Gemfile", "gem 'countries'\n")      # a Gemfile: Bundler's own restriction is the check
    assert pd.undeclared_gem_sentences(tmp_path) == []


def test_node_runs_knip_or_depcheck_only_when_the_project_or_the_path_has_one(tmp_path, monkeypatch):
    write(tmp_path, "package.json", '{"name":"x","dependencies":{}}')
    programs(monkeypatch)
    assert dep_checks(tmp_path) == []
    programs(monkeypatch, "depcheck")
    assert dep_checks(tmp_path)[0].command == ["depcheck"]
    write(tmp_path, "package.json", '{"name":"x","devDependencies":{"knip":"5.0.0"}}')
    assert dep_checks(tmp_path)[0].command == ["npm", "exec", "knip", "--dependencies"]
