# Observability — the cria event log

cria's decisions are legible by design. Every action emits one structured event through a single primitive (`cria/events.py`), to two sinks:

* a **JSONL file** — `<[logging].dir>/cria-YYYYMMDD.jsonl`, the complete record, **never level-filtered**. This is the troubleshooting source of truth: after any run you should be able to reconstruct *exactly why* cria did what it did from the JSONL alone.
* a **console line** (stderr) — a human view, filtered by `[logging].level`.

## The record

One JSON object per line. Common fields:

| field | meaning |
|-------|---------|
| `ts` / `iso` | epoch seconds / ISO-8601 (ms) |
| `level` | `debug` \| `info` \| `warn` \| `error` |
| `kind` | `"<subsystem>.<event>"` — see the catalog |
| `session` | the `X-Cria-Session-Id` (when the harness sends one) |
| `turn` | a per-request id, threaded through every event of that request |
| `msg` | optional human string |
| *rest* | event-specific fields |

## Decisions — the backbone

A **`decision`** event records a fork cria took: `decision` (what was being decided), `choice` (what it picked), and `reason` (why). **Reason is mandatory** — a decision without one is a future debugging session spent guessing. Today's decisions: `engagement` (question/simple/task) and `route` (which role/model).

## Event catalog

Grouped by subsystem; each is a `kind`.

**server** — `server.config` (effective config at startup), `server.start`, `server.stop`.

**request** — `request.recv` (model, stream, n_messages, has_tools), `request.bad` (unparseable body).

**routing** — `route.classify` (a cache hit), `route.classify_error` / `route.classify_unparsed` (the classifier call failed / returned junk → bias fallback), `route.skip` (a chain role was unresolvable), `route.exhausted` (no role resolved); plus the `decision`s `engagement` and `route`.

**upstream** (the model call) — `upstream.request`, `upstream.first_token` (TTFT), `upstream.done` (tokens, tok/s, gen_ms), `upstream.error`.

**claude** (the Claude-CLI provider) — `claude.invoke` (model, resume, cwd), `claude.done` (output_tokens, ms, resumed), `claude.error`.

**indicators** — `indicators.stripped` (how many of cria's own status lines were removed from the inbound history before the model saw them).

**response** — `response.sent`, `response.error` (upstream failed), `response.client_gone` (client disconnected mid-stream).

**http** — `http.access` (debug; the base handler's access line).

## The inspector

`python -m cria.tail` (installed as `cria-tail`) reads the JSONL and renders it — one consistent tool instead of an ad-hoc tailer.

```bash
python -m cria.tail                 # render the newest log in ~/.cria/logs
python -m cria.tail -f              # follow, like tail -f
python -m cria.tail --decisions     # only decisions: what cria chose and why
python -m cria.tail --turn 3f9a1c   # one request/turn, end to end
python -m cria.tail --kind route    # everything routing did
python -m cria.tail --level warn    # warnings and errors only
python -m cria.tail -n 50           # the last 50 matching events
python -m cria.tail --raw | jq .    # matching records as JSONL, for jq
```

Filters compose (`--turn X --kind upstream`), and `--raw` emits the matching records verbatim for piping.

## Per-call capture — EXACTLY what the model sees

The event log records *what cria decided*; the per-call capture records *the literal input the model received*. cria rewrites every request before it reaches the model — frames the current step, applies the context floor (tool-schema bounding + trimming), injects the tool cheatsheet, sets sampling and the reasoning toggle. To see the ground truth of that, turn on capture:

```toml
[logging]
capture_calls = true                 # off by default (verbose: one file per model call)
capture_dir   = "~/.cria/calls"
```

Then every upstream model call writes its **exact final body** — messages (full, untruncated), tools (the *bounded* schema actually sent), all sampling params, and `chat_template_kwargs` (the `enable_thinking` state) — to:

```
~/.cria/calls/<session>/NNNN-<phase>.json      # NNNN = per-session call order
```

`<phase>` labels the role: `classifier`, `planner`, `coder-s<step>`, `critic`, `proxy`. Each file also carries a `stats` block (n_messages / n_tools / token estimate) and the `session` + `turn` ids. A pointer `upstream.dump` event lands in the JSONL, so a capture correlates to the loop events (`loop.item` step=N, `context.floor`, `loop.probe` …) that share its `turn`. To read the coder's inputs across a run in order:

```bash
ls ~/.cria/calls/<session>/*coder* | sort        # every coder call, in call order
cria-tail --kind upstream.dump                    # the pointers + sizes, inline in the log
```

The capture is the request body cria sends. The model's *rendered* prompt (after llama.cpp applies its chat template) is a deterministic function of that body plus the model's fixed template; get it on demand from the server's `POST /apply-template` with the same body.
