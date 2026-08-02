# Goal doc — the language ladder

One language. One model at a time. That model repeats until it scores **4/4**, then the next model
starts. When every model has passed, the language is done and the next one begins.

This is built to run for days. The thing that kills a long goal is not scope — it is that the
assistant's memory of what it did gets compacted away and then reconstructed wrongly. So **every
piece of state lives on disk**, and one command reports it:

```bash
python3 suite/ladder_status.py
```

That command is the only source of truth about progress. It reads `suite/results/results.jsonl`,
`docs/audits/ladder-walk.md`, and the process table. It reads nothing that anyone said.

Exit codes: **0** language complete · **1** work remains · **2** a run is in flight.

---

## The pacing rule — 15 minutes per deliverable

The old flat 30-minute wall was wrong in both directions: it killed runs that were still converging,
and it let a dead run burn the full half hour. The clock is now earned.

`ada-handles` has four deliverables, so a run gets four 15-minute intervals:

| at | the score must be at least | otherwise |
|:--|:--|:--|
| 15 min | 1 / 4 | killed, `terminal: milestone-miss-15min` |
| 30 min | 2 / 4 | killed, `milestone-miss-30min` |
| 45 min | 3 / 4 | killed, `milestone-miss-45min` |
| 60 min | 4 / 4 | killed, `budget-killed` |

**Which** deliverable arrives first does not matter — only the count. A run that keeps delivering
earns up to an hour, double the old wall. A run that is going nowhere is stopped in a quarter of the
time, and that saved time is the point: it buys walks and fixes instead of watching.

The workspace is scored by copying it and running the real verifier on the copy, so nothing cria
does appears in front of the coder mid-run. A miss is **re-checked after 20 seconds** before the
kill, because a single snapshot can catch a half-written file and score a healthy run as stalled.
An unreadable verdict never kills a run — the one direction this check may fail is toward
*keep working*.

---

## The order

Dense first, largest first. A model that is known to be capable failing tells you cria is at fault,
which is the cheaper thing to debug. A 760M-active model failing tells you almost nothing until the
big ones have passed.

| # | model | params | architecture | experts | kind | planner |
|--:|:--|:--|:--|:--|:--|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | — | dense | off |
| 2 | gemma4 | 12B | `gemma4` | — | dense | off |
| 3 | qwythos | 9B | `qwen35` | — | dense | off |
| 4 | qwopus | 9B | `qwen35` | — | dense | off |
| 5 | ornith | 9B | `qwen35` | — | dense | off |
| 6 | mellum2 | 12B / A2.5B | `mellum` | 64, 8 active | MoE | on |
| 7 | nemotron-elastic | 12B / A2B | `nemotron_h_moe` | 128, 6 active | MoE | on |
| 8 | zaya1 | 8.4B / A760M | `zaya` | 16, 1 active | MoE | on |
| 9 | fabliq | 8B / A1B | `lfm2moe` | 32, 4 active | MoE | on |

The order lives in **one place** — `LADDER` in `suite/ladder_status.py`. Nothing else defines it.

**dense/MoE here is read from each model's own GGUF header** (`general.architecture` plus
`<arch>.expert_count` / `expert_used_count`), not from a model card and not from the name. That
matters: fabliq sat on the dense list until the operator questioned it and the header was actually
read — it is an LFM2.5-8B-A1B, 32 experts with 4 active. `docs/model-settings.md` had labelled the
other three MoEs and left fabliq unlabelled, which reads as dense by omission. The fleet is five
dense and four MoE, not six and three.

**Moonlight-16B-A3B was considered and dropped** (2026-08-01) — no evidence it supports tool
calling, which cria's whole loop depends on. Reasoning and the conditions for revisiting are in
`docs/model-settings.md`; do not re-raise it without them.

`lfm25` is deliberately absent: its systemd unit exists but it has no entry in
`~/.config/llama-fleet/models.toml`, so starting it cannot work. Put it back when that is fixed.

### The planner column is a HYPOTHESIS, not a result

The operator's read: dense models cope with the planner off; MoEs need it on. **There is no evidence
for this yet** and it must not be written up as though there is. It is encoded as the starting
setting so the ladder *generates* the evidence — every row records the setting it ran under.

If a model stalls repeatedly at its hypothesised setting and a walk finds no cria fault, flipping the
planner is a legitimate experiment. Record the result either way; that is how the hypothesis becomes
a finding or dies.

---

## The loop

```
        ┌─────────────────────────────────────────────┐
        │  python3 suite/ladder_status.py             │
        └───────────────┬─────────────────────────────┘
                        │
        run ────────────┴──────────── walk ──────── fix ──────┐
         │                                                     │
         └── 4/4? ── yes ──> next model                        │
                     no ───> the run must be WALKED before ────┘
                             that model runs again
```

**Never two runs of a model without a walk between them.** A second run buries the first one's
capture and you learn nothing from either. The oracle enforces this — it will refuse to hand you a
run command while an unwalked failure exists.

### Running

Take the command from the oracle. Do not compose it by hand.

```bash
python3 suite/ladder_status.py        # prints the exact next command
```

While a run is in flight: **do not edit cria or anything in `cria/prompts/`.** Prompts load lazily,
so an edit changes the system that is running. This has killed a run — a deleted prompt file became
six silent handler deaths.

### Walking

Read the run call by call in its capture directory, pairing:

- `NNNN-<phase>.prompt.txt` — the exact bytes cria sent
- `NNNN-<phase>.reasoning.txt` — what the model made of them

Walk the crew calls too — reasoner, judges, compactor — not only the coder. Then write
`## <run_id>` into `docs/audits/ladder-walk.md` with what you found. The oracle looks for that
heading; a walk that exists only in a chat message is invisible to it, and is exactly what a
compaction deletes.

For every wrong turn, four questions in order:

> 1. Did cria state something **false or stale**?
> 2. Did cria tell it to do something **impossible**?
> 3. Did cria **withhold** something it already held?
> 4. Did cria's **wording** cause it?

Only when all four fail is it a model wall. Record model walls in one line and move on — do not
manufacture a finding to have one.

**RUN any code a steer or a prompt contains.** This is not optional and it is the lesson that cost
the most. Phase 1's C1 was walked, its steers were read, their diagnoses were correct, and the cell
was written up as "the advice was right." It was not: one steer's snippet reproduced the exact error
it was explaining, and the other's referenced an undefined name. Reading a fix is not checking it.

### Reading a run means reading EVERY call in it

A walk is reading the whole run — every prompt cria sent and every reasoning the model returned, in
order, from the first call to the last. Not a search. Not a sample. Not a count.

**Nothing here is a substitute for opening the file:**

- `grep` tells you a string's frequency, never what happened.
- "20 of 46 have X" is worth nothing until you have read one of the 46.
- Reading verdicts and skipping reasoning misses the case where the model found the answer and
  then talked itself out of it — which is the single most common shape in this project.
- A scorer that re-implements cria's parser measures your scorer. Import cria's.
- A prompt you wrote yourself is not the prompt cria sent. Replay the captured body.

**What full reading found that counting did not.** One set of 46 judge replies, read end to end:
a judge calling another harness's tool vocabulary, a read-only judge repeatedly trying to edit code,
consecutive retries ruling opposite ways on identical evidence, and complete verdicts written in
prose and discarded. Every count run over those same files had reported something else, and each
number collapsed the moment a file was opened.

**And it is how the mellum2 root cause was finally found** — after two walks of the same run had
blamed the model. Reading the plan in full showed cria mandating a JSON-RPC endpoint the task never
mentioned, contradicting itself two steps later by testing REST, and inventing the `--live` flag
that made the CLI score zero.

If you cannot name the turn numbers you read, you have not walked it.

### Fixing

The fix must obey `docs/principles.md`. In particular:

- **No mitigations, no fallbacks, no band-aids.** Find the upstream cause.
- **Never special-case this prompt.** cria must not know what `ada-handles` is. A fix that helps only
  this task is not a fix.
- **Measure prevalence first.** Base-rate the signal across `~/.cria/calls` before building anything.
  The "silently defeated 33%" is usually one replayed pathological event.
- **The bar to ADD is high.** Removing an assist is usually safer than adding one. An assist that
  fires on a clean signal is pure downside.
- **Every fix needs a test that fails before and passes after**, and `python3 -m pytest` must stay
  green.
- Restart `cria.service` after landing a change, before the next run, and say what went live.

Use the replay harness before spending a run on a question it can answer:

```bash
python3 suite/replay.py --phase coder-s1 --n 40
python3 suite/ask_shape.py --models a,b,c --phase critic
```

Score with **cria's real parsers**, never a lookalike — a scorer that merely looked for a literal key
reported a model at 1/4 that cria reads at 4/4. And **n=4 is noise**: one model measured 1/4 at n=4
and 11/12 at n=12. Anything acted on needs n≥12.

---

## Reporting

Keep `docs/audits/ladder-walk.md` current as you go — it is both the walk record and the progress
report the operator reads. One `## <run_id>` section per walked run: score, where the time went,
the four questions, the verdict, and the fix if there was one.

---

## When a model will not pass

After **5 walked failures with no new cria fault found**, the oracle marks the model `BLOCKED` and
moves to the next one. That is not a pass and the language does not complete — it exists so one
wedged model cannot silently eat days. Everything about it stays on the record.

Tune the number in `BLOCKED_AFTER` (`suite/ladder_status.py`) if 5 is wrong.

---

## Before the first run

```bash
python3 suite/preflight.py --warm
```

It must print **READY**. A cold cache turns a 15-minute interval into a download and the run then
records a model failure that was really a machine failure. `docker` reporting absent is fine.
Preflight also refuses to be ready while a previous run's `pip install` is still on `sys.path` —
that leak once shadowed an import for every Python process on the box for two days.

---

## Traps that have already cost real time

- **`verify.py` is the only judge — so audit the judge.** Never a model's claim, never a green gate.
  And the judge itself can be wrong in a way nothing else will catch: its handle-count check was
  `re.search(r"\d+", out)`, which a Cardano address satisfies on its own digits, so it passed
  address-only output for the whole ladder until a run was verified BY HAND. When a score looks too
  good, run the deliverable yourself before believing it.
- **`go test` replays a cached pass without running anything** — `-count=1` everywhere. This trap was
  found and fixed in the suite's verifier and then found again, unfixed, in cria's gate.
- **A single score is not signal.** Ten runs on identical code scored 2, 0, 2, 2, 1, 2, 1, 3, 2, 0.
  The ladder's answer to this is repetition-until-pass, not reading one number as a verdict.
- **Sampling is per model** and lives in `~/.cria/cria.toml` `[roles.*]`. The runner swaps the model
  and the planner; it does **not** update sampling. Set it from `docs/model-settings.md` when the
  ladder moves to a new model, or you are measuring the previous model's numbers.
- **Never `pkill -f`** — it matches the shell that invoked it.
- **Cross-check a display against the data.** A reply once looked "truncated mid-JSON"; the print
  statement had truncated it.

---

## The one rule about claiming progress

Never write that a run started, is running, or finished without the command output that proves it in
the same turn. "Cell 5 running next" was once written for a run that was never started, and nothing
contradicted it for hours. `ladder_status.py` exists so that no claim is needed — paste what it says.
