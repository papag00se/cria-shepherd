# Phase 1 walk — the handles problem across seven languages

**Model** ternary-bonsai 27B · **harness** codex, planner off · **wall** 30 min/cell · **1 Aug 2026**

One problem in every language, so the language is the only variable. A walk means reading
EVERY call in the run end to end — never a grep, a sample or a count over the capture.
Each cell is read call by call
from `~/.cria/calls/<session>/`, pairing `NNNN-<phase>.prompt.txt` (what cria sent) with
`NNNN-<phase>.reasoning.txt` (what the model made of it). Scores come from `verify.py`, which runs
the deliverables — never from a claim.

For every wrong turn, four questions in order. Only when all four fail is it a model wall.

> 1. Did cria state something **false or stale**?
> 2. Did cria tell it to do something **impossible**?
> 3. Did cria **withhold** something it already held?
> 4. Did cria's **wording** cause it?

---

## Grid

| cell | language | score | calls | tok/s | terminal | cria fault |
|:--|:--|:--:|--:|--:|:--|:--|
| C1 | Python | 🔴 **0/4** | 24 | 39.1 | budget-killed | ⚠️ steer cost 9 of 30 min |
| C2 | Go | 🔴 **0/4** | 67 | 41.8 | budget-killed | ⚠️ gate could report unrun tests |
| C3 | Rust | 🔴 **0/4** | 55 | 33.8 | budget-killed | ✅ none — steers were accurate |
| C4 | JavaScript | 🟢 **4/4** | 45 | 24.9 | budget-killed | ✅ none |
| C5 | Ruby | ⬜ not run | — | — | — | — |
| C6 | PHP | ⬜ not run | — | — | — | — |
| C7 | Java | ⬜ not run | — | — | — | — |

**The headline:** JavaScript succeeded on the **lowest** throughput of the four — 24.9 tok/s against
Go's 41.8. It wasn't budget. Each failing language died on something its toolchain demands and
JavaScript never asks for.

---

## ada-handles

`~/.cria/calls/20260801T010006-019fbc56-649e-71b3-8ab8-595803d1f523` · **0/4** · 24 calls

| deliverable | | detail |
|:--|:--:|:--|
| unit tests | 🔴 | 7 failed, 3 passed |
| live test | 🔴 | no live-test file written |
| resolver CLI | 🔴 | `resolve_handle.py goose` → exit 3 |
| README | 🔴 | never written |

### Where the 30 minutes went

```
coder     16 calls   649s
reasoner   8 calls   638s   ← as much as the coder
────────────────────────────
                    1197s of an 1830s wall
```

Seven of those eight reasoner calls were **consecutive**, producing one directive. Each inspection
round re-sends the whole transcript plus every file read so far:

```
round 1    47K chars
round 2    62K chars
round 3    83K chars
round 4   102K chars   →   247 seconds for one call
```

That single steer cost **544 seconds — 9 of the 30 minutes**.

### What it was stuck on

One bug, from call 13 to the wall: mocking `urllib.request.urlopen`. The coder's helper built a
`MagicMock`, and `resp.read().decode()` handed back another mock instead of bytes:

```
TypeError: the JSON object must be str, bytes or bytearray, not MagicMock
```

Its own diagnosis at call 13 was **correct**: *"the mock chain isn't returning proper bytes/str
values."* It knew. What it could not find was why its fix didn't take. Call 15 is 11,617 characters
of private reasoning that traces the chain five separate times and concludes *"Wait, that should
work!"*, *"this should work"*, *"but the error says it got a MagicMock"* — a model correctly
refusing to believe a false premise it had been handed.

The premise was false in two places, and one of them was cria's.

### The four questions

| | |
|:--|:--|
| false or stale? | **YES — and it was cria's own code.** Steer 1 diagnosed the bug correctly, then told the coder to `patch(..., side_effect=_mock_urlopen(GOOSE_RESPONSE))`. Replayed verbatim, that snippet **reproduces the exact TypeError it was explaining** — `side_effect` set to a mock object makes `urlopen()` return that mock's *return value*, a fresh auto-mock, so `.read()` yields a mock again. |
| impossible? | **YES.** Steer 2's fix line was `resp_mock.__enter__ = lambda s=self: s`. `self` is not defined at module scope, where the helper lives. `NameError`. It cannot run. |
| withheld? | No. |
| wording? | Not the wording — the code. |

Steer 2's *prose* was exactly right, and better than anything the coder produced:
*"`MagicMock.__enter__()` yields a **new** MagicMock — not the one with `.read` set."* That is the
whole answer, and it is the one fact the coder never found on its own (call 15 asserts the
opposite: *"MagicMock's `__enter__` returns self by default"* — it does not).

So cria held the diagnosis the coder needed, said it correctly, and then buried it under a fix that
could not work. The coder rewrote the same test file **five times** against that advice, never wrote
the live test, never wrote the README.

Verified by running all four forms:

```
cria steer 1 verbatim                     TypeError: … not MagicMock   ← the bug it was fixing
same, with return_value= instead          TypeError: lambda takes 0 args, 1 given
cria steer 2's line, at module scope      NameError: name 'self' is not defined
__enter__.return_value = resp             OK                            ← what actually works
```

**Verdict: a cria fault of CONTENT, not only cost.** The earlier pass of this walk recorded "the
advice was right and the model understood it." That was wrong — I read the diagnoses, which were
right, and never ran the code, which was not.

**Fixed — two things:**

| | fix |
|:--|:--|
| the inspection loop was unbounded by size — one steer ate 9 of 30 minutes | [`2eaf2e1`](#) bounds it by size as well as rounds; worst chain 544s → 195s, throughput 24 → 67 calls |
| the steer author wrote code it cannot run | [`1d49456`](#) — the rule was narrow ("never retype a broken line") and permitted *inventing* a fix. Now: describe the change in words, never write code. Measured first: **19% of 1,544 captured steers shipped a code block.** |

---

## handles-go

`~/.cria/calls/20260801T013430-019fbc75-e4c1-79a1-bdac-ac8b2d2e5638` · **0/4** · 67 calls

| deliverable | | detail |
|:--|:--:|:--|
| unit tests | 🔴 | no passing test run |
| live test | 🔴 | no runnable suite to check |
| resolver CLI | 🔴 | `go run . goose` → exit 0, no output |
| README | 🔴 | never written |

Confirmed by hand: the workspace **does not compile**.

```
handles/api_test.go:76:2: expected declaration, found _
FAIL  handles-resolver/handles [setup failed]
```

### The four questions

| | |
|:--|:--|
| false or stale? | **No.** The gate ran `go build`, `go vet` and `go test` and surfaced that exact compile error to the coder in **11 separate prompts**. |
| impossible? | No. |
| withheld? | No — the error was in front of it repeatedly. |
| wording? | No. |

**Verdict: model wall.** A syntax error in a test file, shown eleven times, never fixed.

### But the walk found a separate cria defect

The gate ran `go test ./...` **148 times** in that run. Go replays a cached pass without executing
anything:

```
run 1                  ok  example.com/x  0.001s
run 2 (no edits)       ok  example.com/x  (cached)
run 2 with -count=1    ok  example.com/x  0.001s
```

So a green gate could rest on tests that **never ran** — and it hides precisely the failures that
come and go with no code change: a live test whose API is down, a flake, anything time-dependent.

**Fixed** — [`8fd698d`](#). Galling detail: I had found and fixed this identical trap in the suite's
own Go verifier hours earlier and never thought to check whether cria's gate carried the same
command. It did.

---

## handles-rust

`~/.cria/calls/20260801T020743-019fbc94-4d88-7581-a601-33bbc351a2d5` · **0/4** · 55 calls

| deliverable | | detail |
|:--|:--:|:--|
| unit tests | 🔴 | 7 passed, **2 failed** |
| live test | 🔴 | suite red, so liveness unverifiable |
| resolver CLI | 🔴 | `cargo run -- goose` → exit 101, runtime panic |
| README | 🔴 | never written |

Got the furthest of the failures. The panic:

```
thread 'main' panicked at hyper-util .../connect/http.rs:727:
A Tokio 1.x context was found, but timers are disabled.
Call `enable_time` on the runtime builder to enable timers.
```

### The four questions

| | |
|:--|:--|
| false or stale? | **No — the opposite.** Steer 47 caught cria's *own* stale output and corrected it: *"the E0507 errors cited (src/lib.rs:61) are from a previous build — your last edit already added `.clone()`."* |
| impossible? | No. |
| withheld? | No. Four steers, all naming real lines. |
| wording? | No. |

**Verdict: model wall plus clock.** Two failing assertions and an async-runtime misconfiguration.
cria behaved correctly throughout — recorded as a clean cell rather than dressed up as a finding.

One observation, not a defect: the coder **never once ran the binary** (`cargo run` appears zero
times in its tool calls), so the Tokio panic was invisible for the whole run. cria's gate runs
`check`/`clippy`/`test` and deliberately never executes arbitrary binaries, which is the right
call for a generic gate.

---

## handles-node

`~/.cria/calls/20260801T023958-019fbcb1-d430-7f90-b2ae-56e6b1802ca6` · **4/4** ✅ · 45 calls

| deliverable | | detail |
|:--|:--:|:--|
| unit tests | 🟢 | 4 passed |
| live test | 🟢 | passes with network, **fails without** — provably live |
| resolver CLI | 🟢 | `node src/index.js goose` → address + holder + count |
| README | 🟢 | install / run / test |

Independently re-checked by hand, because a verifier's first pass with a real model deserves the
same scrutiny as a failure:

```
$ node src/index.js goose
  cardano_address: addr1qxsfzsmy6y2seduagp6fx9pht4yz9nspxvzyldtv36p2uz0gz...
  holder_type:     wallet
  total_handles:   15

$ node --test                 → # pass 4  # fail 0
$ unshare -rn node --test     → # pass 3  # fail 1     ← the live test is real
```

### The four questions

Nothing went wrong to interrogate. **One steer in the whole run**, and it was a restraint —
"the checks found no error-class problems… make a small TARGETED edit rather than rewriting".

### What this cell says

```
coder        42 calls   561s     13s per call
reasoner      3 calls   514s
self-compact  1 call    192s
```

Crew share was **56%** — the same as everywhere else. What differed is that the coder's calls were
*cheap*: 13s each against C1's 40s, because JavaScript solutions are shorter and the prompts stayed
small. Same budget, nearly triple the turns.

**The success wasn't cria steering well. It was cria staying out of the way** — one steer, no
thrash, and a language with no compile step, no borrow checker, and no async runtime to configure.

---

## What this phase says so far

**Three cria defects found and fixed** — and the third is in the advice itself, which the first
pass of this walk wrongly cleared:

| | from | fix |
|:--|:--|:--|
| inspection loop unbounded by size — one steer ate 9 of 30 minutes | C1 | `2eaf2e1` |
| `go test` gate could report a pass it never ran | C2 | `8fd698d` |
| **the steer author wrote code it cannot run — both C1 steers shipped a broken fix under a correct diagnosis** | C1 | `1d49456` |

The method failure worth recording: I read the steers' *diagnoses*, found them accurate, and wrote
"the advice was right." I never ran the code they contained. Reading a fix is not checking it —
the same rule cria itself is built on (verify by doing, not by reading) applies to the walk.

**Two cells walked clean.** C3 and C4 produced no cria-side finding. Saying so plainly rather than
manufacturing one.

**The steer count tracks the outcome, inversely:**

| cell | steers | score |
|:--|--:|:--:|
| C4 JavaScript | 1 | 🟢 4/4 |
| C1 Python | 3 | 🔴 0/4 |
| C3 Rust | 4 | 🔴 0/4 |

Whether few steers *cause* success or merely accompany it is unresolved — a run that is going well
trips fewer detectors by construction. Worth watching across the remaining cells, not concluding
from three.

### Caveats a reader needs

- **Every cell was killed at the wall**, including the 4/4 — it had finished its deliverables and
  moved on. Read `terminal` beside `score`, never instead of it.
- **Crew share didn't move.** cria's own reasoner and judge calls take 47–62% of model time across
  these cells, and 54% median across 28 earlier sessions. The size bound capped the worst tail, not
  the total.
- **One run per cell is coverage, not a verdict.** Ten earlier runs of one task scored
  2, 0, 2, 2, 1, 2, 1, 3, 2, 0. Variance exceeds any single fix's effect.
- **Only Go and JavaScript verifiers have met a real model.** Ruby, PHP and Java are wired and
  smoke-tested but unproven, so a surprising result there is as likely to be the verifier as the
  model.
