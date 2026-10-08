# L0 Go cache/checksum root isolation — 2026-10-08

## Incident and evidence

`cart-billing-go_bonsai2_codex_poff_1791443496` paused at its first15-active-minute checkpoint. Full task/seed/frozen task files and initial native prompt/reply/reasoning were read. No requested implementation was delivered: seed arithmetic/tests/go.mod remained unchanged, with only empty probe/checksum additions. The checkpoint0%/protected-continue judgment is not a final and does not end the cell for pace.

The exact harness log shows `go env GOMODCACHE GOPATH GOFLAGS` resolving `/home/jesse/go/pkg/mod` and `/home/jesse/go`, outside the two permitted writable roots. Downloading into a manually specified cell module cache without overriding GOPATH repeatedly produced the real tool error:

```
go: github.com/shopspring/decimal@v1.5.0: verifying go.mod: github.com/shopspring/decimal@v1.5.0/go.mod: open /home/jesse/go/pkg/sumdb/sum.golang.org/latest: no such file or directory
```

Earlier module declarations disappearing are explained by the coder's `go mod tidy` on unchanged production source with no decimal import; this is not evidence that filesystem edits fail to persist. The separate environmental defect is real: suite isolation assigned GOBIN but left Go's module/checksum defaults aimed outside its writable sandbox. A coder should not need to discover and repair harness install/cache configuration to add the dependency the task requests.

The serial parent was stopped, and the already checkpoint-paused Codex process group stopped before the accepted checkpoint could resume inference. The runner archived an unscored `harness-error` with authoritative201calls/1196.1wall seconds/902.0active seconds. This is an infrastructure stop, NOT natural completion or a requirement-pace stop; original attempt remains unscored. Complete workspace, captures, logs, manifests, exact row, stop receipt and SHA256 index live in `~/.cria/validation/l0-bonsai-cart/infrastructure/`. No next main cell or feed rerun is authorized by this finding.

## Upstream repair

`suite/run.py::_isolated_installs` explicitly assigns GOPATH to the existing cell's `go`, GOMODCACHE to its `gomodcache`, and GOCACHE to the already intended XDG `go-build` location. Ambient values cannot redirect those writes to the host. Module/checksum/build caches now fit the same permitted install root; no extra host write permission, task code, dependency choice, prompt, assist, L0/planner/sampling/window/Codex/fleet changes. Go's writable caches cannot remain shared read-only; other ecosystem cache policy is unchanged.

## Verification and rollout

`tests/test_suite_go_cache_isolation.py` executes real `go env` through a login shell, both with absent and poisoned ambient Go paths, and an actual offline Go build writes the scoped build cache. Every unsafe path assertion precedes any potentially shared-cache write. Three tests fail before the repair and pass after. With existing sandbox policy tests:17passed. Full `python -m pytest -q`:5823passed,2skipped, the exact same19historical missing-evidence failures, including all12SUBFAILED entries; no new red. These probes use no network/model/GPU and never modify the frozen task.

Commit/push and service restart must precede one newly authorized linked serial cart replacement. Validate the original failed row and unchanged fleet before adopting the repair revision. Only after exact replacement archive independently judged (honest0% qualifies) may the main campaign progress; preserve thirteen current logical judgments and the original unscored failure separately. No retrospective score changes or universal environment certification.
