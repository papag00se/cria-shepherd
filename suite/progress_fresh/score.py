"""Score a progress model's native reference on the fresh author-labelled set (RTX 3080 only).

    CUDA_VISIBLE_DEVICES=<3080 uuid> python -m suite.progress_fresh.score [--split test] [--model DIR] [--out FILE]

The model is a GLiClass reference directory (default: the final progress-v1 fit). Rows are rendered and encoded by
``suite.progress_loto`` exactly as in training. Prints accuracy, macro-F1, per-label recall and the confusion matrix.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from suite.progress_dataset import LABELS, render_state
from suite.progress_fresh.build import OUT
from suite.progress_loto import DATA, common_setup, encode, f1_report

GPU_3080 = "GPU-393d4998-707c-0ef0-a514-761015477256"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--model", type=Path, default=DATA / "final" / "reference")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != GPU_3080:
        raise SystemExit("only the RTX 3080 may be visible (CUDA_VISIBLE_DEVICES)")
    import torch
    if torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise SystemExit("wrong GPU")
    from suite.gliclass_probe import load_native
    model, pipe, _ = load_native(str(args.model), "cuda")
    _contract, hashes = common_setup(args)
    rows = [json.loads(l) for l in (OUT / f"{args.split}.jsonl").read_text().splitlines()]
    preds = []
    with torch.no_grad():
        for r in rows:
            row = {**r, "family": "progress", "complete_input": render_state(r["requirement"], r["evidence"])}
            inputs = encode(pipe, row, hashes, tuple(LABELS))
            logits = model(**inputs, max_num_classes=len(LABELS)).logits[0, :len(LABELS)].float().cpu()
            preds.append({"id": r["id"], "task": r["task"], "label": r["label"],
                          "prediction": LABELS[int(logits.argmax())], "logits": logits.tolist(),
                          "tokens": int(inputs["input_ids"].shape[1])})
    rep = f1_report([p["label"] for p in preds], [p["prediction"] for p in preds])
    rep["recall"] = {l: rep["confusion"][i][i] / max(1, sum(rep["confusion"][i])) for i, l in enumerate(LABELS)}
    rep.update(model=str(args.model), split=args.split, labels=list(LABELS))
    print(json.dumps(rep, indent=2))
    if args.out:
        args.out.write_text(json.dumps({"report": rep, "predictions": preds}, indent=1) + "\n")


if __name__ == "__main__":
    main()
