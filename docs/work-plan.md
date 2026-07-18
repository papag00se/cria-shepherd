# cria work plan — open items (2026-07-18)

Aggregated from the recent parity-audit / semantic-failure / routing discussions. Three epics
(B is the root and unblocks A and part of C), plus a quick-win convergence set. Nothing here is
committed yet; the "Done" section lists what already shipped.

---

## Epic B — Provider & config architecture  *(ROOT — do first; unblocks A's reasoner wiring)*

Today: a shared `[upstream]` endpoint + `[models.local.<role>]` (sampling + optional per-role
`base_url`) vs `[cloud_pools]`/`[providers]` (`openai`-kind HTTP-with-key **or** `claude_cli`).
The line between "local" and "cloud" is about to dissolve (groq.com / openrouter.ai are remote
OpenAI-compatible HTTP — neither "local like llama.cpp" nor "cloud like the Claude CLI").

- **B1 — Role→endpoint routing bug** *(confirmed; latent on a single box)*. Only the **coder**
  routes per-role; **classifier / reasoner / planner / compactor** are hardwired to the shared
  `upstream` object (server.py:205, 267, 270), so a per-role `base_url` is silently ignored for
  them. Same "silent capability degradation" class as the guard_probe_steer seed.
- **B2 — Dissolve `[upstream]`** — **SUBSUMED by B4 Scheme A (LOCKED)**: `[backends.*]` replace
  both `[upstream]` and `[models.local]`/`[cloud]`. Each role names a backend; per-endpoint config
  lives on the backend; a `[defaults]` block carries the shared `timeout_seconds` (7200). Fixes B1
  by construction (no shared `upstream` to hardwire to). Backward-compat: keep reading the old
  `[upstream]`/`[models.local]`/`[cloud_pools]` schema (deprecated, startup warning) so the live
  cria.toml keeps working through the migration.
- **B3 — De-llama.cpp-couple** so a role can target any OpenAI-compatible endpoint:
  - **B3a — Model naming** per role (multi-model endpoints need a named model; today local roles
    reject an alias and use `/v1/models` loaded-model). *Blocks groq/openrouter.* HIGH.
  - **B3b — Reasoning on/off portability** — `chat_template_kwargs.enable_thinking` + `<think>`
    prefill is llama.cpp-specific; add a per-endpoint reasoning strategy (template kwarg vs API
    param vs skip) so it doesn't silently no-op elsewhere.
  - **B3c — api_key** config for http roles (verify/expose `api_key_env`).
  - **B3d — Graceful degrade**: `/props` window (fallback 8192 → consider a per-role window
    override for large-context remote models), `/apply-template` capture, `/tokenize` calibration
    (all already fail soft — verify + widen defaults).
- **B4 — Transport taxonomy + rename**. The real axis is **transport**, and `local`/`cloud` is
  inverted from reality (llama.cpp="local" can be remote groq; "cloud"=locally-run subscription
  CLIs). Two transport families:
  - **`http`** — an OpenAI-compatible endpoint (base_url + optional api_key + named model):
    llama.cpp (localhost), groq, openrouter, OpenAI/Anthropic API. Location is just the URL.
  - **subprocess-OAuth CLI** — a locally-run CLI on a flat-rate subscription. Members:
    `claude_cli` (exists), **`codex`** (to add — Codex CLI → OpenAI via Codex Pro), and future
    CLIs. So the "cli" transport is a FAMILY, not a single `claude_cli` case.
  Rename lands with B2 (same schema surface). **LOCKED — Scheme A: `[backends.*]` + `[roles.*]`**:
  a backend is a named model target with an explicit `transport`; a role picks a backend +
  sampling/reasoning. This subsumes B2 entirely (backends replace both `[upstream]` and
  `[models.local]`/`[cloud]`), kills local/cloud, and makes the codex/claude family first-class.

    ```toml
    [backends.local-llama]  transport="http"  base_url="http://127.0.0.1:18084"  # loaded-model
    [backends.groq-70b]     transport="http"  base_url="https://api.groq.com/openai/v1" \
                            api_key_env="GROQ_KEY"  model="llama-3.3-70b-versatile"
    [backends.claude-sub]   transport="cli"   tool="claude"    # Claude Max, subprocess/OAuth
    [backends.codex-sub]    transport="cli"   tool="codex"     # Codex Pro,  subprocess/OAuth
    [defaults] timeout_seconds=7200                            # shared default; per-backend override

    [roles.coder]     backend="local-llama"  temperature=0.1
    [roles.reasoner]  backend="claude-sub"   reasoning="on"   temperature=0.6
    ```

## Epic A — Path parity: make plan-off (the user's path) ≥ the loop  *(depends on B1/B2)*

The plan-off/proxy path silently gets the degraded version of several interventions. Found by the
parity audit; the root methodological cause is "presence ≠ parity" (a shared function invoked with
a degraded default on one path).

- **A1 — Reasoned repetition redirect on plan-off** (THE SEED). Loop authors the redirect from
  ground truth + fresh disk + coder evidence (`_author_redirect`); plan-off gets a canned template
  (server.py:624). Extract a shared `author_redirect` both paths call. HIGH.
- **A2 — Reasoner critic on a plan-off `done`**. Loop runs `_verify` (a reasoner critic that must
  also approve a green gate — catches mocked/shallow passes); plan-off's `guard_gate_verdict` is
  objective-only → a green gate immediately ends the session. **A false `done` *ends* the run** —
  arguably worse than A1. HIGH.
- **A3 — Reasoned harness-compaction continuation** on plan-off. Loop re-plans from the compaction
  summary via the reasoner; plan-off appends a canned `reanchor.txt`. This is the "model disowns
  its own work after compaction" trigger. HIGH.
- **A4 — Streaming-transport guard coverage**. `_drive_direct_coder` runs only on the buffered
  transport (`_produce_completion`); `_produce_stream` is a bare proxy → all plan-off guards
  bypassed on streaming `/v1/chat/completions`. Latent (the Responses transport buffers). MED.
- **A5 — Durable parity check** *(the actual repair for the lost trust)*:
  (a) signature-harden `guard_probe_steer` — required keyword `author` + an explicit `CANNED`
  sentinel, so omission is a `TypeError`, not a silent downgrade;
  (b) an AST parity test (`test_path_parity.py`) with an enumerable registry of capability hooks
  both drive-paths must wire, extended to assert every role's calls go through role-resolution
  (no hardwired `upstream`).

## Epic C — Convergence & termination  *(independent; C1–C4 are quick confirmed wins)*

From the 019f770f semantic-failure walk (fabricated tests + buggy code that disagree; 169 calls,
never terminated).

- **C1 — Stall terminator** *(confirmed defect)*. There is **no termination path when the checks
  never go green** — the only off-ramp (satisfaction judge) is gated on `not last_gate_red`, so a
  never-green session churns until the user kills it. Add the mirror of the satisfaction off-ramp:
  persistent-RED across K cycles + a generous budget → end the session **back to the user**. HIGH.
- **C2 — No-progress sensor**: `gate_signature_persistence` — the same failure signature unchanged
  across K gates; also stop re-inserting identical ground truth the model already saw. Feeds C1.
- **C3 — Honest end-state report** to the user (raw record: drives, RED/GREEN gate counts,
  persistent signature, rewrite counts). Never labeled "ceiling"/"unsatisfiable" — the human draws
  the conclusion.
- **C4 — Vacuous-green as EVIDENCE, not a rule**. "green with 0 tests executed / no assertions" is
  only vacuous if tests were part of the ask — a reasoner judgment. Feed the fact to the
  completion/satisfaction judge (which holds the task text); do NOT deterministically block (would
  wedge a test-free task and push a weak model to fabricate tests).
- **C5 — Reasoned thrash-assist PROTOTYPE** *(the frontier bet; depends on B for reasoner
  routing)*. Gather a grounded evidence bundle (recurrence signature + code/test on disk + the
  model's own API bytes + no-progress trajectory + vacuous-green) → a no-tools **reasoner** (which
  is pluggable, so the "weak-model-guess" footgun is config-bounded, not fundamental) → author a
  grounded next-step on the existing steer channel. Anchored so it degrades gracefully (weak
  reasoner ≈ bare-fact reflection; strong reasoner = the real unlock). Gated behind C1.
- **C6 — self-recursion fact** *(demoted)*. "self-call with unchanged arg name" is NOT proof of
  infinite recursion (the name can be rebound; external state can terminate it). Only viable as a
  data-flow-sound, neutral-worded fact inside C5's evidence bundle — never a standalone "this
  recurses forever" verdict.

---

## Dependencies & recommended sequence
1. **C1–C4** first — independent, and C1 fixes a confirmed defect (fast, high-value, no deps).
2. **B (B1+B2+B4, then B3)** — the root; A's reasoner fixes need correct routing, and groq/
   openrouter need B3. Do the config refactor + rename together.
3. **A (A1–A3, A5 lands with A1; A4 alongside)** — rides on B's correctly-routed reasoner.
4. **C5** last — the reasoned thrash-assist, on the now-correctly-routed reasoner, behind C1.

## Done (recent, committed)
never-truncate overhaul · web_fetch/read exec-envelope strip · turn-stats fixes (tokens, calls,
🛡/🧰 ledger) · satisfaction-gate-on-green · validate-before-lower · normalize_tool_names ·
subtractive gate framing.
