# Cycle 1 — walk

Per-run line-by-line walks of the cycle-1 battery. Method: `docs/walk-prompt.md` (a walk is READING
every call end to end, never grepping — principle 23b). Doctrine references are the numbered rules in
`docs/principles.md`.

## shipping-rates-rb_gemma4_codex_poff_1786669475

Commit d9060df. 80 calls, 1,020 s wall (17 min of a 30-min budget), 1,283,383 tokens, terminal
`exited`. Score 1/5 — only `readme_rate_table` passed; the four checks that load the library all died
on `cannot load such file -- eu_countries (LoadError)`. The same cell scored 100% last cycle.

Shape of the run in one line: the model picked `eu_countries` from its own priors at call 0016 before
searching anything, cria's dependency note then told it the gem was fine and only its *loading* was
broken, three reasoned steers kept it inside that frame for fifteen minutes, and the run finally died
— not on the clock — when the compaction prompt, half of which was a listing of the gem files cria had
told it to install into the workspace, was rejected by the server twelve times in a row.

Findings ranked worst first.

---

### 1. The run did not run out of time — it was killed by cria's own compaction prompt (12 × HTTP 400)

**what happened.** At 17 minutes the compaction proxy fired. Its prompt was 42,971 tokens against a
48K window with a 4,096-token reserve; 46% of it was a file listing of the gems the coder had installed
into `vendor/bundle`. The server rejected it, cria retried, and calls 0069–0080 all came back empty.
The session ended with 13 minutes of budget unused and the workspace still holding the LoadError.

**cria fault: yes**

**evidence.** Calls 0069–0080, all twelve identical: `--- PROMPT Δ ---` then `[no response captured]`.
The run log's last lines:

```
ERROR: Reconnecting... 1/5
ERROR: Reconnecting... 2/5
ERROR: Reconnecting... 3/5
ERROR: Reconnecting... 4/5
ERROR: Reconnecting... 5/5
ERROR: stream disconnected before completion: HTTP Error 400: Bad Request
ERROR: stream disconnected before completion: HTTP Error 400: Bad Request
tokens used
1,283,383
```

The captured body `~/.cria/calls/20260813T180510-.../0069-proxy.json` measures it:

```
'stats': {'n_messages': 2, 'n_tools': 0, 'msg_tokens': 42971, 'tool_tokens': 0,
          'est_total': 42971, 'rendered_chars': 167480, 'rendered_tokens_est': 41870}
```

Two messages: system 3,574 chars, user 163,823 chars. Inside the user message, the block headed

```
FILES ON DISK RIGHT NOW (gathered from the filesystem just now, newest first). This is the only
description of the workspace you have — the transcript's file mentions may be stale:
  vendor/bundle/specifications/europe-0.0.28.gemspec (1660 B)
  vendor/bundle/gems/europe-0.0.28/test/test_helper.rb (293 B)
  …
  vendor/bundle/gems/countries-8.1.0/lib/countries/cache/countries.json (265219 B)
  …
This list is complete — a file not listed here does not exist in the workspace.
```

is **75,779 chars (~19K tokens), 902 of its lines `vendor/bundle/...`** — every `.yaml` of every
country and every locale `.json` of the `countries` gem. The four files the task is about
(`README.md (651 B)`, `test/test_rates.rb (1963 B)`, `Gemfile (50 B)`, `lib/shipping/rates.rb`) are
buried at lines 1640-1642 and 2509 of that block.

The context floor ran and could not help: `cria/upstream.py:214` applies `contextfloor.fit` to this
body, but the floor's levers are *reduce tool outputs* and *drop oldest turns*, and this body is one
system message plus one user message with no `tool` roles. There is nothing for it to drop, so it goes
`over_budget` and ships anyway.

**A → B → C.** A: cria's own install-denial note tells the coder to install gems into `vendor/bundle`
*inside the workspace*. B: cria's workspace inventory deliberately does not skip `vendor`
(`cria/groundtruth.py:200` — "Deliberately does NOT include `bin`, `obj` or `vendor`, which are real
source directories in some projects"), so the inventory grows by 902 files. C: the compaction prompt
exceeds the window, the server 400s, twelve retries produce nothing, the run dies with a third of its
budget unspent.

**fixable at A? Yes.** cria created the directory it refuses to exclude. The denial note names one
concrete path — `vendor/bundle` — so the exclusion can be exactly that path (the Bundler convention),
not the bare `vendor` the comment is rightly protecting. Same disease as the `site_packages_leak`
column added on 07-30, in Ruby dress. There is a second, independent fix at B: `contextfloor.fit`
currently has no lever over a *single oversized message*, so any composed prompt that overflows is
shipped rather than reduced — the floor's "guarantees window fit" claim does not hold on the compactor
path.

**principle.** #7 (cria never pollutes the workspace — here cria's advice put 902 files in it and cria's
own reader ate them), #5 (the floor is the one lossless window-fit point and it silently failed to fit).

---

### 2. cria's dependency note stated a false diagnosis and locked the model onto a dead gem

**what happened.** At call 0018 — the very first LoadError, with nothing installed anywhere — cria
appended a note to the shell output asserting the gem was installed somewhere Ruby was not looking, and
told the model the gem itself was not the problem. Nothing had been installed at all. The model spent
the next fifteen minutes on load paths and never once questioned the gem.

**cria fault: yes**

**evidence.** Call 0018, appended by cria to the `ruby -Ilib:test test/test_rates.rb` output:

```
Note: `eu_countries` is installed nowhere ruby is looking. A gem installed with --install-dir is
not on the load path by default — set GEM_HOME to that directory when you run, or add its `lib`
directory to $LOAD_PATH from your code. Fix the loading; the code that uses it is not what failed here.
```

Source: `cria/prompts/dependency_note.txt:10`, fired from `cria/proberun.py:541`. At that moment the
transcript shows the only `gem` commands run were `gem list` (call 0026, read-only) — no install of any
kind had happened, with or without `--install-dir`. The model adopted it verbatim at call 0018:

> "The user is pointing out that `eu_countries` gem is missing and causing a `LoadError`. I need to find
> a suitable gem for EU membership and install it"

and from there the frame never changed. Call 0044 is the moment it could have: it read the gem's own
first line —

```
--- read_file vendor/bundle/gems/eu_countries-0.0.2/lib/eu_countries.rb ---
require "iso3166"
require "eu_countries/eu_country"
```

— and concluded, still inside cria's frame:

> "Wait, if `iso_3166` gem is installed, why can't it find `iso3166`? **Maybe because I need to add it to
> the load path.**"

It had the dead entry point in front of it and read it as a load-path problem, because cria had told it
that is what this class of error means.

**A → B → C.** A: the note asserts a *cause* (`--install-dir`, load path) from an error class that only
says "not found". B: the model treats gem choice as settled and works the package manager. C: fifteen
minutes and four checks lost to a gem that cannot load on any load path.

**fixable at A? Yes.** The note's own docstring says it exists because "8 checks failed with the
dependency declared correctly and simply not reachable" — but it fires on *every* not-found, including
the case where the dependency was never installed and the case where the gem is broken. Two changes
keep the value and drop the lie: (a) ask the world before asserting the cause — if nothing is installed
under the workspace, the sentence about `--install-dir` is false and should not be said; (b) drop
"the code that uses it is not what failed here." That clause is the load-bearing one and it is a claim
cria cannot support: at call 0038 the *same* library failed for a reason that was entirely about the
library. Saying where the ecosystem looks is a fact; ruling out the dependency itself is a guess.

**principle.** #5b (cria never states a FALSE FACT about the world — "a claim built on … a partial
matcher … is a claim about cria, not about the world"), #1 (every assist can become a footgun).

---

### 3. The unstick steer chose the implementation — it named `eu_countries` after considering, and rejecting, the gem that would have worked

**what happened.** The first steer reasoner looked at `gem list`, saw `countries (8.1.0)` already
installed, wrote out loud that using it "would satisfy the task", then issued an imperative directive
naming `eu_countries` and `vendor/bundle`. Its own prompt forbids exactly this.

**cria fault: yes**

**evidence.** Call 0035, the reasoner's private thinking:

> "Wait, is there a simpler way? "Add it to the project dependencies". If they can't use Bundler, maybe
> they should just `require 'countries'` if it's already in `gem list`. Looking at `gem list`:
> `countries (8.1.0)` is present!
> So why did they try to install `eu_countries`? … If `countries` is available, using it would satisfy
> the task of using a third-party gem."

and then, four paragraphs later:

> "I will tell them to install `eu_countries` into a local directory as indicated by the error message
> they received."

The directive delivered at call 0036:

```
⟦ctx:steer⟧ Install the eu_countries gem into a local directory within the project (such as
vendor/bundle ) to resolve the "cannot load such file -- eu_countries (LoadError)" . Once installed,
update your code or environment configuration to include this directory in the $LOAD_PATH so it is
available during both the application execution and the test suite.
```

The coder followed it in the next breath:

> "Okay, I need to install the `eu_countries` gem into a local directory (`vendor/bundle`) because
> installing it into the system or user environment is not allowed."
> → `mkdir -p vendor/bundle && gem install eu_countries --install-dir vendor/bundle --no-document`

That single command is what installed the 902 files behind finding 1.

The steer's own system prompt (call 0035) says:

```
- Do not choose the IMPLEMENTATION. Which library to use, which data structure, which flag, which
  output format, which file to create — those belong to the TASK or to the coder, never to you. Say
  what must become true and stop. Measured: directives that picked the approach cost nine checks …
```

**A → B → C.** A: the steer prompt asks the reasoner for ONE concrete next action, which pulls it
toward naming a library. B: it names `eu_countries` and `vendor/bundle`, ratifying the coder's worst
decision with cria's authority. C: the coder stops evaluating gems entirely and starts installing.

**fixable at A? Yes, at the prompt.** The rule is already written; it is not being obeyed, and the
reasoner's own reasoning shows it *had* the better answer and discarded it to produce "exactly ONE
concrete next action". The two instructions fight: "give exactly ONE concrete next action" plus
"quote the current error" makes naming the failing symbol nearly mandatory. A cheap structural guard:
after the directive is authored, run the existing one-word `steer-code` check (call 0053 already runs
one for false blame) with the question "does this directive name a library, gem, package or flag?" and
drop it if so — the safe null is already the pattern.

**principle.** #1, #2 corollary (cria does not AUTHOR the work), #8 (the judge must be fenced out of
doing the work).

---

### 4. The second steer's false cause killed the only route the deny-note had offered

**what happened.** The third steer told the coder that "the repository checks do not have access to
vendor/bundle". That is not true — the checks run with the workspace as cwd and `vendor/bundle` is in
it; the only thing missing was `GEM_HOME`. The claim contradicted cria's own earlier steer and its own
deny-note, and it ended the vendor/bundle route.

**cria fault: yes**

**evidence.** Call 0052 directive, delivered at call 0054:

```
⟦ctx:steer⟧ "cannot load such file -- eu_countries (LoadError)" The repository checks do not have
access to vendor/bundle and bundle is unavailable. Instead of continuing to attempt manual
installations into vendor/bundle , identify a third-party gem already available in the system
environment from your previous gem list output and use it for the EU membership check instead of
trying to install eu_countries .
```

Compare with what cria itself said two steers earlier (call 0036), and with its own denial note at call
0034:

```
⟦ctx:denied⟧ Installing into the shared system or user environment is not permitted here — an install
must land inside the project directory (…), and this one would not. Install it into the project
instead: `gem install --install-dir vendor/bundle <gem>`, then make it loadable by putting that
directory on the load path — `ruby -Ilib -e "..."` needs `GEM_HOME=vendor/bundle` set, or
`$LOAD_PATH.unshift` the gem's `lib` directory from your code.
```

cria therefore told the coder, in sequence: install into `vendor/bundle` (0034) → install into
`vendor/bundle` (0036) → set GEM_HOME/GEM_PATH and edit the Rakefile (0040) → the checks cannot see
`vendor/bundle` at all, stop (0052). The steer's own prompt forbids the move it made:

```
- Do not state a CAUSE you have not verified. … A sentence beginning "because" or "the problem is"
  about something you have not opened is a guess, and it arrives as an order that outranks the coder's
  own eyes. Measured across twenty-four such directives, the coder's own reading was right and the
  directive was wrong every single time.
```

Note also that the steer at call 0040 pointed at the **Rakefile** — "Modify the `Rakefile` to include
these environment variables" — while the graded check runs `ruby -Ilib -Itest -e …` and never touches
rake. Two of the three steers pointed at things that could not move the score.

**A → B → C.** A: the reasoner reasons about the check command without opening it, and states a cause.
B: the coder abandons `vendor/bundle`, but keeps `eu_countries` (see finding 5), so it now has neither
a working install route nor a working gem. C: the last seven minutes are spent re-reading its own code.

**fixable at A? Yes.** The rule exists; enforce it the same way false *service* blame is already
enforced. `steer-code` (call 0053) asks one yes/no question about blaming the outside world and answered
`GROUNDED` here because it only knows how to check HTTP records. The same one-word check should be given
the filesystem facts cria already gathered — "the directive says X is not accessible; the inventory says
X exists in the workspace" is a deterministic contradiction, and that is a trigger, not a judgment.

**principle.** #5b, #16 (assume cria caused it), #8.

---

### 5. The model refused the correct answer because "add a gem" cannot mean a gem that is already installed

**what happened.** Steer 4 (above) actually pointed at the right gem. The coder ran `gem list countries`,
confirmed `countries (8.1.0)`, and then argued itself out of using it on the grounds that using an
already-installed gem would not count as "adding" one. Every other Ruby run in this cycle that chose
`countries` scored 60–100%.

**cria fault: none** (the steer that got it right was cria's; the reasoning that discarded it was the
model's)

**evidence.** Call 0054 → `gem list countries` → `countries (8.1.0)`. Call 0055 reasoning:

> "I see that `countries` gem is already installed on the system. Let me try to use `countries` instead
> of `eu_countries`. … However, the user specifically asked for a third-party gem that determines
> whether a country is in the EU."

Call 0068, the clearest statement:

> "But the user said: "Add a third-party Ruby gem that determines whether a country is in the EU… and use
> it for the lookup." If I use `countries` which is already there, did I "add" it? No.
> **So I MUST add a new gem.**"

It reached the right answer twice more and dropped it both times:

> "Actually, if I add `countries` to my Gemfile (even though it's already on the system), then I *have*
> added it as a project dependency. And since it's already installed on my system, maybe it will work for
> me too! Let's try this: 1. Add `countries` to the Gemfile. 2. Use `countries` gem in my code…"

— and then, instead of doing it, went to `gem list countries` again (call 0068), which is where the run
ended. The verifier would have accepted it: `country_zone_mapping` only requires a non-stdlib require
that is not a workspace file, plus the right answers for GB/DE/HR/CH/US/NO.

**A → B → C.** A: the prompt's word "add" is read as "must not already exist". B: the model rules out the
one gem on the box. C: it must install, installing lands in a directory the graded runner cannot see,
and the run is unwinnable from call 0016 onward.

**fixable at A?** Not at cria, and the task prompt is not ours to edit (operator rule). The nearest cria-
side fix is finding 3's: had the steer said what must become true ("the library the code requires must be
loadable by `ruby -Ilib -Itest`") instead of naming a gem, the coder's own repeated instinct toward
`countries` would not have been competing with a cria directive naming `eu_countries`. The context that
would have let it catch itself is the search description it never saw — see finding 6.

**principle.** none violated by cria; #1 by omission (the assist that fired chose the wrong side of a
question the model was already answering correctly).

---

### 6. The search result rendering dropped every description — including the 2013 date — and pointed at a file it never named

**what happened.** cria showed the model 20 bare titles and URLs, dropped every result description, and
closed with "the full results, with each page's description, are in the file named above". No file is
named anywhere in that message. The dropped description of the very first result carried the gem's
publication date and its dependency list.

**cria fault: yes**

**evidence.** Call 0030, the complete tail of what the model received:

```
Project: iso3166-countries - The Ruby Toolbox
  https://www.ruby-toolbox.com/projects/iso3166-countries
(the full results, with each page's description, are in the file named above — read it if a title is
not enough to choose)
```

Searching the whole captured request body (`0028-coder-s1.json`) for the spill path: three hits, **all
three inside the `web_search` / `web_fetch` tool schema descriptions**, none in any message. The string
`search-ruby_gem` appears zero times. The file that does exist,
`<workspace>/tmp/read-only/search-gem_eu_countries_rubygems.org.txt`, opens with what was dropped:

```
20 results:
eu_countries | RubyGems.org | your community gem host
  https://rubygems.org/gems/eu_countries/versions/0.0.2
  List all countries in the EU · 0.0.2 July 01, 2013 (6 KB) 0.0.1 May 27, 2011 (6 KB) countries >= 0 ·
  rake >= 0 · rspec >= 0 · Show all transitive dependencies · Caius Durling · = ← Previous version ·
```

That one line the model never saw contains both facts that decided this run: the gem was last published
**July 01, 2013**, and its dependency is `countries >= 0` — the modern `countries` gem, which is exactly
why `require "iso3166"` no longer resolves. The model never opened the file, and could not have: it was
told to read "the file named above" and there was no name above.

Partial mitigation, in fairness: the model *did* fetch the rubygems page directly at call 0030 and the
date was in that output (`0.0.2 (latest) … July 01, 2013`). It read past it —

> "The `eu_countries` gem exists and seems to be exactly what I need. It's a very simple gem (6 KB)."

It took the size off that page and not the date. But by then the choice was made (call 0016) and ratified
by cria (finding 2).

**A → B → C.** A: the inline rendering keeps title+URL and discards the description. B: the pointer to
the full results has no referent, so the spill is unreachable in practice. C: the one line that
distinguishes a live gem from a 2013 abandonware is unreachable, and the model chooses on title alone.

**fixable at A? Yes.** Either inline the descriptions (they are ~2 lines each; the whole file is 8 KB —
smaller than several tool outputs this run carried), or, if the spill is kept, put the actual path in the
sentence. A sentence that says "the file named above" with nothing above it is the tell in #5b — a claim
cria cannot support, in cria's own voice, in the imperative.

**principle.** #5b (the false pointer), #5 (a silent drop of model-read content — the description is not
a cap that was disclosed, it is content removed without saying what was removed).

---

### 7. cria's spill files landed inside the workspace (already on the backlog, confirmed here)

**what happened.** Both search spills were written to `<workspace>/tmp/read-only/`, and they then appeared
in cria's own workspace inventory as project files.

**cria fault: yes**

**evidence.** Final workspace:

```
/home/jesse/.cria/suite/shipping-rates-rb_gemma4_codex_poff_1786669475/workspace/tmp/read-only/
  search-gem_eu_countries_rubygems.org.txt (6629 B)
  search-ruby_gem_eu_membership.txt (8284 B)
```

and in the compaction prompt's authoritative file listing (chunk15, lines 2507-2508):

```
  tmp/read-only/search-gem_eu_countries_rubygems.org.txt (6629 B)
  tmp/read-only/search-ruby_gem_eu_membership.txt (8284 B)
```

**A → B → C.** A: the spill writer targets `./tmp/read-only` relative to the workspace. B: cria's own
inventory presents cria's files to the model as the project's files. C: mild here (the model never opened
them), but it is the documented failure mode — cria's artifacts become the model's context.

**fixable at A? Yes** — already on the backlog; noting the confirmation and that it compounds finding 1
(both are cria writing into, then re-reading, the workspace).

**principle.** #7.

---

### 8. Did the gates work? Yes — all five fired, all five read correctly, none reported green

This is the question the walk was sent to answer, and the answer is that the gate machinery is not the
problem in this run.

**what happened.** Three periodic check-ins and two completion gates fired. Each ran the same composed
script, each got the real LoadError back, each told the model it was not done. No gate reported green
over a LoadError.

**cria fault: none**

**evidence.** The command every gate actually ran (identical bytes each time, call 0018 shown):

```
cd <ws> && __cria_out=$(timeout -k 5 240 ruby -c <ws>/lib/shipping/rates.rb …); printf 'EXIT:%d\n' …
cd <ws> && __cria_out=$(timeout -k 5 240 ruby -c <ws>/test/test_rates.rb …); printf 'EXIT:%d\n' …
cd <ws> && __cria_out=$(timeout -k 5 240 ruby -Ilib -Itest -e 'Dir["test/**/test_*.rb"].each { |f| require File.expand_path(f) }' …); printf 'EXIT:%d\n' …
__cria_test_ec=$__cria_ec
cd <ws> && __cria_out=$(timeout -k 5 240 rake test …); printf 'EXIT:%d\n' …
__cria_test_ec=$__cria_ec
cd <ws> && if [ "${__cria_test_ec:-1}" -eq 0 ] && unshare -rn -- true …
```

What it got back, every time (calls 0018, 0036, 0054, 0064, 0068):

```
⟦ctx:checks⟧ the repo's own checks report these error-class problems … :
<internal:…/kernel_require.rb>:86:in `require': cannot load such file -- eu_countries (LoadError)
	from <ws>/lib/shipping/rates.rb:6:in `<top (required)>'
…
rake aborted!
Command failed with status (1)
```

What the **periodic** gate told the model (call 0018):

```
⟦ctx:steer⟧ I am giving you the CURRENT state of the repo (syntax & tests). If anything below is
broken, fix syntax errors FIRST before continuing and then tests; if it's all clean, carry on.
the repo's own checks FAILED, but a specific line could not be parsed from the output:
$ ruby -Ilib -Itest -e 'Dir["test/**/test_*.rb"].each { |f| require File.expand_path(f) }' — exited 1:
  … cannot load such file -- eu_countries (LoadError)
$ rake test — exited 1: Command failed with status (1)
Run that exact check yourself and read the actual error, then fix the real cause — do not rewrite the
whole file, and do not treat this as done.
```

What the **completion** gate told it, both times (calls 0064 and 0068), after the model's `task_complete`
at call 0063:

```
⟦ctx:steer⟧ not done yet — the repo's own checks are failing:
the repo's own checks did not pass — resolve these before finishing:
$ ruby -Ilib -Itest -e 'Dir["test/**/test_*.rb"].each { |f| require File.expand_path(f) }' — exited 1:
  … cannot load such file -- eu_countries (LoadError)
$ rake test — exited 1: Command failed with status (1)
```

Both refusals are pure fact — the command and its exit status, no verdict, no order. The model's "done"
claim at call 0063 was a fully-formed six-point summary ending in
`task_complete(summary="Fixed repository test failures, added express service …")`; the gate rejected it
and the loop kept working. This is #13 behaving exactly as written, and #12 (surface from the
authoritative event) — the gate quoted exit codes, never prose.

The one thing no gate said: that the model's declared-done claim was built on a library that had never
loaded once in the entire run. The gate reports the *check*; it does not notice that the same error has
been the same error for five consecutive gates on the same symbol. Not a violation — a gap, and the
cheapest place to close it is finding 2's note, which is the only cria voice that speaks about the
dependency at all.

**principle.** none violated. #13 upheld.

---

### 9. Recent fixes — did they behave?

**Reasoning logged on unfinished streams — HELPED.** Reasoning is present and complete throughout,
including on turns that ended in prose rather than a tool call (call 0063's 150-line self-review, call
0068's 400-line deliberation). Without it, findings 2, 3 and 5 would not be provable: the whole case that
the model "found the answer and lost it" rests on reading its reasoning, not its verdicts. The one place
nothing was captured is calls 0069–0080, and that is because the request never reached the model
(finding 1), not because the capture failed.

**`done_incomplete` "report, not an order" framing — HELPED (small).** Both completion-gate messages
(quoted in finding 8) are a list of commands and exit codes with the single lead-in "not done yet — the
repo's own checks are failing". No imperative, nothing for the model to follow into a worse place. Compare
the *steers* in findings 3 and 4, which are imperative and did exactly that. The contrast is the evidence
that the framing change is the right direction.

**Search results inlined rather than spilled away — HALF-FIRED, and the half that fired HURT.** The
titles and URLs did come inline (20 of them, twice). The descriptions did not, and the sentence pointing
at the spill names no file (finding 6). Net effect: the model got a menu with the labels torn off and a
pointer to nowhere. Before the fix it would at least have had to open the file to choose; now it can
choose from titles alone, and it did.

**Cached-check age note — DID NOT FIRE, and its instruction is left dangling.** All three steer prompts
(calls 0035, 0040, 0052) carry:

```
  1. GROUND TRUTH FROM THE REPO'S CHECKS and the fetch record — real output from real runs.
     Trust the words; check the DATE. That section says when it last ran and what has been
     written since.
```

and in all three the `GROUND TRUTH FROM THE REPO'S CHECKS:` section that follows carries **no date and no
age**. The checks were genuinely fresh (they ran in the same turn), so silence on a clean signal is #3
behaving correctly — but the prompt tells the reasoner to check something that is not there, which is the
same shape of small false claim as finding 6's "the file named above". Either emit the age unconditionally
or drop "check the DATE" when there is nothing to check.

**Dependency note (also new this cycle) — HURT.** See finding 2. Its own docstring cites this exact cell
("gemma4's ruby run turned 3-of-5 passing into 1-of-5 that way") as the reason it exists. It fired on that
cell again, and the cell scored 1-of-5 again — this time with the note actively certifying the gem.

---

## Cross-run — the Ruby column, all four models

Established by reading all four runs' captures and the final workspaces, not by sampling. This
sits above the per-run findings because it explains the whole column and none of the four runs can
show it on its own.

### The only run that never saw cria's install refusal is the only run that scored 100%

| model | score | prompts carrying `⟦ctx:denied⟧ Installing into the shared system…` | where the gem ended up |
|---|---:|---:|---|
| qwen35 | **100%** | **0** | already on the box |
| ternary-bonsai | 80% | 20 | `vendor/bundle` |
| nemotron-elastic | 0% | 27 | `vendor/bundle`, after trying to `gem install bundle` |
| gemma4 | 20% | 45 | `vendor/bundle` |

The score falls as the refusal's share of the context rises. That is a correlation, and the cause
under it turned out not to be the obvious one.

### qwen35 did not beat the refusal. It never needed to install anything.

`~/.local/share/gem/ruby/3.2.0/gems/countries-8.1.0` has an mtime of **1786390628** — 2026-08-08,
before the earliest of these runs (1786591218). The gem was left on the box by an older session, it
sits in the user gem directory, and the user gem directory is on ruby's default load path. So
`require "countries"` worked for free.

Every Ruby run that chose `countries` scored 60–100%. Both runs that chose any other gem collapsed.
The task's hardest requirement — *"Add a third-party Ruby gem … add it to the project dependencies,
and use it for the lookup"* — was pre-satisfied for exactly one choice of gem and full price for
every other. **The Ruby column is not a level comparison and its scores cannot be read as model
skill.** cria fault: none. Suite fault: yes.

### And underneath that, three rules that cannot all hold at once

1. The prompt requires a third-party gem.
2. `verify.py::run` (line 58) calls `subprocess.run(cmd, cwd=ws)` with the inherited environment and
   no `GEM_HOME`, and every check invokes bare `ruby -Ilib`. So the verifier can only see gems on
   ruby's DEFAULT load path.
3. `dirguard.install_refusal` correctly refuses an install that lands outside the workspace — which
   is precisely what putting a gem on the default load path requires.

A model that obeys cria cannot satisfy the verifier, and a model that satisfies the verifier has
disobeyed cria or been handed the gem by a previous run. The passes came from contamination.

This is the `A`. The three per-run findings below it — the false cause in the dependency note, the
steer that picked the library, the 902-file workspace that blew the context window — are all `B`,
and all of them are downstream of cria having no workspace-local route that the verifier can see.

### Candidate fixes, for the fix phase

- **At A, suite side.** Give each run a clean, per-run gem environment and let the verifier see it:
  `GEM_HOME` inside the run's workspace, exported for both the coder's shell and `verify.py::run`.
  Then a workspace-local install is loadable, cria's refusal stops being a dead end, and no run
  inherits a previous run's gems. This is making the verifier TRUE, not easier — it runs the project
  the way the project declares it runs. It invalidates every `shipping-rates-rb` row.
- **At A, cria side.** The refusal must not prescribe an implementation (#2's corollary: cria
  surfaces the fact and lets the coder act). Its current remediation names one specific command,
  and that command is the losing one on this box.
- **Not a fix.** Installing the `bundle` binstub. The verifier never calls bundler, so it changes
  nothing about what the checks can see, and it changes the environment mid-campaign.

---

## orders-api-py_ternary-bonsai_codex_poff_1786682533

Commit 0240a94. 93 calls, 45 min wall (killed at the milestone floor), 1,601,115 tokens, terminal
`milestone-miss-45min`. Score 2/4 — `schema_migrated` and `sql_injection_fixed` passed;
`customer_orders_route` failed (`-> 200, alice's items: False, total present: False`) and
`integration_tests` failed (`suite: 11 failed; tests make real HTTP calls: True`). The same cell
scored 3/4 last cycle.

Shape of the run in one line: the model wrote all four changes correctly in the first six minutes
except for one arithmetic slip in the new route, then spent thirty-eight minutes unable to see its
own test failures because cria discarded the output of `pytest` — the coder's runs and cria's own
gate script alike — and cria's compaction certified the broken route as working, so nobody looked
at it again.

**The clock, from the event log** (run start 04:42:13):

| +time | call | what |
|---:|---:|---|
| 1m22 | 0009 | `context.self_compact` (13 turns → 4, step boundary) |
| 5m07 | 0021 | periodic gate 1 — `ran: false, spoke: false` (its output was discarded) |
| 6m56 | 0025 | `loop.wheel_spinning` #1 → steer at 0027 |
| 19m39 | 0038 | periodic gate 2 — `ran: true, spoke: true` |
| 22m52 | 0039 | `loop.wheel_spinning` #2, then `route.compaction` 3 s later |
| 25m22 | 0047 | `loop.steer_roleplay_dropped`, canned fallback steer at 0048 |
| 26m23 | 0059 | `loop.repetition` → steer at 0064 |
| 28m58 | 0067 | periodic gate 3 — `ran: true, spoke: true` |
| 33m40 | 0077 | `loop.wheel_spinning` #3 → steer at 0081 |
| 38m34 | 0086 | periodic gate 4 — `ran: false, spoke: false` |
| 45m00 | 0093 | killed mid-`write_file`; `[no response captured]` |

Findings ranked worst first.

---

### 1. cria threw away every full test run in the session — the coder's and its own gate's — and the run never recovered

**what happened.** `pytest` on the eleven failing integration tests prints ~10 KB. cria's oversize
guard discards a result over 9,000 bytes whole and replaces it with a lecture. It fired 102 times in
this run: 72 on cria's own composed gate script and 30 on the coder's own commands. Two of the four
periodic gates therefore recorded the checks as **never having run**, and after call 0036 (six
minutes in) the model never saw a full test result again.

**cria fault: yes**

**evidence.** The refusal, identical every time (call 0021, the first periodic gate):

```
Chunk ID: dd3e4e
Wall time: 0.1823 seconds
Process exited with code 0
Original token count: 2389
Output:
[9,552 bytes over 231 lines — too much to return, so nothing is shown. Nothing was truncated: the
command ran and its output was discarded, not cut. Ask it a smaller question and run it again…]
```

Every occurrence, by size and chunk id: `dd3e4e` 9,552 B (call 0021 gate), `7fbfc7` 9,325 B (gate
before the compaction), `6e7569` **10,101 B** (call 0058 — the coder's own
`python3 -m pytest tests/test_integration.py -v`, exit 1), `a5fa1f` 9,325 B (call 0064 gate),
`acb807` 9,057 B (call 0081 gate), `633451` 8,912 B (call 0086 gate).

The event log is unambiguous about the cost to cria's own instrument:

```
{"kind": "loop.periodic_gate_result", "ran": false, "spoke": false}   04:47:20  (+5m07)
{"kind": "loop.periodic_gate_result", "ran": false, "spoke": false}   05:20:47  (+38m34)
{"kind": "writeproxy.exec_output_bounded", "chars": 9656,
 "cmd": "cd /tmp/suite-orders-api-py_ternary-bonsai_codex_poff_1786682533-ykre2pv6 || exi"}   ×72
```

**The arithmetic.** `proberun.PROBE_OUTPUT_CAP_BYTES = content_reduce.INLINE_RESULT_MAX_BYTES - 500`
= 8,500, and `writeproxy._bounded_exec_result` refuses a result over `READ_INLINE_MAX` = 9,000. That
derivation is exactly right **for one command**. But `probegate.py:154` does
`plan.script = "\n".join(parts)` — this run's script carried **four** commands (compileall, pyflakes,
pytest, the netns pytest re-run), each separately capped at 8,500:

```
… if [ "$__cria_n" -le 8500 ]; then printf '%s\n' "$__cria_out"; else … head -c 4250 … tail -c 4250 …
```

Four × 8,500 = 34,000 against a 9,000 bound. The derived cap is per-command; the refusal is
per-result. `tests/test_cria_never_composes_a_probe_it_will_refuse.py` asserts
`PROBE_OUTPUT_CAP_BYTES + PROBE_ENVELOPE_RESERVE_BYTES <= INLINE_RESULT_MAX_BYTES` — true, and still
insufficient, because nothing bounds the join.

**A → B → C.** A: the gate composes N probes into one shell result but budgets each one against the
whole-result bound. B: the combined result trips the refusal, so cria's own gate reads its own
refusal, finds no findings, and logs `ran: false`. C: the model, told three times to "fix what the
checks report", is shown nothing; it re-runs the same command; the wheel-spin detector then fires on
the repetition cria caused.

**fixable at A? Yes, and precisely.** Budget the **script**, not the command: divide
`PROBE_OUTPUT_CAP_BYTES` by the number of parts at composition time in
`probegate.py`/`proberun.compose_probe_command`, or run one probe per tool call. The existing test
should assert the property on the composed script with N parts, not on the constant.

There is a second, separate half. The coder's own `pytest -v` at call 0058 asked for
`max_output_tokens: 5000` and produced 3,117 tokens — inside its own request — and cria discarded it
anyway, on a byte rule the model cannot see or plan around. The 2026-08-12 operator ruling (no
elision on any path) makes this deliberate, and the exit status did survive. Recording it as the
consequence, not as a violation: the one command in the run that would have told the model what was
wrong is the command the guard ate, and it ate it four separate times.

**principle.** #12 (surface the metric from the authoritative event — the gate surfaced *its own
refusal*), #10 (verify by doing — the probe ran and cria could not read it), #16.

---

### 2. The compaction briefing certified the broken route as working, and nobody opened it again

**what happened.** At call 0039 the compactor wrote that the new route "returns a JSON object with
an `orders` array and a `total_value` field". No check had ever called that route. It returns
`{"orders": [], "total_value": 0}` for every customer, because of a slice written at call 0016. That
sentence then rode in `⟦ctx:continuation⟧` on every remaining turn, and `orders/app.py` was never
edited again in the following 76 calls.

**cria fault: yes**

**evidence.** The briefing (call 0039, `[proxy]`):

```
1. **New route `GET /customers/<name>/orders`** — added in `orders/app.py`. It returns a JSON object
   with an `orders` array and a `total_value` field (sum of quantity × unit_price for that customer).
…
4. **Parameterized queries** — every order lookup in `orders/db.py` now uses `?` placeholders …
**Current state:**
- `tests/test_db.py::test_create_and_get` — PASSED
- All 11 tests in `tests/test_integration.py` … have not yet been run successfully
```

The compactor's own instruction, in the same prompt:

```
- Only state that tests PASS or the build WORKS if the transcript shows the check ACTUALLY RAN and
  passed (a real command with passing output). If the coder merely ASSERTED success without a
  passing run in the transcript, record it as an unverified claim … A confident claim is not a
  passing test.
```

The transcript it was given contains exactly two runs of anything touching the route
(`d363cd`, `e3c65d`), and both are eleven FAILED lines. The briefing carried the *test* failures
forward honestly and turned the three *deliverables* into settled fact.

What the sentence describes, on disk (`orders/app.py:26`):

```python
name = self.path[len("/customers/"):len("/customers/orders")-len("/orders")]
```

`len("/customers/")` is 11; `len("/customers/orders") - len("/orders")` is 17 − 7 = 10. The slice is
`self.path[11:10]` — the empty string, for every request. `db.get_customer_orders("")` returns
`{"orders": [], "total_value": 0}`, which is the verifier's
`alice's items: False, total present: False`.

The briefing's effect is visible in every later reader. Coder at call 0051, with the line on screen:
*"The app.py already has the new route."* Reasoner at call 0062, with the line on screen:
*"The code looks correct and complete — all four task requirements appear already implemented."*
Reasoner at call 0079, with the line on screen: it goes straight to the conftest. Four readings of
that line by three different seats, and none of them evaluated it.

**A → B → C.** A: the compactor states a behavior no run has exercised. B: the claim is re-injected
as the agent's own prior work on every turn (`⟦ctx:continuation⟧`, quoted verbatim at calls 0048 and
0093), so items 1, 2 and 4 are closed and only the test wiring is open. C: 38 minutes of work on
`conftest.py`, and the one deliverable that was actually broken is never touched.

**fixable at A? Yes.** The evidence rule is written for *tests pass* and *the build works*; the
compactor obeyed it for those two and then asserted a *route's response shape*, which is the same
class of claim. Two changes: (a) extend the rule from "tests pass / build works" to any statement of
what the code DOES — "describe by the file it lives in and the source you read it from, never by
what it returns unless a run showed you"; (b) the briefing already says what remains — a deliverable
whose only evidence is "I wrote it" belongs in the same "unverified claim" bucket the prompt already
has words for.

**principle.** #5b (cria states a fact about the world with nothing behind it), #13 (fail closed —
an unverified deliverable is not done).

---

### 3. Wheel-spin steer #1 named the symbol, not the fault, and cost thirteen minutes

**what happened.** The first unstick directive told the coder to change a function signature. The
real fault was three lines away in `conftest.py`, in a file the reasoner never opened. The coder
complied halfway, reintroduced the same undefined name, and the identical error came back for
another thirteen minutes.

**cria fault: yes**

**evidence.** Trigger at call 0025 (`loop.wheel_spinning`, `writes: 5`, path
`tests/test_integration.py`). The reasoner read lines 1–20 of that file and nothing else. Its
directive, delivered at call 0027:

```
⟦ctx:steer⟧ Read tests/test_integration.py at lines 1–20. Line 10 has
def _req(path, method="GET", body=None, port=http_port): but http_port is never defined as a Python
variable — it's only a pytest fixture name in conftest.py . Fix the _req function by removing
port=http_port from its signature so callers pass the port explicitly.
```

The coder's next act (call 0027 reasoning): *"The issue is that `http_port` is a pytest fixture, not
a module-level constant. I need to fix the `_req` function to accept `port` as a required parameter
and have tests pass it in via the fixture."* It removed the default, went back to bare `PORT` —
undefined again — and added `http_port` to every test signature without passing it to `_req`. The
next gate reports the same class of error, now on `PORT` instead of `http_port` (call 0067):

```
tests/test_integration.py:10:46: undefined name 'PORT'
  the flagged line on disk — line 10: `def _req(path, method="GET", body=None, port=PORT):`
```

What the directive could have said is in the file the reasoner did not read. `conftest.py` at that
moment:

```python
    port = 0
    def wrapper():
        _serve(port=port, path=test_db_path)
    …
    return port, event          # returns 0, never the port the OS actually bound
```

The steer prompt forbids exactly the move that was made:

```
- Do not choose the IMPLEMENTATION. Which library to use, which data structure, which flag, which
  output format, which file to create — those belong to the TASK or to the coder, never to you. Say
  what must become true and stop.
```

"Remove `port=http_port` from its signature" is a signature edit — the implementation. "The test
client must be given the port the server actually bound to" is what must become true, and it points
at the fixture.

**A → B → C.** A: the reasoner diagnoses from the flagged line alone, because the trigger handed it
one path and the lint finding names one line. B: it authors an edit to that line. C: the coder makes
that edit, the symbol changes, the error does not, and the loop restarts.

**fixable at A? Yes.** The trigger already knows the coder rewrote *one* file five times; the
evidence bundle should include the file that file DEPENDS on when the failing name is defined there
— the pyflakes finding says "undefined name 'http_port'" and `conftest.py` is the only file in the
workspace that defines it. That is a deterministic join, not a judgment. Feed it, and the reasoner
reads the fixture.

**principle.** #2 corollary (cria does not author the work), #8 (the reasoner must be fenced to
judging, and given the evidence to judge on).

---

### 4. Wheel-spin steer #2: eight reasoner calls, two and a half minutes, one canned sentence

**what happened.** The second wheel-spin fired at 22m52. The reasoner spent calls 0040–0047 listing
three directories and reading four files — including `app.py` with the broken slice — and never
produced a directive. Twice it emitted a `<tool_call>` block as prose after being told to answer.
cria dropped the second one and fell back to a generic message.

**cria fault: yes**

**evidence.** Call 0046, after `You have inspected enough. Answer NOW with the short unstick
directive spoken to the coder ("You ..."), or EXACTLY the one word ON_TRACK`, the reasoner's whole
answer is:

```
The tester has rewritten test_integration.py at least 5 times without convergence. Let me inspect
the actual files on disk to understand the real state before directing next steps.

<tool_call>
<function=list_dir>
<parameter=path>/tmp/suite-orders-api-py_ternary-bonsai_codex_poff_1786682533-ykre2pv6</parameter>
</function>
</tool_call>
```

cria answers `[not executed — no further inspection rounds]` and asks again. Call 0047 answers with
another bare `<tool_call>`, and cria drops it:

```
{"level": "warn", "kind": "loop.steer_roleplay_dropped", "head": "<tool_call> </tool_call>"}
{"kind": "loop.spin_probe_result", "spoke": true}        — same millisecond
```

What reached the model at call 0048 instead:

```
⟦ctx:steer⟧ you have rewritten `…/tests/test_integration.py` repeatedly — rewriting it again will
not change the outcome. Stop and take a DIFFERENT next action: read the file as it is on disk right
now, run the specific thing that's failing and read the actual error, or inspect the code you
depend on. Then make one targeted change based on what you find.
```

That is the deterministic wheel-spin default, not the reasoner's judgment. The coder obeyed it
literally and spent calls 0049–0057 re-reading `__init__.py`, `app.py`, `db.py`, `conftest.py`,
`test_integration.py`, `test_db.py` and `README.md` — every one of which it had already read this
session — then ran the tests and got the discard message (finding 1).

**Was the drop right? Yes.** `<tool_call> </tool_call>` reaching the coder as a steer would be
cria emitting the harness's own tool syntax into the model's context. The guard did its job.

**The problem is what happened after the drop.** Principle #4's safe null is *inject nothing*; what
fired is a canned imperative that reads exactly like a reasoned directive and carries no new
information. Its three suggestions are the three things the coder had just done. The one thing this
seat could have contributed — it had `app.py` open at call 0046 — it did not notice.

**A → B → C.** A: the reasoner is bounded to N inspection rounds and, when it hits the bound
mid-inspection, is asked for a verdict it has not formed. B: it answers with another tool call; cria
drops it and speaks a canned line. C: 9 calls and ~4 minutes spent re-reading files, at 22–26 minutes
into a 45-minute budget.

**fixable at A? Yes, two ways, both cheap.** (a) When the inspection bound is reached, the "answer
NOW" turn should be a *fresh* prompt with no tool schema attached — a reasoner that cannot see tools
cannot call them (the classifier and steer-code roles already run this way, and neither ever emits a
tool call). (b) When the authored directive is dropped, take the safe null: the deterministic
detector fired on a real fact, but the sentence cria substitutes is not that fact — it is advice, and
the model had already taken all of it.

**principle.** #4 (a deterministic fallback behind a reasoner call), #21/#8 (the seat must be able to
answer the question it is asked), #9 (a purposeful call is cheap — eight calls that author nothing
are not).

---

### 5. The one steer that worked was the one that named cria's own defect

**what happened.** The `loop.repetition` trigger produced the only directive in the run that moved
the score-relevant work, and what it diagnosed was cria's output discard.

**cria fault: none** (recorded because it is the counter-example that dates the others)

**evidence.** Reasoner at call 0063, reasoning:

> "The issue is that the integration tests are producing too much output and getting truncated, so
> the coder can't see if they're passing or failing. They need to run a specific test with minimal
> output to see what's happening."

Delivered at call 0064:

```
⟦ctx:steer⟧ [REDIRECT]
The coder is looping — re-running python3 -m pytest tests/test_integration.py -v 2>&1 repeatedly,
getting truncated output each time with no visible results. They can't see whether any test passes
or fails. **Run a single isolated test with minimal output to see the actual error:**
cd … && python -m pytest tests/test_integration.py::test_post_order_creates_and_returns_id -v
--tb=short 2>&1 | head -50 …
```

The coder ran it and, at call 0066, saw a real traceback for the first time since call 0036. From
there it made genuine progress: `NameError: name 'PORT'` → `http_port = 0` → "The server fixture
doesn't correctly capture the actual bound port" (call 0071) → a fixed port → `ss -tlnp` proving
18080 was listening (call 0092).

Two things to record about it. First, this directive **hands the coder a command to paste**, which
its own prompt forbids and which the `steer-code` check exists to catch — and it is the directive
that helped. Second, it is delivered in the third person about the coder, to the coder, tagged
`[REDIRECT]`; the model read it as *"The user is pointing out that I'm looping"*. It worked, but that
is the shape the roleplay guard drops elsewhere, and it passed through here.

**fixable at A?** Nothing to fix in the steer. The finding is finding 1: the best thing the steer
machinery did all run was route around cria's own guard.

**principle.** none violated.

---

### 6. The model's own bug — the empty customer name — was seen by four readers and evaluated by none

**what happened.** The route's path-slicing arithmetic is wrong in the very first write of
`app.py` (call 0016) and is byte-identical in the final workspace. It is the whole of the
`customer_orders_route` failure.

**cria fault: none**

**evidence.** Written at call 0016 and never changed:

```python
if self.path.startswith("/customers/") and self.path.endswith("/orders"):
    name = self.path[len("/customers/"):len("/customers/orders")-len("/orders")]
```

Verifier detail: `GET /customers/alice/orders -> 200, alice's items: False, total present: False` —
a 200 with an empty body is exactly what `name == ""` produces.

The model's own test would have caught it
(`test_get_customer_orders_returns_orders_and_total` asserts two orders and 22.50) — but that test
never reached its assertions, because the server never started (finding 7). And the same call that
wrote the slice also wrote `except (KeyError, TypeError, ValueErr)`, caught it one call later, and
fixed it; the slice produced no error to catch.

**The context that would have let it catch itself.** Nothing cria said, and one thing cria could
have: the periodic gate runs `pytest` and nothing else. A gate that had ever *called the route* — a
single `curl`-equivalent against the running service, the way `verify.py` does — would have printed
`{"orders": [], "total_value": 0}` for `alice` and the model would have had a fact to work from
instead of a fixture to fight. That is not a task-specific probe: "the project declares an entry
point; start it and ask it for something" is as general as "run the tests". It is worth measuring
before building (#15).

**principle.** none violated by cria; #10 by omission — the gate verifies by running the tests, and
the tests were the thing that could not run.

---

### 7. The fixture that starts the server is never requested by a single test

**what happened.** After call 0083 the conftest is clean and correct in isolation: `stop_server`
starts the app and waits for the port. No test asks for `stop_server`. Every test takes only
`http_port`, which is a bare `return TEST_PORT`. So pytest never instantiates the fixture that
starts anything, and all eleven tests die on connection refused.

**cria fault: none**

**evidence.** Final `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def http_port():
    return TEST_PORT              # 18080 — no server involved

@pytest.fixture(scope="session")
def stop_server(http_port, test_db_path):
    …thread.start()…              # the only thing that starts the server
```

Final `tests/test_integration.py` — all eleven signatures are `def test_…(http_port):`.
`.pytest_cache/v/cache/lastfailed` holds exactly those eleven names.

The model proved the server works at call 0092 (`Port is LISTENING`, `ss` shows
`127.0.0.1:18080 … python3`) and concluded *"The issue is timing — the test connects before the
server thread finishes starting"*, then added a ten-attempt retry loop. Under pytest there was no
server at all to be early for. It ran out of clock two calls later.

**A → B → C.** A: the fixture that has the side effect is named for the teardown handle, not the
setup. B: the tests request the port, which looks like the thing they need. C: the server is never
started, and the model reads the resulting connection refusal as a race.

**fixable at A?** Not at cria. The nearest general assist is finding 6's: a gate that exercises the
service would have separated "the app doesn't work" from "your test harness doesn't start it".

**principle.** none.

---

### 8. Twice the model found the real cause in its own words and lost it

**cria fault: none** — recorded because it is the tell that separates "never found it" from
"found it and dropped it" (#8, the method note).

Call 0053, having just read the conftest:

> "The conftest has a bug — it passes `port=port` (which is 0) but never actually sets PORT before
> calling `_serve`. The server won't bind properly."

It then read two more files and ran the tests instead of fixing it. Call 0036 had already shown it
`http_port = 0` in the pytest failure header and it wrote a rewrite that changed neither.

Call 0071 finds it again and this time acts:

> "The problem: in `conftest.py`, `_serve(port=port, path=path)` — but `port` is 0 (the default).
> The server binds to port 0 which means 'pick a random available port', but we never capture what
> that port actually is."

The fix it then wrote bound a second `HTTPServer` on the same port and left it running; it caught
that itself at call 0075 (*"I'm starting two servers on the same port"*) and retreated to a fixed
port. Real convergence, at 30 minutes, with 15 left.

---

### 9. Smaller things, in one place

- **Two writes byte-identical to what was already on disk** (call 0030, call 0031) after the model
  said "let me fix this properly". `loop.repetition` caught the second one. cria fault: none; the
  note fired correctly.
- **The repetition note was misread.** Call 0084 reasoning: *"I see the issue - I keep getting the
  same output because the tool is caching my previous response."* The note says the call "returned
  the exact same result every time"; the model concluded the tool caches. It did take a different
  action, so no harm — but "it has told you everything it can" is being read as a statement about
  the tool rather than about the repetition.
- **The dirguard refusal fired twice on a mistyped workspace path** (`…ternary-bonsai_poff…`,
  calls 0029 and 0081-era) and named both the real project directory and the bad path. The model
  self-corrected each time. Working as intended; ~2 calls.
- **The periodic gate says the same thing twice in one turn.** At calls 0038 and 0067 the tool
  result carries `⟦ctx:checks⟧ …` and the very next user message is `⟦ctx:steer⟧ I am giving you the
  CURRENT state of the repo …` containing the identical findings block. Two copies of the same four
  lines. Noise, not a lie — but it doubles the most-repeated text in the window.
- **Throughput collapsed with depth**: `⟦cria⟧ coder · ternary_bonsai_27b_q2_0 · 50 tok/s` at the
  start, `· 3 tok/s` near the end. The last ten minutes of the run are eight calls. Any fix that
  saves calls early is worth several late ones.

---

### 10. Recent fixes — did they behave?

**Derived probe cap (`PROBE_OUTPUT_CAP_BYTES` from `INLINE_RESULT_MAX_BYTES`) — HALF-FIRED, and the
half that missed cost the run.** The constant is in place and the composed script carries the right
per-command arithmetic (`-le 8500`, `head -c 4250`). It still refused five gate results and logged
`ran: false` twice, because `probegate.py:154` joins four commands into one result and only the
result is bounded. This is finding 1 and it is the single highest-value fix on this walk.

**Reasoning logged even on unfinished streams — HELPED.** 83 `coder.reasoning` events over 92
completions, and the reasoning is present on turns that ended in prose as well as tool calls.
Findings 2, 3, 6 and 8 are only provable from it — "the app.py already has the new route" (call
0051) and "the conftest has a bug … port is 0" (call 0053) are both reasoning-only. Nothing was
captured for the final call 0093, and that is because the process was killed mid-stream, not a
capture failure.

**Completion-judge "report, not an order" framing, and the verdict tool on the judge's menu — DID
NOT FIRE.** Zero `loop.task_complete`, zero `loop.done_critic`, zero `loop.completion_probe` in the
run window. The model never claimed to be finished, so the completion path was never exercised. No
evidence either way from this cell.

**Search results inlined rather than spilled — DID NOT FIRE.** No `web_search` or `web_fetch` in the
run; the task needs no external source.

**Cached-check age note — FIRED, on an empty section, twice.** Call 0077's reasoner prompt:

```
GROUND TRUTH FROM THE REPO'S CHECKS— these ran BEFORE the coder wrote …/tests/conftest.py,
…/tests/test_integration.py, so they describe the code as it was, not as it is now:
(no check results for this steer)
```

The age sentence is correct in form and is dating nothing — there are no results under it. Calls
0040 and 0059 carry the same section with the same `(no check results for this steer)` and no age
line at all. Two shapes for one empty section; the honest one is to say the section is empty and stop.
Small, but it is the same family as finding 2 — a sentence emitted in cria's own voice with no
referent.

**`loop.steer_roleplay_dropped` — FIRED CORRECTLY, and what followed it did not.** See finding 4:
dropping `<tool_call> </tool_call>` was right; substituting a canned directive for the dropped one
was the miss.


---

## Cross-run — cria refuses its own gate's output

Verified directly in the captures, not inferred. This is the top cria fault of cycle 1 and it is
self-inflicted by the cycle's own probe-cap change.

### What happens

`probegate` composes ONE shell script holding several probes and caps each probe's output at
`proberun.PROBE_OUTPUT_CAP_BYTES` = 8,500 (`INLINE_RESULT_MAX_BYTES` 9,000 minus a 500-byte
envelope reserve). The harness runs the script and returns the JOINED result. That joined result is
then measured by `writeproxy._bounded_exec_result` against `READ_INLINE_MAX` — the same 9,000.

Two probes of 5 KB each clear the per-probe cap and blow the per-result bound, so cria discards its
own gate output whole and hands the coder this instead:

> `[9,552 bytes over 231 lines — too much to return, so nothing is shown. Nothing was truncated:
> the command ran and its output was discarded, not cut. Ask it a smaller question and run it
> again: send it to a file and search that …]`

The coder did not write that command. cria wrote it. It cannot "ask it a smaller question", and the
sentence is addressed to an author who is not there. The harness's own envelope on that same call
reads `Original token count: 2389` — cria refused two and a half thousand tokens.

### It is not catching floods

Every refusal in the two runs where it fired sits within 12% of the bound:

| run | refused results |
|---|---|
| `orders-api-py_ternary-bonsai_1786682533` | 9,552 · 9,325 · 10,101 · 9,057 · 8,912 bytes (194–248 lines) |
| `orders-api-py_gemma4_1786679396` | 4 results, same band |

231 lines of pytest output is an ordinary test run, not the 302,983-token flood the bound was
written for. `10,101` was the coder's own `pytest`, discarded at the moment it most needed reading —
eleven of its tests were failing.

### And the two policies inside it contradict each other

The gate script carries its own elision: `head -c 4250 … middle %d bytes elided … tail -c 4250`.
That is truncation of model-read content, which the operator's 2026-08-12 ruling removed everywhere
else — and the outer bound then refuses the elided result anyway. One composed result, truncated by
one owner and refused by another.

### A → B → C

- **A** — two bounds derived independently: a cap applied PER PROBE, a bound applied PER RESULT, and
  a gate that joins N probes into one result. Nothing reconciles them.
- **B** — an ordinary gate run exceeds the bound and is discarded whole.
- **C** — the coder never sees its failing tests, and cria never sees its own ground truth: two of
  four periodic gates in that run recorded `ran: false, spoke: false`. The run spun 45 minutes on
  a defect its own test output names.

### Fixable at A? Yes.

The per-probe cap must be derived from the bound the JOINED result will be measured against, across
the probes actually in the plan — one owner computing both, not two constants that happen to share a
parent. The gate's internal head+tail elision goes with it: cria bounding its own composed probe is
allowed (#5's counter-nuance), but not in a way that leaves the outer owner refusing the result
anyway.

Principles: #10 (cria's own probe is the ground truth, and it was destroyed), #5b (a refusal
instructing the coder to re-run a command it did not author), #12, #2.

### Prevalence

Distinct refusals across the 24 cycle-1 cells: 21, in 7 runs — `shipping-rates-rb × gemma4` (1),
`orders-api-py × gemma4` (4), `orders-api-py × ternary-bonsai` (5), `feed-pipeline-java × gemma4`
(2), `feed-pipeline-java × qwen35` (6), `rust-toml-cli × ternary-bonsai` (1),
`rust-toml-cli × nemotron-elastic` (2). Not every run that hits it loses — two cells with refusals
still scored 100% — so the refusal is a tax, not a guaranteed kill. It is above the prevalence bar
either way, and the fix costs nothing anyone is relying on.

---

## feed-pipeline-java_gemma4_codex_poff_1786688189

Commit 2bbf2c5. 54 calls, 966 s wall, terminal `milestone-miss-15min` (score 0 against a floor of 1,
confirmed by a recheck). Score 0/5, down from 80% last cycle — tied for the worst regression in the
cycle. Phases: 48 coder, 2 reasoner, 1 classifier, 1 research-step, 1 self-compact, 1 proxy.
Assists that fired: 3 periodic gates, 2 `loop.wheel_spinning`, 1 `rumination.abort`, 1
`context.self_compact`, 1 `route.compaction`, 1 `loop.gate_swept`.

All five checks died on one missing line. The model's rewritten
`src/main/java/pipeline/Importer.java` begins `import org.apache.commons.csv.*;`, not
`package pipeline;`, so the class compiled into the DEFAULT package —
`target/classes/Importer.class`, not `target/classes/pipeline/Importer.class`. The verifier's bench
does `import pipeline.Importer;` and gets `error: package pipeline does not exist`. The file is
valid Java, `mvn compile` is happy, and every cria check went green over it. What was lost is the
file's **identity**, not its validity.

Shape of the run in one line: at fourteen minutes the model made a one-line surgical edit that
turned the build GREEN, cria's stuck-detector fired anyway on a five-writes-ago counter, the
reasoner — holding a clean check in its own prompt and believing the build was still broken — told
it to go re-inspect the worker implementation, the coder answered with a whole-file rewrite that
silently dropped the package line, cria's gate then compiled that file, **deleted the class file
that proved the regression**, and reported no problems; the model spent the last seven minutes
chasing a classpath ghost and worked out the real cause in its final reasoning, one call before the
clock killed it.

**The clock, from the event log** (run start 23:17:00):

| +time | call | what |
|---:|---:|---|
| 2m41 | 0018 | periodic gate 1 — `ran: true, spoke: true` (compile RED, `MapRecord`) |
| 4m31 | 0021 | `loop.wheel_spinning` #1 (`writes: 5`) → steer at 0022 |
| 9m17 | 0028 | `rumination.abort` (`degenerate: true`, 159 s, no tool call) |
| 9m54 | 0029 | `coder-s1-focus1` — the `[OUTPUT LOOP]` reframe |
| 10m12 | 0030 | `context.self_compact` (59 turns → 15) |
| 10m17 | 0032 | `route.compaction` |
| 11m31 | 0037 | `loop.wheel_spinning` #2 (`writes: 5`) → steer delivered at 0038 |
| 14m26 | 0038 | **the packageless rewrite**; periodic gate 2 GREEN, `loop.gate_swept` deletes the class |
| 14m44 | 0042 | `ClassNotFoundException: pipeline.Importer` — the seven-minute chase begins |
| 15m44 | 0054 | model finds the cause in its own reasoning; killed |

Findings ranked worst first.

---

### 1. The unstick steer fired on a GREEN build, and the rewrite it invited dropped `package pipeline;`

**what happened.** At call 0036 the coder made a targeted one-line edit that fixed the last compile
error; the gate that ran immediately after reported no problems and told the coder in cria's own
voice *"do not rewrite the whole file again."* `loop.wheel_spinning` then fired on a write counter
from before that fix, and the reasoner — with the clean check in its prompt — authored a directive
saying the coder had not fixed anything and should go re-inspect the worker. The coder answered with
a whole-file `write_file`, and the new content's first line is an `import`.

**cria fault: yes**

**evidence.** Call 0036, the surgical edit that worked:

```
edit_file  path=src/main/java/pipeline/Importer.java
  old_string: "for (String name : record.headers()) {"
  new_string: "for (String name : csvParser.getHeaderNames()) {"
→ Wrote src/main/java/pipeline/Importer.java
```

The gate result in the very next tool response:

```
⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems. The checks above
cover syntax and lint only — no test command was composed, so nothing here says whether this
project's tests pass. No mvn test tests were found …
```

`loop.wheel_spinning {"step": 1, "path": "src/main/java/pipeline/Importer.java", "writes": 5}` fires
at t+731 s. The reasoner prompt at call 0037 carries the trigger line and the check result side by
side:

```
WHAT TRIPPED THE DETECTOR:
It has rewritten the file `src/main/java/pipeline/Importer.java` at least 5 times with varying
content and it still is not converging.
…
GROUND TRUTH FROM THE REPO'S CHECKS:
the repo's own checks that ran (lint / type-check / syntax) found no error-class problems in your
current edits. If you still need to change this file, make a small TARGETED edit at the specific
line — do not rewrite the whole file again.
```

The reasoner read past both. Its private reasoning at call 0037:

> "`mvn clean compile` failed previously (not shown in the snippet but implied by the "STUCK" flag
> and history). Actually, the transcript shows an error during `mvn clean compile`, but it's
> truncated."
> …
> "The repo check says 'no error-class problems', but that's just syntax."

and the directive it produced, delivered verbatim to the coder at call 0038:

```
⟦ctx:steer⟧ Stop repeatedly rewriting src/main/java/pipeline/Importer.java with minor adjustments
that do not progress toward the primary requirements. You have yet to demonstrate a 4x speed
improvement or confirm that the threading bug is fixed and parallel workers are functional.
Identify the specific source of the threading bug and verify it is resolved before making further
changes to the record processing logic. Read src/main/java/pipeline/Importer.java to inspect the
current worker implementation and identify where concurrency is being blocked.
```

Two of those sentences are false of the world at that moment: the file had just converged (the
compiler said so in the same prompt), and concurrency was not "being blocked" —
`WORKERS_ENABLED = true` had been on disk since call 0014.

The coder's reasoning at 0038 opens by adopting it — *"The user wants me to stop making minor
adjustments that don't progress toward the requirements"* — spends 440 lines re-reading the file it
already had, and then issues **not** a targeted edit but a full `write_file`. The first bytes of the
`content` argument:

```json
{"content":"import org.apache.commons.csv.*;\nimport java.io.IOException;\nimport java.io.Reader;\n…","path":"src/main/java/pipeline/Importer.java"}
```

`package pipeline;` is gone. Every previous write in the run — calls 0013, 0015, 0017, 0019, 0023,
0025, 0026, 0029 — began `package pipeline;`. This is the only one that does not, and its content is
byte-identical to the final workspace file.

**Was it an edit-recovery escalation? No.** cria's edit-recovery never fired on this file. The one
`⟦ctx:edit⟧` refusal in the run was on `pom.xml` at call 0010, and it worked (read, retry, wrote).
The whole-file rewrite at 0038 was the coder's own choice, made against *two* cria strings telling it
not to (the gate's "do not rewrite the whole file again" and the coder system prompt's "Do NOT
rewrite a whole file to make a one-line change") and *one* cria string telling it to go re-inspect
and change the worker. The steer is the newest message in the window and it won.

**The only functional difference** between the green file at 0036 and the fatal file at 0038 is that
one `catch (Exception e)` became three catches. The package line was collateral on a rewrite that
was carrying a five-line change.

**A → B → C.** A: the wheel-spin trigger counts writes over a window that spans a compaction and does
not reset when a check goes green, so it fires on a converged file. B: the reasoner, told the coder
is "not converging", discounts the clean check as "just syntax" and orders a re-inspection of a bug
that is already fixed. C: the coder rewrites the whole file to obey, drops the declaration that makes
the class addressable, and every check dies on `package pipeline does not exist`.

**fixable at A? Yes, two places, both cheap.**
(a) *The trigger.* `loop.wheel_spinning` is a deterministic trigger and it is allowed to be noisy —
but it must not assert. Its text says "**it still is not converging**", which is a claim about the
world, and cria's own check in the same prompt contradicts it. Make the trigger report the count and
stop, and gate it on the check *not* being green: a file that just went from red to green on a
one-line edit is the definition of converging, and cria knows that deterministically.
(b) *The steer author.* The prompt already ranks the checks as authority #1 and the reasoner
explicitly downgraded them in writing. The seat needs one hard fence in the same shape as the
"do not state a CAUSE you have not verified" rule: **if the current checks are clean, you may not
tell the coder that the thing the checks cover is broken.** Everything the directive asserted
(build broken, concurrency blocked) is inside what the checks had just answered.

**principle.** #5b (cria states a false fact — "still is not converging", "where concurrency is being
blocked"), #3 (silence over noise — the signal was clean and cria spoke anyway), #8 (the reasoner
must be grounded on the evidence it was given, not on the trigger's framing), #2 (an intervention
must not make something already working worse — this one did, exactly).

---

### 2. cria compiled the packageless file, produced the artifact that proved it, deleted that artifact, and said nothing

**what happened.** The gate that ran right after the fatal rewrite compiled the code. That compile
created `target/classes/Importer.class` — the class in the wrong place, which is the whole failure in
one filename. cria's litter sweep classified it as probe litter and deleted it, leaving behind an
empty `target/classes/pipeline/` directory. Eighteen seconds later the model went looking, saw the
empty `pipeline/` directory, and concluded its class was exactly where it expected.

**cria fault: yes**

**evidence.** The event, at t+906.3 s (23:31:26):

```
{"kind": "loop.gate_swept", "paths": 2,
 "sample": ["target/classes/Importer$Summary.class", "target/classes/Importer.class"]}
{"kind": "loop.periodic_gate_result", "ran": true, "spoke": false}
```

`probegate.sweep_litter` (cria/probegate.py:956) removes "the untracked files the gate's OWN probes
created", computed as git's `??` set before minus after. In this repo the seed **tracks its build
output** — `git ls-files` in the archived workspace lists
`target/classes/pipeline/Importer$Summary.class` and `target/classes/pipeline/Importer.class`, and
there is no `.gitignore`. So the old, correct class file is tracked and invisible to the sweep, and
the new, wrong-package class file is untracked and gets deleted. The sweep is behaving exactly as
written and it is deleting the coder's build.

What the model saw eighteen seconds later, call 0044:

```
--- list_dir target/classes ---
total 12
drwxr-xr-x 3 jesse jesse 4096 Aug 13 23:31 .
drwxr-xr-x 5 jesse jesse 4096 Aug 13 23:27 ..
drwxr-xr-x 2 jesse jesse 4096 Aug 13 23:31 pipeline
```

and what it concluded, in cria's own transcript:

> "The class `pipeline.Importer` is in `target/classes/pipeline`. The maven exec plugin should be
> able to find it if I specify the classpath or if it's configured correctly."

That directory was empty. `ls -R target/classes` at call 0053 proves it:

```
target/classes:
Importer$Summary.class
Importer.class
pipeline

target/classes/pipeline:
```

Between those two listings the model burned calls 0042–0053 — `mvn exec:java`, reading `pom.xml`,
`mvn compile`, `java -cp target/classes`, `mkdir -p src/test/java/pipeline && mvn test`,
`mvn dependency:copy-dependencies`, `java -cp "target/classes:target/dependency/*"`,
`mvn exec:java -Dexec.classpath=…`, two `list_dir target/classes` — every one of them returning
`Could not find or load main class pipeline.Importer` or `ClassNotFoundException: pipeline.Importer`,
and the model theorising about missing dependencies and shell glob expansion:

> "Okay, `java -cp target/classes` didn't work because it doesn't include the dependencies (like
> commons-csv)."  (call 0046)
> "This might be because I'm running it from a different directory or there's something wrong with
> how the classpath is being expanded in the shell."  (call 0050)

Seven minutes. The run had seven minutes left.

**A → B → C.** A: the sweep's definition of "litter" is "untracked and created by my probe", and in a
project that commits `target/` the coder's *new* build output is untracked while the *old* one is
tracked. B: cria deletes the newest build artifact immediately after every gate, leaving a stale
empty package directory as the only thing on disk. C: the model reads the leftover directory as
evidence its class is correctly placed and spends the rest of the budget on the classpath instead of
the package line.

**fixable at A? Yes, and the fix is a strict improvement over deleting.** The sweep already computes
the exact comparison that names this bug: the set of build outputs before the probe versus after. It
currently uses that set only as a delete list. Two changes, in order of value:

1. **Never sweep a path under a directory the build system owns** (`target/`, `build/`, `dist/`,
   `bin/`, `obj/`, `__pycache__`). cria's probe did not "litter" there — it built there, which is what
   the build directory is for, and the coder needs the result. Litter-sweeping is for scratch files
   cria's probes leave in the source tree.
2. **Surface the set, do not just delete it.** When a build probe produces an output at a path where
   a *tracked* output of the same basename already exists elsewhere in the tree —
   `target/classes/Importer.class` appearing while `target/classes/pipeline/Importer.class` is tracked
   — that is a deterministic anomaly, computed from git and the filesystem with no language knowledge
   at all, and it is the general form of finding 8's guard. See finding 9.

**principle.** #10 (verify by doing — cria's probe produced the ground truth and cria destroyed it),
#5b (the world cria left behind — an empty `pipeline/` directory — told the model something false, and
cria made it that way), #2 (the sweep deleted correct content; ADDITIVE/RECOVERY is the safe class).

---

### 3. The gate said the error line "could not be parsed" while quoting the least useful line of an output that contained it

**what happened.** The first periodic gate got a perfectly ordinary javac error with file, line and
column. cria's summary said no specific line could be parsed and quoted the Maven help URL instead.
The reasoner then built an entire directive on the premise that the error messages were truncated —
and sent the coder to re-run a command whose full output it already had on screen.

**cria fault: yes**

**evidence.** The tool result at call 0018 (`⟦ctx:checks⟧`, cria's own words, first four lines):

```
[ERROR] COMPILATION ERROR :
[ERROR] …/src/main/java/pipeline/Importer.java:[103,18] cannot find symbol
  symbol:   class MapRecord
  location: class pipeline.Importer
```

The `⟦ctx:steer⟧` cria composed from that same output, in the same turn:

```
⟦ctx:steer⟧ I am giving you the CURRENT state of the repo (syntax & tests). If anything below is
broken, fix syntax errors FIRST before continuing and then tests; if it's all clean, carry on.
the repo's own checks FAILED, but a specific line could not be parsed from the output:
$ mvn -q compile — exited 1: [ERROR] [Help 1] http://cwiki.apache.org/confluence/display/MAVEN/MojoFailureException
$ mvn test — exited 1: [ERROR] [Help 1] http://cwiki.apache.org/confluence/display/MAVEN/MojoFailureException
Run that exact check yourself and read the actual error…
```

`Importer.java:[103,18] cannot find symbol` is a file, a line and a column. The Java finding matcher
does not recognise Maven's `path:[line,col]` bracket form (it matches `path:line:col`), so
`completion_block_nudge` found nothing and cria fell through to `failed_unparsed_probes`, which
prints the LAST `[ERROR]` line — which for Maven is always the help URL.

The same false claim was then handed to the reasoner as authority-tier-1 ground truth (call 0021):

```
GROUND TRUTH FROM THE REPO'S CHECKS:
the repo's own checks FAILED, but a specific line could not be parsed from the output:
$ mvn -q compile — exited 1: [ERROR] [Help 1] http://cwiki.apache.org/…/MojoFailureException
```

and the reasoner built its whole directive on it — reasoning:

> "The current check output only shows `[ERROR] [Help 1] …MojoFailureException`. It doesn't show the
> actual Java compiler error (e.g., "cannot find symbol")."

directive at call 0022:

```
⟦ctx:steer⟧ Stop rewriting src/main/java/pipeline/Importer.java in its entirety. You are stuck in a
loop of "rewritten the file... at least 5 times" while receiving truncated error messages that do
not reveal the underlying compilation failure. Execute a command to run mvn compile without the -q
(quiet) flag or use javac directly on the source files to capture and resolve the specific compiler
errors causing the MojoFailureException.
```

Nothing was truncated. The coder obeyed (`mvn clean compile`, call 0022) and got back the identical
text it had already been shown, twice. Cost: ~2 calls and one more full-file rewrite at 0023.

**A → B → C.** A: the finding matcher does not know Maven's `[line,col]` bracket form, so a parseable
error is reported as unparseable. B: cria states "a specific line could not be parsed" — a claim about
cria's matcher, presented as a claim about the output. C: the reasoner diagnoses "truncated error
messages", orders a command that changes nothing, and two calls are spent re-reading a message that
was never hidden.

**fixable at A? Yes.** Two independent fixes, and both should land:
(a) Add Maven's `path:[line,col]` form to the Java finding matcher — it is a spelling of the same
kernel the matcher already handles, not a new rule. But keyed to javac's punctuation it is exactly the
by-shape smell the operator has flagged twice, so:
(b) When no line parses, **quote the checker's own first ERROR-class line rather than its last one.**
Maven, gradle, cargo and go all put the diagnosis first and the boilerplate last; picking the tail is
what turned a real error into a help URL. And drop the phrase "a specific line could not be parsed
from the output" — say what cria actually knows: *"the check failed; cria could not locate a
file:line in the output, so here is what it printed."* The current sentence tells the model the output
lacks something the output has.

**principle.** #5b (the tell, exactly: an assertion the world contradicts, built on a partial matcher),
#12 (surface the metric from the authoritative event — the exit code was right, the located finding
was invented from the wrong line), #23b at the code level.

---

### 4. Three gates, three chances, and what each one could have known

The question this walk was sent with. All three gates ran the same composed script; none of them
lied, and none of them said the one thing that mattered.

**The command, identical every time** (call 0018 shown, workspace path shortened):

```
cd <ws> && __cria_out=$(timeout -k 5 240 python3 -c '…ElementTree parse…' <ws>/pom.xml …); printf 'EXIT:%d\n' …
cd <ws> && __cria_out=$(timeout -k 5 240 mvn -q compile …); printf 'EXIT:%d\n' …
cd <ws> && __cria_out=$(timeout -k 5 240 mvn test …); printf 'EXIT:%d\n' …
__cria_test_ec=$__cria_ec
cd <ws> && if [ "${__cria_test_ec:-1}" -eq 0 ] && unshare -rn -- true …; then … exec mvn test …; fi
```

| gate | +time | result | what it said | what it could have known |
|---|---:|---|---|---|
| 1 | 2m41 | `ran: true, spoke: true` | the compile errors (finding 3 mangled the summary) | correct and useful; the package was still intact |
| 2 | 14m26 | `ran: true, spoke: false` | "no error-class problems … No mvn test tests were found" | **it had just compiled the packageless file and created `target/classes/Importer.class`, then deleted it** (finding 2) |
| 3 | 15m44 | `ran: true, spoke: false` | same | same |

**cria fault: none for what they said; yes for what they threw away** (that half is finding 2).

Gate 2 and 3 are the crux and they are honest: `mvn -q compile` exited 0, so "no error-class
problems" is true. The gate's disclosure is also exactly right — it volunteers *"The checks above
cover syntax and lint only — no test command was composed, so nothing here says whether this
project's tests pass. No mvn test tests were found — to be run they must be annotated @Test, in a
file named *Test.java or *Tests.java (surefire default)."* That is #3 and #5b both behaving: it states
the limit of its own claim instead of hedging or overclaiming.

What no gate did is **run the thing the project says it is**. `README.md`, which cria read into the
transcript at call 0041, gives the entry point in two lines:

```
mvn -q exec:java -Dexec.mainClass=pipeline.Importer -Dexec.args=data/feed.csv
java -cp target/classes pipeline.Importer data/feed.csv
```

Either one, run by the gate at 14m26, prints `ClassNotFoundException: pipeline.Importer` and the run
is saved. The gate compiles and it tests; it never *runs*. Same gap as the `orders-api-py` walk's
finding 6 (a gate that never called the route), in Java dress: **"the project declares an entry point;
start it and ask it for something"** is as general as "run the tests", and this is the second cell in
one cycle where it is the missing probe. Worth base-rating before building (#15) — but two independent
cells now.

**principle.** none violated. #10 by omission.

---

### 5. Did the model ever compile or test against the package path? Yes — and it went green, which is the trap

**what happened.** After the fatal rewrite the model ran `mvn compile` three times and `mvn test`
once. All four succeeded. The package was wrong the whole time.

**cria fault: none**

**evidence.** Every build the model ran after call 0038:

| call | command | result |
|---:|---|---|
| 0038 | (gate) `mvn -q compile` + `mvn test` | `⟦ctx:checks⟧ … reported no error-class problems` |
| 0045 | `mvn compile` | `BUILD SUCCESS`, exit 0 |
| 0046 | `mvn compile && java -cp target/classes pipeline.Importer data/feed.csv` | compile SUCCESS; **`Error: Could not find or load main class pipeline.Importer`** |
| 0047 | `mkdir -p src/test/java/pipeline && mvn test` | `BUILD SUCCESS`, exit 0 (zero tests) |
| 0054 | (gate) same script | `… reported no error-class problems` |

Call 0047 is the purest form of it: the model created an empty test directory and Maven returned
`BUILD SUCCESS` — `maven-surefire-plugin … [INFO] BUILD SUCCESS` over zero tests. cria's gate had
already disclosed that condition in words (finding 4), so cria did not sell it as proof, but the raw
`mvn test` exit 0 in the model's own hand did.

Call 0046 is the moment the world told the truth: the README's own command, verbatim, failing. The
model had `Could not find or load main class pipeline.Importer` on screen four separate times
(0042, 0046, 0049, 0050) before it read it correctly. Nothing cria said pointed at it, and nothing
cria said pointed away from it either — this one is the model's.

**principle.** none.

---

### 6. The two wheel-spins and the rumination abort — helped, nothing, or worse

**`loop.wheel_spinning` #1 — call 0021, delivered 0022. Verdict: WORSE (mildly).**
Trigger: `{"step": 1, "path": "src/main/java/pipeline/Importer.java", "writes": 5}` — deterministic and
true; the coder had genuinely rewritten the file five times. What the reasoner authored is quoted in
finding 3: a directive premised on truncated errors that weren't. What reached the model reached it
intact. What the model did next: `mvn clean compile` (call 0022), got the same bytes, then rewrote the
whole file again (call 0023). Net: two wasted calls, one more full rewrite, and the "the errors are
truncated" frame stayed in the window.

**`rumination.abort` — call 0028. Verdict: HELPED, and the reframe after it helped more.**
`{"degenerate": true, "chars": 2048}` after 159 s of generation with no tool call. The reasoning it cut
off is the clearest thing in the run: the same four sentences about `CSVRecord.Field`, verbatim, six
times —

> "I'll try this: I'll just use a `while` loop with an iterator and see what happens. If it fails,
> I'll just use `record.get(name)`. But how do I know the names?
> Actually, I have an idea! I'll just use the fact that `CSVRecord` has a method to get all fields as
> a map! Wait, does it? Let me check… No, but maybe I can build it."

The detector fired correctly and the `coder-s1-focus1` reframe that followed is a model of the shape:

```
[OUTPUT LOOP] Your last turn stopped generating new text — the tail of it was one short passage
repeating over and over — and it was aborted before it produced a tool call.
This is not about thinking too hard; it is that the same words kept coming out. Do not re-examine
and do not restart from scratch. Take the simplest concrete next step you already know, and take it
NOW as a single tool call.
```

It states a fact about the stream, gives no diagnosis, and asks for one action. The model's next turn
was 20 lines of reasoning and exactly one `write_file`. That is what the other two steers should look
like.

**`loop.wheel_spinning` #2 — call 0037, delivered 0038. Verdict: WORSE, and it is finding 1.**
This is the one that cost the run.

**A note on the trigger itself.** Both wheel-spins carry `"writes": 5`, and the second fired 420 s
after the first with a `context.self_compact` and a `route.compaction` in between. The counter is not
reset by a compaction and not reset by a green check, so the second firing is substantially the same
five writes being counted again — the coder had made *one* write and *one* surgical edit since the
reframe. A detector that can fire twice on the same evidence is a detector that will fire on a
converged file, which is what happened.

**principle.** #1 (every assist can become a footgun — two of the three fired on real triggers and
produced worse-than-nothing directives), #3, #21/#8.

---

### 7. The repetition note called three different writes "this exact call"

**what happened.** cria told the model it had made the same call three times with the same result. The
three calls wrote three genuinely different files.

**cria fault: yes** (small, but it is the same disease as findings 1 and 3)

**evidence.** Call 0027:

```
[you have now made this exact call 3 times and it returned the exact same result every time — the
earlier copies were folded away, so this is the only record of it. Tried:
write_file(src/main/java/pipeline/Importer.java). Repeating it again will return that same result:
it has told you everything it can. Read what it already returned above, or take a DIFFERENT action.]
```

The three writes it folded were: call 0024 (`record.forEach(field -> map.put(field.name(), …))`),
call 0026 first write (a 20-line stub whose `load` body is two comments and returns an empty list),
and call 0026 second write (`for (CSVRecord.Field field : record)`, the full 158-line file). Three
different files. What was identical is the *return value* — `Wrote src/main/java/pipeline/Importer.java`
— because that is what a write always returns.

The note fires again, correctly, at call 0052 on two identical `list_dir(target/classes)` calls. The
difference is the tool: a read repeated is a no-op, a write repeated is not. Fingerprinting a
**write** on `(tool, path)` and then asserting "it returned the exact same result every time … it has
told you everything it can" is a category error — the point of a write is its effect on disk, and the
note's advice ("Read what it already returned above") is meaningless for one.

The `orders-api-py × ternary-bonsai` walk recorded the model misreading this same note as "the tool is
caching my previous response". Two cells, two misreadings, same sentence.

**fixable at A? Yes.** Fingerprint a mutating call on `(tool, path, content-hash)`, not `(tool, path)`
— cria has the content in the args (#12: key on the authoritative event, which for a write includes
what was written). A genuine byte-identical rewrite is still worth flagging and would still fire.

**principle.** #5b, #12.

---

### 8. The model found the root cause in its last reasoning and the clock took it

**what happened.** At call 0053 the model finally ran `ls -R target/classes`, saw the class files at
the root, and worked out the whole thing. It was killed on the next call.

**cria fault: none** (suite timing)

**evidence.** Call 0054, its final reasoning and its final words:

> "I see what happened. `Importer.class` and `Importer$Summary.class` are at the root of
> `target/classes`. This means my source code was NOT under package `pipeline`.
>
> Wait, let me check the file again.
> ```java
> package pipeline;
> ```
> If it's in the `pipeline` package, then after compilation, it should be in
> `target/classes/pipeline/Importer.class`.
> …
> Why are they at the root of `target/classes`? This usually happens if the source directory is
> configured incorrectly or if the file was moved.
> Let me check the structure again."

→ `exec_command {"cmd": "ls -R src/main/java"}` → killed.

It had the diagnosis in words ("my source code was NOT under package `pipeline`") and was one
`read_file` from the fix — a single `edit_file` prepending one line. Note the tell in the middle: it
quotes `package pipeline;` from memory as if it were still in the file. It never re-read the file it
rewrote at 0038; nothing in the run ever showed it the first line of its own output.

**Was it about to recover, or lost?** About to recover — but it had been lost for seven minutes
before that, and the seven minutes were finding 2's. It is worth being precise about the ceiling: even
with the package restored at 15 minutes, `review_written` fails (`no REVIEW.md` — never written) and
`substantially_faster` fails (never benchmarked, and `load` still builds a `HashMap` per row).
Restoring the line buys `messy_feed_handled`, `csv_library` and probably `race_fixed_workers_on` —
3/5, not 5/5. The package line is worth 60 points, not 100.

**principle.** none. #14 is not implicated — cria never handed back; the suite's milestone floor ended
it.

---

### 9. The general shape, and what a guard should actually be

The kernel, stated without Java in it: **a whole-file rewrite silently dropped the declaration that
makes the file addressable from outside itself.** The file still parses, still compiles, still passes
every syntax and lint check — and nothing outside it can name it any more. Go loses `package x`, PHP
and C# lose `namespace x`, Java and Kotlin lose `package x;`, Rust loses the `pub` or the `mod` line in
its parent, Python loses nothing (its module path is its file path, which is why this class of bug is
invisible to a Python-shaped intuition and why the battery only found it in the Java column).

**Is "this file declared X before and does not now" the right shape? No — not as a refusal, and not
keyed on a declaration.** Three reasons, in order:

1. **It is not general, it only sounds general.** "The declaration that makes a file addressable" is a
   real kernel, but the set of languages where it is a *line in the file* is small, and the check
   degenerates into a per-language table of first-line forms. That table is precisely the shape this
   project has been burned by (`feedback_matchers_by_shape`, flagged twice on 08-06): a rule keyed to
   the word "package" is inert in Rust and Python and meaningless in a `.json`.
2. **As a refusal it violates #2.** Moving a class to a different package, splitting a file, renaming a
   module, deleting a stub — all of them legitimately remove the old declaration, and all of them are
   the *first* attempt at something. cria cannot tell an intentional move from an accidental drop from
   the bytes of the write, because the information is not in the bytes. A guard that blocks the first
   attempt traps the loop.
3. **The false-positive rate is not the problem; the tuning is.** The moment you start weighing "does
   `package` in a `.md` count", "what about a moved file", "what about a new file", you are doing the
   judgment at authoring time on imagined cases (#8, the tell). That is a sign the rule wants to be a
   question — but here it does not even need to be a question, because cria can **ask the world**.

**The shape that is actually general, and cria already computes it.** Do not compare the source text;
compare **what the build produced**. cria runs a build probe on every gate and already diffs the
filesystem before and after it (that diff is `sweep_litter`'s input). The anomaly is:

> a build output appeared at a path that did not have one, while a build output that the repo TRACKS,
> with the same basename, is now absent.

`target/classes/Importer.class` appeared; `target/classes/pipeline/Importer.class` is tracked and gone.
No language knowledge, no keyword, no first-line parsing — git and the filesystem answer it, and it is
identically true for Go (`bin/foo` moved), Rust (`target/debug/foo`), .NET (`bin/Debug/**/Foo.dll`) and
Java. It costs one set comparison on data cria has already gathered, and it fires only when a build
that used to place an artifact somewhere now places it somewhere else — which is a regression by
construction (#2 satisfied).

**And then say it, do not act on it.** The output is one disclosed fact in cria's own voice, with the
two paths in it:

> `⟦ctx:checks⟧ the build now produces target/classes/Importer.class; it previously produced
> target/classes/pipeline/Importer.class, which is no longer built.`

No refusal, no diagnosis, no imperative — the coder decides whether that was intentional. Compare what
actually reached the model at that moment: nothing at all, twice, while cria deleted the file that
would have said it.

This is the same fix as finding 2 approached from the other side, and it is the highest-value item on
this walk: **the sweep already has the evidence; it is being used only to delete.**

**principle.** #2 (regression-only, and additive rather than blocking), #5b (say a true thing cria can
support), #8 (deterministic code gathers the fact; nobody needs to judge it), #20/`feedback_matchers_by_shape`
(the reason not to write the Java-keyed version).

---

### 10. Recent fixes — did they behave?

**Java's cheap compile probe (`mvn -q compile` as the syntax floor) — FIRED, HELPED EARLY, AND WAS THE
LAST WORD AT THE WORST MOMENT.** `probediscovery.build_jvm` adds it with the comment *"Java has no
interpreter parse flag, so the compiler IS its syntax floor; with no cheap compile probe, every Java run
in the six-language battery reported 'SYNTAX FLOOR: did not run'."* It worked: gate 1 surfaced
`cannot find symbol MapRecord` at 2m41 instead of at the end. It is also, unavoidably, the mechanism
that certified the packageless file — `javac` has no complaint about a class in the default package.
Not a defect in the fix; the honest reading is that **"it compiles" is a weaker claim than the gate's
green implies, and the gate has no probe that closes the gap** (finding 4). Keep the probe. The gap is
the entry-point run.

**The Java syntax floor in `validate-before-lower` — DID NOT FIRE, because Java is not in the table.**
`writeproxy._VALIDATE_FN`'s `_EXT_CMD` is `{.rb, .js, .mjs, .cjs, .php, .go}` plus in-process
`.py/.json/.xml/.toml`. The comment 20 lines above it names the hole it closed —
*"for a .rb, .go, .java, .rs or .js file the validate-before-lower refusal branch was UNREACHABLE"* —
and `.java` and `.rs` are still not in the table it closed the hole with. Note carefully: **this would
not have caught this bug** (the packageless file is valid Java) and adding `javac` to that table is
expensive and probably wrong. Recording it only because the code claims a coverage it does not have,
and the next reader will believe the comment.

**Derived probe output cap (`bytes over … lines`) — DID NOT FIRE.** Zero refusals in 54 calls; the
largest gate result was ~5.7 KB and the largest coder result 916 tokens. The composed script carried
the per-command arithmetic (`-le 8500`, `head -c 4250`) and never reached it. Clean run for that
mechanism — and worth noting against the cross-run prevalence table, which credits this cell with 2
refusals from the *previous* cycle's run (`…_1786596642`), not this one.

**Reasoning logged on unfinished streams — HELPED, and finding 6 is only provable because of it.**
Call 0028 ends `[finish: rumination]` with all 800 lines of the degenerate loop captured. Without it
the abort would be an unexplained 159-second gap; with it, the trigger is verifiable as correct. Same
for call 0037's reasoner, where the sentence that convicts the steer — *"the transcript shows an error
during `mvn clean compile`, but it's truncated"* — is reasoning-only and appears in no verdict.

**Completion-judge report framing / the verdict tool — DID NOT FIRE.** Zero `loop.task_complete`, zero
`loop.done_critic`, zero completion probes. The model never claimed to be finished — it was still
mid-diagnosis when the milestone killed it. No evidence either way from this cell.

**Cached-check age note — FIRED IN FORM, DATED NOTHING, TWICE.** Both reasoner prompts (calls 0021 and
0037) carry the instruction:

```
  1. GROUND TRUTH FROM THE REPO'S CHECKS and the fetch record — real output from real runs.
     Trust the words; check the DATE. That section says when it last ran and what has been
     written since.
```

and in both, the `GROUND TRUTH FROM THE REPO'S CHECKS:` section that follows carries **no date and no
age**. Third cell in this cycle with the same observation (see the `shipping-rates-rb` and
`orders-api-py` sections). Here it is not harmless: at call 0037 the checks were seconds old and
*that was the load-bearing fact* — the reasoner decided they were stale history ("failed previously
… implied by the STUCK flag and history") and it had nothing in the prompt to contradict it. An
unconditional `— ran 3 s ago, nothing written since` on that section is one line and would have put
the fact where the instruction says to look.

**Litter sweep (`sweep_litter` / `loop.gate_swept`) — FIRED, AND IT IS THE SECOND-WORST THING IN THIS
RUN.** Finding 2. Its own docstring is careful about the three bounds that make deletion safe
(untracked, inside the workspace, failures skipped) and every one of them held. The bound it does not
have is the one that mattered: it does not ask whether the path it is deleting is *the build's output*
rather than *its own scratch*.

### Verified against the tree, after the walk

Two of the findings above were re-checked directly rather than taken on the walk's word.

**The seed ships compiled classes, and they sit on the path the checker imports from.**
`suite/tasks/feed-pipeline-java/seed/target/classes/pipeline/Importer.class` and
`Importer$Summary.class` are in the repo, and the seed has no `.gitignore`. So every run of this task
starts with a pre-built `pipeline.Importer` already at the exact location `verify.py` does
`import pipeline.Importer` against. A workspace can therefore LOOK correct while the model's own
source is not, and the final workspace here shows the end state of that confusion: an empty
`target/classes/pipeline/` directory beside two default-package classes at `target/classes/`.
Task fault, not cria's. A Java seed should ship source and a `pom.xml`, not build output.

**`sweep_litter` does delete untracked build output — by design.** `probegate.py:956` removes every
path in git's untracked set that appeared across the probe window, bounded to untracked and
in-workspace. A gate that runs `mvn compile` therefore creates class files and then deletes them.
That is correct as "clean up after my own probe" and wrong as "leave the workspace as I found it",
because the artifact it removes is sometimes the only evidence of where the build actually put
things. The call-level cost in this run is recorded above with its call numbers; the mechanism is
confirmed here from the source.

**Not re-verified, carried as a candidate:** the claim that `.java` is missing from
`validate-before-lower`'s extension table while a comment says the hole was closed. Left for the
fix phase to confirm before anything is changed on the strength of it.
