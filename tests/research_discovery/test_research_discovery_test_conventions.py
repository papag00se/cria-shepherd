"""What cria says about test files is an observation about default discovery, never 'will not run'."""

import pytest

from cria import probediscovery as pd, proberun
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")
PY_TEST = "import unittest\nclass T(unittest.TestCase):\n    def test_it(self):\n        pass\n"
RUST_TEST = "#[cfg(test)]\nmod t {\n #[test]\n fn x(){}\n}\n"
NODE = {"package.json": '{"name":"x"}'}

# files -> (undiscoverable_tests mentions, stranded_test_sentences mentions, tests_with_no_command mentions)
LAYOUTS = {
    "py no tests": ({"resolve.py": "x=1\n"}, ["No pytest tests were found", "test_*.py or *_test.py"], None, None),
    "go no tests": ({"main.go": "package main\n", "go.mod": "module x\n"}, ["No go test tests", "*_test.go"], None, None),
    "rust no tests": ({"src/main.rs": "fn main(){}\n"}, ["No cargo test tests", "#[test]"], None, None),
    "rust inline tests": ({"src/lib.rs": RUST_TEST}, [], [], ["Test files for cargo test are present"]),
    # g20: real test code existed but default discovery would not select resolve_handle.py
    "py misnamed": ({"resolve_handle.py": PY_TEST}, ["Apparent test code in resolve_handle.py", "explicit-file invocation or a configured runner"],
                    ["outside default automatic discovery conventions for pytest"], None),
    "java misnamed": ({"Helper.java": "class H {\n @Test\n void a(){}\n}\n"}, ["Helper.java", "*Test.java or *Tests.java"], ["@Test"], None),
    "java named": ({"FooTest.java": "class H {\n @Test\n void a(){}\n}\n"}, [], [], ["mvn test"]),
    # cycle 4 handles-cli-node x gemma4: test_lookup.js is a plain assert script with no `describe` — the NAME is the evidence
    "node scripted test": ({**NODE, "lookup.js": "1", "test_lookup.js": "const {execSync}=require('child_process');\nrunTest('goose');\n"},
                           ["test_lookup.js"], ["outside default automatic discovery conventions for jest/vitest", "__tests__/"], None),
    "node no tests": ({**NODE, "lookup.js": "1"}, ["No jest/vitest tests were found"], [], None),
    "node tests, no runner": ({**NODE, "lookup.test.js": "describe('x',()=>{});\n"}, [], [], ["Test files for jest/vitest are present", "nothing here has run them"]),
    # ruby is one language with two frameworks: minitest (test/test_*.rb) drew 'No rspec tests were found' 49 times over a green suite
    "ruby minitest": ({"lib/rates.rb": "module S\nend\n", "test/test_rates.rb": 'require "minitest/autorun"\nclass T < Minitest::Test\n  def test_a\n  end\nend\n'}, [], [], ["Test files for"]),
    "ruby no tests": ({"lib.rb": "module X\nend\n"}, ["minitest", "rspec"], None, None),
    "py misnamed, runner configured": ({"resolve_handle.py": PY_TEST, "pytest.ini": "\n"}, [], [], None),
    "py runner configured": ({"resolve.py": "x\n", "pytest.ini": "\n"}, [], [], None),
    "vendored tree": ({"resolve.py": "x\n", ".venv/lib/python3.12/site-packages/_pytest/test_main.py": "def test_x(): pass\n"},
                      ["No pytest tests were found"], [], None),
    # names that merely contain `test`/`spec` are production code
    "protest.rb": ({"protest.rb": "x"}, None, [], None),
}

@pytest.mark.parametrize("name", sorted(LAYOUTS))
def test_layout_gets_the_right_observation(tmp_path, name):
    files, undiscoverable, stranded, no_command = LAYOUTS[name]
    for rel, body in files.items():
        write(tmp_path, rel, body)
    for said, got in ((undiscoverable, pd.undiscoverable_tests(tmp_path)), (stranded, pd.stranded_test_sentences(tmp_path)),
                      (no_command, pd.tests_with_no_command(tmp_path))):
        text = " ".join(got)
        if said is None:
            continue
        assert bool(said) == bool(got), (name, got)
        assert all(s in text for s in said), (name, text)
        assert "will not run" not in text   # a default-convention mismatch is not an execution prohibition

@pytest.mark.parametrize("src,cfg", [("resolve.py", "pytest.ini"), ("index.js", "jest.config.js"), ("a.php", "phpunit.xml"), ("a.rb", ".rspec")])
def test_a_runner_config_silences_the_default_convention_claim(tmp_path, src, cfg):
    """phpunit.xml / jest.config / pytest.ini re-point discovery, so the default-convention sentence would be false."""
    write(tmp_path, src, "x\n")
    assert pd.undiscoverable_tests(tmp_path)
    write(tmp_path, cfg, "\n")
    assert pd.undiscoverable_tests(tmp_path) == []

@pytest.mark.parametrize("ext,body,holds", [
    # three languages wrote tests the ordinary way and cria said they had none
    ("php", r"class T extends \PHPUnit\Framework\TestCase {}", True), ("php", "  #[Test]\n  public function itAdds() {}", True),
    ("php", "class Resolver {\n  public function run() {}\n}", False),
    ("java", "  @ParameterizedTest\n  void adds() {}", True), ("java", "  @RepeatedTest(3)\n  void adds() {}", True),
    ("java", "  void helper() {}\n  int total;", False),
    ("js", "import test from 'node:test'\ntest('a', () => {})", True), ("js", "export function resolve(h) { return h; }", False),
])
def test_a_languages_ordinary_test_spelling_is_recognised(tmp_path, ext, body, holds):
    """A marker that misses a language's normal spelling makes cria claim 'no tests' over a file full of them."""
    import re
    marker = next(c for c in pd.TEST_CONVENTIONS if ext in c.exts).marker
    assert bool(re.search(marker, body, re.M)) is holds

def test_a_bare_dir_gets_a_test_floor_but_a_declared_runner_or_no_tests_gets_none(tmp_path):
    """Python and Ruby need no manifest, so a root test file alone must produce a probe (the six-language battery found zero tests run)."""
    write(tmp_path / "py", "app.py", "x = 1\n")
    write(tmp_path / "py", "test_app.py", "def test_x():\n    assert True\n")
    write(tmp_path / "rb", "rates.rb", "module R; end\n")
    write(tmp_path / "rb", "test/test_rates.rb", 'require "minitest/autorun"\n')
    write(tmp_path / "rbcfg", "test/test_rates.rb", 'require "minitest/autorun"\n')
    write(tmp_path / "rbcfg", ".rspec", "--format doc\n")
    write(tmp_path / "none", "app.py", "x = 1\n")
    write(tmp_path / "rake", "Rakefile", 'Rake::TestTask.new(:test)\n')
    write(tmp_path / "rake", "lib.rb", "module X\nend\n")
    write(tmp_path / "rake2", "Rakefile", 'task :build do\nend\n')
    write(tmp_path / "rake2", "lib.rb", "module X\nend\n")
    kinds = lambda d: [c.kind for c in proberun.select_completion_probes(str(tmp_path / d)) if c.kind is pd.ProbeKind.Test]
    assert kinds("py") and kinds("rb") and not kinds("none")
    rake = lambda d: [c.command[:2] for c in proberun.select_completion_probes(str(tmp_path / d))]
    assert ["rake", "test"] in rake("rake") and ["rake", "test"] not in rake("rake2")   # a declared rake target is not an invention
    assert not [c for c in proberun.select_completion_probes(str(tmp_path / "rbcfg")) if "test/**/test_*.rb" in " ".join(c.command)]

