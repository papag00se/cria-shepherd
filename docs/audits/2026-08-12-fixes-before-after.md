# Fixes from the assisted-arm walk — before and after

Everything here was found by the line-by-line walk of the 24 assisted runs
(`2026-08-12-assisted-arm-walk.md`). Nothing from an earlier batch is included.

Each entry: what happens **now**, and what will happen **after**. Every "now" is copied out of the
captured runs, and each was re-opened in the captures before being written down here — the first
draft of this document mis-titled its own first finding by trusting a summary instead.

One is landed. Eight are not.

---

## 1. A coloured build log read as binary — LANDED (`fdd14ea`)

**Now.** The model runs `mvn compile -q`. Maven prints its errors in colour. Colour codes are
control characters, cria counts them, decides the output is a binary blob, and replaces it:

```
Process exited with code 1
Output:
[binary content: 3,295 bytes — not shown; binary data cannot be read as text]
```

The model has an exit code and nothing else, so it guesses — and guesses wrong:
> "The compilation succeeded. Let me verify by looking at the compile log and running the tests."

212 of qwen35's 275 Java prompts. 86 of gemma4's 112.

**After.** Colour codes are stripped before the binary test, so the same call returns:

```
Process exited with code 1
Output:
[ERROR] /ws/src/main/java/pipeline/Importer.java:[88,31] method accumulate in class
        pipeline.Importer cannot be applied to given types;
[ERROR]   required: java.lang.String,int
[ERROR]   found:    java.lang.String
```

A real PNG is still replaced by the fact line. Verified: the escape byte is the *only* control
character in Maven's output; stripping it flips the verdict.

---

## 2. cria states an environment fact it never checked, and the guard cannot see the task

**Now.** The task says *"we'd rather lean on something maintained"*. The model checks what is
installed:

```
$ gem list | grep -iE "country|eu|iso"
fileutils (default: 1.7.0)
```

cria reads that and writes:
> "Stop looking for country/EU gems — none exist in this environment. Write the code yourself…
> Use a simple constant hash for the country-to-zone map."

`gem list` shows what is **installed**. It says nothing about what is **installable** —
`gem install countries` works on that box, and gemma4 did exactly that in the same task and scored
the check. cria turned an observation into a conclusion, and the conclusion made hand-rolling the
only option left.

cria does check every directive before sending it. Here is the entire question it asks:
> "does this directive hand the coder code to copy, or does it describe in words what must become
> true and leave the writing to the coder?"

It is shown 700 characters of directive with **no task and no workspace**. It answered `DESCRIBES`
and let it through. It was never in a position to notice the directive told the model to do the one
thing the user ruled out.

**After.** Two changes.

The steer may report what a command returned, not what cria concludes the world is like:
> "`gem list` shows no country/EU gem installed. That is what is present, not what is installable."

And the guard is given the user's task, so it can ask the question that matters — *does this
directive tell the coder to do something the task ruled out?* Here that is a one-word answer.

**Not** "steers must be vague." A specific steer is often exactly what a weak model needs.

---

## 3. The hand-off note reports stale problems as current

**Now.** When the conversation gets long, cria asks the same weak model to write a summary, with no
files on screen and no check output. Its instructions require it to fill in *"what still fails and
why (quote the concrete error and file:line)"*. So it fills that slot from memory:

> "**Fix Compilation:** Move the declaration of `List<Future<Map<String, Double>>> futures` outside
> the `if (WORKERS_ENABLED …)` block so it is accessible in the merge logic."

That build error had already been fixed. cria then pins the note to the top of every later prompt
under this heading:

> "Earlier in THIS session you worked on this task and produced the summary below — **this is YOUR
> OWN prior work**…"

So a guess now outranks the file on disk, in 200+ prompts.

The summariser already has a rule against inventing a *pass*: *"Only state that tests PASS or the
build WORKS if the transcript shows the check ACTUALLY RAN."* **The rule is one-sided.** Nothing
stops it inventing a *failure*.

**After.** The same rule, both directions. A problem may be carried forward only if the transcript
shows the check that found it actually ran, and it is stamped with when:

> "At call 180, `mvn compile` exited 1: `cannot find symbol: variable futures`. Not re-run since."

Unverified state is labelled as such, exactly as an unverified pass already is.

---

## 4. Old check results replayed as current

**Now.** cria re-attaches the last check output under this heading, verbatim from
`prompts/steer_checks_repeat.txt`:

> "⟦ctx:checks⟧ These are the repo's own checks, **unchanged since you were last shown them — you
> have not cleared them yet.** They are the checker's exact words, not a summary"

Sometimes the model has already fixed the thing. cria is then stating, as fact, something it has not
observed — and the reader is separately told to rank that block above everything else it can see. It
cannot doubt cria, so it doubts reality: stale bytecode, Ruby caching, unsaved files, inconsistent
tools. Or it spends its one steer ordering a fix that landed calls ago.

**After.** cria says when, and stops claiming "unchanged":

> "⟦ctx:checks⟧ These are the repo's checks as they ran at call 41, before your edit to `rates.rb`.
> They have not been re-run since."

And the block expires the moment a file it names is written again — at which point cria re-runs the
checks or drops them. cria never asserts a present state it has not observed.

---

## 5. "Don't weaken the tests" aimed at the model's own tests

**Now.** cria appends this to every failing-check report:

> "If a TEST is what failed, fix what the test caught; changing the test so it stops asking is not a
> fix."

In nemotron's Ruby run the failing test was one the model had written itself, five calls earlier,
with a bug in the test's own setup. It read the rule as binding:

> "However, the instruction says 'Don't change what the tests assert…' So we must adjust code to
> meet the test expectation."

It then bent working code to satisfy its own broken test.

The rule is not wrong and should not be deleted — it was added because models talked themselves into
weakening real assertions. It is aimed at the wrong set of files.

**After.** Scope it to the tests that were there at the start, which cria already knows:

> "If a TEST is what failed, fix what the test caught; changing the test so it stops asking is not a
> fix. This covers the tests that came with the repo. Tests you wrote this session are yours to
> correct."

---

## 6. cria orders work that is already done

**Now.** cria builds its view of the session from the model's recent *thinking*, not from disk. With
three minutes left on the clock, nemotron's Rust run was told:

> "Create the command-line tool that reads the TOML file and prints the value."

The tool had existed since call 7. 22 occurrences across the arm; pure waste in every one.

**After.** Before a finished directive is sent, cria checks it against the disk. If the file it asks
for already exists, or the command it prescribes already failed in this session, the steer is
dropped and nothing is injected. Silence is free; a wrong order is not.

---

## 7. A write is answered with nothing but "Wrote <path>"

**Now.** The model writes a file. The entire tool result is:

```
Wrote lib/shipping/rates.rb
```

So the newest copy of that file anywhere in the model's context is the version from **before** the
change. When it later rebuilds an edit, it reproduces the stale version it can still see. cria's own
judges hit the same wall: file contents clipped mid-word with no marker, so one judge reported the
same phantom truncation four times in a single run —

> "in turn [21] … they wrote a truncated file to `test/test_rates.rb` (`assert_equal 6.49, Sh;`)"

The file was complete and 45 lines long. The clip was cria's.

**After.** The write result carries the file's new content, so the freshest copy in the conversation
is the current one. And a shortened view never stands in for a file in a judge's transcript: show it
whole, or require the judge to read it from disk before it may claim anything about its contents.

---

## 8. The "what can I run?" judge has the manifests filtered out of its list

**Now.** cria asks a judge whether the task needs a program run, and hands it the workspace listing
with data files removed — sensible, since you do not *run* a pom.xml. On gemma4's Java run the list
was one line:

```
PROGRAMS THAT ACTUALLY EXIST IN THE PROJECT DIRECTORY RIGHT NOW:
  src/main/java/pipeline/Importer.java (6783 B)
```

But the same prompt then says the command may be *"that tool's own run target — `cargo run`,
`go run .`, `mvn exec:java`, `npm start`, `rake`"*. **The filter removes exactly the files that say
which of those five applies.** `.xml`, `.toml`, `.json` and `.mod` are all on the strip list. The
judge concluded:

> "There is no `pom.xml` or `build.gradle` listed in the provided file list? … if there's only a
> `.java` file and no build system visible…"

No final verification run happened. cria's own code comment already records this on Rust —
Cargo.toml and Cargo.lock stripped the same way.

**After.** A build manifest is not a document. One named entry per ecosystem survives the filter and
is labelled for what it is:

```
PROGRAMS THAT ACTUALLY EXIST IN THE PROJECT DIRECTORY RIGHT NOW:
  src/main/java/pipeline/Importer.java (6783 B)
BUILD FILES — not programs, but they name the run target:
  pom.xml (1204 B)
```

---

## 9. A read that did not return the file is logged as a completed read

**Now.** The model asked to read `<workspace>/Importer.java`. The real file is
`src/main/java/pipeline/Importer.java` and is 6,783 bytes; the workspace root holds only
directories. cria's ledger recorded:

> "**WHAT HAS REALLY BEEN READ THIS SESSION** (parsed from the documents themselves):
>  - /tmp/…/Importer.java — 261 chars read from disk"

261 characters, for a 6,783-byte file, at a path that does not hold it. The judge read the ledger,
ruled the reading step DONE, and the run moved on without ever opening the code. (The raw result is
not recoverable — compaction removed it from the conversation before the next capture — so the exact
error text is unconfirmed. The discrepancy is not.)

**After.** The ledger records a read only when the command succeeded, and it does not describe a
failure as a document. The judge sees the truth:

> "- /tmp/…/Importer.java — read FAILED (exit 1). Nothing was read."

---

## Order

8 and 9 first: small, certain, no assist removed. Then 1 (done), 3, 4, 6, 7 — each stops cria
asserting something it has not observed, which is doctrine 5b and needs no trade-off argument.

2 and 5 last. Both narrow an assist, and the walk read only assisted runs — there is no baseline
control yet, so there is no evidence about what these assists also *earn*. gemma4's Ruby went
40% → 100% under the same machinery.
