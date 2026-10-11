# N1 — gate plumbing in Codex's history (phi4 / Java A4, A5, A6)

Measured over `inbound-*-responses.json` of the three capture dirs (A4 `…005747-01a129f7`, A5 `…024009-01a12a55`,
A6 `…032524-01a12a7e`) and `cria-20261011.jsonl` (`usage.context_reported`). Trigger = 13,926 tokens.

## What crosses Codex's trigger

For every request that follows a normal (tooled) response: reported usage of that response + chars/4 of the
items appended since (new `function_call_output`s; separately, new call arguments).

| Estimate | A4 (≥trig: compactions / n; <trig: compactions / n) | A5 | A6 |
|---|---|---|---|
| reported only | 5/5 ; 22/151 | 0/0 ; 1/32 | 3/3 ; 15/125 |
| **+ appended tool OUTPUTS** | **27/27 ; 0/129** | 1/1 ; 0/31 | **17/17 ; 1/111** |
| + outputs + call arguments | 27/73 ; 0/83 | 1/17 ; 0/15 | 18/60 ; 0/68 |

Codex's local estimate is the appended **outputs**; call **arguments are not in it** (adding them makes it fire
~3× too often). Consistent with `docs/codex-context-window.md`, now measured rather than inferred. Not proven from
Codex source.

## Components (unique calls over the session)

| | A4 | A5 | A6 |
|---|---|---|---|
| gate launch calls (avg args / avg output) | 56 (10.4 KB / 6.3 KB) | 20 (11.0 KB / 5.3 KB) | 46 (10.7 KB / 7.2 KB) |
| gate poll calls (avg args / avg output) | 33 (1.9 KB / 6.4 KB) | 9 (1.9 KB / 7.6 KB) | 42 (1.9 KB / 4.5 KB) |
| launch args: survey program / reader program / guard+probes | 281 K / 94 K / 168 K of 583 K | 100 K / 33 K / 72 K of 220 K | 231 K / 77 K / 149 K of 490 K |
| compactions (requests with no tools) | 27 | 1 | 18 |
| compaction preceded by gate-dominant appended output | 7 | 1 | 3 |
| … by cria-lowered `⟦ctx:tool⟧` result-dominant | 14 | 0 | 11 |
| … by plain (coder-authored) command output | 6 | 0 | 4 |

Spools of 18 A6 gates: 340,841 raw bytes → 89,469 zlib (3.8×); 85 pages of 6,000 raw → 43 packed (every A6 gate but
the 45 KB cold-maven one fits ONE page).

## Finding the task statement did not have

The gate is the **minority** cause of the compactions in these runs (3 of 18 in A6, 7 of 27 in A4). The majority
follow cria's lowered `⟦ctx:tool⟧` edit/write/read results: 217 KB of output across 59 calls in A6, of which 86 KB is
the **workspace survey riding home on lowered tool results** (`writeproxy`'s `survey_command` ride) and the rest
`⟦ctx:editfail⟧` payloads. Counterfactual (reported unchanged): shrinking every gate output 3.3× keeps
3/18 (A6), 7/27 (A4), 1/1 (A5) of those compactions under the trigger; it cannot touch the others. The follow-up
that matters most is the same treatment (lossless, packed, or not-sent-unless-needed) for the survey ride and the
lowered-tool result payloads. Not done here.

## What N1 changes (gate only)

* Page reader + survey become one content-addressed helper written once per session into the harness temp dir (the
  spool's own directory); calls name it. Warm launch args 10.7 KB → ~3 KB; poll args 1.9 KB → ~0.4 KB.
* Pages carry as many RAW bytes as zlib packs into the unchanged 6,000-byte wire bound; `offset`/`total`/`sha256` are
  over the raw spool; without zlib the page is the old raw page (`enc raw`). A gate that took 2–8 pages takes 1.
* Missing helper → typed `helper-gone` → terminal UNKNOWN; the session reinstalls it for the next gate.

## Before / after (real bash, one gate cycle, every call: arguments + outputs, chars)

| Gate | Before (018482b5) | After, first gate of a session | After, session already holds the helper |
|---|---|---|---|
| A6 maven fixture (5.5 KB probe output + survey) | 2 calls; args 10,689; outputs 9,147; **19,836** | 1 call; args 10,621; outputs 2,111; 12,732 | 1 call; args 3,059; outputs **2,111**; **5,170** (3.8×) |
| A6 cold-maven spool (45 KB raw) | 8 calls; args 20,863; outputs 60,327; **81,190** | 1 call; args 10,421; outputs 5,496; 15,917 | 1 call; args 2,859; outputs **5,496**; **8,355** (9.7×) |

The trigger-relevant figure is the outputs column: 9,147 → 2,111 (4.3×) and 60,327 → 5,496 (11×). Fixture:
`tests/fixtures/n1_a6_maven_compile_failure.txt`. Not reduced: the launch guard (~1.5 KB of shell) and the probe
commands still ride in the launch call.
