# Indicators — telemetry, never model context

> Design note for the port. "Indicators" are out-of-band signals about **what
> Shepherd did this turn** — the chosen route, the model, which guards fired,
> context moves. They are for the **human / harness**, NOT the model.

## The invariant

An indicator must **never enter the model's context**, and must be **trivially
stripped** from any transcript before Shepherd makes its upstream LLM call.

Indicators are *distinct from nudges.* A nudge is an in-context directive the model
is **meant** to see (a STOP block, a forced-diagnosis instruction). An indicator is
the **human-facing notice** that the nudge fired ("Repetition guard fired"). Same
event, two audiences — keep the audiences on separate channels.

## How to surface them (two layers)

1. **Primary — a distinct SSE event type.** Emit `event: shepherd.indicator` with a
   JSON `data` payload (`{kind, route, model, guard, detail}`). Separate channel:
   never in `content`, nothing to strip, the harness renders it however it likes.
2. **Fallback — sentinel-marked, for a plain-content harness.** If a harness can only
   render assistant `content`, prefix each indicator line with a reserved sentinel
   (e.g. `⟦shepherd⟧ …`). Then a single regex (`^⟦shepherd⟧.*$`) strips them on the
   **inbound transcript** before the upstream call — the same inbound-rewrite slot
   the bidirectional massages use (cf. `represent_shell_writes` in codex-local). The
   sentinel must be something the model would never emit and a harness would never
   mangle.

Either way: **Shepherd strips its own indicators on the way in.** If the harness
echoes prior assistant turns back (sentinel form), the inbound pass removes them so
they can't accrete in context or confuse the model.

## The indicators we surface today (from codex-local)

**Identity / routing**
- Chosen **route** + confidence + reason (`RouteDecision`).
- **Model** that served the turn.
- **Failover** — walked the chain (role unresolvable / model down).

**Guards fired** (the human notice; the nudge itself is the in-context directive)
- Repetition guard · Forced-diagnosis guard · Context-reset guard · Rumination guard
- Quality gate · Patch-failed → `write_file` rewrite · Malformed-tool-call recovered

**Context-shaping events**
- Calibrated context budget (learned real-token ratio).
- Compacted older turns / compacted active turn / dropped oldest (last resort).
- Context overflow → re-trimmed and retried.
- Oversized tool output reduced or omitted.

**Massages applied** (silent in codex-local — worth surfacing here)
- Tool-name → `shell` alias · `write_file` → `shell` base64 · leaked tool-call
  recovered · malformed-JSON repaired.

**Stats**
- Local-vs-cloud tokens + savings (the `/stats` data), per session.

**Onboarding / config (one-time, session start)**
- **Model-name mismatch** — Shepherd sees the `model` field the harness sends on
  every request. If it doesn't match the model actually serving (e.g. harness says
  `gpt-5.5`, Shepherd is `ornith-9b`), surface a one-time tip: *"set `model =
  ornith-9b` for an accurate display."* Shepherd can DETECT it (from the request) but
  not FIX it on a config-name-display harness (Codex shows its configured name, not
  the response's) — so it's advisory. (The harness's own promo/announcement banners
  are NOT a channel — they're harness-internal fetches Shepherd can't touch.)
- **Window not reported** — if the harness's context window looks wrong (its gauge
  never moves, or it overflows past where it should), advise configuring the real
  window (the harness learns the window from config, not the server — see CUTOVER
  "Compaction"). The gauge itself goes honest once Shepherd reports real usage + the
  harness has the real window.

## For the port

Pick the channel early — an SSE indicator event is cheap and keeps `content` clean,
so prefer it. Reserve the sentinel + a strip pass for harnesses that only do plain
content. Whatever you choose, the strip-before-upstream pass is mandatory and belongs
next to the inbound transcript rewrites. Catalog of the underlying guards/moves:
[`shephard.md`](shephard.md).
