# The 24-pair walk — what cria gets wrong, and where it is still shaped like one Python task

Both arms of all 24 battery cells were read call by call: 48 runs, 813 chunks, 1,186 incidents across two passes. Every claim below traces to a verbatim quote in a capture. Method note in `battery-walk.md`.

## 1. "Model own fault" was mostly context

The first pass filed 302 incidents as the model's own mistake. 241 could be re-located in the transcript and were re-read at the call, with the model's reasoning, to find what it was actually looking at.

| attributed cause | count | share |
|---|---:|---:|
| genuinely the model | 90 | 37% |
| cria — tool/denial surface | 58 | 24% |
| cria — an injection | 42 | 17% |
| the task prompt | 39 | 16% |
| the harness | 7 | 3% |
| cria — a judge acting without injecting | 5 | 2% |
| **contextual cause of some kind** | **151** | **63%** |

cria is implicated in 105 of 241 (44%); the task prompts in another
39. Of the contextual causes, 17 carry a Python or ada-handles assumption.

`genuinely-model` at 37% is real and was not inflated away — a hallucinated stdlib API with nothing in the context pointing at it stays the model's. But it is a minority of the bucket, and the bucket was the largest in the walk.

## 2. The fifteen fixable classes

### 1. cria authors the code — steers and judge "proposed fix" dictate implementations cria never compiled
*cria-injection · 10 incidents · carries a language assumption*

A steer or satisfaction-judge verdict arrives as the last, highest-authority text in the window. When it contains a code body, a shell script, a refactor strategy, or a file layout, a weak model stops reading the repo and transcribes the injection — cria becomes the author, and the author is the same weak model with no compiler. Two sub-shapes: (a) literal code (whole files, function bodies, heredocs), (b) prescribed strategy the reasoner never verified is the cause ("bind to port 0 and thread it through", "add tests/main.rs", "replace its contents with a version that..."). Both overwrite a working state the coder had already reached, and both are executed in preference to the model's own correct reading. cria/loop.py:6579 already detects (a) and DELIVERS anyway by operator ruling; nothing detects (b).

Evidence:
- nemotron-elastic/rust-toml-cli 0053 → destroyed the only green build: "Create src/lib.rs that holds pub fn extract_value<'a>(...) -> Option<&'a toml::Value> { ... eprintln!(...); process::exit(1); return None; } ... Perform these four steps now with write_file" — the dictated body returns `current` from an `Option` fn and puts `return None` after `exit(1)`; the coder's four lib.rs writes are attempts to render it.
- nemotron-elastic/rust-toml-cli 0038 → judge "Proposed fix": "cd <ws> && rm -rf src && mkdir -p src/tests && cat > src/main.rs <<'EOF' ... current.get(segment).ok_or_else(|_| {...}) ... EOF" — re-injects the live E0593, writes files by heredoc which the same prompt's tool rules forbid, and uses Python triple-quoted strings in Rust.
- nemotron-elastic/orders-api-py 0129 → "Edit the start_server function in test_api.py so it binds to a random port (use port 0), captures the actual server.server_port, and uses that value for every URL... Perform this edit now with edit_file." — prescribed a refactor for a failure it had not diagnosed (the URLs had swapped format args); the coder abandoned a working fixed-port state.

**Fix.** Make the existing no-code contract binding instead of advisory, and widen it from code to strategy. (1) In cria/loop.py, stop delivering on DICTATES: rather than a reasoner verdict, hold every code-shaped line in a directive to a VERBATIM-QUOTE test cria can run — the line must appear byte-for-byte in a file cria has read or in captured checker output. Quotes survive; author-written lines are stripped and only the prose ships. This is subtractive and needs no per-language knowledge. (2) Apply the same filter to _verdict_nudge's `proposed_fix` (cria/loop.py:7601), which today is gated only by ungrounded_routes — the judge path is how the whole-script dictations reached the coder. (3) Bind steer authors to naming the OBSERVED contradiction and the file, and forbid prescribing a file layout, a directory, or a refactor plan: those are decisions the ecosystem and the coder own, and a steer that names them is asserting a design it did not verify.

### 2. turns that cria swallows — a well-formed action is discarded with no message at all
*cria-tool-surface · 5 incidents*

The model emits a complete tool call inside reasoning_content. cria/massage.py:1122 recovers it only if every named tool is on the menu (_menu_admits); an unknown name, or a missing required arg, returns the completion untouched — no denial, no unknown-tool message, nothing. The model receives an empty turn: it believes it acted, gets no result, and repeats or reasons from memory. Downstream, cria reads the empty turn as the coder FINISHING and fires exec-intent, the gate and the satisfaction judge against a workspace where nothing happened. The model looks like it is stalling while it is in fact producing correct actions cria is eating.

Evidence:
- nemotron-elastic/orders-api-py 0167 raw response: content='', tool_calls=[], finish_reason='stop'; reasoning ends "<tool_call>\n<function=str_replace_editor>\n<parameter=path>\n.../tests/test_api.py\n</parameter>\n<parameter=view_range>\n[110, 140]\n</parameter>\n</function>\n</tool_call>" — no ⟦ctx:denied⟧ anywhere in the following prompt.
- nemotron-elastic/orders-api-py 0178 and 0180: same shape twice in four calls; the walk filed it as "malformed stop-finish output with parameter-tag debris" — it was two complete calls thrown away.
- nemotron-elastic/orders-api-py 0006: same swallow on the FIRST action of the run, and the empty turn pulled the whole completion machinery in at calls 7-12 after only two list_dirs.

**Fix.** Two kernel changes, both making cria honest rather than louder. (1) In cria/massage.py, every refusal path in recover_reasoning_tool_calls must EMIT the refusal it currently only logs (massage.reasoning_call_off_menu / _not_terminal): return the existing malformed_call_refusal to the model naming the tool it tried and the tools that exist — cria already builds the menu, so this is a true fact, not an assist. (2) An assistant turn with empty content and no tool_calls must never satisfy the completion path in cria/loop.py; a bare empty turn is a lost turn, not a finish, and the gate/judge cycle must not run on it.

### 3. the nearest copy wins — stale and model-invented file text sits closer to the generation point than the truth
*cria-injection · 7 incidents*

A weak model resolves "the current file" to whichever rendering of it is nearest the end of the prompt or most repeated. cria supplies three sources of false-nearest text: rejected edit_file payloads left standing verbatim (formatted exactly like a file listing), compaction bullets that replay superseded write_file bodies as prompt-LEADING content, and the edit-recovery echo that pastes the broken body as the last thing before the coder writes. Nothing carries a recency or supersedes marker, so the model cites its own hallucination as an authority and reverts fixes it already landed.

Evidence:
- nemotron-elastic/cart-billing-go 0021: the rejected call-0005 old_string (an invented cart.go with `Item{ID, Name, PricePerUnit}`) stayed in the transcript unmarked; the model wrote "the earlier snippet we saw in the instruction shows the Item struct with ID, Name, PricePerUnit float64... Perhaps the original code is missing; we need to restore that structure."
- nemotron-elastic/orders-api-py 0049: the prompt OPENS with "⟦ctx:compacted⟧ 23 earlier turn(s) were compacted..." whose bullets include a full superseded write_file body for orders/db.py; the model then described two different versions as "current" three sentences apart.
- nemotron-elastic/orders-api-py 0138: 13 copies of `def start_server():` in one window, the two NEAREST (its own mis-copied old_strings) missing the `global` line that is on disk — "But they didn't assign to the global variable `_server_port`... That's a bug."

**Fix.** One rule at prompt assembly, subtractive: exactly one verbatim copy of any file region may be in the window, and it is the newest. (1) Collapse REJECTED tool-call payloads in replayed history to a placeholder ("[rejected edit: old_string did not match <path>]") — model-authored text that never reached disk must never be rendered as file content. (2) Compaction summarises a write as one line naming the path and the fact of the write, never the payload. (3) Older renderings of the same region are replaced with a one-line pointer to the newest. The asymmetry is the bug: today fabrications persist verbatim while verified content is dropped.

### 4. edit_file recovery: refusal over trivia, an anchor that cannot disambiguate, and a forced retype that deletes working code
*cria-tool-surface · 6 incidents*

Three defects compound. (a) The matcher refuses a correct code change when old_string differs only in a comment or whitespace line. (b) The divergence hint quotes a snippet that is not unique in the file and never says WHICH line of the model's copy is foreign or where it really occurs, so a model whose transcription is faithful-to-the-wrong-region cannot see its error and resubmits byte-identically. (c) The escalation clock (cria/editrecovery.py:42-75) is keyed to the PATH and reset by any successful write, so six identical failures never reach ESCALATE_AFTER — and when escalation does fire it orders a whole-file retype, which is the one thing a small model is worst at: the retype silently drops lines outside the region it was asked to fix.

Evidence:
- nemotron-elastic/orders-api-py 0064: a CORRECT fix was thrown away because old_string carried "# Table exists, ensure schema is complete" instead of "# Table exists, ensure we have an index on the customer column" — a comment the model itself had written one call earlier.
- nemotron-elastic/orders-api-py 0173: "⟦ctx:edit⟧ test_api.py — your old_string is not an exact match. Here is the file's real text where yours first differs from it:\n---\n    finally:\n        stop_server()\n\n\nif __name__ == \"__main__\":\n---" — that snippet occurs twice; the model's only wrong line (`# Ensure the server is stopped even if the test fails`) genuinely exists elsewhere in the file, and the hint never says so. Resubmitted byte-identically 3×.
- nemotron-elastic/orders-api-py 0146: "you have failed to edit this file 3 times — you cannot pin its exact current text. STOP editing it... produce the corrected FULL file in a single write_file call" → the retype emitted `# Use a fixed port to avoid random port issues` and dropped `global _server, _server_thread, _server_port`, creating the bug the model then spent 16 calls rediscovering.

**Fix.** In cria/editrecovery.py: (1) anchor the hint — give the divergence LINE NUMBER and state the deletion explicitly ("the line `X` in your copy is not here; it occurs at line N"), because a bare snippet that appears twice cannot disambiguate. (2) Key the escalation counter to the repeated old_string, not the path: a byte-identical resubmission after a mismatch escalates immediately, and a successful write to the file no longer resets it. (3) Retire the unbounded whole-file retype (its own docstring already documents this footgun): escalate to a REGION rewrite of the function that failed to match, and diff the result against disk, rejecting any change outside that region. (4) Delete the coder_system.txt promise "if it can't match, edit_file shows you the file's actual text" unless it is unconditionally true — today it rewards guessing old_string as a way to see the file.

### 5. the compaction briefing invents project state, then cria re-injects it as the model's own verified work
*cria-injection · 5 incidents*

The compactor gets a transcript with reasoning_content stripped (for a reasoning-first model that is nearly everything: 58 of 87 assistant turns rendered as the bare string "assistant: "), the ORIGINAL task prompt in full, and an explicit ban on tools. The only coherent narrative left in its input is the task's to-do list, so it paraphrases the request as "what remains", inventing details and framework names that appear nowhere in its input. cria then wraps that output in "⟦ctx:continuation⟧ ... this is YOUR OWN prior work", converting a hallucination into the highest-authority statement of project state — and the coder reads its own summary as user intent.

Evidence:
- nemotron-elastic/orders-api-py 0182 briefing: "a placeholder `GET /customers/<name>/orders` route that currently returns an empty list... The schema in `db.py` lacks a `status` column" — measured: grep 'placeholder' in the compactor's input = 0, while the implemented route and `status TEXT NOT NULL DEFAULT 'pending'` are both present in that same input.
- nemotron-elastic/orders-api-py 0195 briefing: "orders/app.py – the Flask application that exposes the API routes" — grep 'Flask' in the compactor input = 0 (stdlib-only project); and "tests that currently only call the database directly" is a verbatim paraphrase of the task prompt's opening line.
- nemotron-elastic/orders-api-py 0147 briefing: "causing a `ConnectionRefusedError` when the test tries to connect to `127.0.0.1:8080`" — the recorded traceback says host = '127.0.0.1:1'; at 0150 the coder read its own summary as external intent: "The user wants to modify start_server to bind to port 0".

**Fix.** Stop asking a blind model for facts cria already holds. (1) Build the briefing's "what is done / what remains" from ground truth — the file tree and the last gate result — and let the summarizer supply narrative only; cria owns disk, so this removes the invention surface rather than adding a checker. (2) Validate any error the briefing quotes against the recorded last gate output and DROP the clause when they disagree (never re-inject an unchecked failure cause under a header asserting it is established work). (3) Either withhold the original task statement from the compaction input (the coder receives it separately every turn) or label it "the request as first stated — NOT current state"; it is the text the summarizer plagiarizes. (4) Do not feed the compactor a transcript with the channel this model thinks in removed.

### 6. guards that fire on the wrong failure mode — and on each other
*cria-injection · 6 incidents*

cria's anti-loop guards are written for one situation (deliberation loops, genuinely-informative repeats) and are delivered unconditionally. Against a different failure mode they forbid the exact recovery step: the repetition guard tells a model that a FAILED call "has told you everything it can", leaving reasoning-from-memory as the only permitted move; it fires on a re-read that another cria mechanism just ordered; and the rumination / output-loop guard's "do not re-examine" is catastrophic when the loop is caused by a stale mental copy of a file, because the simplest correct next step IS a read. The guards also cut generation at the moment the model turns toward the right action.

Evidence:
- nemotron-elastic/orders-api-py 0034, after view_image returned "image content omitted because it could not be processed": "[you have now made this exact call 2 times and it returned the exact same result every time... Repeating it again will return that same result: it has told you everything it can. Read what it already returned above, or take a DIFFERENT action.]" → the model reconstructed db.py from memory, got it backwards, and called task_complete with all tests red.
- nemotron-elastic/orders-api-py 0064: an ⟦ctx:edit⟧ refusal ordered "Use THESE lines verbatim... " (requiring a re-read); the model complied; the repetition guard then counted that compliant read as redundant and forbade another — the model produced a theory refuted by the file on screen and a no-op edit whose old_string and new_string are identical.
- nemotron-elastic/orders-api-py 0175: "[OUTPUT LOOP] ... Do not re-examine and do not restart from scratch. Take the simplest concrete next step you already know, and take it NOW as a single tool call." → it re-sent the byte-identical stale old_string, because the thing it "already knew" was the frozen copy.

**Fix.** Condition each guard on the last failure's mode, and delete the sentences that are false. (1) cria/prompts/trim_repeat_collapsed.txt: a call that returned an error or an empty payload is not a call that "told you everything it can" — for that case say the call failed and name the tool that answers the question; never tell a model to "read what it already returned" when nothing was returned. (2) Exempt from the repetition guard any read that a cria message in the preceding turn demanded — a guard must not punish the recovery another guard ordered. (3) cria/prompts/rumination_guard.txt and its output-loop twin: drop the absolute "do not re-examine"; when the preceding failure was an edit-anchor mismatch, the simplest next step is a read, and a blanket ban on reading is what freezes the stale copy in place.

### 7. the checks block points at the raise site and then restates itself lossily
*cria-injection · 6 incidents*

cria/probegate.py:247 appends "the flagged line on disk — line N: `...`" to every `path:LINE` finding under a header ordering the coder to "resolve exactly what it names". That is correct for a LINTER (the flagged line is the defect) and actively misleading for a RUNTIME EXCEPTION, where the flagged line is where execution died, not where the bug is — so cria's own annotation aims the model at correct code. Compounding it: the traceback is mid-elided exactly where the frame locals live, the same diagnostic is pasted once per command (making a compiler's SUGGESTED line typographically identical to a file line), and a lossy condensed rollup is placed AFTER the lossless block, where a model reads position as recency.

Evidence:
- nemotron-elastic/orders-api-py 0093/0116: "the flagged line on disk — line 136: `with urllib.request.urlopen(req_get) as resp:`" while the defect is two lines above — `url="http://127.0.0.1:%d/orders/%d" % (bob_order_id, _server_port)` — swapped format args producing host '127.0.0.1:1'. The same prompt elided "…777 tokens truncated…" over the frame that showed it. The coder spent four passes hunting a phantom port-1 binding.
- nemotron-elastic/rust-toml-cli 0021-0022: rustc's "13 | fn extract_value(value: &TomlValue..." and its "help: consider introducing a named lifetime parameter | 13 | fn extract_value<'a>(...)" pasted 4× in identical gutter format → "We did `read_file` and saw the content. It shows: fn extract_value<'a>... So it does have `'a`."
- nemotron-elastic/rust-toml-cli 0078: last text before the turn was the condensed rollup "• src/lib.rs:30: mismatched types (+1 more)", dropping the compiler's `help: try wrapping the expression in Some` that was present in full upstream → the model theorised that `--no-deps` (a flag visible only because cria prints its own command line) was breaking type resolution.

**Fix.** Make the gate say less and never restate. (1) In probegate, suppress the "flagged line on disk" annotation for exception-class findings — a raise site is not a defect site, and an annotation cria cannot justify is a false pointer in cria's own voice. (2) Never elide inside a traceback; the elided region is where the decisive values live. (3) Show a diagnostic once and list the commands that produced it, and never paste a checker's SUGGESTED line in the same format as a file line without labelling it. (4) Drop the condensed rollup whenever the raw block is already in the prompt — a lossy restatement placed after a lossless one is read as the newer, authoritative version. (5) Remove the "same result as a later check below" phrasing, which explicitly teaches the model that position does not imply recency, and give check blocks a monotonic marker so exactly one is current.

### 8. denials that name a category instead of a legal next move
*cria-tool-surface · 6 incidents · carries a language assumption*

A refusal is the model's only teacher about the boundary it hit. cria's refusals state the category ("outside the working directory", "could not be processed") and either give no remedy or give one that cannot be executed. The model concludes the requirement itself is impossible and invents — which is exactly what it did. A remedy phrased for one ecosystem's layout ("use a path within the project") is a dead end for any ecosystem that installs dependencies outside the project.

Evidence:
- gemma4/shipping-rates-rb 0073: "⟦ctx:denied⟧ Writing/reading outside the working directory is not permitted here... The path '/home/jesse/.local/share/gem/ruby/3.2.0' is outside it; use a path within the project instead." — that path is the installed `countries` gem, the only offline source of the EU list. The model: "I'll just hardcode them for now and if they complain, I will say I couldn't find an automated way" → a hand-rolled 27-country list with SV in and CZ out.
- nemotron-elastic/orders-api-py 0033: view_image on db.py returned only "image content omitted because it could not be processed" — it never says the file is not an image, never says the tool takes only images, never names read_file; the model repeated the call, and cria's own steer recap echoed the failed call back as an ordinary action.
- nemotron-elastic/rust-toml-cli 0071-0077: write-path denial example "Re-send write_file with the full path INCLUDING the filename you want, e.g. `<that folder>/your_file.py`" — a .py example in a Rust workspace, alongside steers prescribing a tests/ layout; the model created tests/Cargo.toml and `use super::extract_value;`.

**Fix.** Hold every refusal to the same truth bar as any other cria statement: say what is actually wrong in the world's terms and, if a legal route exists, name it — otherwise say only what is forbidden and stop. Concretely: (1) cria/dirguard.py's read-side denial must not prescribe "a path within the project" for a read that lands in a language package directory — under external_dir_permission=read, allow the read; that is the level's entire purpose. (2) A tool must refuse on what it actually検 detects ("<path> is not an image — read_file reads source files") rather than on a downstream processing failure, and a tool that cannot succeed in this workspace should not be on the menu at all. (3) Derive every example filename in a denial from the path actually being written; a hardcoded extension is cria asserting an ecosystem.

### 9. steers that assert facts about the repo cria never read
*cria-injection · 3 incidents*

The steer author names a symbol, a file, or an absence without resolving it against disk — and cria has disk. A weak model always believes cria's assertion over its own reading: told a function lives in a file where it does not exist, it invents a plausible one; told a feature is missing that is implemented forty lines away in its own prompt, it re-implements it. This is doctrine 5b (a false fact with no trace) inside the mechanism whose whole purpose is grounding. cria already enforces this class for phantom PATHS and false LINE citations — the enforcement simply stops short of symbols and existence claims.

Evidence:
- nemotron-elastic/orders-api-py 0085: "...and change start_server to bind to port 0 then store the returned port in _server_port before calling db.init()." — start_server is not in orders/app.py; it lives in tests/test_api.py. The model invented a Flask app to satisfy it: "Probably the route is defined like: @app.route('/customers/<name>/orders'...)" in a stdlib-only repo.
- nemotron-elastic/orders-api-py 0145: "The missing feature is the **GET /customers/<name>/orders** endpoint. Do this now: 1. Read orders/app.py... 2. Add a route that calls db.all_orders_for_customer(name)" — refuted at line 834 of that same prompt: `CUSTOMER_RE = re.compile(r"^/customers/([^/]+)/orders$")` with a working handler.
- gemma4/shipping-rates-rb 0080: "use the `countries` gem to dynamically determine EU member states, for example by checking if a country belongs to the European Union or using its respective membership status provided by the gem" — true but unactionable; the coder had already disproved `Countries::EU` and been denied the gem source, so a remedy in vague prose read as confirmation that no remedy exists.

**Fix.** Extend the existing steer enforcement in cria/loop.py (the _steer_phantom_path / _false_line_citation family) with two more exact checks, both subtractive: (1) SYMBOL RESOLUTION — any identifier the steer binds to a named file must be found in that file, or the steer is dropped (safe null), never reworded. (2) EXISTENCE CLAIMS — any "missing / absent / not implemented" assertion must be checked against the tree before it ships. And where a steer would prescribe using a specific library facility, require it to name a symbol verified on disk or say only what is wrong; prescribing a remedy in prose after the coder has already disproved the obvious spelling teaches the model the requirement is impossible.

### 10. task prompts that assert world-facts the model cannot check, or refer to things by bare reference
*task-prompt-ambiguity · 4 incidents · carries a language assumption*

In the assists-off arm the prompt is the entire context. Three shapes derail a weak model: a false or unverifiable claim about the outside world (which in an offline sandbox becomes a pure recall test), a clause that simultaneously blocks the workable alternative, and a bare referential phrase with no anchor on disk ("the current three", "the subtotal", "grep a customer's order") that the model resolves against whatever else is in the window. cria's coder system prompt then amplifies it: COMPREHENSIVE / VALIDATE / "keep working until complete" with no legal way to close an open question, so the model loops instead of choosing.

Evidence:
- nemotron-elastic/cart-billing-go 0018, prompt: "Use whatever the Go ecosystem standardises on for decimal money rather than hand-rolling it." — no such standard exists; the model invented `github.com/stephane-berdouchez/go-money` ("That is a third-party package but is standard for decimal money in Go"), and used the same clause to reject math/big integer cents twice: "But the instruction says 'use whatever the Go ecosystem standardises on'."
- gemma4/cart-billing-go 0033/0035: two ~8,200-token rumination passes quoting the prompt's own gaps — "Usually 'subtotal' means before discounts. But in many contexts, it might mean after discounts." ... "'Support needs to be able to grep a customer's order out of the logs' ... The prompt doesn't say I should add a new field for ID" — the log cannot identify a customer because Cart has no customer field.
- nemotron-elastic/cart-billing-go 0018 (discounts): "keeping the current three as the file's contents" names none of the three; with a fabricated trio also in the window the model wrote SUMMER25/WINTER10/EARTHDAY instead of WELCOME10/SUMMER25/VIP50.

**Fix.** Two things, neither a per-task pin. (1) Sweep the suite prompts for the two shapes and fix them at the source: replace any assertion about the outside world the model cannot verify offline with the requirement actually wanted ("use a decimal or integer-cents representation instead of float64"), and replace every bare referent with something checkable against disk ("the three codes currently hard-coded in cart.go"). A prompt is context, and an unverifiable premise is the same defect class as a cria false fact. (2) In cria/prompts/coder_system.txt, the exhaustiveness rules currently have no discharge: either soften COMPREHENSIVE/VALIDATE so they do not demand resolution of the unresolvable, or add one line permitting the model to pick a reading, state it once, and not revisit it. Today it is told to be exhaustive and forbidden to stop, which is a loop with no exit.

### 11. the gate mutates the workspace it then reports on as GROUND TRUTH
*cria-injection · 1 incidents*

The check gate runs the repo's tests against the live workspace. When those tests write state (a database file, a fixture, an output artifact), each gate invocation leaves the state behind, so the NEXT gate reports a failure that cria itself manufactured — presented to the coder under the strongest possible header. The coder cannot reconcile it with anything it did, and the same injection forbids the accommodation ("changing the test so it stops asking is not a fix"), so it loops until a guard cuts it.

Evidence:
- nemotron-elastic/orders-api-py 0108: "[GROUND TRUTH — the repo's own checks fail] ... AssertionError: assert 6 == 1\nE  +  where 6 = len([{'customer': 'alice', 'id': 1...}, {'id': 3...}, {'id': 9...}, {'id': 11...}])" — consecutive odd ids: one alice row and one bob row per gate run, accumulating in the workspace's orders.db.
- nemotron-elastic/orders-api-py 0108 coder, ~15× verbatim: "Actually, we can see from the previous test run that the test was passing, which means that the DB file was properly cleaned... But the failure we saw earlier was because the test was expecting exactly one order, but was receiving six." — an unresolvable bind, ended by the rumination detector with no output.

**Fix.** Run the check gate so it cannot leave state behind: execute against a pristine copy of the workspace, or snapshot the tree before the run and restore anything the run created, before any result is presented to the coder. This is shape-general — any test in any language that writes a file has it — and it is a correctness fix to cria's own ground truth, not an assist. A number that grows by one per gate invocation must never be printed under a header that calls it ground truth.

### 12. an escape hatch whose only gate is the model's self-report
*cria-injection · 1 incidents*

The standing checks header carries a clause permitting the coder to change a test when its PREMISE is factually wrong and the coder "has CHECKED". A weak model reads a failing assertion dump as "the outside world I checked". The clause is the one sentence in the block that authorises weakening a test, so a cornered model finds it, quotes it, and uses it — including on an assertion that was passing in the same prompt. cria cannot verify the self-report, so the gate is decorative.

Evidence:
- cria/prompts/block_nudge_preamble.txt and steer_checks_repeat.txt, verbatim: "The ONE exception is a test whose PREMISE is factually wrong — it asserts something about the outside world that you have CHECKED and found untrue. In that case say in one line what you checked and what it actually returned, then correct the test to match reality."
- nemotron-elastic/orders-api-py 0105 coder: "So we need to check the test's premise: it asserts len(result[\"orders\"]) == 1. The failure shows len(result[\"orders\"]) == 6. So the premise that there should be exactly one order is false." — it ran no check; the count came from the assertion dump, and that assertion was passing (1 failed, 3 passed).

**Fix.** Remove the clause. It is an assist whose precondition cria cannot check, in the same prompt as the rule it undoes — the highest-risk shape there is. If the capability is genuinely needed later, bind it to evidence cria already holds: it may fire only when cria can point at a real command in the transcript whose recorded output contradicts the assertion. Saying less is the fix; the base rule ("fix what the test caught") is complete on its own.

### 13. the host repo's own doctrine leaks into the task workspace as first-class instruction
*cria-injection · 1 incidents*

cria's preamble reframer (cria/loop.py:4325, prompts/preamble_instructions.txt) re-presents whatever project instructions the harness supplies as "Project instructions (from the repo — follow these)", and replays them in every steer recap as "[01] the task/context said: ...". In the suite, that surfaced cria-shepherd's own development doctrine inside an unrelated /tmp workspace containing no such file. A rule written for a long-lived repo — never patch around a problem, always widen the fix — is precisely the wrong instruction for a weak model that has just formed a wrong theory: it converts a bad one-line guess into a destructive rewrite.

Evidence:
- nemotron-elastic/orders-api-py 0045, injected: "Project instructions (from the repo — follow these):\n# AGENTS\n\n## One rule to rule them all:\nMitigations, fallbacks, and band-aids are strictly prohibited. There is an upstream fix. Find it."
- nemotron-elastic/orders-api-py 0045 coder: "But the instruction says 'Mitigations, fallbacks, and band-aids are strictly prohibited... Find it.' So we should find the upstream fix... We'll change the signature of init to accept a path parameter, and remove the global DB_PATH usage." It overrode its own caution — "the instruction says we should not make unnecessary changes; but this is necessary" — and emitted `def create_order(customer, item, quantity, unit_price, status='pending', path):`, breaking imports and syntax.

**Fix.** Relay project instructions only when they belong to the workspace under test: cria knows the workspace path, so require the relayed text to be present in an instructions file inside it, and drop it otherwise (silence over noise). This is one check at the single reframe chokepoint, not a per-task exclusion, and it removes a whole category of foreign authority — any operator doctrine, from any repo, that a weak model will read as a mandate about the code in front of it.

### 14. reasoning is erased between turns while fabrications survive
*cria-injection · 2 incidents*

cria replays a prior assistant turn's thinking as an empty `<think></think>` while keeping the tool call that followed it. Every conclusion the model reached but did not immediately encode in an action is deleted, so it re-derives the same diagnosis, re-reads the same files, and trips the repetition and rumination guards — the recorded "found it then lost it" pattern. The asymmetry is what makes it lethal: rejected, model-invented file text persists verbatim in the same window where a verified diagnosis is dropped.

Evidence:
- nemotron-elastic/cart-billing-go 0020 (correct, then gone): "they do int(taxed*100)/100 which truncates rather than rounding properly... The fix would be to round properly: use math.Round(taxed*100)/100." — at 0021 that turn is replayed as `<|im_start|>assistant\n<think></think>\n<tool_call>...` and the model is back to "Perhaps the original code is missing; we need to restore that structure."
- nemotron-elastic/orders-api-py 0120 (same erasure at compaction scale): 58 of 87 assistant turns in the compactor's input are the bare string "assistant: " — the coder's conclusions ("Already present / Already done / Already using") appear zero times, so the briefing reconstructed "what remains" from the task prompt.

**Fix.** Fix the asymmetry from the destructive side first: stop replaying an empty `<think></think>` shell (a turn rendered as having thought nothing is a false statement about the model's own history), and collapse rejected tool-call payloads as in the stale-text class — so the window no longer preserves inventions while discarding findings. Where a turn reached a concrete diagnosis and did not act on it, the durable-facts anchor cria already maintains is the right home for one line of it; that is an existing mechanism reused, not a new assist.

### 15. tool surface that makes the wrong move the only reachable one
*cria-tool-surface · 3 incidents*

A tool whose result omits the payload the next documented step requires forces the model to manufacture it. web_search returns a spill-file pointer and zero URLs, while the same system prompt says research means `web_fetch <url>` and also says "DO NOT GUESS URLs" — the surface forbids the guess and makes it the only available action. The same shape appears as menu entries that cannot succeed in this workspace: they are pure attractor surface for a model matching a verb in its plan to a tool name.

Evidence:
- gemma4/shipping-rates-rb 0040, the entire tool result: "web_search \"ruby countries gem EU members documentation\" — results saved to ./tmp/read-only/search-....txt (each result is title / url / description). They are NOT inlined here (search snippets are mostly noise)." — zero URLs. The response has no reasoning and 32 completion tokens: straight to web_fetch of an invented GitHub URL → 404. Across 31 chunks the coder never opened either search spill, while it did grep the web_fetch spill successfully.
- nemotron-elastic/orders-api-py 0033: plan says "First, view current db.py" → view_image(orders/db.py); the menu entry reads "view_image — attach a local image so you can see it", and the workspace has no images at all.
- nemotron-elastic/orders-api-py 0006: an empty turn (no content, no tool call) after two list_dirs was read as the coder finishing, launching exec-intent, the gate and the satisfaction judge against a workspace where nothing had been written.

**Fix.** A tool result must carry the one thing the next step needs. Inline the top N result titles and URLs in the web_search result (a URL is the payload, not noise) and keep the spill for the descriptions — this makes the result honest rather than adding an assist. Build the curated menu from what this workspace can actually support, dropping entries that can only fail (an image tool with no images). And never let an empty assistant turn reach the completion path.

## 3. Language bias in the assists — 47 findings, 30 costing points now

Full list with verified file:line in `docs/audits/battery-language-bias.md`.
