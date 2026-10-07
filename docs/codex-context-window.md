# Codex and the context window (a harness-specific exception)

**Short version:** cria advertises the model's real runtime context window the standard
way, in `GET /v1/models`. Any standards-compliant harness reads it and applies its own
compaction policy — cria does nothing per-harness. **Codex is the exception:** it will not
read that window from a keyless local provider, so for Codex (and only Codex) you set one
extra config key. This page documents why, the minimal setup, and how it was validated, so
the exception is understood rather than cargo-culted.

## The standard cria follows

There is **no wire standard for a compaction *trigger*** — when to compact is a client-side
policy. The standard *signal* is the context **window**, and each harness derives its own
trigger from it (Codex compacts at 90% of the window). So cria's only job is to state the
window truthfully. `GET http://127.0.0.1:18085/v1/models` returns the **runtime** window
(never the larger trained max) under every field name the OpenAI-compatible ecosystem reads:

```jsonc
{
  "data": [{
    "id": "<the model cria is serving>",
    "context_window": 40960, "max_context_window": 40960,  // OpenAI / Codex
    "context_length": 40960,                               // OpenRouter / HF
    "max_model_len": 40960,                                // vLLM
    "meta": { "n_ctx": 40960 }                             // llama.cpp (this stack's native)
  }],
  "models": [ /* same entry — Codex reads this key */ ]
}
```

The value is discovered from the backend's `/props` `n_ctx` and cached for the cria
process lifetime. After a backend swap, restart cria once the new backend is ready,
then verify its model ID and context before syncing Codex. The restored fleet's managed
`llama-fleet switch` performs that check and restarts cria if its card is stale;
changing the backend alone does not refresh the cached advertisement.

## Why Codex needs an exception

Codex ignores that advertisement for a keyless local provider. Its model-catalog refresh is
gated (verified against `codex-rs` `main`, 2026-09):

- `models-manager/src/manager.rs` — `should_refresh_models() = uses_codex_backend() ||
  has_command_auth() || supports_api_key_discovery()`, and `refresh_available_models` early-
  returns unless the `ApiKeyModelDiscovery` feature flag is on.
- `model-provider/src/models_endpoint.rs` — `supports_api_key_models()` is true only with a
  `model_catalog_url` **or** the first-party OpenAI provider; `supports_api_key_discovery`
  additionally requires API-key auth.

A keyless local shim satisfies none of these, so Codex **never fetches `/models`**. Proven,
not assumed: three isolated `codex exec` runs (log-marked, no other traffic) produced **zero**
hits on cria's `/v1/models`, even with `model_catalog_url` and a dummy `env_key` set. With no
catalog entry, Codex falls back to `model_info_from_slug` — a hardcoded **272,000**-token
window — never auto-compacts, and a session that crosses the server's real ceiling dies mid-
turn with `HTTP 400` (measured: `request (41,662 tokens) exceeds the available context size
(40,960 tokens)`). Codex logs the tell on every run: `warning: Model metadata for '<model>'
not found. Defaulting to fallback metadata`.

The one channel Codex *does* honor for any provider is `model_context_window` in config.toml
(`with_config_overrides`, applied on top of the fallback). Codex then derives the auto-compact
trigger as `model_auto_compact_token_limit` if set, else 90% of the window
(`ModelInfo::auto_compact_token_limit` = `context_window * 9 / 10`), and `min(explicit,
derived)` means an explicit trigger can only pull it lower, never past the wall.

## Minimal setup

Point Codex at cria via an isolated `CODEX_HOME` (so your global `~/.codex` is untouched):

```toml
# $CODEX_HOME/config.toml
model         = "ternary_bonsai_2_27b_pq2_0"   # must equal cria's /v1/models id
model_provider = "cria"
model_context_window = 40960                   # the server's real n_ctx — the ONLY window Codex reads here
model_auto_compact_token_limit = 34816         # optional; ~85% for margin. Omit to let Codex use 90%.

[model_providers.cria]
name = "cria (local shim)"
base_url = "http://127.0.0.1:18085/v1"
wire_api = "responses"                         # cria speaks Codex's Responses wire; keyless
```

Don't hand-maintain the numbers — generate them from what cria is serving:

```bash
python scripts/sync_codex_model.py     # writes model + model_context_window + trigger from cria /v1/models
```

Run it after any model swap. `scripts/swap_and_test.sh` and the suite (`suite/run.py`) call
it automatically, so a swapped model never leaves a stale window behind.

## How it was validated

Set a distinctive `model_context_window` and read what Codex records in its own session
rollout (`$CODEX_HOME/sessions/**/rollout-*.jsonl`, field `model_context_window`):

| configured `model_context_window` | Codex-recorded window | = configured × 0.95 (its effective %) |
|---|---|---|
| 13337 | 12670 | ✅ 12670.15 |
| 40960 | 38912 | ✅ 38912.0 |

The recorded window derives from the configured value — not the 272K fallback (which would
record ~258400) — confirming the override is honored and drives Codex's context accounting.
With 40960 configured, Codex compacts at the trigger (34816) well below the 40960 ceiling
that previously 400'd.

**When to revisit:** this exception exists solely because Codex won't read the standard
`/v1/models` window for a keyless provider. If a future Codex fetches the catalog for local
providers (or the `ApiKeyModelDiscovery` gate is relaxed), re-run the zero-hit test above; if
Codex starts hitting `/v1/models`, the standard advertisement covers it and the config key
becomes redundant.
