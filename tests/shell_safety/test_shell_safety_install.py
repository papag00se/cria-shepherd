"""An install refusal remedies in the ecosystem's own terms, naming only binaries this box can type (shipping-rates-rb /
ternary-bonsai: the ruby route said `bundle` when only `bundle3.2` existed; a refusal both said 'You do not need to
install it' and 'Install it into the project instead')."""
import json

import pytest

from cria import dirguard, wsview, writeproxy

BOX = {"bundle": "bundle3.2", "gem": "gem", "ruby": "ruby", "npm": "npm", "python3": "python3", "cargo": "cargo",
       "go": "go", "composer": "composer", "mvn": "mvn"}


@pytest.fixture
def box(monkeypatch):
    """The coder's PATH is the only boundary: `toolpath.resolved` answers with what the shell would type."""
    return lambda present: monkeypatch.setattr(dirguard.toolpath, "resolved", lambda name: present.get(name, ""))


def test_each_manager_is_answered_in_its_own_ecosystems_destination_with_the_binary_that_exists(box):
    """pip -> .venv, npm -> node_modules, cargo -> Cargo.toml, go -> go.mod, composer -> vendor/, mvn -> pom.xml,
    gem -> the DISCOVERED `bundle3.2`; no unfilled token; the system managers get no invented route."""
    box(BOX)
    wanted = {"pip install requests": ".venv", "npm install -g eslint": "node_modules", "cargo install ripgrep": "Cargo.toml",
              "go install example.com/x@v1": "go.mod", "composer global require x": "`vendor/`", "mvn install": "pom.xml",
              "gem install countries": "`bundle3.2 install`"}
    for command, marker in wanted.items():
        advice = dirguard._local_install_advice(command)
        assert marker in advice and "{{" not in advice and (".venv" in advice) == command.startswith("pip"), command
    assert dirguard._local_install_advice("apt install x") == dirguard._local_install_advice("brew install x") == ""


def test_the_route_falls_to_what_the_box_can_run_and_to_silence_when_nothing_can(box):
    box({"gem": "gem3.2"})
    assert "gem3.2 install --install-dir vendor/bundle" in dirguard._local_install_advice("gem install countries")
    assert "already installed" not in dirguard._local_install_advice("gem install --local gems/europe-0.0.28.gem")   # a path, not a package
    box({})
    refusal = dirguard.install_refusal("gem install countries", "none", "/w")
    assert refusal and "not permitted" in refusal and "bundle" not in refusal and "not established" not in refusal
    box({"gem": None, "bundle": None})      # nobody has asked yet is not "there is no way": it must not read as impossible
    assert "not established yet" in dirguard.install_refusal("gem install countries", "none", "/w")
    assert dirguard.install_refusal("pip install x", "write", "/w") is None and dirguard.kill_refusal("pkill -f x", "write") is None


def test_installing_the_routes_own_tool_says_only_that_it_exists_and_never_also_routes_a_dependency(box):
    box(BOX)
    said = dirguard._local_install_advice("which bundler; gem install bundler 2>&1 | tail -5")
    assert "already installed" in said and "`bundle3.2`" in said and "Gemfile" not in said and "into the project instead" not in said
    assert "Gemfile" in dirguard._local_install_advice("gem install countries")


@pytest.mark.parametrize("command", ["mvn install", "mvn -q install", "mvn install:install-file -Dfile=x.jar"])
def test_a_maven_goal_that_publishes_into_the_shared_repository_is_refused_but_a_build_is_not(command, box):
    """0ea27f58: `mvn install` publishes this cell's artifact into the shared ~/.m2 for a later cell to resolve (cross-cell contamination)."""
    box(BOX)
    assert dirguard.install_refusal(command, "none", "/w")
    assert dirguard.install_refusal("mvn -q test", "none", "/w") is None


# THE CODER'S OWN SUCCESSFUL RUN IS GROUND TRUTH THAT THE TOOL EXISTS (shipping-rates-rb: `gem list` succeeded, then the first `gem install X`
# was refused as "not established yet" because the survey that answers for programs rides only on a write; c1 calls 9-10, c4 14-16).
def _ran(command, code):
    envelope = f"Chunk ID: a1\nWall time: 0.1 seconds\nProcess exited with code {code}\nOriginal token count: 0\nOutput:\n"
    return [{"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": command})}}]},
            {"role": "tool", "tool_call_id": "c1", "content": envelope + "countries (8.1.0)\n"}]


@pytest.mark.parametrize("command,programs", [
    ("gem list", ["gem"]),
    ("cd app && FOO=1 bundle exec rake test", ["cd", "bundle"]),
    ("gem list | grep countries", []),                   # the exit status is grep's
    ("gem list; echo done", []),                         # ... and echo's
    ("false || gem list", []),                           # it may not have been reached
    ("command -v gem && echo yes", ["echo"]),            # a lookup runs nothing
    ("echo gem", ["echo"]),                              # a name in an argument is prose
    ("./bin/gem list", []),                              # some other program, by path
])
def test_a_programs_a_successful_run_proves_are_the_command_words_of_an_unconditional_chain(command, programs):
    assert dirguard.programs_that_ran(command) == programs


def test_a_gem_the_coder_ran_names_the_direct_route_at_the_first_install_refusal():
    refused = lambda: dirguard.install_refusal("gem install countries", "none", "/w")
    for history, named in ((_ran("gem list", 0), True), (_ran("gem list", 127), False), (_ran("gem list | head", 0), False), ([], False)):
        token = wsview.bind(wsview.View("/w", "install-proof"))
        try:
            writeproxy.represent_inbound(history, workspace_root="/w")
            said = refused()
        finally:
            wsview.unbind(token)
        assert ("install --install-dir vendor/bundle" in said) is named and ("not established yet" in said) is not named, history
