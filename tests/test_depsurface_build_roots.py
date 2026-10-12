"""C40 must find the dependency where THIS run's build keeps it, not only under the home directory.

Walked: feed-pipeline-java x ornith1.5_9b B0/B1. The harness declares the run's writable roots
(`<install>` and the workspace) and the build is told `-Dmaven.repo.local=<install>/m2/repository`; the
resolved opencsv-5.9.jar sat there while depsurface looked only in ~/.m2, abstained every time, and the
coder invented `CSVFormat`/`RFC4180Reader` against a jar it never saw.
"""
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cria import depsurface, dirguard
from test_dependency_surface_note import _WorkspaceCase, tool

POM = ("<project><dependencies><dependency><groupId>com.opencsv</groupId>"
       "<artifactId>opencsv</artifactId><version>5.9</version></dependency></dependencies></project>")
FAKE_JAVAP = ["public class com.opencsv.CSVReader implements java.io.Closeable {",
              "  public java.lang.String[] readNext() throws java.io.IOException;", "}"]


class _BuildLayout(_WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.install = os.path.join(self.home, ".cria", "suite-installs", "run1")
        self.repo = os.path.join(self.install, "m2", "repository")
        d = os.path.join(self.repo, "com", "opencsv", "opencsv", "5.9")
        os.makedirs(d)
        self.jar = os.path.join(d, "opencsv-5.9.jar")
        with zipfile.ZipFile(self.jar, "w") as zf:
            zf.writestr("com/opencsv/CSVReader.class", b"\xca\xfe\xba\xbe")
        with open(os.path.join(self.ws, "pom.xml"), "w") as fh:
            fh.write(POM)
        real = depsurface._javap_lines
        depsurface._javap_lines = lambda jar, fqcn: list(FAKE_JAVAP)
        self.addCleanup(setattr, depsurface, "_javap_lines", real)

    def system(self, text=None):
        text = text if text is not None else (
            f"The writable roots are `{self.install}`, `{self.ws}`.")
        return {"role": "system", "content": text}

    def echo(self, loc=None):
        return tool("Picked up JAVA_TOOL_OPTIONS: \"-Dmaven.repo.local="
                    f"{loc or self.repo}\"\n[ERROR] COMPILATION ERROR")


class BuildRootTests(_BuildLayout):
    def test_declared_root_finds_the_jar_in_the_install_layout(self):
        out = self.represent([self.system(), tool("mvn output")])
        note = out[1]["content"]
        self.assertIn("THE VERSION OF com.opencsv:opencsv:5.9", note)
        self.assertIn(self.jar, note)
        self.assertIn("public java.lang.String[] readNext()", note)

    def test_the_location_the_build_printed_in_a_tool_result_finds_it(self):
        deep = os.path.join(self.install, "a", "b", "c", "d", "e", "repo")
        os.makedirs(os.path.dirname(deep))
        os.rename(self.repo, deep)   # deeper than the bounded search from the root
        out = self.represent([self.system(), self.echo(deep)])
        self.assertIn(os.path.join(deep, "com", "opencsv"), out[1]["content"])

    def test_a_build_location_in_assistant_text_is_never_a_source(self):
        deep = os.path.join(self.install, "a", "b", "c", "d", "e", "repo")
        os.makedirs(os.path.dirname(deep))
        os.rename(self.repo, deep)
        guess = {"role": "assistant", "content": f"-Dmaven.repo.local={deep}"}
        self.assertEqual(dirguard.dependency_roots([self.system(), guess, tool("x")]),
                         (self.install, self.ws))
        out = self.represent([self.system(), guess, tool("mvn output")])
        self.assertEqual(out[2]["content"], "mvn output")

    def test_a_printed_location_outside_every_declared_root_is_ignored(self):
        elsewhere = os.path.join(self.home, "elsewhere", "repository")
        os.makedirs(os.path.dirname(elsewhere))
        os.rename(self.repo, elsewhere)
        out = self.represent([self.system(), self.echo(elsewhere)])
        self.assertEqual(out[1]["content"].count("THE VERSION OF"), 0)

    def test_roots_in_a_user_message_are_not_declared_roots(self):
        said = {"role": "user", "content": f"The writable roots are `{self.install}`."}
        out = self.represent([said, tool("mvn output")])
        self.assertEqual(out[1]["content"], "mvn output")

    def test_no_declared_roots_is_unchanged_behaviour(self):
        out = self.represent([tool("mvn output")])
        self.assertEqual(out[0]["content"], "mvn output")
        self.assertEqual(dirguard.dependency_roots([tool("mvn output")]), ())
        self.assertIsNone(depsurface.gather("jvm", "com.opencsv:opencsv", "5.9"))

    def test_wrong_version_in_the_root_still_abstains(self):
        with open(os.path.join(self.ws, "pom.xml"), "w") as fh:
            fh.write(POM.replace("5.9", "5.8"))
        out = self.represent([self.system(), tool("mvn output")])
        self.assertEqual(out[1]["content"], "mvn output")

    def test_a_symlink_out_of_the_root_is_not_followed(self):
        outside = os.path.join(self.home, "outside")
        os.makedirs(outside)
        os.rename(os.path.join(self.repo, "com"), os.path.join(outside, "com"))
        os.symlink(outside, os.path.join(self.repo, "com"))
        self.assertIsNone(depsurface.gather("jvm", "com.opencsv:opencsv", "5.9",
                                            cache_roots=(self.install,)))

    def test_go_module_cache_under_a_declared_root(self):
        d = os.path.join(self.install, "gomod", "github.com", "shopspring", "decimal@v1.4.0")
        os.makedirs(d)
        with open(os.path.join(d, "decimal.go"), "w") as fh:
            fh.write("package decimal\n\nfunc NewFromString(v string) (Decimal, error) {\n\treturn Decimal{}, nil\n}\n")
        s = depsurface.gather("go", "github.com/shopspring/decimal", "v1.4.0", cache_roots=(self.install,))
        self.assertIsNotNone(s)
        self.assertTrue(s.root.startswith(self.install))
