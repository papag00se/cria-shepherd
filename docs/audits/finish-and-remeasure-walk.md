# Walk — `finish-and-remeasure`, step 3

Every call read first to last, prompts and reasoning both, per [`docs/walk-prompt.md`](../walk-prompt.md). Three readers over 13 chunks; **every finding below was then reproduced by hand** against the surviving workspace or the source, and the reproduction is quoted. A finding that did not survive that is marked `refuted` and kept.

## `shipping-rates-rb_ternary-bonsai_codex_poff_1787035426` — 1/5, killed at 30 min, 60 calls

Code state `1b05cfd`. Four of five deliverables written and correct in the final workspace; one require blocks all of them.

**A correction to the earlier reading of this cell.** The `Rakefile` TypeError reported mid-run is **not** in the delivered result — the model wrote that line at call 0051 and had removed it by the end. The mid-run copy was taken while it was still there. The final workspace has exactly one blocker:

```
ruby -Ilib -e 'require "shipping/rates"'  ->  cannot load such file -- iso3166 (LoadError)
```

`eu_countries-0.0.2/lib/eu_countries.rb` line 1 is `require "iso3166"`, and `countries-8.1.0/lib` ships `countries.rb` and `countries/` — no `iso3166.rb`. The gem is broken against the gem it depends on. That choice is the model's.

**But the line the model had to back out of was cria's idea**, and the tail of the run was spent on a theory cria supplied. Findings below in the order they cost.

---

### 1. cria named an install method that never happened, and its remedy became the model's fatal line

`cria/prompts/dependency_note.txt`, the ruby installed-branch, appended to the model's own `bundle exec rake test` output at call 0052:

> Note: `minitest/autorun` is installed nowhere ruby is looking. A gem installed with --install-dir is not on the load path by default — set GEM_HOME to that directory when you run, or add its `lib` directory to $LOAD_PATH from your code. **Fix the loading; the code that uses it is not what failed here.**

Reproduced by hand against the real workspace:

```
$ ruby -e 'require "minitest"; puts Minitest::VERSION'
5.16.3
$ python3 -c "... dependency_line('ruby', WS) ..."
install_landed: True
Note: `minitest/autorun` is installed nowhere ruby is looking. A gem installed with --install-dir ...
```

Three things wrong at that moment:

- **"installed nowhere ruby is looking"** — it is exactly where plain ruby looks. It was missing only from bundler's isolated set, because the model had just removed `gem "minitest"` from the Gemfile.
- **"A gem installed with --install-dir"** — no `--install-dir` install happened in this run. Every install was `bundle install --path vendor/bundle`. cria asserted a cause it had not established.
- **"the code that uses it is not what failed here"** — rules out the one correct move, putting `gem "minitest"` back.

**The model's own diagnosis was better than cria's and it deferred anyway.** Call 0053: *"The issue is that bundler isolates gems and doesn't include system-installed gems like minitest."* That is right. It then adopted cria's remedy shape and wrote:

```ruby
# Ensure system gems (minitest, etc.) are on the load path when running under bundler.
$LOAD_PATH.unshift Dir[ENV["GEM_HOME"], Dir.pwd].select { |d| File.directory?(d) }.first
```

`ENV["GEM_HOME"]` appears nowhere in the model's code before cria's note said *"set GEM_HOME to that directory"*. With `GEM_HOME` unset that raises `TypeError: no implicit conversion of nil into String` and aborts `rake test`. The model removed it again several calls later.

`cria fault: yes` — reproduced from the source, not inferred from the transcript.

**This is the same defect `test_the_dependency_note_asks_the_disk.py` was written for, on the other branch.** That fix made the NOT-installed sentence ask the disk. The INSTALLED sentence still asserts *how* it was installed, and cria has never checked that.

### 2. The bundler install route dictates a directory bundler does not create

`cria/prompts/install_remedy.txt`, `gem_bundler`, shown at calls 0026, 0028, 0042, 0055, 0057:

> run `bundle install --path vendor/bundle`. That install is reachable only under bundler — **anything started as plain `ruby` still fails to require it** … add `$LOAD_PATH.unshift File.expand_path("../../vendor/bundle/gems/<gem>-<version>/lib", __dir__)` … `require "bundler/setup"` is **the weaker version of this**.

Reproduced from scratch, in a clean project:

```
bundle install --path vendor/bundle          ->  vendor/bundle/ruby/3.2.0/gems/countries-8.1.0
ls vendor/bundle/gems                        ->  No such file or directory
ruby -Ilib -e 'require "shipping/rates"'     ->  true          # with require "bundler/setup" at the top
(cd /tmp && ruby -I$D/lib -e 'require "shipping/rates"')  ->  LoadError
(cd /tmp && BUNDLE_GEMFILE=$D/Gemfile ruby ...)          ->  true
```

So: **the dictated path does not exist** for the command in the same sentence, and **"anything started as plain `ruby` still fails to require it" is false** from the project directory. The model pasted the dead path in verbatim and then debugged around a line that was a no-op.

And every check in `suite/tasks/shipping-rates-rb/verify.py` runs `subprocess.run(cmd, cwd=ws)` — the project directory, where the Gemfile is. The premise that "the checks that judge a library do not start where the Gemfile is" is false for this verifier.

`cria fault: yes`

**Where the wrong path came from, and why it surfaced only now.** `0d2fec4` measured the load-path line on a baseline run that installed with `gem install --install-dir vendor/bundle` — which *does* create `vendor/bundle/gems/`. That path was pasted into the bundler route, whose command produces a different tree. `dirguard._INSTALL_REMEDY` picks the first route whose tool is on PATH, so `gem_bundler` was unreachable until `ruby-bundler` was installed (`e5c752c`). **Installing the apt package flipped cria onto a route carrying the other route's path.** A fix that caused something new — exactly what the walk brief asks about.

**The repo already contains the refutation.** The later commit `f2b8b5b`'s own test says `require "bundler/setup"` *"was verified by running it rather than recalled: a `--path vendor/bundle` install plus that one first line passes all three shapes the verifier uses"*. The prompt still calls it the weaker version. Two commits, opposite conclusions, both still asserted. The tie-break is not a preference: `0d2fec4`'s evidence is a **5/5 vs 2/5 comparison across different runs**, and the measured noise floor at identical code is 25 points — more than one check. `f2b8b5b`'s evidence is running it. So is mine.

### 3. cria told the model a RubyDoc page "is YAML", then refused to let it read the page — **fixed `01c8136`**

Calls 0016–0017 and again 0038. On the fetch:

> This document is too large for the context (10,251 chars) — it was saved IN FULL to ./tmp/reference/www.rubydoc.info_gems_countries_3.1.0_ISO3166_Country.txt … **It is YAML.**

and on the read of that file:

> ⟦ctx:denied⟧ … is a large reference document — **reading it whole gets truncated, so you would miss the middle.** It is YAML.

Reproduced against the spilled file that is still on disk:

```
$ head -1 tmp/reference/www.rubydoc.info_gems_countries_3.1.0_ISO3166_Country.txt
RubyDoc.info:
$ python3 -c "from cria import webfetch; print(webfetch._doc_format(open(F).read()))"
'YAML'
```

`_doc_format`'s YAML test is `^(?:---\s*$|[A-Za-z_][\w.-]*:(?:\s|$))`, which matches any prose line of the form `Word:` — ubiquitous in documentation. And because HTML is reduced to text *before* the sniff, the function's `"HTML"` branch is unreachable for a spilled page. Its own docstring states the rule it breaks: *"cria states the format it has actually seen, never a guess from the file extension."*

The page cria mislabelled and then withheld is `ISO3166::Country` — the class carrying `in_eu?`, from the gem that works. The model went to `eu_countries` on the next call.

`cria fault: yes`

### 4. Two sentences the read-refusal fix did not reach

`fda715b` replaced *"reading it whole would be truncated"* with *"is larger than can be returned in one read, so nothing is shown"* in `large_read_steer.txt` and `large_range_steer.txt`. Two siblings still carry the old claim:

- `cria/prompts/spill_read_steer.txt:1` — "reading it whole **gets truncated**, so you would miss the middle."
- `cria/prompts/webfetch_guards.txt:20` (`spill`) — "This document is **too large for the context** ({{CHARS}} chars)".

10,251 characters is about 3K tokens against a 49,152-token window. Neither sentence is true; both turn an internal inline limit into a fact about the world (#5b).

`cria fault: yes`

### 5. The tail: nine calls on a theory cria supplied, while the model's own evidence refuted it

Calls 0052–0060 contain no work on any deliverable. The model held one theory throughout — *"the transitive dependencies aren't being found"* — and its own `ls` in the same stretch shows `countries-8.1.0` present in `vendor/bundle/ruby/3.2.0/gems/`. Nothing transitive was missing. `iso3166` is not a gem; it is a require `eu_countries` issues against a `countries` layout that stopped existing years ago.

cria emitted the frame `…/eu_countries-0.0.2/lib/eu_countries.rb:1:in '<top (required)>'` repeatedly. It never showed that file's one line, though it has a mechanism that does exactly that — it printed `the flagged line on disk — line 6: …` for the Rakefile in the same run. One line of `eu_countries.rb` would have ended the loop.

`cria fault: none` for the gem choice; **recorded** as the largest missed opportunity of the run.

### 6. Recorded, not yet acted on

- **A third reader still contradicts the other two.** `gate_error_text` was fixed so `completion_block_nudge` and `failed_unparsed_probes` are surfaced together rather than exclusively. At call 0058 the steer still said *"a specific line could not be parsed from the output"* while the `⟦ctx:checks⟧` block four lines above printed `the flagged line on disk — line 6: $LOAD_PATH.unshift Dir[ENV["GEM_HOME"]…`. The annotation comes from `clean_gate_output`, a reader the earlier fix did not cover.
- **A disclosed elision inside cria's own ground-truth block.** `proberun.py:807` prints `...[middle 192 bytes elided; head+tail kept so an early failure survives]...` in the middle of a stack trace. Disclosed, but still a per-output cap on model-read content (#5).
- ~~**`Wall time: 0.0000 seconds`** reported for commands that demonstrably ran.~~ **Refuted.** `Wall time:` is part of the HARNESS's exec envelope, not cria's — cria only ever strips it (`dedup.py:192`, `selfcompact.py:217`, `content_reduce.py:37`). Nothing here to fix. `cria fault: none`

## What the model did on its own

- Diagnosed the seeded bug in one line — *"the free-shipping check uses `>` instead of `>=`"* — and fixed it with a one-character edit. Never touched a repo test assertion.
- Installed the gem properly under `--path`, having been refused a system install.
- Read the real API off the generated docs (`ISO3166::EUCountry.codes`) instead of inventing a method.
- Handled the `GB` trap correctly: `zone_for` returns `domestic` for `GB` **before** consulting the gem, whose EU list still contains `GB`.
- Rejected hardcoding when it was tempted — *"maybe I should just inline the EU country codes"* — because the task forbids it.
- Out-reasoned cria once, on bundler isolation, and deferred to cria's wrong note anyway.

Its own unforced error, never surfaced by any check because the LoadError masked it at import: `resolve_zone` upcases its input and returns the upcased string, so `shipping_cost("domestic", …)` would raise `unknown zone: DOMESTIC`.
