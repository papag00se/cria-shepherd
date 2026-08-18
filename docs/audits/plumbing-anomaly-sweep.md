# Anomaly sweep — the plumbing (swept 2026-08-17)

**Seed.** Walking a failed run showed cria refusing a file write with the message `:36: s`. The write validator shells out to the language's syntax checker, then reports the failure as `_msg.splitlines()[0][:200]` — a per-line cap *and* a character budget, on a compiler diagnostic, which principle 5 names explicitly as truncation. The model discarded a complete working implementation because it could not see the error.

Five orthogonal lenses, dispatched in parallel. Every HIGH below was spot-checked against source or measured against the 16,849 captured calls before it was written down.

| lens | question |
|---|---|
| Truncation | where else does cria shorten what the model reads |
| Matchers | where else is a rule keyed to one tool's wording and silently inert elsewhere |
| Unverified facts | where else does cria assert a count, cause or state it never observed |
| Suppressed guards | where else can the failure a guard detects prevent the guard from firing |
| Divergent copies | where else is one owned fact stated twice and drifting |

---

## Tier 1 — broken now, small fix each

- [ ] **The syntax refusal destroys the diagnostic.** `writeproxy.py:427` keeps line one of the checker's output and cuts it to 200 chars, *after* substituting a 96-char workspace path that `ruby -c` prints twice — 198 of the 200 characters are path. The `_at` helper that exists to quote the offending source line back is itself capped at 200 (`writeproxy.py:461`). Delete both caps; a compiler diagnostic is ground truth and goes whole.
- [ ] **The offline test re-run keeps the last 600 bytes, undisclosed.** `proberun.py:800`. A suite's failure header is at the top. No marker says anything was removed.
- [ ] **The dependency-note fix never reaches the gate path.** `proberun.py:581` calls `dependency_note(report)` with no `workspace_root`, so `install_landed` returns `None` and the corrected branch is unreachable — the coder still gets the false "a gem installed with `--install-dir` is not on the load path" sentence. `writeproxy.py:1555` passes the root correctly; one of two sites got it. The test calls `dependency_line` directly and passes over the gap.
- [ ] **Two live steers threaten a truncation that no longer happens.** `large_read_steer.txt:1`, `large_range_steer.txt:1` — "reading it whole would be truncated" — against the operator ruling recorded in `oversize_refusal.txt:3`: no elision and no truncation on any path. `writeproxy.py:679` calls that sentence false and removed it from the spill path only.
- [ ] **The Ruby load-path advice contradicts itself across two prompts.** `dependency_note.txt:10` says set `GEM_HOME`; `install_remedy.txt:26` says `GEM_HOME` is insufficient because tests you did not write run without it. The note also describes `gem install --install-dir` when cria routed the coder through bundler — the same defect the walk found in `install_remedy.txt` itself.
- [ ] **The rumination notice states a cause of zero.** `rumination.py:312` fires on marker density OR raw length; both render *"Your last reasoning pass hit N second-guessing phrases"* (`rumination_guard.txt:1`). On the length arm N can be 0. `loop.py:8319` records fixing this exact self-refuting shape for the sibling detector.
- [ ] **The repeat count is borrowed, in two places.** `loop.py:5410-5412` emits `count=REPEAT_FINGERPRINT_N` and sets `repeat_action` to whatever call was in flight, for both the repetition route and the refusal route. `redirect_canned.txt:1` reads the same field and adds "in a row", which is false for the windowed route too. Measured cost in the walk: a reasoner told "three failed attempts" about one call, which ordered the model to hardcode data the task forbade.
- [ ] **A comment claims a test that does not exist.** `selfcompact.py:436` — "Mirrors writeproxy's write-tool names; a test asserts sync". Nothing in `tests/` references `_WRITE_TOOL_NAMES`, and the lists have diverged: `create_file` and `str_replace` payloads are never stubbed after compaction.
- [ ] **The rumination watcher goes blind after one reasoning token.** `upstream.py:721` — `watch_text = "".join(reasoning) or "".join(content)`. One reasoning delta makes the first truthy forever, so a runaway that then floods content is unwatched.
- [ ] **The URL-guess streak cannot advance on its dominant failure.** `webfetch.py:1241` gates on `status is not None`; a transport error returns `None` (`webfetch.py:1284`). A model guessing nonexistent domains gets DNS failures, so the threshold is unreachable. Its test calls `guess_hint` directly.
- [ ] **The periodic step check is effectively dead.** `loop.py:3012` triggers on an exact modulo against a counter `guard_periodic_gate` zeroes from outside. **Measured: 1,147 `periodic_gate` against 14 `periodic_step_check`**, all fourteen at `turns=12, step=1`.

## Tier 2 — structural, scoped

- **The proxy stream path has no guards at all.** `upstream.py:446` iterates SSE with no dead-stream, degenerate, window or rumination check; `server.py:989` routes every non-loop request through it. **That is the entire BASE arm** — which is why the baseline's longest single call is 525 seconds of nothing. Route it through the watched reader.
- **The dead-stream clock is read off frame arrival.** `upstream.py:691` sits inside `for raw in resp:` and behind two `continue` guards. Measured: fired **once** in 16,849 calls, at 743.4s against a 180s threshold; the 400-frame arm has never fired. Read the clock off the heartbeat that already ticks during a stall.
- **"Zero tests collected" is recognised only for pytest.** `proberun.py:191`, consumed by `gate_ran_tests`. Verified false for go `[no test files]`, jest `No tests found`, cargo `running 0 tests`, rspec `0 examples` — so a vacuous green passes in six of seven languages and cria tells the satisfaction judge tests ran. Derive it from the tally table that already covers twelve runners.
- **PHP has no test discovery and no entry-point detection.** `probediscovery.py:337` gates PHP on `composer.json`, which PHP does not require; `execcheck.py:77` detects PHP entry points by shebang alone and has no composer row. Verified: a PHP workspace yields `discover() == []` and `corroborate()` abstains. Ruby's identical hole was fixed by widening to `Rakefile`. `handles-php` is a live cell.
- **Write-tool names are hand-kept in eight places** despite `shelltool.is_write_tool_name` existing with zero callers. Each list is missing different entries: `loop.py:145` has `apply_patch` and not `str_replace_editor`; `contextfloor.py:69` the reverse. Verified: a Claude Code menu reduces to `['Bash']` — every file tool dropped.
- **Three "keep this verbatim" marker lists disagree.** `selfcompact.py:74`, `contextfloor.py:82`, `loop.py:6501`. The floor does not protect markers selfcompact declares must never be lost; selfcompact does not exclude the floor's own synthesized note, producing the summary-of-a-summary it exists to prevent. Both sync tests assert one-way membership.
- **The truncation guard erases the evidence the spiral detectors need.** `_drop_tool_calls` (`loop.py:8481`) strips the call, so `loop.py:2317` skips both `guard_track_repetition` and `guard_track_write_streak` — the corruption loop its own docstring describes never accrues a streak.
- **Stream-error recovery forfeits every guard.** `upstream.py:747` re-asks buffered on an SSE error, unwatched, bounded only by the 7200s read timeout — and a runaway is a plausible cause of that error.

## Verified after the sweep — what survived and what did not

**LANDED (six).** Tier 1's syntax refusal, the borrowed repeat count, the dependency-note root, and the read-refusal wording; Tier 2's wire silence deadline and the vacuous-green test check. Each was re-verified or reproduced before it was touched.

**REFRAMED — the read refusal.** Filed as "the operator ruled out truncation on every path, so the sentence is false". That did not survive: the ruling governs cria's own paths, and a claim about a downstream cut is a different claim. What makes it false is narrower — the refusal fires at 9,000 bytes and the truncation it cited was measured at ~20,707 tokens, nine times higher. So at the size it actually fires, nobody would have truncated anything. Fixed on that reason.

**NOT BUILT — PHP discovery, and it is wider than PHP.** The claim checks out: `discover()` on a PHP project with source and tests but no `composer.json` returns nothing. But ecosystem detection is manifest-only for *every* language, and the consequence is not confined to PHP:

```
orders-api-py     (its real seed) ->  NOTHING
shipping-rates-rb                 ->  rake test, rubocop, rspec
feed-pipeline-java                ->  mvn compile, mvn test
```

**`orders-api-py` discovers no probes at all, and it is the highest-scoring Python cell (90–100%).** So cria's gate has never run a test on it. That is a coverage gap, not a false fact — with the vacuous-green fix landed, `gate_ran_tests` now correctly reports that no tests ran, so the judge is told the truth about cria's blindness rather than a fiction.

Not built, deliberately. It is an ADDITION of coverage, rule 1 sets a high bar for those, and rule 15 asks for prevalence first — of the 21 `loop.gate` events in the logs, **zero found no probes**. The cell scores 90–100% without cria's gate, so the cost of the gap is unmeasured. **Trigger to revisit:** a walked run where the gate's silence is what let a wrong answer through, or a Python cell whose score is limited by unverified tests.

## Tier 3 — bigger, defer until the area is touched

- **The gate's entire evidence is head+tail cut in the shell it generates.** `proberun.py:731` — `head -c N` / `...[middle N bytes elided]...` / `tail -c N`, budget split across probes. This is the seed at full scale: compiler and test output, the ground truth every verdict rests on. Spill it whole and hand back a path, the way an oversized fetch already works.
- **The delivered program's own output is cut at 4,000 chars, twice.** `execcheck.py:511` and `:605` — the live-run evidence that decides `NOT_OBSERVED`.
- **Test-failure messages become 200-char findings.** `probeparse.py:705`. Assertion diffs are routinely longer.
- **The lossy prose-stripper is still on a model-facing path.** `contextfloor.py:360` → `content_reduce.py:151`, whose own comment records it inverting a note's meaning ("could not be read from it" → "could read it"). `digest_reduce` exists to avoid exactly this and is used elsewhere.
- **Ecosystem maps in four copies** with different coverage: `probediscovery.py` (10), `execcheck.py:158` (no Python, PHP, DotNet), `dirguard.py:180` (no Go), `linterprobe.py:65`.
- **Token estimation corrected in one path only.** `contextfloor.py:198` uses the learned ratio; `rumination.py:278` and `upstream.py:723,887` use raw `len//4`.
- **API-spec facts clipped per field** — descriptions at 96 chars, examples at 32, field lists at 40 (`webfetch.py:541,558,703`; `apidiscovery.py:196,314`).

---

## Posture check

The sweep found a lot, and the reason it could is that this codebase records its own reasoning. Nearly every finding above was locatable because a docstring or comment states what the mechanism is *for* — which is what let five agents tell a deliberate narrow scope from an accidental one. Several findings are literally "the comment says a test asserts this; it does not", which is only a finding because the comment was written.

What is working, verified during the sweep rather than assumed:

- **The reasoning-channel tool-call recovery.** 598 of 766 otherwise-dead reasoner replies are recovered; the residue is 1.8%.
- **The repeat-call detector and content de-duplication**, both firing correctly in the walked runs with the model responding.
- **The gate-side line matcher** (`probegate.py:324`) is shape-based, not phrase-based — which is precisely the contrast that makes the seed's `line\s+(\d+)` an accident rather than a policy.
- **Superseded-write stubbing** is working in the coder body.
- **The BASE/CRIA arm separation is real**: steers, gate blocks and the `__cria_` leak appear in zero baseline runs.

Three of the walk's five findings turned out to be plumbing shared by both arms rather than drive defects. That is a good sign about the drive loop and a bad one about the plumbing, and this report is mostly about the plumbing.

## Also open, from the walk (docs/audits/four-failed-runs-walk.md)

- `write_file` has no identical-bytes refusal, though `edit_file` does and cria holds the pre-write bytes.
- The "these checks ran before your edit" caveat attaches only to the newest check block; an older one silently sheds it and reads as current.
- The `__cria_` shell variables are model-visible inside a command attributed to the coder. Reported in three prior walks, never landed.
