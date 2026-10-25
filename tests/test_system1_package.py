"""The System 1 bundle producer: provenance is verified against the training records, then copied."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cria import system1
from suite import system1_package

PROMPTS = system1_package.PROMPTS
NATIVE_CONFIG = {"architecture_type": "uni-encoder", "prompt_first": True, "class_token_index": 128001,
                 "text_token_index": 128002}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entry(path: Path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha(data)}


def assessed(i, family, state, tokens):
    ids = list(range(tokens))
    return {"id": f"c{i}", "family": family, "int4_prediction": system1.FAMILIES[family].labels[0],
            "int4_logits": [1.5, -0.5],
            "native_input": {"state": state, "tokens": tokens, "native_inputs": {"input_ids": [ids]}}}


def rows_for(n, unicode_index):
    return [assessed(i, "retrospective" if i % 2 else "dictation",
                     {"candidate_briefing" if i % 2 else "public_directive": "ü" if i == unicode_index else "t"},
                     10 + i) for i in range(n)]


@pytest.fixture
def training(tmp_path):
    root = tmp_path / "training"
    run = root / "train-001"
    export = run / "export-001"
    (run / "reference").mkdir(parents=True)
    (export / "int4").mkdir(parents=True)
    (export / "native-reference/onnx").mkdir(parents=True)
    (root / "assessment/v2").mkdir(parents=True)
    native = {"config.json": json.dumps(NATIVE_CONFIG).encode(), "tokenizer.json": b'{"tok": 1}',
              "tokenizer_config.json": b"{}", "model.safetensors": b"native weights",
              "onnx/model.onnx": b"fp32 onnx"}
    for name, data in native.items():
        (export / "native-reference" / name).write_bytes(data)
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json"):
        (run / "reference" / name).write_bytes(native[name])
    (export / "int4/model.onnx").write_bytes(b"int4 graph")
    (export / "int4/model.onnx.data").write_bytes(b"int4 weights")
    (export / "int4/recipe.json").write_text("{}")
    (export / "download.json").write_text(json.dumps({
        "repo": "r", "revision": "rev", "snapshot": str(export / "native-reference"),
        "files": {n: {"bytes": len(d), "sha256": sha(d)} for n, d in native.items()}}))
    files = {n: entry(export / "int4" / n) for n in ("model.onnx", "model.onnx.data")}
    (export / "quantized.json").write_text(json.dumps({
        "source": {"sha256": sha(native["onnx/model.onnx"])}, "files": files,
        "complete_bundle_bytes": sum(f["bytes"] for f in files.values())}))
    (run / "trained.json").write_text("{}")
    (run / "training-source.json").write_text("{}")
    (run / "contract.json").write_text(json.dumps(
        {"policy_sha256": {f: s.policy_sha256 for f, s in system1.FAMILIES.items()}}))
    (root / "assessment/v2/results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows_for(194, 7)) + "\n")
    return root


def test_a_built_bundle_verifies_and_binds_every_source(training, tmp_path):
    out = system1_package.build_bundle(tmp_path / "bundle", training_root=training)
    manifest = dict(system1.verify_bundle(out).manifest)
    assert set(manifest["files"]) == {"model.onnx", "model.onnx.data", "tokenizer.json", "tokenizer_config.json",
                                      "config.json", "policy/retrospective.txt", "policy/dictation.txt"}
    assert (out / "policy/dictation.txt").read_bytes() == (PROMPTS / "offline_onejev_dictation.txt").read_bytes()
    prov = manifest["provenance"]
    assert prov["source_int4_sha256"]["model.onnx"] == sha(b"int4 graph")
    assert prov["native_weights_sha256"] == sha(b"native weights")
    assert set(prov["source_files_sha256"]) >= {"quantized.json", "download.json", "contract.json"}
    assert not list(tmp_path.glob("bundle.tmp-*"))
    assert not any(p.is_symlink() for p in out.rglob("*"))  # standalone: no pointer into the training tree


def test_an_existing_target_is_never_overwritten(training, tmp_path):
    (tmp_path / "bundle").mkdir()
    with pytest.raises(FileExistsError):
        system1_package.build_bundle(tmp_path / "bundle", training_root=training)


@pytest.mark.parametrize("victim,message", [
    ("export-001/int4/model.onnx.data", "quantized artifact"),   # recorded by quantized.json
    ("reference/tokenizer.json", "native file recorded"),        # recorded by download.json
    ("export-001/native-reference/model.safetensors", "frozen native artifact changed"),
])
def test_provenance_is_checked_against_the_producers_records_and_a_failure_leaves_nothing(
        training, tmp_path, victim, message):
    path = training / "train-001" / victim
    path.write_bytes(path.read_bytes() + b"!")
    with pytest.raises(ValueError, match=message):
        system1_package.build_bundle(tmp_path / "bundle", training_root=training)
    assert not (tmp_path / "bundle").exists() and not list(tmp_path.glob("bundle.tmp-*"))


def test_a_policy_that_is_not_the_frozen_training_policy_is_refused(training, tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for family in system1.FAMILIES:
        (prompts / f"offline_onejev_{family}.txt").write_bytes((PROMPTS / f"offline_onejev_{family}.txt").read_bytes())
    (prompts / "offline_onejev_dictation.txt").write_text("edited policy\n")
    with pytest.raises(ValueError, match="frozen training policy"):
        system1_package.build_bundle(tmp_path / "bundle", training_root=training, prompts=prompts)


def test_selftest_takes_shortest_longest_and_non_ascii_per_family_from_the_frozen_calls():
    cases = system1_package.select_selftest(rows_for(20, 9))
    by_family = {f: {c["id"] for c in cases if c["family"] == f} for f in system1.FAMILIES}
    assert by_family == {"retrospective": {"c1", "c19", "c9"}, "dictation": {"c0", "c18"}}
    case = next(c for c in cases if c["id"] == "c1")
    assert case["tokens"] == 11 and case["input_ids_sha256"] == system1._ids_sha(range(11))
    assert case["logits"] == [1.5, -0.5] and case["label"] == "RETROSPECTIVE"


def test_a_recorded_token_count_that_disagrees_with_its_ids_is_refused():
    rows = rows_for(4, -1)
    rows[0]["native_input"]["tokens"] += 1
    with pytest.raises(ValueError, match="token count"):
        system1_package.select_selftest(rows)
