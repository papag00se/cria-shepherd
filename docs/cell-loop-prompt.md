# Single-cell Supervisor prompt

Replace `<model>` and `<task>` with the official model ID and suite task ID before sending.

> In this repository, supervise **<model> / <task>** at L5 with planning OFF until its independent final usefulness is **at least 75%; exactly 75% counts**. Resume existing evidence and fixes; do not restart completed work.
>
> Loop: run the cell → independently judge delivered work → if below target, walk the complete capture → fix demonstrated upstream causes in cria → test, commit, merge/push to main and deploy → rerun. Never repair the benchmark workspace yourself.
>
> Follow `suite/README.md` for sandboxed, detached runs, serial inference, 15-active-minute checkpoint judgments/reports and final scoring. Change no runtime/config during a cell.
>
> Use `docs/walk-prompt.md` to assign independent deduplicated sections to cheap readers with `docs/walk-reader.md`; use `docs/walk-investigator.md` for diagnosis and fixes. Preserve exhaustive line-by-line reading. Parallelize non-conflicting work, not approval chains. Run focused tests while fixing and the full suite at the end before deployment/rerun.
>
> Stay on this cell until the target is independently met. No other cells, speculative fixes, repeated reviews, freezes or proof warehouses. Continue without asking unless genuinely blocked; then ask one specific question.
