"""System 1 bundle verification table: every way a bundle can be wrong (manifest, files, links, budget, native config, policy bytes, self-test coverage) is a typed
System1BundleError naming the cause BEFORE anything loads; a pristine bundle verifies; the typed state/dependency errors of the runtime edge."""
import hashlib
import json
import os
import types

import pytest

from cria import system1
from cria.system1 import System1BundleError
from test_misc_runtime_system1 import eng, make_bundle  # noqa: F401


def edit_manifest(fn):
    def mutate(root):
        path = root / "manifest.json"
        manifest = json.loads(path.read_text())
        fn(manifest, root)
        path.write_text(json.dumps(manifest))
    return mutate


def rewrite_file(name, data, relist=True):
    """Replace a bundle file; keep the manifest honest about it unless relist is False."""
    def mutate(manifest, root):
        (root / name).write_bytes(data)
        if relist:
            manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return edit_manifest(mutate)


def drop(key):
    return edit_manifest(lambda m, r: m.pop(key))


def setkey(key, value):
    return edit_manifest(lambda m, r: m.__setitem__(key, value))


def symlink(root):
    os.symlink(root / "tokenizer.json", root / "link.json")


ROWS = [
    (setkey("schema", "other/9"), "manifest schema must be"),
    (setkey("bundle_id", ""), "no bundle_id"),
    (setkey("renderer", "mystery"), "manifest renderer must be"),
    (setkey("max_window_tokens", 512), "frozen 16384 tokens"),
    (setkey("weight_budget_bytes", 1), "frozen 250000000 bytes"),
    (setkey("files", {}), "lists no files"),
    (edit_manifest(lambda m, r: m["files"].__setitem__("../escape", {"bytes": 1, "sha256": "0" * 64})), "unsafe bundle path"),
    (edit_manifest(lambda m, r: m["files"]["model.onnx"].update(sha256="NOT-HEX")), "needs integer bytes and a hex sha256"),
    (edit_manifest(lambda m, r: m["files"]["model.onnx"].update(bytes=-1)), "needs integer bytes and a hex sha256"),
    (setkey("weights", []), "names no external weight file"),
    (edit_manifest(lambda m, r: m["families"].pop("dictation")), "families must be exactly"),
    (edit_manifest(lambda m, r: m["families"]["dictation"].update(labels=["X", "Y"])), "labels/state key differ"),
    (setkey("graph", "ghost.onnx"), "not in its file list"),
    (symlink, "bundle contains a symlink"),
    (lambda root: (root / "extra.bin").write_bytes(b"x"), "unlisted ['extra.bin']"),
    (lambda root: (root / "model.onnx").unlink(), "missing ['model.onnx']"),
    (rewrite_file("model.onnx.data", b"w" * system1.WEIGHT_BUDGET_BYTES, relist=False), "budget is under"),
    (edit_manifest(lambda m, r: m["files"]["tokenizer.json"].update(bytes=99)), "manifest says 99"),
    (lambda root: (root / "tokenizer.json").write_bytes(b"[]"), "tampered or corrupt"),
    (rewrite_file("config.json", b"{not json"), "native config is not JSON"),
    (rewrite_file("config.json", json.dumps({"architecture_type": "bi-encoder", "prompt_first": True, "class_token_index": 128001, "text_token_index": 128002}).encode()), "architecture_type is 'bi-encoder'"),
    (rewrite_file("config.json", json.dumps({"architecture_type": "uni-encoder", "prompt_first": False, "class_token_index": 128001, "text_token_index": 128002}).encode()), "prompt_first is False"),
    (rewrite_file("policy/dictation.txt", b"a different policy"), "dictation policy is not the policy the model was trained under"),
    (rewrite_file("policy/dictation.txt", b"\xff\xfe"), "cannot read a policy file"),
    (setkey("selftest", []), "at least one selftest case for every family"),
    (edit_manifest(lambda m, r: m.__setitem__("selftest", m["selftest"][:1])), "at least one selftest case for every family"),
]


@pytest.mark.parametrize("mutate, message", ROWS, ids=[m for _, m in ROWS])
def test_a_bundle_with_any_defect_is_refused_with_the_defect_named(eng, tmp_path, mutate, message):  # noqa: F811
    """Each row corrupts exactly one thing in an otherwise valid bundle; verification names it, loading never starts."""
    root = make_bundle(tmp_path / "b", eng, mutate)
    with pytest.raises(System1BundleError, match=message.replace("[", r"\[").replace("]", r"\]").replace("(", r"\(")):
        system1.verify_bundle(root)


def test_a_pristine_bundle_verifies_and_the_pin_and_location_checks_apply(eng, tmp_path):  # noqa: F811
    """The good bundle yields its id, hashed manifest and policy texts (immutable); a wrong pinned manifest hash, a missing manifest, a file posing as the bundle and a symlinked bundle dir are refused."""
    root = make_bundle(tmp_path / "b", eng)
    bundle = system1.verify_bundle(root)
    sha = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    assert bundle.bundle_id == "fake" and bundle.manifest_sha256 == sha and set(bundle.policies) == set(system1.FAMILIES)
    assert system1.verify_bundle(root, expected_manifest_sha256=sha).manifest_sha256 == sha
    with pytest.raises(TypeError):
        bundle.manifest["bundle_id"] = "x"
    with pytest.raises(System1BundleError, match="is not the pinned"):
        system1.verify_bundle(root, expected_manifest_sha256="0" * 64)
    (tmp_path / "empty").mkdir()
    (tmp_path / "file").write_text("x")
    os.symlink(root, tmp_path / "alias")
    for bad in (tmp_path / "empty", tmp_path / "file", tmp_path / "alias", tmp_path / "absent"):
        with pytest.raises(System1BundleError, match="not a directory|cannot read System 1 bundle manifest"):
            system1.verify_bundle(bad)
    (tmp_path / "empty" / "manifest.json").write_text("{nope")
    with pytest.raises(System1BundleError, match="manifest is not JSON"):
        system1.verify_bundle(tmp_path / "empty")


def test_an_absent_runtime_library_is_a_typed_dependency_error_and_unsafe_names_never_pass(monkeypatch):
    """Importing a missing optional extra says which one; the path validator refuses absolute, parent, empty-segment and backslash names."""
    with pytest.raises(system1.System1DependencyError, match="'no_such_module_sv2' is not installed"):
        system1._import("no_such_module_sv2")
    for name in ("/abs", "a/../b", "a//b", "a\\b", "", None, "./x"):
        with pytest.raises(System1BundleError):
            system1._relative(name)
    assert system1._relative("policy/x.txt") == "policy/x.txt"
