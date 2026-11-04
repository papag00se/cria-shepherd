"""Package quality as an L5 returned-history assist: the L5 Ruby incident replayed with fake sources and a fake reasoner."""
import json

import pytest

from cria import dependencyexistence as de, packagequality as pq, registries, returnedpolicies as rp, wsview
from cria.toolcontracts import ReturnedHistory

TASK = "Do not hardcode EU membership. Add a third-party Ruby gem that determines whether a country is in the EU, add it to the project dependencies, and use it for the lookup."
VERSIONS = {"country": [("0.0.1", "2010-12-07T20:04:38Z")],
            "countries": [(f"{i // 10}.{i % 10}.0", f"{2008 + i // 8}-01-02T10:14:36Z") for i in range(103)],
            "country_select": [("8.0.3", "2024-05-01T00:00:00Z"), ("1.0.0", "2012-01-01T00:00:00Z")]}
GEMS = {"country": {"downloads": 6150, "version": "0.0.1", "version_created_at": "2010-12-07T20:04:38.845Z",
                    "info": "This rubygem does not have a description or summary.", "source_code_uri": "https://github.com/spider-network/country"},
        "countries": {"downloads": 135458753, "version": "8.1.0", "version_created_at": "2026-01-02T10:14:36.119Z",
                      "info": "All sorts of useful information about every country packaged as pretty little country objects.", "source_code_uri": "https://github.com/countries/countries"},
        "country_select": {"downloads": 90000000, "version": "8.0.3", "version_created_at": "2024-05-01T00:00:00Z", "info": "Country select helper"}}


def sources(url, data=None):
    sources.calls.append(url)
    for name, versions in VERSIONS.items():
        if url == f"https://rubygems.org/api/v1/versions/{name}.json":
            return 200, json.dumps([{"number": n, "created_at": at} for n, at in versions])
        if url == f"https://rubygems.org/api/v1/gems/{name}.json":
            return 200, json.dumps(GEMS[name])
    if url.startswith("https://rubygems.org/api/v1/search.json"):
        return 200, json.dumps([{"name": "country_select"}])
    if url == "https://api.osv.dev/v1/query":
        return 200, "{}"
    return 404, ""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    sources.calls = []
    de._CHECKED.clear(); de.NOTES.clear(); pq._CHECKED.clear(); pq._POOR.clear(); pq.NOTES.clear()
    monkeypatch.setattr(de._Budget, "fetch", lambda self, url, data=None: sources(url, data))
    monkeypatch.setattr(registries.shutil, "which", lambda name: None)
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


def history(ws, command, output, ask, session="s", tail=()):
    msgs = [{"role": "user", "content": TASK},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
            {"role": "tool", "tool_call_id": "c1", "content": output}, *tail]
    return msgs, ReturnedHistory(msgs, {"c1": command}, str(ws), session, True, None, 8192, ask)


def test_a_one_release_placeholder_gem_is_compared_with_the_real_one_and_its_load_failure_stops_being_coached(tmp_path):
    questions = []
    def ask(question):
        questions.append(question)
        return '{"reasonable": false, "better": "countries", "reason": "country is an empty 2010 placeholder; countries is the maintained gem"}'
    msgs, source = history(tmp_path, "cd app && timeout 60 gem install country 2>&1 | tail -20", "Successfully installed country-0.0.1", ask)
    rp._note_package_quality(source)
    note = msgs[-1]["content"]
    assert "`country`: 6,150 downloads in total; 1 release: latest 0.0.1 (2010-12-07), first release 2010-12-07" in note
    assert "`countries`: 135,458,753 downloads in total; 103 releases: latest 8.1.0 (2026-01-02)" in note
    assert "judged `country` a poor fit (country is an empty 2010 placeholder; countries is the maintained gem) and named `countries`" in note
    assert len(questions) == 1 and TASK in questions[0] and "6,150 downloads" in questions[0] and "135,458,753 downloads" in questions[0]
    rp._note_package_quality(history(tmp_path, "x", "x", ask)[1])    # a package is judged once per session
    assert len(questions) == 1
    # the same gem fails to load: the load-path coaching is deferred to the fact above
    load = {"role": "tool", "tool_call_id": "c2", "content": "cannot load such file -- country (LoadError)"}
    msgs2, later = history(tmp_path, "gem install country", "ok", ask, tail=[
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": "ruby -Ilib t.rb"})}}]}, load])
    rp._note_missing_dependency(later)
    assert msgs2[-1]["content"] == "cannot load such file -- country (LoadError)"
    other = {**load, "content": "cannot load such file -- other_gem (LoadError)"}
    msgs3, unrelated = history(tmp_path, "gem install country", "ok", ask, tail=[msgs2[-2], other])
    rp._note_missing_dependency(unrelated)
    assert "Note: `other_gem`" in msgs3[-1]["content"]      # a different, unjudged gem is still coached as before


@pytest.mark.parametrize("answer, expect_note", [
    ('{"reasonable": true, "better": "", "reason": "fits"}', False),
    ("I think it is fine", False),                        # unparseable = no note
    (None, False),                                        # no reasoner = no note
    ('{"reasonable": false, "better": "not_in_the_list", "reason": "meh"}', True),   # a pick outside the list is dropped, the finding stays
])
def test_the_reviewer_is_the_only_voice_and_every_failure_to_answer_is_silence(tmp_path, answer, expect_note):
    msgs, source = history(tmp_path, "gem install country", "ok", None if answer is None else (lambda q: answer))
    rp._note_package_quality(source)
    assert ("poor fit" in msgs[-1]["content"]) is expect_note
    assert ("named `" in msgs[-1]["content"]) is False
    assert pq.judged_poor("s", "rubygems", "country") is expect_note


def test_a_hard_red_flag_is_stated_as_a_fact_without_a_reasoner(tmp_path):
    def flagged(url, data=None):
        if url == "https://registry.npmjs.org/old-lib":
            return 200, json.dumps({"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": {"deprecated": "use new-lib"}},
                                    "time": {"created": "2014-01-01T00:00:00Z", "1.0.0": "2014-01-01T00:00:00Z"}})
        if url == "https://api.osv.dev/v1/query":
            return 200, json.dumps({"vulns": [{"id": "GHSA-aaaa"}, {"id": "GHSA-bbbb", "withdrawn": "2020-01-01"}]})
        return 404, ""
    note, poor = pq.assess("npm", "old-lib", None, TASK, None, flagged, lambda argv: "")
    assert poor and "`old-lib` 1.0.0 is marked deprecated by its registry (use new-lib)." in note
    assert "1 known security advisories: GHSA-aaaa" in note and "GHSA-bbbb" not in note


@pytest.mark.parametrize("command, expected", [
    ("cd app && timeout 60 gem install --install-dir vendor/gems country 2>&1 | tail -20", [("rubygems", "country", None)]),
    ("gem install countries -v 8.1.0", [("rubygems", "countries", "8.1.0")]),
    ("pip install -r requirements.txt requests==2.31.0 ./local 'flask[async]>=2'", [("pypi", "requests", "2.31.0"), ("pypi", "flask", None)]),
    ("python3 -m pip install httpx && uv add rich", [("pypi", "httpx", None), ("pypi", "rich", None)]),
    ("npm i -g left-pad@1.3.0 @scope/pkg github:user/repo", [("npm", "left-pad", "1.3.0"), ("npm", "@scope/pkg", None)]),
    ("cargo add serde --features derive", [("crates", "serde", None)]),
    ("go get github.com/shopspring/decimal@v1.4.0 ./...", [("go", "github.com/shopspring/decimal", "v1.4.0")]),
    ("dotnet add app.csproj package Newtonsoft.Json --version 13.0.3", [("nuget", "Newtonsoft.Json", "13.0.3")]),
    ("composer require monolog/monolog:3.5.0", [("packagist", "monolog/monolog", "3.5.0")]),
    ("vcpkg install fmt:x64-linux", [("vcpkg", "fmt", None)]),
    ("conan install --requires=fmt/10.2.1@", [("conan", "fmt", "10.2.1")]),
    ("bundle install && echo gem install nothing", []),
])
def test_direct_installs_name_the_packages_the_coder_committed_to(command, expected):
    assert pq.install_coordinates(command) == expected
