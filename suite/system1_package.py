"""Producer: freeze a GLiClass v2 INT4 export into a standalone System 1 bundle.

Reads the training artifacts ONCE, at build time, and writes ``<out>`` containing only what
``cria.system1`` needs to serve — graph, external weights, tokenizer, native config, the exact policy
bytes and a ``manifest.json`` binding every file by size and SHA-256 — plus the source hashes of the
artifacts it was cut from. The bundle has no path or symlink into the training tree. The manifest also
carries a self-test taken from the frozen INT4 assessment calls (exact token-id digest, label and
logits), which the runtime replays at startup.

    python -m suite.system1_package --out ~/.cria/models/system1/expanded-v2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from cria import system1
from suite.gliclass_quantize import validate_native_manifest
from cria.system1 import FAMILIES, MANIFEST_NAME, MANIFEST_SCHEMA, MAX_WINDOW_TOKENS, RENDERER, WEIGHT_BUDGET_BYTES

TRAINING_ROOT = Path("~/.cria/training/gliclass-v4-edge-expanded-v2").expanduser()
PROMPTS = Path(__file__).resolve().parent.parent / "cria" / "prompts"
DEFAULT_BUNDLE_ID = "gliclass-v4-edge-expanded-v2-int4"


def _sha(path: Path) -> str:
    return system1._file_sha256(path)


def select_selftest(rows: list[dict]) -> list[dict]:
    """Per family: the shortest, the longest, and the shortest non-ASCII frozen INT4 assessment call."""
    cases = []
    for family in FAMILIES:
        rs = [r for r in rows if r["family"] == family]
        non_ascii = [r for r in rs if any(ord(c) > 127 for c in json.dumps(r["native_input"]["state"], ensure_ascii=False))]
        picks = [min(rs, key=lambda r: r["native_input"]["tokens"]),
                 max(rs, key=lambda r: r["native_input"]["tokens"])]
        if non_ascii:
            picks.append(min(non_ascii, key=lambda r: r["native_input"]["tokens"]))
        seen = set()
        for r in picks:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            native = r["native_input"]
            ids = native["native_inputs"]["input_ids"][0]
            if len(ids) != native["tokens"]:
                raise ValueError(f"{r['id']}: recorded token count disagrees with its ids")
            cases.append({"id": r["id"], "family": family, "state": native["state"], "tokens": native["tokens"],
                          "input_ids_sha256": system1._ids_sha(ids), "label": r["int4_prediction"],
                          "logits": r["int4_logits"]})
    return cases


def build_bundle(out: Path | str, *, training_root: Path | str = TRAINING_ROOT, prompts: Path | str = PROMPTS,
                 bundle_id: str = DEFAULT_BUNDLE_ID) -> Path:
    """Write the bundle to ``out`` (must not exist) atomically and return the verified path."""
    out = Path(out).expanduser()
    root = Path(training_root).expanduser()
    run = root / "train-001"
    sources = {
        "model.onnx": run / "export-001/int4/model.onnx",
        "model.onnx.data": run / "export-001/int4/model.onnx.data",
        "tokenizer.json": run / "reference/tokenizer.json",
        "tokenizer_config.json": run / "reference/tokenizer_config.json",
        "config.json": run / "reference/config.json",
    }
    contract = json.loads((run / "contract.json").read_bytes())
    policies = {}
    for family in FAMILIES:
        path = Path(prompts) / f"offline_onejev_{family}.txt"
        if _sha(path) != contract["policy_sha256"][family]:
            raise ValueError(f"{family} policy differs from the frozen training policy")
        sources[f"policy/{family}.txt"] = path
        policies[family] = f"policy/{family}.txt"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    rows = [json.loads(line) for line in (root / "assessment/v2/results.jsonl").read_text().splitlines()]
    if len(rows) != 194:
        raise ValueError("the frozen v2 assessment must hold its 194 INT4 calls")
    for r in rows:
        if r["native_input"]["tokens"] > MAX_WINDOW_TOKENS:
            raise ValueError("a frozen assessment input exceeds the frozen window")
    provenance_paths = {
        "download.json": run / "export-001/download.json", "quantized.json": run / "export-001/quantized.json",
        "recipe.json": run / "export-001/int4/recipe.json", "trained.json": run / "trained.json",
        "contract.json": run / "contract.json", "assessment-v2-results.jsonl": root / "assessment/v2/results.jsonl",
        "training-source.json": run / "training-source.json"}
    # Provenance is verified against the producers' own records, not only self-hashed: the native
    # snapshot must still match download.json, and every copied file must be the exact file those
    # records name (INT4 graph/shard by quantized.json, tokenizer/config by the native manifest).
    export = run / "export-001"
    download = validate_native_manifest(export)
    quantized = json.loads(provenance_paths["quantized.json"].read_bytes())
    for name in ("model.onnx", "model.onnx.data"):
        record = quantized["files"][name]
        if sources[name].stat().st_size != record["bytes"] or _sha(sources[name]) != record["sha256"]:
            raise ValueError(f"{name} is not the quantized artifact recorded in quantized.json")
    for name in ("tokenizer.json", "tokenizer_config.json", "config.json"):
        record = download["files"][name]
        if sources[name].stat().st_size != record["bytes"] or _sha(sources[name]) != record["sha256"]:
            raise ValueError(f"{name} is not the native file recorded in download.json")
    if quantized["complete_bundle_bytes"] != sum(quantized["files"][n]["bytes"] for n in quantized["files"]):
        raise ValueError("quantized.json bundle bytes disagree with its files")
    if quantized["source"]["sha256"] != download["files"]["onnx/model.onnx"]["sha256"]:
        raise ValueError("the INT4 graph was not quantized from the recorded native export")
    tmp = out.with_name(out.name + f".tmp-{os.getpid()}")
    tmp.mkdir(parents=True)
    try:
        files = {}
        for name, src in sources.items():
            dest = tmp / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            files[name] = {"bytes": dest.stat().st_size, "sha256": _sha(dest)}
        manifest = {
            "schema": MANIFEST_SCHEMA, "bundle_id": bundle_id, "renderer": RENDERER,
            "max_window_tokens": MAX_WINDOW_TOKENS, "weight_budget_bytes": WEIGHT_BUDGET_BYTES,
            "graph": "model.onnx", "weights": ["model.onnx.data"], "tokenizer": "tokenizer.json",
            "tokenizer_config": "tokenizer_config.json", "config": "config.json",
            "families": {f: {"labels": list(s.labels), "state_key": s.state_key, "policy": policies[f]}
                         for f, s in FAMILIES.items()},
            "files": dict(sorted(files.items())),
            "selftest": select_selftest(rows),
            "provenance": {
                "model": download["repo"], "revision": download["revision"],
                "native_weights_sha256": download["files"]["model.safetensors"]["sha256"],
                "source_files_sha256": {name: _sha(p) for name, p in sorted(provenance_paths.items())},
                "source_int4_sha256": {n: _sha(sources[n]) for n in ("model.onnx", "model.onnx.data")},
                "frozen_policy_sha256": contract["policy_sha256"],
                "producer_sha256": {"suite/system1_package.py": _sha(Path(__file__)),
                                    "cria/system1.py": _sha(Path(system1.__file__))},
                "not_human_gold": "assistant-reviewed labels; synthetic challenge plus exposed training replay",
            },
        }
        (tmp / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        system1.verify_bundle(tmp)
        os.rename(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, default=TRAINING_ROOT)
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    args = parser.parse_args()
    out = build_bundle(args.out, training_root=args.training_root, bundle_id=args.bundle_id)
    print(json.dumps({"bundle": str(out), "manifest_sha256": _sha(out / MANIFEST_NAME)}))


if __name__ == "__main__":
    main()
