"""cria/depsurface.py — Candidate C40's ground-truth probe of a resolved dependency's real exported
surface, plus the 2026-09-25 manifest/lockfile parsing that replaced the textual-success trigger.
Hermetic: every fixture builds its own throwaway cache tree under a temp HOME/workspace: no test here
depends on a real ``~/go/pkg/mod``, ``~/.cargo``, or gem install existing on the box that runs the
suite (the JVM ``javap`` tests are the one exception, guarded by an explicit availability check, since
``javap`` is a real tool this module shells out to rather than a plain file read).

The offline replay against the REAL caches on this box lives under
``~/.cria/walk-findings/2026-09-24/c40-replay/``.
"""
import os
import shutil
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

    def test_read_hint_points_at_the_real_readable_directory(self):
        d = self._write_module(body="package decimal\nfunc NewFromString(v string) Decimal { return Decimal{} }\n")
        surface = depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0")
        self.assertIn(d, surface.read_hint)
        self.assertIn("read_file", surface.read_hint)


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


@unittest.skipUnless(shutil.which("javap"), "javap not on PATH on this machine")
class JvmTests(_HomeCase):
    """javap is a REAL tool this module shells out to (jars are compiled, not text) -- these tests
    build a REAL tiny jar with the stdlib `zipfile`/`javac`-free trick (a jar needs no javac here:
    javap only needs valid .class bytes, which the JDK itself ships for java.lang.* -- but simplest
    and most deterministic is to just copy a real, already-compiled class from the JDK's own runtime
    into a throwaway jar, so no compiler is required either)."""

    def _write_jar(self, group="org.apache.commons", artifact="commons-csv", version="1.10.0"):
        import zipfile
        d = os.path.join(self.home, ".m2", "repository", *group.split("."), artifact, version)
        os.makedirs(d, exist_ok=True)
        jar_path = os.path.join(d, f"{artifact}-{version}.jar")
        # A real, valid .class file: java.lang.Object's own, shipped in every JDK's runtime image.
        # Copied in under a throwaway package name -- javap decodes real bytecode either way.
        import subprocess
        extracted = subprocess.run(
            ["javap", "-classpath", os.environ.get("JAVA_HOME", "") or "/usr", "-public", "java.lang.String"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(extracted.returncode, 0, extracted.stderr)  # sanity: javap itself works here
        # Build a jar containing java.lang.String.class read straight from the JDK's own modules via
        # `javap`'s classpath resolution is not enough to EXTRACT bytes portably across JDK layouts
        # (JDK 9+ ships classes inside a `jrt:` image, not loose .class files) -- so instead this
        # jar carries a REAL, freshly compiled minimal class using the JDK's own `javac`, when present.
        javac = shutil.which("javac")
        if not javac:
            self.skipTest("javac not on PATH -- cannot build a real .class fixture")
        src_dir = os.path.join(self.home, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, "CSVParser.java"), "w") as fh:
            fh.write(
                "package org.apache.commons.csv;\n"
                "public final class CSVParser {\n"
                "    public CSVParser(java.io.Reader r, CSVFormat f) {}\n"
                "    public java.util.List<String> getHeaderNames() { return null; }\n"
                "}\n")
        with open(os.path.join(src_dir, "CSVFormat.java"), "w") as fh:
            fh.write("package org.apache.commons.csv;\npublic final class CSVFormat {}\n")
        subprocess.run([javac, "-d", src_dir, os.path.join(src_dir, "CSVParser.java"),
                        os.path.join(src_dir, "CSVFormat.java")], check=True, timeout=30)
        with zipfile.ZipFile(jar_path, "w") as zf:
            for root, _dirs, files in os.walk(src_dir):
                for name in files:
                    if name.endswith(".class"):
                        full = os.path.join(root, name)
                        arc = os.path.relpath(full, src_dir)
                        zf.write(full, arc)
        return jar_path

    def test_fails_before_no_jar_abstains(self):
        self.assertIsNone(depsurface.gather("jvm", "org.apache.commons:commons-csv", "1.10.0"))

    def test_passes_after_real_javap_signature_no_invented_constructor(self):
        self._write_jar()
        surface = depsurface.gather("jvm", "org.apache.commons:commons-csv", "1.10.0")
        self.assertIsNotNone(surface)
        self.assertEqual(surface.ecosystem, "jvm")
        joined = "\n".join(surface.lines)
        self.assertIn("CSVParser(java.io.Reader", joined)
        # The session's invented single-arg `CSVParser(Reader)` and OpenCSV's `readNext()` must not
        # appear -- there is nothing in the real, freshly compiled class to invent them from.
        self.assertNotIn("readNext", joined)
        self.assertNotIn("hasNext", joined)

    def test_read_hint_says_javap_not_grep_a_jar_is_not_text(self):
        jar = self._write_jar()
        surface = depsurface.gather("jvm", "org.apache.commons:commons-csv", "1.10.0")
        self.assertIn("javap", surface.read_hint)
        self.assertIn(jar, surface.read_hint)
        self.assertNotIn("grep", surface.read_hint)  # a jar is not readable text -- never say grep it


class ScopeTests(_HomeCase):
    def test_unknown_ecosystem_abstains(self):
        self.assertIsNone(depsurface.gather("cobol", "whatever", "1.0"))

    def test_missing_coordinate_fields_abstain(self):
        self.assertIsNone(depsurface.gather("go", "", "v1.0.0"))
        self.assertIsNone(depsurface.gather("go", "github.com/x/y", ""))

    def test_jvm_without_a_valid_groupid_artifactid_coordinate_abstains(self):
        self.assertIsNone(depsurface.gather("jvm", "no-colon-here", "1.0.0"))


class ManifestParsingTests(unittest.TestCase):
    """Pure text parsing -- no disk access -- of the resolver's own durable record, replacing the
    2026-09-24 textual-stdout trigger the supervisor found covered ~0 of the real p27 row."""

    def test_go_mod_single_line_require(self):
        text = "module example.com/x\n\ngo 1.21\n\nrequire github.com/shopspring/decimal v1.4.0\n"
        self.assertEqual(depsurface.parse_manifest("go", text),
                         [("github.com/shopspring/decimal", "v1.4.0")])

    def test_go_mod_require_block(self):
        text = ("module example.com/x\n\nrequire (\n\tgithub.com/shopspring/decimal v1.4.0\n"
                "\tgithub.com/foo/bar v0.1.0\n)\n")
        self.assertEqual(depsurface.parse_manifest("go", text),
                         [("github.com/shopspring/decimal", "v1.4.0"), ("github.com/foo/bar", "v0.1.0")])

    def test_cargo_lock_package_stanza(self):
        text = ('# auto-generated\n\n[[package]]\nname = "toml"\nversion = "0.8.23"\n'
                'source = "registry+https://..."\n\n[[package]]\nname = "serde"\nversion = "1.0.229"\n')
        self.assertEqual(depsurface.parse_manifest("rust", text),
                         [("toml", "0.8.23"), ("serde", "1.0.229")])

    def test_gemfile_lock_top_level_spec(self):
        text = ("GEM\n  remote: https://rubygems.org/\n  specs:\n    countries (3.1.0)\n"
                "      i18n_data (~> 0.13.0)\n    i18n_data (0.13.1)\n\nPLATFORMS\n  ruby\n")
        self.assertEqual(depsurface.parse_manifest("ruby", text),
                         [("countries", "3.1.0"), ("i18n_data", "0.13.1")])

    def test_pom_xml_literal_version(self):
        text = ("<project><dependencies><dependency>\n"
                "<groupId>org.apache.commons</groupId>\n"
                "<artifactId>commons-csv</artifactId>\n"
                "<version>1.10.0</version>\n"
                "</dependency></dependencies></project>")
        self.assertEqual(depsurface.parse_manifest("jvm", text),
                         [("org.apache.commons:commons-csv", "1.10.0")])

    def test_pom_xml_property_version_not_claimed_resolved(self):
        # A `${property}` version is not evaluated here -- reporting it as a literal coordinate would
        # be a claim this parser cannot back; gather()'s cache-presence check is the real confirmation
        # either way, and this parser abstains on the one thing it cannot read without guessing.
        text = ("<dependency><groupId>org.apache.commons</groupId>"
                "<artifactId>commons-csv</artifactId><version>${commons-csv.version}</version>"
                "</dependency>")
        self.assertEqual(depsurface.parse_manifest("jvm", text), [])

    def test_unknown_ecosystem_or_empty_text(self):
        self.assertEqual(depsurface.parse_manifest("cobol", "anything"), [])
        self.assertEqual(depsurface.parse_manifest("go", ""), [])


class DeclaredCoordinatesTests(unittest.TestCase):
    """`declared_coordinates` reads through wsview's body seam (tests/conftest.py's autouse
    DirectView binds real disk reads for the whole suite, exactly like every other wsview-backed
    test in this repo)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_no_workspace_root_is_empty(self):
        self.assertEqual(depsurface.declared_coordinates(None), [])
        self.assertEqual(depsurface.declared_coordinates(""), [])

    def test_no_manifest_on_disk_is_empty(self):
        self.assertEqual(depsurface.declared_coordinates(self.ws), [])

    def test_go_mod_on_disk_is_read_and_parsed(self):
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write("module x\n\nrequire github.com/shopspring/decimal v1.4.0\n")
        self.assertEqual(depsurface.declared_coordinates(self.ws),
                         [("go", "github.com/shopspring/decimal", "v1.4.0")])

    def test_multiple_manifests_on_disk_all_contribute(self):
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write("require github.com/shopspring/decimal v1.4.0\n")
        with open(os.path.join(self.ws, "Cargo.lock"), "w") as fh:
            fh.write('[[package]]\nname = "toml"\nversion = "0.8.23"\n')
        got = set(depsurface.declared_coordinates(self.ws))
        self.assertIn(("go", "github.com/shopspring/decimal", "v1.4.0"), got)
        self.assertIn(("rust", "toml", "0.8.23"), got)


if __name__ == "__main__":
    unittest.main()
