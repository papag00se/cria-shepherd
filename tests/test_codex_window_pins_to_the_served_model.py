"""The isolated Codex config must carry the window of the model cria is ACTUALLY serving.

Codex will not fetch a keyless local provider's /models catalog (its refresh is gated on
uses_codex_backend || has_command_auth, and a keyless shim is neither), so the ONLY channel
for the real window is model_context_window in config.toml. If that key is missing, or worse
is planted inside a [model_providers.*] or [projects.*] table where Codex won't read it as a
top-level setting, Codex falls back to a hardcoded 272K window, never auto-compacts, and a
long cell dies mid-turn with a 400. These pin _set_key's two failure modes.
"""
import importlib.util
from pathlib import Path

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

_spec = importlib.util.spec_from_file_location(
    "sync_codex_model", Path(__file__).resolve().parent.parent / "scripts" / "sync_codex_model.py")
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)


CONFIG = (
    'model = "cria-local"\n'
    'model_provider = "cria"\n'
    '\n'
    '[model_providers.cria]\n'
    'name = "cria (local shim)"\n'
    'base_url = "http://127.0.0.1:18085/v1"\n'
)


def test_an_existing_top_level_key_is_replaced_in_place_not_duplicated():
    out = sync._set_key(CONFIG, "model", '"ternary_bonsai_2_27b_pq2_0"')
    assert out.count("model = ") == 1  # replaced, not appended a second time
    assert 'model = "ternary_bonsai_2_27b_pq2_0"' in out
    assert '"cria-local"' not in out


def test_a_new_key_lands_at_top_level_never_inside_a_table():
    out = sync._set_key(CONFIG, "model_context_window", "40960")
    # It must appear BEFORE the first table header, or a TOML parser reads it as a key of
    # [model_providers.cria] and Codex never sees it as a model setting.
    assert out.index("model_context_window = 40960") < out.index("[model_providers.cria]")
    if tomllib is not None:
        parsed = tomllib.loads(out)
        assert parsed["model_context_window"] == 40960              # top level
        assert "model_context_window" not in parsed["model_providers"]["cria"]  # not captured


def test_the_window_and_trigger_survive_a_second_sync_idempotently():
    once = sync._set_key(sync._set_key(CONFIG, "model_context_window", "40960"),
                         "model_auto_compact_token_limit", "34816")
    twice = sync._set_key(sync._set_key(once, "model_context_window", "40960"),
                          "model_auto_compact_token_limit", "34816")
    assert once == twice
    assert once.count("model_context_window = ") == 1
    assert once.count("model_auto_compact_token_limit = ") == 1
