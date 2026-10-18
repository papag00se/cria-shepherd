# Walk supervisor

Coordinate a complete chronological reading of the selected run. Every prompt, recorded reasoning trace, reply, tool call and result must be read line-by-line. No sampling, grep-based substitutes, or summaries of unread material. Even thousands of large files do not justify shortcuts. Look for subtle or obvious context footguns and whether recent fixes help or introduce problems.

## Assign the reading

Use `suite/walk.py <session> --out <dir> --reader-context-tokens <reader-window> --label <cell>` to produce lossless chunks and one `assignments.json`. Alternatively use an explicitly sized `--segment-bytes` budget; 250000 bytes is intended for a large-context reader, not automatically for a smaller cheap model.

Assign each manifest section to one fresh reader, with its ordered chunk paths, finding path, and [reader prompt](walk-reader.md). Use no more than ten simultaneous readers; dispatch further sections as capacity becomes available. Readers may run independently and in parallel. The same reader reads all chunks in its section, in order, without compaction. Do not split a section among readers or let a reader skip its initial context. An oversized call must be paged completely; if the section cannot fit a reader's context, assign a reader that can hold it rather than silently compacting.

Each section supplies its own initial context. Later calls explicitly reference exact prompt lines that reader already read; all new or changed text is printed. COPY references preserve the current ordering, and DELETE/REPLACE markers describe context changes. No reference depends on another reader's section. `--full-prompts` remains available when every prompt must be printed independently.

## Use findings, not another reading bureaucracy

Require completed reading coverage and actual cited observations, including uncertainty or an explicit no-findings result. An assignment or empty file is not completed reading. Reading coverage does not depend on finding a bug. Notes track progress on disk, not in reader memory; they are temporary working material, not a permanent proof archive.

Give findings and cross-section questions to the [investigator/fixer](walk-investigator.md). Reader suggestions are leads, not established causes. The investigator checks cited original interactions and source before acting; it need not repeat every reader's entire section. Check neighboring sections when needed to establish a causal chain across their boundary. Reuse completed readings; do not restart a whole walk merely to verify one finding.

Keep the role boundary clear: cheap readers read and observe; investigators diagnose and fix; the supervisor ensures complete coverage, integrates results, and continues the run/walk/fix goal. Multiple agents should do useful non-conflicting work, not create approval chains. Preserve necessary regression inputs in the repository and actual model-call logs in their canonical location. Remove settled temporary walk material under the repository's retention policy.
