# AGENTS.md — cria-shepherd

cria is a harness-agnostic shim (stdlib-only Python, OpenAI wire protocol on both sides) that makes a small local model do real agentic coding. It sits between an OpenAI-compatible coding harness and the model, and rewrites the stream between them to catch the ways a 9B-class model derails on its own.

## Read first — before changing any behavior

1. **[`docs/principles.md`](docs/principles.md)** — the **design doctrine**: the rules that turned revelations into law while building cria. This is the *why* behind every mechanism. Read it before adding, removing, or changing an assist.
2. **[`docs/heuristic-assists.md`](docs/heuristic-assists.md)** — the *mechanisms* (the assists cria applies), the embodiments of the doctrine.
3. **[`README.md`](README.md)** — user-facing overview, wire diagram, config model.
4. **[`docs/shephard.md`](docs/shephard.md)** — the research lineage + the architectural boundary principles (owns no executors / no rendering; session-scoped guard state).

## Before anything else: it is always cria's fault

**The phrase "it's the model's fault" is banned here, in every form** — "the model failed", "a model
limitation", "a real model result, not our bug", "that's just how this model behaves". Whatever the
coder did, cria let it happen; the only question is which assist was absent, silent, mistimed, or
wrong. A small model derailing is not an explanation, it is the PROBLEM STATEMENT — restating it
ends an investigation exactly where cria's work begins. Rumination is the rumination steer failing
to land. A false completion claim is a chance to redirect that cria did not take. Score the work
honestly — a usefulness percentage measures delivered code — but never let a low score become a
verdict on the weights. See [principle 16](docs/principles.md#16-it-is-always-crias-fault-the-models-fault-is-not-a-finding),
which carries the incident that made this a ban rather than a preference.

## The doctrine in one screen (full text in [`docs/principles.md`](docs/principles.md))

- **Ground truth over judgment** — deterministic code GATHERS facts; a reasoner JUDGES. Verify by *doing* (cria runs its own read-only probes), not by reading the model's claim. Files alone are never signal. Surface every metric from the authoritative event, never a re-count or text-match. Don't fear an extra reasoner call that grounds the next action — a purposeful call is cheap next to the coder churn (re-fetches, failed edits, gate loops) it prevents. **A single focused question is a first-class tool**: when deterministic code reaches for a keyword/verb list or a proximity window to settle what is really a judgment, ask instead. That is not extra inference — it is the cheaper half of the trade, and it avoids a pattern that must be retuned every time reality writes a sentence it did not anticipate (measured: one such rule took four revisions and three false positives in four runs).
- **Never destroy information the model reads** — truncation is a footgun (any clip is an undetectable lie); the context floor is the ONE lossless window-fit point, and any reduction it does make is LABELLED. Never cap output for latency. **Never speak over a tool**: cria may SELECT which of a checker's real lines to show, but never substitute its own words for what the tool actually said (see docs/audits/2026-07-26-tool-voice-anomaly-audit.md).
- **Keep cria's own artifacts out of the user's tree** — cria's config, plan mirror and scratch live in cria's dir, never the workspace. The ONE exception is deliberate: an oversized fetch/search is spilled to `./tmp/read-only/` inside the workspace *because the model must be able to grep it*; that dir is guarded from edits and is the only thing cria writes there.
- **Fail safe** — fail CLOSED on completion (an undecidable judge means NOT done); fail open only toward "keep working." Two acknowledged fail-OPEN exits remain, both bounded and deliberate: no reasoner AND no shell (nothing can verify at all), and the MAX_COMPLETION_CHECKS bound that stops a task the coder genuinely cannot finish from looping forever. **cria must NEVER end a session by handing back to a human.** Measure prevalence before building a heuristic; **it is always cria's fault** (see the top of this file).
- **Assists are footguns** — the bar to ADD is high; interventions are additive / regression-only (never block the first fix, never delete correct content); silence over noise; **no fallbacks — fix upstream.**
- **A wire invariant belongs at the wire** — if a property must be true of the body the model RECEIVES (strict role alternation, no orphan `tool`, no malformed historical tool_call), enforce it in `Upstream._prep`, the last point before serialization. A transform run at a call site is undone by anything appended downstream, and ordering two lines per call site is a band-aid per site. Carry the role's intent as a cria-internal body hint, consume and strip it at the wire, keep it opt-in so models that don't need it ship byte-identical bodies. And fix the path that PRODUCED the incident, not the one that resembles it — the phase is on every captured body; a census takes one command.
- **Invisible & agnostic** — the model never sees the literal token "cria" (`⟦ctx:…⟧` markers only); agnostic across harness, model, prompt, and language.

## Official model names — use these exact project identities

`gemma4_12b`, `ornith1.5_9b`, `ling3.0_tiny`, `bonsai2`, `k2_horizon_7b`, `phi4`, `qwen3.8_9b_distill` are the official names (operator, 2026-09-30). Gemma4 and Gemma4 QAT are **one** `gemma4_12b` row. Use official names in reports and findings; legacy service/executable keys and historical artifact IDs are compatibility/provenance, not additional models. The single registry is `suite/model_names.py`; full policy and alias table: [`docs/model-names.md`](docs/model-names.md). Never rename stored run IDs/captures or reset a live campaign just to change display names. Unspecified models retain their names.

## Planning policy — OFF unless explicitly requested

Planning was deliberately retired from normal operation. Keep its implementation only for optional experiments. Config construction/loading and suite CLIs default to OFF; no engagement level (including L5), battery arm, model swap, or automation may enable it implicitly. Turning it ON requires explicit operator opt-in (`[planner].enabled = true` or `--planner on`). Do not infer consent from retained planner code, capability descriptions, or historical planner-on runs. Do not add a required `--planner off` flag. Commit `4a089fe7` incorrectly re-enabled it at L5; preserve regression coverage for that incident. Planner-on results do not measure the intended planner-off system.

## Hard operational rules (cria-specific)

- **Prompts live in `cria/prompts/*.txt`** (via `prompts.load` / `render` / `load_map`) — never an inline f-string the model reads.
- **The model never sees "cria"** — `⟦ctx:…⟧` for model-facing markers; `⟦cria⟧` (no colon) human notes are stripped before the model re-reads.
- **stdlib-first** — no third-party runtime deps; Python ≥ 3.11.
- **Secrets** — `env_file` is `~/.cria/.env` only; config names the env var, never the key.
- **Open the file before you quote a number about it.** Any claim about how a model behaves — a rate, a count, a "N of M" — requires that you have read at least one of the underlying captures **in full**: the prompt cria sent, the reply, the reasoning. `grep -c` over `~/.cria/calls` measures string frequency, not behavior. If your scorer re-implements a check cria already owns (a verdict parser, a phase's key, a tool-name match), it is wrong; import cria's. Five measurements of one subsystem were reported wrong in a single evening this way, each collapsing the instant a file was actually opened. See principle 23b.
- **Every fix needs a fails-before / passes-after test**; run `python -m pytest` (stdlib-only, fake upstream, no GPU/network).
- **Commits** — branch off `main` for changes; commit + push per unit of work; end commit messages with the co-author trailer.

## Live testing (the running service)

cria runs as `cria.service` in front of the local model on `:18084`; cria serves on `:18085`. After landing a behavior change: restart it (`sudo systemctl restart cria.service`, passwordless) and say what went live. Swap models via `scripts/live_model.py` / `scripts/swap_and_test.sh`. The live model is **ternary-bonsai** (`ternary_bonsai_27b_q2_0`). Every decision logs a structured event to `~/.cria/logs/cria-YYYYMMDD.jsonl` (`cria-tail -f`); per-call captures (exact body + rendered prompt
+ response) go to `~/.cria/calls/<session>/` when `capture_calls` is on.
