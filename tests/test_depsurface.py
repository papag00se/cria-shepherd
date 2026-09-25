"""cria/depsurface.py — Candidate C40's ground-truth probe of a resolved dependency's real exported
surface. Covers: the 2026-09-25a manifest/lockfile parsing (direct dependencies only, B2), the
2026-09-25b safety fixes (path containment + coordinate grammar + javap class allowlist, B4), the
completeness contract (B3: `complete=True` only for a real, authoritative, exhaustive tool), and the
session-scoped delivered-state store (B1).

Hermetic: every fixture builds its own throwaway cache tree under a temp HOME/workspace: no test here
depends on a real ``~/go/pkg/mod``, ``~/.cargo``, or gem install existing on the box that runs the
suite (the JVM ``javap`` tests are the one exception, guarded by an explicit availability check).
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
        self.assertIsNone(depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0"))

    def test_passes_after_real_exported_signatures_selected_fallback_scan(self):
        # No real `go` binary available in this sandbox in general -- force the fallback path by
        # using a fake module name `go doc` cannot possibly resolve even if `go` IS present, so this
        # test is meaningful with or without a real Go toolchain on the box running the suite.
        self._write_module(module="example.invalid/nonexistent", body=(
            "package decimal\n\n"
            "type Decimal struct {\n\tvalue *big.Int\n}\n\n"
            "func NewFromString(value string) (Decimal, error) {\n\treturn Decimal{}, nil\n}\n\n"
            "func (d Decimal) Round(places int32) Decimal {\n\treturn d\n}\n\n"
            "func (a *decimal) Round(nd int) {}\n\n"   # UNEXPORTED receiver -- must be excluded (B3)
            "func lowerCaseHelper() int {\n\treturn 0\n}\n"))
        surface = depsurface.gather("go", "example.invalid/nonexistent", "v1.4.0")
        self.assertIsNotNone(surface)
        self.assertFalse(surface.complete)   # fallback scan is never complete (B3)
        self.assertIn("func NewFromString(value string) (Decimal, error) {", surface.lines)
        self.assertIn("func (d Decimal) Round(places int32) Decimal {", surface.lines)
        self.assertIn("type Decimal struct {", surface.lines)
        self.assertFalse(any("Quantize" in ln for ln in surface.lines))
        self.assertFalse(any("lowerCaseHelper" in ln for ln in surface.lines))
        # The unexported-receiver method must NOT be selected (independent review B3 -- this exact
        # false-positive crowded the real Decimal.Round/RoundCeil out of the real cart replay).
        self.assertFalse(any("*decimal) Round" in ln for ln in surface.lines))

    def test_byte_exact_no_line_differs_from_the_real_file(self):
        real = ("package decimal\n\nfunc NewFromString(value string) (Decimal, error) {\n"
                "\treturn Decimal{}, nil\n}\n")
        self._write_module(module="example.invalid/nonexistent", body=real)
        surface = depsurface.gather("go", "example.invalid/nonexistent", "v1.4.0")
        for line in surface.lines:
            self.assertIn(line, real.splitlines())

    def test_test_files_excluded(self):
        d = self._write_module(module="example.invalid/nonexistent",
                               body="package decimal\nfunc NewFromString(v string) Decimal { return Decimal{} }\n")
        with open(os.path.join(d, "decimal_test.go"), "w") as fh:
            fh.write("package decimal\nfunc TestSomething() {}\n")
        surface = depsurface.gather("go", "example.invalid/nonexistent", "v1.4.0")
        self.assertNotIn("decimal_test.go", surface.sources)

    def test_uppercase_module_segment_is_escaped(self):
        d = os.path.join(self.home, "go", "pkg", "mod", "github.com", "!c!o!r!p", "!widget@v1.0.0")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "widget.go"), "w") as fh:
            fh.write("package widget\nfunc New() int { return 0 }\n")
        surface = depsurface.gather("go", "github.com/CORP/Widget", "v1.0.0")
        self.assertIsNotNone(surface)

    def test_read_hint_points_at_the_real_readable_directory(self):
        d = self._write_module(module="example.invalid/nonexistent",
                               body="package decimal\nfunc NewFromString(v string) Decimal { return Decimal{} }\n")
        surface = depsurface.gather("go", "example.invalid/nonexistent", "v1.4.0")
        self.assertIn(d, surface.read_hint)
        self.assertIn("read_file", surface.read_hint)

    @unittest.skipUnless(shutil.which("go"), "go not on PATH on this machine")
    def test_real_go_doc_all_used_when_the_module_is_in_the_real_local_cache(self):
        # A REAL box test, not hermetic to this fixture's temp HOME: proves `go doc -all` fires and
        # is labelled complete against the box's real module cache, IF it happens to hold this exact
        # coordinate (the same cache the c40-replay scripts use). Skips cleanly otherwise.
        os.path.expanduser = self._real_expanduser
        real_cache = os.path.expanduser("~/go/pkg/mod/github.com/shopspring/decimal@v1.4.0")
        if not os.path.isdir(real_cache):
            self.skipTest("real shopspring/decimal@v1.4.0 not cached on this box")
        surface = depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0")
        self.assertIsNotNone(surface)
        self.assertTrue(surface.complete)
        joined = "\n".join(surface.lines)
        self.assertIn("func (d Decimal) Round(places int32) Decimal", joined)
        self.assertIn("func (d Decimal) RoundCeil(places int32) Decimal", joined)
        self.assertIn("func NewFromString(value string) (Decimal, error)", joined)


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
        self.assertFalse(surface.complete)   # Rust never claims completeness (B3)
        self.assertTrue(any("pub fn from_str" in ln for ln in surface.lines))
        self.assertFalse(any("private_helper" in ln for ln in surface.lines))
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
        self.assertFalse(surface.complete)
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
    def _write_jar(self, group="org.apache.commons", artifact="commons-csv", version="1.10.0"):
        import zipfile
        import subprocess
        d = os.path.join(self.home, ".m2", "repository", *group.split("."), artifact, version)
        os.makedirs(d, exist_ok=True)
        jar_path = os.path.join(d, f"{artifact}-{version}.jar")
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
                        zf.write(full, os.path.relpath(full, src_dir))
        return jar_path

    def _write_weird_named_jar_entry(self, group="org.evil", artifact="pwn", version="1.0.0"):
        """A jar whose one entry is shaped like a `javap` flag -- B4's option-injection fixture."""
        import zipfile
        d = os.path.join(self.home, ".m2", "repository", *group.split("."), artifact, version)
        os.makedirs(d, exist_ok=True)
        jar_path = os.path.join(d, f"{artifact}-{version}.jar")
        with zipfile.ZipFile(jar_path, "w") as zf:
            zf.writestr("-J-Dpwned=1.class", b"")
            zf.writestr("-version.class", b"")
            zf.writestr("ok/Real.class", b"")   # one entry that WOULD pass the allowlist
        return jar_path

    def test_fails_before_no_jar_abstains(self):
        self.assertIsNone(depsurface.gather("jvm", "org.apache.commons:commons-csv", "1.10.0"))

    def test_passes_after_real_javap_signature_no_invented_constructor(self):
        self._write_jar()
        surface = depsurface.gather("jvm", "org.apache.commons:commons-csv", "1.10.0")
        self.assertIsNotNone(surface)
        self.assertFalse(surface.complete)   # bounded to MAX_FILES real classes -- never complete
        joined = "\n".join(surface.lines)
        self.assertIn("CSVParser(java.io.Reader", joined)
        self.assertNotIn("readNext", joined)
        self.assertNotIn("hasNext", joined)

    def test_read_hint_says_javap_not_grep_a_jar_is_not_text(self):
        jar = self._write_jar()
        surface = depsurface.gather("jvm", "org.apache.commons:commons-csv", "1.10.0")
        self.assertIn("javap", surface.read_hint)
        self.assertIn(jar, surface.read_hint)
        self.assertNotIn("grep", surface.read_hint)

    def test_option_shaped_class_entries_never_reach_javap(self):
        # B4: a crafted jar entry name that looks like a `javap` flag must never be passed to the
        # real subprocess at all -- `_jar_classes` filters it before `_javap_lines` is ever called.
        self._write_weird_named_jar_entry()
        classes = depsurface._jar_classes(
            os.path.join(self.home, ".m2", "repository", "org", "evil", "pwn", "1.0.0", "pwn-1.0.0.jar"))
        self.assertNotIn("-J-Dpwned=1", classes)
        self.assertNotIn("-version", classes)
        self.assertIn("ok.Real", classes)

    def test_javap_lines_refuses_an_unvalidated_name_even_if_called_directly(self):
        jar = self._write_jar()
        self.assertEqual(depsurface._javap_lines(jar, "-J-Dpwned=1"), [])
        self.assertEqual(depsurface._javap_lines(jar, "; rm -rf /"), [])


class ScopeTests(_HomeCase):
    def test_unknown_ecosystem_abstains(self):
        self.assertIsNone(depsurface.gather("cobol", "whatever", "1.0"))

    def test_missing_coordinate_fields_abstain(self):
        self.assertIsNone(depsurface.gather("go", "", "v1.0.0"))
        self.assertIsNone(depsurface.gather("go", "github.com/x/y", ""))

    def test_jvm_without_a_valid_groupid_artifactid_coordinate_abstains(self):
        self.assertIsNone(depsurface.gather("jvm", "no-colon-here", "1.0.0"))


class PathEscapeTests(_HomeCase):
    """B4: a manifest-declared coordinate is untrusted data. Every ecosystem must refuse a
    coordinate shaped to escape its cache root, even when a file that would otherwise satisfy the
    escaped path genuinely exists there."""

    def test_go_package_escape_is_refused(self):
        # A file genuinely sitting one level above the module cache root.
        secret = os.path.join(self.home, "go", "pkg", "secret.go")
        os.makedirs(os.path.dirname(secret), exist_ok=True)
        open(secret, "w").close()
        self.assertIsNone(depsurface.gather("go", "../secret", "v1.0.0"))
        self.assertIsNone(depsurface.gather("go", "..%2F..%2Fsecret", "v1.0.0"))

    def test_rust_crate_name_escape_is_refused(self):
        self.assertIsNone(depsurface.gather("rust", "../../etc", "1.0.0"))
        self.assertIsNone(depsurface.gather("rust", "toml", "../../etc"))

    def test_ruby_gem_name_escape_is_refused(self):
        self.assertIsNone(depsurface.gather("ruby", "../../etc", "1.0.0"))

    def test_jvm_group_or_artifact_escape_is_refused(self):
        self.assertIsNone(depsurface.gather("jvm", "../../etc:passwd", "1.0.0"))
        self.assertIsNone(depsurface.gather("jvm", "org.apache.commons:../../../etc", "1.10.0"))

    def test_jvm_absolute_artifact_does_not_reset_the_join(self):
        # os.path.join("/a/b", "/etc/passwd") == "/etc/passwd" -- the exact escape independent
        # review flagged. An absolute-looking artifactId must never resolve outside ~/.m2.
        real_secret = os.path.join(self.home, "run_secret")
        with open(real_secret, "w") as fh:
            fh.write("nope")
        self.assertIsNone(depsurface.gather("jvm", "org.apache.commons:" + real_secret, "1.10.0"))

    def test_safe_child_rejects_a_symlink_escape(self):
        root = os.path.join(self.home, "cacheroot")
        outside = os.path.join(self.home, "outside")
        os.makedirs(root, exist_ok=True)
        os.makedirs(outside, exist_ok=True)
        os.symlink(outside, os.path.join(root, "link"))
        self.assertIsNone(depsurface._safe_child(root, "link", "..", "outside"))
        result = depsurface._safe_child(root, "link")
        # The symlink target itself is not under root -- refused.
        self.assertIsNone(result)

    def test_safe_child_accepts_a_real_child(self):
        root = os.path.join(self.home, "cacheroot")
        os.makedirs(os.path.join(root, "a", "b"), exist_ok=True)
        got = depsurface._safe_child(root, "a", "b")
        self.assertEqual(got, os.path.realpath(os.path.join(root, "a", "b")))


class ManifestParsingTests(unittest.TestCase):
    """Pure text parsing -- no disk access -- of the resolver's own durable record. Direct
    dependencies only (independent review B2): a lockfile enumerates the whole transitive graph."""

    def test_go_mod_single_line_require(self):
        text = "module example.com/x\n\ngo 1.21\n\nrequire github.com/shopspring/decimal v1.4.0\n"
        self.assertEqual(depsurface.parse_manifest("go", text),
                         [("github.com/shopspring/decimal", "v1.4.0")])

    def test_go_mod_require_block(self):
        text = ("module example.com/x\n\nrequire (\n\tgithub.com/shopspring/decimal v1.4.0\n"
                "\tgithub.com/foo/bar v0.1.0\n)\n")
        self.assertEqual(depsurface.parse_manifest("go", text),
                         [("github.com/shopspring/decimal", "v1.4.0"), ("github.com/foo/bar", "v0.1.0")])

    def test_go_mod_indirect_requires_excluded(self):
        text = ("module example.com/x\n\n"
                "require github.com/shopspring/decimal v1.4.0\n"
                "require github.com/transitive/thing v0.0.1 // indirect\n"
                "require (\n\tgithub.com/another/direct v2.0.0\n"
                "\tgithub.com/another/indirect v0.0.2 // indirect\n)\n")
        got = depsurface.parse_manifest("go", text)
        self.assertIn(("github.com/shopspring/decimal", "v1.4.0"), got)
        self.assertIn(("github.com/another/direct", "v2.0.0"), got)
        self.assertNotIn(("github.com/transitive/thing", "v0.0.1"), got)
        self.assertNotIn(("github.com/another/indirect", "v0.0.2"), got)

    def test_cargo_toml_direct_names_inline_table(self):
        text = '[package]\nname = "x"\n\n[dependencies]\ntoml = "0.8"\nserde = { version = "1.0" }\n'
        self.assertEqual(depsurface._cargo_toml_direct_names(text), {"toml", "serde"})

    def test_cargo_toml_direct_names_own_table_form(self):
        text = '[dependencies.toml]\nversion = "0.8"\nfeatures = ["parse"]\n'
        self.assertEqual(depsurface._cargo_toml_direct_names(text), {"toml"})

    def test_cargo_direct_coordinates_excludes_transitive(self):
        toml_text = '[dependencies]\ntoml = "0.8"\n'
        lock_text = ('[[package]]\nname = "toml"\nversion = "0.8.23"\n\n'
                    '[[package]]\nname = "serde"\nversion = "1.0.229"\n')  # transitive, not in Cargo.toml
        got = depsurface._cargo_direct_coordinates(toml_text, lock_text)
        self.assertEqual(got, [("toml", "0.8.23")])

    def test_gemfile_lock_direct_only_excludes_transitive(self):
        text = ("GEM\n  remote: https://rubygems.org/\n  specs:\n    countries (3.1.0)\n"
                "      i18n_data (~> 0.13.0)\n    i18n_data (0.13.1)\n\n"
                "PLATFORMS\n  ruby\n\nDEPENDENCIES\n  countries\n\nBUNDLED WITH\n   2.4.0\n")
        got = depsurface._gemfile_lock_direct_coordinates(text)
        self.assertEqual(got, [("countries", "3.1.0")])   # i18n_data is transitive-only, excluded

    def test_pom_xml_literal_version_direct_only(self):
        text = ("<project><dependencies><dependency>\n"
                "<groupId>org.apache.commons</groupId>\n"
                "<artifactId>commons-csv</artifactId>\n"
                "<version>1.10.0</version>\n"
                "</dependency></dependencies></project>")
        self.assertEqual(depsurface.parse_manifest("jvm", text),
                         [("org.apache.commons:commons-csv", "1.10.0")])

    def test_pom_xml_dependency_management_excluded(self):
        text = ("<project><dependencyManagement><dependencies><dependency>\n"
                "<groupId>com.example</groupId><artifactId>pinned-only</artifactId>"
                "<version>9.9.9</version>\n"
                "</dependency></dependencies></dependencyManagement>"
                "<dependencies><dependency>\n"
                "<groupId>org.apache.commons</groupId><artifactId>commons-csv</artifactId>"
                "<version>1.10.0</version>\n"
                "</dependency></dependencies></project>")
        got = depsurface.parse_manifest("jvm", text)
        self.assertEqual(got, [("org.apache.commons:commons-csv", "1.10.0")])
        self.assertNotIn(("com.example:pinned-only", "9.9.9"), got)

    def test_pom_xml_property_version_not_claimed_resolved(self):
        text = ("<dependency><groupId>org.apache.commons</groupId>"
                "<artifactId>commons-csv</artifactId><version>${commons-csv.version}</version>"
                "</dependency>")
        self.assertEqual(depsurface.parse_manifest("jvm", text), [])

    def test_unknown_ecosystem_or_empty_text(self):
        self.assertEqual(depsurface.parse_manifest("cobol", "anything"), [])
        self.assertEqual(depsurface.parse_manifest("go", ""), [])


class DeclaredCoordinatesTests(unittest.TestCase):
    """`declared_coordinates` reads through wsview's body seam (tests/conftest.py's autouse
    DirectView binds real disk reads for the whole suite)."""

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

    def test_rust_requires_both_cargo_toml_and_cargo_lock(self):
        with open(os.path.join(self.ws, "Cargo.lock"), "w") as fh:
            fh.write('[[package]]\nname = "toml"\nversion = "0.8.23"\n')
        # Cargo.toml missing -- no direct-name source, so nothing is declared even though the lock
        # entry exists (never trust the lockfile alone, B2).
        self.assertEqual(depsurface.declared_coordinates(self.ws), [])
        with open(os.path.join(self.ws, "Cargo.toml"), "w") as fh:
            fh.write('[dependencies]\ntoml = "0.8"\n')
        self.assertEqual(depsurface.declared_coordinates(self.ws), [("rust", "toml", "0.8.23")])

    def test_multiple_manifests_on_disk_all_contribute(self):
        with open(os.path.join(self.ws, "go.mod"), "w") as fh:
            fh.write("require github.com/shopspring/decimal v1.4.0\n")
        with open(os.path.join(self.ws, "Cargo.toml"), "w") as fh:
            fh.write('[dependencies]\ntoml = "0.8"\n')
        with open(os.path.join(self.ws, "Cargo.lock"), "w") as fh:
            fh.write('[[package]]\nname = "toml"\nversion = "0.8.23"\n')
        got = set(depsurface.declared_coordinates(self.ws))
        self.assertIn(("go", "github.com/shopspring/decimal", "v1.4.0"), got)
        self.assertIn(("rust", "toml", "0.8.23"), got)


class AnchorStateTests(unittest.TestCase):
    """B1 round 2: real session-scoped ANCHOR state (tool_call_id + exact rendered text), checked/
    updated by `writeproxy._note_dependency_surface` but owned here so it can be unit-tested directly."""

    def setUp(self):
        depsurface._ANCHOR.clear()
        self.addCleanup(depsurface._ANCHOR.clear)

    def test_unanchored_coordinate_has_no_state(self):
        self.assertIsNone(depsurface.anchor_state("sess-1", ("go", "x", "v1.0.0")))

    def test_anchored_coordinate_remembers_call_id_and_text_for_that_session_only(self):
        depsurface.set_anchor_state("sess-1", ("go", "x", "v1.0.0"), "call-abc", "the real note")
        self.assertEqual(depsurface.anchor_state("sess-1", ("go", "x", "v1.0.0")),
                         ("call-abc", "the real note"))
        self.assertIsNone(depsurface.anchor_state("sess-2", ("go", "x", "v1.0.0")))

    def test_no_session_key_never_records_and_never_recalls(self):
        depsurface.set_anchor_state("", ("go", "x", "v1.0.0"), "call-abc", "text")
        self.assertIsNone(depsurface.anchor_state("", ("go", "x", "v1.0.0")))

    def test_no_call_id_never_records(self):
        depsurface.set_anchor_state("sess-1", ("go", "x", "v1.0.0"), "", "text")
        self.assertIsNone(depsurface.anchor_state("sess-1", ("go", "x", "v1.0.0")))

    def test_re_anchoring_moves_the_call_id_keeps_the_text(self):
        coord = ("go", "x", "v1.0.0")
        depsurface.set_anchor_state("sess-1", coord, "call-old", "the real note")
        depsurface.set_anchor_state("sess-1", coord, "call-new", "the real note")
        self.assertEqual(depsurface.anchor_state("sess-1", coord), ("call-new", "the real note"))

    def test_bounded_per_session(self):
        for i in range(depsurface._ANCHOR_MAX_PER_SESSION + 10):
            depsurface.set_anchor_state("sess-1", ("go", f"pkg{i}", "v1.0.0"), f"call-{i}", "text")
        self.assertLessEqual(len(depsurface._ANCHOR["sess-1"]), depsurface._ANCHOR_MAX_PER_SESSION)


if __name__ == "__main__":
    unittest.main()
