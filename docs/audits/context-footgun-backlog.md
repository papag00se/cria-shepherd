# Context footgun backlog

Findings from the line-by-line walk of the 2026-08-11..13 suite arm. 40 result slices were read
call by call — no grepping — starting from something visibly wrong in the model's own thinking and
asking what in the context could have caused that thought. 468 wrong turns, 314 of them traced
back to something cria put in the context.

Ranked by damage: broke working code or lost a whole run first, then lost checks, then wasted
wall-clock. Every entry records the A -> B -> C chain, because the fix belongs at A. These came
from subagent readers and are CANDIDATES: date-check each against the code before acting. One
already-fixed Ruby finding ("No rspec tests were found", 331 prompts) was traced end to end before
anyone noticed the captures predated the fix by a day.

## Tier 1 — broke working code or killed runs

### 1. cria asks its own PATH what exists on the machine (one root, three sites)

- **Occurrences:** 16 · **Languages:** 2 (node, rust) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Also filed as:** cria's PATH is not the coder's PATH; cria's own probes run in a different world than the coder
- **Fix belongs at:** A-earliest

**cria asks its own PATH what exists on the machine**

*Chain.* cria's service has a minimal search path -> every probe whose tool lives under the user's home is
dropped as "not installed" -> the gate runs only a syntax check -> cria tells the coder and its
own judges the repo is clean while nothing compiles.

*What happens.* Before composing a check, cria decides whether the tool exists by looking at its own process's
search path. cria runs as a background service with a bare path, while the coder's commands run
through a login shell that finds tools in the user's home directory. So cargo, node, npm, pytest
and pyflakes are invisible to cria and perfectly runnable for the coder. Every check needing them
is dropped, and the near-empty gate is then reported as the repo's checks passing.

*Worst example.* nemotron-elastic/rust 0016-0046. Check block: "the repo's own checks that ran reported no error-
class problems." Coder: "Let's compile mentally: main uses toml crate. It reads file, parses,
navigates dotted key path ... That's fine." The project did not compile for the first 45 calls.

*Realised cost.* 8 wrong turns, nearly all lost checks: two Rust cells where no Rust tool ever ran, a Node cell
where the delivered program was never executed once (14 live checks, every one with no exit code),
plus the steers that leaned on the empty green and sent coders back to files that were already
correct.

*Proposed fix.* Ask the shell that will actually run the probe: one `command -v <prog>` through the same login
shell cria already borrows, once per session, cached. Keep the existing UNSURE-MEANS-KEEP posture
- a miss inside cria's own process is not the certainty that function's docstring claims to
require. Extend the same ownership to the live-run check, which spawns its own process and today
special-cases only python; that also retires the python-alias patch, which was one symptom of this
cause. Do not add a PATH to the service unit: that fixes one box and leaves the wrong question
being asked (#4).

*Would it survive measurement?* Count, per run, probes dropped by the installed-check whose program the login shell does resolve -
a log count plus one `command -v` sweep. Already reproduced deterministically on this box for
cargo, node, npm, pytest and pyflakes, in four cells across four models. This is the surest item
in the set and I would land it first.

**cria's PATH is not the coder's PATH**

*Chain.* service PATH lacks $HOME toolchains -> shutil.which says cargo/node absent -> every language probe
is filtered out of the gate plan and the live-execution probe cannot launch -> the gate reports a
clean type-check on a project that does not compile, or 'NO tests were actually executed' when
tests passed three times -> judge and coder act on the false line

*What happens.* cria runs as a systemd service with the default PATH, so anything installed under the user's home
— cargo, node — is invisible to it. cria decides a check cannot run by looking at its own PATH,
drops every Rust or Node probe, and then reports in its own voice that lint, type-check and syntax
found no problems, or that no tests were executed. The coder and the completion judge both act on
that.

*Worst example.* ternary-bonsai/rust 0028 — cria: "the repo's own checks that ran (lint / type-check / syntax)
found no error-class problems in your current edits"; the judge: "So the code seems to be
working." src/main.rs had two hard compile errors, and the only probe that ran was a Python TOML
parse of Cargo.toml.

*Realised cost.* A Rust project that failed to compile passed every gate of its run and was called clean three
times to the coder and once as GROUND TRUTH to a judge. The Node live-execution probe — the one
mechanism built to catch a green gate over a broken program — produced nothing 5 times out of 5.
Elsewhere it cost three wasted verify rounds re-running tests that had already passed.

*Proposed fix.* Resolve a probe's program in the environment the probe actually runs in — one `bash -lc 'command
-v <prog>'` through the same login shell cria borrows from the harness, cached per session — in
proberun.program_is_installed and in execcheck's runner. The function's own contract is 'False
only when cria is SURE'; cria's service PATH is a fact about cria, not about the machine, so today
it removes probes on a non-certainty (5b). Keep the abstain direction: anything cria cannot
resolve there stays in the plan. Secondary, not instead: the clean-branch message must name only
what actually ran — it may not say 'type-check' when nothing type-checked the changed language.
This is kernel-level, not per-language: it fixes rustup, nvm, pyenv and sdkman at once.

*Would it survive measurement?* Count gate plans across the preserved suite workspaces whose probe set contains no probe in the
workspace's primary language. On this box I expect that to be every Rust and every Node cell —
half the battery. It does not even need the corpus: `env -i PATH=<service default> python3 -c
"shutil.which('cargo')"` returns None today, which is the whole finding. Very likely to hold.

**cria's own probes run in a different world than the coder**

*Chain.* cria.service declares no PATH -> shutil.which('node') is False inside cria -> program_is_installed
drops every node/npm probe and execcheck.run raises FileNotFoundError -> the gate reports 'no
error-class problems' over zero executed tests nine times and the live-run check returns 'not run'
five times -> the satisfaction judge has no evidence and ratifies a green gate

*What happens.* cria runs as a systemd service with the bare default PATH. The coder runs through a login shell
that has nvm on it. So node exists for the coder and does not exist for cria. Every node test
probe is silently dropped from the gate, and the live-execution check reports that the program was
not run because node is missing — while the same prompt shows the coder running node successfully
a dozen times.

*Worst example.* qwen35/node, gates 0164-0234 — gate note: "[GROUND TRUTH] The checks passed but NO tests were
actually executed (0 collected / no test probe ran)." and live check: "the delivered program was
not run, because FileNotFoundError: [Errno 2] No such file or directory: 'node'."

*Realised cost.* The one check built to catch a green gate over a wrong program produced nothing, five times in one
cell. Measured across archives: 51 captured prompts in 43 distinct sessions carry "No such file or
directory: 'node'" from this probe.

*Proposed fix.* Make cria resolve tools in the same environment the coder runs in — resolve through the coder's
login shell (bash -lc 'command -v node') in cria/proberun.py program_is_installed and
cria/execcheck.py run(), keeping the existing unsure-means-keep rule when that lookup itself
fails. This removes a false certainty rather than adding an assist: the docstring promises 'absent
from this machine' and delivers 'absent from cria's PATH', which is principle 5b, cria stating a
false fact. Do NOT paste an Environment=PATH line with a pinned node version into cria.service —
that is the mitigation principle 4 forbids and it rots at the next node upgrade.

*Would it survive measurement?* Already largely measured: 51 prompts, 43 sessions carrying the node FileNotFoundError, and python
has 1 left only because interpreter aliasing already patched that one spelling. The second number
worth counting before touching program_is_installed: how many gate runs dropped every test probe
and still reported clean. If that is zero the fix is cosmetic; from this cell alone it is nine. I
expect both to hold.

### 2. The steer author writes free prose, and every rule about it is also prose

- **Occurrences:** 26 · **Languages:** 6 (go, java, node, python, ruby, rust) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria asks for free prose -> the author fills its gaps with an invented cause, a chosen library,
several actions or a completion claim -> cria ships it as an order and the coder builds exactly
that.

*What happens.* cria asks a small model for a paragraph of instruction and governs it with a list of prohibitions
in the system prompt: do not state a cause you have not verified, do not pick the library or the
file, give exactly one action, never say the task is complete. The models break those rules
constantly, and cria relays the paragraph in the imperative, where it outranks the coder's own
eyes. The tail of a multi-part directive is lost as well, because a steer lives for exactly one
turn.

*Worst example.* nemotron-elastic/ruby, 0068. Author: "the gem is called 'country', version 0.9.3. That gem exists
per earlier search result" — the search file's first line reads "Documentation for countries
(0.9.3)". Next call: "ERROR: Could not find a valid gem 'country' (= 0.9.3) in any repository."

*Realised cost.* The largest bucket. A nonexistent gem and a nonexistent method ordered by name; a seeded test file
destroyed by a dictated whole-file write; a working parallel importer rewritten against a phantom
slowdown; a job declared complete while the migration was untouched; the second half of a two-part
directive silently dropped four times in one run.

*Proposed fix.* Narrow what the author may emit. Ask for two fields — the verbatim evidence line it is citing, and
ONE next action — and let cria compose the sentence (#8: code composes, the reasoner answers a
narrow question). That removes the cause slot, the implementation slot, the completion claim and
the multi-action shape in one change, with no new checker; stacking another validator on a
reasoner is the band-aid (#4). Where a seat still cannot hold the contract, the honest deliverable
is a per-model rate, not more prompt text.

*Would it survive measurement?* Over captured directives count: share with a causal clause ('because', 'the problem is'), share
naming a library/flag/file the task text does not name, share with a second imperative verb, share
claiming completion. Readers already measured 42% multi-action (659/1564) and ~1% completion
claims; this walk adds ~11 implementation picks in 26. Then the harder count — how often the coder
obeyed and it was wrong. I expect the contract change to survive. I expect the completion-claim
and menu-of-options sub-cases NOT to survive as separate guards: both measured near 1%, and each
would be a new assist for a rare leak.

### 3. The judge is shown the wrong half, and never told it was cut

- **Occurrences:** 35 · **Languages:** 5 (java, node, python, ruby, rust) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria bounds a judge's evidence from the wrong end and hides the cut -> the judge reads a fragment
as the whole file or the whole run -> it states a false fact about the workspace in a directive
the coder obeys.

*What happens.* When cria writes up the session for one of its own judges, it keeps the first 400 characters of
each command result and the first 160 of each tool argument, with no sign that anything was
removed, and it squeezes out the line breaks. The first 400 characters of a test run are its
banner and of a file read its opening lines, so the judge gets the part that carries no answer and
reads the cut as the end of the thing. It then tells the coder, in cria's voice, that code is
missing, a file is truncated, or a test is broken. Two nearby surfaces fail the same way: a write-
refusal spends its whole 200-character budget on the file path printed twice, and the completion
judge's action log is trimmed from the front so finished work looks unstarted.

*Worst example.* nemotron-elastic/java 0027-reasoner. Rendered evidence: "-> result: ... Parallel workers are
disabled - turning *". Directive shipped to the coder: "Quote the line: \"Parallel workers are
disabled - turning *\". The task wants that line changed to enable parallel workers." The real
switch was the field WORKERS_ENABLED = false; the verifier reported "import spawned 0 thread(s)".

*Realised cost.* About 35 wrong turns. Two cases of working code made worse (an exception swallowed, a test file
renumbered so it can no longer reach its own server), several checks never earned, three steers
lost outright when the same prompt surface blew the window on a vendored dependency tree, and one
run that ended on the clock with the fix unmade.

*Proposed fix.* At cria/selfcompact.py:219 keep head AND tail inside the same budget and append an explicit cut
marker naming what to re-read; stop collapsing newlines in a tool-result body (the defanging that
function exists for is the copyable envelope, not whitespace). Same shape at
cria/writeproxy.py:372 - bound the checker's message around the error, not from the start of a
line that opens with the workspace path twice. Where the completion judge's action log is elided,
attach the on-disk inventory cria already computes for the run probe. Principle 5's counter-nuance
allows bounding a prompt cria composes; 5b requires the bound be disclosed - an undisclosed clip
asserts that a file ends where cria stopped copying. Also exclude from the workspace walk the
dependency directory cria's own install refusal told the coder to install into. All of this is
existing rendering made honest: no new assist, no new model call.

*Would it survive measurement?* Count, over every judge and steer prompt in the corpus, how often the clip removed the failing
line or the symbol the directive names, and how many directives quote text that exists only as a
clip seam. One reader already counted 140 of 140 pytest results rendered to judges as pure banner
in a single run. I expect this to hold wherever a command puts its verdict last, which is every
runner in the suite. The weakest sub-claim is the newline collapse, which only bit whitespace-
sensitive files (2 wrong turns) and should be counted on its own before it is used to justify
anything.

### 4. The finish check's doubt arrives as an order

- **Occurrences:** 17 · **Languages:** 4 (java, node, python, ruby) · **Models:** 3 (gemma4, nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* a toolless or second-opinion judge writes a free-text reason -> cria wraps it as 'the task is NOT
fully done yet: <reason> ... finish exactly what is called out above' -> the coder deletes passing
code or invents a gap to satisfy the order.

*What happens.* When cria's completion check cannot confirm the job is done, it does not simply keep the coder
working — it repeats whatever sentence the judge wrote, in cria's own voice, as an instruction,
directly under a line saying the tests pass. Those sentences come from passes cria itself
distrusts: a reasoning-off retry that has no tools and cannot look at the workspace, or a second-
opinion veto that answers in free text. Sometimes there is no sentence at all, and the coder is
still told to 'finish exactly what is called out above' when nothing was called out. The coder
believes it and edits working code.

*Worst example.* qwen35/ruby 3/3, 0367 -> 0368. cria: "The zone_for method hardcodes \"EU\" to return \"eu\"
instead of using the countries gem for all two-letter codes as required." Coder: "Let me fix the
code to not hardcode \"EU\" but instead let the gem handle it." A 22/22 suite went to 2 failures —
one per lost check.

*Realised cost.* Broke working code in five runs: 15 self-written tests git-restored, the EU branch deleted twice
(the exact two checks that run lost), a Node dependency re-added that the task said to remove, a
500 turned into a 201 that still fails the integration check. Plus one run that re-judged an
already-green workspace for 266 more calls until the clock killed it.

*Proposed fix.* Stop putting a judge's prose in the coder's mouth. Fail closed on completion (#13) but let the
coder-facing text carry only a gap cria can point at from its own gate findings; when there is
none, send nothing (#3 silence over noise, #5b never state what you cannot ground). Do not re-ask
the confirm brake over a suite the gate reports green. This deletes a channel rather than adding a
filter (#1).

*Would it survive measurement?* Count across all captures: (a) done_incomplete steers whose reason came from a reasoning-off or
confirm pass, (b) how many landed on a workspace the gate reported green, (c) how many were
followed within three coder calls by an edit that turned a passing check red. This walk already
shows 7 of 13 done_incomplete steers in one run carrying the content-free string, and four runs
where green went red right after. I think it holds. What would NOT survive is a claim that these
judges are usually wrong — many not-satisfied verdicts are correct — so the fix must be 'do not
relay prose', never 'distrust the verdict'.

### 5. cria asks its own models about the workspace without showing it the workspace

- **Occurrences:** 16 · **Languages:** 6 (go, java, node, python, ruby, rust) · **Models:** 3 (nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria composes a briefing/steer prompt with no (or partial, or stale) disk facts -> the model
states a file, a state or a cause it cannot see -> cria ships it as ⟦ctx:rollup⟧ /
⟦ctx:continuation⟧ / a steer -> the coder plans against a world that does not exist

*What happens.* cria composes prompts for its own compactor and steer author, tells them to name files and states
precisely, and gives them no on-disk list — or a partial one, or one where the only verbatim copy
of a file is the oldest. They fill the gap: files that exist are reported missing, files that
never existed are reported built, and a cause nobody verified is stated as fact. cria then ships
that sentence in its own voice as the session's memory, and the coder trusts it over the real file
list printed a few lines below.

*Worst example.* qwen35/rust 0032 — briefing: "**Test file created** — `tests/nested_key_lookup.rs` exists"; the
very next prompt's own ground-truth block lists six files, none of them tests/ or README.md, and
that path never existed in the run.

*Realised cost.* A Rust cell struck two of four deliverables off its own to-do list because the briefing said they
existed. A Python cell spent ten calls chasing a NameError the briefing invented. A Go cell
deleted a variable declaration and duplicated a function because the only readable copy of the
file in the steer prompt was 37 calls out of date.

*Proposed fix.* One owner for workspace facts in every prompt cria composes. Pass groundtruth.workspace_inventory
into the compaction prompt on BOTH paths — cria's own self-compact and the harness LOCAL_COMPACT
route in server.py — with the line the step critic already gets ('a path not in this list does not
exist'). Give the steer author that same complete inventory whenever a compaction reset the write
history, not only when the recovered list came back empty (the `if not disk` gate at
loop.py:6234). Make stub_old_write_args keep the newest write per PATH, which is what its own
docstring promises, and apply the same 'exactly one verbatim copy, and it is the newest' rule to
read results in composed judge prompts so no stale copy is the only readable one. Finally, carry
the steer author's two existing bans — no unverified cause, no implementation — into
selfcompact_summary.txt. This is #8 (deterministic code gathers the facts, the model writes the
prose) reusing a value cria already computes for the very next block; it is a file LIST, not file
contents, which was measured and dropped.

*Would it survive measurement?* Three counts, all mechanical over the captures: briefings naming a path absent from the inventory
at that moment; steer prompts whose disk section is a strict subset of the workspace after a
compaction; prompts holding a stale verbatim read of a path that was later written. I expect the
second to be near 100% of post-compaction steers — that is the strongest number here. The first I
have in 5 clear instances across 4 models and expect to hold. The 'no invented cause' prompt
clause is the weakest part: it is a wording change with only 2 instances behind it, and should
ride along, not lead.

### 6. The 400-character clip that cuts the task in half

- **Occurrences:** 8 · **Languages:** 3 (go, node, ruby) · **Models:** 2 (qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* blanket 400-char clip in _defanged_line -> the requirement sentence is cut off the only copy of
the task -> supervisor calls the required work unrequested and picks the forbidden implementation
-> coder complies -> the deliverable the task asked for is destroyed

*What happens.* When cria builds the steer author's prompt it squeezes every transcript line to 400 characters
with no marker. The task message is the only copy of the task in that prompt, and these tasks run
700-900 bytes, so the last requirement is simply gone. The supervisor then rules the coder's work
off-task and dictates the opposite of what the task demanded, and the coder obeys cria's voice
over its own prompt.

*Worst example.* ternary-bonsai/go 0022 and 0046 — the author's only task text ends "Stop using `float64` for mon";
its directive: "Delete `go.mod`'s `require github.com/shopspring/decimal` line and remove its
import from cart.go NOW." The task said "Add a third-party Go decimal module … do not create a
custom decimal type."

*Realised cost.* Two runs broken outright: a Go cell one character from 5/5 deleted its require line and scored
0/5; a Ruby cell shipped a hand-typed EU list the task explicitly forbids. A Node cell chased a
phantom truncated Dockerfile for fifteen calls off the same clip applied to a file body.

*Proposed fix.* Exempt the root task/context message from the clip in cria/selfcompact.py::_defanged_line — or
give steer_diagnose_user.txt its own {{TASK}} section fed from the plan's task text, the way
research_step_user.txt already is — and make the remaining clips disclose themselves ('+N chars
not shown'). #5's counter-nuance permits bounding a composed judge prompt; 5b forbids printing a
cut sentence as 'the task said'. This deletes a silent lie, it adds nothing. Do NOT strengthen the
'do not choose the implementation' prose: it was present, quoted its own measured cost, and was
read on the call that broke the run.

*Would it survive measurement?* Count suite task prompts longer than 400 characters after whitespace collapse (I expect all of
them) and steer/flail prompts that carry the clipped root message (I expect every one). That
number is overwhelming. The narrower number — directives that contradict a clipped-off requirement
— is 4 of 8 here across two models and two languages; even if it were rarer, two of those four
cost the entire run.

### 7. The seats cria writes prompts for are shown a clipped, stale world

- **Occurrences:** 18 · **Languages:** 5 (go, java, python, ruby, rust) · **Models:** 3 (nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria cuts or omits part of the evidence with no marker -> the judge reads the clip as the whole ->
cria delivers that false reading to the coder as an instruction.

*What happens.* cria composes the prompt for its steer author and its finish judges. That prompt cuts every
transcript line at 400 characters and every tool argument at 160, with no mark that anything was
cut; it leaves the check slot empty even when a gate ran one call earlier; it hides file contents
behind a pointer; and on most triggers it omits the coder's thinking and cria's own earlier
instructions. The seat reads the clip as the world and reports it as fact — three different shell
commands look identical, a finished table looks half-written, a required deliverable vanishes from
the task text.

*Worst example.* qwen35/java 1/4, 0019. Three different commands ('... -q 2>&1', '... > /tmp/importer_output.txt
2>&1', '... > data/output.txt 2>&1') render to one identical 164-char line, and the steer says:
"You've run `time mvn exec:java ...` three times with identical behavior".

*Realised cost.* Broke working code: the Go module requirement was clipped off the task, and the coder was ordered
to drop the dependency twice, ending the run with every check failing. Elsewhere a finished README
and a passing suite were both declared broken, and a judge narrated an import edit that never
happened.

*Proposed fix.* Disclose every cut and fill every slot from one owner. Append an explicit '...N chars cut — read
the file' marker wherever cria/selfcompact.py:210/224 shortens, never clip the turn that carries
the task, budget edit_file's two strings separately so both are visible, and build the author's
check block from the same last-gate object the coder's checks block uses, staleness sentence
included. Rule 5's counter-nuance permits bounding a composed prompt only when the bound is
DISCLOSED; today it is silent, which makes it a 5b false fact.

*Would it survive measurement?* Count what fraction of composed author/judge prompts contain a line that hits the 160/400 cap, and
what fraction of those cuts remove the informative part (a redirect, an edit's new_string, a
numbered task item). Then count how many false claims trace to a capped line — I read 8 of these
18 as directly caused. Disclosure costs nothing and cannot mislead, so it clears the bar even at
half my estimate. The 'fill the check slot from the last gate' half needs its own count: how often
a steer is authored while a fresh gate result exists in the session.

### 8. The guards on cria's own directives are keyed on syntax and grounded on the coder's beliefs

- **Occurrences:** 14 · **Languages:** 4 (go, python, ruby, rust) · **Models:** 3 (gemma4, nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* a syntax pattern misses the span, or the wrong haystack passes it -> the directive ships whole ->
the coder writes the invented code, now backed by cria's authority.

*What happens.* cria has a family of checks meant to stop a directive handing the coder invented code. They decide
'is this code?' with patterns written for Python and JavaScript, so they are blind to Rust paths,
`use` lines and `gem install`. They decide 'did cria really see this?' against a haystack that
includes the coder's own private thinking and tool arguments, so a hallucination the coder
invented counts as verified and comes back in cria's voice. When they do fire they sometimes strip
the true half of a sentence and keep the invented half, and a 'this dictates code' verdict is only
logged, never acted on.

*Worst example.* nemotron-elastic/python 3/3, 0197. Coder's private thinking: "return self._send(201, {\"error\":
\"internal server error\"})? ... That seems odd." cria's steer: "replace the line that returns 500
on exception with 201". That line is still on disk at orders/app.py:54.

*Realised cost.* The compile error that failed a whole Rust run (`use toml::Reader;` ordered twice by cria after
the compiler had refuted it); a Python API returning 201 on a failed insert, which is the failed
integration check; four calls writing and removing an invalid `go.sum:` line cria told the coder
to add; a whole turn lost to a false 'your last message contained the file's contents'.

*Proposed fix.* Key the family on provenance and disk, never on syntax. Build the 'did cria see this' haystack
only from tool results, gate output, disk listings and the author's own reads — never from the
coder's arguments or thinking, which the same prompt already labels unverified. Then let any
quoted span absent from that haystack be the trigger for the one DICTATES question, which needs no
per-language list (#9's corollary: the rule that needs an exception list should have been a
question; feedback_matchers_by_shape). And act on the verdict — a DICTATES answer with nothing
strippable drops the steer instead of logging it.

*Would it survive measurement?* Two counts, both answerable offline over the captures. First: directives where the strip removed
nothing but a quoted span appears only inside the coder's reasoning block — pure code, and I
expect it to be common. Second: spans the current pre-filter misses per language; here it was
inert on 100% of the Rust and `gem` cases. The number that could sink it is the false-strip rate
under the narrowed haystack — a steer quoting the coder's own failing line must still survive, so
measure that before landing.

## Tier 2 — lost checks

### 9. The project says how to run and test itself; cria parses that and ignores it

- **Occurrences:** 10 · **Languages:** 2 (java, node) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria parses the project's own run and test commands -> withholds them from the probe that must
name one, and vetoes them when named -> the live-run check never runs the delivered program -> a
green gate stands on nothing but the coder's own word.

*What happens.* cria reads the README's run lines and the manifest's scripts, then hides them from the judge it
asks to name the run command, and shows that judge a file list with the README stripped out as a
data file. The judge guesses - help text, invented handles, or "nothing runnable has been written
yet" on a project with a main function. When a judge does name a real command, a second check
rejects it because a build tool's run target is not a file on disk. Test discovery has the same
hole: a package.json script named test is thrown away when cria does not recognise the command
inside it, and cria then tells the coder its tests cannot be found.

*Worst example.* nemotron-elastic/node. The probe's own reasoning: "we need to guess. However the instruction says
\"Be concrete and short.\" So we can say something like \"handle: 0x123456\"." It answered `node
lookup.js --handle=somehandle --json` while the workspace README on disk says `node lookup.js
goose` - the command the verifier runs.

*Realised cost.* About 10 wrong turns, mostly lost checks. On one Java task the live-run probe was disarmed on 10
of 12 firings; on two Node tasks the one invocation that exposes the shipped bug was never run by
anyone, coder or cria, and the bug shipped.

*Proposed fix.* Treat the project's own declaration as the fact it is. Pass the parsed README and manifest
commands into the exec-intent prompt as a labelled block - cria builds those exact lists one
function later anyway. Let a declared command satisfy the on-disk test for build-tool run targets.
Let a package.json script named test both silence "no tests were found" and become the test probe,
on the strength of its name. And add the entry-point fact - a main function, an `if __name__`, a
bin entry - from the deterministic pass that already walks the workspace, so the judge exercises
judgment instead of inferring runnability from the request's prose (#8). Keep stripping .md from
the file inventory; the commands are the artifact, not the file.

*Would it survive measurement?* Count exec-intent answers naming a command that appears in neither README nor manifest, and count
inconclusive live-execution markers whose reason is a build-tool token. One reader already counted
the second across every log on the box: 95 of 234, 40.6%, spread over cargo, go, rake, npm, mvn
and bundle. Both should hold. The thin sub-claim is "a manifest test script counts by its name"
(one cell) - count how often such a script is discarded as unrecognised before landing that half.

### 10. Old check results are served as the current state

- **Occurrences:** 10 · **Languages:** 3 (go, python, ruby) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria caches a gate's output -> the coder edits the file it names -> the block is replayed to the
steer author as current ground truth with no age -> the author overrides the coder's own passing
run and orders work already done.

*What happens.* The steer author's prompt opens with a block of check output labelled the repo's ground truth and
tells the author to trust it above the file on disk. That block can be several edits old, and
nothing in it says when it ran or what has been written since. The guard that would clear a stale
block only fires when cria can recognise the rendered text as a test failure by phrase, so a
compile error, or a runner whose wording cria does not know, is never cleared. Authors then order
fixes that already landed, or tell the coder that correct code is broken.

*Worst example.* qwen35/go 0034. Steer author: "The repo checks confirm: - `sum.Add` is being called with 2
arguments but expects 1", while the file quoted in the same prompt reads
sum.Add(price.Mul(quantity)). The coder's build one call later: "Build succeeded".

*Realised cost.* About 10 wrong turns. A doubled "require require" line written into go.mod and three no-op edit
cycles to undo it, several coder turns spent disproving cria, and repeated cases of a model
doubting a file it had just read correctly.

*Proposed fix.* Carry the age clause cria already computes into the author's block - the coder-facing repeat
prompt already says "they last ran X, and <file> has been written since" - and drop the flat
"Trust it" when a write landed after the gate. Then decide "superseded" from the gate's own parsed
tally carried on the gate state, not by re-reading the prose cria rendered (#12); that deletes the
phrase list rather than growing it, and covers every runner and every compile failure at once
instead of adding a minitest arm and waiting for the next language (#4). Same commit: the "since
the last gate" anchor searches the coder's history for a marker that never reaches it, so today
the window is the whole session.

*Would it survive measurement?* Count steers whose cited error appears in no check that ran after the last write to the file it
names. Ten here across four models and three languages, and two authors said in their own thinking
that the block looked stale before deferring to it anyway. I expect it to hold. What I would not
assume is the split between the two halves - "no age clause" versus "supersede guard too narrow" -
so count each separately before choosing which lands first.

### 11. The judge answers on the tool channel, because that is the channel cria gave it

- **Occurrences:** 10 · **Languages:** 4 (node, python, ruby, rust) · **Models:** 2 (nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* tools offered in one channel + answer demanded in another, with copyable coder signatures printed
below -> the judge emits <function=satisfied> or <function=exec_command> -> cria discards the
reply -> 'unverified — keep working' or a canned redirect reaches a finished/correct workspace ->
the coder invents a missing deliverable or abandons a good line

*What happens.* cria hands a judge two inspection tools in the XML dialect, prints the coder's full call
signatures at the end of the same prompt, and then demands the verdict as bare JSON in the text
channel. The model answers on the channel it was last using — a call to a function named after the
verdict flag, or the coder's exec_command copied parameter-for-parameter. cria cannot parse
either, so a correct approval or a correct diagnosis is thrown away and the fail-closed path
speaks instead.

*Worst example.* qwen35/ruby 0138 — the reasoning-off retry: '{"satisfied": false, "reason": "All five task
requirements are met: tests pass (21/21) …"}'; the steer cria built from it: "⟦ctx:steer⟧ The
repo's automated checks pass, but the task is NOT fully done yet: All five task requirements are
met …"

*Realised cost.* One Ruby run scored 5/5 at call 0133, was told it was unfinished with no gap named, ran 249 more
calls and ended at 60%. One Rust run lost 5 of 6 correct approvals and paid a full coder round for
each. One Python run threw away four reasoner calls that had found the run's actual root cause.

*Proposed fix.* Two changes where cria composes the judge prompt, both internal to cria. (1) Give the verdict a
tool: put `verdict(satisfied, reason, proposed_fix)` on the judge's own menu beside
list_dir/read_file and read the answer off the structured tool_call — #12, surface from the
authoritative event, never a text match. Policy is untouched: the careful pass still holds the
sole power to approve and unparseable still fails closed (#13). (2) Defang the coder's tool block
to names and one-line prose with no parameter lists — the same lesson selfcompact already applies
to the transcript printed beside it, where the copyable rendering was measured to be imitated 8%
of the time. Do not add a phantom-call repair or a retry: that is a fallback on a fallback (#4).

*Would it survive measurement?* Count judge replies with empty or unparseable content whose reasoning contains a `<function=`
span. cria already emits loop.judge_phantom_tool and massage.reasoning_call_off_menu, so this is a
log count, not a re-read: 5 of 6 careful passes in one cell, hits in 4 cells across 2 models. I
expect it to hold. The number that could sink the verdict-as-tool half is the opposite risk — how
often the judge would call `verdict` before inspecting — and that is answerable by replay before
landing.

### 12. Two size limits disagree, so cria's own checks vanish

- **Occurrences:** 7 · **Languages:** 1 (python) · **Models:** 2 (qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* the gate's output budget is larger than the budget that will accept it -> a 10 KB test run is
discarded whole -> cria's gate parser reads the refusal, records "did not run", and says nothing
-> neither the coder nor any judge ever sees the failing tests.

*What happens.* cria shapes its check script's output to fit 16,384 bytes with a disclosed head-and-tail trim, but
the layer that returns results refuses anything over 9,000 bytes whole. Everything in between is
discarded, so the careful trim never runs. cria then reads its own refusal note where the check
result should be, records that the check did not run, and stays silent - while the coder is told
the output was thrown away and pays to run the suite again.

*Worst example.* ternary-bonsai/python 0034. Tool result: "[10,104 bytes over 182 lines - too much to return, so
nothing is shown. Nothing was truncated: the command ran and its output was discarded, not cut.]"
The steer that followed: "each new `bind()` fails with \"Address already in use.\" The output was
truncated, but that's the root cause."

*Realised cost.* 7 wrong turns with a long tail: twelve consecutive gates produced no check at all across 87 calls
in one run, and in another the entire run's diagnosis was guesswork because no one ever saw a
pytest failure - it ended at the wall with the real bug untouched.

*Proposed fix.* Derive the probe's output cap from content_reduce.INLINE_RESULT_MAX_BYTES minus the harness
framing, so cria can never compose a probe whose output it will then refuse. And let the gate
parse the raw harness result before the model-facing rewrite runs (or exempt a result carrying the
gate marker from the inline bound) - that bound exists to protect the model's window, and cria's
own instrument reading is not model-facing. Secondary removal: drop "| head -50" from the oversize
refusal's advice; a verdict is at the end of the output, and a pipe also replaces the command's
exit code with the filter's, which the same note then calls accurate.

*Would it survive measurement?* Count gate results whose size falls between the two limits, and count gate-result events recording
"did not run" while a probe was actually composed. Both are cheap log counts and were already
reproduced in two cells. The "| head -50" removal is a separate, thinner claim (3 wrong turns, one
cell): count how many commands the refusal induced and how many used the head filter, and land the
cap fix first regardless.

### 13. cria turns the limits of its own checks into claims about the code

- **Occurrences:** 11 · **Languages:** 5 (java, node, python, ruby, rust) · **Models:** 3 (gemma4, nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* a check cannot establish something -> cria writes a sentence that reads as a finding about the
code -> the finish judge rejects a complete workspace and the coder is ordered to fix it.

*What happens.* Two checks cannot establish much, and cria states something anyway. The offline re-run only shows
the tests need no outside network, but cria's sentence says they 'exercise the code against their
own fixtures' — false for any suite that starts a local server. The live-run leg cannot run `cargo
run`, `go run`, `npm start` or `mvn` at all, because it looks for the command as a filename on
disk; instead of staying quiet it tells the finish judge 'the delivered program was not run,
because cargo run is not an entry point on disk'. Judges quote that back as a defect, and the
judge that decides whether anything is runnable answers unstably and invents commands and expected
output.

*Worst example.* qwen35/rust 3/3, 0139 -> 0140. cria: "Live execution inconclusive — the delivered program was not
run, because cargo run is not an entry point on disk." Coder: "The context says tests are not
running and cargo run is not an entry point. Let me check the actual state of the workspace" —
after it had run both successfully.

*Realised cost.* The live-run leg is dead in every build-tool language — cargo, go, npm, maven, gradle, rake — so
cria independently ran no deliverable in those runs. At least three complete workspaces were
declared unfinished on the strength of the false sentence, and one Node run built its whole test
suite around an invented `--handle` flag and a stake address a judge called 'a known valid
handle'.

*Proposed fix.* Two corrections and one silence. In cria/execcheck.py, when program_token resolves through
_PROJECT_RUNNERS the target is the PROJECT, so satisfy the on-disk test from the manifest that
manifest_commands already reads a few lines below (Cargo.toml means `cargo run` exists) — the
head-first fix landed without updating its own caller, #24's corollary. Reword
tests_pass_offline.txt to the observation only: the same tests pass with the outside network
removed, loopback still up. And keep an inconclusive out of the judges' evidence entirely, exactly
as cria already keeps it from the coder (#3, #5b).

*Would it survive measurement?* The corroborate half needs no prevalence at all: replaying it against the final workspaces already
returns False for cargo, go, npm and mvn, so the check is dead by construction, not by rate. The
offline sentence is the same — it is false whenever the service under test is local, which is a
property, not a frequency. Only the exec-intent rewrite needs counting: identical prompts answered
differently (4 samples, 3 false / 1 true in one slice) proves instability but not that a reframed
question is better, so base-rate the new wording over captures before shipping it.

### 14. The checker grades something the prompt never asked for

- **Occurrences:** 7 · **Languages:** 2 (java, node) · **Models:** 3 (gemma4, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* prompt.txt states the deliverable -> model builds exactly that -> verify.py gates on a value or a
spelling the prompt never named -> check scores 0, and on the java task the false premise then
travels through cria's own compaction, satisfaction judge and steer author into an order to break
a passing check

*What happens.* In five of the eight cells the task's own scorer cannot be satisfied by doing what the task's own
prompt says. Three separate defects, one shape: the node task asks for two printed values but the
scorer demands a third that only the seed printed; the java task lists duplicate SKUs as bad rows
to skip while requirement 1 forbids changing row counts and the scorer compares row counts to a
seed that sums them; the same java scorer only counts a located finding when a bare digit sits
right after '.java', so the normal markdown way of writing a line range scores zero. The model
reads the prompt, does what it says, and loses the check.

*Worst example.* qwen35/node, call 0014 — prompt: "Output the holder's address and the number of handles that
holder owns." verify.py:68: "if code != 0 or not ADDR_RE.search(out):" where ADDR_RE is
addr1[0-9a-z]{20,} — a second, different address the prompt never mentions.

*Realised cost.* handles-cli-node capped at 2/4 for two different models (one added console.log flips it to 4/4,
re-run and confirmed). feed-pipeline-java: the speed check was unpassable once duplicates were
dropped, plus roughly forty calls of cria's judges arguing a premise the scorer punishes. gemma4's
java review lost its findings check on formatting alone.

*Proposed fix.* Fix the suite task pairs, not cria. (1) suite/tasks/handles-cli-node — either name the resolved
address in prompt.txt or drop ADDR_RE from the entry-point gate and score stake1 + count (stake1
already proves the live call happened). (2) suite/tasks/feed-pipeline-java/prompt.txt — say
plainly that repeat rows for one SKU are legitimate and stay counted; move duplicate SKUs out of
the bad-row list. (3) suite/tasks/feed-pipeline-java/verify.py:192 — match by shape: a file
reference and a number inside the same finding, tolerating backticks, parentheses, 'Lines' and
ranges. Same class as commit b623d90. Do NOT fix any of this in cria: naming a task's fields to
the model is exactly the task-specific overfit principle 20 forbids.

*Would it survive measurement?* Take every scored check in suite/tasks/*/verify.py and ask whether its pass condition is derivable
from that task's prompt.txt alone. I expect it holds easily — 5 of the 8 cells walked here already
fail it, three tasks are implicated, and b623d90 fixed the identical class on a fourth task last
month. The one number that could shrink it: how many of these actually changed a cell's score
rather than just costing calls. Here it changed the score in at least 3 of the 5.

## Tier 3 — wasted time

### 15. The read-a-source machinery runs on tasks with nothing to read

- **Occurrences:** 12 · **Languages:** 4 (go, node, python, rust) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria asks for an external source while showing only local filenames -> a reading step is pinned
that either closes instantly for nothing or can never close -> calls burn before the first edit
and cria describes real research as empty.

*What happens.* Before coding, cria asks whether an external source must be read first — and prints the workspace
file list underneath the question. Judges answer with a local file, so cria pins 'read cart.go' as
a plan step the coder must clear. The exit that clears a reading step only counts a page as a
source when API routes or response fields were parsed from it, so a crate's documentation never
counts, the step cannot close honestly, and cria tells the coder in every prompt that the page
holding the answer defines nothing. The read ledger also counts files the coder wrote itself.

*Worst example.* nemotron-elastic/rust, 0033. The block titled "WHAT HAS REALLY BEEN READ THIS SESSION" lists
"tests/test_nested_lookup.rs" — written by the coder four calls earlier — and the judge closed the
documentation step with "So we have DONE." No page defining the toml crate API was ever read in
the run.

*Realised cost.* A fifth of one run's budget spent before any code changed; 27 calls held open on a step that could
not close; a Rust run whose documentation step was ruled done on the coder's own README and which
then invented an API that never compiled.

*Proposed fix.* Stop authoring a reading step when the task names no external host. Memory already records this
pinned step as retired once for exactly this cost, so the safe direction is to remove it again,
not reword it (#1; #2's corollary — cria writes no plan step of its own). Where the machinery
remains: count a 2xx page with substantive content as a source, build the read ledger only from
fetches and spills and never from files the session wrote, and drop the route-shaped sentence on
tasks with no API.

*Would it survive measurement?* Count authored research steps whose named source is a path already in the workspace inventory cria
printed in the same prompt, and the calls each cost before the first edit; five of five such steps
here named local files, across four models. Also count research-check verdicts on tasks with no
API: if they are overwhelmingly NOT_DONE-then-cleared-by-a-critic, the step is pure overhead. Both
should hold. What would not survive on its own is widening grounded_sources without the removal —
that keeps the cost and only softens the false sentence.

### 16. cria's story of what happened is not what cria's own record says

- **Occurrences:** 12 · **Languages:** 4 (java, python, ruby, rust) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria alters or mis-narrates the model's own turn -> the model or the judge reasons about an action
that never happened -> it hunts a phantom, re-issues a request it already made, or obeys an order
built on the phantom.

*What happens.* Several places where cria narrates an action get the action wrong. It told a judge it had answered
ON_TRACK when cria had aborted that reply mid-stream. It billed the coder for repeatedly running a
command that was cria's own injected check. It renders a command that never finished as a finished
result. It says a filter ate the output and the exit status is unknown, printed directly beneath
the exit status. And when it silently drops part of what the model asked for - all but the last
tool call in a reasoning turn, or a line number it could not parse - it says nothing at all.

*Worst example.* nemotron-elastic/ruby 0048. cria's prompt: "You were just asked whether a small coding model was
stuck, and you answered with the single word ON_TRACK." The reply it refers to ended "reasoning
stream ABORTED HERE by the rumination guard" with no content at all. The steer that reached the
coder: "the file src/express.js line 5 must contain the new endpoint definition" - in a project
with no src directory and no JavaScript.

*Realised cost.* About 12 wrong turns: a phantom JavaScript file path ordered into a Ruby project, two coder turns
spent re-running cria's own check script, a byte-identical duplicate write, several lost requests
re-issued, three reads returned from the wrong line, and a research step closed as done with
nothing actually read.

*Proposed fix.* Every sentence cria says about an action must come from the event that produced it (#12), and a
refusal to forward must be spoken - the codebase already wrote that rule in one place and skipped
it in the others. Concretely: do not run the ON_TRACK rescue on a stream cria aborted; apply the
existing gate-probe predicate to the repeat-collapse note as well as the failure-squash rule, and
label cria's own probe as cria's in the judge transcript; render a result with no exit sentinel as
"did not finish"; give a byte count an honest label instead of putting it under "response fields
it defines"; cut the causal clause from the filtered-output note down to what the code can
actually compute; name the dropped tool-call spans and either recover or name an unparseable
argument instead of popping it; and at the wire put an assistant turn's narration before the call
it accompanied rather than after that call's result (#24). Every one is a removal or a truth-fix
of an existing string.

*Would it survive measurement?* Each site needs its own count and all are cheap: rescue calls fired on aborted streams; repeat-
notes whose command carries the probe wrapper; transcript entries rendered as results with no exit
code; reasoning turns holding more than one tool-call span; line-number arguments that fail to
parse. The probe-attribution and unfinished-command ones I expect to hold broadly (3 and 2 wrong
turns already, in different models). The multi-span drop (4 wrong turns, 2 cells) and the
narration reorder (2 wrong turns, 1 cell) are thin - count them before touching the massage or
wire paths, since both change execution-adjacent behaviour.

### 17. Word-matching decides when to interrupt

- **Occurrences:** 12 · **Languages:** 3 (node, python, rust) · **Models:** 2 (gemma4, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* cria matches words in the model's prose -> it interrupts a coder that is fine, or discards a
judge's real answer -> the author, obliged to say something, names a defect that does not exist
and the coder obeys it.

*What happens.* cria decides the coder may be stuck by looking for struggle words in its recent thinking, and
decides whether to rescue a judge's lost answer by looking for phrases like "is stuck" in the
judge's thinking. Both are word lists over free prose. On a migration task the task's own
vocabulary arms the detector on half the turns, so it fires on a coder making straight-line
progress; the author then has to produce a directive and invents one. The rescue fails the other
way: a judge that had settled on a real directive phrased it in words the list does not hold, and
the directive was dropped.

*Worst example.* qwen35/node 0030. Trigger text in the prompt: "Its recent private reasoning (below) looks like it
may be circling on a failure, while no check is currently steering it." Directive: "fix the CLI to
output ... \"Invalid handle\" when the handle doesn't contain a dot, as the tests expect." -
promoting the coder's own self-written test to the specification and breaking the documented `node
lookup.js goose` for 18 calls.

*Realised cost.* About 12 wrong turns: 12 calls in one run that produced no output at all (11% of it), three
directives that chose libraries the steer author is explicitly forbidden to choose (including the
dependency the task existed to remove), one self-imposed rule blessed as a requirement that failed
every live test for 18 calls, and six author calls whose settled directive was thrown away.

*Proposed fix.* Replace each word list with the fact it stands in for. The rescue is the free one and is
structural: run it when the reply carries no directive and no tool call while its thinking is non-
empty - and never on a stream cria itself aborted. The fire trigger should key on something cria
owns, such as no bytes changed on disk across N drives or a repeated tool-and-arguments
fingerprint (#8) - but that is a behaviour change and needs its own prevalence work before it
replaces anything. Do not retune the word list: adding and removing words is the exception-list
tell (#4). If a count shows the rescue and the ON_TRACK confirm call almost never yield a
directive, the safe direction is to delete them (#1).

*Would it survive measurement?* Count the arm rate of the struggle filter per coder turn, the share of fires that answer ON_TRACK,
and the share of rescue fires that yield a directive. Measured in three cells already: 53% arm
rate on one task, 6 of 12 fires ON_TRACK in another, 0 rescues from 9 empty replies in a third.
The over-firing claim would hold. What would NOT survive on this evidence is the proposed
replacement trigger - "no bytes changed across N drives" has never been measured as a stuck
signal, so it must be counted before it is built, and until then the only justified change is the
rescue gate and possibly deleting the confirm call.

### 18. A refusal that leaves no way forward

- **Occurrences:** 9 · **Languages:** 6 (go, java, node, python, ruby, rust) · **Models:** 4 (gemma4, nemotron-elastic, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* cria refuses or reduces a tool result -> the message states a bound, not a route or a reason ->
the model cannot act on it and guesses -> repeat searches, junk files in the deliverable, or a
whole line of investigation abandoned

*What happens.* cria says no, or quietly gives less than it promised, and the message names the prohibition or the
outcome but not the route. The model cannot follow the route it was offered — grep a file whose
contents nobody will name, use 'a safer approach' nobody spells out — so it improvises: four more
web searches, a site: search over a local path, three more rm spellings, a rename of node_modules,
a hunt for a Python interpreter that was on PATH the whole time.

*Worst example.* gemma4/ruby 0017 — refusal: "⟦ctx:denied⟧ … is a large reference document … grep the file for what
you need"; coder: "Okay, I'm stuck in a loop with `read_file` on a truncated file." The gem it
then spent four searches finding was the third result in that file.

*Realised cost.* About twelve calls re-finding a fact that was in the first twenty lines of a file cria refused.
Twelve more calls concluding the box had no Python. Two junk search files and a renamed dependency
tree shipped in deliverables. One lost check: an off-target search verdict deleted the on-disk
file whose top three results answered the coder's question.

*Proposed fix.* Every refusal cria authors must state what is true and one route the model can take with what it
has (5b's counter-nuance: a cap is fine when it is DISCLOSED). Upstream, at the places that
compose them: register a search spill's own result titles and URLs as that path's outline at spill
time — cria writes that file and holds them, so 'grep it for what you need' becomes actionable,
exactly as a fetched doc's outline already is; have dirguard's command refusal say that NO part of
the command ran and name the offending stage; have the rm guard name the permitted spelling; say
'find not applied — the whole document fits' when a documented behaviour did not happen; and stop
DELETING content on an off-target search verdict — prepend the recommendation to the real file
instead (#2 forbids deleting correct content, and the code's own comment already says 'labelled
now, not deleted'). No bound is loosened: the 9,000-byte whole-read refusal, the rm guard and
external_dir_permission all stay as they are.

*Would it survive measurement?* suite/replay_logic.py --check spill-outline already counts outline-less spill refusals; the
search-spill share of them decides the outline fix, and writeproxy's own docstring records 26% of
1,931 steers carrying no outline — I expect that to hold. The no-delete change needs no count, it
is a principle-2 violation. The rm, dirguard, view_image and find-disclosure wordings are 1-2
incidents each: land them only if a corpus grep for each refusal string followed within three
calls by another attempt at the same forbidden shape comes back non-trivial. One item I would not
land on this evidence: numbering whole file reads the way ranged reads already are — first count
how often a coder pastes a line straight from a whole read into edit_file's old_string, because
numbering would break every one of those.

### 19. The stuck detectors fire on a coder that is moving

- **Occurrences:** 9 · **Languages:** 5 (go, java, python, ruby, rust) · **Models:** 3 (gemma4, nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* a word list or a repeat count fires on ordinary work -> an author with nothing wrong to report
writes a directive anyway -> the coder is pulled off a correct line of work.

*What happens.* cria decides a coder may be circling by matching struggle words in its private thinking and by
counting repeated actions. It fires on models that restate the task every turn — the task's own
words include 'fail', 'instead' and 'keep' — on a coder re-verifying finished work, on a coder
part-way through a reading step, and once on a coder whose very last action had already broken the
loop. Every false fire hands the seat to an author that is not allowed to answer 'all fine'.

*Worst example.* nemotron-elastic/go, 0010. The evidence ends with the coder's own escape — "Ok, I'm stuck. Let's
search for a decimal library. Use web_search." — and cria ruled "The coder is stuck because they
are just reading files and planning", sending it to write discounts.json. The search results
naming shopspring/decimal were never opened in the remaining 114 calls.

*Realised cost.* Mostly wasted calls, but two hard losses: a Rust run stopped reading the crate documentation and
invented an API that never compiled, and a Go run that had the correct module name in its own
thinking was sent to write a JSON file instead and never recovered the name.

*Proposed fix.* Gate the trigger on facts cria already holds before it spends the call (#11: only a deterministic
anomaly earns a reasoner call). Do not fire when the coder's newest turn is an action whose
fingerprint is not already in the window — a new action is the loop ending. Subtract spans the
coder copied from the pinned task before matching struggle words. Both remove known-false inputs
from an existing trigger; neither adds a heuristic.

*Would it survive measurement?* Count fires per run and, for each: did the window hold a repeated fingerprint, was the newest turn
a new action, and did the matched struggle words appear verbatim in the pinned task. Nine of nine
fires I could check here were on non-loops, and two matched only task-copied words. The gate I
would most want counted against a real stall is 'a new action ends the loop' — measure how often a
genuinely stuck coder still varies its actions, or the fix disarms the detector.

### 20. The runaway guards measure the wrong thing

- **Occurrences:** 5 · **Languages:** 3 (go, java, python) · **Models:** 2 (gemma4, nemotron-elastic)
- **Fix belongs at:** A-earliest

*Chain.* absolute marker count gated at output_reserve/2 -> every long plan is aborted at ~8.2K tokens ->
the produced text is discarded and the model restarts from the task statement -> the flail author,
which only sees reasoning that survived the guard, calls the coder 'circling' and orders the very
write it was aborted composing

*What happens.* The rumination detector counts six second-guessing words, absolute, and checks at half the output
reserve — which with this config is a hard 8,192-token ceiling on thinking. Any long deliberative
pass on a hard task trips it, the abort throws away everything the stream produced, and the retry
tells the model to continue from reasoning cria just erased. The mirror image is worse: both
runaway guards read only the fields cria managed to parse, so a stream it cannot parse at all is
invisible to them and runs until the context is exhausted.

*Worst example.* nemotron-elastic/java 0017 — cria: "⟦RUMINATION GUARD FIRED⟧ 10 second-guessing markers · ~8254
reasoning tokens · aborted mid-stream"; the text it killed: "We'll call write_file with path …
pom.xml … <?xml version=\"1.0\" encoding=\"UTF" — cut mid-write.

*Realised cost.* One Java run landed zero edits — final workspace byte-identical to the seed, 0 of 5 checks — after
eleven aborts, all within a 27-token band at the gate. One Go run had the correct library in hand
('shopspring/decimal') in an aborted turn and never mentioned it again in 34 calls. In the blind
direction, two turns burned 45% of a run's wall clock producing nothing.

*Proposed fix.* Make the marker arm a RATE — markers per thousand reasoning tokens — instead of an absolute count,
in cria/rumination.py. A real spiral is dense and still trips it; a single long plan that says
'actually' twelve times in eight thousand tokens does not. As configured the guard IS the short
hard cap #6 forbids, so this restores the stated design rather than adding anything. And count raw
stream frames alongside the parsed accumulators in chat_watched, so a stream cria cannot parse is
not invisible to its own watcher — cria measuring its own blindness against the authoritative
stream (#12). Do not reword the retry text and do not feed abort history to the steer author: both
are new prose on a seat that is already over-instructed (#1, #3).

*Would it survive measurement?* The abort-token histogram over the battery captures is the whole question: if aborted passes
cluster at the gate rather than at high marker density, the marker arm is decorative and the rate
fix is justified. Here 11 of 11 landed in a 27-token band with marker counts spanning 10 to 27
against a threshold of 6 — the gate did all the work. Recount marker density on aborted versus
completed passes corpus-wide before choosing the rate number. I expect it to hold for thinking-on
models and to be irrelevant for thinking-off ones. The unparseable-stream half is one incident and
survives only if 'many raw frames, zero parsed characters' shows up in other captures.

### 21. The network-off re-run fires when it cannot answer anything

- **Occurrences:** 5 · **Languages:** 2 (java, python) · **Models:** 3 (gemma4, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* the second run is composed unconditionally -> it mutates the workspace or fails for its own
reasons -> its noise is published as the repo's ground truth while its one real product, the
comparison, is discarded -> the coder chases a duplication or a port collision that does not
exist.

*What happens.* After running the tests, the gate runs them again in a network-free namespace to see whether they
secretly needed the network. It runs that second time no matter what the first run did, and no
matter whether the runner can even start in that namespace. When the first run was already red,
the second answers nothing and only changes the workspace again. When the two disagree, cria
publishes the messy result and throws the clean-room one away. For Maven the second run cannot
start at all, and its error reaches the coder looking like a project failure.

*Worst example.* gemma4/python 0061-0077. The coder's own run: "8 passed in 2.08s", exit 0. Its theory after the
next gate reported a higher row count: "The test `test_get_customer_orders` might be running
multiple times in a loop within pytest (e.g., `pytest -n auto` for parallel execution)." The count
rose by exactly four per gate because every gate ran the suite twice.

*Realised cost.* 5 wrong turns with a very long tail: about 25 coder calls hunting a row-duplication mechanism that
did not exist, and in another cell 45 calls of port work that ended with dead attributes in the
shipped service file and a test file that can no longer reach its own server.

*Proposed fix.* Gate the offline leg on the first run's exit code inside the composed script. When both ran, take
the published error class from the isolated run rather than discarding it - that comparison is the
leg's only product and cria already pays for it. Where the runner cannot start in the namespace at
all (Maven's per-user cache), leave the leg out: a probe that cannot pass is not a check and its
output should not reach the coder. All three are removals, or uses of something cria already runs.

*Would it survive measurement?* Count gates where the offline leg ran after a red online run - pure side effect, zero information
- and gates whose published error class does not reproduce in the isolated run. The first is a
plain log count and I expect it to be near-universal. The second is the load-bearing one for the
port case and rests on a single cell. There is an honest counter-argument from one reader: in the
gemma cell the double run is what forced the model to make its tests idempotent, and that
robustness passed a check - so count what the conditional costs, not only what it saves.

### 22. Calls the model made that never happened

- **Occurrences:** 6 · **Languages:** 3 (go, node, python) · **Models:** 2 (nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* model emits N valid calls -> cria forwards one / mangles the type / says nothing about the refusal
-> history shows all N calls with one result -> model theorises a fault that does not exist and
re-issues the work one call at a time

*What happens.* The model emits well-formed tool calls and cria loses them on the way out. Only the last call in a
reasoning-channel run is forwarded; a JSON array written inside an XML parameter tag is passed on
as a string and the harness rejects it; and the message that would tell the model 'your call was
refused, it is not on your menu' exists in only one of the two drivers, so the whole plan-off arm
never speaks it. The model sees silence or a type error, invents a reason — wrong working
directory, bad JSON — and redoes work.

*Worst example.* qwen35/go 0005 and 0050 — coder after two of three reads vanished: "Let me read the cart.go file
to understand the current implementation."; the completion judge after the same collapse: "I need
to read the actual files from the workspace root, not from /tmp." Replaying cria's own parser on
the captured reply returns one call out of three.

*Realised cost.* Two to four wasted calls per instance across five cells, plus the repetition detector firing on
loops cria created and spending reasoner calls on them. In one Python cell an empty turn caused by
a refused off-menu call was scored as a completion claim: two judge calls and a full gate run
against an untouched workspace.

*Proposed fix.* Three completions of mechanisms cria already has, all in one owner. (1)
recover_reasoning_tool_calls should recover the TERMINAL RUN of complete calls, not spans[-1],
reusing the `_skip_between_calls` rule the content channel already applies — this removes a drift
the file's own docstring says cannot happen. (2) Give coerce_args array and object arms under its
own stated total-match rule: json.loads yields exactly the declared type or the string is left
untouched, same discipline as the integer arm the docstring justifies with 148 measured
rejections. (3) Move the LOST_CALL_KEY pop into the shared coder turn so both drivers speak the
nudge that has been in the tree since 2026-08-11 and has fired zero times. No new assist and no
new judgment in any of the three.

*Would it survive measurement?* Three separate counts. The lost-call nudge is already decided: 62 off-menu refusals over two days
against 0 loop.lost_call_offmenu events. The array-cast count is a grep for 'expected a sequence'
in tool responses — 3 cells here, and update_plan is the only array-typed parameter on the menu,
so the ceiling is low but the fix is two lines. The multi-span recovery is the weakest: nobody has
counted how often a reasoning-channel reply carries more than one complete call, and massage would
have to log the span count first. If that comes back rare, land only the other two.

### 23. cria takes the coder's action away instead of telling it something

- **Occurrences:** 4 · **Languages:** 2 (ruby, rust) · **Models:** 2 (nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* the judge is asked to rule on a query without being told what it is for -> cria swaps the tool
arguments in place -> the coder's real question is never asked, and cria's substitution becomes
the record held against it.

*What happens.* When the coder is about to search, a judge rules the query on- or off-target and cria rewrites the
query in place. The judge is shown the task and the query, but not the plan step the coder is on
nor the error it is stuck on, so a documentation search during a 'read the documentation' step and
an error-message search during debugging both read as drift. The transcript then shows the
substituted query as the coder's own words, so the coder never retries, and cria's later
duplicate-search refusals are enforced against a string the coder never typed. Once a steer landed
on top of cria's own 'read that file' pointer and countermanded it.

*Worst example.* nemotron-elastic/rust, 0006. The step in flight was "Read the crates.io TOML crate
documentation..."; the judge reasoned "That seems off-target: they need to write a tool, not
search docs", and cria searched "rust toml dotted key path command line tool" instead. The saved
results hold 20 finished tools and no crate API.

*Realised cost.* One Rust run never obtained the crate's real API and shipped an import that does not exist; one
Ruby run left the file naming the correct gem unread for 27 calls while it committed to the wrong
gem.

*Proposed fix.* Never substitute — surface. cria's own doctrine already says so: 'cria never SUBSTITUTES its own
action for the coder's: surface the fact, steer, and let the coder act' (#2's corollary). If the
guard stays at all, give the judge the two facts cria already holds — the current plan step and
the most recent failing command — so it can tell research from drift, and treat a recommendation
that normalises to the same query as no redirect at all.

*Would it survive measurement?* Count substitutions per run and, for each: was the recommendation a near-duplicate of the original
under the repeat gate's own normaliser, and was the coder later refused against the substituted
string. Four occurrences across three models is thin for rebuilding the judge's prompt, and I
would not ship the 'give it the current blocker' half on this alone. The 'surface, do not
substitute' half needs no prevalence — it is a stated doctrine violation, and one case is enough.

### 24. Triggers keyed to one ecosystem's spelling

- **Occurrences:** 4 · **Languages:** 2 (java, node) · **Models:** 3 (gemma4, qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* matcher/renderer written for python+posix -> no match on another ecosystem -> the code-dictation
guard is skipped, the workspace listing hides the source file, the vendored tree is not pruned ->
a forbidden implementation is delivered unchecked, ~14 calls walk a tree cria had in full, a
dependency's own test suite becomes the top-ranked test target

*What happens.* Several of cria's deterministic triggers and renderers are written against Python and POSIX
shapes, so on Java, Rust and Node they simply never match. The guard that stops a steer from
handing the coder code never asks its question about a Java directive. The post-compaction file
list shows one level down, which for Maven is 'src/ (main)' and hides the source file. A
dependency tree pruned by the name node_modules is invisible once it is renamed.

*Worst example.* ternary-bonsai/java 0040 — steer: "drop the dependency entirely and handle CSV parsing inline in
Importer.java"; task: "Use a third-party Java CSV library … do not write a CSV parser." The
dictation guard never ran, because its command pattern lists pip, pytest, sudo, sed and cat.

*Realised cost.* Two code-dictating directives shipped with no guard call, one of them telling the coder to hand-
roll a CSV parser the task forbids. Roughly fourteen calls per compaction re-deriving a Maven
path. A vendored tree shipped inside a deliverable.

*Proposed fix.* Replace the enumerated lists with shape tests at the same trigger sites, and delete the duplicate
renderer. A bare-command shape (leading bare word plus flag-shaped arguments) and a code-line
shape replace the pip/pytest/sudo/sed/def/import list, with the existing reasoner still deciding
quote-versus-dictation — the deterministic trigger stays deterministic (#8). Delete server.py's
depth-1 `_workspace_listing` and call groundtruth.workspace_inventory(flavor="coder"), which
already walks the whole tree and is already documented as the post-compaction coder list: one
owner, one job. Prune a vendored tree by shape — a directory with no manifest of its own whose
immediate children each carry one — rather than by its name. This is #20 (de-overfit by language)
and #9's matchers-by-shape corollary. Do NOT add Java or Rust keywords to the pattern: that is
exactly the retune #9's tell forbids.

*Would it survive measurement?* For the dictation guard: count delivered steers per run and how many contain a code or command
line by shape but not by the current pattern. Java, Rust, Go and Node are half the battery, so I
expect it to hold; the real risk is the other direction, a shape test firing on ordinary prose,
which is why the reasoner must still decide and why the base-rate of delivered steers per run has
to come first. The one-renderer fix needs no count at all — two functions do one job today. The
vendored-tree prune is a single occurrence that cost nothing; I doubt a count of renamed
dependency trees across the workspaces would justify it, and it should wait.

### 25. A stream that says nothing for twelve minutes and cannot be stopped

- **Occurrences:** 1 · **Languages:** 1 (ruby) · **Models:** 1 (gemma4)
- **Fix belongs at:** a-middle-link

*Chain.* server buffers an unterminated tool call -> zero deltas reach cria -> the rumination watcher and
the degenerate-tail backstop both read an empty string and never fire -> of principle 6's three
backstops only n_ctx is live (timeout is 7200s), and n_ctx by construction burns the entire
remaining window first

*What happens.* The model server generated 44,510 tokens and streamed no content, no reasoning and no tool-call
fragment — llama.cpp buffers an unterminated tool call and only emits on a successful parse.
cria's runaway watchers all read the text stream, which was empty, so none of them ever ran. Only
the context wall ended it, after 43% of the cell's wall clock had gone to nothing.

*Worst example.* gemma4/ruby, call 0009 — upstream.done {"total_ms": 730418.5, "tokens": 44510, "aborted": false}
with no preceding upstream.first_token event, then loop.truncated_dropped.

*Realised cost.* 12m10s of a 30-minute cell producing zero work. Across the last three days of logs: 9 streamed
calls over 10,000 tokens with no first token and no abort, 1h43m of wall time, four of them in
this battery arm.

*Proposed fix.* Put the invariant at the wire (principle 24): one more trigger on the abort path that already
exists — a stream that has parsed zero deltas of any kind past a wall-clock bound is dead,
whatever the server thinks it is doing. It is a byte count and a clock, not judgment, and it
reuses the abort-and-re-prompt that degenerate_tail owns rather than adding an assist class. The
bound must come from the measured slowest legitimate first token across the fleet, not a guess — a
cold 27B already looked dead once (commit cc8e8c7).

*Would it survive measurement?* Two counts. First, dead streams: 9 in 13,344 streamed calls over three days, 0.07%, costing 1h43m.
Second, the false-positive tail: the distribution of legitimate time-to-first-delta per model,
cold and warm. The fix survives only if those two distributions do not overlap. My honest guess is
the dead ones sit above 300s while legitimate cold starts top out near 120s, so it holds — but if
the tails touch, do nothing, because the cost is wall time and not a wrong answer.

### 26. An edit near-miss has no message of its own

- **Occurrences:** 4 · **Languages:** 1 (java) · **Models:** 1 (nemotron-elastic)
- **Fix belongs at:** A-earliest

*Chain.* a near-miss edit produces a result mode with no message body -> the wrong template renders, with a
literal question mark where the line number should be -> the coder is told a true line is absent
and searches for it until the clock runs out.

*What happens.* When the text the model wants to replace almost matches the file, cria produces a distinct near-
miss result - but no message was ever written for that case, so it falls through to the message
for a different case. The coder is told its copy first differs at "LINE ?", is shown a line that
does not contain the text it was looking for, and is told that a line it remembers, which is
really in the file, is not there. Three calls went into hunting text cria had said did not exist,
and the steer author then re-issued the same failing edit word for word.

*Worst example.* nemotron-elastic/java 0031. cria: "your old_string is not an exact match. Your copy first differs
from the file at LINE ?. ... line ? is where your copy is wrong, and a line you remember that is
not shown here is not in the file." Coder: "But we need to find exact line. Let's view file
again."

*Realised cost.* 4 wrong turns: the last six calls of the run spent re-reading one file, a steer spent commanding a
repeat of the edit cria had just rejected, and nothing written before the wall.

*Proposed fix.* Give the near-miss its own message: say there is no exact match, quote the nearest line, and claim
nothing about lines that are not shown. Delete the fallback that prints "?" when there is no line
number - a message that cannot name a line must not print one (#4, #5b). Both are edits to strings
and control flow that already exist; the distinction is already drawn one module upstream.

*Would it survive measurement?* Count near-miss edit failures across the corpus and how many are followed by a re-read rather than
a corrected edit. This is 4 wrong turns in one cell, one model, one language - thin, and I will
not claim prevalence. But the defect is structural rather than statistical: a result mode with no
message renders another mode's words plus a literal "?", which is wrong on its first occurrence. I
would land the deleted "?" fallback on that basis alone and hold the new wording until a count
exists.

### 27. cria pays for reasoning and then bins it

- **Occurrences:** 3 · **Languages:** 3 (java, ruby, rust) · **Models:** 2 (qwen35, ternary-bonsai)
- **Fix belongs at:** A-earliest

*Chain.* a reply is cut or unparseable -> cria discards the reasoning or anchors it to the wrong sentence
-> the coder gets nothing, or gets a sentence the judge never meant as its ruling.

*What happens.* When the steer author's reply is cut off at the token limit, cria drops the whole call — including
the thinking it has already paid for, whose first paragraph twice held the correct fix. And when a
recovery pass does pull the ruling out of a judge's thinking, cria tries to re-anchor that text
back into the original thinking and silently falls back to the opening sentences when the anchor
is not found, shipping the judge's throat-clearing as the reason the task is not done.

*Worst example.* ternary-bonsai/ruby, 0085. Recovered: "the code was broken because it used the wrong API
(`EuCountries.eu_members` instead of `ISO3166.EUCountry.codes.include?(code)`)". Delivered: "Let
me check if there's a way to see what happened after my write_file call."

*Realised cost.* One Rust run's exact fix was thrown away at the moment it existed ('the tests are still using
.parse() which is incorrect'); one Ruby run's only correct naming of the gem API was replaced by
the judge's own meta-commentary and the run closed out wrong.

*Proposed fix.* Delete the silent fallback at cria/loop.py:1433 — when the anchor is not found, use the recovered
sentence itself, the only text in that path known to be about the ruling (#4: a fallback that
fires exactly when the recovery worked is the band-aid). On a length-cut author reply, run the
same recovery the clean path runs, reading the HEAD of the trace rather than the tail, because a
cut trace never reached its end. Both are the operator's standing rule: read the reasoning first —
'found it then lost it' is not 'never found it'.

*Would it survive measurement?* Count `loop.steer_truncated` and anchor misses across the battery. Truncation fired 1 in 47 and 1
in 187 reasoner calls in the two runs I have — too thin to justify a recovery pass on cut replies
yet, so that half should wait for the count. The anchor fallback is different and needs no bar: it
is a single branch that fires precisely when the recovery succeeded, it is a deletion, and it is
the safe direction (#1). The anchor case is one occurrence here; I would ship the deletion anyway
because the alternative it replaces is cria stating a reason the judge never gave.

### 28. Search results are filed away where the model never looks

- **Occurrences:** 2 · **Languages:** 1 (go) · **Models:** 1 (nemotron-elastic)
- **Fix belongs at:** A-earliest

*Chain.* every search is spilled to disk regardless of size -> the model gets a pointer instead of an
answer -> it never opens the file -> it invents a dependency and the whole task fails.

*What happens.* A web search never comes back with anything. cria writes the results to a file and hands the model
a pointer, whatever the size - here 5,890 bytes, comfortably under the limit cria already uses to
decide a result is too big to show inline. The model searched twice for a decimal library, was
told to go read a file, never did, and invented a module path that does not exist. Nothing in that
project ever built.

*Worst example.* nemotron-elastic/go. Model: "Ok, I'm stuck. Let's search for a decimal library. Use web_search."
The spill file's fourth line: "decimal package - github.com/shopspring/decimal - Go Packages". The
shipped go.mod: "require github.com/elliott/decimal v1.6.0".

*Realised cost.* 2 wrong turns that cost the entire cell: four of five verifier checks scored zero because the
project never compiled against a module that does not exist.

*Proposed fix.* Make search obey the size rule cria already owns for command output: show the titles and links
when they fit under the existing inline limit, and spill only when they do not. That is deleting a
special case rather than adding an assist. The code's own reason for spilling names the
descriptions as noise - and the titles and links are exactly the fact a model needs when it is
choosing a dependency.

*Would it survive measurement?* Count spill files written versus spill files later read, across the whole corpus. Zero reads in
124 calls in this cell. If the read rate is low everywhere, the spill buys nothing and costs the
answer; if models usually do read it, this is one weak model's habit in one cell and the special
case should stay exactly as it is. That single count decides it, and I would not change the code
before running it.

## Tier 4 — one-offs, recorded but not scheduled

### 29. The seed teaches a setting that does nothing

- **Occurrences:** 1 · **Languages:** 1 (python) · **Models:** 1 (nemotron-elastic)
- **Fix belongs at:** A-earliest

*Chain.* seed serve() sets db.DB_PATH as if it took effect -> model copies the idiom into its test setup ->
requests and assertions run against two different databases -> integration_tests fails with
"assert 'id' in {'error': 'internal server error'}"

*What happens.* The orders-api seed's serve() assigns db.DB_PATH and then calls functions whose path default was
already bound at import, so the assignment is dead. A model copied that idiom into its own test:
fixtures went to a temp database, the server it started read the module default. Its integration
test then failed on an empty database, which is the literal failure the scored check dies on.

*Worst example.* nemotron-elastic/python, call 0041 — seed: "def serve(port=8080, path=db.DB_PATH): db.DB_PATH =
path"; model's test: "db.DB_PATH = db_path / db.init(db_path)" then starts the handler.

*Realised cost.* One check lost in one cell. The scored probes never hit it because the verifier installs its
database at ws/orders.db, so the dead line only bites the model's own tests.

*Proposed fix.* suite/tasks/orders-api-py/seed/orders/app.py: either bind the path at call time so the assignment
means something, or delete it so the seed stops teaching a move that cannot work. It is the task
owner's call, and it does not change what the task is about (parameterised queries and API
behaviour). Nothing to change in cria.

*Would it survive measurement?* Count how many of the four models that ran orders-api-py copied the db.DB_PATH assignment into
their own tests. One is not enough to justify touching a deliberately flawed seed. My guess: it
does not survive — I would expect one or two, and if it is one, leave the seed alone and let this
stand as a note.

### 30. A fixed port on a shared box

- **Occurrences:** 1 · **Languages:** 1 (python) · **Models:** 1 (gemma4)
- **Fix belongs at:** nothing-to-fix

*Chain.* model hard-codes 8081 instead of asking the OS for a free port -> the suite runs the workspace
directly on the shared box -> an unrelated service answers -> ~20 calls of writes, kills and
probes until cria's steer names the collision

*What happens.* The coder pinned its test server to port 8081 while an unrelated uvicorn owned that port on the
operator's machine, so its own routes answered with a body it never wrote. It spent about twenty
calls unable to explain that. cria's reasoner named the real cause from the coder's own port
listing and unstuck it.

*Worst example.* gemma4/python, calls 0022-0043 — coder: "If I wrote {\"error\": \"no such route\"}, why did it
show \"detail\":\"Not Found\"?"; ss output: uvicorn pid 3196532 on 127.0.0.1:8081.

*Realised cost.* Roughly 25 wasted calls, recovered inside the run. No check lost.

*Proposed fix.* Nothing. cria recovered on its own, and isolating each workspace in its own network namespace
would hide a resilience problem this arm exists to surface (principle 19). Worth telling the suite
owner that every model running orders-api-py against a box with uvicorn on 8080/8081 hits this, so
that column is partly measuring port luck.

*Would it survive measurement?* Count how many orders-api-py runs collided with a listener the operator had up, and whether the
collided runs score lower than the clean ones. If all four models collided the scores are still
comparable to each other; if only some did, the task's cross-model numbers are noisy. Either way
it changes the suite's reading of a column, not cria's code.

### 31. The steer author picked the implementation

- **Occurrences:** 1 · **Languages:** 1 (java) · **Models:** 1 (qwen35)
- **Fix belongs at:** nothing-to-fix

*Chain.* steer_diagnose.txt forbids choosing the implementation -> the author names a field and its
modifiers anyway -> the coder adopts it as a task item

*What happens.* cria's steer author is told never to choose the implementation — not the library, not the data
structure, not a flag. In one steer it named a specific flag and its access modifiers alongside
its actual direction. The coder took the whole thing as the plan.

*Worst example.* qwen35/java, call 0209 — steer: "Ensure the `WORKERS_ENABLED` flag is not `public static final` if
it needs runtime control." against steer_diagnose.txt: "Do not choose the IMPLEMENTATION. Which
library to use, which data structure, which flag … those belong to the TASK or to the coder, never
to you."

*Realised cost.* Small on its own — the damaging half of that same steer came from the task prompt defect, not from
this. Cost here is one wasted item in the coder's plan.

*Proposed fix.* Nothing yet. The rule already exists in the prompt; adding another sentence to restate it is noise
on a prompt that already carries it (principles 1 and 3), and one violation is not evidence the
wording is weak.

*Would it survive measurement?* Count authored steers across the captured runs that name a concrete field, flag, type or library.
Below about three, do nothing. I expect it comes in low — the reasoner obeyed this rule in every
other steer in these eight cells — so my honest guess is it does not survive and should stay
unfixed.

## Fixed

### 32. cria classifies the harness's summarize handshake, then throws the answer away

- **Occurrences:** 6 · **Languages:** 1 (java) · **Models:** 1 (qwen35)
- **Fix belongs at:** A-earliest

*Chain.* classify runs before the compaction test in server.py -> the model ruminates to the cap and
returns empty -> about a quarter of the run's wall clock is spent producing nothing, on a run
killed by the clock.

*What happens.* Every incoming turn is classified before it is routed. The harness's compaction message is routed
to the summarizer by a plain string test regardless, so the classification is discarded — but it
is still requested first. A small model handed a four-way taxonomy for a message that is not a
request runs to the token limit and returns nothing at all.

*Worst example.* qwen35/java 4/4, 0378. The turn is "<<<LOCAL_COMPACT>>> Summarize the thread for continuation."
and the reply is empty at the cap; the reasoning reads "Wait, I'll check if `task_type` should be
`question`. ... Wait, I'll check if `reason` should be \"summarizing thread\"."

*Realised cost.* Six calls, 16,384 tokens each, roughly 19.5 minutes of a 76-minute run that ended budget-killed.

*Proposed fix.* Move the existing `_is_compaction_request` test ahead of `_classify` in both produce paths in
cria/server.py and skip classification on those turns. It removes a model call using a
deterministic string test cria already owns (#8) and closes a live hazard as well: a compaction
turn that happened to classify as coding would engage the coder loop on a summarize request.

*Would it survive measurement?* This one needs almost no prevalence argument: 6 of 6 compaction turns in the run returned empty at
the cap, and the discard is visible in the code path (server.py:754 routes compaction before the
classification is read). The only number worth adding is how many compaction turns a long run has
— it grows with run length, which strengthens the case. It is a removal of a model call, so the
downside risk is zero.

### 33. Model calls whose answers nothing reads

- **Occurrences:** 4 · **Languages:** 3 (go, java, rust) · **Models:** 3 (gemma4, nemotron-elastic, qwen35)
- **Fix belongs at:** A-earliest

*Chain.* cria makes (or invites) a call whose result is discarded by construction -> the model spends
minutes producing an answer -> nothing downstream reads it -> in the update_plan case the coder's
own transcript then contradicts cria's step header and it spends a turn arbitrating

*What happens.* cria pays for calls that cannot affect anything. It classifies the harness's compaction handshake
before reaching the branch that ignores the classification, and the classifier — asked a question
its three labels cannot answer — oscillates until it hits the token ceiling and returns nothing. A
one-word guard runs with thinking on and is observe-only anyway. And cria leaves update_plan on
the coder's menu while cria itself owns the step pointer, so the harness acknowledges a plan
advance cria ignores.

*Worst example.* qwen35/java 0238 — classifier reasoning: "Is it a 'question'? It's asking for a summary. Is it a
'task'? …"; its response: finish_reason "length", completion_tokens 16384, content "" — 195
seconds on a 209-token prompt, six times in one run.

*Realised cost.* 19.5 minutes of a 76-minute budget-killed run on six classifier calls, every one hitting the
16,384-token ceiling with empty output. 51 seconds of a 420-second run on a one-word verdict
recorded as observe-only. One dead 37 KB research call. One coder turn with no tool call at all,
spent reconciling two versions of which step it was on.

*Proposed fix.* Stop making them — all four are removals (#1's safe direction). Short-circuit _classify when
_is_compaction_request is true, in both the completion and stream producers: the compaction branch
already ignores the value and _engages_loop returns True before reading it, so nothing downstream
changes. Run the one-word DICTATES guard with thinking off the way satisfaction-confirm already
does, or drop the call entirely while its verdict is observe-only on the drop. Put the ask LAST in
research_step_user.txt, the same ordering rule selfcompact already documents ('a model obeys the
last instruction it reads'). Drop update_plan from the curated coder menu while cria drives the
plan.

*Would it survive measurement?* The classifier count is already decided in-run (6 of 6 compaction turns, all empty at the ceiling)
and is verifiable corpus-wide by counting classifier calls on turns that routed to the compactor —
I expect it to hold in every run that compacts, which is most long ones. The update_plan removal
needs a count of update_plan calls followed by an unchanged cria step index across the battery;
one occurrence today, so it should not land alone. The thinking-off guard and the prompt
reordering each have one measurement behind them and are latency-only; they are cheap but should
be reported as such, not as wins.

## Not cria's — traced to the model itself

153 wrong turns. No change proposed for nine of the ten shapes; the tenth is a counter, not an
assist. Recorded so the next walk does not re-litigate them.

### Went against what its own screen said

- **Occurrences:** 33

*What happens.* The answer was already in the prompt — an error naming its own cause, a spec line, a refusal, a
requirement, a file the model had just read — and the model asserted the opposite. The commonest
shape is a self-describing error read as a fault in the library, the server, the network or the
environment. This is the largest single kind, and in every one of them cria had delivered the
right bytes whole and unaltered. Cause likely missed: no — a few sit next to a steer that later
echoed the belief, but those were filed separately and the model was first.

*Realised cost.* the biggest bucket. Three runs lost their central check to a single instance each: the pathless
HTTP request line across all three qwen35/python slices, the holders URL built from a handle in
nemotron/node, and a nonexistent Go module explained away as an offline box.

*Verdict.* Nothing, and specifically do not add a second cria voice over a clean tool result — #3 (silence
over noise) and #5b (cria may SELECT a checker's real lines, never SUBSTITUTE its own). This is
the ceiling showing: a 9-27B reads an error that names its own cause and prefers a familiar story.
A harness can put the truth in front of it and can make it run things; it cannot make it believe
the output. The only lever that touches this class is cria running the delivered program itself
(#10) and reporting the exit code — which already exists.

### The supervisor seats fail the way the coder does

- **Occurrences:** 25

*What happens.* cria's judges, steer authors and completion gates are the same small model in a different chair,
and they inherit the same blind spots. They approved a deliverable that broke a requirement quoted
in their own prompt, called a malformed HTTP request valid, reasoned their way to "it is stuck"
and then emitted the word that means fine, cited stale failures as current, and often returned
nothing parseable at all. One in six of all these wrong turns is a supervisor seat rather than the
coder. Cause likely missed: here more than anywhere — these prompts are cria's own words, so
prompt shape is a live suspect even where the needed facts were present.

*Realised cost.* five lost checks; ~18 of 105 calls in one java slice on gate bookkeeping; 17 calls and ten minutes
in a gemma4/python slice because a judge answered in prose instead of JSON, with zero workspace
change in those seventeen calls.

*Verdict.* Nothing to add and nothing to remove. Every recovery here is a documented fail-closed path and
cutting it fails open (#13) — this corpus contains no false completion, which is what that cost
buys. What the group is actually worth is a bound, not a build: a same-model judge buys no
independence on the class of bug the coder is blind to (qwen35/python 0164 reproduced the coder's
exact misreading). That is an argument about which model sits in the judge seat, not about a new
assist.

### Its own broken probe became the evidence

- **Occurrences:** 17

*What happens.* The model built a scratch script, a timing command, a filter or a jar, got a wrong number out of
it, and then trusted that number over the code. Timings with the build tool inside the timed
region, a jar packaged from the seed and never rebuilt, a hand-typed Content-Length four bytes too
long, a grep that stripped every error line, its own mislabelled log line. Whole runs then went to
a requirement already met or a bug that lived only in the probe. Cause likely missed: no, with one
exception — one conflation was between two cria-spilled files whose names are domain-led.

*Realised cost.* the largest wasted-call bucket. qwen35/java 4/4 spent about 90 of 103 calls chasing a 4x speed bar
it was already passing by 14x; qwen35/java 3/4 spent about 46 calls hunting a method that existed
only in a stale jar.

*Verdict.* Nothing — and specifically not a timing probe or a build-freshness check. Task-specific probes are
already rejected (#20 and feedback_no_footgunning), and cria may not author the coder's commands
(#2 corollary). The general mechanism that covers this already exists: cria's own read-only probes
(#10) and the gate re-running the tests, which is what told the truth in every one of these runs
while the model believed its own number.

### Rebuilt from memory what it could have copied

- **Occurrences:** 16

*What happens.* Rather than editing in place or copying the exact bytes it already had, the model regenerated
content from memory — whole-file rewrites and hand-typed edit anchors. Every regeneration loses
something: an import, a country code, a closing brace, a working output line, a path segment. Six
of these destroyed code that worked; the rest were edits that could not match. Cause likely
missed: no for the model half, but the group exposed one real cria defect in the recovery message.

*Realised cost.* six cases of broke-working-code, the rest wasted calls. ternary-bonsai/rust threw away a 3.0/4.0
state and finished at 0. ternary-bonsai/node deleted the one line the checker was looking for.
ternary-bonsai/ruby lost Croatia out of a hand-retyped EU list and failed the one check that tests
it.

*Verdict.* The mechanism is the model: the coder prompt already says "Do NOT rewrite a whole file to make a
one-line change" and edit-recovery already prints the real text. But there is one true cria defect
at a middle link, and it is a #5b violation: when the divergence line is unknown,
cria/editrecovery.py:136 renders `line=... or "?"` into the anchor body, so the model is told
"your copy first differs from the file at LINE ?" and "line ? is where your copy is wrong" — cria
asserting a line number it does not have, twice, in its own voice. Fix upstream in
prompts/editfail_reports.txt: give the unknown-line case its own body that shows the anchor and
drops both line sentences (the no_anchor family already models the wording). It removes a false
fact; it does not cure the mechanism.

### Guessed a name instead of looking it up

- **Occurrences:** 13

*What happens.* The model needed an exact name — a library version, a method, a module, a directive, a tool — and
produced one from memory instead of reading it. The invented name failed, and the recovery was
usually another guess from the same memory. A lookup was available every time, and in three cases
the correct listing was already on screen in the same window. Cause likely missed: no.

*Realised cost.* two runs lost their entire build to it — ternary-bonsai/java on commons-csv 1.3.0 then 1.4.0 with
the real directory listing in the window, and ternary-bonsai/go on decimal v1.35.1 when `go get
...@latest` resolved it first try in 0.66s. Elsewhere it is wasted calls in every language.

*Verdict.* Nothing. The coder system prompt already carries "DO NOT GUESS URLs, FORMATS, OR OBJECT STRUCTURE"
and "investigate first", and a registry-existence probe has already been measured and dropped (4
hits in 239 instructions, none of them the failure). Adding a name-checker would be a task-
specific probe (#20) stacked on an instruction that is already correct (#1, #3).

### Said it had done work it had only thought about

- **Occurrences:** 13

*What happens.* The model composed code, a summary or a verification in its head and then reported it as done.
Whole implementations written into the thinking channel followed by task_complete; summaries
listing files that were never written; a "verified locally" quoting a command that was never run;
a compaction briefing recording test results that had never occurred. Cause likely missed: no —
the prompts forbid all of it in the exact words that would have prevented it.

*Realised cost.* mostly wasted calls: the fail-closed completion gate refused every false completion in this
corpus. Where it cost more, it was a summary carrying a false state into later prompts.

*Verdict.* Nothing. This is precisely what #13 exists for and it held every time. The compaction prompt
already states the both-directions rule verbatim ("the build failed on X before the edit to Y; not
re-run since"), so restating it is noise (#3). One wording tidy, not a mechanism: the heading "THE
CODER'S REAL ACTIONS AND THEIR OUTPUTS SO FAR (ground truth)" sits directly above a model-written
summary that cria's next paragraph calls unverified — two cria sentences contradicting each other
in one prompt.

### Ordinary coding mistakes

- **Occurrences:** 12

*What happens.* Plain bugs of the kind this model size predicts: a class attribute used inside an instance method,
`const fetch = fetch`, rounding to the nearest hundred instead of the nearest cent, a two-
character test that swallows a two-letter zone name, a test asserting a key its own route never
returns, a blocking helper called synchronously. Nothing in the context caused them and nothing in
the context could have stopped them without cria writing the code. Cause likely missed: no. This
is the hard floor.

*Realised cost.* five lost checks. One run finished one character from a perfect score.

*Verdict.* Nothing, and this is the honest ceiling. cria may not author the implementation (#2 corollary —
the steer author is explicitly barred from writing the replacement line, and a steer that did so
is on the already-fixed list). The only harness lever is making the failure visible sooner, which
is the gate, and the gate reported every one of these truthfully.

### The turn produced nothing

- **Occurrences:** 9

*What happens.* The model ended a turn with no message and no tool call: the call was written inside its private
thinking in its own dialect, or the arguments were missing a required key, or it simply stopped
after announcing what it would do next. One turn generated 41,000 tokens of an unterminated tool
call over twelve and a half minutes while every cria watcher saw zero characters. Cause likely
missed: yes, partly — cria's blindness during that turn is a real co-cause and is where the only
fix in this whole set lives.

*Realised cost.* the single worst cost in the corpus: gemma4/node lost an entire run — 80% of the wall clock in one
turn, then a milestone kill on an untouched seed, all four checks failing because no file was ever
written.

*Verdict.* One real upstream change, and it is measurement rather than an assist. All three of cria's runaway
watchers are fed from parsed content, reasoning and tool-argument deltas
(cria/upstream.py:498-501, :519); while llama.cpp holds an open tool call none of those three
fields carries a character, so all three are blind and the ticker prints rate-less beats for
twelve minutes. Count raw SSE frames in Upstream.chat_watched and emit the count on upstream.done.
If frames arrive, the existing rumination and degenerate-tail gates can run off a real decode
count and guard_truncation's "write it in smaller pieces" can fire while budget remains; if they
do not, say so once in the log instead of leaving a hole. Second, move the loop.truncated emit
below the `path is None` break (cria/loop.py:7451/7454) so cria stops telling the operator it
retried when it did not — that line is a #5b false fact today. Do NOT add a promoter that executes
a tool call found in the reasoning channel: that runs what the model wrote in a scratchpad (#1).

### Circling

- **Occurrences:** 8

*What happens.* The model re-ran a settled command, re-derived a settled paragraph, or restated a hypothesis it
had already disproved — in one case after six independent checks had shown the file was clean. In
one slice, nine reasoning passes degenerated into the same paragraph repeated a dozen or more
times until the guard cut the stream. Cause likely missed: no. Every instance here was caught by
an existing cria guard.

*Realised cost.* wasted calls only — no check was lost to circling that a guard did not interrupt.

*Verdict.* Nothing. The guards fired on genuine degeneration every time, their re-prompt wording is correct,
and on the positive side the flail steer is what moved a fix out of a scratch file and into the
deliverable in qwen35/rust. One thing to hold in view rather than fix: at nemotron-elastic/ruby
0056 the aborted turn had already composed the exact README table the check wanted, and it was
never written. The abort was still right — preserving aborted reasoning re-injects the loop the
guard exists to kill.

### Found the answer and let go of it

- **Occurrences:** 6

*What happens.* The model reached the correct diagnosis in plain words and then, in the same turn or the next one,
replaced it with something else. Twice it named the right library and wrote the wrong one; twice
it worked out the right signature or fix in reasoning and emitted a different one; twice it
declared the task complete on the strength of a diagnosis it never wrote to disk. Cause likely
missed: no — nothing new entered the prompt between the right answer and the wrong one.

*Realised cost.* two lost checks and two runs that ended within one call of the fix — in the qwen35/ruby 3/3 case
the wall clock, not the model, is what ended it.

*Verdict.* Nothing to build. This is the shape the project already treats as the crux — "found it then lost
it" needs a different reading from "never found it" (#8's lesson, feedback_read_the_reasoning). It
changes how a run is scored and how a model's ceiling is judged, not what gets added to cria.

