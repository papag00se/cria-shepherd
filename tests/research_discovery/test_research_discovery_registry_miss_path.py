"""A dependency the coder names that does not exist is answered with real candidates only: registry search, exact
lookups of separator/segment variants, vcpkg's port list, the installed tool's own query. PyPI and Go offer none."""
import json

import pytest

from cria import registries as R


def fetcher(replies):
    """URL -> (status, body); anything unlisted is a 404 (absent)."""
    def fetch(url):
        return replies.get(url, (404, ""))
    return fetch


def test_a_missing_gem_gets_real_names_from_search_variants_and_the_installed_tool():
    replies = {
        "https://rubygems.org/api/v1/versions/iso_country.json": (200, json.dumps([{"number": "1.0"}])),
        "https://rubygems.org/api/v1/search.json?query=iso-country": (200, json.dumps([{"name": "countries"}])),
    }
    ran = []
    def run(argv):
        ran.append(argv)
        return "country_select (9.0.0)\n"
    found = R.check("rubygems", "iso-country", fetch=fetcher(replies), run=run, which=lambda tool: tool == "gem")
    assert found.lookup.exists is False
    assert found.suggestions.candidates == ["iso_country", "countries", "country_select"]
    assert ran == [["gem", "search", "--remote", "iso-country"]]


def test_a_missing_version_carries_the_real_version_list():
    replies = {"https://proxy.golang.org/github.com/shopspring/decimal/@v/list": (200, "v1.3.0\nv1.4.0\n")}
    found = R.check("go", "github.com/shopspring/decimal", "v0.38.0", fetch=fetcher(replies), which=lambda t: None)
    assert found.version_ok is False and found.lookup.versions == ["v1.3.0", "v1.4.0"] and found.suggestions is None


@pytest.mark.parametrize("registry, name", [("pypi", "requsts"), ("go", "github.com/shopspring/dec")])
def test_registries_without_search_offer_no_invented_suggestion(registry, name):
    found = R.check(registry, name, fetch=fetcher({}), which=lambda t: None)
    assert found.lookup.exists is False and found.suggestions.candidates == [] and "no suggestion" in found.suggestions.note


def test_cpp_and_csharp_misses_use_the_vcpkg_port_list_conan_remote_and_nuget_search():
    baseline = json.dumps({"default": {"fmt": {}, "spdlog": {}, "fmtlog": {}}})
    replies = {R.VCPKG_BASELINE: (200, baseline),
               "https://center2.conan.io/v2/conans/search?q=fmtt*": (200, json.dumps({"results": []})),
               "https://azuresearch-usnc.nuget.org/query?q=Newtonsof&take=5": (200, json.dumps({"data": [{"id": "Newtonsoft.Json"}]}))}
    fetch = fetcher(replies)
    assert R.suggest("vcpkg", "fmtt", fetch=fetch, which=lambda t: None).candidates == ["fmt", "fmtlog"]
    assert R.suggest("conan", "fmtt", fetch=fetch, which=lambda t: None).candidates == []
    assert R.suggest("nuget", "Newtonsof", fetch=fetch, which=lambda t: None).candidates == ["Newtonsoft.Json"]
