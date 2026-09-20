#!/usr/bin/env python3
"""Emit a captured run for a FULL line walk — every call, every line, zero truncation.

Why this exists: a walk done through an ad-hoc digest script silently cut reasoning at a few
hundred characters and tool arguments shorter still, and two real defects (a file the run DID
create, and the harness's "unsupported call" replies) were invisible in the cut. The walk doctrine
(docs/goals/regression-goal.md) says "read EVERY call in order — no grep, no sampling"; this tool is the
one permitted way to materialize a capture for that reading, and it NEVER truncates content.

For each call NNNN-<phase> in the capture directory it prints:

  CALL NNNN [phase]
  --- PROMPT ---            the full prompt the FIRST time each phase appears; after that, only
                            the suffix beyond the byte-identical common prefix with the previous
                            prompt of the SAME phase (nothing is lost: the omitted bytes were
                            already printed verbatim). When a prompt is recomposed — shorter than
                            or diverging from its predecessor — that is flagged with the char
                            count and, by default, the divergent remainder is printed IN FULL.
                            --full-prompts disables prefix-dedup entirely.
  --- THINK ---             the model's complete reasoning_content, unabridged.
  --- SAY ---               the complete assistant text, unabridged.
  --- TOOL CALL <name> ---  the complete raw argument string of every tool call, unabridged.
  [finish: <reason>]

Output goes to stdout, or to numbered chunk files with --out (default ~64 KB AND ~1800 lines per
chunk so a reader can take the run in order without any single file being unloadable). Bytes alone
were not enough: a chunk of many short lines came to 3,318 lines, a reader capped at 2,000 read the
head and moved on, and 2,406 lines went unwalked without anything saying so.

    python3 suite/walk.py ~/.cria/calls/<session>            # whole run to stdout
    python3 suite/walk.py <session-name> --out /tmp/lw       # chunked into /tmp/lw/chunkNN.txt
    python3 suite/walk.py <session-name> --full-prompts      # no prefix-dedup at all

There is deliberately NO flag to shorten, sample, or filter content. If a walk needs less than
this, it is not a walk.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

CALLS_ROOT = Path.home() / ".cria" / "calls"
CHUNK_BYTES_DEFAULT = 64_000
CHUNK_LINES_DEFAULT = 1_800   # under a 2,000-line read cap, with room for the reader's own framing
# Measured, not theoretical: a prior multi-agent walk on these same Codex-class walkers hit repeated
# "remote compaction capacity error" and only recovered once each reader's segment was cut under
# ~300 kB. A walk that lets its material compact before findings are recorded is a summarized skim,
# not a walk. So we batch chunks into segments below that measured ceiling, one fresh reader each.
#
# That ceiling is a property of the READER model that consumes the segments, not of this tool. The
# default below suits a large-context (>=~200k-token) reader; a smaller reader needs a smaller
# budget or it overflows immediately — the exact failure this prevents. Derive it from the reader's
# window with --reader-context-tokens, or set --segment-bytes outright.
SEGMENT_BYTES_DEFAULT = 250_000
# A segment must fit the reader with room for its system prompt, reasoning, and finding write, and
# stay under the provider's compaction trigger. The fraction and chars-per-token below reproduce the
# one measured point (272k-token reader -> ~285 kB, matching the observed <300 kB safe ceiling) and
# stay conservative for small readers (48k-token reader -> ~50 kB). chars-per-token is deliberately
# low so token count is over-, never under-, estimated.
READER_WINDOW_FRACTION = 0.35
CONSERVATIVE_CHARS_PER_TOKEN = 3.0
_CALL_RE = re.compile(r"^(\d{4})-(.+)\.json$")


def budget_for_reader(context_tokens, fraction=READER_WINDOW_FRACTION,
                      chars_per_token=CONSERVATIVE_CHARS_PER_TOKEN):
    """A compaction-safe segment byte budget for a reader with the given token window."""
    if context_tokens <= 0:
        raise ValueError("context_tokens must be positive")
    return max(1, int(context_tokens * fraction * chars_per_token))


def group_by_budget(sizes, budget):
    """Contiguous index groups whose summed sizes each stay <= budget, preserving order.

    A single item larger than the budget becomes its own group (it cannot be split without
    cutting a call, which is worse than one long segment) and is left for the caller to flag.
    Never reorders: a walk is chronological, so segment K must precede segment K+1.
    """
    if budget <= 0:
        raise ValueError("budget must be positive")
    groups, cur, cur_sz = [], [], 0
    for i, s in enumerate(sizes):
        if cur and cur_sz + s > budget:
            groups.append(cur)
            cur, cur_sz = [], 0
        cur.append(i)
        cur_sz += s
        if len(cur) == 1 and cur_sz > budget:
            groups.append(cur)
            cur, cur_sz = [], 0
    if cur:
        groups.append(cur)
    return groups


def write_assignments(outdir, chunk_names, chunk_sizes, budget, findings_dir, label):
    """Batch already-written chunk files into compaction-safe segments and emit the plan.

    Writes assignments.json (machine-readable), WALK-PLAN.md (coordinator protocol), and one
    empty finding-file stub per segment (never overwriting an existing one, so a reader's work
    is preserved across reruns). Returns the segment list.
    """
    findings_dir = Path(findings_dir)
    findings_dir.mkdir(parents=True, exist_ok=True)
    groups = group_by_budget(chunk_sizes, budget)
    width = max(2, len(str(len(groups))))
    segments = []
    for idx, group in enumerate(groups, 1):
        names = [chunk_names[i] for i in group]
        seg_bytes = sum(chunk_sizes[i] for i in group)
        finding = findings_dir / f"seg-{idx:0{width}d}.md"
        segments.append({
            "index": idx,
            "chunks": names,
            "bytes": seg_bytes,
            "oversized": len(group) == 1 and seg_bytes > budget,
            "finding_file": str(finding),
        })
        if not finding.exists():
            head = f"# Walk findings — {label or outdir.name} — segment {idx:0{width}d}\n\n"
            head += f"Chunks: {', '.join(names)}\n\n"
            head += ("For each observation record: chunk + CALL number -> the context/event cria "
                     "produced -> the coder reasoning/action it caused -> the disk/check consequence. "
                     "Cite exact artifacts. A lead is not a finding until verified against the capture.\n")
            finding.write_text(head)
    manifest = {
        "capture": str(outdir),
        "label": label,
        "segment_bytes_budget": budget,
        "chunks_total": len(chunk_names),
        "segments": segments,
    }
    (outdir / "assignments.json").write_text(json.dumps(manifest, indent=2) + "\n")
    plan = [
        f"# Walk plan — {label or outdir.name}",
        "",
        f"{len(chunk_names)} chunks batched into {len(segments)} compaction-safe segments "
        f"(<= {budget:,} bytes each). Segments are self-contained (prompts are not deduped), so a "
        "fresh reader can take any one segment without having read an earlier one.",
        "",
        "## Protocol (the failure this prevents: one reader handed the whole capture, its context "
        "fills, it compacts mid-walk, and the walk silently becomes a summarized skim)",
        "",
        "1. One FRESH reader per segment. Never continue a reader from memory onto a second segment "
        "— a continued reader is exactly what compacts. Assign the next unstarted segment to a new reader.",
        "2. The reader reads every line of its segment's chunks in order and writes its finding file "
        "(context -> action -> consequence, citing chunk + CALL). The finding file is the unit of progress, not the reader's memory.",
        "3. Before assigning segment K+1, verify segment K's finding file exists and cites real chunks/calls.",
        "4. The walk is complete only when every segment has a verified finding file.",
        "",
        "## Segments",
        "",
    ]
    for seg in segments:
        flag = "  ** OVERSIZED: one call exceeds the budget — page it, read in parts **" if seg["oversized"] else ""
        plan.append(f"- seg-{seg['index']:0{width}d}: {', '.join(seg['chunks'])}  "
                    f"({seg['bytes']:,} bytes) -> {seg['finding_file']}{flag}")
    (outdir / "WALK-PLAN.md").write_text("\n".join(plan) + "\n")
    return segments


def resolve_capture(arg: str) -> Path:
    p = Path(os.path.expanduser(arg))
    if p.is_dir():
        return p
    cand = CALLS_ROOT / arg
    if cand.is_dir():
        return cand
    matches = sorted(d for d in CALLS_ROOT.iterdir() if d.is_dir() and arg in d.name)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"no capture directory matches {arg!r} under {CALLS_ROOT}")
    sys.exit(f"{arg!r} is ambiguous under {CALLS_ROOT}: " + ", ".join(d.name for d in matches))


def list_calls(cap: Path):
    """(number, phase, stem) for every captured call, in call order."""
    out = []
    for f in sorted(cap.iterdir()):
        m = _CALL_RE.match(f.name)
        if m and not f.name.endswith((".response.json",)):
            out.append((m.group(1), m.group(2), f.with_suffix("")))
    return out


def emit_call(num: str, phase: str, stem: Path, prev_prompts: dict, full_prompts: bool):
    """Render one call as text. prev_prompts maps phase -> previous full prompt text."""
    lines = []
    lines.append("=" * 90)
    lines.append(f"CALL {num} [{phase}]")
    lines.append("=" * 90)

    prompt_file = stem.parent / f"{num}-{phase}.prompt.txt"
    prompt = prompt_file.read_text(errors="replace") if prompt_file.exists() else ""
    prev = prev_prompts.get(phase)
    if full_prompts or prev is None:
        tag = "" if full_prompts else f" (FULL, first {phase})"
        lines.append(f"--- PROMPT{tag} ---")
        lines.append(prompt.rstrip("\n"))
    else:
        i = 0
        limit = min(len(prev), len(prompt))
        while i < limit and prev[i] == prompt[i]:
            i += 1
        if len(prompt) < len(prev):
            lines.append(f"--- PROMPT Δ [prompt SHRANK by {len(prev) - len(prompt)} chars — recomposed] ---")
        else:
            lines.append("--- PROMPT Δ ---")
        lines.append(prompt[i:].rstrip("\n"))
    prev_prompts[phase] = prompt

    resp_file = stem.parent / f"{num}-{phase}.response.json"
    if resp_file.exists():
        resp = json.loads(resp_file.read_text(errors="replace"))
        for choice in resp.get("choices", []):
            msg = choice.get("message", {})
            think = (msg.get("reasoning_content") or "").rstrip("\n")
            if think:
                lines.append("--- THINK (full) ---")
                lines.append(think)
            say = (msg.get("content") or "").rstrip("\n")
            if say:
                lines.append("--- SAY (full) ---")
                lines.append(say)
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                lines.append(f"--- TOOL CALL {fn.get('name', '?')} (full args) ---")
                lines.append(fn.get("arguments", ""))
            lines.append(f"[finish: {choice.get('finish_reason')}]")
    else:
        lines.append("[no response captured]")
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("capture", help="capture dir path, session name, or unique fragment of one")
    ap.add_argument("--out", help="write numbered chunk files into this directory instead of stdout")
    ap.add_argument("--chunk-bytes", type=int, default=CHUNK_BYTES_DEFAULT,
                    help=f"target size per chunk file with --out (default {CHUNK_BYTES_DEFAULT})")
    ap.add_argument("--chunk-lines", type=int, default=CHUNK_LINES_DEFAULT,
                    help=f"target lines per chunk file with --out (default {CHUNK_LINES_DEFAULT})")
    ap.add_argument("--full-prompts", action="store_true",
                    help="print every prompt whole; no common-prefix dedup")
    ap.add_argument("--segment-bytes", type=int, default=0,
                    help="with --out, batch chunks into compaction-safe segments and emit "
                         f"assignments.json + WALK-PLAN.md (suggested {SEGMENT_BYTES_DEFAULT} for a "
                         "large-context reader); 0 disables. Implies --full-prompts so each segment "
                         "is self-contained. Overrides --reader-context-tokens.")
    ap.add_argument("--reader-context-tokens", type=int, default=0,
                    help="the token window of the model that will READ the segments; the segment "
                         "byte budget is derived from it. Use this instead of --segment-bytes when "
                         "the reader is not a large-context model (e.g. a 48000-token reader).")
    ap.add_argument("--findings-dir", default=None,
                    help="where per-segment finding stubs go (default <out>/findings)")
    ap.add_argument("--label", default=None, help="a label (e.g. the cell/run) for the plan header")
    args = ap.parse_args()

    # Resolve the segment budget: explicit bytes win, else derive from the reader's window, else a
    # default that assumes a large-context reader (and says so, so a small reader is not silently
    # handed segments bigger than its whole window).
    segment_bytes = 0
    if args.segment_bytes:
        segment_bytes = args.segment_bytes
        if args.reader_context_tokens:
            print("note: --segment-bytes overrides --reader-context-tokens")
    elif args.reader_context_tokens:
        segment_bytes = budget_for_reader(args.reader_context_tokens)
    if (args.segment_bytes or args.reader_context_tokens) and not args.out:
        sys.exit("segmenting needs --out (segments batch the chunk files it writes)")

    cap = resolve_capture(args.capture)
    calls = list_calls(cap)
    if not calls:
        sys.exit(f"no captured calls in {cap}")

    # Segments go to independent fresh readers, so each must stand alone: prefix-dedup is lossless
    # ONLY for a single reader taking every chunk in order. Force whole prompts when segmenting.
    full_prompts = args.full_prompts or bool(segment_bytes)
    if segment_bytes and not args.full_prompts:
        print("note: segmenting forces whole prompts so each segment is self-contained")

    prev_prompts = {}
    blocks = [emit_call(num, phase, stem, prev_prompts, full_prompts)
              for num, phase, stem in calls]

    if not args.out:
        sys.stdout.write("".join(blocks))
        return

    outdir = Path(os.path.expanduser(args.out))
    outdir.mkdir(parents=True, exist_ok=True)
    chunks, cur, size, lines = [], [], 0, 0
    for b in blocks:
        n = b.count("\n") + 1
        # A call never splits across chunks — every chunk is a whole number of calls. Both budgets
        # bind: bytes so a chunk stays loadable, lines so it stays READABLE by a line-capped reader.
        if cur and (size + len(b) > args.chunk_bytes or lines + n > args.chunk_lines):
            chunks.append("".join(cur))
            cur, size, lines = [], 0, 0
        cur.append(b)
        size += len(b)
        lines += n
    if cur:
        chunks.append("".join(cur))
    width = max(2, len(str(len(chunks))))
    over = []
    for i, text in enumerate(chunks, 1):
        name = f"chunk{i:0{width}d}.txt"
        (outdir / name).write_text(text)
        n = text.count("\n") + 1
        if n > args.chunk_lines:
            over.append((name, n))
    total = sum(len(c) for c in chunks)
    print(f"{len(calls)} calls → {len(chunks)} chunks, {total:,} bytes, in {outdir}")
    if segment_bytes:
        names = [f"chunk{i:0{width}d}.txt" for i in range(1, len(chunks) + 1)]
        sizes = [len(c) for c in chunks]
        findings_dir = args.findings_dir or (outdir / "findings")
        segments = write_assignments(outdir, names, sizes, segment_bytes, findings_dir, args.label)
        oversized = sum(1 for s in segments if s["oversized"])
        if not args.segment_bytes and args.reader_context_tokens:
            print(f"  note: {segment_bytes:,} bytes derived from a "
                  f"{args.reader_context_tokens:,}-token reader window")
        print(f"  → {len(segments)} segments (<= {segment_bytes:,} bytes) in assignments.json / "
              f"WALK-PLAN.md" + (f"; {oversized} oversized (page them)" if oversized else ""))
    # One call can exceed the budget on its own, and splitting a call is worse than a long chunk.
    # Saying so is the difference between a reader paging it and a reader silently missing it.
    for name, n in over:
        print(f"  OVERSIZED {name}: {n:,} lines — one call exceeds --chunk-lines; PAGE IT, "
              f"read offset {args.chunk_lines}+ as well")


if __name__ == "__main__":
    main()
