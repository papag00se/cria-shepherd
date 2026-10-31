"""Authored text is checked against the evidence cria composed (urlgrounding), and the live-execution evidence is read from the project's own files (execcheck).
Incidents: rubygems.org/gems/eu 404 (prefix of a real gem), api.handle.me/resolve (path only in OTHER hosts' urls), mock web_fetch leaking into a plan, cargo new one dir down."""
import pytest

from cria import execcheck, urlgrounding as ug
from gates_completion_helpers import gates_completion_view  # noqa: F401

EV = ("GET /handles/{handle} lists one. See https://api.handle.me/handles/{handle} and https://reimagined.github.io/resolve "
      "plus rubygems.org/gems/eu_countries ./path/to/resolveOpenApiReferences https://holders.io/holders/{addr}")


@pytest.mark.parametrize("url,host_ok,url_ok", [
    ("https://api.handle.me/anything", True, False), ("https://API.handle.me", True, False),
    ("https://rubygems.org/gems/eu", True, False),            # prefix of eu_countries: not grounded
    ("https://rubygems.org/gems/eu_countries/", True, True),   # trailing slash tolerated; matched without scheme
    ("https://other.example/x", False, False), ("", False, False), ("   ", False, False), ("http://[bad", False, False),
])
def test_host_grounding_is_weaker_than_exact_url_grounding(url, host_ok, url_ok):
    assert ug.host_is_grounded(url, EV) is host_ok and ug.url_is_grounded(url, EV) is url_ok
    assert ug.host_is_grounded(url, None) is False and ug.url_is_grounded(url, None) is False


def test_routes_and_urls_in_authored_text_are_grounded_by_the_evidence_not_by_novelty():
    assert ug.ungrounded_routes("send POST /handles/resolve now; GET /handles/{handle}; DELETE /; PUT /x/,", EV) == ["POST /handles/resolve", "PUT /x/"]
    assert ug.ungrounded_routes("", EV) == [] and ug.ungrounded_routes(None, None) == []
    text = ("fetch https://api.handle.me/resolve, https://api.handle.me/handles/{other_name}, https://api.handle.me/, "
            "https://nowhere.io/a, https://holders.io/holders/{address} and `https://api.handle.me/handles` and {\"u\": \"https://api.handle.me/handles\"}")
    assert ug.ungrounded_urls(text, EV) == ["https://api.handle.me/resolve", "https://nowhere.io/a"]
    assert ug.ungrounded_urls("see https://[bad/x and http://api.handle.me/handles/{h}", EV) == []


@pytest.mark.parametrize("text,tools,want", [
    ("Write tests that mock web_fetch; then import `web_fetch` and call web_fetch", ["web_fetch", "", "grep"], ["web_fetch"]),
    ("web_fetch the spec first, then grep it", ["web_fetch", "grep"], []),      # an instruction to the agent is fine
    ("patch the grep helper", ["web_fetch", "grep"], ["grep"]),
    ("mock web_fetch", [], []), ("mock web_fetch", None, []), ("  ", ["web_fetch"], []), (None, ["web_fetch"], []),
])
def test_a_coder_tool_used_as_a_library_of_the_deliverable_is_reported_once(text, tools, want):
    assert ug.harness_tool_leaks(text, tools) == want


@pytest.mark.parametrize("files,expected", [
    ({"pyproject.toml": "[project.scripts]\nx = 'a:b'\n", "lib.py": "x = 1\n"}, ["pyproject.toml"]),
    ({"Cargo.toml": "[[bin]]\nname='a'\n"}, ["Cargo.toml"]),
    ({"package.json": '{"scripts": {"start": "node a.js"}}', "run.mjs": "#!/usr/bin/env node\n"}, ["package.json", "run.mjs"]),
    ({"setup.py": "setup(entry_points={})", "Main.java": "public static void main(String[] a) {}", "x.php": "#!/usr/bin/php\n"}, ["Main.java", "setup.py", "x.php"]),
    ({"pyproject.toml": "[tool.x]\n", "noext": "if __name__ == '__main__':\n"}, []),
])
def test_entry_points_follow_each_languages_own_convention_and_manifests(tmp_path, files, expected):
    for rel, body in files.items():
        (tmp_path / rel).write_text(body)
    assert execcheck.entrypoints(str(tmp_path)) == expected


@pytest.mark.parametrize("pkg,want", [
    ('{"scripts": {"build": "x", "start": "node a", "test": "t"}}', ["npm run build", "npm run start", "npm run test", "npm start", "npm test"]),
    ('{"scripts": null}', []), ("[1]", []), ("{broken", []),
])
def test_declared_commands_come_from_the_manifests_scripts_and_tolerate_a_malformed_one(tmp_path, pkg, want):
    (tmp_path / "package.json").write_text(pkg)
    (tmp_path / "Gemfile").write_text("source 'x'\n")
    assert execcheck.manifest_commands(str(tmp_path)) == want + ["bundle exec"]


def test_readme_commands_are_only_launcher_lines_and_nothing_is_read_from_a_missing_or_empty_root(tmp_path):
    (tmp_path / "README.rst").write_text("# c\n$ python3 app.py goose\n> node x\n| bash a |\n\n./run.sh --fast\nsay hello\n   $   make test  \n")
    (tmp_path / "notes.md").write_text("python hidden.py\n")
    assert execcheck.readme_commands(str(tmp_path)) == ["python3 app.py goose", "./run.sh --fast", "make test"]
    empty = tmp_path / "e"
    empty.mkdir()
    for root in ("", str(empty), str(tmp_path / "gone")):
        assert execcheck.readme_commands(root) == [] == execcheck.manifest_commands(root) == execcheck.entrypoints(root)
