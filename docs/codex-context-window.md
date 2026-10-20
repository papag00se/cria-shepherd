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
None of this enables cria's context floor or any new assist. Faithful preceding usage is
necessary, not sufficient: Codex estimates new tool results locally before the next native
measurement. Measured on the phi4 / Java captures (A4/A5/A6), that local estimate is chars/4 of the
`function_call_output` items appended since the last report — a compaction followed every request where
reported usage plus those outputs reached the trigger, and call *arguments* were not part of it. At L4+
the outputs cria itself causes (gate transport pages, the survey riding lowered tool results) therefore
count against the harness's trigger even though the model never reads them; see
[the N1 measurement](audits/2026-10-11-n1-gate-plumbing-measurement.md).
The capability catalog must preserve the pinned client's actual output-budget
default (`bytes/10000`), not accidentally widen it to a context-sized token budget. The
CPU-only default-parity and dense-burst regressions are documented in the
[restoration evidence](audits/2026-10-08-l0-codex-default-output-restoration.md).

## What L1-L5 report: the model-visible context, pre-floor

At L1-L5 the existing usage facade reports **estimated continuing model-visible context**, not native generation consumption. `input_tokens` is the PRE-FLOOR size (chars/4 of messages + tool schema, the context floor's own estimate) of the conversation the **model** is shown for this session — not the whole inbound request. `output_tokens` is the same estimator applied to the public reply that can return as model-visible history: public content and calls, with human-only indicator/transcript content and gate plumbing handled by their canonical projections. Private reasoning fields do not become that history. Reply sizing happens before synthetic lowering, so harness execution scaffolding is not mistaken for coder text. One owner, `cria/modelview.py`:

- **Loop turns** (coder, gate survey/launch/poll, transport pages, completion checks; Chat and
  Responses, stream and buffered): `Loop.visible_context_tokens`, which sizes the exact framing the
  coder prompt is built from (`_frame_for_item`, plan-off form) before the drive. Gate-transport
  turns make no upstream call and get the same number from the same request messages.
- **Proxied turns, including a harness compaction request**: `modelview.visible_tokens` of the body
  the model is shown (post focus-trim), or, for a compaction request, of the conversation being
  compacted (not the summary prompt cria rebuilds it into).
- **Out of the number:** cria's completion-gate plumbing and results that `clean_gate_results`
  removes (survey/launch/poll arguments, base64 pages), blanked `⟦cria⟧` status turns, and the
  harness's own agent prompt. **In:** cria's coder system prompt, the Responses `instructions`
  (folded into it), the tool hint, the cleaned gate verdicts, and the tool schema.
- **Not multiplied by `tokenratio`** — that is the floor's conservative safety factor (rise fast, ~1.6 on
  tiny judge calls), not a calibrated estimate; phi4's coder frames measure 1.02x chars/4.
- **Not in it:** per-turn steers/facts a coder call appends after framing, and (planner ON only) the
  step prompt. The size is taken before cria's own self-compaction and before `contextfloor.fit`.

- **L1/L2** (no loop, no floor): the proxied body as the model receives it (`modelview.visible_tokens`
  of the post-focus-trim body), still a chars/4 estimate and unchanged from before for bodies without a
  stamped gate call. The floor/refit statements below apply to L3-L5 only; at L1/L2 the server's own
  answer settles window fit, as it always did.

The usage object labels these top-level counts with `context_estimate: {estimated: true, scope: "continuing-model-visible-context", method: "contextfloor.est_total"}`. It also carries the **unchanged original Chat-Completions usage object** under `native_usage`, including native cached-input/output details. Responses JSON and SSE preserve both fields; native detail counts are not attached to estimated context counts. Native consumption, billing and human performance metrics must use the native object or the original upstream events/captures, never the facade estimate. Missing native usage stays missing/empty, not an invented measured zero. No private-token count is inferred by subtracting chars/4 reasoning estimates from native consumption. L0's standard measured usage and details are unchanged.

Why: a harness compacts when the reported size crosses its trigger. Counting gate plumbing made
phi4 (16,384 window; Codex trigger `int(16384*.85)=13,926`) compact 11-48 times per L5 cell — 31 of 31
over-trigger reports followed by a Codex compaction in `feed-pipeline-java_phi4_codex_poff_1791646575`
— while the model never read more than ~10.5K tokens; each compaction erased the coder's real
history. Real work still compacts: a genuinely large conversation reports large, and the harness's
configured trigger/reserve are unchanged.

Why this cannot repeat the under-reporting incidents (`docs/goals/compaction-live-report.md` runs 3-4;
L0 Ornith HTTP400, above): both had no floor in effect. At L3-L5 `contextfloor.fit` plus the measured
final-wire refit (`Upstream._prep`) fit the wire to the window whatever the harness is told, and the
reported number is the pre-floor model-visible size, so it only under-counts cria-authored additions
of a few hundred bytes. L0 is untouched (native usage, above). Chat-Completions **streaming** reports
no cria usage at all (upstream's own usage, if any, passes through); that is unchanged.
Tests: `tests/test_model_visible_usage.py` (real captured Codex requests), `tests/test_continuing_context_usage.py` (context/native separation through production reporting and Chat/Responses JSON/SSE), and `tests/test_pinned_codex_continuing_context.py` (actual pinned Codex with a sandboxed isolated home and fake endpoints only). The pinned-client controls demonstrate premature compaction under the old consumption contract, retention of the public action/result under the corrected projection, and legitimate compaction for large public output. This establishes the local accounting/compaction boundary, not usefulness causality across whole runs.

## Stable history after final-wire fitting

For requests with a session identity, `Upstream._prep` retains the floor's exact labelled replacements and removals while their source prefix remains unchanged and edited historical sources have not become live input. Appending a turn does not regenerate the early compaction note or restore a previously reduced caller persona. Changed source evidence invalidates history reuse; an unchanged-prefix rewind also invalidates edits that now touch the current request, its live notes or recent tail and paired calls. Invalidated history is fitted afresh under its current protection obligations. Changed caller spans are never replaced with stale instructions. New tasks, models and assist selections have separate fitting scope, and auxiliary roles do not inherit coder state. The process-local session/role store is bounded; restart or eviction loses reuse state, not source evidence.

Retained edits and previous-prefix bytes belong to one `Upstream` instance and an explicit nonempty session identity. Another instance starts fresh even when it uses the same URL and session string; requests without a session identity do not retain or inherit those edits. Token-density observations have a separate existing scope: `tokenratio` learns per model across the process. Those measurements can change fitting pressure across requests without transferring any history. Fixed-window test oracles specify `safety_override` for their declared density and leave learned observations intact.

Only actual overflow starts another reduction. History dropping aims to leave 25% headroom, yielding to the protected live core; headroom alone never authorizes sacrificing a protected anchor. If the hard window still requires sacrificing a historical anchor, feasibility is judged against the hard budget even when the smaller headroom target cannot be attained. Each new reduction uses original evidence rather than accumulating summaries of summaries. The existing lossless-first reductions, truthful labels, paired-tool cleanup, measured final-wire refit and L0–L2 exclusion still apply. Neither this headroom nor reuse changes generation caps or planner settings.

Stopping and anchor-sacrifice decisions measure complete rendered replacement notes, including their stubs, provenance, modified paths and any retained notes. Digest allowances are not estimates of complete note size. Caller, restored-file and tool-result labels count in the same whole-request budget; message and schema rounding cannot accumulate hidden fractions. If later wire transforms add text, `_prep` refits the original input with that measured growth budgeted separately. With a known window and no native measurement, residual estimated overflow is refused before capture or transport. Native final-template measurement remains authoritative when available.

The effective output reservation yields to the final required input after reduction as well as to the initial live core. Complete disclosures and reduced caller/restored text can change that requirement. If the surviving input fits the hard window after all reduction levers, it is prepared with the remaining output room; the floor reports both the requested and effective reservations. This does not set or change a generation cap. Prefix and wire-growth measurements explicitly declare `reshape=None`, so they do not add false reshape counts to the operator's ledger.

The coder system's permission summary is independent of build output. New validated dependency locations are dated observations after their first source tool result; they do not alter that system or older observations. A new continuation's inventory is a fixed reference to the native paired calls/results and their own availability labels. No changing result count or id list is copied into earlier handoff text. Legacy relocation requires a known frame lead and a complete exact footer at the end; a header-prefix match in quoted or unknown handoff prose is insufficient. The fixed reference replaces only that recognized footer, whose entire literal text (including unmatched historical IDs) is preserved in a separate quotation appended after the existing history before fitting. The quotation makes no current availability claim. Only the floor may reduce it, with a label. Typed producer identity makes relocated historical wording reducible without displacing the actual current request, consuming live-tail protection or acquiring anchor protection from its quoted text. Unknown passages stay byte-identical. These projections are derived from the offered history without another session cache.

Each prepared request with a session identity emits `context.prefix`, comparing against the previous prepared request in that session, including intervening auxiliary calls. `phase` and `previous_phase` disclose role changes; only fitting state is partitioned by role. `shared_bytes`, `previous_bytes` and `request_bytes` count UTF-8 bytes. `basis=rendered-prompt` means the server-rendered template was available through existing measurement/capture; otherwise `basis=messages-and-tools` explicitly identifies a deterministic schema/message projection, not native cache tokens. `reason`, `changed_message`, `marker` and `reduction_source_changed` distinguish appended turns, new reductions, changed source evidence, changed schemas and later wire transforms. `break_source` attributes the first changed message to `dependency_annotation`, `inventory`, `floor` or `other`; it is null for an initial, identical or appended request. A reduction elsewhere is insufficient evidence for attributing the first break to the floor. In particular, an inline caller-reduction label is attributed to the floor only when that message's offered source is unchanged; an earlier caller edit remains `other` even if later history is reduced in the same request. Attribution compares compact observation-only signatures, never confers authority on model-visible markers, and is independent of reduction reuse. Rejected measured trial fits do not become previous requests. Preparation is observed before transport: this event alone does not prove server acceptance or cache reuse. Fresh facts, restored text, surveys, optional evidence folds and harness compaction can still change earlier bytes; this floor state does not freeze live facts.

CPU-only regressions through real `Upstream._prep`: `tests/test_context_prefix_stability.py`, `tests/test_context_floor_disclosure_budget.py` and `tests/test_context_annotation_prefix.py`, including ordinary and exact `rank4-ablation` selections, production coder framing and handoff reframing, unchanged older dependency facts and handoffs, current-request protection, source attribution, caller-span retention, source invalidation, task/role/session isolation, complete disclosure accounting and measured-refit accounting.

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
and explicit reasoning effort `none` (unchanged by the output-default restoration). It uses the original generic Codex instructions retained
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
New rows also disclose model-visible historical wire envelopes under `wire_translations`,
including their authoritative event/count data. These are lossless translations, not a
claim of invisibility or byte-identical history.

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
