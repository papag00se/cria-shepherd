"""System 1 runtime edges not reached by the bundle/judgment tests: the process-wide bounded arena (one budget per ORT module, a refused
request says which budget the process already runs under), constructor argument refusals, an unreadable model output, the record of a
failed call when the tokenizer itself is what failed, and a capture that could not be written. ONNX/tokenizer are the module-boundary fakes of
`test_misc_runtime_system1`; the real-engine check lives in the sibling `..._cov4_system1_real_onnx` test."""
import json
from pathlib import Path

import pytest

from cria import callcapture, system1
from cria.system1 import System1BundleError, System1Runtime
from test_misc_runtime_system1 import eng, make_bundle, rlog_for  # noqa: F401


class FakeOrt:
    """The five names `_register_arena` touches; records what it was asked to allocate."""
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail
        self.OrtAllocatorType = type("T", (), {"ORT_ARENA_ALLOCATOR": 7})
        self.OrtMemType = type("M", (), {"DEFAULT": 0})

    def OrtMemoryInfo(self, *args):
        return ("info",) + args

    def OrtArenaCfg(self, cfg):
        return cfg

    def create_and_register_allocator(self, info, cfg):
        if self.fail:
            raise self.fail
        self.calls.append((info, cfg))


def test_the_bounded_arena_is_registered_once_per_module_and_a_second_budget_is_refused():
    """ORT's allocator is process-global: the first runtime fixes the ceiling (exactly-as-requested extension, so max_mem is real), the same
    budget is a no-op, a different one is refused naming the budget in force, and a failed registration leaves nothing recorded."""
    ort = FakeOrt()
    system1._register_arena(ort, 2 * 1024**3)
    system1._register_arena(ort, 2 * 1024**3)
    (info, cfg), = ort.calls
    assert info == ("info", "Cpu", 7, 0, 0)
    assert cfg["max_mem"] == 2 * 1024**3 and cfg["arena_extend_strategy"] == 1
    with pytest.raises(System1BundleError, match=f"already runs System 1 under a {2 * 1024**3}-byte memory budget, not {3 * 1024**3}"):
        system1._register_arena(ort, 3 * 1024**3)
    broken = FakeOrt(fail=RuntimeError("allocator exists"))
    with pytest.raises(System1BundleError, match="cannot bound the System 1 CPU memory arena: allocator exists"):
        system1._register_arena(broken, 2 * 1024**3)
    assert broken not in system1._arenas and len(ort.calls) == 1


@pytest.mark.parametrize("kw", [{"threads": 0}, {"threads": True}, {"threads": "6"}, {"memory_budget_bytes": 1024**3 - 1},
                                {"memory_budget_bytes": True}, {"memory_budget_bytes": 4e9}])
def test_a_runtime_refuses_a_nonsense_thread_count_or_memory_budget_before_touching_the_bundle(tmp_path, kw):
    """No bundle path exists here: the argument refusal must come first (a bool is not a count)."""
    with pytest.raises(System1BundleError, match="threads must be a positive integer|memory_budget_bytes must be an integer"):
        System1Runtime(tmp_path / "no-such-bundle", **kw)


def test_a_prepared_input_renders_the_native_record_the_frozen_assessments_store(eng, tmp_path):  # noqa: F811
    """labels, rendered text, state, policy, token count, and ids with an all-zero token_type_ids and all-one attention_mask of that length."""
    rt = System1Runtime(make_bundle(tmp_path / "b", eng))
    prepared = rt.prepare("dictation", {"public_directive": "run it"})
    record = prepared.native_input()
    n = len(prepared.input_ids)
    assert record["tokens"] == n == prepared.token_count and record["state"] == {"public_directive": "run it"}
    assert record["native_inputs"] == {"input_ids": [list(prepared.input_ids)], "token_type_ids": [[0] * n], "attention_mask": [[1] * n]}
    assert record["labels"] == list(system1.FAMILIES["dictation"].labels) and record["rendered_input"] == prepared.rendered_input and record["policy"] == prepared.policy


def test_an_unreadable_model_output_and_a_tokenizer_that_fails_are_recorded_with_what_exists(eng, tmp_path):  # noqa: F811
    """Logits that are not numbers: typed 'unreadable model output', recorded with the full input. A tokenizer that failed at prepare time is
    recorded with its ids ABSENT (it just failed; they are not re-derived). With no log the same failure is raised and nothing is written."""
    calls, rlog = tmp_path / "calls", rlog_for(tmp_path.name)
    rt = System1Runtime(make_bundle(tmp_path / "b", eng), capture_dir=calls)
    state = {"public_directive": "run it"}
    eng.logits = [["a", "b"]]
    with pytest.raises(system1.System1RuntimeError, match="unreadable model output"):
        rt.judge("dictation", state, rlog=rlog)
    first = rlog.kinds("system1.error")[-1]
    assert first["error"] == "System1RuntimeError" and first["capture"] and first["input_sha256"]
    eng.logits = [[2.0, -1.0]]
    eng.tok.__class__.encode = lambda self, text: (_ for _ in ()).throw(ValueError("bad utf-8"))
    with pytest.raises(system1.System1RuntimeError, match="tokenizer failed: bad utf-8"):
        rt.judge("dictation", state, rlog=rlog)
    record = json.loads(Path(rlog.kinds("system1.error")[-1]["capture"]).read_text())
    assert record["request"]["input_ids"] == [] and record["request"]["token_count"] == 0 and "tokenizer failed" in record["response"]["message"]
    before = len(rlog.events)
    with pytest.raises(system1.System1RuntimeError, match="tokenizer failed"):
        rt.judge("dictation", state)
    assert len(rlog.events) == before and len(list((calls / callcapture.session_dirname(rlog.session) / "system1").iterdir())) == 2


def test_a_capture_the_store_could_not_write_is_reported_not_hidden(eng, tmp_path, monkeypatch):  # noqa: F811
    """capture_native returning None (unwritable calls dir) yields no path and a `system1.capture_failed` warning; without a log or a calls dir it is silent."""
    rlog = rlog_for(tmp_path.name)
    rt = System1Runtime(make_bundle(tmp_path / "b", eng), capture_dir=tmp_path / "calls")
    monkeypatch.setattr(callcapture, "capture_native", lambda *a, **k: None)
    assert rt._capture_call("dictation", {}, {}, rlog) is None
    assert rlog.kinds("system1.capture_failed") == [{"level": "warn", "family": "dictation"}]
    assert rt.judge_detailed("dictation", {"public_directive": "x"}, rlog=rlog).capture_path is None
    assert len(rlog.kinds("system1.capture_failed")) == 2
    assert rt._capture_call("dictation", {}, {}, None) is None
    bare = System1Runtime(make_bundle(tmp_path / "c", eng))
    assert bare._capture_call("dictation", {}, {}, rlog) is None and len(rlog.kinds("system1.capture_failed")) == 2
