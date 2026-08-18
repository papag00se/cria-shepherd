# Walk — the four failed runs of the targeted + retest passes (2026-08-17)

Every call of four captures read first to last, including the model's own thinking. All four were killed at `milestone-miss-15min` with zero deliverables. Every finding below was re-verified against the raw capture or reproduced against live code; anything the walkers reported that did not survive that check is not here.

| run | calls | what killed it |
|---|---:|---|
| rust-toml-cli × ternary-bonsai (targeted) | 22 | three whole-file rewrites re-diagnosing an error two edits stale |
| shipping-rates-rb × ternary-bonsai (targeted) | 42 | cria's syntax refusal destroyed the diagnostic, then ordered a forbidden hardcode |
| shipping-rates-rb × gemma4 (targeted) | 27 | one dead stream ate 743 of 949 seconds |
| shipping-rates-rb × ternary-bonsai (retest) | 49 | cria's install note named a directory bundler never creates |

**None of these runs failed for lack of capability.** Every model diagnosed the seeded bug correctly and early — 2m15s, 5min, 6min. Three of the four had working code on disk at some point.

---

## 1. The dead-stream guard cannot fire on a stream that is dead enough

`shipping-rates-rb × gemma4`, call 0017: **743.4 seconds — 78% of the run's wall clock — in one call that produced nothing.**

```json
"finish_reason": "rumination"
"cria_rumination": {"dead_stream": true, "chunks": 2, "seconds": 743.4}
```

`rumination.DEAD_STREAM_SECONDS` is 180. The guard fired at 743 because **the clock is read inside `for raw in resp:`** (`cria/upstream.py`, the elapsed test sits in the loop body). With two frames in twelve minutes the loop body ran twice, so the threshold could not be evaluated until the second frame landed at t=743.

This guard was written earlier the same day, for a call that delivered ~300 frames. Its test drives 300 frames over 755 seconds and passes. **It never exercised "almost no frames at all", which is the case the guard's own comment claims to cover:** *"The clock is the one signal a quiet server cannot suppress."* A quiet enough server suppresses it.

The coder in that run needed **72 seconds of generation in total** across its other 18 calls.

---

## 2. The syntax refusal spends its whole message budget on the path, twice

`shipping-rates-rb × ternary-bonsai` (targeted), call 0026. The model wrote a complete implementation — `express`, the rate table, `zone_for`, country-code dispatch, all five changes, 2,025 characters. cria refused it and said:

> `write_file REFUSED (not written): this would replace a currently-valid rates.rb with content that does not parse — /tmp/suite-…/lib/shipping/rates.rb: /tmp/suite-…/lib/shipping/rates.rb:36: s. Fix the content so the file is valid, then write again.`

The real error was `syntax error, unexpected '(', expecting 'end'` at `ISO3166::Country[]("#{code}")`.

**Reproduced byte-exact.** `cria/writeproxy.py` runs the checker on a temp file, substitutes the real path back in, then caps: `_msg.splitlines()[0][:200]`. `ruby -c` prints the path **twice** on line one. The workspace path is 96 characters, so 194 of the 200-character budget is spent before the diagnostic starts — leaving `:36: s`.

cria also elides the rejected payload from history (`[2025 characters — this edit was REJECTED]`), so the model has neither its draft nor the error. Its next write dropped `express`, the rate table and the dispatch. **They were never recovered in the remaining 17 calls.**

The assist built for exactly this — quoting the offending source line — is keyed to the regex `line\s+(\d+)`. Ruby says `rates.rb:36:`. So does `node --check`, `php -l`, `gofmt -e`. It abstains silently on four of the six languages the validator covers.

---

## 3. cria's install note prescribes a directory bundler never creates

Both ternary-bonsai ruby runs. `cria/prompts/install_remedy.txt`, key `gem_bundler`, one sentence:

> run `bundle3.2 install --path vendor/bundle` … add `$LOAD_PATH.unshift File.expand_path("../../vendor/bundle/gems/<gem>-<version>/lib", __dir__)`

The command creates `vendor/bundle/ruby/3.2.0/gems/`. The path names `vendor/bundle/gems/`. **Verified on disk:** the surviving workspace has the former and `ls` on the latter is `No such file or directory`. The two halves of one cria-authored sentence contradict each other.

The `vendor/bundle/gems` layout is correct for the *other* route in the same file (`gem_direct`, which uses `gem install --install-dir vendor/bundle`). The load-path sentence was written for that layout and reused under bundler's.

In the retest run the install **succeeded** at call 0033. The model then probed cria's path three times, found nothing, and concluded:

> *"the bundler install didn't work properly"* … *"The countries gem is not installed."* … *"I can't install it via bundler due to permission issues"*

**Nine calls (0041–0049) re-installing a gem that was already installed.** The `$LOAD_PATH` line the note exists to obtain was never written, so the delivered `require "countries"` is unreachable to the verifier and all four code checks score zero.

A layout-independent form is true for both and was verified working under plain `ruby` on the surviving workspace:

```ruby
Dir[File.expand_path("../../vendor/bundle/**/gems/*/lib", __dir__)].each { |p| $LOAD_PATH.unshift p }
```

---

## 4. The refusal-count redirect reports a repetition that never happened

`shipping-rates-rb × ternary-bonsai` (targeted). cria told its own steer author:

> `WHAT TRIPPED THE DETECTOR: It keeps repeating the SAME action 3× without the outcome changing: exec_command {"cmd":"which bundler …"}`

**The coder issued that command once, at call 0031.** Counted directly from the response captures: one occurrence.

The trigger was the `blocked_fires` branch in `loop.guard_track_repetition` — three cria REFUSALS in the window, of three *different* commands. That branch sets `redirect_due` and then falls into the repetition route's reporting: `rlog.emit("loop.repetition", count=REPEAT_FINGERPRINT_N, …)` with `gs.repeat_action` set to whatever call was in flight. So a refusal count is announced as a repetition count, naming an action that was not repeated.

The reasoner read it literally and wrote it back as established fact:

> *"you've already confirmed they're unavailable (three failed attempts)"*

then, on that premise, authored:

> *"implement EU membership as a hardcoded constant map of two-letter country codes (e.g., `{ "DE" => true, "FR" => true }`) … That satisfies the task requirement without needing an external gem that can't be installed here."*

The task says, verbatim: **"Do not hardcode EU membership."** The reasoner's own system prompt carries the guard — *"Do not choose the IMPLEMENTATION… Measured: directives that picked the approach cost nine checks — one told the coder to hand-roll a list the task had explicitly forbidden hand-rolling"* — and it was ignored, because the false count made the premise look settled.

The model obeyed, read the steer as the user's instruction (*"The user is telling me to switch direction"*), wrote an `EU_MEMBERS` hash missing HR and PL with eleven duplicate entries, then argued itself back out over six calls:

> *"Wait, I need to reconsider. The task says 'Add a third-party Ruby gem that determines whether a country is in the EU'. Using a hardcoded list of EU members doesn't use a third-party gem."*

**Three reasoner calls plus six coder calls — about 4.5 minutes of a 16-minute run — to issue a wrong instruction and undo it.**

---

## 5. Superseded build output is never marked stale, and the write confirmation says nothing

`rust-toml-cli × ternary-bonsai`. Calls 0020, 0021 and 0022 are three full rewrites of the same 7,150-character file. The diffs:

```
0020:  - // Use get() since Table keys are String, not &str.
       + // Table keys are String, so we need to use get with a String key.
0021:  - // Table keys are String, so we need to use get with a String key.
       + // Table keys are String — use get with a String key.
0022:  - let entry = current.get(key);
       + let entry = current.get(key.to_string());
```

Two of the three changed one comment. **239 seconds, 7,185 completion tokens, net code change: one wrong line** — the `E0308` the run died on.

The model's own reasoning at 0021: *"Wait, that's from my OLD code. Let me check what the actual error is with the new code."* It could not. The freshest compiler diagnostic in its context was from two edits earlier, nothing marked it stale, and every `write_file` returned the same content-free string: `Wrote <path>`.

cria already refuses a no-op `edit_file` (`if old == new: _fail('identical')`). There is no equivalent for `write_file`, though cria holds the pre-write bytes.

---

## What the walk says about the recent fixes

- **edit-first cheatsheet** — not testable on the rust run, which started 53 minutes before the commit. On the retest run it worked for `Gemfile` (both changes used `edit_file`) and did not for `rates.rb` (two whole-file rewrites, the second to move a single `require` line).
- **superseded-write stubbing** — working in the coder body on the retest run (`[elided 1527 chars — an EARLIER version …]`). Gap: it tracks write→write only. A `write_file` superseded by later `edit_file` calls stays in full.
- **the `__cria_` sentinel leak** — still live, in three of the four runs, rendered inside a shell command attributed to the coder. Previously reported in `cycle-1-walk.md`, `cycle-3-walk.md`, `cycle-3-fixes.md`.
- **repeat-call detector and content de-duplication** — both firing correctly and the model responding to them.
- **reasoning-channel tool-call recovery** — fired and worked (retest run call 0016).
