# Indicators — telemetry for the human, never model context

Indicators are cria's out-of-band notes about what it did this turn: the route, the model, which guards fired, context moves. They are for the **human / harness**, not the model. They are implemented in [`cria/indicators.py`](../cria/indicators.py); the structured record of the same decisions is the [event log](observability.md).

## The invariant

An indicator never enters the model's context and is stripped from the transcript before cria makes its upstream call. Indicators are distinct from steers: a steer is an in-context directive the model is *meant* to see; an indicator is the human-facing notice that it fired. Same event, two audiences, two channels.

## How they travel: the content channel, behind one sentinel

cria talks to the harness over the model-answer pipe and the harness renders whatever text is in the completion, so cria decorates the completion with lines that start with the sentinel `⟦cria⟧` (`indicators.MARKER`). No separate SSE event type exists (an earlier design proposed one; it was never built, because a plain-content harness cannot render it). The harness needs to understand nothing; the same marker is how cria finds and removes its own lines on the way back in.

- **Strip on the way in.** `indicators.strip_history` removes every `⟦cria⟧` line from non-tool messages before the model re-reads them, and the clean reasoning body between a pair of `⟦cria⟧ 💭` fence lines. A tool result is never stripped (it is a tool's own payload and may quote the marker). An UNMATCHED fence removes only the marker lines, never the answer after it. `strip_prose_dropped_marker` is the unconditional net for the one model-facing `⟦prose-dropped⟧` token on a compacted reply. The strip runs at every engagement level and again at the wire (`Upstream._prep`), so no single missed call site can leak a marker (principle 17).
- **Never the word "cria" to the model.** Model-facing markers use `⟦ctx:…⟧`; only the human-facing `⟦cria⟧` notes are stripped.

## What is surfaced

Each family has its own `[indicators]` switch (`enabled` is the master; with it off the stream is a pure passthrough):

| `[indicators]` key | Line |
|---|---|
| `connect` | one banner on the first turn of a session, `⟦cria⟧ cria connected · <model>`, plus the template-compat glyphs (`cria/compat.py`): reports, never gates |
| `route` | `⟦cria⟧ <role> · <model>`, the ongoing "which model answered" banner (after a failover walk the banner names the role and model that ANSWERED, and a note names the roles walked) |
| `metrics` | the `· N tok/s` suffix on the route banner (suppressed under three streamed deltas, where a rate is noise) |
| `assists` | `⟦cria⟧ <note>` guard/assist lines: repetition and rumination guards, "running the repo's checks (…)", truncation warnings, recoveries. Turning it off strips these notes from the completion before it ships |
| `stats` | the terse end-of-turn summary line |
| `status` | a live `⟦cria⟧ <phase>` ticker while cria works (judges, compaction, gates): the first-minutes black box, narrated |
| `reasoning` | forward the model's reasoning on the native Responses reasoning channel (Codex's live "thinking" preamble; transient) |
| `reasoning_transcript` | also fold the reasoning into the message as a fenced `⟦cria⟧ 💭` block so it stays in scrollback (turn `reasoning` off if a client shows it twice) |

At engagement level 0 (pure proxy) cria decorates nothing. The authoritative record of anything an indicator reports is the JSONL event (`failover.walk`, `context.floor`, `indicators.stripped`, …), never the displayed line.

## What the connect banner checks

`cria/compat.py` reads the served model's `/props` once and reports (never gates, principle 19) the two template facts that earned a line after being measured against every ladder model: whether the chat template has a **tools branch** at all, and whether it enforces strict **turn alternation** (shown as handled, 🟡, when the coder role sets `merge_consecutive_turns`). Anything else, including a mismatch between the `model` a harness displays and the model serving, is not reported. A harness learns its context window from its own config, not the server, which is why Codex needs an explicit `model_context_window` ([codex-context-window.md](codex-context-window.md)).

The catalog of the guards behind the notes is [heuristic-assists.md](heuristic-assists.md) and [shephard.md](shephard.md).
