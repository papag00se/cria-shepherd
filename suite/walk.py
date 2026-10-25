#!/usr/bin/env python3
"""Prepare lossless captured-call material for navigation, not a reader protocol.

Official staged walking: docs/walk-prompt.md. Mixed context/response output from this utility
must not be supplied as stage-1 reasoning-only evidence.

Why this exists: a walk done through an ad-hoc digest script silently cut reasoning at a few
hundred characters and tool arguments shorter still, and two real defects (a file the run DID
create, and the harness's "unsupported call" replies) were invisible in the cut.
This preparation utility NEVER truncates content; it does not require exhaustive context reading.

For each call NNNN-<phase> in the capture directory it prints:

  CALL NNNN [phase]
  --- PROMPT ---            complete initial context for each phase in each reader's section.
                            Later prompts reference exact whole lines already read in that
                            section, naming the source CALL/phase and 1-based inclusive line
                            ranges. New/changed text is printed verbatim; deletions, replacements
                            and the current positions of reused lines are explicit. Moved or
                            reintroduced lines can reference an earlier prompt in the section.
                            --full-prompts prints every prompt in full instead.
  --- UNFINISHED STREAMED REASONING ---  any saved .json.reasoning.partial.txt, verbatim,
                            labelled with its artifact name and byte count; never a completed
                            response. Included even when a completed response also exists.
  --- THINK ---             the model's complete reasoning_content, unabridged.
  --- SAY ---               the complete assistant text, unabridged.
  --- TOOL CALL <name> ---  the complete raw argument string of every tool call, unabridged.
  [finish: <reason>]

Output goes to stdout, or to numbered chunk files with --out (default ~64 KB AND ~1800 lines per
chunk so a reader can take the run in order without any single file being unloadable). Bytes alone
were not enough: a chunk of many short lines came to 3,318 lines, a reader capped at 2,000 read the
head and moved on, and 2,406 lines went unwalked without anything saying so.

    python3 suite/walk.py ~/.cria/calls/<session>            # whole run to stdout
    python3 suite/walk.py <session-name> --out ~/.cria/walk-findings/<date>/<cell>   # chunkNN.txt; never /tmp
    python3 suite/walk.py <session-name> --full-prompts      # no prefix-dedup at all

With --segment-bytes or --reader-context-tokens, assignments.json assigns independent sections.
Each section starts with its own complete context and reuses text ONLY within that section.
Reconstruction follows chunk order within a section; sections are independently reconstructible. Budgets count actual emitted UTF-8 bytes, including references and complete new
reasoning/results. No call is split; an oversized single call is explicitly flagged.

There is deliberately NO flag to shorten, sample, or filter content.
"""
import argparse
from difflib import SequenceMatcher
import json
import os
import re
import sys
from pathlib import Path

# The documented file entrypoint must resolve the same project modules as suite.walk.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suite.capture_paths import request_identity, request_paths

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
# One coefficient, from ONE measured point, honestly labelled as such. The prior walk was safe under
# ~300 kB of segment text on a reader with a ~272k-token window, i.e. ~1.0 byte of segment per token
# of the reader's window (272000 * 1.0 = 272 kB, under the observed 300 kB ceiling). That is the only
# thing measured; do not dress it up as separate "window fraction" and "chars per token" factors,
# because a single data point constrains only their product. The scaling to other readers assumes the
# ceiling tracks the window (unproven, but the error is safe for smaller readers: a smaller budget).
# Adjust this one number if a specific reader is remeasured; the oversized flag makes a bad fit loud.
SEGMENT_BYTES_PER_WINDOW_TOKEN = 1.0



def budget_for_reader(context_tokens, bytes_per_token=SEGMENT_BYTES_PER_WINDOW_TOKEN):
    """A compaction-safe segment byte budget for a reader with the given token window.

    Derived from a single measured point (~300 kB safe at a ~272k-token window). Conservative and
    approximate; the caller flags any single chunk that still exceeds the result.
    """
    if context_tokens <= 0:
        raise ValueError("context_tokens must be positive")
    return max(1, int(context_tokens * bytes_per_token))


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


def write_assignments(outdir, chunk_names, chunk_sizes, budget, findings_dir, label, *, groups=None):
    """Batch already-written chunk files into compaction-safe reading assignments.

    assignments.json is the sole coordination record. Readers write actual findings at its
    named paths; generating assignments creates no finding stubs or duplicate protocol document.
    All working files stay in the same disposable walk directory. Returns the segment list.
    """
    findings_dir = Path(findings_dir)
    if not findings_dir.resolve().is_relative_to(Path(outdir).resolve()):
        raise ValueError("findings must stay inside the walk directory")
    findings_dir.mkdir(parents=True, exist_ok=True)
    # Explicit groups preserve the context resets chosen BEFORE chunking. Never
    # regroup delta chunks into sections whose readers lack their referenced calls.
    groups = group_by_budget(chunk_sizes, budget) if groups is None else groups
    if [i for group in groups for i in group] != list(range(len(chunk_names))):
        raise ValueError("section groups must cover every chunk once in order")
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
            "oversized": seg_bytes > budget,
            "finding_file": str(finding),
        })
    manifest = {
        "capture": str(outdir),
        "label": label,
        "segment_bytes_budget": budget,
        "chunks_total": len(chunk_names),
        "prompt_references": "section-local; read assigned chunks in order; line ranges are 1-based and inclusive",
        "segments": segments,
    }
    (outdir / "assignments.json").write_text(json.dumps(manifest, indent=2) + "\n")
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
    for f in request_paths(cap):
        _number, phase = request_identity(f)
        out.append((f.name.split('-', 1)[0], phase, f.with_suffix("")))
    return out


def emit_call(num: str, phase: str, stem: Path, prev_prompts: dict, full_prompts: bool):
    """Render a call; prev_prompts holds phase-local prompt and already-read lines.

    Only exact whole lines from the same reader's earlier prompts may be omitted.
    References preserve their placement; deletions/replacements name the old ranges.
    A section resets this map, so each phase starts with complete context.
    """
    lines = []
    lines.append("=" * 90)
    lines.append(f"CALL {num} [{phase}]")
    lines.append("=" * 90)

    prompt_file = stem.parent / f"{num}-{phase}.prompt.txt"
    prompt = prompt_file.read_bytes().decode("utf-8") if prompt_file.exists() else ""
    prev = prev_prompts.get(phase)
    if full_prompts or prev is None:
        tag = "" if full_prompts else f" (FULL, first {phase} in this section)"
        lines.append(f"--- PROMPT{tag} ---")
        lines.append(prompt)
    else:
        previous_number, previous_prompt, known = prev
        old, new = previous_prompt.splitlines(keepends=True), prompt.splitlines(keepends=True)
        source = f"CALL {previous_number} [{phase}]"
        lines.append(f"--- PROMPT Δ [against {source}; line ranges are 1-based and inclusive] ---")
        if not old and not new:
            lines.append("--- PROMPT EMPTY ---")
        for kind, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if kind == "equal":
                lines.append(f"--- PROMPT COPY [{source} lines {a + 1}-{b} -> lines {c + 1}-{d}] ---")
            elif kind == "delete":
                lines.append(f"--- PROMPT DELETE [{source} lines {a + 1}-{b}; before current line {c + 1}] ---")
            else:
                if kind == "replace":
                    lines.append(f"--- PROMPT REPLACE [{source} lines {a + 1}-{b} -> lines {c + 1}-{d}] ---")
                else:
                    lines.append(f"--- PROMPT INSERT [lines {c + 1}-{d}] ---")
                # A moved or reintroduced line is not new reading. References
                # point to where its literal bytes were FIRST supplied, even if
                # the immediately previous prompt no longer contains them.
                cursor = c
                while cursor < d:
                    match = known.get(new[cursor])
                    end = cursor + 1
                    if match is not None:
                        source_number, offset, source_lines = match
                        while (end < d and offset + end - cursor < len(source_lines)
                               and new[end] == source_lines[offset + end - cursor]):
                            end += 1
                        lines.append(f"--- PROMPT COPY [CALL {source_number} [{phase}] lines {offset + 1}-{offset + end - cursor} -> lines {cursor + 1}-{end}] ---")
                    else:
                        while end < d and new[end] not in known:
                            end += 1
                        lines.append("".join(new[cursor:end]))
                    cursor = end
    # Trial rendering during section packing must never mutate the previous
    # reader's dictionary: a rejected trial cannot make unread lines 'known'.
    known = {} if prev is None else prev[2].copy()
    prompt_lines = prompt.splitlines(keepends=True)
    for index, line in enumerate(prompt_lines):
        known.setdefault(line, (num, index, prompt_lines))
    prev_prompts[phase] = (num, prompt, known)

    # Upstream._partial_path appends to the FULL metadata filename (including .json). A killed
    # stream can leave only this artifact. Coexistence with a response does not erase the fragment:
    # expose it separately, never promote its prose to assistant text, actions or a finish status.
    partial_file = Path(f"{stem}.json.reasoning.partial.txt")
    if partial_file.exists():
        partial = partial_file.read_bytes()
        lines.append(f"--- UNFINISHED STREAMED REASONING [artifact: {partial_file.name}; "
                     f"{len(partial)} bytes; not a completed response] ---")
        # Producer writes UTF-8. Decode strictly and do not strip or translate any saved newline.
        lines.append(partial.decode("utf-8"))
        lines.append("--- END UNFINISHED STREAMED REASONING ---")

    resp_file = stem.parent / f"{num}-{phase}.response.json"
    if resp_file.exists():
        resp = json.loads(resp_file.read_bytes())
        for choice in resp.get("choices", []):
            msg = choice.get("message", {})
            think = msg.get("reasoning_content") or ""
            if think:
                lines.append("--- THINK (full) ---")
                lines.append(think)
            say = msg.get("content") or ""
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


def render_sections(calls, budget, full_prompts=False):
    """Greedily pack whole calls using their actual section-local rendered bytes.

    Test a delta with a copy of the current reader state. If it does not fit,
    reset and render that same call with full initial context for the next reader.
    An oversized call stands alone and is reported, never clipped or split.
    A zero budget is the original single-reader, unbounded stream.
    """
    if budget < 0:
        raise ValueError("section budget must not be negative")
    sections, current, state, size = [], [], {}, 0
    for call in calls:
        candidate_state = state.copy()
        block = emit_call(*call, candidate_state, full_prompts)
        block_size = len(block.encode("utf-8"))
        if budget and current and size + block_size > budget:
            sections.append(current)
            current, state, size = [], {}, 0
            candidate_state = {}
            block = emit_call(*call, candidate_state, full_prompts)
            block_size = len(block.encode("utf-8"))
        current.append(block)
        state, size = candidate_state, size + block_size
        if budget and size > budget:
            sections.append(current)
            current, state, size = [], {}, 0
    if current:
        sections.append(current)
    return sections


def chunk_blocks(blocks, byte_budget, line_budget):
    """Keep calls whole, and never mix blocks from separate reader sections."""
    chunks, current, size, lines = [], [], 0, 0
    for block in blocks:
        n = block.count("\n") + 1
        block_bytes = len(block.encode("utf-8"))
        if current and (size + block_bytes > byte_budget or lines + n > line_budget):
            chunks.append("".join(current))
            current, size, lines = [], 0, 0
        current.append(block)
        size += block_bytes
        lines += n
    if current:
        chunks.append("".join(current))
    return chunks


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("capture", help="capture dir path, session name, or unique fragment of one")
    ap.add_argument("--out", help="write numbered chunk files into this directory instead of stdout")
    ap.add_argument("--chunk-bytes", type=int, default=CHUNK_BYTES_DEFAULT,
                    help=f"target size per chunk file with --out (default {CHUNK_BYTES_DEFAULT})")
    ap.add_argument("--chunk-lines", type=int, default=CHUNK_LINES_DEFAULT,
                    help=f"target lines per chunk file with --out (default {CHUNK_LINES_DEFAULT})")
    ap.add_argument("--full-prompts", action="store_true",
                    help="print every prompt whole; no section-local line reuse")
    ap.add_argument("--segment-bytes", type=int, default=0,
                    help="with --out, batch chunks into compaction-safe segments and emit "
                         f"assignments.json (suggested {SEGMENT_BYTES_DEFAULT} for a "
                         "large-context reader); 0 disables. Each segment starts with complete "
                         "context and deduplicates only within itself. Overrides --reader-context-tokens.")
    ap.add_argument("--reader-context-tokens", type=int, default=0,
                    help="the token window of the model that will READ the segments; the segment "
                         "byte budget is derived from it. Use this instead of --segment-bytes when "
                         "the reader is not a large-context model (e.g. a 48000-token reader).")
    ap.add_argument("--findings-dir", default=None,
                    help="where readers write findings inside --out (default <out>/findings)")
    ap.add_argument("--label", default=None, help="a label (e.g. the cell/run) for assignments")
    args = ap.parse_args()
    if args.chunk_bytes <= 0 or args.chunk_lines <= 0:
        ap.error("chunk byte and line budgets must be positive")
    if args.segment_bytes < 0 or args.reader_context_tokens < 0:
        ap.error("section byte and reader context budgets must not be negative")

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

    sections = render_sections(calls, segment_bytes, args.full_prompts)

    if not args.out:
        sys.stdout.write("".join(sections[0]))
        return

    outdir = Path(os.path.expanduser(args.out))
    outdir.mkdir(parents=True, exist_ok=True)
    chunks, groups = [], []
    for section in sections:
        section_chunks = chunk_blocks(section, args.chunk_bytes, args.chunk_lines)
        groups.append(list(range(len(chunks), len(chunks) + len(section_chunks))))
        chunks.extend(section_chunks)
    width = max(2, len(str(len(chunks))))
    over = []
    for i, text in enumerate(chunks, 1):
        name = f"chunk{i:0{width}d}.txt"
        (outdir / name).write_bytes(text.encode("utf-8"))
        n = text.count("\n") + 1
        if n > args.chunk_lines:
            over.append((name, n))
    sizes = [len(c.encode("utf-8")) for c in chunks]
    total = sum(sizes)
    print(f"{len(calls)} calls → {len(chunks)} chunks, {total:,} bytes, in {outdir}")
    if segment_bytes:
        names = [f"chunk{i:0{width}d}.txt" for i in range(1, len(chunks) + 1)]
        findings_dir = args.findings_dir or (outdir / "findings")
        segments = write_assignments(outdir, names, sizes, segment_bytes, findings_dir, args.label,
                                     groups=groups)
        oversized = sum(1 for s in segments if s["oversized"])
        if not args.segment_bytes and args.reader_context_tokens:
            print(f"  note: {segment_bytes:,} bytes derived from a "
                  f"{args.reader_context_tokens:,}-token reader window")
        print(f"  → {len(segments)} segments (<= {segment_bytes:,} bytes) in assignments.json"
              + (f"; {oversized} oversized (page them)" if oversized else ""))
    # One call can exceed the budget on its own, and splitting a call is worse than a long chunk.
    # Saying so is the difference between a reader paging it and a reader silently missing it.
    for name, n in over:
        print(f"  OVERSIZED {name}: {n:,} lines — one call exceeds --chunk-lines; PAGE IT, "
              f"read offset {args.chunk_lines}+ as well")


if __name__ == "__main__":
    main()
