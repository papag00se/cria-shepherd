"""Dependencies resolved into the RUN's own cache (not ~): the declared coordinates are located by a bounded walk under the
harness-declared cache roots; the real `go doc` / `javap` tools (stand-in executables on PATH) supply the surface; and the
session remembers an abstain, an anchor and a withheld pointer without re-probing (feed-pipeline-java: opencsv sat in
<install>/m2/repository all run while only ~/.m2 was searched)."""
import os
import stat
import zipfile

import pytest

from cria import depsurface as ds
from research_discovery_helpers import disk_view, write  # noqa: F401

pytestmark = pytest.mark.usefixtures("disk_view")
JAVAP = "Compiled from \"CSVReader.java\"\npublic class com.opencsv.CSVReader implements java.io.Closeable {\n  public java.lang.String[] readNext();\n}\n"
GODOC = "package decimal // import \"github.com/shopspring/decimal\"\n\nTYPES\n\ntype Decimal struct {\n\tvalue int\n}\n    A number.\n\nfunc NewFromInt(v int64) Decimal\n"


def tool(directory, name, stdout, code=0):
    path = directory / name
    path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{stdout}EOF\nexit {code}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def run(tmp_path, monkeypatch):
    bin_dir, home = tmp_path / "bin", tmp_path / "home"
    bin_dir.mkdir(), home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    cache = tmp_path / "install" / "caches"                                  # the run's own cache, a few levels below the root
    write(cache, "m2/repository/x/placeholder.txt", "")
    jar = cache / "m2/repository/com/opencsv/opencsv/5.9/opencsv-5.9.jar"
    jar.parent.mkdir(parents=True)
    with zipfile.ZipFile(jar, "w") as z:
        for name in ("com/opencsv/CSVReader.class", "com/opencsv/CSVReader$Builder.class", "com/opencsv/package-info.class", "-evil/Flag.class"):
            z.writestr(name, b"\xca\xfe")
    write(cache, "gomod/github.com/shopspring/decimal@v1.4.0/decimal.go", "package decimal\n\nfunc NewFromInt(v int64) Decimal {\n}\nfunc helper() {}\n")
    write(cache, "cargo/serde-1.0.200/src/lib.rs", "pub trait Serialize {}\nfn hidden() {}\npub struct Wrapper;\n")
    write(cache, "bundle/gems/countries-3.1.0/lib/countries.rb", "module Countries\n  def in_eu?\n  end\nend\n")
    write(tmp_path, "ws/go.mod", "module app\nrequire github.com/shopspring/decimal v1.4.0\n")
    write(tmp_path, "ws/pom.xml", "<project><dependencies><dependency><groupId>com.opencsv</groupId><artifactId>opencsv</artifactId><version>5.9</version></dependency></dependencies></project>")
    return tmp_path, cache, bin_dir


def test_a_coordinate_declared_in_the_manifest_is_found_in_the_runs_cache_and_read_with_the_real_tools(run):
    tmp, cache, bin_dir = run
    ws, roots = str(tmp / "ws"), (str(cache),)
    declared = ds.declared_coordinates(ws)
    assert declared == [("go", "github.com/shopspring/decimal", "v1.4.0"), ("jvm", "com.opencsv:opencsv", "5.9")]
    assert all(ds.source_located(e, p, v, ws, roots) for e, p, v in declared) and not any(ds.source_located(e, p, v, ws) for e, p, v in declared)
    assert not ds.source_located("jvm", "com.opencsv:opencsv", "6.0", ws, roots) and not ds.source_located("cobol", "x", "1", ws, roots)

    assert ds.gather("jvm", "com.opencsv:opencsv", "5.9", ws, roots) is None            # no javap on PATH: abstain, never invent
    tool(bin_dir, "javap", JAVAP)
    jvm = ds.gather("jvm", "com.opencsv:opencsv", "5.9", ws, roots)
    assert jvm.sources == ("com.opencsv.CSVReader",) and "  public java.lang.String[] readNext();" in jvm.lines and not jvm.complete
    assert not any(l.startswith("Compiled from") for l in jvm.lines) and "no further classes" in jvm.read_hint
    tool(bin_dir, "javap", "boom\n", code=1)
    assert ds.gather("jvm", "com.opencsv:opencsv", "5.9", ws, roots) is None             # a failing javap yields nothing, not a guess

    scan = ds.gather("go", "github.com/shopspring/decimal", "v1.4.0", ws, roots)
    assert scan.lines == ("func NewFromInt(v int64) Decimal {",) and not scan.complete  # no `go` on PATH: the bounded file scan
    tool(bin_dir, "go", GODOC)
    doc = ds.gather("go", "github.com/shopspring/decimal", "v1.4.0", ws, roots)
    assert doc.complete and "type Decimal struct {" in doc.lines and "func NewFromInt(v int64) Decimal" in doc.lines
    assert doc.coordinate == "github.com/shopspring/decimal v1.4.0" and doc.read_hint.startswith("run `go doc -all github.com/shopspring/decimal@v1.4.0`")
    tool(bin_dir, "go", "", code=1)
    assert ds.gather("go", "github.com/shopspring/decimal", "v1.4.0", ws, roots).complete is False

    assert [l for l in ds.gather("rust", "serde", "1.0.200", ws, roots).lines] == ["pub trait Serialize {}", "pub struct Wrapper;"]
    assert ds.gather("ruby", "countries", "3.1.0", ws, roots).lines == ("module Countries", "  def in_eu?")


def test_the_walk_under_a_cache_root_is_bounded_and_never_follows_a_link_out(run, monkeypatch):
    tmp, cache, _ = run
    outside = tmp / "outside" / "serde-9.9.9" / "src"
    write(outside, "lib.rs", "pub fn leak() {}\n")
    os.symlink(tmp / "outside", cache / "link")
    assert ds._rust_crate_dir("serde", "9.9.9", (str(cache),)) is None and ds._rust_crate_dir("serde", "1.0.200", (str(cache), "/nonexistent")) is not None
    monkeypatch.setattr(ds, "MAX_ROOT_DIRS", 2)
    assert ds._rust_crate_dir("serde", "1.0.200", (str(cache),)) is None                  # past the directory budget: abstain


def test_the_session_remembers_an_abstain_an_anchor_and_a_withheld_pointer_and_nothing_across_sessions():
    coord = ("jvm", "com.opencsv:opencsv", "5.9")
    assert ds.should_retry_gather("s-dep", coord) is True and ds.should_retry_gather("", coord) is True
    ds.record_abstain("s-dep", coord)
    assert [ds.should_retry_gather("s-dep", coord) for _ in range(ds._ABSTAIN_RETRY_EVERY)] == [False] * (ds._ABSTAIN_RETRY_EVERY - 1) + [True]
    ds.clear_abstain("s-dep", coord)
    assert ds.should_retry_gather("s-dep", coord) is True
    assert ds.anchor_state("s-dep", coord) is None
    ds.set_anchor_state("s-dep", coord, "call_1", "NOTE")
    ds.set_anchor_state("s-dep", coord, "call_2", "NOTE2")                                # anchor loss: the note moves to the newest result
    assert ds.anchor_state("s-dep", coord) == ("call_2", "NOTE2") and ds.anchor_state("other", coord) is None
    ds.record_withheld("s-dep", coord, "com.opencsv:opencsv:5.9", "/m2/x.jar", "run javap")
    assert ds.is_withheld("s-dep", coord) and not ds.is_withheld("other", coord)
    assert ds.withheld_pointers("s-dep", {coord}) == [("com.opencsv:opencsv:5.9", "/m2/x.jar", "run javap")]
    assert ds.withheld_pointers("s-dep", {("jvm", "com.opencsv:opencsv", "6.0")}) == []   # a bumped version drops the stale pointer
