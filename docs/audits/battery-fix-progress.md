# Battery walk — fix progress

Live status for the fixes from `battery-pair-walk.md` (15 classes) and `battery-language-bias.md`
(47 findings). Updated as each lands. **This file, not chat, is the status.**

## The rule these follow

Per-language tables are CORRECT and expected — every language gets its equivalent check. Two things
are defects: a HOLE in a table (one language missing the check its siblings have), and one
language's phrasing standing in for the general question (a matcher keyed to pytest's wording that
is inert on go/JUnit/jest). Python may legitimately carry extra handling because it can be the OS's
own language; that is a real difference, not an overfit.

## Status

| # | fix | group | state |
|---|---|---|---|
| 1 | off-menu recovered call is eaten silently → emit the refusal | critical | **done** |
| 2 | an empty turn must never satisfy completion | critical | **done** |
| 3 | foreign project instructions relayed as repo doctrine | critical | **done** |
| 4 | no_tests_found states a repo fact from a cria miss | false-fact | **done** |
| 5 | gate "0 collected" borrows pytest vocabulary | false-fact | **done** |
| 6 | "This list is complete" on a filtered listing | false-fact | **done** |
| 7 | uncounted-offline note blames the runner | false-fact | **done** |
| 8 | checkstyle injected as "the repo's own checks" | false-fact | **done** |
| 9 | fetch ledger's no-structure note | false-fact | superseded — the fetch ledger's no-structure note is only reachable on a web task; left as recorded |
| 10 | "flagged line on disk" on an exception finding | false-fact | **done** |
| 11 | ruby: minitest alongside rspec | table-hole | **done** |
| 12 | task runners (Rakefile/Makefile/…) are manifests | table-hole | **done** |
| 13 | java: syntax floor + cheap compile probe | table-hole | **done** |
| 14 | node: built-in `node --test` recognised | table-hole | **done** |
| 15 | runner tally: minitest + node TAP rows | table-hole | **done** |
| 16 | test floor beyond python | table-hole | **done** |
| 17 | stale-check trigger matches every language's test names | table-hole | **done** |
| 18 | one owner for ext→validator (writeproxy ← probediscovery) | one-owner | **done** |
| 19 | one owner for build-artifact skip sets | one-owner | **done** |
| 20 | program_token resolves head-first | entry-point | **done** |
| 21 | runnable_listing is an allowlist | entry-point | **done** |
| 22 | exec-intent prompt drops "must name a listed file" | entry-point | **done** |
| 23 | README corroboration weakens, never vetoes | entry-point | **done** |
| 24 | rejected edit payloads collapsed in replay | injection | **done** |
| 25 | compaction never replays a write payload | injection | **done** |
| 26 | empty `<think></think>` not replayed | injection | superseded by 24/25 — the empty `<think>` replay is the same asymmetry, fixed at the surviving-fabrication end |
| 27 | DICTATES held to a verbatim-quote test | injection | **done** |
| 28 | steer symbol/existence claims resolved against disk | injection | **done** |
| 29 | guards conditioned on the failure mode | injection | **done** |
| 30 | gate runs against a pristine copy | injection | **done** |
| 31 | remove the "change a test if its premise is wrong" clause | injection | **done** |
| 32 | coder-capability roster named from the workspace | prompt | **done** |
| 33 | install refusal remediates in the ecosystem it refused | prompt | **done** |
| 34 | write_isdir exemplar derived from the path | prompt | **done** |
| 35 | cheatsheet web_fetch exemplar | prompt | **done** |
| 36 | suite: live-test ext→runner map | suite | **done** |
| 37 | suite: session_live_evidence pytest literal | suite | **done** |
| 38 | suite: README probe python3 caveat | suite | **done** |

## Closed

All 38 landed or accounted for, each with a test that fails before and passes after, full suite green
at every step (2,915 → 3,049). Two were resolved differently from the walk's recommendation, after
reading why the code was the way it was:

- **The test-weakening exception was TIGHTENED, not removed.** The walk said delete it. Its original
  commit (`d8d0589`) shows it fixed a measured trap: in two walked runs a test asserted a false
  world-fact and the coder reached "so the test is wrong" three times and talked itself out of it,
  because cria had forbidden the only correct repair. Deleting it re-opens that. The precondition is
  now an EXTERNAL system, evidenced by a command run this session with its output quoted, and the
  test's own failure message is explicitly disqualified.
- **DICTATES still delivers.** The 2026-08-04 operator ruling stands. What changed is that the
  ruling's own reasoning — sighted dictation carried the ladder passes, blind dictation did the harm
  — is now enforced: a code span that appears in the evidence cria showed the author survives, one
  it invented is stripped, and the prose ships either way.

One bug of my own was caught by the suite mid-flight and is worth recording: the widened write
validator is prepended to the heredoc templates, which are `.format()`ed, so its dict literal's
braces read as format placeholders and took down every lowered write with `KeyError: "'"`. Rebuilt
brace-free, with a test that a real lowered write still builds.

## Fix 39 — the gate cleanup killed the gate

Landed after the fix batch, found by the assisted arm's first six cells.

Fix 22's litter cleanup deleted the untracked files the probes created, using `rm -rf` inside the
script cria hands the harness. **Codex's sandbox rejects any exec containing an `rm -f` style
command, and rejects the whole script.** So no probe section ever came back; `interpret_gate` read
that as "nothing ran" — which is correct and completely silent — and cria abstained from its largest
assist on every turn of every task in every language. 12/12 gate invocations rejected across the six
gemma4 cells before the arm was stopped.

`writeproxy.py:801` already records this exact sandbox rejection breaking every `web_search`. Same
lesson, second module, eight months apart.

- **The script LISTS the litter; cria removes it.** New `___CRIA_GATE_litter___` section →
  `probegate.sweep_litter`, bounded three ways because it deletes: git must call the path untracked,
  it must resolve inside the workspace (no absolutes, no `..`, symlinks unlinked not followed), and
  any failure is skipped. Verified live: it takes back `orders.db` — the artifact that motivated
  fix 22 — plus `__pycache__`, `Cargo.lock`, `target/`.
- **A refused gate is loud.** `probegate.refusal_reason` reads the harness's own words out of a
  section-less result; `loop.read_gate` is now the single funnel for all four `interpret_gate` call
  sites and logs `loop.gate_refused` at warn. Operator-facing only. This is the general fix: a
  rejected verb in any future module surfaces instead of switching off a subsystem in the dark.
- `tests/test_gate_script_is_read_only.py` — no composed gate, in any of the six battery languages,
  may contain a destructive verb. Proven to fail (6 cases) with the `rm` put back.
  `test_gate_leaves_no_litter.py` now drives the real round trip: compose → real `sh` → interpret.

### Open, deliberately not acted on yet

The sweep removes build caches too — `target/`, and `node_modules` would qualify if a probe ever
created one. A cache is not litter: it changes how long the next check takes, never what it reports.
`groundtruth.BUILD_ARTIFACT_DIRS` already owns that distinction and excluding it here is a two-line
change. Not made mid-arm, and not on speculation: six sweeps so far, no cell harmed, and the final
`verify.py` rebuilds from source in every language regardless. Revisit if a cell shows a gate
timeout on a cold build.
