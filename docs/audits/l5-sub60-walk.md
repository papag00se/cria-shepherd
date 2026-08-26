# Walk — every L5 cell below 60%

Nine of the twenty-four level-5 cells scored under 60 on the 144-cell engagement ladder. This walks each one from its captured session — cria's own event log, the prompts it sent, the workspace it left — and asks one question per cell: **what failed, and did cria cause or worsen it?**

Level 5 is the full stack: tool-call repair, cria's tool menu, context fixes, done-refusals and assists all on. If cria hurts anywhere, it hurts most here.

| cell | score | root cause | cria's part |
|---|---:|---|---|
| nemotron-elastic × orders-api-py | 5 | `setattr` on a dict kills the package import | none found |
| nemotron-elastic × shipping-rates-rb | 8 | one-glyph typo of its own workspace path | **caused** — near-miss note could not see a dropped letter |
| ternary-bonsai × feed-pipeline-java | 15 | opencsv's two reader APIs mixed | none found |
| nemotron-elastic × feed-pipeline-java | 22 | two invented opencsv class locations | none found |
| nemotron-elastic × cart-billing-go | 24 | Python's decimal API written in Go | 30-call read/test spiral unseen |
| qwen35 × orders-api-py | 29 | app never reaches its own query layer | 27 calls lost to `/tmp` refusals |
| nemotron-elastic × handles-cli-node | 39 | `--help` tested against the wrong array | **worsened** — 18 refused surveys, stale view |
| gemma4 × rust-toml-cli | 51 | see below | **worsened** — 46 refused surveys, stale view all run |
| qwen35 × handles-cli-node | 58 | live test never invokes the CLI | 6 calls lost to `/tmp` refusals |

Two cria defects were found, both traced to root cause, both fixed and pushed. Six of the nine cells failed on the model inventing a library API, with no cria contribution visible in the session.

## Defect 1 — the workspace-typo note is blind to a dropped letter

`shipping-rates-rb × nemotron-elastic` typed `…-zpis1_t` for its real workspace `…-zpsis1_t` and asked to list it. The path is genuinely outside the workspace, so `dirguard` refused — correctly. It then repeated the same mistyped call for the rest of the session: **42 of its 115 coder calls drew that refusal, from the second call to the last.** It scored 8.

cria already has the sentence that ends this loop. `external_path_case_note` says *"the path you gave differs from the project directory ONLY BY A TYPO"*, and `_case_typo_of_workspace` decides when to attach it. It never fired, because the fold it used only case-folded and collapsed dash/underscore — and a dropped character survives both.

The function's own docstring records the two earlier walks: a capital `I` for a lowercase `i` (106 calls, ~300 wasted), then an underscore for a dash one glyph over, which "the note never fired [for] because the fix was letter-case-only". **This is the third instance, and the third glyph class.** Each fix widened the fold by exactly the class just walked, so the next class walked in fresh.

Fixed by asserting the property instead of enumerating its instances: the path is a typo of the workspace when the segment that should have been the workspace is **within one edit** of it — Damerau-Levenshtein ≤ 1, which covers case, dash/underscore, a dropped, doubled, wrong or transposed character, and whatever the fourth walk would have found. Bounded to a sibling of the real workspace so a genuinely different directory can never draw the note. `tests/test_dirguard.py::WorkspaceTypoIsOneGlyph` asserts six glyph classes and five non-matches.

## Defect 2 — cria's survey outgrew the result it rides home on

cria has no synchronous channel to the harness, so it asks the workspace questions by appending a survey command to a tool call it is already lowering. The ride-along note is explicit about the constraint:

> The survey is appended to write/edit/list translations, **whose own output is one bounded line**.

That is true of writes and edits. It is false of `list_dir`, whose lowering caps its listing at `READ_INLINE_MAX` — **9,000 bytes on its own** — against a survey measured at 6.6–10 KB in these sessions. One result could reach ~19 KB against the ~10 KB a harness keeps.

The harness then cuts the middle. The survey's closing marker is in the tail and survives; the records in the middle do not, so the entry count it declares no longer matches the records that arrived. `wsview.apply_survey` refuses it — correctly, because a listing cut in transit is indistinguishable from a listing of a smaller repo. cria then runs on with a stale workspace view, and the readers that lose it are the gate probes and `_confirm_completion`.

Measured across all 144 cells: **449 refused surveys in 11 cells**, and the refusals track the harness's own cut markers almost one for one.

| cell | surveys refused | harness cuts |
|---|---:|---:|
| L5 nemotron-elastic × rust-toml-cli | 112 | 127 |
| L5 gemma4 × shipping-rates-rb | 94 | 94 |
| L4 nemotron-elastic × rust-toml-cli | 49 | 60 |
| L5 gemma4 × rust-toml-cli | 46 | 47 |
| L2 qwen35 × shipping-rates-rb | 29 | 29 |
| L2 qwen35 × rust-toml-cli | 17 | 17 |

Eight of the eleven affected cells are L5 runs — the rung where the view has the most readers. Two of them are in this walk's below-60 list.

Each half was bounded and their **sum** was not, which is the whole bug. Fixed by dropping `list_dir` from `_SURVEYABLE`: writes and edits really do answer in one line and keep carrying the survey, and a `list_dir` changes nothing on disk, so a view that waits for the next write is not stale about anything that happened in between. `tests/test_the_survey_never_outgrows_one_result.py` asserts the property — no surveyable tool may be a read, list, fetch or search — rather than today's four tool names.

## Not a defect, but the operator's call — `/tmp` scratch is refused

Three below-60 cells lost calls to a refusal that is working as designed. `[safety] external_dir_permission` defaults to `none`, so anything outside the workspace is refused for reads and writes alike.

| cell | path refused | prompts carrying the refusal |
|---|---|---:|
| qwen35 × orders-api-py | `/tmp/test.db` | 29 |
| ternary-bonsai × rust-toml-cli | `/tmp/test.toml` | 30 |
| qwen35 × handles-cli-node | `/tmp/test-handle-lookup` | 9 |
| qwen35 × feed-pipeline-java | `/tmp/determinism_test.java`, `~/.m2/repository` | 68 |
| nemotron-elastic × rust-toml-cli | `~/.cargo/registry/…/toml-0.8.23/src/value.rs` | 25 |

Across all 24 L5 cells, **213 prompts carry an external-path refusal**. Every one of these is a model reaching for a scratch file or a dependency's source, and the refusal already names the alternative (`./tmp/`). The models mostly do not take it: qwen35 spent calls 44–71 on `/tmp/test.db` before moving on.

The last row is the one worth the operator's attention. `nemotron-elastic × rust-toml-cli` was **trying to read the toml crate's own source to learn its API** — and the single most common failure cause in this entire campaign is models inventing library APIs. That cell went on to invent `Value::Number`. Raising the level to `read` would allow exactly that lookup while still refusing every external write. It is a config change with a real quality argument behind it, and it is not mine to make.

## The six cells with no cria contribution

They fail the same way, and it is not a process failure:

- **ternary-bonsai × feed-pipeline-java** — `reader.readNext()` throws a checked exception and sits unguarded, while the `catch` written for it wraps the iterator loop, which cannot throw it. Zero cria interventions all session.
- **nemotron × feed-pipeline-java** — imports `com.opencsv.CSVRecord` (that class is commons-csv's) and `com.opencsv.exceptions.CsvParseException` (the real name is `CsvException`). Its review then lists its own unfixed compile errors, with file and line, as the deliverable.
- **nemotron × cart-billing-go** — `taxed.Quantize(2, decimal.ROUND_HALF_UP)`, both names from Python's decimal module.
- **nemotron × orders-api-py** — builds a dict to stand in for a module, then calls `setattr` on it.
- **nemotron × handles-cli-node** — tests `--help` against the constant catalogue of flags instead of the user's arguments, so help always fires.
- **qwen35 × orders-api-py** — a working query layer the app never routes to.

## The spiral cria no longer watches for

`nemotron × cart-billing-go` spent its **first 30 calls of 60** on `read cart.go → go test → read cart.go → go test`, with three identical reads in a row at one point and no write to `cart.go` until call 31. Nothing fired: the wheel-spin trigger counts *writes*, and there were none.

The detector that would have caught it — "the same action N times in this window" — was removed on 2026-08-19 on measured grounds recorded in `guard_track_refusals`: base runs containing three or more identical consecutive calls averaged 51%, and the cria runs where the steer fired averaged 48%. **It should stay removed.** This cell is evidence for that, not against it: the model self-corrected out of the spiral on its own at call 31, exactly as the removal note predicts, and then failed on `Quantize` — a defect no anti-spiral steer touches. Re-adding it would buy back thirty calls and change the score by nothing.

## What this walk did not find

No cell showed cria destroying working code, mis-steering a model away from a correct approach, or truncating content the model needed. The context floor, the tool menu, the write proxy and the done-refusals all behaved. The two defects found were both cria failing to *help* — a note that did not fire and a view that went stale — never cria doing harm.

The campaign's headline stands after the walk: at level 5 the failures are library APIs the models invent, and the ladder's rungs do not touch that.
