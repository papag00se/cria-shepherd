"""Producer: copy a GLiClass v2 INT4 export into a standalone System 1 bundle.

Reads the training artifacts ONCE, at build time, and writes ``<out>`` containing what ``cria.system1`` loads
— graph, external weights, tokenizer, native config, the policy files — and ``selftest.json``, cases taken
from the INT4 assessment calls (token-id digest, label and logits), which the runtime replays at startup.
The bundle has no path or symlink into the training tree.

    python -m suite.system1_package --out ~/.cria/models/system1/expanded-v2
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from cria import system1
from cria.system1 import FAMILIES, SELFTEST_FILE, policy_file
from suite.system1_paths import TRAINING_ROOT as NATIVE_TRAINING_ROOT

TRAINING_ROOT = Path("~/.cria/training/gliclass-v4-edge-expanded-v2").expanduser()
REFERENCE = NATIVE_TRAINING_ROOT / "reference"
PROMPTS = Path(__file__).resolve().parent.parent / "cria" / "prompts"


def select_selftest(rows: list[dict]) -> list[dict]:
    """Per family: the shortest, the longest, and the shortest non-ASCII INT4 assessment call."""
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


def build_bundle(out: Path | str, *, training_root: Path | str = TRAINING_ROOT, prompts: Path | str = PROMPTS) -> Path:
    """Write the bundle to ``out`` (must not exist) atomically and return it."""
    out = Path(out).expanduser()
    root = Path(training_root).expanduser()
    run = root / "train-001"
    reference = REFERENCE if root == TRAINING_ROOT else run / "reference"
    sources = {
        "model.onnx": run / "export-001/int4/model.onnx",
        "model.onnx.data": run / "export-001/int4/model.onnx.data",
        "tokenizer.json": reference / "tokenizer.json",
        "tokenizer_config.json": reference / "tokenizer_config.json",
        "config.json": reference / "config.json",
    }
    for family in FAMILIES:
        sources[policy_file(family)] = Path(prompts) / f"offline_onejev_{family}.txt"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    rows = [json.loads(line) for line in (root / "assessment/v2/results.jsonl").read_text().splitlines()]
    tmp = out.with_name(out.name + f".tmp-{os.getpid()}")
    tmp.mkdir(parents=True)
    try:
        for name, src in sources.items():
            dest = tmp / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        (tmp / SELFTEST_FILE).write_text(json.dumps(select_selftest(rows), indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8")
        os.rename(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, default=TRAINING_ROOT)
    args = parser.parse_args()
    print(build_bundle(args.out, training_root=args.training_root))


if __name__ == "__main__":
    main()
