# AGENTS.md — cria-shepherd

cria is a harness-agnostic shim (stdlib-only Python, OpenAI wire protocol on both sides) that
makes a small local model do real agentic coding. It sits between an OpenAI-compatible coding
harness and the model, and rewrites the stream between them to catch the ways a 9B-class model
derails on its own.

## Read first — before changing any behavior

1. **[`docs/principles.md`](docs/principles.md)** — the **design doctrine**: the rules that turned
   revelations into law while building cria. This is the *why* behind every mechanism. Read it
   before adding, removing, or changing an assist.
2. **[`docs/heuristic-assists.md`](docs/heuristic-assists.md)** — the *mechanisms* (the assists cria
   applies), the embodiments of the doctrine.
3. **[`README.md`](README.md)** — user-facing overview, wire diagram, config model.
4. **[`docs/shephard.md`](docs/shephard.md)** — the research lineage + the architectural boundary
   principles (owns no executors / no rendering; session-scoped guard state).

## The doctrine in one screen (full text in [`docs/principles.md`](docs/principles.md))

- **Ground truth over judgment** — deterministic code GATHERS facts; a reasoner JUDGES. Verify by
  *doing* (cria runs its own read-only probes), not by reading the model's claim. Files alone are
  never signal. Surface every metric from the authoritative event, never a re-count or text-match.
- **Never destroy information the model reads** — truncation is a footgun (any clip is an
  undetectable lie); the context floor is the ONE lossless window-fit point. Never cap output for
  latency. Never pollute the user's workspace.
- **Fail safe** — fail CLOSED on completion (an undecidable judge means NOT done); fail open only
  toward "keep working." **cria must NEVER end a session by handing back to a human.** Measure
  prevalence before building a heuristic; assume cria caused it until proven otherwise.
- **Assists are footguns** — the bar to ADD is high; interventions are additive / regression-only
  (never block the first fix, never delete correct content); silence over noise; **no fallbacks —
  fix upstream.**
- **Invisible & agnostic** — the model never sees the literal token "cria" (`⟦ctx:…⟧` markers only);
  agnostic across harness, model, prompt, and language.

## Hard operational rules (cria-specific)

- **Prompts live in `cria/prompts/*.txt`** (via `prompts.load` / `render` / `load_map`) — never an
  inline f-string the model reads.
- **The model never sees "cria"** — `⟦ctx:…⟧` for model-facing markers; `⟦cria⟧` (no colon) human
  notes are stripped before the model re-reads.
- **stdlib-first** — no third-party runtime deps; Python ≥ 3.11.
- **Secrets** — `env_file` is `~/.cria/.env` only; config names the env var, never the key.
- **Every fix needs a fails-before / passes-after test**; run `python -m pytest` (stdlib-only, fake
  upstream, no GPU/network).
- **Commits** — branch off `main` for changes; commit + push per unit of work; end commit messages
  with the co-author trailer.

## Live testing (the running service)

cria runs as `cria.service` in front of the local model on `:18084`; cria serves on `:18085`.
After landing a behavior change: restart it (`sudo systemctl restart cria.service`, passwordless)
and say what went live. Swap models via `scripts/live_model.py` / `scripts/swap_and_test.sh`. The
live model is **fabliq** (`fabliq_8b_reasoning_q6`). Every decision logs a structured event to
`~/.cria/logs/cria-YYYYMMDD.jsonl` (`cria-tail -f`); per-call captures (exact body + rendered prompt
+ response) go to `~/.cria/calls/<session>/` when `capture_calls` is on.
