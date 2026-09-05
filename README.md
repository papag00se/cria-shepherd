<div align="center">

# 🦙 cria-shepherd

**Your 8B can't do agentic coding. Shepherded, it can.**

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue) ![zero dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen) ![tests](https://img.shields.io/badge/tests-1591%20passing-brightgreen) ![local first](https://img.shields.io/badge/cloud-optional-9cf)

*A cria is a baby llama. It needs a shepherd.*

</div>

---

Small local models are terrible agents. Left alone in a coding loop, a 9B stalls, reruns the same failing command sixteen times, leaks mangled tool calls, invents API endpoints, and proudly declares victory over broken code.

cria-shepherd is a **compound AI system** that sits between your agent harness and your model server and fixes that. What the harness sees as one model endpoint is actually a crew: a classifier, a planner, a coder, a step critic, a completion judge, a steer author, a compactor — plus deterministic detectors, probes, verifiers, and repairs around every one of them. The capability comes from the structure, not the weights.

```
  ┌─────────┐  /v1/chat/completions  ┌───────────────┐  /v1/chat/completions  ┌──────────────┐
  │ harness │ ─────────────────────► │ cria-shepherd │ ─────────────────────► │ model server │
  │ (agent) │  /v1/responses         │    :18085     │  the whole crew        │   (:18084)   │
  └─────────┘ ◄───────────────────── └───────────────┘ ◄───────────────────── └──────────────┘
```

**The receipt:** a quantized local model, driven by cria through a stock coding harness, completed a real API-integration task fully unaided — working resolver, 12 passing unit tests, a *genuinely live* network test, and an accurate README — in 25 minutes. Every deliverable verified by running it, not by believing anyone.

## Sixty seconds to shepherded

```bash
git clone https://github.com/papag00se/cria-shepherd.git && cd cria-shepherd
pip install -e .                     # stdlib only — installs `cria` and `cria-tail`
cp cria.example.toml ~/.cria/cria.toml   # point [defaults].base_url at your model server
python -m cria                       # cria now serves :18085
```

Point your harness at `http://127.0.0.1:18085/v1` instead of the model server. That's it. Chat-Completions harnesses set a base URL; Responses-API harnesses (Codex) set `wire_api = "responses"`. No plugin, no model fork, no API key. A `⟦cria⟧` status ticker narrates the pipeline live — planning, steps, checks, compaction, running clock.

## Why it's different

**vs. server-side compound systems** (groq/compound and friends): their model mix is a product decision — cria's is a config file. Bind every role to one scrappy local 9B, or put the judges on a big cloud model and keep the coder local, or anything between. Failover chains handle whatever doesn't resolve. And cria **owns no executors** — every tool runs in *your* harness, on *your* machine, under *your* permissions. cria composes, interprets, verifies. It never runs your code itself.

**vs. "just use a bigger model"**: that's the point. The research question this repo exists to answer is how far structure alone can carry small weights — so we test the hardest configuration on purpose: every role played by one 8–27B, no cloud, no help.

## Battle-tested across the board

- **Seven models, 9B–27B, dense and MoE** — Ornith, Qwopus, Qwythos, Gemma 4 Fable, Mellum 2, Nemotron Elastic, Ternary-Bonsai. A model that breaks cria isn't a nuisance here — it's a requirement. Launch recipes per model in [`docs/model-settings.md`](docs/model-settings.md).
- **Harnesses**: exercised under Codex (Responses API) and Claude tooling; anything speaking OpenAI Chat-Completions works. Tools are matched by *family*, never by one harness's names.
- **Languages**: gates and probes discover each ecosystem's own checks — parse floors, builds, linters, and test runners — for JS/TS, Python, Rust, Go, JVM (Maven and Gradle), .NET, PHP, Ruby, and Elixir, fresh from the workspace on every gate. Completion judges also receive three-valued build/source/test participation evidence: exact runner lines where available, honest unknowns where a green event did not identify what it reached.
- **Prompts**: hardened on multi-step agentic tasks — API integrations, database work, test suites, and CLI tools — evaluated by independent usefulness judgments over archived workspaces and exact call captures. cria never special-cases a benchmark prompt.

## The assists

Six families. Every one of them exists because a captured run failed without it — the full catalog with receipts lives in [`docs/heuristic-assists.md`](docs/heuristic-assists.md).

| family | what it does |
|---|---|
| **Nudges** | directives the model *sees* — break repetition, wheel-spinning, thrash, rumination, quiet flailing |
| **Massages** | silent repairs it *doesn't* — byte-exact write lowering, leaked/fused tool-call recovery, dialect salvage, poisoned-history repair |
| **Probes** | cria gathers its own ground truth — syntax floors, a completion gate that runs the repo's real checks on every "done" claim and transports their output losslessly in verified harness pages, computed facts (it counts the parens; the model just fixes them) |
| **Reasoned guidance** | detectors *trigger*, a reasoner *judges* — stuck-loop steers authored from fresh on-disk truth, living-plan re-derivation, step verdicts. Guarded both ways: fabricated steers and impossible judge claims get dropped, traced |
| **Context shaping** | every request fits the model's real window, cria's own responsibility — auto-detected, budget-aware, never truncating what the model must read; rolling self-compaction that points at files on disk instead of quoting stale copies |
| **Guards** | for how small models actually fail — invented endpoints (route-grounding against really-fetched specs), dropped/invented actions and completions (fail-closed accountability), false signals (an unfinished check reads UNFINISHED — never "passed", never "tool missing") |

## Planning mode

Optional plan-first loop, built for small attention spans:

- The planner **investigates before it plans** — a real tool loop over the repo, docs, and filesystem. Steps come from evidence, not vibes.
- The plan is **alive** — after each verified step (and on stalls) a reasoner re-derives what remains from the work actually done.
- Every step faces a **critic** with its own inspection tools, an approve-path brake that re-checks the disk, and fail-closed handling of anything unparseable.
- Noise steps — bare commands, dictated code, speculative endpoints — get scrubbed, whoever authored them. Deliverable coverage is checked at draft, at every re-derive, and at the end.

## The doctrine

Every mechanism above traces back to a rule learned from a captured failure: *assists are footguns. Never truncate what the model reads. Deterministic code gathers facts; a reasoner judges. Fail closed. State the fact or be silent. Never end a session to a human.* The full set — with the incidents that forged them — is in [`docs/principles.md`](docs/principles.md), and [`AGENTS.md`](AGENTS.md) is the entry point for anyone (human or agent) about to change cria's behavior.

## Roles & backends

Four roles — `classifier`, `reasoner`, `coder`, `compactor` — each bound to a backend with its own sampling and reasoning protocol:

```toml
[backends.local]
transport = "http"
base_url  = "http://127.0.0.1:18084"     # any OpenAI-compatible server

[backends.groq]                          # optional: escalate a role off-box
transport = "http"
base_url  = "https://api.groq.com/openai/v1"
api_key_env = "GROQ_API_KEY"             # the config names the var, never the key
model = "llama-3.3-70b"

[roles.coder]
backend = "local"
reasoning = "on"                         # on | off | auto — translated per backend dialect
temperature = 0.2

[failover]
coding = ["coder", "reasoner"]           # unresolvable backends are skipped, chain collapses
```

Backends can also be `transport = "cli"` subprocesses — ride your `claude` OAuth subscription as a role. Usage-limit pooling across backends is on the roadmap. Every key is documented inline in [`cria.example.toml`](cria.example.toml).

## Watch it work

```bash
cria-tail -f                         # follow the decision log — every action has a reason
python -m pytest                     # 1,591 stdlib-only tests, no GPU, no network
python suite/run.py --task ada-handles --model qwythos --harness codex --planner on
```

Every action emits a structured event to `~/.cria/logs/`. Every suite run archives its full evidence — workspace, per-call capture, event trail — because every future fix starts from a captured failure.

## Lineage

cria-shepherd is the Python form of the "Shephard" research first prototyped in a Rust fork of the Codex CLI. The fork was the lab; the specs it produced are the deliverable — see [`docs/shephard.md`](docs/shephard.md).
