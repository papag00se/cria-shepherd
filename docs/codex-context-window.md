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

## Usage must be measured, not estimated

At L0, cria forwards the backend's measured prompt/completion/total token counts.
Responses maps the input/output names and preserves cached-input and output details;
the chars/4 inbound estimate is logging only. Replacing native usage with that estimate
prevents a harness from reaching its configured compaction trigger before the real window
fills. This caused the fresh Ornith shipping run's HTTP400 on 2026-10-07.

A native rejection with measured `n_prompt_tokens > n_ctx` maps to the Responses error
code `context_length_exceeded`, retaining the original message and counts. The rejection
body is captured before parsing consumes it. Codex0.159.3 exits on this typed error rather
than blindly reconnecting; it does **not** retroactively repair an overflowing session.
The real pinned-harness regression proves proactive compaction on native usage and a safe,
non-retrying terminal on overflow, through L0 and a fake backend without GPU inference.
None of this enables cria's context floor or any new assist.

## Incomplete tool history must remain renderable

A native `length` finish can leave a second tool call with an unfinished JSON argument.
Codex rejects that call, preserves its error result, and asks for context compaction.
Native templates parse historical argument JSON even on a tool-free compaction request;
forwarding the unfinished argument verbatim as executable-shaped JSON prevents compaction.
At the final wire boundary, L0 losslessly encodes malformed historical argument bytes under
`_unparsed`, retaining call identity and result without completing or guessing a command.
Valid arguments remain unchanged; argument recovery remains L1. A real pinned-harness
regression proves compaction and successful exit after an incomplete call, and native
CPU-only template replay proves the rejected original request renders after translation.
See [the incident and exact evidence](audits/2026-10-08-l0-incomplete-history-wire.md).

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

## Suite model metadata and writable homes

The restored L0 launcher also supplies `model_catalog_json` in Codex 0.159.3. Context
numbers alone do not supply tool capabilities: the unknown-model fallback omitted
`apply_patch` while its instructions still required it. The suite's explicit local
catalog declares the native freeform patch tool, actual runtime context, text input,
and no requested reasoning. It uses the original generic Codex instructions retained
in `cria/prompts/codex_suite_base.txt`, with the patch example corrected to the translated
`input` argument; it does not impersonate another model or enable planning.

Responses freeform tools translate to Chat-Completions functions with one string `input`.
The full input-format declaration remains in the schema description (not backend grammar
enforcement); replies return native `custom_tool_call` items, and calls/results round-trip
without changing patch bytes. Streaming and buffered paths use the request's tool types,
not tool-name guesses. Real pinned-Codex tests execute an allowed patch and reject an
outside-workspace patch through an L0 server and fake upstream, without GPU inference.

Each suite child now gets a fresh `codex-home` in its isolated cell install directory.
Only routing `config.toml` is copied; credentials, shared skills, sessions and databases
are not. Codex may write trust bookkeeping there without modifying the fingerprinted
canonical template. Each restored row records its catalog digest and cell home.

`l0_campaign.py --resume-after-launcher-repair OLD_SHA --campaign-revision NEW_SHA`
is an explicit, locked provenance transition, not a retry. It preserves only completed,
judged fresh runs from that campaign with their exact original revision and fleet snapshot;
remaining untouched cells run at the new immutable revision. All fleet assets must remain
exact, except inode/mtime changes for a byte-identically restored canonical Codex config.
The original manifest and repair history are retained. Reports must disclose this revision
boundary; the first result is neither overwritten nor reclassified as a repaired run.

For an operator-authorized infrastructure repair, the same explicit transition accepts
`--resume-after-infrastructure-repair OLD_SHA --preserve-infrastructure-failure RUN_ID`.
It validates that exact blocked, fresh `harness-error` attempt against the old inputs,
preserves its row digest and evidence, and consumes the slot as `infrastructure-failed`.
It never judges, credits, or retries that cell; the failed row remains rejected by ordinary
scoreable-row validation. Reconciliation blocks if the retained failure disappears,
changes, or gains a duplicate. Only untouched pending cells launch under the new revision.
A second explicit repair also validates and retains every prior failed-row digest unchanged.
For the current campaign, the operator requires a successful, independently judged replacement
run (0% is valid) before any subsequent cell proceeds. Supervision launches that replacement
serially in a distinct linked cohort, waits for its judgment, then resumes the original driver;
retained failures are historical evidence, never scores or permission to skip a cell.

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
