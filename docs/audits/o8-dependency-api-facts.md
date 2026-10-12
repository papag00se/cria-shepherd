# O8 — unresolved third-party API: what ground truth cria can hand the coder (investigation)

Status: measured, not implemented. Prototype + scripts + raw replays:
`~/.cria/validation/java-cells/ornith1.5_9b/o8/` (`prototype/pkglisting.py`, `prototype/o8_census*.py`).

## 1. Prevalence (all of ~/.cria/calls, 398 sessions with a coder phase)
Only three tasks use a third-party library (Java/opencsv, Go/shopspring decimal, Rust/toml); the Ruby,
Python, Node tasks are stdlib/own-code. Counted from every distinct tool result across ALL coder bodies
of a session (a last-body count undercounts: compaction drops early errors — B0's are gone from its final
body). Third-party = the error's location/qualifier is outside the project (Java `location: package
com.*|org.*` / `package com.* does not exist`; Go `decimal.X undefined`; Rust E0599/E0433 on `toml::`).
The census script is a measurement tool with per-language patterns; cria itself would not carry them.

| task | sessions | saw ≥1 third-party unresolved-name error | ≥3 distinct such results | last check of the final body still had one |
|---|---|---|---|---|
| feed-pipeline-java | 78 | 42 | 23 | 13 |
| cart-billing-go | 64 | 36 | 33 | 11 |
| rust-toml-cli | 48 | 16 | 3 | 1 |

94 of 190 sessions (49%) hit it; ≥25 (13%) ended on it. ornith1.5_9b: 3 of 4 such sessions hit it (B0, B1, Go).
`writeproxy.dependency_surface` (C40) fired once ever in ~/.cria/logs (a Rust run, 2026-10-09).

## 2. Root cause of the silence: the existing fact never finds the jar
cria already has this mechanism: `cria/depsurface.py` (pom.xml coordinate -> jar -> `javap`) delivered by
`writeproxy._note_dependency_surface`. It looks ONLY in `~/.m2/repository` (`_m2_jar`), `~/go/pkg/mod`,
`~/.cargo`, ... In the suite the build is told to keep its cache elsewhere
(`-Dmaven.repo.local=<install>/m2/repository`, echoed in every mvn output and declared writable in the
request), so `gather()` abstains every time. B1: the jar is at
`<install>/m2/repository/com/opencsv/opencsv/5.9/opencsv-5.9.jar`; depsurface never saw it.
(Even when found, it javaps the first 8 classes alphabetically, not what the errors name.)

## 3. Design options
A. **Upstream (A-fix): give depsurface's locators the build's real cache roots** (the harness-declared
   roots, `dirguard.declared_roots`, already derived from the request) in addition to the home defaults.
   Proactive (fires as soon as the manifest declares the dependency, before any failure); no new
   mechanism; per-ecosystem naming (`artifact-version.jar`, `name@vX`, `name-X.Y.Z`) is already in that
   table. Weakness: its note shows an alphabetical slice, not what the coder is missing.
B. **Failure-driven namespace listing (prototyped).** Every dotted/slashed identifier in the failing check
   output is a candidate namespace (`a.b.C` -> `a/b/C`, `a/b`); the DISK is the filter: it counts only if
   an archive (stdlib zipfile: jar/zip/whl/nupkg) or tree under a declared root really holds it. No keyword
   lists, no grammar (principle 20); the workspace is excluded; most-mentioned namespace first (kills
   `org.apache.maven.plugins` noise); entries bounded (60) with the true total. Shown on the check result
   the model reads. Facts only. Weakness: namespaces that are not directories (Go import paths with
   `@version`, Rust crate names with `-version`) need option A's naming table instead.
C. Ask the reasoner to name coordinate + missing symbols from the output, then list. Not needed where B's
   disk filter works; keep as the fallback only if a language needs it (one focused question).

## 4. Prototype output (B1 and B0 compile output, real jar)
```
The output above names `com.opencsv`. Read directly from the installed opencsv-5.9.jar, that namespace
contains (29 entries): AbstractCSVParser.class, AbstractCSVWriter.class, CSVIterator.class, CSVParser.class,
CSVParserBuilder.class, CSVReader.class, CSVReaderBuilder.class, CSVReaderHeaderAware.class, CSVWriter.class,
ICSVParser.class, ICSVWriter.class, RFC4180Parser.class, RFC4180ParserBuilder.class, ... bean/, enums/, exceptions/ ...
```
(`CSVFormat` and `RFC4180Reader` are absent.) Identical result from both captures.

## 5. Replay (ornith1.5_9b -> :18084, serial, 3 runs per turn per arm)
* B1 0084 / 0085 (jar resolved, symbol errors): 6 runs each arm. Inspect the real jar (javap/unzip): 1 -> 4.
  Real opencsv classes in the model's calls: 1 -> 4. Invented class names in an edit: 1 -> 0
  (absent-2 kept `CSVFormat`/`RFC4180Reader`). Present-1 rewrote the file with real imports
  (`CSVReader`, `CSVParserBuilder`) but still misused the constructor.
* B0 0045-0047: INVALID for this question. At those turns the dependency was not yet declared (error is
  "package does not exist", the jar was downloaded later), so the fact would not exist; both arms mostly
  re-read files (6/9 vs 3/9). Not counted.

## 6. Recommendation
Direction is consistent but N=6 on one task is not a clear effect; nothing implemented. Next: (1) land
option A (small, upstream, proactive) and re-run B1 end-to-end; (2) if Java still invents after the
note is in the window, wire B into the check-failure block (`writeproxy`, beside
`_note_missing_dependency`) with a fails-before/passes-after test; (3) widen the replay to Go/Rust turns.
Limitation: O2 (readable-roots) is not on main; B1 absent-arm already inspected the jar sometimes.

## 7. Step 1 landed (option A) + replay with the real output
`depsurface.gather(..., cache_roots)`: the home default first, then a bounded search (depth 4, 3000 dirs,
containment-checked) under `dirguard.dependency_roots(messages)` = harness-declared roots (system/developer
text) + an in-root `-Dmaven.repo.local` shown in a TOOL result (assistant text never a source). Covers
jvm/go/rust/ruby locators. No roots -> unchanged. The failure-driven namespace listing (option B) is NOT
in: the surface is gathered once per coordinate and anchored, before any failure exists, so it does not fit
that rung; it stays step 2 (check-failure block).
Replay, B1 0084/0085, real `represent_inbound` output, 3 runs per arm (`o8/real-B1-*.json`): jar
inspected (javap/jar tf) 0/6 -> 4/6; edits used real classes 2 (one still invented
`com.opencsv.enums.CSVRecord`); absent arm 0/6 inspected, 0 edits. Small N, same direction as the prototype.
