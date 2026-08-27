# Level 0 against level 1 — nine cells, both arms, walked

Nine agents, one cell each, every call in both arms read in order — prompt and reasoning. 18 runs, roughly 1,100 calls. Every claim below was reproduced by running something.

The question: ten of twelve cells fell from level 0 to level 1, several catastrophically, and one-directional movement is not what noise looks like.

## The statistical premise is correct

Across **301 pairs of repeat runs** at the same model, task and level in `results.jsonl`: later run lower 97, higher 116, flat 88. Direction is symmetric — 45% down, mean change +3.5, median 0. Repeat runs do not drift downward, so 9-down-1-up is about a 0.5% event under the observed split.

## No level-1 mechanism caused any of it

Level 1 turns on three things. Replayed over every captured reply and request at the commit each run shipped on: `massage.apply` changed **0 of 1,615** replies, `repair_history_tool_args` **0 of 401** requests, `ensure_tool_integrity` found **0** orphans. One exception, found by the rust walker and correctly excluded from the count: one `fused_tail_trimmed` in `gemma4 × rust-toml-cli`, which cut a fused second turn off a tool argument, landed exactly on the heredoc terminator, and did the right thing.

Every fork was from a byte-identical prompt. The gemma4 java fork at call 0005 carried no reasoning at all.

## Nine cells, nine model-side proximate causes

| cell | what decided it |
|---|---|
| gemma4 × java | `[^\d.]` where Java needs `\\d`; the model sent it correctly and an unquoted heredoc ate the backslash. One character fixed = **1/5 → 5/5**. But the real gap is that L0 ran `mvn compile` four times and fixed three of its own errors; L1 never built anything. |
| gemma4 × python | `CREATE UNIQUE INDEX` on a customer column in an orders service. Deleting the word `UNIQUE` = **1/4 → 3/4**, exactly L0's score. |
| gemma4 × rust | L1 read `--quiet` as its own argument rather than cargo's, and never ran `cargo build` or `cargo test` in seven calls. |
| gemma4 × node | `parseArgs({allow_leading_hyphens: true})` — the option does not exist. Its own empty `catch` swallowed `ERR_PARSE_ARGS_UNEXPECTED_POSITIONAL` and exited 0, so the same command ran **285 times** against output that could not change. `reasoning_content` was null on all 272 calls of the streak. |
| gemma4 × ruby | Found the right gem, installed it, then asked an empty version-number module for an EU predicate **277 times**. `ISO3166::Country.new('DE').in_eu?` was on disk throughout. |
| bonsai × go | One call, 40,822 tokens, 1,193 seconds, the same test function 339 times inside a heredoc; unparseable JSON, no file. L0 made the identical decimal-API mistakes and had calls left to run `go build` and fix them. |
| bonsai × ruby | Three calls, 1,058 seconds, 145 copies of one method. The file that landed has no `shipping_cost` at all. L0 died of a dialect-leaked tool call that level 1's own repair would have fixed. |
| bonsai × rust | Its briefing named the functions but not the file holding them; it concluded its own library was a missing crates.io crate and rewrote it from memory, dropping one `*`. The working code was beside it the whole time. |
| bonsai × python | `self.path[12:]` where `"/customers/"` is 11 characters. It caught the bug at call 0011, announced the fix, re-emitted the identical line, and never made a successful HTTP request in 30 minutes. Fixing two offsets = **1/4 → 3/4**. |

## Three real cria defects, found by the walks

**1. The compaction REQUEST rewrite ran at every level. FIXED (`c7866b3`).** cria discards the harness's summarize instruction, substitutes its own, and flattens the history into one text message — context surgery, level 3 by the ladder's own definition. Its sibling (rewriting the reply) was gated on 2026-08-24; this half was missed.

It is not free. Flattening destroys the model server's prefix cache. Measured cold prefills: **453s, 369s, 358s, 286s** — 21% of a 30-minute budget, and on the bonsai ruby level-1 arm the call was still in flight when the gate fired.

It also promises what it cannot deliver below level 2: *"A FILES ON DISK list may appear below the transcript… a file NOT on that list does not exist."* That list comes from the survey view, and nothing surveys the disk below level 2. That is exactly how the bonsai rust cell died.

**2. Runaway protection is gated at level 4. NOT YET FIXED.** Generations over 8,000 tokens: **0 at level 0, 4 at level 1**; the largest L0 generation across all twelve cells was 3,137 tokens. cria's degenerate-run backstop watches content, reasoning *and tool-call arguments*, and replayed against the real 40,822-token runaway it fires at ~8,500 characters — about 90 seconds instead of 1,193 — while staying silent on every legitimate long write in the level-0 arms. It lives only on the streaming watched path, wired behind `done_refusals`. Principle 6 puts runaway protection outside the assist ladder.

**3. Repeat detection cannot see a short repeated result.** `dedup.fold_repeated_messages` is level 3 and has a 200-character floor. gemma4 ruby's repeated result was 112 bytes, and 295 of that run's 317 tool results are under 200. A 277-long identical loop is invisible to it at any level.

## What is still not explained

Every cell has a model-side proximate cause and every fork came from an identical prompt. Nothing found accounts for the direction of the split.

What the walks do explain is why the failures were **fatal**: levels 0 through 3 have no runaway guard, no repeat detection, and no safe file write. A run that goes wrong there has nothing to stop it. The level-0 runs happened not to go wrong — and in five of nine cells they were saved by the same thing, which is that they executed what they had written and let the error message do the work.
