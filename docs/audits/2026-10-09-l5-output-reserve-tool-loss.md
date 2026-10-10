# Restored L5: output reservation deleted the callable tool menu

## Finding and scope

The stopped campaign `l5-restored-20261008` has 35 attempted cells: 34 independently published finals and the operator-stopped phi4 / Node original. Thirteen cells have not run. All five attempted phi4 cells have authoritative `context.floor` events reporting dropped tools. No such events were found for the other 30 attempted cells, and their captured coder menus do not have the two-write-tool-only signature. This is a tool-availability census, not a behavioral census or proof that every other assist behaved correctly.

The campaign/session mapping covers all 35 attempted cells, using the captured workspace-root/run identity; all their available coder request bodies and matching October log events were inspected programmatically. Exact external census: `~/.cria/validation/l5-tool-loss-census/census.json`. Initial Ruby prompt and reply were read completely (the reply contains no separate reasoning field): `~/.cria/calls/20261009T121148-01a12214-2811-7141-afc9-fd95066fa24f/0002-coder-s1.{json,prompt.txt,response.json}`. Follow-up reply `0003-coder-s1.response.json` attempts `list_dir` as fenced text. The initial wire lists only `write_file` and `edit_file` while prose advertises reading, listing and execution.

| Affected cell | Authoritative tool-drop events |
|---|---:|
| phi4 / Ruby | 100 |
| phi4 / Go | 45 |
| phi4 / Python | 50 |
| phi4 / Java | 53 |
| phi4 / Node | 47 |

Each is an event count, not a count of failed actions. No phi4 / Rust run exists in this campaign.

## Cause

The canonical production coder configuration reserves 16,384 tokens for generation, independently of an unset hard output cap. The native phi4 context is also 16,384 tokens. `contextfloor.fit` previously clamped the reservation to `window - 512`, leaving only 512 tokens for all input before density calibration. `_compress_tools` then deleted tools from the end of the menu until their schema fit a fraction of that tiny budget. The real Ruby event at 1791573109.64 reports window 16384, effective reservation 15872, eight dropped tools, and an input still over budget. An initial environment turn was replaced by an omission note too.

This is cria introducing a structural obstacle. Published zeros describe delivered files, not fair capability measurements. Preserved originals, captures, checkpoints and existing results must not be erased or silently replaced. The operator stopped the campaign and both heartbeats before authorizing this repair. No replacement or campaign restart is authorized by this fix.

## Repair

At the existing context floor, the input-side reservation ceiling now accounts for the live input core (system instructions, initial environment/task, latest question and tail, and issuing calls for retained tool results) plus the callable tool schema under the existing density estimate. Where that core can fit, it wins over a conflicting output reservation. Historical input that itself exceeds the window still goes through the ordinary floor; lowering a reservation to zero cannot save an intrinsically oversized core.

The floor never deletes tools. Description bounding retains every tool's name, arguments and required fields; an impossible schema reports `over_budget` rather than silently changing the capabilities. The event records requested and effective reservations. No hard output cap, sampling change, model substitution, fixed half-window heuristic, planner activation or suite retry was introduced. Large-window reservations retain their old value.

## Verification

New regressions fail before the fix and pass after it: equal 16K window/reservation retains the initial input and all tools, an impossible schema retains all tools while reporting overflow, the actual wire serializer retains capabilities without adding `max_tokens`, and large-window reservations are unchanged. Focused related tests: 92 passed, 14 subtests passed. Full `python -m pytest`: 5859 passed, 2 skipped, 3581 subtests passed and the same 19 historical missing-evidence failures; no tests removed or weakened. Logs: `/tmp/cria-reserve-before.log`, `/tmp/cria-reserve-after-focused.log`, `/tmp/cria-reserve-full-tests-after.log`.

This validates the wire/context repair with fake upstreams, not a new live coding result. Campaign remains stopped; subsequent L5 measurements require explicit operator authorization and transparent handling of affected originals.
