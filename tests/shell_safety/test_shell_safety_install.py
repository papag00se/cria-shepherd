"""An install refusal remedies in the ecosystem's own terms, naming only binaries this box can type (shipping-rates-rb /
ternary-bonsai: the ruby route said `bundle` when only `bundle3.2` existed; a refusal both said 'You do not need to
install it' and 'Install it into the project instead')."""
import pytest

from cria import dirguard

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
