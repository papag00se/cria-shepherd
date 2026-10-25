"""``[system1]`` — the optional trained CPU classifier's configuration and startup refusal.

Disabled is the default and costs nothing: the core never imports the runtime or its third-party
dependencies. Enabled means the operator asked for the classifier, so a service that cannot bring it
up must refuse to start; it never quietly runs without it (principle 4 — no fallbacks).
"""
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from cria import config, system1, system1wiring
from cria.config import Config, System1Config


def load(tmp_path, body):
    path = tmp_path / "cria.toml"
    path.write_text(textwrap.dedent(body))
    return Config.load(path)


def test_it_is_disabled_by_default_and_a_missing_table_changes_nothing(tmp_path):
    assert Config().system1 == System1Config(enabled=False, bundle_dir=None, threads=6)
    assert load(tmp_path, "[server]\nport = 1\n").system1 == Config().system1


def test_an_enabled_table_is_read_with_its_explicit_bundle_and_threads(tmp_path):
    cfg = load(tmp_path, '[system1]\nenabled = true\nbundle_dir = "~/bundles/s1"\nthreads = 3\n')
    assert cfg.system1.enabled is True and cfg.system1.threads == 3
    assert cfg.system1.bundle_path == Path("~/bundles/s1").expanduser()


def test_a_bundle_is_never_guessed_once_enabled(tmp_path):
    with pytest.raises(ValueError, match="bundle_dir is required"):
        load(tmp_path, "[system1]\nenabled = true\n")


@pytest.mark.parametrize("body", [
    "[system1]\nenabled = true\nbundle_dir = \"/b\"\nunknown = 1\n",
    "[system1]\nenabled = \"yes\"\n",
    "[system1]\nenabled = 1\n",
    "[system1]\nbundle_dir = 7\n",
    "[system1]\nbundle_dir = \"  \"\n",
    "[system1]\nthreads = 0\n",
    "[system1]\nthreads = -2\n",
    "[system1]\nthreads = \"6\"\n",
    "[system1]\nthreads = 2.5\n",
    "[system1]\nthreads = true\n",
    "system1 = 3\n",
])
def test_every_unknown_key_and_wrong_type_is_refused_rather_than_coerced(tmp_path, body):
    with pytest.raises(ValueError, match="system1"):
        load(tmp_path, body)


def test_disabled_builds_nothing(tmp_path):
    assert system1wiring.build(System1Config()) is None


def test_the_default_core_never_imports_the_runtime_or_its_dependencies():
    code = ("import sys, cria.server, cria.loop, cria.config, cria.groundedaction, cria.__main__\n"
            "bad = [m for m in ('cria.system1', 'onnxruntime', 'tokenizers', 'numpy') if m in sys.modules]\n"
            "assert not bad, bad\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parents[1])
    assert done.returncode == 0, done.stderr


def test_a_missing_bundle_refuses_startup(tmp_path):
    cfg = System1Config(enabled=True, bundle_dir=str(tmp_path / "absent"))
    with pytest.raises(system1wiring.StartupError, match="not a directory"):
        system1wiring.build(cfg)


def test_a_directory_that_is_not_a_verified_bundle_refuses_startup(tmp_path):
    cfg = System1Config(enabled=True, bundle_dir=str(tmp_path))
    with pytest.raises(system1wiring.StartupError, match="cannot be loaded"):
        system1wiring.build(cfg)


def test_missing_optional_dependencies_refuse_startup_with_the_real_reason(tmp_path):
    class NoDeps:
        def __init__(self, *a, **k):
            raise system1.System1DependencyError("'onnxruntime' is not installed")

    cfg = System1Config(enabled=True, bundle_dir=str(tmp_path))
    with patch.object(system1, "System1Runtime", NoDeps):
        with pytest.raises(system1wiring.StartupError, match="onnxruntime"):
            system1wiring.build(cfg)


@pytest.mark.parametrize("failure", [RuntimeError("ort exploded"), ValueError("bad manifest"), KeyError("x"),
                                     system1.System1BundleError("sha mismatch")])
def test_any_failure_while_loading_an_enabled_bundle_refuses_startup_with_the_real_reason(tmp_path, failure):
    class Broken:
        def __init__(self, *a, **k):
            raise failure

    with patch.object(system1, "System1Runtime", Broken):
        with pytest.raises(system1wiring.StartupError, match=type(failure).__name__):
            system1wiring.build(System1Config(enabled=True, bundle_dir=str(tmp_path)))


def test_the_runtime_gets_the_configured_threads_and_the_call_capture_root(tmp_path):
    seen = {}

    class Loaded:
        bundle_id, manifest_sha256 = "b", "m"

        def __init__(self, bundle, threads, **kw):
            seen.update(bundle=bundle, threads=threads, **kw)

    events = []
    log = type("L", (), {"emit": lambda self, kind, **kw: events.append((kind, kw))})()
    with patch.object(system1, "System1Runtime", Loaded):
        runtime = system1wiring.build(System1Config(enabled=True, bundle_dir=str(tmp_path), threads=2),
                                      log, capture_dir=tmp_path / "calls")
    assert isinstance(runtime, Loaded)
    assert seen == {"bundle": tmp_path, "threads": 2, "capture_dir": tmp_path / "calls"}
    assert events[0][0] == "system1.loaded" and events[0][1]["manifest_sha256"] == "m"
