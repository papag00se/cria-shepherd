# Goal doc — the full matrix run

Hand this to a `/goal` prompt. It states the objective, the method, what has already been settled
(so it is not re-litigated), and the traps that have cost real time.

---

## Objective

Run the full matrix — task × model × harness × planner — and turn the results into cria fixes.

**Success is not a score.** It is: every cell has evidence, every failure has been walked to a
cause, and every cause is either fixed upstream or written down as a model wall with one line of
proof. A matrix full of numbers nobody walked is a wasted day of GPU.

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

Walk every run call by call in `~/.cria/calls/<session>/`, pairing:

- `NNNN-<phase>.prompt.txt` — the exact bytes cria sent
- `NNNN-<phase>.reasoning.txt` — what the model thought about them

The reasoning prose is the evidence; a verdict alone is not. Walk the crew calls too — reasoner,
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
