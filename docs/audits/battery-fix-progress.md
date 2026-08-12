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
| 1 | off-menu recovered call is eaten silently → emit the refusal | critical | todo |
| 2 | an empty turn must never satisfy completion | critical | todo |
| 3 | foreign project instructions relayed as repo doctrine | critical | todo |
| 4 | no_tests_found states a repo fact from a cria miss | false-fact | todo |
| 5 | gate "0 collected" borrows pytest vocabulary | false-fact | todo |
| 6 | "This list is complete" on a filtered listing | false-fact | todo |
| 7 | uncounted-offline note blames the runner | false-fact | todo |
| 8 | checkstyle injected as "the repo's own checks" | false-fact | todo |
| 9 | fetch ledger's no-structure note | false-fact | todo |
| 10 | "flagged line on disk" on an exception finding | false-fact | todo |
| 11 | ruby: minitest alongside rspec | table-hole | todo |
| 12 | task runners (Rakefile/Makefile/…) are manifests | table-hole | todo |
| 13 | java: syntax floor + cheap compile probe | table-hole | todo |
| 14 | node: built-in `node --test` recognised | table-hole | todo |
| 15 | runner tally: minitest + node TAP rows | table-hole | todo |
| 16 | test floor beyond python | table-hole | todo |
| 17 | stale-check trigger matches every language's test names | table-hole | todo |
| 18 | one owner for ext→validator (writeproxy ← probediscovery) | one-owner | todo |
| 19 | one owner for build-artifact skip sets | one-owner | todo |
| 20 | program_token resolves head-first | entry-point | todo |
| 21 | runnable_listing is an allowlist | entry-point | todo |
| 22 | exec-intent prompt drops "must name a listed file" | entry-point | todo |
| 23 | README corroboration weakens, never vetoes | entry-point | todo |
| 24 | rejected edit payloads collapsed in replay | injection | todo |
| 25 | compaction never replays a write payload | injection | todo |
| 26 | empty `<think></think>` not replayed | injection | todo |
| 27 | DICTATES held to a verbatim-quote test | injection | todo |
| 28 | steer symbol/existence claims resolved against disk | injection | todo |
| 29 | guards conditioned on the failure mode | injection | todo |
| 30 | gate runs against a pristine copy | injection | todo |
| 31 | remove the "change a test if its premise is wrong" clause | injection | todo |
| 32 | coder-capability roster named from the workspace | prompt | todo |
| 33 | install refusal remediates in the ecosystem it refused | prompt | todo |
| 34 | write_isdir exemplar derived from the path | prompt | todo |
| 35 | cheatsheet web_fetch exemplar | prompt | todo |
| 36 | suite: live-test ext→runner map | suite | todo |
| 37 | suite: session_live_evidence pytest literal | suite | todo |
| 38 | suite: README probe python3 caveat | suite | todo |
