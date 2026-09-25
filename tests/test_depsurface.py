"""cria/depsurface.py — Candidate C40's ground-truth probe of a resolved dependency's real exported
surface. Hermetic: every fixture builds its own throwaway cache tree under a temp HOME/workspace: no
test here depends on a real ``~/go/pkg/mod``, ``~/.cargo``, or gem install existing on the box that
runs the suite. The offline replay against the REAL caches on this box lives under
``~/.cria/walk-findings/2026-09-24/c40-replay/`` (out of the unit-test tree by design: a replay proves
the box's real caches ground the real invented-API incident; a hermetic test proves the code is
correct without depending on that real state existing at all).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria import depsurface


class _HomeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self._real_expanduser = os.path.expanduser
        os.path.expanduser = lambda p: (self.home if p == "~" else
                                        os.path.join(self.home, p[2:]) if p.startswith("~/") else
                                        self._real_expanduser(p))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, os.path, "expanduser", self._real_expanduser)


class GoTests(_HomeCase):
    def _write_module(self, module="github.com/shopspring/decimal", version="v1.4.0", body=None):
        d = os.path.join(self.home, "go", "pkg", "mod", module + "@" + version)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "decimal.go"), "w") as fh:
            fh.write(body or "")
        return d

    def test_fails_before_no_cache_abstains(self):
        # No module dir written at all — the fails-before precondition for the whole module.
        self.assertIsNone(depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0"))

    def test_passes_after_real_exported_signatures_selected(self):
        self._write_module(body=(
            "package decimal\n\n"
            "type Decimal struct {\n\tvalue *big.Int\n}\n\n"
            "func NewFromString(value string) (Decimal, error) {\n\treturn Decimal{}, nil\n}\n\n"
            "func (d Decimal) Round(places int32) Decimal {\n\treturn d\n}\n\n"
            "func lowerCaseHelper() int {\n\treturn 0\n}\n"))
        surface = depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0")
        self.assertIsNotNone(surface)
        self.assertEqual(surface.ecosystem, "go")
        self.assertIn("func NewFromString(value string) (Decimal, error) {", surface.lines)
        self.assertIn("func (d Decimal) Round(places int32) Decimal {", surface.lines)
        self.assertIn("type Decimal struct {", surface.lines)
        # The invented member from the real incident must not appear — there is nothing to invent it
        # FROM; gather() only ever emits lines it read.
        self.assertFalse(any("Quantize" in ln for ln in surface.lines))
        self.assertFalse(any("lowerCaseHelper" in ln for ln in surface.lines))  # unexported, excluded

    def test_byte_exact_no_line_differs_from_the_real_file(self):
        real = ("package decimal\n\nfunc NewFromString(value string) (Decimal, error) {\n"
                "\treturn Decimal{}, nil\n}\n")
        self._write_module(body=real)
        surface = depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0")
        for line in surface.lines:
            self.assertIn(line, real.splitlines())

    def test_test_files_excluded(self):
        d = self._write_module(body="package decimal\nfunc NewFromString(v string) Decimal { return Decimal{} }\n")
        with open(os.path.join(d, "decimal_test.go"), "w") as fh:
            fh.write("package decimal\nfunc TestSomething() {}\n")
        surface = depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0")
        self.assertNotIn("decimal_test.go", surface.sources)

    def test_uppercase_module_segment_is_escaped(self):
        # Go's own module-cache escaping: an uppercase letter in the import path becomes `!` + lower.
        d = os.path.join(self.home, "go", "pkg", "mod", "github.com", "!c!o!r!p", "!widget@v1.0.0")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "widget.go"), "w") as fh:
            fh.write("package widget\nfunc New() int { return 0 }\n")
        surface = depsurface.gather("go", "github.com/CORP/Widget", "v1.0.0")
        self.assertIsNotNone(surface)


class RustTests(_HomeCase):
    def _write_crate(self, name="toml", version="0.8.23", body=None):
        d = os.path.join(self.home, ".cargo", "registry", "src", "index.crates.io-deadbeef",
                         f"{name}-{version}", "src")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "lib.rs"), "w") as fh:
            fh.write(body or "")
        return d

    def test_fails_before_no_registry_abstains(self):
        self.assertIsNone(depsurface.gather("rust", "toml", "0.8.23"))

    def test_passes_after_pub_items_selected_never_parse_str(self):
        self._write_crate(body=(
            "pub struct Value;\n\n"
            "impl Value {\n"
            "    pub fn from_str(s: &str) -> Result<Value, Error> {\n        todo!()\n    }\n"
            "    fn private_helper() {}\n"
            "}\n\n"
            "pub fn from_str(s: &str) -> Result<Value, Error> { todo!() }\n"))
        surface = depsurface.gather("rust", "toml", "0.8.23")
        self.assertIsNotNone(surface)
        self.assertTrue(any("pub fn from_str" in ln for ln in surface.lines))
        self.assertFalse(any("private_helper" in ln for ln in surface.lines))
        # The invented member the real incident wrote must be structurally absent from the source.
        self.assertFalse(any("parse_str" in ln for ln in surface.lines))


class RubyTests(_HomeCase):
    def test_fails_before_no_gem_abstains(self):
        self.assertIsNone(depsurface.gather("ruby", "countries", "3.1.0"))

    def test_passes_after_workspace_vendored_gem_selected(self):
        d = os.path.join(self.home, "ws", "vendor", "bundle", "gems", "countries-3.1.0", "lib")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "countries.rb"), "w") as fh:
            fh.write("module ISO3166\n  class Country\n    def in_eu?\n      true\n    end\n  end\nend\n")
        surface = depsurface.gather("ruby", "countries", "3.1.0",
                                    workspace_root=os.path.join(self.home, "ws"))
        self.assertIsNotNone(surface)
        self.assertTrue(any("in_eu?" in ln for ln in surface.lines))

    def test_home_gem_selected_when_no_workspace_copy(self):
        d = os.path.join(self.home, ".gem", "ruby", "3.2.0", "gems", "countries-3.1.0", "lib")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "countries.rb"), "w") as fh:
            fh.write("class Country\n  def in_eu?\n    true\n  end\nend\n")
        surface = depsurface.gather("ruby", "countries", "3.1.0")
        self.assertIsNotNone(surface)


class ScopeTests(_HomeCase):
    def test_jvm_is_explicitly_out_of_scope(self):
        # Even with a real jar-shaped tree present, jvm has no probe entry — documented scope-out,
        # not an accidental miss.
        d = os.path.join(self.home, ".m2", "repository", "org", "apache", "commons", "commons-csv",
                          "1.10.0")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "commons-csv-1.10.0.jar"), "w").close()
        self.assertIsNone(depsurface.gather("jvm", "org.apache.commons:commons-csv", "1.10.0"))

    def test_unknown_ecosystem_abstains(self):
        self.assertIsNone(depsurface.gather("cobol", "whatever", "1.0"))

    def test_missing_coordinate_fields_abstain(self):
        self.assertIsNone(depsurface.gather("go", "", "v1.0.0"))
        self.assertIsNone(depsurface.gather("go", "github.com/x/y", ""))


if __name__ == "__main__":
    unittest.main()
