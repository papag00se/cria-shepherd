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
    assert levels["dependency-existence-note"] == 5
