"""The registry check as an L5 returned-history assist: facts about missing packages/versions, once, no network."""
import json

import pytest

from cria import dependencyexistence as de, registries, returnedpolicies as rp, wsview
from cria.toolcontracts import ReturnedHistory

PROXY = "https://proxy.golang.org/github.com/shopspring/decimal/@v/list"


def fake_fetch(url):
    fake_fetch.calls.append(url)
    if url == PROXY:
        return 200, "v1.0.0\nv1.5.0\nv1.6.0\n"
    if url.startswith("https://proxy.golang.org/"):
        return 404, ""
    if url == "https://rubygems.org/api/v1/versions/eu.json":
        return 404, ""
    if url.startswith("https://rubygems.org/api/v1/search.json"):
        return 200, json.dumps([{"name": "eu_central_bank"}, {"name": "eu_countries"}])
    return 404, ""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    fake_fetch.calls = []
    de._CHECKED.clear(); de.NOTES.clear()
    monkeypatch.setattr(de._Budget, "fetch", lambda self, url: fake_fetch(url))
    monkeypatch.setattr(de._Budget, "run", lambda self, argv: "")
    monkeypatch.setattr(registries.shutil, "which", lambda name: None)
    token = wsview.bind(wsview.DirectView())     # production fills the view from a harness survey; here, this disk
    yield
    wsview.unbind(token)


def request(ws, call_id, output="ok", session="s"):
    msgs = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": call_id, "content": output}]
    rp._note_dependency_existence(ReturnedHistory(msgs, {}, str(ws), session, True, None, 8192))
    return msgs[-1]["content"]


def test_a_missing_package_and_a_missing_version_are_stated_once_from_the_registry(tmp_path):
    (tmp_path / "go.mod").write_text("module app\nrequire github.com/shopspring/decimal v0.38.0\n")
    first = request(tmp_path, "c1")
    assert ("`github.com/shopspring/decimal` exists on the Go module proxy; published versions are v1.0.0, v1.5.0, v1.6.0 "
            "(v0.38.0 is not one of them).") in first
    n = len(fake_fetch.calls)
    again = request(tmp_path, "c1")                       # same transcript resent: replayed, never looked up twice
    assert again == first and len(fake_fetch.calls) == n
    # a failed install naming a gem that does not exist: the registry's own similar names, no advice
    out = request(tmp_path, "c2", "Could not find gem 'eu' in rubygems repository https://rubygems.org/")
    assert "No package named `eu` exists on RubyGems." in out and "eu_central_bank" in out
    # PyPI offers no names by design; an existing version and an unknown (network) lookup are silent
    assert "No package named `nopkg` exists on PyPI.\n" in request(tmp_path, "c3", "ERROR: No matching distribution found for nopkg") + "\n"
    assert request(tmp_path, "c4", "ERROR: No matching distribution found for nopkg").endswith("for nopkg")   # already checked: silent
    (tmp_path / "go.mod").write_text("module app\nrequire github.com/shopspring/decimal v1.5.0\n")
    assert request(tmp_path, "c5", "ok", session="s2") == "ok"        # exists at its declared version: silent


def test_the_assist_is_selected_only_at_level_5():
    from cria import assistruntime, toolstages
    levels = {d.policy.id: d.policy.default_level for d in toolstages.defaults().history}
    assert levels["dependency-facts"] == 5
    retired = {"dependency-existence-note", "package-quality-note", "dependency-api-evidence", "missing-dependency-note"}
    assert not retired & set(levels)          # the four overlapping assists are ONE registration


def test_an_invalid_version_string_is_stated_as_invalid_for_its_ecosystem(tmp_path):
    (tmp_path / "go.mod").write_text("module app\nrequire github.com/shopspring/decimal v0.4.00\n")
    out = request(tmp_path, "v1")
    assert "`v0.4.00` is not a valid version string for the Go module proxy (declared for `github.com/shopspring/decimal`): " \
           "a Go module version is vMAJOR.MINOR.PATCH, no leading zeros." in out
    assert "not one of them" not in out        # not a published-versions claim: the string is not a version at all
    assert de.invalid_version("go", "v1.6.0") == "" and de.invalid_version("go", "1.6.0")
    assert de.invalid_version("npm", "1.02.0") and de.invalid_version("npm", "1.3.0") == ""
    assert de.invalid_version("pypi", "2.31.0") == "" and de.invalid_version("pypi", "banana")
    assert de.invalid_version("rubygems", "13.2.1") == "" and de.invalid_version("maven", "whatever") == ""


def test_declared_dependency_files_beyond_lockfiles_are_read_with_only_exact_pins_as_version_claims(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "1.3.0", "lodash": "^4.17.0",
                                                                          "local": "file:../x", "gh": "user/repo"}}))
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\nflask>=2\n-e .\n# comment\n")
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["httpx[http2]==0.27.0 ; python_version>\'3.8\'"]\n')
    (tmp_path / "Cargo.toml").write_text('[dependencies]\ntoml = "0.8"\nserde = { version = "=1.0.200" }\nmine = { path = "../m" }\n')
    (tmp_path / "src" / "App").mkdir(parents=True)
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\ngem 'eu'\ngem 'rake', '13.2.1'\n")
    (tmp_path / "src" / "App" / "App.csproj").write_text('<Project><ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3" />'
                                         '</ItemGroup></Project>')
    (tmp_path / "vcpkg.json").write_text(json.dumps({"dependencies": ["fmt", {"name": "spdlog"}]}))
    (tmp_path / "conanfile.txt").write_text("[requires]\nzlib/1.3.1\n[generators]\nCMakeDeps\n")
    got = set(de.declared(str(tmp_path)))
    assert {("npm", "left-pad", "1.3.0"), ("npm", "lodash", None), ("pypi", "requests", "2.31.0"), ("pypi", "flask", None),
            ("pypi", "httpx", "0.27.0"), ("crates", "toml", None), ("crates", "serde", "1.0.200"),
            ("nuget", "Newtonsoft.Json", "13.0.3"), ("vcpkg", "fmt", None), ("vcpkg", "spdlog", None),
            ("conan", "zlib", "1.3.1"), ("rubygems", "eu", None), ("rubygems", "rake", "13.2.1")} <= got
    assert not {c for c in got if c[1] in ("local", "gh", "mine", "CMakeDeps")}


def test_a_declared_npm_package_that_does_not_exist_is_stated_from_the_registry(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"no-such-pkg-cria": "1.0.0"}}')
    out = request(tmp_path, "n1")
    assert "No package named `no-such-pkg-cria` exists on npm." in out
    assert "https://registry.npmjs.org/no-such-pkg-cria" in fake_fetch.calls


def test_one_assist_states_a_nonexistent_gem_and_never_coaches_loading_it(tmp_path):
    def facts(output, call_id):
        msgs = [{"role": "user", "content": "go"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": call_id, "content": output}]
        rp._note_dependency_facts(ReturnedHistory(msgs, {}, str(tmp_path), "s", True, None, 8192))
        return msgs[-1]["content"]
    assert "No package named `eu` exists on RubyGems." in facts("Could not find gem 'eu' in rubygems repository https://rubygems.org/", "c1")
    load = facts("cannot load such file -- eu (LoadError)", "c2")
    assert load == "cannot load such file -- eu (LoadError)"                 # the registry said it does not exist: no load-path coaching
    assert "Note: `other`" in facts("cannot load such file -- other (LoadError)", "c3")   # an unjudged name is coached as before
