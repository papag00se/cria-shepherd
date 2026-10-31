"""Startup-side wiring: env file secrets, the system1 classifier seam (fail safe), failover."""
import os

import pytest

from cria import failover as fo
from cria import loop, system1, system1wiring
from cria.config import System1Config
from cria.envfile import env_secret, load_env_file


def test_env_file_loads_only_allowlisted_names_and_never_clobbers_the_environment(tmp_path, monkeypatch):
    """The leak guard: an env file holding unrelated secrets must not push them into cria; existing env wins; CRLF/quotes/export are normalized."""
    for name in ("SC_BRAVE", "SC_QUOTED", "SC_EXPORTED", "SC_AWS", "SC_SET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SC_SET", "from-env")
    path = tmp_path / ".env"
    path.write_text('# c\n\nSC_BRAVE=brave-key\r\nSC_QUOTED="quoted value"\r\nexport SC_EXPORTED=two\n'
                    "SC_AWS=not-cria's-secret\nSC_SET=from-file\n")
    allow = {"SC_BRAVE", "SC_QUOTED", "SC_EXPORTED", "SC_SET"}
    assert load_env_file(str(path), allow) == 3  # SC_SET already present, not counted
    assert (os.environ["SC_BRAVE"], os.environ["SC_QUOTED"], os.environ["SC_EXPORTED"], os.environ["SC_SET"]) == (
        "brave-key", "quoted value", "two", "from-env")
    assert "SC_AWS" not in os.environ
    assert load_env_file(str(path), set()) == 0 and load_env_file(str(tmp_path / "absent"), allow) == 0


def test_env_secret_strips_crlf_and_blank_is_none(monkeypatch):
    """A trailing CRLF in a key would corrupt an Authorization header; a blank value is no secret."""
    monkeypatch.setenv("SC_KEY", "  key\r\n")
    monkeypatch.setenv("SC_BLANK", "   ")
    assert env_secret("SC_KEY") == "key"
    assert env_secret("SC_BLANK") is None and env_secret(None) is None and env_secret("SC_UNSET_XYZ") is None


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


@pytest.mark.parametrize("fault", ["raises", "unexpected-label", "typed-error"])
def test_a_classifier_that_cannot_answer_declines_and_the_briefing_is_rejected_without_asking_a_reasoner(fault):
    """System1 fails SAFE: any runtime error or off-menu label is 'no answer' (logged with the real error); the compaction briefing is rejected and no reasoner stands in."""
    class Runtime:
        def judge(self, family, state, *, rlog=None):
            if fault == "raises":
                raise RuntimeError("ort exploded")
            if fault == "typed-error":
                raise system1.System1Error("no-fit input")
            return "MAYBE"

    log, asked = Log(), []
    with pytest.raises(system1wiring.Unjudged):
        system1wiring.classify(Runtime(), "retrospective", "The briefing.", log, seat="t")
    assert [k for k, _ in log.events] == ["system1.declined"] and log.events[0][1]["family"] == "retrospective"
    role = type("R", (), {"reasoning": "off"})()
    ok = loop.validate_compaction_briefing(lambda *a, **k: asked.append(a), role, "We built X.", files="", checks="",
                                           transcript_blocks=[], rlog=log, system1=Runtime())
    assert ok is False and asked == []


def test_a_classifier_failure_never_swallows_an_interrupt():
    """Only Exception declines; KeyboardInterrupt still stops the service."""
    class Runtime:
        def judge(self, *a, **k):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        system1wiring.classify(Runtime(), "retrospective", "x", None, seat="t")


def test_an_enabled_classifier_that_cannot_load_refuses_startup_and_disabled_loads_nothing(tmp_path, monkeypatch):
    """No silent run without the classifier: missing dir, unverified bundle, or any load error is a StartupError naming the real cause."""
    assert system1wiring.build(System1Config()) is None
    with pytest.raises(system1wiring.StartupError, match="not a directory"):
        system1wiring.build(System1Config(enabled=True, bundle_dir=str(tmp_path / "absent")))
    with pytest.raises(system1wiring.StartupError, match="cannot be loaded"):
        system1wiring.build(System1Config(enabled=True, bundle_dir=str(tmp_path)))  # not a verified bundle

    class Broken:
        def __init__(self, *a, **k):
            raise ValueError("bad manifest")

    monkeypatch.setattr(system1, "System1Runtime", Broken)
    with pytest.raises(system1wiring.StartupError, match="ValueError: bad manifest"):
        system1wiring.build(System1Config(enabled=True, bundle_dir=str(tmp_path)))


CHAIN = ["light", "light_backup", "cloud_reasoner", "cloud_coder"]


def test_failures_are_classified_from_status_and_text():
    """HTTP status + error text map onto the failure kinds the executor decides on."""
    F = fo.Failure
    for status, msg, expected in [(429, "too many requests", F.RATE_LIMIT), (429, "quota exceeded", F.QUOTA_EXHAUSTED),
                                  (401, "", F.AUTH), (403, "", F.AUTH), (404, "", F.MODEL_NOT_FOUND), (503, "", F.MODEL_UNAVAILABLE),
                                  (408, "", F.TIMEOUT), (None, "connection timed out", F.TIMEOUT),
                                  (None, "connection refused", F.MODEL_UNAVAILABLE)]:
        assert fo.classify_failure(status, msg) is expected, (status, msg)
    assert fo.classify_failure(None, "", is_context_overflow=True) is F.CONTEXT_OVERFLOW


def test_the_executor_retries_a_timeout_once_walks_on_unavailable_and_reraises_when_alone():
    """Flaky shared-GPU case: retry the same route once after one backoff; a dead endpoint walks the chain; a lone endpoint re-raises the real error."""
    calls, slept = [], []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("the request timed out")
        return "ok"

    def dead():
        raise ConnectionError("connection refused")

    classify = lambda e: fo.classify_failure(None, str(e))  # noqa: E731
    run = lambda attempts: fo.run("coding", attempts, classify=classify, rlog=Log(), sleep=slept.append)  # noqa: E731
    assert run([fo.Attempt("coder", flaky)]) == "ok" and len(calls) == 2 and len(slept) == 1
    assert run([fo.Attempt("a", dead), fo.Attempt("b", lambda: "second")]) == "second"
    with pytest.raises(ConnectionError):
        run([fo.Attempt("only", dead)])
    assert isinstance(fo.decide_action(fo.Failure.AUTH, "cloud_coder", "r", CHAIN, 0), fo.HardFail)
    assert fo.decide_action(fo.Failure.RATE_LIMIT, "light", "r", CHAIN, 2).role == "light_backup"
    assert fo.decide_action(fo.Failure.RATE_LIMIT, "light", "r", CHAIN, 0, retry_after_ms=60000).wait_ms == 30000
