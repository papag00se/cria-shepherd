"""System 1 (optional CPU classifier) is advisory: every failure is typed and declines. Real runtime, fake ONNX/tokenizer engines."""
import hashlib, json, sys, time, types
from pathlib import Path

import pytest

from cria import callcapture, system1, system1wiring
from cria.system1 import FAMILIES, MAX_WINDOW_TOKENS, System1Error, System1Runtime
from suite import fresh_l5_campaign
from suite.run import collect_capture

DICT = {"public_directive": "run it"}
NOOP, NS = (lambda *a, **k: None), types.SimpleNamespace


class Arr:
    def __init__(self, rows):
        self.rows, self.shape = rows, (len(rows), len(rows[0]) if rows else 0)
    reshape = lambda self, _: [v for r in self.rows for v in r]


@pytest.fixture
def eng(monkeypatch):
    """Mutable fake-engine state: logits to return, an error to raise, extra tokens, what reached the graph."""
    e = NS(logits=[[2.0, -1.0]], fail=None, extra=0, fed=[])

    class Tok:
        from_file = classmethod(lambda cls, path: cls())
        no_truncation = no_padding = NOOP
        token_to_id = lambda self, t: {"<<LABEL>>": 128001, "<<SEP>>": 128002}.get(t)
        encode = lambda self, text: NS(ids=[1] + [ord(c) % 99 for c in text] + [2] + [7] * e.extra)

    class Session:
        __init__ = NOOP
        get_providers = lambda self: ["CPUExecutionProvider"]
        get_inputs = lambda self: [NS(name=n) for n in ("input_ids", "attention_mask")]

        def run(self, outputs, feed, run_options=None):
            e.fed.append(feed)
            if e.fail:
                raise e.fail
            return [Arr(e.logits)]
    ort = NS(SessionOptions=lambda: NS(add_session_config_entry=NOOP), InferenceSession=Session, RunOptions=lambda: NS(add_run_config_entry=NOOP))
    np = NS(int64=int, asarray=lambda v, dtype=None: v if isinstance(v, Arr) else Arr(v), ones_like=lambda a: Arr([[1] * len(r) for r in a.rows]))
    monkeypatch.setattr(system1, "_register_arena", NOOP)
    monkeypatch.setattr(system1, "_import", lambda name: {"onnxruntime": ort, "tokenizers": NS(Tokenizer=Tok), "numpy": np}[name])
    e.tok, e.ort = Tok(), ort
    return e


def make_bundle(root, eng, mutate=None):
    """A manifest-valid bundle on disk (fake weights); its self-test is produced with the fake engines."""
    (root / "policy").mkdir(parents=True)
    blobs = {"model.onnx": b"graph", "model.onnx.data": b"w" * 70, "tokenizer.json": b"{}", "tokenizer_config.json": b"{}",
             "config.json": json.dumps({"architecture_type": "uni-encoder", "prompt_first": True, "class_token_index": 128001,
                                        "text_token_index": 128002}).encode()}
    selftest = []
    for fam, spec in FAMILIES.items():
        blobs[f"policy/{fam}.txt"] = (Path(system1.__file__).parent / "prompts" / f"offline_onejev_{fam}.txt").read_bytes()
        ids = eng.tok.encode(system1.render_input(spec.labels, blobs[f"policy/{fam}.txt"].decode(), system1.render_state({spec.state_key: "s"}))).ids
        selftest.append({"id": fam, "family": fam, "state": {spec.state_key: "s"}, "tokens": len(ids), "label": spec.labels[0],
                         "input_ids_sha256": system1._ids_sha(ids), "logits": [2.0, -1.0]})
    for name, data in blobs.items():
        (root / name).write_bytes(data)
    (root / "manifest.json").write_text(json.dumps({
        "schema": system1.MANIFEST_SCHEMA, "bundle_id": "fake", "renderer": system1.RENDERER, "selftest": selftest,
        "max_window_tokens": MAX_WINDOW_TOKENS, "weight_budget_bytes": system1.WEIGHT_BUDGET_BYTES, "graph": "model.onnx",
        "weights": ["model.onnx.data"], "tokenizer": "tokenizer.json", "tokenizer_config": "tokenizer_config.json", "config": "config.json",
        "families": {f: {"labels": list(s.labels), "state_key": s.state_key, "policy": f"policy/{f}.txt"} for f, s in FAMILIES.items()},
        "files": {n: {"bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in blobs.items()}}))
    if mutate:
        mutate(root)
    return root


def rlog_for(session):
    events = []
    return NS(session=session, turn="t1", events=events, emit=lambda kind, **kw: events.append((kind, kw)),
              kinds=lambda kind: [kw for k, kw in events if k == kind])


@pytest.mark.parametrize("fail", ["window+1", "nan", "shape", "tie", "engine"])
def test_a_failed_judgment_is_typed_never_clipped_and_the_guard_declines(eng, tmp_path, fail):
    """No answer is no answer: typed error, an over-window input never reaches the graph, the guard declines, the runtime lives on."""
    rt = System1Runtime(make_bundle(tmp_path / "b", eng), capture_dir=tmp_path / "calls")
    eng.fed.clear()  # construction ran the self-test through the graph
    eng.extra = MAX_WINDOW_TOKENS - len(rt.prepare("dictation", DICT).input_ids) + 1 if fail == "window+1" else 0
    eng.logits = {"nan": [[float("nan"), 1.0]], "shape": [[1.0, 2.0, 3.0]], "tie": [[0.5, 0.5]]}.get(fail, eng.logits)
    eng.fail = RuntimeError("allocator: smaller than requested bytes") if fail == "engine" else None
    rlog = rlog_for(tmp_path.name)
    with pytest.raises(system1wiring.Unjudged) as caught:
        system1wiring.classify(rt, "dictation", "run it", rlog, seat="vet")
    assert isinstance(caught.value.__cause__, System1Error) and len(rlog.kinds("system1.declined")) == 1
    assert Path(rlog.kinds("system1.error")[0]["capture"]).is_file() and bool(eng.fed) is (fail != "window+1")
    eng.extra, eng.fail, eng.logits = 0, None, [[2.0, -1.0]]
    assert rt.judge("dictation", DICT) == "DESCRIBES"


def test_the_exact_window_fits_decision_is_argmax_in_label_order_and_only_the_trained_key_is_admitted(eng, tmp_path):
    """The longest whole input is judged untruncated; classes map to the trained labels; a wrong key never reaches inference."""
    rt = System1Runtime(make_bundle(tmp_path / "b", eng))
    eng.extra = MAX_WINDOW_TOKENS - len(rt.prepare("dictation", DICT).input_ids)
    assert rt.judge_detailed("dictation", DICT).token_count == MAX_WINDOW_TOKENS
    eng.extra, brief, fed = 0, {"candidate_briefing": "x"}, len(eng.fed)
    for logits, want in (([[4.0, -3.0]], ("RETROSPECTIVE", "DESCRIBES")), ([[-3.0, 4.0]], ("PLAN", "DICTATES"))):
        eng.logits = logits
        assert (rt.judge("retrospective", brief), rt.judge("dictation", DICT)) == want
    for family, state in (("retrospective", DICT), ("dictation", {"public_directive": "  \n"}), ("dictation", {**DICT, "x": "y"})):
        with pytest.raises(system1.System1StateError):
            rt.judge(family, state)
    assert len(eng.fed) == fed + 4


@pytest.mark.parametrize("mutate", [lambda r: (r / "model.onnx.data").write_bytes(b"w" * 69 + b"x"), lambda r: (r / "extra.bin").write_bytes(b"x")],
                         ids=["flipped-byte", "unlisted-file"])
def test_a_tampered_bundle_stops_the_service_before_the_graph_loads(eng, tmp_path, mutate):
    """Verification precedes loading; with [system1] enabled a bad bundle is a StartupError, never a silent fallback."""
    eng.ort.InferenceSession = lambda *a, **k: pytest.fail("graph loaded from an unverified bundle")
    with pytest.raises(system1wiring.StartupError):
        system1wiring.build(NS(enabled=True, threads=1, bundle_path=make_bundle(tmp_path / "b", eng, mutate)))


def test_classifier_records_are_complete_and_invisible_to_the_suites_llm_evidence(eng, tmp_path):
    """A classifier record that looked like an upstream call would inflate call counts and invalidate every capture-on row."""
    calls, rlog = tmp_path / "calls", rlog_for(tmp_path.name)  # the capture counter is process-wide per session
    rt = System1Runtime(make_bundle(tmp_path / "b", eng), capture_dir=calls)
    for phase in ("coder", "satisfaction"):
        path = callcapture.capture({"messages": [{"role": "user", "content": phase}]}, rlog, calls_dir=calls, phase=phase)
        callcapture.capture_response(path, {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}, rlog)
        j = rt.judge_detailed("retrospective", {"candidate_briefing": "full text"}, rlog=rlog)
    session = calls / callcapture.session_dirname(rlog.session)
    record = json.loads(Path(j.capture_path).read_text())
    assert record["request"]["rendered_input"] == j.rendered_input and record["request"]["input_ids"] == list(j.input_ids)
    assert "messages" not in record["request"] and len(list((session / "system1").iterdir())) == 2
    row = {"capture_dirs": [str(session)], "capture_dir": str(session), "calls": 2, "phases": {"coder": 1, "satisfaction": 1},
           "started": time.time() - 30, "wall_seconds": 3600}
    assert collect_capture([session])["calls"] == 2 and fresh_l5_campaign._valid_capture_evidence(row) is True
