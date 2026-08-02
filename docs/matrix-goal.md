# Goal doc — the full matrix run

Hand this to a `/goal` prompt. It states the objective, the method, what has already been settled
(so it is not re-litigated), and the traps that have cost real time.

---

## Objective — PHASE 1: the language sweep, and only that

Run **one task, seven languages**: the handles problem across `ada-handles` (Python) and
`handles-{go,rust,node,ruby,php,java}`, on the models we care about. Nothing else. The other task
types in `docs/task-battery.md` are built and proven but are a LATER matrix run — establish this
baseline first.

Why this cut: the handles problem is the one cria has the most history with, and holding the task
constant makes the language the only variable. A cell that fails then says something about that
language or about cria, not about a different problem.

**Success is not a score.** It is: every cell has evidence, every failure has been walked to a
cause, and every cause is either fixed upstream or written down as a model wall with one line of
proof. A matrix full of numbers nobody walked is a wasted day of GPU.

### The phase-1 grid

| | ada-handles | handles-go | handles-rust | handles-node | handles-ruby | handles-php | handles-java |
|---|---|---|---|---|---|---|---|
| ternary-bonsai | | | | | | | |
| qwythos | | | | | | | |
| gemma4 | | | | | | | |

Start with ternary-bonsai (the normal live model) across all seven, then widen. Planner off,
harness codex, unless a cell is specifically about those axes.

### Before the first run

```bash
python3 suite/preflight.py --warm
```

It must print READY. A cold `cargo` or `mvn` cache turns a 30-minute budget into a download, and
the cell then records a model failure that was really a machine failure. `docker` is reported
absent and that is fine — it is only used by a later task, whose Dockerfile is read, not built.

## How to run it

```bash
python3 suite/run.py --task <task> --model <model> --harness codex --planner off --note "<cell> <sha>"
```

- One run per code state. Never edit code or `cria/prompts/*` while a run is in flight — prompts load
  lazily, so an edit mid-run changes the running system (this killed a run: a deleted prompt file
  became six silent handler deaths).
- 30-minute wall per cell; `SUITE_WALL_MINUTES` overrides.
- Restart `cria.service` after landing a change, before the next run.
- `suite/verify.py` is the only judge. Never the model's claim, never a green gate.

### Swapping models

Sampling lives in `~/.cria/cria.toml` `[roles.*]` and is **per model** — update it when you swap, per
`docs/model-settings.md`. The recorded values there are the source of truth; the TOML often still
holds the previous model's numbers. Server-side settings (ctx, KV, template) live in
`~/.config/llama-fleet/models.toml` and need a model restart.

## How to find cria's faults (the part that matters)

Walk every run call by call in `~/.cria/calls/<session>/` — **every call, start to finish**, not a grep, not a sample, not a count over the files. Pair:

- `NNNN-<phase>.prompt.txt` — the exact bytes cria sent
- `NNNN-<phase>.reasoning.txt` — what the model thought about them

The reasoning prose is the evidence; a verdict alone is not. Reading the verdicts and skipping the reasoning misses the commonest shape in this project — the model finding the answer and then talking itself out of it. A count over the captures is not a walk and has repeatedly produced confident wrong answers; open the files. Walk the crew calls too — reasoner,
judges, compactor — not just the coder.

For every wrong turn, ask in this order:

1. Did cria state something false, stale, or contradicted by its own check output in the same prompt?
2. Did cria tell it to do something that cannot work?
3. Did cria withhold something it already had?
4. Did cria's **wording** cause it — not the fact, the phrasing?

Only after all four fail is it a model wall. Record model walls in one line and move on.

## Use the replay harness before running anything

A full run costs 30 minutes and yields one noisy number. Most questions do not need one.

```bash
python3 suite/replay.py --phase coder-s1 --n 40          # captured prompts, settings matrix
python3 suite/replay.py --phase satisfaction-confirm --forced-only
python3 suite/sampling_probe.py --trials 5               # literal-copy fidelity per model
python3 suite/ask_shape.py --models a,b,c --phase critic # A/B a wording across the fleet
```

Rules learned the hard way:

- **Score with cria's real parser, never a lookalike.** `replay.cria_reads_verdict` imports cria's own
  `_fill_missing_verdict_flag` / `_consistent_word`. A scorer that merely looks for the literal key
  reported qwythos at 1/4 when cria accepts 4/4 — a "live defect" that did not exist.
- **n=4 is noise.** A model measured 1/4 at n=4 and 11/12 at n=12; a regression was reported on the
  strength of the first. Anything acted on needs n≥12.
- **Test the fleet before shipping, not after.** Two changes generalised from gemma4 alone were
  wrong: one broke the step critic (8/8 → 1/8), one was unnecessary for nine of ten models.
- **Cross-check a display against the data.** A reply "truncated mid-JSON" was truncated by the
  print statement, not the model.

## Settled — do not re-litigate

| Question | Answer | Evidence |
|---|---|---|
| Do sampling settings affect copying long literals? | **No.** Identical across every setting. | `sampling_probe.py`, 5 settings × 5 literals |
| Is `repeat_penalty` behind the long-address churn? | **No.** | same |
| Should every judge be asked for one word? | **No** — fixes the confirm, breaks the critic. | gemma4: confirm 0/10→10/10, critic 8/8→1/8 |
| Should the ask offer both shapes at once? | **No** — worst of the three. | zaya1 9/12 vs 11/12 |
| Can gemma4 copy a 60+ char opaque literal? | **Unreliably** — ~1 in 3, always case corruption, deterministic at temp 0. | bisected 60→120 chars |
| Does maven print a test failure's file/line? | **No** — only in `target/surefire-reports`. | real failing run |
| Is qwythos's critic verdict broken? | **No.** 6/6. The 1/4 was a scorer artefact. | re-measured with cria's parser |

### Fleet verdict readability (n=6, cria's own parser, greedy)

| model | confirm JSON | confirm word | critic JSON | critic word |
|---|---|---|---|---|
| qwythos | 6/6 | 6/6 | 6/6 | 6/6 |
| fabliq | 6/6 | 6/6 | 4/6 | 6/6 |
| mellum2 | 6/6 | 6/6 | 5/6 | **1/6** |
| nemotron-elastic | 6/6 | 6/6 | 5/6 | 6/6 |
| gemma4 | **0/6** | 6/6 | 5/6 | **1/6** |

Reads as: gemma4's confirm is the ONE real failure (0/6, reproduced at n=6, 10 and 14) — hence the
escalation in `_judge_completion`. The critic must KEEP its JSON ask: a word costs mellum2 and
gemma4 (1/6 each). Everything else already works, which is why nothing else changed.

## The battery

### Phase 1 — these seven, and nothing else

| task | language |
|---|---|
| `ada-handles` | Python |
| `handles-go` | Go |
| `handles-rust` | Rust |
| `handles-node` | JavaScript |
| `handles-ruby` | Ruby |
| `handles-php` | PHP |
| `handles-java` | Java |

### Later phases — built, proven, and deliberately NOT in phase 1

`shipping-rates-py`, `cart-billing-go`, `orders-api-py`, `feed-pipeline-py`, `handles-cli-node`
cover the other sixteen task categories (see `docs/task-battery.md`). Every one starts from seeded
code and every verifier has been checked against both a correct solution and a real cheat. They
wait until the language baseline is understood.

**Seeded** tasks (`failing-tests-py`, `bug-report-go`, `missing-tests-py`) start from existing code
instead of an empty directory — categories 3, 2 and 4 of the operator's battery list. That is the
axis that was missing entirely: every earlier task was greenfield, so nothing exercised reading a
file the model did not write, editing it surgically, or acting on gate output, which is where most
of cria's measured footguns live.

Same problem in every language, on purpose: the matrix varies ONE thing at a time and this axis is
the language. A cell that fails therefore says something about the language or about cria, not
about a different task.

Toolchains for every verifier are installed on this box (go, cargo, node, ruby+rspec, php+phpunit,
mvn). A missing one scores `toolchain: not installed`, never a silent zero.

**Run the verifier against a known-good solution before trusting a cell.** Doing exactly that
caught a verifier bug that would have mis-scored every Go run: `go test` replays a cached pass
without executing anything, so the network-blocked half of the liveness check succeeded and a
genuinely live test was scored as mocked. `-count=1` fixes it. Assume the same class of trap exists
in the runners not yet exercised this way — rust, node, ruby, php, java are wired but only Go has
been proven in both directions (live scores 4/4, mocked scores 3/4).

## Open threads

- **The score is flat.** Ten runs since the big fixes: `2,0,2,2,1,2,1,3,2,0`. Best 3/4, no trend.
  Per-run variance exceeds any single fix's effect, so a single run cannot tell you whether a change
  helped. Either batch 3–5 runs per build and compare distributions, or judge fixes on their own
  merits and stop reading single scores as signal.
- **The lost point is usually the CLI entry point.** g20 defined `main()` and never called it; g21
  moved it without importing; g24 wrote a library with no entry block; g25 rewrote a working
  positional CLI into `--handle` — with cria's help.
- **The back half of a walled run is destructive.** g21 and g25 both had a working deliverable
  mid-run and broke it by the wall. The two runs that finished EARLY scored highest.
- **Crew cost.** cria's own reasoner/judge calls take ~50% of GPU time; the server has one slot, so
  every crew call blocks the coder. Measured, not yet shown to be harmful.

## Doctrine that keeps biting

`docs/principles.md` in full; the four that actually caught things this cycle:

- Assists are footguns — the bar to ADD is high, removing is usually safer.
- Silence over noise — a worse paraphrase of ground truth the model already holds is a footgun.
- Never state a false fact — including in a naming convention derived from a file extension.
- Fail closed — but check that the thing you are failing closed on is readable at all first.
