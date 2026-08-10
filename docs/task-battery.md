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

## The matrix: one kind of work per language

Every task carries four deliverables of similar weight, and **no two tasks share a language**. That
second rule is not decoration. A finding that only ever appears in Python cannot be told apart from
a Python-specific quirk in cria, and the project's whole claim is that it is harness- and
language-agnostic.

**Scores are percentages, not fractions.** A task carries as many checks as its work honestly
needs; the constraint that remains is that every check WITHIN a task costs roughly the same effort.
`suite/capabilities.py` and `suite/coverage.py` model what each task DEMANDS — wall clock does not:
`orders-api-py` takes twenty minutes because it polls an HTTP service and `shipping-rates-rb` takes
one because arithmetic is fast, and neither number says how much the model had to be good at.

**Five of the six now reach the network**, and in every case because the work genuinely calls for
it rather than to tick the box: the right fix for float money in Go is a decimal library, the right
fix for `split(",")` in Java is a CSV parser, and the right source for EU membership in Ruby is a
maintained gem rather than a list typed by hand (Croatia joined in 2013; Switzerland and Norway
never did). The measurement now depends on the package registries being up — a real cost, recorded
here rather than discovered later.

| task | language | categories covered | status |
|---|---|---|---|
| `shipping-rates-rb` | Ruby | **3** resolve failing tests · **1** feature from spec · **4** write missing tests · **19** update docs · country→zone via a gem | built 2026-08-10; 5 checks; seed 0%, honest 100%, four cheats measured |
| `cart-billing-go` | Go | **2** bug from user report · **12** logging/observability · **14** config/environment · **6** refactor · decimal money via a library | built; 5 checks; seed 0%, honest 100%, three cheats measured |
| `orders-api-py` | Python | **8** new API endpoint · **9** database change · **5** integration tests · **11** security fix | built; scored 4/4 by gemma4 and qwen35, so proven satisfiable |
| `feed-pipeline-java` | Java | **17** data transform · **10** optimise slow code · **13** concurrency · **20** code review · real CSV parser | built 2026-08-10; Maven; 5 checks; seed 0%, honest 100%, three cheats measured |
| `handles-cli-node` | JavaScript | **18** external service · **16** CLI tooling · **7** dependency migration · **15** containerise | built; seed scores 0/4; **4/4 not yet proven** |
| `rust-toml-cli` | Rust | discover and use a third-party crate under compile-loop pressure | built; scored 4/4 by gemma4, so proven satisfiable |

Toolchains for all six are on the box and need no network: ruby+minitest, go, python3, JDK 21,
node 22, cargo with a warm crate cache.

### Why the earlier selection was wrong

The first battery ran `shipping-rates-py`, `orders-api-py`, `feed-pipeline-py`, `missing-tests-py`,
`sqlite-inventory` and `rust-toml-cli` — five Python tasks and one Rust. The original five-task
design already had Go and JavaScript in it; the selection dropped both and replaced them with
Python. The `handles-*` ports were excluded on the grounds that one problem in seven languages is a
portability question rather than a variety one. That reasoning is right for measuring variety of
WORK and exactly backwards for measuring variety of LANGUAGE, and the trade was never surfaced.

Two tasks were ported rather than newly invented, so the work axis is unchanged and only the
language moved: `shipping-rates-py` → `shipping-rates-rb`, `feed-pipeline-py` → `feed-pipeline-java`.
The Python originals stay on disk. Retired from the matrix: `missing-tests-py` (its category 4 is
covered by the Ruby task) and `sqlite-inventory` (Python, and overlapping `orders-api-py`).

### Also in the suite, not in the matrix

| task | language | shape |
|---|---|---|
| `ada-handles` | Python | API research + client + tests + live test + docs — already mined for findings |
| `handles-{go,rust,node,ruby,php,java}` | six | the same problem, one language each — isolates the language variable |
| `shipping-rates-py`, `feed-pipeline-py` | Python | the originals the Ruby and Java members were ported from |
| `missing-tests-py`, `sqlite-inventory` | Python | retired from the matrix, kept as evidence |

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
