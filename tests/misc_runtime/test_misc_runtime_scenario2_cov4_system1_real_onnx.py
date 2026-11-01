"""System 1 against the REAL optional engines, when they exist on this machine: a hand-encoded ONNX graph (two int64 inputs -> logits [1,2], pure
protobuf wire bytes written here, no `onnx` package) and a WordLevel tokenizer are bundled, verified, loaded by `System1Runtime` under the real
bounded arena, and judged. The fakes in the sibling tests pin cria's logic; this one pins the ONNX Runtime / tokenizers API it assumes (arena
config keys, run options, input names, token ids). Skipped unless the `system1-v2` environment's interpreter has onnxruntime+tokenizers+numpy.
Runs in that interpreter as a subprocess; cria itself is stdlib-only and is imported from this checkout."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ENV_PYTHON = Path.home() / ".local/share/cria/envs/system1-v2/bin/python"
REPO = Path(__file__).resolve().parents[2]


def _has_engines():
    if not ENV_PYTHON.is_file():
        return False
    probe = subprocess.run([str(ENV_PYTHON), "-c", "import onnxruntime, tokenizers, numpy"], capture_output=True)
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(not _has_engines(), reason="no system1-v2 environment with onnxruntime/tokenizers/numpy")

SCRIPT = textwrap.dedent('''
    import hashlib, json, struct, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from tokenizers import Tokenizer, models, pre_tokenizers
    from cria import system1

    root = Path(sys.argv[2]); (root / "policy").mkdir(parents=True)

    def varint(n):
        out = b""
        while True:
            b, n = n & 0x7F, n >> 7
            out += bytes([b | (0x80 if n else 0)])
            if not n: return out
    def field(num, wire, payload): return varint(num << 3 | wire) + payload
    def ldelim(num, data): return field(num, 2, varint(len(data)) + data)
    def vint(num, n): return field(num, 0, varint(n))
    def node(op, ins, outs, attrs=b""): return b"".join(ldelim(1, i.encode()) for i in ins) + b"".join(ldelim(2, o.encode()) for o in outs) + ldelim(4, op.encode()) + attrs
    def attr(name, **kw):
        if "i" in kw: return ldelim(5, ldelim(1, name.encode()) + vint(3, kw["i"]) + vint(20, 2))
        return ldelim(5, ldelim(1, name.encode()) + b"".join(vint(8, v) for v in kw["ints"]) + vint(20, 7))
    def info(name, elem, dims):
        shape = b"".join(ldelim(1, vint(1, d) if isinstance(d, int) else ldelim(2, d.encode())) for d in dims)
        return ldelim(1, name.encode()) + ldelim(2, ldelim(1, vint(1, elem) + ldelim(2, shape)))
    W = ldelim(5, vint(1, 1) + vint(1, 2) + vint(2, 1) + ldelim(4, struct.pack("<2f", 0.001, -0.001)) + ldelim(8, b"W"))
    nodes = [node("Cast", ["input_ids"], ["f_ids"], attr("to", i=1)), node("Cast", ["attention_mask"], ["f_mask"], attr("to", i=1)),
             node("ReduceSum", ["f_ids"], ["s_ids"], attr("axes", ints=[1]) + attr("keepdims", i=1)),
             node("ReduceSum", ["f_mask"], ["s_mask"], attr("axes", ints=[1]) + attr("keepdims", i=1)),
             node("Add", ["s_ids", "s_mask"], ["x"]), node("MatMul", ["x", "W"], ["logits"])]
    graph = b"".join(ldelim(1, n) for n in nodes) + ldelim(2, b"g") + W + ldelim(11, info("input_ids", 7, [1, "n"])) \\
        + ldelim(11, info("attention_mask", 7, [1, "n"])) + ldelim(12, info("logits", 1, [1, 2]))
    model = vint(1, 7) + ldelim(8, vint(2, 11)) + ldelim(7, graph)

    words = {"[UNK]": 0, "<<LABEL>>": 128001, "<<SEP>>": 128002}
    tok = Tokenizer(models.WordLevel(words, unk_token="[UNK]")); tok.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    blobs = {"model.onnx": model, "model.onnx.data": b"w" * 70, "tokenizer.json": tok.to_str().encode(), "tokenizer_config.json": b"{}",
             "config.json": json.dumps({"architecture_type": "uni-encoder", "prompt_first": True, "class_token_index": 128001, "text_token_index": 128002}).encode()}
    selftest = []
    for fam, spec in system1.FAMILIES.items():
        blobs[f"policy/{fam}.txt"] = (Path(system1.__file__).parent / "prompts" / f"offline_onejev_{fam}.txt").read_bytes()
        ids = tok.encode(system1.render_input(spec.labels, blobs[f"policy/{fam}.txt"].decode(), system1.render_state({spec.state_key: "s"}))).ids
        x = (sum(ids) + len(ids)) * 0.001
        selftest.append({"id": fam, "family": fam, "state": {spec.state_key: "s"}, "tokens": len(ids), "label": spec.labels[0],
                         "input_ids_sha256": system1._ids_sha(ids), "logits": [x, -x]})
    for name, data in blobs.items(): (root / name).write_bytes(data)
    (root / "manifest.json").write_text(json.dumps({
        "schema": system1.MANIFEST_SCHEMA, "bundle_id": "real-onnx", "renderer": system1.RENDERER, "selftest": selftest,
        "max_window_tokens": system1.MAX_WINDOW_TOKENS, "weight_budget_bytes": system1.WEIGHT_BUDGET_BYTES, "graph": "model.onnx",
        "weights": ["model.onnx.data"], "tokenizer": "tokenizer.json", "tokenizer_config": "tokenizer_config.json", "config": "config.json",
        "families": {f: {"labels": list(s.labels), "state_key": s.state_key, "policy": f"policy/{f}.txt"} for f, s in system1.FAMILIES.items()},
        "files": {n: {"bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in blobs.items()}}))

    rt = system1.System1Runtime(root, threads=1, memory_budget_bytes=2 * 1024**3)
    j = rt.judge_detailed("dictation", {"public_directive": "run it"})
    again = system1.System1Runtime(root, threads=1, memory_budget_bytes=2 * 1024**3)       # same budget: the arena is shared, not re-registered
    try:
        system1.System1Runtime(root, threads=1, memory_budget_bytes=3 * 1024**3); other = "accepted"
    except system1.System1BundleError as exc:
        other = str(exc)
    print(json.dumps({"label": j.label, "logits": list(j.logits), "tokens": j.token_count, "ids": list(j.input_ids), "again": again.bundle_id, "other": other,
                      "spin": rt._session.get_session_options().get_session_config_entry("session.intra_op.allow_spinning")}))
''')


def test_a_hand_built_onnx_graph_is_verified_loaded_under_the_bounded_arena_and_judged(tmp_path):
    """The graph sums its inputs, so the expected logits are computable from the token ids alone: x=(sum(ids)+len(ids))*0.001 for class 0 and -x
    for class 1 — the label is class 0's, the logits are exact to float32, the whole input is tokenised untruncated (UNK except the two
    special tokens), a second runtime at the same budget loads, and one asking for a different budget is refused naming the first."""
    run = subprocess.run([str(ENV_PYTHON), "-c", SCRIPT, str(REPO), str(tmp_path / "bundle")], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout.strip().splitlines()[-1])
    x = (sum(out["ids"]) + len(out["ids"])) * 0.001
    assert out["label"] == "DESCRIBES" and out["tokens"] == len(out["ids"]) > 100
    assert out["logits"] == pytest.approx([x, -x], abs=2e-3) and set(out["ids"]) <= {0, 128001, 128002}
    assert out["spin"] == "0"       # idle intra-op workers sleep: spinning burned 2.3-2.9x the CPU of the same judgment (bit-identical logits)
    assert out["again"] == "real-onnx" and "already runs System 1 under a 2147483648-byte memory budget, not 3221225472" in out["other"]
