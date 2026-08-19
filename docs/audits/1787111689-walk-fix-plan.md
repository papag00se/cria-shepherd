# Fix plan — the walk of `shipping-rates-rb × ternary-bonsai` `1787111689`

Run: 3/5, 75 calls, 61 minutes, killed at the 60-minute floor. Walked in full — 28 chunks, four readers, every call and every reasoning block. Findings below are **grouped by root cause, not by symptom**, because most of the twenty-odd observations collapse into nine roots. Each root carries the evidence, the fix, what it risks, and what would prove it wrong.

**Nothing here is built.** Three small fixes already landed during the walk and are marked `landed`; everything else is a plan.

---

## The one-paragraph story

The model shipped three of five checks unaided. The other two come down to two bugs: a **symbol key where the gem uses a string** (`data[:eu_member]`), and a **repo test broken by a line cria pasted into a steer**. cria's own judge diagnosed the first one exactly — naming `in_eu?` and the string key — and cria **suppressed the verdict** because the judge had used up its inspection rounds. Those rounds were spent re-reading files cria had just handed it. `in_eu` appears in **13 judge prompts and 0 coder prompts**.

---

## Tier 1 — cria destroyed or withheld information the coder needed

### A. A capped judge's correct answer is thrown away whole
`loop.satisfaction_gap_withheld {"rounds": 5}` suppressed: *"the countries gem's ISO3166::Country class provides `in_eu?` … not `eu_member?`"*, with the fix. The coder got boilerplate instead and guessed.

The suppression rule is **right** and must stay — it exists because a capped judge invented a gap and talked a coder from 5/5 down to 4/5. What is wrong is treating the whole verdict as one indivisible judgement.

**Fix.** Split the verdict by what cria can check itself. A withheld reason naming a **concrete, verifiable claim** — a method name, a `file:line`, a missing path — is not judgement; cria can test it against disk or against the gem before deciding to drop it. Claims that survive a deterministic check are delivered; the rest stays withheld. This is #8 applied to cria's own judge: the reasoner proposes, deterministic code disposes.

**Risk.** A new delivery path for text a rule currently blocks. Mitigate by delivering only the checked fragment, never the essay.
**Would refute it.** If withheld reasons rarely contain a checkable claim. Measure over the corpus before building: how many `satisfaction_gap_withheld` heads name a symbol, path or line that cria could verify.

### B. The document the coder needed was refused to the coder and handed to the judge
10,251 bytes against a 9,000-byte inline limit. `landed` — the judge no longer receives cria's spill directory, and the seeded block names its root. **The coder is still blocked**, and that half is unfixed.

**Fix, three parts.**
1. **Derive the inline limit from the window that actually exists**, not a fixed 9,000. 10,251 characters is ~2.5K tokens against a 49,152-token window. The context floor is the real guard; this constant is a second, blunter one that fires at 14% over.
2. **Give the refusal a usable handle.** It says "grep the file for what you need" and carries `{{OUTLINE}}` — filled from parsed routes and fields, so a Ruby class reference gets an empty one. The coder was told to grep with no indication what for. When no structural outline exists, emit one from the text: heading lines, `def`/`class` lines, section markers. Something the model can grep *toward*.
3. **Let a refusal that names a line range be taken.** The recovery cria offers (`start_line`/`end_line`) was never used in this run or the previous one.

**Risk.** (1) touches a window-safety constant. It is not a truncation rule — nothing is cut — but it must be justified against the floor, not against convenience.

### C. cria tells the model a page contains nothing, in cria's own voice
`fetched_facts_sections.txt:62`, live on every prompt after the fetch:

> *"this page answered, but no endpoint definitions were found in it … whatever it returned is in the transcript. If this task needs a machine-readable API definition, nothing read so far provides one."*

Two false facts. **"whatever it returned is in the transcript" is untrue precisely because cria refused to put it there.** And the page defines `in_eu?` with its source — "nothing provides one" is a REST-shaped judgement fired at a library reference.

**Fix.** The ledger states what came back and how big it is. It stops rating the page's usefulness. Delete the endpoint-shaped clause; replace the transcript claim with where the content actually is (inline, or the spill path). Same family as the YAML sniff already fixed: **cria must describe a document by what it holds, not by what its parser could extract.**

**Risk.** Low — this is a deletion.

### D. Elision fabricates a record that never existed
`...[middle 6838 bytes elided; head+tail kept so an early failure survives]...` welded **the head of error 1 to the tail of error 5**: a block headed `test_zone_for_non_eu_country_is_international`, holding a **US** country object, ending in **Germany** data, attributed to `test_zone_for_eu_member_is_eu`. Four of five errors never shown. Presented under "the checker's OWN message".

This is worse than truncation. A shortened record is missing information; a spliced record is **information that was never true**.

**Fix.** Elision must never join two records. Cut at record boundaries — per-failure blocks are separable in every runner cria already parses — and drop whole records, saying how many and which. If no boundary can be found, drop the section entirely rather than splice it.

**Risk.** None to correctness. Costs a boundary-finder per runner family, which `probeparse` largely has.

### E. The write digest shows every "before" and no "after"
Every edit reaches the reasoner as `old_string=` in full and `new_string=[elided … an EARLIER version …]`. The seat asked to judge whether the coder is looping is given no diff — which is exactly the judgement it was convened to make. Reasoning is also stripped from replayed history, so the model cannot see that it already concluded *"it stores EU membership as a key in its data hash"*.

**Fix.** Supersession elision must keep the **newest** version, not the oldest. The rule "an earlier version was replaced by a later write" should drop the earlier one and show the later — it currently does the reverse for `new_string`.

---

## Tier 2 — cria pushed the model somewhere worse

### F. A steer pasted code, and the code broke a passing repo test
The `[REDIRECT]` steer at call 0058 shipped:

> `# Instead of: zone = zone_or_code.is_a?(String) && … # Use this: zone = ZONE_BASE.key?(zone_or_code) ? zone_or_code : zone_for(zone_or_code)`

The model adopted it verbatim. Four calls later `test_unknown_zone_rejected` — a **repo** test — went red and stayed red: `"moon"` is not a `ZONE_BASE` key, so it falls through to `zone_for` → `"international"` → no `ArgumentError`. One of the three final failures.

The steer author's own prompt forbids this: *"Describe required code changes in words only. Never provide replacement code, snippets, functions, or lines to paste."* A stripper exists — `_strip_invented_code` — and the run logged `loop.steer_dictated_code {"delivered": true, "stripped": 0}`.

**Fix, and the first step is a reading, not a change.** Establish which path emitted the pasted line: the steer author (stripped, 0) or the redirect/flail author (possibly no stripper at all). Then either the stripper is defeated by the `Instead of X / Use Y` shape — X is observed code, so Y rides in on it — or the path has no stripper. Both are fixable; they are different fixes, and guessing which would be exactly the mistake this document is written against.

**Risk.** The stripper deliberately lets quoted observed code through. Any tightening must keep that.

### G. The one probe that answered the question had its answer deleted
The coder ran `puts c.data[:eu_member]; puts c.name` and got a **blank line**, then `France`. The blank line is the entire bug — `nil`, because the hash is string-keyed. cria's digest rendered that call to the steer author as:

> `→ exit 0: France`

The author then wrote a steer blaming `shipping_cost`, and its own reasoning says *"the country lookup works fine in isolation"* — a conclusion the deleted line disproves.

**Fix.** The digest must not drop empty lines from captured output. An empty line in a program's stdout is a value. Where the digest compresses, it must compress by **dropping whole records**, never by trimming inside one (same rule as D).

### H. Stale red evidence, re-served with a one-sentence disclaimer
The same failing check block was re-shown 22 times in one range, several thousand characters each, with a one-line note that it predates the edit. In two cases the note was **false** — the line numbers in the "stale" block had already shifted to match the edit. In another the before and after were byte-identical, so the note implied a change that had not happened.

**Fix.** Do not re-serve a red block cria knows is stale. Either re-run the check, or show the finding without the body and say it has not been re-run. cria holds both the previous and current results and can say which.

### I. The compaction summary re-injects the ORIGINAL file as current state
Four times in the final stretch, `⟦ctx:compacted⟧` embedded the **starting** `rates.rb` — no `express`, no `zone_for`, and the `>` the model had fixed in its first edit — labelled only *"Summary of what those turns contained"*. Three of the four carried no "re-read for current contents" hedge. The summary bullets are also malformed: `• {"path":"spec/shipping_spec.rb"}read_file` — arguments first, tool name appended.

**Fix.** A compaction summary must not embed a file body that a later write superseded — cria has the write ledger and already uses it for supersession elision elsewhere (see E). Apply the same rule here. Fix the bullet composition separately; it is a formatting bug with a one-line cause.

---

## Tier 3 — waste, and mechanisms that fire without effect

### J. Role escalation is a no-op that costs a full re-prefill
`coder-s1` → `focus1` → `focus2` → `focus3`, each triggering a complete prompt re-render. The system prompt and tool list at focus2 and focus3 are **byte-identical**. Three rumination kills, three full re-prefills, nothing changed in what the model was told.

**Fix.** An escalation that changes nothing should not happen. Either each level narrows something real, or the ladder collapses to one level.

### K. The rumination guard killed the seat whose job was to unstick the run
Two of the last four calls were the steer author and the coder, both terminated with `[finish: rumination]`. The run ended with four consecutive dead turns.

**Fix.** A killed unstick author needs a fallback that is not silence — the ground truth cria already holds, delivered plainly, is better than nothing. Note this brushes against #4 (no fallbacks); the honest framing is that cria should say what it *observed* rather than substitute a guess for a failed reasoner.

### L. The coder burned eight calls on `BUNDLE_PATH` when `bundle exec` works
cria's install advice names `bundler/setup` and `BUNDLE_GEMFILE`, never `bundle exec`. The model invented `BUNDLE_PATH=… ruby -e`, got `LoadError` eight times, and cria never connected them — even though the model's own history contained a working `bundle exec` invocation.

**Fix.** Candidate only. The dependency note now reads the install mechanism off disk; the same reading could name how to *run* a one-liner under it. **Measure first** (#15): how often does a coder issue a bare `ruby -e`/`python -c` against a project-local install across the corpus? Below the bar, record and do not build.

### M. The checks preamble never says whose test failed
~1,000 characters of unchanging rules on every gate injection, and it never distinguishes the repo's tests from the model's own — while the preamble's entire subject is that the two are governed differently. In this run `test_unknown_zone_rejected` was the repo's and the other two were the model's. cria holds both lists.

**Fix.** Label each failing test with which it is. The information is already in the seeded-test comparison the verifier uses.

---

## Not cria's, recorded so the next walk does not re-litigate

- `data[:eu_member]` — the model quoted the string key correctly in prose one turn earlier, then typed a symbol.
- The two-character dispatch (`zone_or_code.length == 2`) that made the zone name `"eu"` collide with country codes — the model's design, before any cria steer.
- One wrong assertion in its own new test, corrected by itself with the arithmetic shown.

## Already landed during the walk

| | |
|---|---|
| the judge stops being fed cria's spill as the coder's work | `fbed921` |
| the seeded block names the root its paths are relative to | `ef9b4d3` |
| the exec-intent seat and its self-vetoing command list | `1e0ac6e`, earlier |

## Outcome — every item worked through

Landed, each with a test naming the incident:

| root | what changed | |
|---|---|---|
| C | the fetch ledger says where the body actually is, instead of claiming a transcript cria refused to write to | `b415161` |
| D | an elision cuts at line boundaries and can no longer splice two records into one | `b21acdc` |
| G | an empty line in a program's output is a value — anchored on the harness's own `Output:` marker | `e6a3626` |
| E | a stale edit hides both halves, so the newest write is where the diff lives | `c115ce4` |
| I | the compaction note says it describes the past; its bullets read as `name(args)` | `557cf10` |
| F | the dictated-code detector can see Ruby predicate/bang methods and Rust macros | `461a52b` |
| B | the read refusal states the document's extent and a range that fits | `5f7bd86` |
| J | the abort notice is replaced on a retry, never stacked | `e933c57` |
| L | the install route says how to run a one-off command under a project-local install | `7d6ae26` |

**Refuted on measurement or on reading — recorded, not built:**

- **A (split the withheld verdict).** The corpus holds **one** `satisfaction_gap_withheld` event, ever — against 1,521 inspection rounds and 74 caps. #15 says measure prevalence before building a heuristic, and one occurrence is not a systemic problem. The two causes of the cap that produced it were fixed upstream instead (the spill exclusion and the rooted paths), which is where the value was.
- **H (the staleness note was false).** Read against the capture: a fresh gate result appears with no note, and the SAME result reappears with the note on the next call after a write. Line numbers at 0058 (`rates.rb:50`, `test_rates.rb:71`) match the fresh gate, and the note at 0059 refers to writes made after it. The note is correct; the walk agent's reading was not.
- **K (a killed unstick author needs a fallback).** `loop.steer_rescue_skipped` fired with "stream aborted by a guard" — a stream cria itself killed must not become a directive, which is a deliberate rule with its own incident behind it. Silence is the right answer. What was worth fixing in that tail was J.
- **M (label which failing test is the repo's).** cria cannot answer it truthfully with what it holds. The measured case is `test_unknown_zone_rejected` — a REPO test living inside a file the coder also edited — so file-level attribution, the only level cria's write ledger reaches, would have labelled it the coder's own. A wrong label here is exactly the class of false fact the rest of this document is about.
