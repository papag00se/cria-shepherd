"""System 1 bundle loading table: every way a bundle can be wrong (unreadable files, native config, policy bytes, self-test coverage) is a typed
System1BundleError naming the cause BEFORE the graph loads; a pristine bundle loads; the typed state/dependency errors of the runtime edge."""
import json
import types

import pytest

from cria import system1
from cria.system1 import System1BundleError
from test_misc_runtime_system1 import eng, make_bundle  # noqa: F401


def rewrite(name, data):
    def mutate(root):
        (root / name).write_bytes(data)
    return mutate


def config(**over):
    return json.dumps({"architecture_type": "uni-encoder", "prompt_first": True, "class_token_index": 128001, "text_token_index": 128002, **over}).encode()


ROWS = [
    (lambda root: (root / "config.json").unlink(), "cannot read the System 1 bundle"),
    (rewrite("config.json", b"{not json"), "cannot read the System 1 bundle"),
    (rewrite("config.json", config(architecture_type="bi-encoder")), "architecture_type is 'bi-encoder'"),
    (rewrite("config.json", config(prompt_first=False)), "prompt_first is False"),
    (rewrite("policy/dictation.txt", b"a different policy"), "dictation policy is not the policy the model was trained under"),
    (rewrite("policy/dictation.txt", b"\xff\xfe"), "cannot read the System 1 bundle"),
    (rewrite("selftest.json", b"[]"), "at least one case for every family"),
    (lambda root: (root / "selftest.json").unlink(), "cannot read the System 1 bundle"),
]


@pytest.mark.parametrize("mutate, message", ROWS, ids=[m for _, m in ROWS])
def test_a_bundle_with_any_defect_is_refused_with_the_defect_named(eng, tmp_path, mutate, message):  # noqa: F811
    """Each row corrupts exactly one thing in an otherwise valid bundle; loading names it, the graph never loads."""
    root = make_bundle(tmp_path / "b", eng, mutate)
    with pytest.raises(System1BundleError, match=message):
        system1.load_bundle(root)


def test_a_pristine_bundle_loads_with_its_policy_texts_and_self_test(eng, tmp_path):  # noqa: F811
    """The good bundle yields its id (the directory name), the policy texts (immutable) and a self-test covering every family."""
    root = make_bundle(tmp_path / "b", eng)
    bundle = system1.load_bundle(root)
    assert bundle.bundle_id == "b" and set(bundle.policies) == set(system1.FAMILIES)
    assert {case["family"] for case in bundle.selftest} == set(system1.FAMILIES)
    with pytest.raises(TypeError):
        bundle.policies["dictation"] = "x"


def test_an_absent_runtime_library_is_a_typed_dependency_error():
    """Importing a missing optional extra says which one."""
    with pytest.raises(system1.System1DependencyError, match="'no_such_module_sv2' is not installed"):
        system1._import("no_such_module_sv2")


def _runtime(eng, tmp_path, **kw):  # noqa: F811
    return system1.System1Runtime(make_bundle(tmp_path / "rt", eng), **kw)


@pytest.mark.parametrize("break_it, message", [
    (lambda e: setattr(e.ort, "InferenceSession", lambda *a, **k: (_ for _ in ()).throw(OSError("corrupt graph"))), "cannot load the System 1 graph or tokenizer: corrupt graph"),
    (lambda e: setattr(e.ort.InferenceSession, "get_providers", lambda self: ["CUDAExecutionProvider"]), r"CPU only; ORT selected \['CUDAExecutionProvider'\]"),
    (lambda e: setattr(e.ort.InferenceSession, "get_inputs", lambda self: [types.SimpleNamespace(name="ids")]), "graph inputs are"),
    (lambda e: setattr(e.tok.__class__, "token_to_id", lambda self, t: 5), "tokenizer maps <<LABEL>> to 5"),
    (lambda e: setattr(e, "logits", [[-9.0, 9.0]]), "self-test .* disagrees with the producer's record"),     # the label flips
    (lambda e: setattr(e, "logits", [[2.1, -1.0]]), "disagrees with the producer's record"),                  # logits drift beyond 2e-4
    (lambda e: setattr(e, "fail", RuntimeError("oom")), "self-test case could not run"),
])
def test_a_runtime_that_cannot_reproduce_the_producers_records_never_starts(eng, tmp_path, break_it, message):  # noqa: F811
    """Load, provider, input-name, token-id and self-test disagreement are each a typed startup refusal with the cause in the message."""
    root = make_bundle(tmp_path / "rt", eng)
    break_it(eng)
    with pytest.raises(System1BundleError, match=message):
        system1.System1Runtime(root)


def test_a_logits_drift_inside_the_gate_is_accepted_and_the_tokenizer_failure_is_typed(eng, tmp_path):  # noqa: F811
    """1e-5 of drift passes the 2e-4 gate (the self-test is a fidelity check, not an equality one); a tokenizer that raises at prepare time is a System1RuntimeError, not a bare exception."""
    root = make_bundle(tmp_path / "rt", eng)
    eng.logits = [[2.00001, -1.0]]
    rt = system1.System1Runtime(root)
    assert rt.bundle_id == "rt" and rt.threads >= 1 and rt.memory_budget_bytes > 0
    eng.tok.__class__.encode = lambda self, text: (_ for _ in ()).throw(ValueError("bad utf-8"))
    with pytest.raises(system1.System1RuntimeError, match="tokenizer failed: bad utf-8"):
        rt.prepare("dictation", {"public_directive": "x"})
    with pytest.raises(system1.System1StateError, match="unknown System 1 family 'nope'"):
        rt.prepare("nope", {"public_directive": "x"})
    with pytest.raises(system1.System1StateError, match="must be exactly"):
        rt.prepare("dictation", ["public_directive"])
