# L0 Cargo registry/cache root isolation — 2026-10-08

## Preserved incident

`rust-toml-cli_ling3.0_tiny_codex_poff_1791463727` naturally exited after authoritative22calls/60.0wall-active seconds, but the complete native harness log establishes an infrastructure defect before Rust compilation: Cargo tried writing `/home/jesse/.cargo/registry/cache/index.crates.io-1949cf8c6b5b557f/clap_lex-1.1.1.crate` and the shared registry index, both read-only under the pinned workspace/install-root sandbox. An offline attempt also could not resolve the locked libc0.2.190 from the host's older0.2.189 cache. Natural harness exit does not make an infrastructure-compromised attempt scoreable.

The original row is preserved verbatim at `~/.cria/validation/l0-ling-rust/infrastructure/original-result.json`; its classification receipt preserves original-row and full-log hashes and exact archive/capture paths. The campaign result now records `harness_terminal=exited`, `terminal=harness-error` and explicit infrastructure provenance. The archive, task files, complete native log, exact captured prompts/replies/reasoning and census remain unchanged. No independent usefulness judgment is recorded. Driver1681749 was stopped after the owned runner archived/exited and before any Phi4 cell could launch.

## Root cause and bounded repair

`suite/run.py::_isolated_installs` already assigned CARGO_INSTALL_ROOT, which only chooses installed binaries; it omitted CARGO_HOME, which owns registry downloads/index/cache state. Thus a task requesting a published parser had to discover and repair the suite's missing environment rather than simply use Cargo. Assign CARGO_HOME to the existing cell-local cargo directory alongside CARGO_INSTALL_ROOT, overriding absent or inherited ambient configuration. No shared home copies, new host writable permissions, toolchain/weights changes, task source assistance, dependencies pinned by the supervisor, prompts, L0/planner/sampling/windows/output policy or runtime assists changed.

## Regression and operational validation

`tests/test_suite_cargo_cache_isolation.py` fails twice before the fix, for absent and poisoned ambient CARGO_HOME. Both fail before any possible host-cache write. After the fix, real Cargo invoked through the same login-shell family consumes configuration exclusively from the cell home, builds an offline probe into that home's configured target directory, executes it successfully and leaves the poisoned host configuration unchanged. With Go and Codex sandbox-policy coverage:19passed. The probe has no external API/model/GPU dependency and does not change any archived task.

Full `python -m pytest -q`:5825passed,2skipped,3572subtestspassed and exactly the same19 historical missing-evidence failures. All19 FAILED/SUBFAILED summary entries (including12SUBFAILED entries) match the retained Go-cache repair baseline verbatim, no new red; complete receipt and comparison in `~/.cria/validation/l0-ling-rust/infrastructure/`. Commit/push and frontend restart precede the explicitly authorized linked serial replacement `l0-restored-20261008-ling-rust-rerun-1`. That replacement must terminate successfully and receive its own exact-archive independent judgment (honest0% qualifies), then report publication/revision adoption gates Phi4 advancement. The original remains unscored, both heartbeats/frontend retained, no Ornithfeed rerun.
