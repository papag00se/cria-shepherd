# Restored L0: Maven repository and JVM temporary isolation

## Preserved incident

`feed-pipeline-java_k2_horizon_7b_codex_poff_1791468524` is unscored, not a zero. The original terminal row is preserved at `~/.cria/validation/l0-k2-feed/infrastructure/original-result.json`; archive, captures and native log remain intact. Classification retains natural harness exit separately from infrastructure `harness-error`. Driver1952543 was stopped after the natural archive, before scoring or advancing.

The full initial prompt/reply and terminal0028 reply were inspected, along with task, seed, archived sources and external verification. Additional native log inspection of lines285–384 established the earlier baseline `mvn -q compile` failure: `Could not create local repository at /home/jesse/.m2/repository`. Java/Jansi also reported read-only `/tmp`. Shell TMPDIR and existing install roots do not redirect either default. Later manually selecting a writable Maven repository does not erase the suite fault or qualify this original for judgment. The malformed authored POM is a distinct delivered-source defect; no POM/importer fix is supplied to the coder.

## Bounded repair

`suite/run.py::_isolated_installs` supplies JVM properties `maven.repo.local=<cell>/m2/repository` and `java.io.tmpdir=<cell>/java-tmp` through `JAVA_TOOL_OPTIONS`; creates the latter outside the workspace; preserves unrelated ambient options. JVM-native quoted-option parsing handles paths with spaces, unlike shell-expanded MAVEN_OPTS. Explicit command-line JVM properties and project-owned configuration retain ordinary precedence; this redirects the default/ambient writable state, not arbitrary coder-specified destinations.

No toolchain, task source, dependency, prompt, assist, sampling, planner, window, sandbox permission or fleet change. No inference ran during repair. No API request in verification; offline Maven validates a separate packaging-pom fixture without plugin downloads, and real Java reports effective properties. This proves launcher isolation, not the feed's speedup, CSV behavior or parallel determinism.

## Regression evidence

`tests/test_suite_maven_cache_isolation.py` exercises absent and poisoned ambient properties through a real login shell/Maven/Java, checks effective cell paths, preserved unrelated option, created local repository and unchanged host sentinel. Both tests fail before repair and pass afterward;21 focused tests pass. Full `python -m pytest`:5827 passed/2 skipped/same19 historical FAILED/SUBFAILED entries, compared exactly against the preceding Cargo repair run. Logs and comparison receipt are in the infrastructure evidence directory.

The original must remain excluded from logical scores/averages. After commit/push/restart and revision adoption, one authorized linked replacement must be independently judged from its exact terminal archive before K2/handles advances. No Ornith feed rerun is authorized; frontend and both heartbeats remain active.
