# The task battery — what we test cria against, and why

The suite's job is not to grade models. It is to put cria under the kinds of pressure real coding
work applies, so its own footguns surface where a call-by-call walk can find them. A task earns its
place by exercising machinery no other task reaches.

## Design rules

1. **Comparable weight.** Every task carries roughly four deliverables of similar size, the shape
   the original `ada-handles` set: research, implementation, tests, documentation. A single-skill
   exercise ("fix this one bug") produces a thin signal and finishes in five minutes.
2. **Deterministic scoring only.** `verify.py` runs the deliverables and scores what works. Never a
   model claim, never a judge verdict, never a green gate.
3. **The cheats must be worthless, and must be TESTED.** Every verifier here was run against a real
   cheat before it was trusted — see "Cheat-resistance" below.
4. **Seeded beats greenfield for finding cria bugs.** Greenfield tests research and creation.
   Seeded tasks start from code the model did not write, which is the only way to exercise reading
   an unfamiliar file, editing it surgically, and acting on gate output — where most of cria's
   measured footguns live.
5. **No task is ever special-cased in cria.** Doctrine. The suite doubles as cria's regression
   harness, and a prompt cria recognises is worthless as one.

## The 20 categories, and how they are covered

Five tasks, four categories each. The grouping follows how the work actually arrives — a billing
ticket brings config and logging with it; a new endpoint brings a schema change and validation.

| task | language | categories covered | status |
|---|---|---|---|
| `shipping-rates-py` | Python | **3** resolve failing tests · **1** feature from spec · **4** write missing tests · **19** update docs | built, proven both ways; verifier corrected 2026-08-10 (see below) |
| `cart-billing-go` | Go | **2** bug from user report · **12** logging/observability · **14** config/environment · **6** refactor without behaviour change | built, seed scores 0/4 |
| `orders-api-py` | Python | **8** new API endpoint · **9** database change · **5** integration tests · **11** security fix | planned |
| `feed-pipeline-py` | Python | **17** data transform · **10** optimise slow code · **13** concurrency · **20** code review | planned |
| `handles-cli-node` | JavaScript | **18** external service · **16** CLI tooling · **7** dependency migration · **15** containerise | planned |

Tooling for every one of these exists on the box: go, cargo, node, ruby+rspec, php+phpunit, mvn,
docker, and Go's race detector.

### Also in the suite (single-shape, kept for language coverage)

| task | language | shape |
|---|---|---|
| `ada-handles` | Python | API research + client + tests + live test + docs |
| `handles-{go,rust,node,ruby,php,java}` | six | the same problem, one language each — isolates the language variable |
| `rust-toml-cli` | Rust | must discover and use a third-party crate |
| `sqlite-inventory` | Python | schema design + SQL + CLI, fully offline |

## Cheat-resistance

Scoring a coding task is mostly a fight against the easy way out. Each defence below was checked by
committing the cheat and confirming the score:

| cheat | defence | measured |
|---|---|---|
| weaken or delete the failing test | seeded tests hashed against `seed/` | 1/4 |
| special-case the numbers in the ticket | hidden cases at inputs never shown | 3/4 |
| `assert True` × 20 | **mutation scoring** — seeded bugs the suite must catch | shallow 2/4, thorough 4/4 |
| mock the "live" test | must PASS with network and FAIL without (`unshare -rn`) | mocked 3/4, live 4/4 |
| import a logger and never call it | run real inputs, read what actually reached stderr | — |
| implement the feature but never test it | the model's own tests must mention it | — |

Two traps worth remembering, both found by running the verifier rather than trusting it:

- `go test` replays a **cached** pass without executing anything. Every Go invocation needs
  `-count=1`, or the network-blocked half of a liveness check succeeds and a genuinely live test
  scores as mocked.
- Hidden expectations must be **computed, not recalled**. One of mine was wrong (7.77 × 7 with
  WELCOME10 rounds to 52.87, not 52.89) and would have failed a correct solution.

## Seeding

A task shipping a `seed/` directory has it copied into the workspace and committed before the run,
so `git status` is clean and the model's own diff stays legible to it. Hidden tests live in
`hidden/` and are copied in only at scoring time — nothing in the workspace hints at them during
the run.


## Verifier corrections found by running the battery

**`shipping-rates-py`, 2026-08-10 — `suite_green_tests_intact` punished the task's own instruction.**
The check demanded the seeded test file be byte-identical to the seed. The prompt says *"Don't
change what the tests assert"* and, two paragraphs later, *"Add it, with tests"* — and the obvious
place to add tests is the file that already has them. The first baseline run caught it: gemma4
appended three correct express tests, deleted nothing, weakened nothing, left the suite green at 10
passed, and lost the point. Its true score was 4/4, recorded as 3/4.

Byte-identity is now per-test-function integrity: every seeded test must still exist with its source
unchanged, and additions are free. The anti-cheat is intact and was re-proven both ways — a weakened
assertion and a deleted test are each still caught, while the honest solution scores 4/4.

The general lesson for the remaining five: a verifier can be wrong by being too STRICT, not only too
lax, and the tell is a plausible-looking near miss rather than an all-zero column. The status tool
catches all-zero automatically; this class needs a human to read the diff.
