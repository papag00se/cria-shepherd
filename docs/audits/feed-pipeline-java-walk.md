# Walk — `feed-pipeline-java × qwen35`, 2026-08-19

**Result: 0 of 5.** 319 calls, 61 minutes, killed at the wall.

| milestone | score |
|---|---|
| 30 min | **4.0 / 5** |
| 45 min | 3.0 |
| 60 min | **0.0** — wall |

It held four of five deliverables at the half-way mark and finished with none. `REVIEW.md`, the cheapest deliverable on the board, was never created at any point in the run.

Walked line by line across seven segments. Every finding below was re-verified against the captures by hand before it was written down; three subagent findings were checked and **rejected** (see the last section).

**Evidence files** are copied into [`runs/walk-feed-java-0819/`](../../runs/walk-feed-java-0819/) so they can be opened directly. Each problem names the exact files. The four worst are also extracted into single readable `EXTRACT-*.txt` files.

---

## Where the hour went, before any of the defects

| coder turns | 242 |
|---|---:|
| `exec_command` | 105 |
| `read_file` | 73 |
| `write_file` | 23 |
| `edit_file` | 18 |
| `list_dir` | 13 |
| everything else | 10 |

**178 of 242 turns — 74% — were looking, not changing.** Only 41 turns wrote anything. Of the 105 shell commands, 38 were `head`/`cat`/`wc` re-reading the one file the model kept rewriting. `read_file` on that file is refused as too large, so the model re-acquired it in slices, over and over, after each of its six whole-file rewrites.

That is the baseline cost the defects below sit on top of.

---

## Problem 1 — cria destroyed the workspace file with its own placeholder text

**Severity: highest. This is what turned 4/5 into a rebuild-from-scratch.**

- Evidence: [`0095-coder-s1.response.json`](../../runs/walk-feed-java-0819/0095-coder-s1.response.json), [`0097-coder-s1.prompt.txt`](../../runs/walk-feed-java-0819/0097-coder-s1.prompt.txt), [`0097-coder-s1.reasoning.txt`](../../runs/walk-feed-java-0819/0097-coder-s1.reasoning.txt)
- Readable extract: [`EXTRACT-0095-the-destructive-write.txt`](../../runs/walk-feed-java-0819/EXTRACT-0095-the-destructive-write.txt)

### What happened

To save context, cria replaces a *superseded* write's content **inside the model's own conversation history** with a placeholder. The template is `write_stub_superseded` in [`cria/prompts/compact_view.txt`](../../cria/prompts/compact_view.txt).

At call 0095 the model, rewriting that same file, copied the placeholder forward as the new file content:

```
[elided 8031 chars — an EARLIER version of ./src/main/java/pipeline/Importer.java,
 replaced by a later write in this session; read_file for what is actually on disk now]
```

The write executed. At 0097 javac said:

```
Importer.java:[1,1]   class, interface, enum, or record expected
Importer.java:[1,20]  illegal character: '—'
```

`—` is the em dash in cria's own sentence. The model's reasoning at 0097, unprompted:

> *"The file got corrupted with placeholder text. I need to rewrite the entire file properly."*

A 357-line file became one line of cria's internal note. Recovery was `git checkout`; the only commit in that workspace is the seed, so it reverted to the **original broken importer** and threw away everything built since — including a threading fix that then had to be re-diagnosed and re-fixed from scratch.

### Where the fix belongs

A led to B which broke C, so fix A. **A** is that the stub is model-facing prose sitting in exactly the slot where file content sits, carrying nothing that marks it as cria's. This repo's own rule is that model-facing markers are `⟦ctx:…⟧`; all four stubs in `compact_view.txt` are bare `[elided …]`.

**Fix, two parts:**

1. **Refuse any write whose content is cria's own marker text.** Deterministic, cheap, and it alone would have saved this run.
2. **Mark the stubs** so they are recognisable as cria's rather than as something the model might have written — which is what makes (1) general instead of a string match against four templates.

Do not fix B (do not teach the model to avoid the placeholder). The placeholder should be unmistakable and the write should be refused.

### Before / after

| | |
|---|---|
| **before** | `write_file(content="[elided 8031 chars — an EARLIER version of …]")` → **written to disk**, tool reports `Wrote …`, file destroyed |
| **after** | write refused: content is cria's own history marker, not file content — read the file and write real content |

---

## Problem 2 — cria's re-orientation reasoner wrote a bash script, cria shipped it, the model called it "the user"

**Two independent occurrences.**

- Evidence: [`0066-reasoner.response.json`](../../runs/walk-feed-java-0819/0066-reasoner.response.json), [`0067-coder-s1.prompt.txt`](../../runs/walk-feed-java-0819/0067-coder-s1.prompt.txt), [`0067-coder-s1.reasoning.txt`](../../runs/walk-feed-java-0819/0067-coder-s1.reasoning.txt) — and again at [`0156`](../../runs/walk-feed-java-0819/0156-reasoner.response.json) / [`0157`](../../runs/walk-feed-java-0819/0157-coder-s1.reasoning.txt)
- Readable extract: [`EXTRACT-0066-reorientation-wrote-bash.txt`](../../runs/walk-feed-java-0819/EXTRACT-0066-reorientation-wrote-bash.txt)

### What happened

After a compaction, cria asks a reasoner to write one short orientation directive. Its system prompt says *"Output ONLY that directive to the coder — no preamble, no meta-commentary."*

The reasoner answered with first-person narration and a series of fenced `bash` blocks. cria injected the whole thing verbatim as `⟦ctx:steer⟧`.

The coder's next reasoning:

> **"The user is right - I need to inspect the workspace before continuing. Let me run the commands they suggested."**

It then executed the script command by command — roughly 14 calls at 0067–0080 and 10 more at 0157–0167 — re-deriving facts the continuation summary two messages earlier had already stated with file:line precision.

### Where the fix belongs

The steer channel already has a gauntlet (`_grounded_steer_or_none`: roleplay, argument blobs, ungrounded URLs, phantom paths, phantom fields, dictated code). **The re-orientation output does not go through it.** That is the gap — not the reasoner's disobedience, which a prompt cannot prevent.

**Fix:** route the re-orientation directive through the same guards every other authored steer faces. A fenced code block in a "one short directive" answer should be refused, not forwarded.

### Before / after

| | |
|---|---|
| **before** | `⟦ctx:steer⟧ I need to inspect the workspace… ```bash find . -type f -name "*.java" …``` ` → coder reads it as the user speaking and spends ~24 calls on it |
| **after** | the same guards that catch dictated code catch this: refused, no steer that turn (silence over a bad steer) |

---

## Problem 3 — a true, verified judge finding was thrown away and replaced with boilerplate

- Evidence: [`0304-satisfaction.response.json`](../../runs/walk-feed-java-0819/0304-satisfaction.response.json), [`0305-coder-s1.prompt.txt`](../../runs/walk-feed-java-0819/0305-coder-s1.prompt.txt)
- Readable extract: [`EXTRACT-0304-judge-verdict-vs-what-shipped.txt`](../../runs/walk-feed-java-0819/EXTRACT-0304-judge-verdict-vs-what-shipped.txt)

### What happened

The satisfaction judge did real inspection — `list_dir`, then `read_file` on two files — and returned:

> *"REVIEW.md does not exist in the workspace (confirmed via list_dir). The task explicitly requires creating this file… All other requirements appear to be met."*

What the coder received:

> *"This step is not yet verified as complete. Keep working: re-check the step's goal against the files on disk, then demonstrate completion by running the repo's own checks and showing their real, unfiltered output."*

The judge's inspection had hit its budget cap, so `inspection_capped` discarded the reason and substituted `unverified_step`. The guard exists because a capped judge once asserted something false and cost a working run a check. Here the discarded reason was **true, specific, and the one thing the run needed to hear** — `REVIEW.md` was never written in 319 calls.

### Where the fix belongs

The cap is a proxy for "this judge may not have seen enough." That is a reasonable worry about a claim of *presence* ("the code does X"), which needs reading. It is not a reasonable worry about a claim of *absence* established by a directory listing.

**Fix:** let a capped judge's reason through when the claim is an absence the judge verified with a listing it actually ran. Keep suppressing capped claims about file contents. This narrows the guard rather than removing it.

### Before / after

| | |
|---|---|
| **before** | judge: *"REVIEW.md does not exist (confirmed via list_dir)"* → coder receives generic "keep working" |
| **after** | coder receives the absence, named: *"REVIEW.md does not exist in the workspace"* |

---

## Problem 4 — a dictated shell command shipped byte-identical, through a gap in this morning's fix

- Evidence: [`0270-reasoner.response.json`](../../runs/walk-feed-java-0819/0270-reasoner.response.json), [`0273-coder-s1.prompt.txt`](../../runs/walk-feed-java-0819/0273-coder-s1.prompt.txt)
- Readable extract: [`EXTRACT-0270-dictated-shell-command.txt`](../../runs/walk-feed-java-0819/EXTRACT-0270-dictated-shell-command.txt)

### What happened

The flail steer told the coder:

> *"Stop editing the source file and create the missing REVIEW.md… **Run `cat > REVIEW.md << 'EOF'`** with file name and line numbers for each issue found."*

That heredoc appears nowhere in observed code before call 0270 — the reasoner invented it. It was delivered byte-identical.

This morning's fix restates a dictated directive instead of hollowing it out, but it is gated on `stripped > 0`, and the strip **cannot see shell commands**. Tested directly against that exact string:

```
spans stripped: 0
_CODE_LINE matches the heredoc line?  False
_INLINE_CALL matches?                 False
```

`_CODE_LINE` covers `def`/`class`/`import`/`pip install`/`sed -i`/`cat `/`grep -n`/`pytest`. It does not cover a redirect or a heredoc. So the most dangerous dictated form — a shell command that **writes a file** — is invisible to the guard that decides whether to restate.

### Where the fix belongs

Not in the restate path, which behaved correctly given its input. In `_CODE_LINE`: the shell-write shapes cria already recognises elsewhere (`cria/loop.py::_shell_write_target` knows redirects, `tee`, and heredocs for the wheel-spin guard) are absent from the code-line pattern. **One owner for "is this text a shell write"**, shared by both.

### Before / after

| | |
|---|---|
| **before** | `stripped=0` → delivered unchanged → *"Run `cat > REVIEW.md << 'EOF'`"* reaches the coder |
| **after** | the heredoc is recognised as invented code → `stripped=1` → the directive is restated in words, or refused |

---

## Problem 5 — recovered sibling tool calls are dropped silently

- Evidence: [`0236-coder-s1.response.json`](../../runs/walk-feed-java-0819/0236-coder-s1.response.json), [`0237-coder-s1.prompt.txt`](../../runs/walk-feed-java-0819/0237-coder-s1.prompt.txt)

### What happened

This model emits its tool calls inside `reasoning_content`; cria recovers them (**188 times** in this run). `recover_reasoning_tool_calls` takes `spans[-1]` — the **last** span. When the model emits several *sibling* calls, the earlier ones are discarded and it is never told.

At 0236 it emitted `list_dir`, `list_dir`, `read_file`. Only `read_file` ran.

`spans[-1]` is deliberate and correct for **nested** dialects (a write whose content illustrates another call) — `_outermost` handles that case. Siblings are a different shape and fall through it.

**Blast radius: 3 of 188 recoveries in this run.** Small, but silent, which is the part that matters — cria discards a request without saying so.

### Before / after

| | |
|---|---|
| **before** | three calls emitted, one runs, two vanish with no record |
| **after** | either all admitted siblings run, or the drop is stated: *"only the last of your N calls was run"* |

---

## Checked and rejected

Three subagent findings did not survive verification. Recording them because the walk prompt says a subagent finding is a candidate, not a fact.

1. **"The dictated-code guard let literal Java through at call 0191."** No. Both strings in that steer — `new WorkerResult(0, new ConcurrentHashMap<>())` and `new WorkerResult(new ConcurrentHashMap<>(), new int[5])` — are the coder's own code, eight lines apart in a file it wrote. `stripped=0` is correct; the 2026-08-04 ruling explicitly protects a steer that quotes the coder's own failing line. **cria fault: none.**

2. **"cria truncated the write at 0310 / executes only the FIRST recovered call."** No, twice over. cria showed the model's own prior write back byte for byte (10,173 in, 10,173 out), nothing hit a token cap, and recovery takes the **last** span, not the first.

3. **"The unclosed brace came from a partial view of the file."** No. The model had read the complete file in two successful chunked reads at 0291–0292 before it began rewriting, and cria executed its write byte-identically. It omitted the class's closing brace twice in a row while re-deriving a new chunking design each time. **cria fault: none** — a model authoring slip.

Worth stating plainly: the model **did** catch its own broken file at 0312 and produced a correct, brace-balanced replacement at 0319. That write never reached disk — the wall landed about nine seconds earlier.

---

## Status — 2026-08-19

| problem | state |
|---|---|
| 1 — cria's placeholder written to disk | **fixed** `d387b64` — the superseded call and its result are REMOVED, not stubbed. Nothing is left that can be read as content. |
| 2 — re-orientation shipped a bash script | **fixed** `317c87e` — refused on shape (a fence, or ≥3 command lines), falling back to the canned reanchor that already existed. 57 of 59 captured notes still delivered. |
| 3 — a true judge finding replaced by boilerplate | **fixed** `efee733` — the judge's size cap is gone. Not a revert: `seed_files` fixed the cause seventeen days after the cap was built for it. |
| 4 — a dictated shell heredoc shipped intact | **fixed** `6d9742d`, `700bb79` — `cria/shellshape.py` owns "is this a shell command"; the walked heredoc now routes to the restater. |
| 5 — sibling recovered calls dropped silently | **open**, deliberately (operator: not a concern). |

**None of it has faced a live model.** `loop.steer_restate` has fired **zero** times in every log ever written — the piece that decides what the coder actually reads has only ever been exercised against stubbed answers. What is verified is detection, on the captures, by hand.

Two defects were introduced and fixed inside this same day's work, both mine, both found only because the operator questioned the algorithm rather than the outcome:

* `shellshape.confidence` scored whole blocks, so signals accumulated with length and a 976-character description of real work scored 0.73 — the caller replaced the whole paragraph with a marker. Fixed by scoring the strongest SEGMENT.
* The segmenter split on a bare `.`, shattering `test.test.js` into `- test.` / `test.` / `js`; `test.` opens with a binary name, so bullet lists of filenames scored as commands. And `signals()` reported the whole block while `confidence()` reported the best segment, so a caller could see a score of 0.45 with an empty signal list.
