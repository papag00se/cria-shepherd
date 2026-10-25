"""System 1 runtime: bundle verification, the frozen render/tokenise/decide contract and capture.

Run against FAKE ``onnxruntime`` / ``tokenizers`` / ``numpy`` modules so the stdlib suite exercises the
real runtime code. The last class runs the real bundle through the real engines and skips when
either is absent (it needs ``~/.cria/models/system1/expanded-v2`` and the System 1 environment).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

from cria import callcapture, system1
from cria.system1 import (FAMILIES, MAX_WINDOW_TOKENS, System1BundleError, System1Error, System1NoFit,
                          System1NonFinite, System1Runtime, System1RuntimeError, System1StateError)

REPO = Path(__file__).resolve().parent.parent
PROMPTS = REPO / "cria" / "prompts"
CLS, LABEL_ID, SEP_ID = 1, 128001, 128002


# ---- fake engines ----------------------------------------------------------------------------

class FakeArray:
    def __init__(self, rows):
        self.rows = rows
        self.shape = (len(rows), len(rows[0]) if rows else 0)

    def reshape(self, _):
        return [v for row in self.rows for v in row]


class FakeNumpy:
    int64 = int

    @staticmethod
    def asarray(value, dtype=None):
        return value if isinstance(value, FakeArray) else FakeArray(value)

    @staticmethod
    def ones_like(arr):
        return FakeArray([[1] * len(row) for row in arr.rows])


class FakeTokenizer:
    """Deterministic: one id per character after CLS, closed by SEP; <<LABEL>>/<<SEP>> are ids."""
    calls: list = []
    extra_tokens = 0
    flags: dict = {}

    @classmethod
    def from_file(cls, path):
        inst = cls()
        inst.path = path
        cls.flags = {"no_truncation": False, "no_padding": False}
        return inst

    def no_truncation(self):
        type(self).flags["no_truncation"] = True

    def no_padding(self):
        type(self).flags["no_padding"] = True

    def token_to_id(self, token):
        return {"<<LABEL>>": LABEL_ID, "<<SEP>>": SEP_ID}.get(token)

    def encode(self, text):
        type(self).calls.append(text)
        ids = [CLS] + [ord(c) % 1000 + 10 for c in text] + [2]
        return types.SimpleNamespace(ids=ids + [7] * type(self).extra_tokens)


class FakeSession:
    behavior = staticmethod(lambda ids: [[2.0, -1.0]])
    running = 0
    peak = 0
    lock = threading.Lock()
    providers = ["CPUExecutionProvider"]
    inputs = ["input_ids", "attention_mask"]
    seen_feed: list = []
    seen_run_options: list = []
    registrations: list = []
    session_entries: list = []

    def __init__(self, path, sess_options=None, providers=None):
        self.options, self.requested = sess_options, providers
        type(self).session_entries.append(dict(sess_options.entries))

    def get_providers(self):
        return type(self).providers

    def get_inputs(self):
        return [types.SimpleNamespace(name=n) for n in type(self).inputs]

    def run(self, outputs, feed, run_options=None):
        cls = type(self)
        cls.seen_feed.append((outputs, feed))
        cls.seen_run_options.append(run_options)
        with cls.lock:
            cls.running += 1
            cls.peak = max(cls.peak, cls.running)
        try:
            threading.Event().wait(0.01)
            result = cls.behavior(feed["input_ids"].rows[0])
            if isinstance(result, Exception):
                raise result
            return [FakeArray(result) if isinstance(result, list) else result]
        finally:
            with cls.lock:
                cls.running -= 1


@pytest.fixture(autouse=True)
def fake_engines(monkeypatch):
    ort = types.ModuleType("onnxruntime")
    def options():
        entries = {}
        return types.SimpleNamespace(intra_op_num_threads=None, inter_op_num_threads=None, entries=entries,
                                     add_session_config_entry=entries.__setitem__)
    ort.SessionOptions = options
    ort.OrtAllocatorType = types.SimpleNamespace(ORT_ARENA_ALLOCATOR="arena")
    ort.OrtMemType = types.SimpleNamespace(DEFAULT="default")
    ort.OrtMemoryInfo = lambda *a: ("meminfo", *a)
    ort.OrtArenaCfg = lambda cfg: ("arenacfg", dict(cfg))
    ort.create_and_register_allocator = lambda info, cfg: FakeSession.registrations.append((info, cfg))

    class RunOptions:
        def __init__(self):
            self.entries = {}

        def add_run_config_entry(self, key, value):
            self.entries[key] = value
    ort.RunOptions = RunOptions
    ort.InferenceSession = FakeSession
    tok = types.ModuleType("tokenizers")
    tok.Tokenizer = FakeTokenizer
    np = types.ModuleType("numpy")
    for name in ("asarray", "ones_like", "int64"):
        setattr(np, name, getattr(FakeNumpy, name))
    for name, module in (("onnxruntime", ort), ("tokenizers", tok), ("numpy", np)):
        monkeypatch.setitem(sys.modules, name, module)
    FakeTokenizer.calls, FakeTokenizer.extra_tokens = [], 0
    FakeSession.behavior = staticmethod(lambda ids: [[2.0, -1.0]])
    FakeSession.running = FakeSession.peak = 0
    FakeSession.providers = ["CPUExecutionProvider"]
    FakeSession.inputs = ["input_ids", "attention_mask"]
    FakeSession.seen_feed = []
    FakeSession.seen_run_options = []
    FakeSession.registrations = []
    FakeSession.session_entries = []


# ---- a real bundle on disk, fake weights -----------------------------------------------------

NATIVE_CONFIG = {"architecture_type": "uni-encoder", "prompt_first": True,
                 "class_token_index": LABEL_ID, "text_token_index": SEP_ID}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_bundle(root: Path, *, mutate=None, config=None, selftest=True) -> Path:
    """Write a manifest-valid bundle. Its self-test is computed with the fake engines."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "policy").mkdir(exist_ok=True)
    blobs = {"model.onnx": b"graph", "model.onnx.data": b"weights" * 10, "tokenizer.json": b"{}",
             "tokenizer_config.json": b"{}", "config.json": json.dumps(config or NATIVE_CONFIG).encode()}
    for family in FAMILIES:
        blobs[f"policy/{family}.txt"] = (PROMPTS / f"offline_onejev_{family}.txt").read_bytes()
    for name, data in blobs.items():
        (root / name).write_bytes(data)
    manifest = {
        "schema": system1.MANIFEST_SCHEMA, "bundle_id": "fake-bundle", "renderer": system1.RENDERER,
        "max_window_tokens": MAX_WINDOW_TOKENS, "weight_budget_bytes": system1.WEIGHT_BUDGET_BYTES,
        "graph": "model.onnx", "weights": ["model.onnx.data"], "tokenizer": "tokenizer.json",
        "tokenizer_config": "tokenizer_config.json", "config": "config.json",
        "families": {f: {"labels": list(s.labels), "state_key": s.state_key, "policy": f"policy/{f}.txt"}
                     for f, s in FAMILIES.items()},
        "files": {n: {"bytes": len(d), "sha256": _sha(d)} for n, d in blobs.items()},
        "selftest": [],
    }
    if selftest:
        manifest["selftest"] = [selftest_case(f, f"{f} sample text") for f in FAMILIES]
    if mutate:
        mutate(manifest, root)
    (root / system1.MANIFEST_NAME).write_text(json.dumps(manifest))
    return root


def selftest_case(family, text):
    spec = FAMILIES[family]
    policy = (PROMPTS / f"offline_onejev_{family}.txt").read_text()
    rendered = system1.render_input(spec.labels, policy, system1.render_state({spec.state_key: text}))
    ids = FakeTokenizer().encode(rendered).ids
    return {"id": family, "family": family, "state": {spec.state_key: text}, "tokens": len(ids),
            "input_ids_sha256": system1._ids_sha(ids), "label": spec.labels[0], "logits": [2.0, -1.0]}


@pytest.fixture
def bundle(tmp_path):
    return make_bundle(tmp_path / "bundle")


def brief(text="The parser compiles and two tests fail."):
    return {"candidate_briefing": text}


def directive(text="Run the failing test and report."):
    return {"public_directive": text}


class Rlog:
    def __init__(self, session="s1"):
        self.session, self.turn, self.events = session, "t1", []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self, kind):
        return [kw for k, kw in self.events if k == kind]


# ---- import discipline -----------------------------------------------------------------------

def test_importing_the_module_loads_no_third_party_package():
    code = ("import sys; import cria.system1; "
            "bad=[m for m in ('onnxruntime','tokenizers','numpy','torch','transformers') if m in sys.modules]; "
            "print(bad)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_enabled_runtime_without_the_engines_says_so(bundle, monkeypatch):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    with pytest.raises(system1.System1DependencyError):
        System1Runtime(bundle)


# ---- the frozen contract ----------------------------------------------------------------------

class TestRenderingAndDecision:
    def test_input_is_native_prompt_first_with_policy_then_rendered_state(self, bundle):
        rt = System1Runtime(bundle)
        prepared = rt.prepare("retrospective", brief("a\nb"))
        policy = (PROMPTS / "offline_onejev_retrospective.txt").read_text()
        assert prepared.rendered_input == ("<<LABEL>>RETROSPECTIVE<<LABEL>>PLAN<<SEP>>" + policy
                                           + "candidate_briefing: a\nb")
        assert prepared.labels == ("RETROSPECTIVE", "PLAN")
        assert prepared.native_input()["native_inputs"]["token_type_ids"] == [[0] * prepared.token_count]
        assert prepared.native_input()["native_inputs"]["attention_mask"] == [[1] * prepared.token_count]

    def test_dictation_has_its_own_labels_policy_and_key(self, bundle):
        prepared = System1Runtime(bundle).prepare("dictation", directive("do x"))
        assert prepared.rendered_input.startswith("<<LABEL>>DESCRIBES<<LABEL>>DICTATES<<SEP>>")
        assert prepared.rendered_input.endswith("public_directive: do x")

    def test_render_state_equals_the_training_renderer_for_trained_states(self):
        from suite.gliclass_probe import render_state as training
        for state in ({"candidate_briefing": "x\ny: z"}, {"public_directive": "uni ü 漢字\n\n  end "}):
            assert system1.render_state(state) == training(state)

    def test_tokenizer_is_told_never_to_truncate_or_pad(self, bundle):
        System1Runtime(bundle)
        assert FakeTokenizer.flags == {"no_truncation": True, "no_padding": True}

    def test_decision_is_argmax_in_frozen_label_order(self, bundle):
        rt = System1Runtime(bundle)
        FakeSession.behavior = staticmethod(lambda ids: [[-3.0, 4.0]])
        assert rt.judge("retrospective", brief()) == "PLAN"
        assert rt.judge("dictation", directive()) == "DICTATES"
        FakeSession.behavior = staticmethod(lambda ids: [[4.0, -3.0]])
        assert rt.judge("retrospective", brief()) == "RETROSPECTIVE"
        assert rt.judge("dictation", directive()) == "DESCRIBES"

    def test_judgment_is_the_complete_authoritative_record(self, bundle):
        rt = System1Runtime(bundle, threads=3)
        FakeSession.behavior = staticmethod(lambda ids: [[1.0, 1.0 + 2.0]])
        j = rt.judge_detailed("dictation", directive("go"))
        assert j.label == "DICTATES" and j.logits == (1.0, 3.0) and j.token_count == len(j.input_ids)
        assert abs(sum(j.probabilities.values()) - 1) < 1e-12 and j.probabilities["DICTATES"] > 0.88
        assert j.manifest_sha256 == rt.manifest_sha256 and j.bundle_id == "fake-bundle"
        outputs, feed = FakeSession.seen_feed[-1]
        assert outputs == ["logits"] and list(feed["input_ids"].rows[0]) == list(j.input_ids)
        assert feed["attention_mask"].rows == [[1] * j.token_count]

    def test_session_is_cpu_with_the_requested_threads(self, bundle, monkeypatch):
        seen = {}
        original = FakeSession.__init__

        def spy(self, path, sess_options=None, providers=None):
            seen.update(threads=sess_options.intra_op_num_threads, inter=sess_options.inter_op_num_threads,
                        providers=providers)
            original(self, path, sess_options, providers)
        monkeypatch.setattr(FakeSession, "__init__", spy)
        System1Runtime(bundle, threads=4)
        assert seen == {"threads": 4, "inter": 1, "providers": ["CPUExecutionProvider"]}

    def test_a_gpu_provider_is_refused(self, bundle):
        FakeSession.providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        with pytest.raises(System1BundleError, match="CPU only"):
            System1Runtime(bundle)


class TestBoundedMemory:
    """One long input must not be able to take the host down — and must never be clipped to avoid it."""

    def test_the_cpu_arena_is_registered_with_a_hard_exact_ceiling_and_used_by_the_session(self, bundle):
        rt = System1Runtime(bundle)
        ((info, cfg),) = FakeSession.registrations
        assert info == ("meminfo", "Cpu", "arena", 0, "default")
        assert cfg[1]["max_mem"] == system1.ARENA_BUDGET_BYTES == 16 * 1024**3
        assert cfg[1]["arena_extend_strategy"] == 1  # kSameAsRequested: max_mem is the real ceiling
        assert FakeSession.session_entries[-1] == {"session.use_env_allocators": "1"}
        assert rt.memory_budget_bytes == system1.ARENA_BUDGET_BYTES
        assert rt.prepare("dictation", directive()).token_count <= MAX_WINDOW_TOKENS  # the window is untouched

    def test_every_run_shrinks_the_arena_back(self, bundle):
        rt = System1Runtime(bundle)
        rt.judge("dictation", directive())
        assert FakeSession.seen_run_options[-1].entries == {"memory.enable_memory_arena_shrinkage": "cpu:0"}

    def test_registration_is_idempotent_per_process_for_one_budget(self, bundle, tmp_path):
        System1Runtime(bundle)
        System1Runtime(make_bundle(tmp_path / "again"))
        assert len(FakeSession.registrations) == 1

    def test_a_different_budget_cannot_silently_run_under_the_first(self, bundle, tmp_path):
        System1Runtime(bundle)
        with pytest.raises(System1BundleError, match="already runs"):
            System1Runtime(make_bundle(tmp_path / "again"), memory_budget_bytes=2 * 1024**3)

    @pytest.mark.parametrize("bad", [0, -1, 1024, 2.5e9, "16GiB", None])
    def test_an_unusable_budget_is_refused(self, bundle, bad):
        with pytest.raises(System1BundleError, match="memory_budget_bytes"):
            System1Runtime(bundle, memory_budget_bytes=bad)

    def test_an_allocator_refusal_is_a_typed_runtime_error_not_a_crash_and_the_next_call_works(self, bundle):
        rt = System1Runtime(bundle)
        FakeSession.behavior = staticmethod(lambda ids: RuntimeError(
            "Available memory of 4738505984 is smaller than requested bytes of 34359738368"))
        with pytest.raises(System1RuntimeError, match="smaller than requested"):
            rt.judge("retrospective", brief())
        FakeSession.behavior = staticmethod(lambda ids: [[2.0, -1.0]])
        assert rt.judge("retrospective", brief()) == "RETROSPECTIVE"

    def test_a_failed_registration_fails_startup(self, bundle, monkeypatch):
        def refuse(*a):
            raise RuntimeError("no arena")
        monkeypatch.setattr(sys.modules["onnxruntime"], "create_and_register_allocator", refuse)
        with pytest.raises(System1BundleError, match="no arena"):
            System1Runtime(bundle)


class TestStateAdmission:
    @pytest.mark.parametrize("family,state", [
        ("retrospective", {"public_directive": "x"}),            # the other family's key
        ("dictation", {"directive": "x"}),                       # an abbreviated key
        ("retrospective", {"candidate_briefing": "x", "extra": "y"}),
        ("dictation", {}),
        ("dictation", {"public_directive": ""}),
        ("dictation", {"public_directive": "  \n"}),
        ("dictation", {"public_directive": ["x"]}),
        ("dictation", "plain text"),
        ("unknown", {"public_directive": "x"}),
    ])
    def test_anything_but_the_trained_key_set_is_refused(self, bundle, family, state):
        rt = System1Runtime(bundle)
        before = len(FakeSession.seen_feed)
        with pytest.raises(System1StateError):
            rt.judge(family, state)
        assert len(FakeSession.seen_feed) == before  # nothing reached the model


class TestFitAndFailClosed:
    def test_the_exact_window_fits_and_one_token_more_is_refused_untruncated(self, bundle):
        rt = System1Runtime(bundle)
        base = rt.prepare("dictation", directive()).token_count
        FakeTokenizer.extra_tokens = MAX_WINDOW_TOKENS - base
        assert rt.prepare("dictation", directive()).token_count == MAX_WINDOW_TOKENS
        FakeTokenizer.extra_tokens += 1
        before = len(FakeSession.seen_feed)
        with pytest.raises(System1NoFit):
            rt.judge("dictation", directive())
        assert len(FakeSession.seen_feed) == before  # never sent, never clipped

    @pytest.mark.parametrize("logits", [[[float("nan"), 1.0]], [[1.0, float("inf")]], [[float("-inf"), 0.0]]])
    def test_nonfinite_logits_raise(self, bundle, logits):
        rt = System1Runtime(bundle)
        FakeSession.behavior = staticmethod(lambda ids: logits)
        with pytest.raises(System1NonFinite):
            rt.judge("dictation", directive())

    @pytest.mark.parametrize("logits", [[[1.0]], [[1.0, 2.0, 3.0]], [[1.0, 2.0], [3.0, 4.0]], []])
    def test_wrong_shapes_raise(self, bundle, logits):
        rt = System1Runtime(bundle)
        FakeSession.behavior = staticmethod(lambda ids: logits)
        with pytest.raises(System1RuntimeError):
            rt.judge("retrospective", brief())

    def test_tied_logits_are_no_decision(self, bundle):
        rt = System1Runtime(bundle)
        FakeSession.behavior = staticmethod(lambda ids: [[0.5, 0.5]])
        with pytest.raises(System1RuntimeError, match="tied"):
            rt.judge("retrospective", brief())

    def test_an_engine_failure_is_typed_not_swallowed(self, bundle):
        rt = System1Runtime(bundle)
        FakeSession.behavior = staticmethod(lambda ids: RuntimeError("ort exploded"))
        with pytest.raises(System1RuntimeError, match="ort exploded"):
            rt.judge("retrospective", brief())

    def test_every_failure_is_a_system1_error(self):
        for cls in (system1.System1BundleError, System1StateError, System1NoFit, System1RuntimeError,
                    System1NonFinite, system1.System1DependencyError):
            assert issubclass(cls, System1Error)


class TestConcurrency:
    def test_inference_is_serial_across_threads(self, bundle):
        rt = System1Runtime(bundle)
        FakeSession.peak = 0
        results = []
        threads = [threading.Thread(target=lambda i=i: results.append(rt.judge("dictation", directive(f"d{i}"))))
                   for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(results) == 8 and FakeSession.peak == 1


# ---- bundle verification ----------------------------------------------------------------------

def tamper(path: Path, data: bytes):
    path.write_bytes(data)


class TestBundleVerification:
    def test_a_good_bundle_loads_and_exposes_the_manifest_hash(self, bundle):
        rt = System1Runtime(bundle)
        assert rt.manifest_sha256 == _sha((bundle / "manifest.json").read_bytes())

    def test_a_pinned_manifest_hash_must_match(self, bundle):
        System1Runtime(bundle, expected_manifest_sha256=_sha((bundle / "manifest.json").read_bytes()))
        with pytest.raises(System1BundleError, match="pinned"):
            System1Runtime(bundle, expected_manifest_sha256="0" * 64)

    @pytest.mark.parametrize("name", ["model.onnx", "model.onnx.data", "tokenizer.json", "tokenizer_config.json",
                                      "config.json", "policy/dictation.txt"])
    def test_one_changed_byte_in_any_file_is_refused_before_loading(self, bundle, name, monkeypatch):
        loaded = []
        monkeypatch.setattr(FakeSession, "__init__", lambda *a, **k: loaded.append(1))
        data = (bundle / name).read_bytes()
        tamper(bundle / name, data[:-1] + bytes([data[-1] ^ 1]))
        with pytest.raises(System1BundleError):
            System1Runtime(bundle)
        assert loaded == []

    def test_a_resized_file_is_refused(self, bundle):
        (bundle / "model.onnx.data").write_bytes(b"short")
        with pytest.raises(System1BundleError, match="bytes"):
            System1Runtime(bundle)

    def test_an_unlisted_file_is_refused(self, bundle):
        (bundle / "extra.onnx.data").write_bytes(b"x")
        with pytest.raises(System1BundleError, match="unlisted"):
            System1Runtime(bundle)

    def test_a_missing_file_is_refused(self, bundle):
        (bundle / "tokenizer.json").unlink()
        with pytest.raises(System1BundleError, match="missing"):
            System1Runtime(bundle)

    def test_a_symlink_into_another_tree_is_refused(self, tmp_path, bundle):
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"weights" * 10)
        (bundle / "model.onnx.data").unlink()
        (bundle / "model.onnx.data").symlink_to(outside)
        with pytest.raises(System1BundleError, match="symlink"):
            System1Runtime(bundle)

    @pytest.mark.parametrize("bad", ["../model.onnx", "/etc/passwd", "a//b", "./x", "a\\b", ""])
    def test_manifest_paths_must_be_bundle_relative(self, tmp_path, bad):
        def mutate(m, root):
            m["files"][bad] = {"bytes": 1, "sha256": "0" * 64}
        with pytest.raises(System1BundleError, match="unsafe"):
            System1Runtime(make_bundle(tmp_path / "b", mutate=mutate))

    def test_the_weight_budget_is_measured_on_real_bytes_before_any_hashing(self, tmp_path, monkeypatch):
        def mutate(m, root):
            with (root / "model.onnx.data").open("wb") as f:
                f.truncate(system1.WEIGHT_BUDGET_BYTES)  # sparse: exactly the budget is already too big
            m["files"]["model.onnx.data"] = {"bytes": system1.WEIGHT_BUDGET_BYTES, "sha256": "0" * 64}
        hashed = []
        monkeypatch.setattr(system1, "_file_sha256", lambda p: hashed.append(p) or "0" * 64)
        with pytest.raises(System1BundleError, match="budget"):
            System1Runtime(make_bundle(tmp_path / "b", mutate=mutate))
        assert hashed == []

    def test_a_policy_override_is_refused_even_with_a_self_consistent_manifest(self, tmp_path):
        def mutate(m, root):
            data = b"A different question.\n"
            (root / "policy/retrospective.txt").write_bytes(data)
            m["files"]["policy/retrospective.txt"] = {"bytes": len(data), "sha256": _sha(data)}
        with pytest.raises(System1BundleError, match="trained under"):
            System1Runtime(make_bundle(tmp_path / "b", mutate=mutate))

    @pytest.mark.parametrize("mutation", [
        lambda m, r: m["families"]["dictation"].update(labels=["DICTATES", "DESCRIBES"]),   # swapped order
        lambda m, r: m["families"]["dictation"].update(state_key="directive"),
        lambda m, r: m["families"].pop("dictation"),
        lambda m, r: m.update(max_window_tokens=1024),
        lambda m, r: m.update(weight_budget_bytes=10**9),
        lambda m, r: m.update(renderer="other"),
        lambda m, r: m.update(schema="system1-bundle/9"),
    ])
    def test_the_manifest_cannot_redefine_the_frozen_contract(self, tmp_path, mutation):
        with pytest.raises(System1BundleError):
            System1Runtime(make_bundle(tmp_path / "b", mutate=mutation))

    def test_a_native_config_that_is_not_prompt_first_is_refused(self, tmp_path):
        with pytest.raises(System1BundleError, match="prompt_first"):
            System1Runtime(make_bundle(tmp_path / "b", config={**NATIVE_CONFIG, "prompt_first": False}))

    def test_a_tokenizer_with_other_structural_ids_is_refused(self, bundle, monkeypatch):
        monkeypatch.setattr(FakeTokenizer, "token_to_id", lambda self, t: 5)
        with pytest.raises(System1BundleError, match="tokenizer maps"):
            System1Runtime(bundle)

    def test_a_missing_selftest_is_refused(self, tmp_path):
        with pytest.raises(System1BundleError, match="selftest"):
            System1Runtime(make_bundle(tmp_path / "b", selftest=False))

    def test_a_graph_that_fails_to_load_is_a_bundle_error(self, bundle, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("bad protobuf")
        monkeypatch.setattr(FakeSession, "__init__", boom)
        with pytest.raises(System1BundleError, match="bad protobuf"):
            System1Runtime(bundle)


class TestStartupSelfTest:
    def test_the_same_label_with_wrong_logits_is_refused(self, tmp_path):
        FakeSession.behavior = staticmethod(lambda ids: [[2.01, -1.0]])  # 0.01 > 2e-4, same argmax
        with pytest.raises(System1BundleError, match="self-test"):
            System1Runtime(make_bundle(tmp_path / "b"))

    def test_logits_within_the_frozen_gate_pass(self, tmp_path):
        FakeSession.behavior = staticmethod(lambda ids: [[2.0001, -1.0001]])
        System1Runtime(make_bundle(tmp_path / "b"))

    def test_a_different_tokenisation_is_refused(self, tmp_path):
        def mutate(m, root):
            m["selftest"][0]["input_ids_sha256"] = "0" * 64
        with pytest.raises(System1BundleError, match="self-test"):
            System1Runtime(make_bundle(tmp_path / "b", mutate=mutate))

    def test_a_flipped_label_is_refused(self, tmp_path):
        FakeSession.behavior = staticmethod(lambda ids: [[-2.0, 1.0]])
        with pytest.raises(System1BundleError, match="self-test"):
            System1Runtime(make_bundle(tmp_path / "b"))


# ---- records --------------------------------------------------------------------------------

class TestAuthoritativeRecords:
    def test_a_judgment_emits_the_event_and_writes_one_native_record(self, bundle, tmp_path):
        calls = tmp_path / "calls"
        rt = System1Runtime(bundle, capture_dir=calls)
        rlog = Rlog(tmp_path.name)  # the process-wide counter is keyed by session: keep tests apart
        j = rt.judge_detailed("retrospective", brief("full text"), rlog=rlog)
        (event,) = rlog.kinds("system1.judgment")
        assert event["input_sha256"] == _sha(j.rendered_input.encode()) and event["tokens"] == j.token_count
        assert event["logits"] == list(j.logits) and event["label"] == j.label and event["elapsed_s"] >= 0
        assert event["manifest_sha256"] == rt.manifest_sha256 and j.capture_path == event["capture"]
        path = Path(event["capture"])
        assert path.parent.name == "system1" and path.name == "0001-system1-retrospective.json"
        record = json.loads(path.read_text())
        request, response = record["request"], record["response"]
        assert request["rendered_input"] == j.rendered_input and request["input_ids"] == list(j.input_ids)
        assert request["state"] == {"candidate_briefing": "full text"} and request["labels"] == list(j.labels)
        assert request["policy"] == (PROMPTS / "offline_onejev_retrospective.txt").read_text()
        assert request["policy_sha256"] == system1.FAMILIES["retrospective"].policy_sha256
        assert request["token_count"] == j.token_count and request["manifest_sha256"] == rt.manifest_sha256
        assert response["label"] == j.label and response["logits"] == list(j.logits)
        assert response["tokens"] == j.token_count and response["elapsed_s"] == j.elapsed_s
        assert record["phase"] == "system1-retrospective" and record["session"] == tmp_path.name

    def test_native_records_never_look_like_upstream_calls(self, bundle, tmp_path):
        """Reviewer-verified blocker: the suite counts ``*.response.json`` and reads ``messages`` as GPU calls."""
        calls = tmp_path / "calls"
        rt = System1Runtime(bundle, capture_dir=calls)
        rlog = Rlog(tmp_path.name)  # the process-wide counter is keyed by session: keep tests apart
        rt.judge("retrospective", brief(), rlog=rlog)
        rt.judge("dictation", directive(), rlog=rlog)
        session = callcapture.session_dirname(tmp_path.name)
        folder = calls / session
        assert list(folder.glob("*")) == [folder / "system1"]           # nothing flat in the session folder
        assert list(folder.glob("*.response.json")) == [] and list(folder.rglob("*.response.json")) == []
        assert sorted(p.name for p in (folder / "system1").iterdir()) == [
            "0001-system1-retrospective.json", "0002-system1-dictation.json"]  # own counter
        assert not rlog.kinds("upstream.dump") and not rlog.kinds("upstream.response_dump")
        for record in (json.loads(p.read_text()) for p in (folder / "system1").iterdir()):
            assert "messages" not in record["request"] and "body" not in record

    def test_native_counter_is_independent_of_and_does_not_shift_upstream_captures(self, bundle, tmp_path):
        calls = tmp_path / "calls"
        rt = System1Runtime(bundle, capture_dir=calls)
        rlog = Rlog(tmp_path.name)  # the process-wide counter is keyed by session: keep tests apart
        rt.judge("dictation", directive(), rlog=rlog)
        upstream = callcapture.capture({"messages": [{"role": "user", "content": "x"}]}, rlog, calls_dir=calls,
                                       phase="coder")
        rt.judge("dictation", directive(), rlog=rlog)
        assert Path(upstream).name == "0001-coder.json"
        assert sorted(p.name for p in (Path(upstream).parent / "system1").iterdir()) == [
            "0001-system1-dictation.json", "0002-system1-dictation.json"]

    def test_native_counter_resumes_after_a_restart_and_never_overwrites(self, bundle, tmp_path):
        calls = tmp_path / "calls"
        rlog = Rlog(tmp_path.name)  # the process-wide counter is keyed by session: keep tests apart
        System1Runtime(bundle, capture_dir=calls).judge("dictation", directive("first"), rlog=rlog)
        callcapture._seq.clear()  # a restart forgets the in-memory counter
        System1Runtime(bundle, capture_dir=calls).judge("dictation", directive("second"), rlog=rlog)
        names = sorted(p.name for p in (calls / callcapture.session_dirname(tmp_path.name) / "system1").iterdir())
        assert names == ["0001-system1-dictation.json", "0002-system1-dictation.json"]

    def test_capture_off_events_carry_no_payload_but_an_accurate_hash(self, bundle, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rlog = Rlog()
        secret = "UNIQUE-USER-CODE-7f3a"
        j = System1Runtime(bundle).judge_detailed("dictation", directive(secret), rlog=rlog)
        (event,) = rlog.kinds("system1.judgment")
        assert event["capture"] is None and event["input_sha256"] == _sha(j.rendered_input.encode())
        assert secret not in json.dumps(rlog.events, default=str)
        assert "input" not in event and "input_ids" not in event
        assert {p.name for p in tmp_path.glob("*")} == {"bundle"}  # nothing written anywhere else

    def test_capture_off_failures_carry_no_payload_either(self, bundle):
        secret = "UNIQUE-USER-CODE-9b1c"
        rt = System1Runtime(bundle)
        FakeTokenizer.extra_tokens = MAX_WINDOW_TOKENS
        rlog = Rlog()
        with pytest.raises(System1NoFit):
            rt.judge("dictation", directive(secret), rlog=rlog)
        (event,) = rlog.kinds("system1.error")
        assert event["capture"] is None and len(event["input_sha256"]) == 64
        assert secret not in json.dumps(rlog.events, default=str)

    @pytest.mark.parametrize("fail", ["nofit", "nonfinite", "engine"])
    def test_failures_record_the_full_input_and_reraise(self, bundle, tmp_path, fail):
        rt = System1Runtime(bundle, capture_dir=tmp_path / "calls")
        if fail == "nofit":
            FakeTokenizer.extra_tokens = MAX_WINDOW_TOKENS
        elif fail == "nonfinite":
            FakeSession.behavior = staticmethod(lambda ids: [[float("nan"), 0.0]])
        else:
            FakeSession.behavior = staticmethod(lambda ids: RuntimeError("boom"))
        rlog = Rlog()
        with pytest.raises(System1Error):
            rt.judge("dictation", directive("the whole thing"), rlog=rlog)
        (event,) = rlog.kinds("system1.error")
        assert "input" not in event and "the whole thing" not in json.dumps(event)
        record = json.loads(Path(event["capture"]).read_text())
        request = record["request"]
        assert request["rendered_input"].endswith("public_directive: the whole thing")
        assert request["input_ids"] and request["state"] == {"public_directive": "the whole thing"}
        assert event["input_sha256"] == _sha(request["rendered_input"].encode())
        assert record["response"]["error"] == event["error"] and "messages" not in request
        assert event["error"] in {"System1NoFit", "System1NonFinite", "System1RuntimeError"}
        assert rlog.kinds("system1.judgment") == []

    def test_a_state_error_is_recorded_without_inventing_an_input(self, bundle):
        rlog = Rlog()
        with pytest.raises(System1StateError):
            System1Runtime(bundle).judge("dictation", {"directive": "x"}, rlog=rlog)
        (event,) = rlog.kinds("system1.error")
        assert event["error"] == "System1StateError" and event["input_sha256"] is None


# ---- the real bundle through the real engines ----------------------------------------------

REAL_BUNDLE = Path("~/.cria/models/system1/expanded-v2-live").expanduser()
TRAINING = Path("~/.cria/training/gliclass-v4-edge-expanded-v2").expanduser()


def _real_engines():
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False
    return (REAL_BUNDLE / "manifest.json").exists() and (TRAINING / "assessment/v2/results.jsonl").exists()


@pytest.mark.skipif(not _real_engines(), reason="needs onnxruntime+tokenizers and the built System 1 bundle")
class TestRealNativeParity:
    """Actual frozen INT4 calls: exact native token ids and logits within the 2e-4 production gate."""

    @pytest.fixture(scope="class")
    def rows(self):
        rows = [json.loads(l) for l in (TRAINING / "assessment/v2/results.jsonl").read_text().splitlines()]
        pick = []
        for family in FAMILIES:
            rs = sorted((r for r in rows if r["family"] == family), key=lambda r: r["native_input"]["tokens"])
            uni = [r for r in rs if any(ord(c) > 127 for c in json.dumps(r["native_input"]["state"], ensure_ascii=False))]
            pick += [rs[0], rs[len(rs) // 2], rs[-1], *uni[:1], *uni[-1:]]
        return list({r["id"]: r for r in pick}.values())

    @pytest.fixture(scope="class")
    def runtime(self):
        return System1Runtime(REAL_BUNDLE)

    def test_batch_matches_ids_rendering_logits_and_choices(self, runtime, rows):
        assert len(rows) >= 8 and {r["family"] for r in rows} == set(FAMILIES)
        for r in rows:
            native = r["native_input"]
            j = runtime.infer(r["family"], native["state"])
            assert list(j.labels) == native["labels"] and j.rendered_input == native["rendered_input"]
            assert list(j.input_ids) == native["native_inputs"]["input_ids"][0], r["id"]
            assert j.label == r["int4_prediction"]
            for got, want in zip(j.logits, r["int4_logits"]):
                assert abs(got - want) <= 2e-4 + 2e-4 * abs(want), r["id"]

    def test_all_frozen_training_inputs_render_and_tokenise_identically(self, runtime):
        """the 836 training cases, each recorded in both label orders: the served order must be byte/id identical; training also alternated the
        label order (never served), so those rows check the renderer and tokenizer with their own order."""
        served = reversed_rows = 0
        for line in (TRAINING / "train-001/native-training-inputs.jsonl").read_text().splitlines():
            r = json.loads(line)
            (key,) = r["state"]
            family = next(f for f, spec in FAMILIES.items() if spec.state_key == key)
            labels = tuple(r["labels"])
            rendered = system1.render_input(labels, runtime._bundle.policies[family], system1.render_state(r["state"]))
            assert rendered == r["rendered_input"], r["id"]
            ids = r["native_inputs"]["input_ids"][0]
            assert runtime._tokenizer.encode(rendered).ids == ids, r["id"]
            if labels == FAMILIES[family].labels:
                assert list(runtime.prepare(family, r["state"]).input_ids) == ids
                served += 1
            else:
                assert labels == tuple(reversed(FAMILIES[family].labels))
                reversed_rows += 1
        assert served == reversed_rows == 836  # every case recorded once per label order


@pytest.mark.skipif(not _real_engines(), reason="needs onnxruntime+tokenizers and the built System 1 bundle")
def test_real_engine_refuses_an_oversized_activation_without_clipping_and_stays_usable():
    """A fresh process (the arena is process-wide) with a 1 GiB budget: a long complete input is refused
    by the allocator as System1RuntimeError with its tokens intact, then a normal call still works."""
    code = """
import json, sys
from cria.system1 import System1Runtime, System1RuntimeError
rt = System1Runtime(sys.argv[1], memory_budget_bytes=1024**3)
long_state = {"candidate_briefing": "word " * 6000}
tokens = rt.prepare("retrospective", long_state).token_count
try:
    rt.infer("retrospective", long_state)
    refused = None
except System1RuntimeError as exc:
    refused = str(exc)
ok = rt.infer("dictation", {"public_directive": "Run the failing test."})
print(json.dumps({"tokens": tokens, "refused": refused, "label": ok.label}))
"""
    out = subprocess.run([sys.executable, "-c", code, str(REAL_BUNDLE)], cwd=REPO, capture_output=True,
                         text=True, check=True, timeout=300)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["tokens"] > 5000
    assert "smaller than requested" in result["refused"] or "Failed to allocate" in result["refused"]
    assert result["label"] in ("DESCRIBES", "DICTATES")
