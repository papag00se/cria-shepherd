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

