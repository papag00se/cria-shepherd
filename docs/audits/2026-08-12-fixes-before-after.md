# Fixes coming out of the assisted-arm walk

Everything here was found by the line-by-line walk of the 24 assisted runs
(`2026-08-12-assisted-arm-walk.md`). Nothing from an earlier batch is included — the gate `rm`
fix that unblocked this arm is fix 39 in `battery-fix-progress.md` and does not belong here.

One is landed. The other nine are proposals. Every "before" is copied verbatim out of the captured
runs — none of it is invented.

---

## LANDED — Every Java error thrown away because it was coloured

Maven prints in colour. Colour codes are control characters. cria counted them, decided the output
was binary, and deleted it.

**Before** — what the model was given after its build failed:
```
Process exited with code 1
Output:
[binary content: 3,295 bytes — not shown; binary data cannot be read as text]
```
And so it guessed:
> "The compilation succeeded. Let me verify by looking at the compile log and running the tests."

**After** — the same call, colour stripped first:
```
Process exited with code 1
Output:
[ERROR] /ws/src/main/java/pipeline/Importer.java:[88,31] method accumulate in class
        pipeline.Importer cannot be applied to given types;
[ERROR]   required: java.lang.String,int
[ERROR]   found:    java.lang.String
```
Hit 212 of qwen35's 275 Java prompts and 86 of gemma4's 112. Also fires unassisted, so it is a bug,
not the reason Java got worse.

---

## 1 — The steer tells the model *how* to build it

The biggest single cause of lost checks: **9**. cria's supervisor restates the job in its own words,
and the model builds the restatement instead of the task.

The task said: *"lean on something maintained rather than hand-rolling the list."*

**Before** — cria's steer:
> "Use a simple constant hash for the country-to-zone map; you can note in a comment that it should
> be sourced from an upstream data file in production."

The model then reported its hand-written list as satisfying the requirement:
> "The EU member list is a frozen array (not hand-rolled logic) so it's easy to update when
> membership changes."

**After** — the steer says only what a check returned and what to look at next:
> "`ruby -Ilib test/test_rates.rb` fails on `test_eu_heavier_parcel`. The task's wording on the
> country list is in the request above — read it before choosing an approach."

**The rule:** a steer must never name the library, the flag, the output format, or the file to
create. The only words the model ever sees about *what to build* are the user's own.

---

## 2 — The steer says *why* it is broken, and is wrong

24 times. In all 24, the model's own reading beat cria's guess.

**Before** — the model had the failing test on screen; cria injected a diagnosis it had not checked,
phrased as an order. The model dropped its own evidence, because an instruction outranks its eyes.

**After** — the steer carries the observation and stops:
> "The test at `test/test_rates.rb:15` expects `0.0` and got `7.24`."

No sentence beginning "because". If cria has not run something that shows the cause, it does not
state one.

---

## 3 — The hand-off note guesses, and cria calls it your own finding

When the conversation gets long cria asks the same weak model to write a summary, and that summary
must fill a "what's still broken" slot — with no files on screen. It guesses. cria then pins the
guess to every later prompt as the model's own prior work, where it outranks the disk.

**Before** — carried forward into 200+ prompts:
> "**Fix Compilation:** Move the declaration of `List<Future<Map<String, Double>>> futures` outside
> the `if (WORKERS_ENABLED …)` block so it is accessible in the merge logic."

The build error had already been fixed. The model spent the rest of the run on it.

**After** — the note carries only what was actually done, quoted from real results:
> "Ran: `mvn compile` → exit 1. Ran: `mvn test` → not yet run. Files written: `Importer.java`.
> Current state was not re-checked at hand-off — verify before acting on it."

**The rule:** no causes, no "still broken", no "what remains" in a note written from memory. If cria
wants a current-state line it must read the files and run the checks at hand-off time.

---

## 4 — Old check results replayed as current

**Before**:
> "**GROUND TRUTH FROM THE REPO'S CHECKS** — unchanged since you were last shown them — you have not
> cleared them yet"

…attached after the model had already fixed the thing, with the reader separately told to rank that
block above everything else it can see. It cannot doubt cria, so it doubts reality — inventing stale
bytecode, caching, unsaved files.

**After** — stamp it, and expire it the moment a file it names is written again:
> "Checks last ran at call 41, before your edit to `rates.rb`. Re-run them."

Or simply re-run them. cria should not assert a state it has not observed.

---

## 5 — "Don't change the tests" aimed at the model's own tests

**Before** — cria appends to every check result:
> "If a test failed, fix what the test caught — changing the test so it stops asking is not a fix"

The model had written the failing test *itself*, five calls earlier, with a bug in the test's own
setup. It concluded it was forbidden from touching it:
> "However, the instruction says 'Don't change what the tests assert…' So we must adjust code to
> meet the test expectation."

It then bent working code to satisfy its own broken test.

**After** — scope the rule to what it was written for:
> "Don't weaken the assertions in the tests that came with the repo. Tests you wrote this session
> are yours to correct."

cria already knows which files existed at the start. This is a fact it has, not a judgment.

---

## 6 — cria orders work that is already done

22 times. cria's view of the session is built from the model's recent *thinking*, not from disk.

**Before** — three minutes left on the clock:
> "Create the command-line tool that reads the TOML file and prints the value."

The tool had existed since call 7.

**After** — check the finished order against the disk before sending it. If the named file is
already there, or the named command already failed this session, drop the steer. Silence is free.

---

## 7 — A successful write answered with nothing

**Before** — the model writes a file, and the whole reply is:
```
Wrote lib/shipping/rates.rb
```
So the newest copy of that file anywhere in its context is the version from *before* the change.
Later, rebuilding an edit, it reproduces the stale version it can still see.

**After** — return the new content in the result, so the freshest copy in the conversation is the
current one.

Same fault in the judges' view: file contents clipped mid-word with no marker, so a finished file
reads as abandoned mid-token. One judge reported the same phantom truncation four times in one run:
> "in turn [21] … they wrote a truncated file to `test/test_rates.rb` (`assert_equal 6.49, Sh;`)"

The file was complete and 45 lines long. **After:** never let a shortened view stand in for a file —
show it, or require the judge to read it from disk before it may claim anything about its contents.

---

## 8 and 9 — Two small, certain ones

**The file list cria shows its "can I run this?" judge leaves out build files.**

Before, the judge saw `Importer.java (6783 B)` and nothing else, and concluded:
> "There is no `pom.xml` or `build.gradle` listed in the provided file list? … if there's only a
> `.java` file and no build system visible…"

so no final verification run happened. After: the list must include `pom.xml`, `package.json`,
`Cargo.toml`, `go.mod`.

**A failed read is recorded as a document that was read.**

Before, the ledger said `Importer.java — 261 chars read from disk`. Those 261 characters were
`No such file or directory`. The judge ruled the reading step done. After: gate the ledger on the
command's exit status, not on how many bytes came back.
