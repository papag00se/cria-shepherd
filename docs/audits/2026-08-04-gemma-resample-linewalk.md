# Line walk — gemma4 re-measure (temp 1.0, plan-off), run ada-handles_gemma4_codex_poff_1785893473

Operator-ordered FULL line walk after two skim-era errors were caught by hand (the
"__spec__.py never existed" claim; the unexplained "unsupported call" replies). Method: every
call 0001–0283 in order at full fidelity — complete reasoning, complete response and tool
arguments, and every NEW prompt line (full prompt on each phase's first appearance, per-call
delta after; deltas include full tool results and recomposed judge evidence). No truncation, no
grep. Notes appended chunk by chunk as read; each note asks "how could this line have fouled
the run?"

Capture: ~/.cria/calls/20260804T183134-019fcf8c-1efb-7143-bae9-b8e0660a48ce

Materialized with `python3 suite/walk.py 20260804T183134 --out <dir>` — the committed
full-fidelity extractor this incident produced (284 calls, 62 chunks, 3,412,452 bytes; zero
truncation). The tool immediately caught what the ad-hoc chunker still missed: one whole call and
every judge-phase THINK block (classifier / research-step / reasoner private reasoning).

## Findings by call

### chunk 01 — calls 0001–0017 (classify, research step, first coder turns, first steer)

- **0001 classifier** — THINK and verdict both sound (`task`/`coding`). Clean.
- **0002 research-step** — the authored step guessed "OpenAPI spec" and "API key auth for
  rate-limit tiering"; its THINK even planned to "ask about an authentication key/token …
  required by their policy". cria's no-guess check caught it and forced a retry. The invention
  texture is visible on the model's second call of the run.
- **0003 research-step retry** — corrected sentence is clean (learning auth requirements is a
  reading goal, not an assertion). Guard worked as designed.
- **0004 coder-s1** — first coder THINK already invents `GET /api/v1/resolve/{handle}` and
  camelCase fields (`resolvedAddress`, `holderAddress`) — not acted on, but the exact shapes it
  will later have to unlearn. Opens with `list_dir` — correct.
- **0005** — reads `pyproject.toml` (doesn't exist). Harmless survey.
- **0006** — THINK states a flat hallucination: "there's already src/ and apps/" — the workspace
  is empty and nothing in context said that. First false fact of the run, and it spends the next
  call chasing `src`.
- **0007 — THE STRUCTURALLY MALFORMED WRITE (cria fault, fixed).** The write_file arguments are
  scrambled beyond JSON repair: content ends with the fused tail `',path:`, one KEY is
  `"/home/jesse/Documents/pyproject.toml<|\"|>,result_type"` (the path AND gemma's native
  tool-syntax quote token `<|"|>` leaked into a JSON key), and it invents a `result_type:
  "file_created"` field — hallucinating the tool's RESPONSE shape into its own call. No usable
  `path` → the call fell through cria's lowering RAW and Codex answered the opaque
  **"unsupported call: write_file"**. Also note the path targets `/home/jesse/Documents` —
  outside the workspace; because the call was never lowered, dirguard never saw it either.
  Fixed this session: writeproxy now refuses missing-path write/edit calls with a plain-cause
  message (cria/prompts/{write,edit}_missing_path.txt, tests in test_writeproxy.py).
- **0008** — the foul lands: the coder reads "unsupported call" as *"I can't edit/create files
  outside the allowed paths … sandboxed environment with restricted filesystem access"*. A false
  belief seeded by an opaque error — exactly what the new refusal text names instead. Its next
  list_dir call (0008→0009) again carries fused junk args (`"name='/home/jesse/Documents'<|\"|>,query":false`)
  — Codex ignored the junk keys and it worked, masking the malformation pattern.
- **0009** — writes pyproject.toml WITH phantom packaging: `poetry-tools==0.19`,
  build-backend `"pudupatch.build; extra == 'pudupatch'"` — invented packages now ON DISK, where
  any later `pip install` walks into them. THINK also inflates scope: "add venv, pytest,
  pydantic …, httpx + HTTP2, ruff" for a task that needs one script, tests, and a README.
- **0010–0016 reasoner (flail steer)** — detector fired correctly (the coder WAS circling).
  The reasoner's inspection is clumsy but bounded: reads a `src/*.py` GLOB (0010), lists the dir
  (0011), reads pyproject (0012), reads `.git` as a file (0013), reads build.py (0014), then
  RE-reads pyproject it already read (0015) — cria's "You have inspected enough. Answer NOW"
  brake fired at 0016 and worked. Two judge-seat fabrications the digest walk never showed, now
  visible in THINK: 0010's reasoning claims "The latest check reports ZERO python tests passing"
  when the prompt said "(no check results for this steer)" — an invented check result; 0013's
  claims ".git (which is not even a dir)". Neither reached the directive, but the same
  fabrication texture sits in the judge seat.
- **0016 directive** — right about the loop (wrong /home write path, phantom build deps, zero
  deliverables), and it does order the phantom-dep revert. But it also prescribes "an async
  resolver that validates via pydantic … expose a cli" — absorbing the CODER's own inflated
  plan (httpx/pydantic/async — none task-required) and handing it back as instruction. The steer
  thereby ENDORSES the dependency scope that later has to install cleanly in the sandbox.
- **0017** — steer delivered. Coder THINK claims "Reverted pyproject … dropping the poetry-tools
  fluff" — **no write happened**; the poisoned pyproject is still on disk verbatim. A false-done
  claim in reasoning. It then fetches `https://api.handle.me/openapi.json` — the right move.
  ("pydipotent" mutation token in THINK: transient temp-1.0 noise, self-corrected.)

### chunk 02 — calls 0018–0023 (spec navigation; TWO cria faults found and fixed)

- **0018** — the spill + outline machinery works beautifully: full spec saved, 33 endpoints and
  exact response shapes (`holder`, `resolved_addresses.ada`, `total_handles`) put in front of the
  model. THINK invents garbage line numbers ("list lines 100593867:248"), and the actual call is
  `start_line=1041, end_line=358` — **INVERTED** (end before start).
  **cria fault #2 of this walk (fixed):** cria silently dropped the end_line (the `end >= start`
  guard fell through to the start-only branch, reading 1041→EOF) and refused THAT as "too large —
  narrow it to a smaller start_line/end_line window" — a misleading cause for a request the coder
  believed was already narrow. 100 inverted ranges across 3 captured sessions. Now refused with
  the true cause (`cria/prompts/inverted_range.txt`, `InvertedRangeTests`).
- **0019** — coder greps the spill file for `"GET /handles/"` — zero hits, exit 0. The literal
  `GET /handles/` exists only in cria's OUTLINE rendering; the raw JSON keys are `"/handles/…"`
  with `"get"` nested inside. The empty-but-successful grep then feeds the false THINK in 0020
  ("the openapi file isn't at ./tmp/read-only/"). cria's `_HTTP_VERB` strip already handles this
  for `find=` — the coder just grepped instead. Model error, seeded by cria's own `GET <path> →`
  outline spelling; noted, no change (the outline wording already says "grep … FROM THAT LIST").
- **0020** — coder tries `ls -F /tmp; grep -r … /tmp` (with mutated flag garbage
  `sort -u07569077-t ':'`) — dirguard denies it with the correct, plain-cause message. Guard ✓.
- **0021** — THINK confabulates history ("must have been from an earlier session … I
  misremembered") — the false belief from 0019's empty grep compounding. Re-fetches with
  `find="GET /handles/"`; cria's verb-strip answers with the real `/handles/…` sections.
- **0021 result — cria fault #3 of this walk (fixed), THE BIG ONE:** the find match was 19,809
  chars; cria windowed it to ~16,000 chars (4,000 est-tokens) and shipped it. Codex re-renders
  every tool output into later prompts through a **10,000-byte middle-cut** — so the slice
  arrived holed: `…1599 tokens truncated…` sits mid-payload, and that cut version rode in
  **84 of this run's 283 prompts** (once in history, cut forever). Corpus-wide: 166 distinct
  harness cuts. The never-truncate principle was being defeated on the far side of the harness.
  Fixed: shared `content_reduce.INLINE_RESULT_MAX_BYTES = 9000`; fetch pages, find windows and
  `READ_INLINE_MAX` (which sat exactly ON the budget at 12,000) all derive from it; bounding is
  by paging/spill, never by dropping (`HarnessHistoryBudgetTests`).
- **0022 reasoner steer** — fired while the coder was actually recovering. The directive is
  half-grounded: "Read /tmp/read-only/…openapi.json with find=…" **fuses two tools** (`find=` is
  a web_fetch argument; read_file has no such thing) and names an absolute `/tmp/read-only/…`
  path (the real one is `./tmp/read-only/…` inside the workspace — the very path shape dirguard
  denied two calls earlier). THINK also invents "The task's worth 100". The coder happened to
  translate it into a sane `web_fetch find=` — but a weaker moment would have re-tripped
  dirguard. Watch for recurrence before proposing an authoring guard.
- **0023** — coder converts the confused steer into `web_fetch find="GET /holders/"` — fine.

### chunk 03 — calls 0024–0031 (the invented-line-range steer poisons the run)

- **0024** — `/holders/{address}` schema lands complete and correct (`total_handles` integer,
  the exact fields). Then THINK derails: "I need to fetch a valid stake key … search for
  top-ranking wallet addresses on Cardano" — the holder address comes FROM the
  `/handles/{handle}` response; a web-ranked wallet is scope drift. Fires the search.
- **0025 search-guard** — correctly rules the query off-target. Its THINK carries hallucinated
  flavor ("GOOSE … whose holders get ranked as 'top wallets'"), but the verdict is right. The
  recommendation, though, is `https://api.handle.me/openapi.json` — a URL the fetched-pages
  ledger right in front of it says was ALREADY fetched. The coder dutifully re-fetches it (0026)
  and burns a call on the repeat-gate denial. Small: the guard's recommendation should prefer a
  NOT-yet-fetched target when the ledger marks it fetched. (The denial re-serves the outline, so
  the cost stayed one call.)
- **0026** — repeat-gate denial ✓ (outline re-served). THINK **fabricates tool history**:
  "grep -n for 'resolved' gives lines 6508, 6791" — no grep ever ran. Reads 6508–6793.
- **0027** — past-EOF read answered truthfully ("has 2,873 lines; 6508 is past the end") — the
  missing-file/empty-file guard working. The recovery grep self-destructs on a mutated token:
  `grep -n "\"type\":" .>./tmp/read-only/api.handle.me_openapi.json' 2>/dev/null` — note that is
  a SHELL REDIRECT AIMED AT THE SPILL FILE; only the unmatched quote (exit 2) kept it from
  clobbering the model's own ground-truth copy. The spill lives inside the workspace, so no
  guard would have stopped it. **Candidate hardening (measure first): write-protect
  ./tmp/read-only spills (mode 0444) so a stray redirect can't destroy fetched evidence.**
- **0028 reasoner — THE POISONING STEER.** Detector fired fairly (fabricated-grep THINK). The
  reasoner held read_file/list_dir and used NEITHER. Its THINK asserts "Read the file at lines
  1745-1803 (the handle/resolved_addresses definition)" — an INVENTED range, never verified; and
  the directive ships it as fact: "Read it at 1745-1803, then build a model from what's actually
  in those lines:". Lines 1745–1803 are actually `/swagger/swagger.yml` and `/mpt-root`. The
  range passes the beyond-EOF citation guard (1803 < 2873) — plausible, unread, wrong.
- **0029** — coder obeys, reads 1745–1803, receives swagger/mpt-root schema.
- **0030** — the poison blooms: THINK decides "I should add it ['verified'] to my resolver so
  the caller knows when MPT checks are degraded" — a feature the task never asked for, planted
  by the steer's wrong window. Re-reads 1796–1803.
- **0031** — drift deepens: "I'll now fetch /health for live stats on sync status before
  designing error handling." Re-fetches openapi.json verbatim (repeat gate will answer).
- **Open finding for prevalence count: judge-seat INVENTED LINE RANGES** — a directive citing
  `file:START-END` for a path the authoring session never read, where the numbers appear nowhere
  in its evidence. Deterministically checkable from the steer session's own tool trace. Count
  across captures before adding a guard (high bar to ADD).

### chunks 04–06 — calls 0032–0039 (line-fishing, the SECOND invented-range steer, first code)

- **0032** — exact-repeat fetch nudge fires correctly ("made this exact call 2 times"). THINK
  invents a new fishing range "1860-2045 … the resolve_handle response's exact fields" — lands
  on /policies and /datum instead. The 0028 steer legitimized fishing by line number; the coder
  is now doing it freely.
- **0033** — /policies + /datum arrive. THINK has the RIGHT realization — "GET /handles/{handle}
  already includes the holder field, so I only need one round trip" (straight from cria's shape
  ledger) — then keeps fishing anyway (1789–2036). **In-run confirmation of the inline-bound
  fix:** this read's result (under the old READ_INLINE_MAX=12000) shows `…386 tokens truncated…`
  in every later prompt — Codex middle-cut a read cria had passed as inline-safe. The new
  9,000-byte shared bound covers exactly this.
- **0034 reasoner — the SECOND invented-range steer.** Its THINK misstates its own evidence
  twice ("an invalid read at 1796–1803 … zero output" — that read SUCCEEDED and returned 8
  lines), then the directive asserts "read … at lines 1789–2045 to get the actual
  resolved_addresses and sibling fields" — while the evidence pane RIGHT ABOVE IT shows what
  1789–2045 actually holds: mpt-root, /health, /policies, /datum. No resolved_addresses. The
  claim contradicts text it was shown. Same shape as 0028: content-at-line-range asserted
  without (or against) ground truth. That is now two poisoning steers of identical shape in one
  run.
- **0035** — coder obeys the steer, re-reads 1789–2045 (it had JUST read it) → repeat nudge.
- **0036** — pivots to code at last: writes `src/client.py` (httpx async). The field names are
  all CORRECT — `holder`, `resolved_addresses.ada`, `total_handles` — lifted straight from
  cria's fetched-shapes ledger. The ledger did its job even through the flailing. THINK invents
  handles "you're01397, gofamaji" (not acted on).
- **0037** — writes `tests/test_wallet.__spec__.py` — THE file the skim-era walk falsely called
  "never existed". Ground truth: created here, a nonsense stub (`async_main` returning
  `asyncio.coroutine`, then `asyncio.run(async_main())` — would TypeError if ever run).
- **0038** — update_plan with off-task items ("setup virtual env … completed", "add pytest and
  pytest[qa]") — plan channel is noise, not deliverables.
- **0039** — write_file with **NO `path` ARGUMENT AT ALL**: `{"content": "[tool.poetry]\ndev-dependencies
  = [ … \"pycodegen==265937e4df5aabceaebe', …"}` — truncated content, phantom package `pycodegen`
  pinned to a hex blob, no path. This is the missing-path malformation the new writeproxy
  refusal now answers with a plain cause (pre-fix it drew "unsupported call: write_file").

### chunk 07 — calls 0040–0051 (the dictated README steer with a FABRICATED wallet address; the gate works)

- **0040 reasoner** — THINK claims false diligence: "I've read all relevant files (pyproject,
  client, both test files) directly" — this authoring session made ZERO tool calls. Its
  directive tells the coder to write the README **and dictates a full Python block** containing
  a fabricated 86-char "wallet" (`1qWvS5Z89t67eEAtF0uCjH4N3K1LpQXStM2aYfAUPz7hBde8iPKEGUMmD36o/4OunHUnmrtbHzJAErIeeT7S5U`)
  — not a Cardano address shape, appears in no evidence. Invented DATA riding inside dictated
  code — a claim class none of the steer guards checks (URL ✓, system path ✓, file:line ✓,
  auth-claim ✓ — but a bare fabricated VALUE sails).
- **0047 steer-code judge** — correctly answers DICTATES. Per the operator's 2026-08-04
  observe-only ruling the steer is logged (`loop.steer_dictated_code`, delivered=true) and
  DELIVERED — working as ruled; this walk is part of that cohort's re-measure. Watch the
  fabricated address's fate downstream.
- **0048** — coder absorbs the steer as "the user's sample async main code" and plans to include
  it. Re-reads client.py (its 2nd read — repeat pressure building).
- **0049 — THE GATE FIRES, and it is excellent**: composed checks catch `tests/test_wallet.py:14
  SyntaxError: unmatched ')'` with cria's counted-fact line ("line 14 on disk … contains 1 '('
  and 2 ')'"), plus both pytest collection errors. Ground truth, exact lines, no judgment.
- **0050–0051** — coder reads the real files (good), diagnoses line 14 correctly in THINK
  (extra paren + phantom `resolved_ur1` field) — then "fixes" client.py by ADDING validation:
  `if not handle_name or not all(c.isalnum() for c in handle_name) or "." not in handle_name:
  raise ValueError("Invalid Handle format")` — **a self-contradiction**: it requires a "." AND
  all-alphanumeric (a "." is not alnum), so EVERY input raises. The resolver is now a landmine
  for goose/papagoose. Model-authored, unprompted by any steer. Watch it detonate.

