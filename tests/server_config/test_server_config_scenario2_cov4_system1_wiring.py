"""System 1 service wiring edges: a runtime that loads is reported once with its identity (and the capture flag), the optional-runtime import
failing is a startup refusal naming the cause, and a guard declines on a non-string/off-menu answer whether or not anyone is logging."""
import types

import pytest

from cria import system1, system1wiring
from cria.config import System1Config


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def test_a_loaded_runtime_is_logged_with_its_identity_and_whether_it_captures(tmp_path, monkeypatch):
    made = []

    class Runtime:
        bundle_id, manifest_sha256 = "bundle-7", "ab" * 32

        def __init__(self, bundle, threads, *, capture_dir=None):
            made.append((bundle, threads, capture_dir))

    monkeypatch.setattr(system1, "System1Runtime", Runtime)
    cfg = System1Config(enabled=True, bundle_dir=str(tmp_path), threads=3)
    log = Log()
    runtime = system1wiring.build(cfg, log, capture_dir=tmp_path / "calls")
    assert isinstance(runtime, Runtime) and made == [(tmp_path, 3, tmp_path / "calls")]
    assert log.events == [("system1.loaded", {"bundle_dir": str(tmp_path), "threads": 3, "capture": True, "bundle_id": "bundle-7", "manifest_sha256": "ab" * 32})]
    quiet = Log()
    system1wiring.build(cfg, quiet)
    assert quiet.events[0][1]["capture"] is False and system1wiring.build(cfg) is not None            # no log: still builds


def test_a_runtime_module_that_cannot_be_imported_is_a_startup_refusal_naming_why(tmp_path, monkeypatch):
    monkeypatch.delattr(system1, "System1Runtime")
    with pytest.raises(system1wiring.StartupError, match="runtime dependencies are unavailable: cannot import name 'System1Runtime'"):
        system1wiring.build(System1Config(enabled=True, bundle_dir=str(tmp_path)))


@pytest.mark.parametrize("answer", ["MAYBE", None, 3, ""])
@pytest.mark.parametrize("logged", [True, False])
def test_an_answer_outside_the_trained_labels_declines_with_or_without_a_log(answer, logged):
    runtime = types.SimpleNamespace(judge=lambda family, state, rlog=None: answer)
    log = Log() if logged else None
    with pytest.raises(system1wiring.Unjudged, match=f"unexpected label {answer!r}") as caught:
        system1wiring.classify(runtime, "dictation", "x", log, seat="gate")
    assert (caught.value.family, caught.value.reason) == ("dictation", f"unexpected label {answer!r}")
    if logged:
        assert log.events == [("system1.declined", {"level": "warn", "family": "dictation", "seat": "gate", "error": "UnexpectedLabel", "detail": repr(answer)})]


def test_a_trained_label_passes_through_and_the_state_key_is_the_familys_own():
    seen = []
    runtime = types.SimpleNamespace(judge=lambda family, state, rlog=None: seen.append((family, state)) or system1.FAMILIES["dictation"].labels[1])
    assert system1wiring.classify(runtime, "dictation", "build it", None, seat="s") == system1.FAMILIES["dictation"].labels[1]
    assert seen == [("dictation", {system1.FAMILIES["dictation"].state_key: "build it"})]
