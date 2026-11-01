"""A toolchain's build output is named by the survey, not walked (E2ERS: after the first `cargo build` the survey spent its whole tree budget
inside `target/`, so every Rust survey said "NOT complete" and no judge could settle that a file was absent).

The real survey program runs in a real shell on a real directory; the readers are the real view, the real inventory renderer and the real
lint-floor walk."""
import subprocess

import pytest

from cria import groundtruth, linterprobe, probediscovery, wsview


def surveyed(root, sess, **kw):
    out = subprocess.run(["bash", "-lc", wsview.survey_command(sess, cd=str(root), **kw)], capture_output=True, text=True, timeout=120).stdout
    view = wsview.View(str(root), sess)
    assert wsview.apply_survey(view, wsview.strip_survey(out)[1])
    return view


def crate(root, *, manifest="Cargo.toml", output="target", outputs=300):
    (root / manifest).write_text("[package]\nname = 'x'\n")
    (root / "src").mkdir()
    (root / "src" / "main.rs").write_text("fn main() {}\n")
    (root / "src" / "lib.py").write_text("x = 1\n")
    for i in range(outputs // 6):                       # a built crate: dozens of directories, hundreds of files
        d = root / output / "debug" / "deps" / f"d{i}"
        d.mkdir(parents=True)
        for j in range(6):
            (d / f"lib{j}.rlib").write_text("x")


@pytest.mark.parametrize("manifest,output", [("Cargo.toml", "target"), ("pom.xml", "target"), ("build.gradle", "build"), ("build.gradle.kts", ".gradle"), ("mix.exs", "_build")])
def test_a_built_project_is_surveyed_complete_with_its_output_named_and_unknown_inside(tmp_path, manifest, output):
    crate(tmp_path, manifest=manifest, output=output)
    view = surveyed(tmp_path, "survey1-built")
    assert view.complete and view.isdir(output) is True and view.isfile("src/main.rs") is True and view.isfile("src/missing.rs") is False
    assert view.isfile(f"{output}/debug/deps/d0/lib0.rlib") is None and view.listdir(output) is None      # unknown, not absent
    assert sorted(e.path for e in view.files()) == sorted(str(tmp_path / p) for p in (manifest, "src/main.rs", "src/lib.py"))
    assert view.build_output(output) == f"{manifest} beside it" and view.build_output("src") is None


def test_an_output_name_without_its_ecosystems_manifest_is_an_ordinary_directory_and_is_walked(tmp_path):
    """`target`/`build` are also names an author writes into; only the manifest beside them makes them output. A pom.xml is not gradle's."""
    crate(tmp_path, manifest="pom.xml", output="build", outputs=12)
    view = surveyed(tmp_path, "survey1-ambiguous")
    assert view.isfile("build/debug/deps/d0/lib0.rlib") is True and view.folded == [] and view.build_output("build") is None


def test_the_inventory_of_a_built_crate_settles_absence_and_a_real_fold_still_bounds_it(tmp_path):
    crate(tmp_path)
    token = wsview.bind(surveyed(tmp_path, "survey1-inventory"))
    try:
        built = groundtruth.workspace_inventory(str(tmp_path))
        assert groundtruth.survey_settles_absence(built) and "NOT complete" not in built and "target" in built
        assert groundtruth.survey_settled_absent(built, ["README.md", "target/debug/app.d"]) == ["README.md"]
    finally:
        wsview.unbind(token)
    big = tmp_path / "src" / "big"
    big.mkdir()
    for i in range(wsview.FOLD_AT + 1):
        (big / f"f{i}.rs").write_text("")
    token = wsview.bind(surveyed(tmp_path, "survey1-inventory-fold"))
    try:
        assert not groundtruth.survey_settles_absence(groundtruth.workspace_inventory(str(tmp_path)))
    finally:
        wsview.unbind(token)


def test_the_lint_floor_skips_a_folded_output_on_its_proof_and_still_walks_the_source(tmp_path):
    crate(tmp_path)
    token = wsview.bind(surveyed(tmp_path, "survey1-lint"))
    try:
        files, skipped = linterprobe.collect_files_with_skips(str(tmp_path), ["py", "rs"])
    finally:
        wsview.unbind(token)
    assert files == [str(tmp_path / "src" / "lib.py"), str(tmp_path / "src" / "main.rs")]
    assert skipped == ["target (Cargo.toml beside it)"]


def test_every_manifest_that_proves_an_output_is_one_its_ecosystem_is_discovered_from():
    """The proof is the discovery's own evidence: a manifest the table names that discovery would not read as that ecosystem is a typo."""
    for ecosystem, rules in wsview.BUILD_ARTIFACT_DIRS.items():
        for manifests, names in rules:
            assert names and all(not n.startswith("/") and "/" not in n for n in names)
            for manifest in manifests:
                found = probediscovery.detect_ecosystems(probediscovery.ProjectDir(dir=None, files={manifest}))
                assert ecosystem in [probediscovery.eco_name(e) for e in found], (ecosystem, manifest)
