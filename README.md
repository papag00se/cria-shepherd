# cria-shepherd

**A harness-agnostic shim that makes a small local model do real agentic coding.**

`cria-shepherd` sits between an OpenAI-compatible coding agent and a small local model
(9B-class, on llama.cpp or any OpenAI-compatible server) and rewrites the stream between
them. A 9B driving an agent loop alone stalls, loops on failing commands, leaks malformed
tool calls, and declares victory over broken code. cria catches each failure mode with a
targeted **heuristic assist** and hands the harness a completion it can use.

It speaks the OpenAI wire protocol on both sides — no harness plugin, no model fork — and
owns no executors: the harness still runs the tools and owns the workspace. Standard
library only, Python ≥ 3.11, local-first, and every decision emits a structured event.

The name: a *cria* is a baby llama.

```
  ┌─────────┐  /v1/chat/completions  ┌───────────────┐  /v1/chat/completions  ┌──────────────┐
  │ harness │ ─────────────────────► │ cria-shepherd │ ─────────────────────► │ model server │
  │ (agent) │  /v1/responses         │    :18085     │  applies assists       │   (:18084)   │
  └─────────┘ ◄───────────────────── └───────────────┘ ◄───────────────────── └──────────────┘
```

Point your harness at cria instead of at the model server. Endpoints:
`POST /v1/chat/completions`, `POST /v1/responses`, `GET /v1/models`, `GET /health`.

## The heuristic assists

The reason cria exists — five families, [full catalog in `docs/heuristic-assists.md`](docs/heuristic-assists.md):

- **Nudges** — directives the model *sees* to break loops: repetition, thrash,
  rumination, tunnel-vision, and read-without-write guards.
- **Massages** — silent output repairs the model never sees: `write_file` lowered to a
  byte-exact `base64` shell call, leaked-tool-call recovery, JSON and `apply_patch` fixes.
- **Context shaping** — cria keeps every request under the model's window *itself*,
  whatever the harness sends: it auto-detects the real window, budgets for the tool
  schema, reduces oversized tool outputs, and trims the oldest turns so the request
  always fits — no reliance on the harness to compact — plus a destructive-overwrite guard.
- **Probes** — cria makes its own read-only calls for ground truth: a syntax floor
  (`py_compile`/`node --check`) and a completion gate that runs tests on any "done" claim.
- **Reasoned guidance** — a cheap local reasoner drafts a plan up front, and on a stuck
  loop authors the next step from fresh ground truth instead of a canned nudge.

## Design doctrine

The *why* behind those mechanisms is a set of hard-won rules — truncation is a footgun,
deterministic code gathers facts while a reasoner judges, assists are footguns, fail closed,
cria never ends a session to a human. They are collected in
**[`docs/principles.md`](docs/principles.md)**, with [`AGENTS.md`](AGENTS.md) as the entry
point for anyone (human or agent) about to change cria's behavior.

## Install

Requires Python ≥ 3.11 and an OpenAI-compatible model server (llama.cpp is the reference)
already serving your model.

```bash
git clone https://github.com/papag00se/cria-shepherd.git
cd cria-shepherd
pip install -e .          # installs the `cria` and `cria-tail` scripts; no third-party deps
```

## Configure

cria auto-discovers `~/.cria/cria.toml` then `./cria.toml` (deep-merged, cwd wins), or pass
`--config`:

```bash
mkdir -p ~/.cria && cp cria.example.toml ~/.cria/cria.toml && $EDITOR ~/.cria/cria.toml
```

Minimum config — a transparent, assist-applying proxy in front of one model server:

```toml
[server]
port = 18085                            # 18084 = raw model, 18085 = cria

[defaults]
base_url = "http://127.0.0.1:18084"     # shared endpoint for backends that omit their own
```

cria uses ONE config model: **`[backends]`** say WHERE a model runs (transport `http` | `cli`);
**`[roles]`** bind a backend to the sampling + reasoning cria attaches to every request for that
role (applied per request — change = cria restart, not a model reload). cria addresses four roles —
`classifier`, `reasoner`, `coder`, `compactor`:

```toml
[backends.local]
transport = "http"
base_url  = "http://127.0.0.1:18084"    # a served (keyless) endpoint — cria uses the loaded model

[roles.coder]
backend        = "local"
reasoning      = "on"                    # "on" | "off" | "auto"
temperature    = 0.0
repeat_penalty = 1.05                    # also: top_p · top_k · min_p · max_tokens · output_reserve
```

Route by task type through a `[failover]` chain, and escalate off-box by adding a **keyed** backend
(`api_key_env = "GROQ_API_KEY"` + `model = "…"`) or a `transport = "cli"` backend (the `claude`
CLI) and appending its role to the chain — a role whose backend needs a missing key/binary is
simply skipped, so the chain collapses to whatever resolves. Secrets stay in the environment (the
config names the env var, never the key). Model **launch** settings (context, quant, GPU) belong to
the model server, not cria — see [`docs/model-settings.md`](docs/model-settings.md). Every key is
documented inline in [`cria.example.toml`](cria.example.toml).

## Run

```bash
python -m cria             # auto-discovers ~/.cria/cria.toml; flags: --host --port --log-level --config
```

Then point your harness's model client at `http://127.0.0.1:18085/v1`. Chat-Completions
harnesses just set that base URL; Responses-API harnesses (e.g. Codex) point their
provider there with `wire_api = "responses"` and no API key. You don't have to tune the
harness's context-window to the model — cria discovers the real window and keeps every
request under it regardless. Each response opens with a `⟦cria⟧ <role> · <model>` line so
you can see cria is in the loop.

## Observe & test

Every action logs a structured event with an explicit `reason` to
`~/.cria/logs/cria-YYYYMMDD.jsonl`; inspect with the bundled tool. Tests are stdlib-only
with a fake upstream — no GPU or network.

```bash
cria-tail -f               # follow the log  ·  --decisions  ·  --turn <id>
python -m pytest
```

## Background

cria-shepherd is the Python form of the "Shephard" research prototyped in a Rust fork of
the Codex CLI; that fork is the research vehicle, the specs it produced are the
deliverable. See [`docs/heuristic-assists.md`](docs/heuristic-assists.md) and
[`docs/shephard.md`](docs/shephard.md).
