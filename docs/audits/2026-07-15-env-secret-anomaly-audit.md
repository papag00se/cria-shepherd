# Env / Secret-Handling Anomaly Sweep — 2026-07-15

> **Tier 1 RESOLVED 2026-07-15.** Root fixed: cria loads its own env file at startup
> (`cria/envfile.py` `load_env_file`, keyed off a new `env_file` config), normalizing values
> once so the CRLF footgun dies at the source; `env_secret` is the single key accessor (used by
> the search key and cloud provider keys); `_warn_config` surfaces a misconfigured feature at
> startup. The duplicate Brave request is collapsed into `cria/brave.py`. Live-verified: after
> setting `env_file` in the toml and restarting, `env_secret` resolves the key and a live request
> synthesizes `web_search`.
>
> **Tier 2 + Tier 3 RESOLVED 2026-07-15.** Consolidation: `cria/toolargs.py` (one `parse_args` +
> `tool_path` + `PATH_KEYS`, delegated from writeproxy/massage/loop); `_command_of` uses
> `shelltool._CMD_FIELDS`; `massage._read_command` handles start-only. Band-aid visibility: the
> classifier escalates to ERROR after 3 consecutive failures; planner infra failure logs at ERROR;
> routing warns (naming the missing var) when a cloud provider is dropped for a missing key;
> `reasoning="auto"` documented. 660 tests green. Whole sweep closed.


Second sweep, triggered by a **recurring** failure: the Brave web-search key was "fixed
twice" at the code level and still didn't work. This sweep asked *why the fixes keep
bouncing off*.

## The root cause (confirmed at runtime, all four dimensions converge)

The Brave key is configured correctly — `~/.cria/cria.toml` sets
`planner.search_api_key_env = "BRAVE_SEARCH_API_KEY"`, and `/home/jesse/.env/.env`
contains that variable. **But the running daemon's `/proc/<pid>/environ` has no such
variable.** There is **no `.env`-loading code anywhere in cria, and no `EnvironmentFile=`
in the systemd unit.** So `os.environ.get("BRAVE_SEARCH_API_KEY")` returns `""` in the
daemon, and every code-level fix (the CRLF `.strip()`, reading the var in the writeproxy)
is a band-aid on a variable that was never in the process. It "works by hand" because the
interactive shell / runbook sources the `.env`; the systemd service does not.

**One fix collapses all the HIGH items:** load + normalize an env file at startup (stdlib,
keyed off a `cria.toml` path) so cria is self-sufficient regardless of launcher.

## Tier 1 — the recurring failure + what I introduced

- [ ] **No env-file loader → secrets never reach the daemon.** `cria/__main__.py` /
  `cria/config.py` (absence); `cria.service` has no `EnvironmentFile=`. Load a configured
  env file at startup and normalize values once.
- [ ] **CRLF hygiene at two consumer sites, none at the source.** `server.py:196`,
  `server.py:395` `.strip()` the search key; `routing.py:109` reads cloud provider keys
  with NO strip → a CRLF `.env` breaks cloud `Authorization` with the same "invalid header"
  the search fix was written to prevent. Normalize once at the load boundary; one key
  accessor.
- [ ] **Duplicate, diverged Brave request (I introduced the second one).**
  `planner_tools.brave_search` (proper `urlencode`, X-Subscription-Token + Accept +
  User-Agent, count clamp, error handling) vs `writeproxy._search_command` (`sed 's/ /+/g'`
  query encoding that corrupts `&?#+`/unicode, only X-Subscription-Token, no error
  handling). Share one endpoint + URL/header builder.
- [ ] **web_search silently off, no signal.** Empty key → `advertise()` just doesn't inject
  the tool; the planner returns a canned "no search key" steer to the *model*
  (`planner_tools.py:238`) instead of telling the *operator*. Warn at startup when a
  configured-looking feature can't run.
- [ ] **Planner silently not built** when `enabled=true` but a reasoner/coder role is
  missing (`server.py:191`) — plain passthrough with no explanation. Warn.
- [ ] **`_qbash` reimplements `shlex.quote`** (`writeproxy.py:172`) — I added it; use
  `shlex.quote`.

## Tier 2 — consolidation (reduces future drift; not the failing thing)

- [ ] **`_read_command` duplicated & diverged** — `writeproxy.py:207` (handles start-only
  range) vs `massage.py:255` (silently ignores `start`). Massage should delegate.
- [ ] **Double-escaped-newline repair in 3 places** — `writeproxy.py:373`, `massage.py:698`,
  `massage.py:738`. One normalization pass at the tool-arg boundary.
- [ ] **Tool-arg JSON parse reimplemented ~7×** with divergent `strict=` leniency
  (writeproxy/massage/planner/loop×3/responses/focustrim). One `parse_tool_args` helper.
- [ ] **Command-field extraction, 4 different field-sets** — canonicalize on
  `shelltool._CMD_FIELDS`; others import it.
- [ ] **Path-extraction `path/file_path/file` chain repeated 7×** — one `_tool_path` helper.

## Tier 3 — band-aids masking recurring bugs (operator visibility)

- [ ] **classifier `_fallback` biases-to-engage on ANY failure** (`classify.py:95`) — a
  persistently broken classifier is masked as normal routing; escalate repeated
  parse/route errors (root is usually the fenced-JSON/reasoning-leak parse bug).
- [ ] **planner broad `except Exception` → None → plain routing** (`planner.py:286`) — an
  infra failure looks identical to "chose not to plan"; narrow it.
- [ ] **Cloud provider dropped for a missing key with no log** (`routing.py:110`) — warn.
- [ ] **`reasoning="auto"` in example toml but not in the dataclass docstring**
  (`config.py:146`) — harmless drift; document `"auto"`.

## Posture check

The env/secret code itself is small and mostly correct — the failure is **architectural**:
cria assumed its launcher provides the environment, so a service manager that doesn't
source `.env` silently starved every secret. The many duplications are recent organic
growth (some from this session's writeproxy work), not rot. The fix is one load-and-
normalize boundary plus operator-visible warnings; the consolidation is cleanup that keeps
the next drift from happening.

## Provenance

Four parallel dimension agents: env/secret propagation, duplicate implementations, config
coherence, band-aid patterns. Runtime-confirmed against `/proc/<pid>/environ`.
