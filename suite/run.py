#!/usr/bin/env python3
"""Suite runner — one cell of the test matrix per invocation.

Provisions a throwaway workspace, points the rig at the requested model + planner setting,
drives one harness run of the task prompt under an active-time budget, then collects metrics from
cria's own capture/events, preserves the workspace for an independent usefulness judgment, and
appends one JSON row to suite/results/results.jsonl.

At every checkpoint the runner pauses the harness, freezes the workspace, and waits for the
campaign agent to infer a percentage of usefulness plus whether the work is complete, progressing,
or stalled. That percentage appears in every checkpoint progress report and the final archived-
workspace judgment is also a usefulness percentage. A progressing run earns the next interval, up
to the task's explicitly budget-only limit; no checklist count or mechanical percentage threshold
participates. Checkpoints begin at 30 active minutes and recur every 15 active minutes.

Kill mechanics follow the runctl scars: match the codex process list explicitly (ps + grep of
the exec pattern, excluding shells), never `pkill -f` (it matches the invoking shell).

Usage: run.py --task ada-handles --model ternary-bonsai --harness codex --planner off [--note x]
"""

import argparse
import hashlib
import json
import pathlib
import os
import re
import signal
import site
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import sampling

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
# One stray 403 is a blip; a run peppered with them was throttled. Measured: the affected
# runs carried dozens, the healthy ones none.
THROTTLE_PROMPTS = 5
# NOT /tmp. A run's workspace IS its evidence — the archive and every walk that reads what the coder
# actually built — and this box runs cleaners over /tmp. One removed a workspace before archival.
# The evidence-preservation rule one screen down — "Nothing under ~/.cria/suite is
# ever auto-cleaned" — was already the intent; the live tree just was not covered by it.
#
# NOT under ~/.cria either, and that is not a style choice: `writeproxy._targets_cria_home` REFUSES
# any absolute write that resolves into cria's own home, so a workspace there would have every write
# the model makes refused. This is the durable place that is neither.
#
# AND NOT INSIDE THE REPO. It used to be `<repo>/runs`, so every workspace path the model reads —
# its own cwd, every file:line a checker prints, every absolute path in a tool result — carried the
# string `cria-shepherd`. The model reads that (#17 is about the model never seeing the token) and
# on cart-billing-go x nemotron-elastic 1788241229 call 0061 minted `github.com/jesse/creashepherd`
# from it. A neutral durable dir outside the tree removes the token from the path entirely;
# SUITE_RUNS_DIR overrides it for anyone who wants elsewhere.
RUNS_DIR = Path(os.environ.get("SUITE_RUNS_DIR") or (Path.home() / "suite-runs")).expanduser()
RUNS_DIR.mkdir(parents=True, exist_ok=True)

CALLS_DIR = Path.home() / ".cria" / "calls"
EVENTS_DIR = Path.home() / ".cria" / "logs"
CRIA_TOML = Path.home() / ".cria" / "cria.toml"
# Isolated Codex config dir that routes the harness through cria (:18085) instead of the operator's
# global ~/.codex (OpenAI). The suite always points CODEX_HOME here so a run measures cria, never
# whatever provider the ambient shell happened to select. Set up once at ~/.cria/codex-home.
SUITE_CODEX_HOME = Path.home() / ".cria" / "codex-home"
TASK_MINUTES = 15
KILL_GRACE = 20

# fleet model name -> systemd service (one model at a time on the 3080)
SERVICES = {
    "ternary-bonsai-2": "llama-ternary-bonsai-2",
    "qwythos": "llama-qwythos-q6",
    "qwopus": "llama-qwopus-q6",
    "qwen35": "llama-qwen35",
    "ornith15": "llama-ornith-q6",
    "gemma4-qat": "llama-gemma4-qat",
    "maple-preview": "llama-maple-preview",  # DeepGrove ternary MoE 20B-A1B (stamsam prism fork)
}

# RETIRED 2026-09-18 — weights, units and (for bonsai) binaries deleted from the box, so these keys
# could only ever fail a swap. Their historical scores survive in suite/historical_ladder.json and
# results.jsonl, which is why the KEYS still appear there and must not be renamed:
#   "ternary-bonsai" -> llama-ternary-bonsai   (Bonsai 1, superseded by ternary-bonsai-2)
#   "gemma4"         -> llama-gemma4           (stock it Q4_K_M, superseded by gemma4-qat)
# test_suite_model_registries_agree.py fails if a SERVICES entry names a unit that is not installed,
# which is exactly how the stale pair above was caught.

# EXTERNALLY MANAGED MODELS — not llama.cpp systemd units on :18084. Qwen3.8-27B runs as a vLLM
# container on its OWN card (the RTX 3090, :18020), which cria's [backends.local] points straight at,
# so there is no GPU-swap to do here: the endpoint is already up and the llama.cpp fleet on the 3080
# does not contend with it. swap_model just confirms the endpoint is live. Value = its health URL.
EXTERNAL = {
    "qwen38": "http://127.0.0.1:18020/health",
}

# Harness launchers: name -> argv builder (headless/exec mode only). Phase 0 ships codex;
# the other adapters land with their harness phases.
def _codex_argv(prompt: str):
    return ["codex", "exec", "--yolo", prompt]

HARNESSES = {"codex": _codex_argv}


def _codex_env(base: dict) -> dict:
    """Force the suite's cria-routing Codex home onto the child env, whatever the operator's shell
    had. The override is the point: an inherited CODEX_HOME (a `.envrc` left active, an export in a
    profile) would otherwise silently repoint the harness, and the run would score a different
    target than the one it names. Returns a new dict; the input is not mutated."""
    return {**base, "CODEX_HOME": str(SUITE_CODEX_HOME)}


def _require_codex_home() -> None:
    """Fail CLOSED before a run if the isolated Codex home is not set up. A missing config.toml makes
    `codex exec` fall back to its built-in default provider — i.e. NOT cria — and the run would look
    fine while measuring the wrong endpoint. Better a loud stop than a quiet mismeasurement (#13)."""
    cfg = SUITE_CODEX_HOME / "config.toml"
    if not cfg.is_file():
        raise RuntimeError(
            f"suite Codex home missing: {cfg} does not exist. The suite routes Codex through cria "
            f"via an isolated CODEX_HOME; create it with a [model_providers.cria] block "
            f"(base_url http://127.0.0.1:18085/v1, wire_api \"responses\") before running.")

def sh(*cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def wait_health(url: str, tries=90, delay=10) -> bool:
    """Poll until the server answers. 15 minutes, not 5.

    A healthy model answers on the first poll, so the ceiling costs nothing when it is not needed —
    and when it IS needed the alternative is a false "never became healthy", which writes no result
    row at all. A campaign driver then re-queues the same cell forever, because an absent row is
    indistinguishable from a cell that has not been attempted. Observed 2026-08-10: ternary-bonsai
    (6.7 GB, PrismML fork) exceeded 5 minutes from a cold page cache after a large file cleanup, and
    the battery driver looped on it twice before anyone looked."""
    import urllib.request
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(delay)
    return False


def swap_model(model: str) -> None:
    if model in EXTERNAL:
        # A container-managed endpoint on its own card — nothing to start or stop. cria's base_url
        # already points at it; just confirm it answers before the cell runs.
        if not wait_health(EXTERNAL[model]):
            raise RuntimeError(f"external model {model} endpoint {EXTERNAL[model]} not healthy")
        return
    target = SERVICES[model]
    for svc in SERVICES.values():
        if svc != target:
            sh("sudo", "-n", "systemctl", "stop", f"{svc}.service")
    sh("sudo", "-n", "systemctl", "start", f"{target}.service", timeout=60)
    if not wait_health("http://127.0.0.1:18084/health"):
        raise RuntimeError(f"model {model} ({target}) never became healthy")


def configure_cria(model: str, planner_enabled: bool) -> dict:
    """Write this model's sampling AND the planner setting, then restart cria once.

    Sampling used to be a manual step in the goal doc, and it was missed 26 consecutive times: every
    gemma4 run in results.jsonl was sent ternary-bonsai's numbers (coder 0.2/0.95/20) because the
    runner swapped the model and the planner and left `[roles.*]` alone. Those runs measured a model
    nobody was testing. A step that must be remembered before each run is a footgun, so the runner
    does it.
    """
    spec = sampling.apply(model, CRIA_TOML)
    text = CRIA_TOML.read_text()
    new = re.sub(r"(\[planner\][^\[]*?enabled\s*=\s*)(true|false)",
                 lambda m: m.group(1) + ("true" if planner_enabled else "false"), text, count=1)
    if new == text and f"= {'true' if planner_enabled else 'false'}" not in text:
        raise RuntimeError("could not toggle [planner].enabled in cria.toml")
    CRIA_TOML.write_text(new)
    sh("sudo", "-n", "systemctl", "restart", "cria.service", timeout=60)
    if not wait_health("http://127.0.0.1:18085/health"):
        raise RuntimeError("cria never became healthy after reconfiguration")
    # cria now serves this model; pin Codex's window to it. Without the real window Codex
    # uses a 272K fallback, never auto-compacts, and a cell that crosses the server ceiling
    # 400s mid-turn (measured: request 41,662 > ctx 40,960). sync reads the live window from
    # cria /v1/models, so it tracks the swap with no hardcoded number.
    sh(sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "sync_codex_model.py"),
       timeout=30)
    return spec


# WHERE EVERY ECOSYSTEM INSTALLS WHEN NOBODY SAYS WHERE. A run under --yolo can install into the
# operator's real environment, and the resulting artefact outlives the run: the NEXT run finds a
# dependency it never installed and scores points for work it did not do.
#
# This watched Python only, and the cost is measured. `shipping-rates-rb` requires a third-party gem;
# `countries-8.1.0` has been in the user gem dir since 2026-08-10 12:37 (installed thirteen minutes
# before e19911b, whose subject is gem detection — the task author validating the reference solution
# and leaving it behind). Every ruby row since has reported `site_packages_leak: []` while four of
# them were scored against a gem no model installed: re-scored with the dir hidden, 5/5 → 1/5,
# 5/5 → 1/5, 4/5 → 1/5.
#
# So the tripwire is per-ECOSYSTEM, because the failure is. A rule keyed to one language's spelling
# is inert on the other five — the same shape the operator has flagged repeatedly.
def _user_install_roots() -> dict:
    """`{label: directory}` for each ecosystem's default user-level install location. Asked of the
    tool where the tool can answer, so a version bump or a custom GEM_HOME does not silently blind
    the tripwire; a fixed path only where there is no command to ask."""
    home = os.path.expanduser("~")
    roots = {}
    try:
        roots["py"] = site.getusersitepackages()
    except Exception:  # noqa: BLE001
        pass
    probes = {
        "gem": ("ruby", "-e", "print Gem.user_dir + '/gems'"),
        "npm": ("npm", "root", "-g"),
    }
    for label, argv in probes.items():
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=20).stdout.strip()
            if out:
                roots[label] = out
        except (OSError, subprocess.SubprocessError):
            pass
    for label, path in (("cargo", f"{home}/.cargo/registry/cache"),
                        ("go", f"{home}/go/pkg/mod/cache/download"),
                        ("maven", f"{home}/.m2/repository")):
        if os.path.isdir(path):
            roots[label] = path
    return roots


def _ruby_keep_path() -> list:
    """The gem directories a cell must still SEE: Ruby's own, and nothing anyone installed.

    GEM_PATH REPLACES THE SEARCH PATH, IT DOES NOT EXTEND IT. Pointed at an empty cell directory it
    hides `minitest` and `rake`, which ship with Ruby and live in `/usr/lib/ruby/gems`. Walked on
    shipping-rates-rb x nemotron-elastic the night isolation landed: the run spent 24 of its 60 calls
    trying five ways to load minitest, cria's check block carried `cannot load such file --
    minitest/autorun` in 51 of 61 prompts, and the one-character bug the task opens with was never
    touched. The cell scored 8 — a measurement of this bug, not of the model.

    Asked of Ruby, never spelled out here (#20). DROP ONLY `Gem.user_dir`, the leaked user root.

    It used to drop `Gem.default_dir` as well, on the theory that a plain `gem install` lands there
    and the distribution's own gems live somewhere else. That is FALSE on this box and the mistake
    was invisible: `Gem.default_path` here is exactly `[user_dir, default_dir]`, so subtracting both
    returned an EMPTY keep-list, GEM_PATH became the cell alone, and minitest / rake / bundler went
    dark again — the precise regression the drop was added to fix, silently reintroduced, because
    this function is written to degrade to `[]` without complaint.

    Measured 2026-09-18, shipping-rates-rb x ternary-bonsai-2: the coder spent its whole first 32
    minutes probing GEM_HOME/GEM_PATH and trying to install into `/usr/lib/ruby/gems/3.4.0` to get
    a working minitest, which cria correctly denied as a system install; it wrote ZERO lines of the
    five requested deliverables. Another cell scored as a measurement of this bug, not of a model.

    Dropping only the user root is sound BY CONSTRUCTION rather than by inspection: `gem install`
    as a non-root user cannot write into `/usr/lib/ruby/gems`, so what is there arrived from the
    distribution's package manager, and the hand-installed contamination this isolation exists to
    hide (`--user-install` of `iso_country_codes`, `countries`, `rspec`) lands in `user_dir`, which
    is still dropped. `user_install_listing` remains the tripwire if that ever stops holding.

    Empty when Ruby is not installed or cannot answer, which leaves GEM_PATH as the cell alone — the
    behaviour before this, and no worse for a box with no Ruby on it."""
    try:
        out = subprocess.run(
            ["ruby", "-e", "print (Gem.default_path - [Gem.user_dir]).join(File::PATH_SEPARATOR)"],
            capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return []
    return [d for d in out.split(os.pathsep) if d]


def _ruby_cell_install_dirs(root) -> list:
    """The cell's OWN gem dir(s) that must be on GEM_PATH so a gem the model installs LOADS.

    `gem install` on this box defaults to `--user-install` and writes to `Gem.user_dir`, which is
    derived from XDG_DATA_HOME. We point XDG_DATA_HOME at `root/xdg-data`, so the install lands in
    `root/xdg-data/gem/ruby/<api>` — a per-cell path. Ask Ruby for the exact directory under that
    XDG_DATA_HOME rather than spelling the version here (#20). Distinct from `_ruby_keep_path`, which
    drops the SHARED host `Gem.user_dir` to hide cross-run leaks: this is the cell's own dir, inside
    the workspace, so naming it leaks nothing. Empty when Ruby is absent or cannot answer, which
    leaves the prior behaviour (installs unreadable) rather than inventing a path."""
    env = {**os.environ, "XDG_DATA_HOME": str(root / "xdg-data")}
    try:
        out = subprocess.run(["ruby", "-e", "print Gem.user_dir"],
                             capture_output=True, text=True, timeout=30, env=env).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return []
    return [out] if out else []


def _cell_install_bin_dirs(root) -> list:
    """Every executable directory created by the cell's redirected install roots.

    Redirecting an install root without putting its executable directory on PATH creates the same
    impossible state Ruby had before 774be9a: installation succeeds, but the next command cannot
    run what was installed. This is not theoretical: stock npm's prefix bin and Python's ~/.local/bin
    are on this host's PATH; their cell equivalents were not. `uv tool` also derives its bin as the
    sibling of XDG_DATA_HOME (root/bin). Keep each tool's cell-local bin ahead of the host PATH so a
    cell's just-installed command wins over an ambient one. Asked Ruby for its ABI-bearing user dir;
    the other layouts are tool-defined, stable roots set immediately below."""
    ruby_bins = [str(Path(d) / "bin") for d in _ruby_cell_install_dirs(root)]
    return [str(root / "py" / "bin"),        # pip install --user console_scripts
            str(root / "bin"),               # uv tool (XDG_DATA_HOME/../bin)
            str(root / "npm" / "bin"),
            str(root / "gem" / "bin"),
            *ruby_bins,
            str(root / "go" / "bin"),
            str(root / "cargo" / "bin")]


def _isolated_installs(ws) -> dict:
    """Environment that keeps this cell's package installs INSIDE its own workspace.

    NO CELL MAY AFFECT ANOTHER CELL, and for five days they did. `user_install_listing` was built to
    make contamination visible rather than to prevent it — its own words: "Nothing is prevented or
    cleaned here — a leak that is visible can be reasoned about". That fails in one specific way: the
    row records the DELTA a run creates, so the run that installs is visible and every run that
    INHERITS is silent. Five rows in the whole campaign recorded a leak; every later cell on the box
    read those packages and reported nothing.

    Measured, and it decided cells. `gem:countries-8.1.0` has been on this box since 2026-08-22 and
    `gem:iso_country_codes-0.7.8` since 2026-08-24 13:30, left by one ruby cell ninety minutes before
    another ruby cell went looking. Walked: the first run searched for "country", found nothing,
    fell back to a hardcoded list and banked its other deliverables (85); the second searched for
    "countries", found an installed gem nobody in that run had installed, and spent 277 calls
    interrogating it (28). By the time the ternary-bonsai ruby cells ran, seven gems left by four
    earlier cells were discoverable by `gem list`.

    The direction is one-way — installs accumulate, so a later cell can find more than an earlier one
    and never less. That is why a batch comparison drifts one way and a repeat of a single cell does
    not.

    Every root here is one `user_install_listing` already probes, so the tripwire keeps working and
    now measures a run against its own empty slate. The shared DOWNLOAD caches are left alone
    deliberately: a cached artifact is not discoverable by name, and taking them away would make
    every run re-fetch the world inside a 30-minute budget, which changes what the suite measures
    for a reason unrelated to isolation."""
    root = Path(ws) / ".cell-installs"
    return {
        # THE USER-LEVEL ROOT ITSELF. `gem install --user-install` ignores GEM_HOME and writes to
        # `Gem.user_dir`, which is derived from XDG_DATA_HOME — and `--user-install` is exactly the
        # command that leaked `iso_country_codes` onto this box. Verified: with XDG_DATA_HOME set,
        # `Gem.user_dir` moves and `--user-install` lands inside the cell.
        "XDG_DATA_HOME": str(root / "xdg-data"),
        "XDG_CACHE_HOME": str(root / "xdg-cache"),
        # ruby: `gem install` and `bundle` honour these. GEM_PATH is not a prefix — it REPLACES the
        # search path — so it has to name Ruby's own gems too. See _ruby_keep_path.
        "GEM_HOME": str(root / "gem"),
        # GEM_PATH must also NAME the cell's own user-install dir, or a gem the model installs
        # cannot be loaded. On this box `gem install` defaults to `--user-install`, so it lands in
        # `Gem.user_dir` (derived from the XDG_DATA_HOME we set above -> root/xdg-data/gem/ruby/X.Y.Z),
        # NOT in GEM_HOME. GEM_PATH REPLACES the search path, so if it names only `root/gem` +
        # Ruby's own gems, the just-installed gem is invisible and `require` fails. Walked on
        # shipping-rates-rb x ternary-bonsai-2 (2026-09-19): the coder understood the one-line fix
        # at turn 7, then spent turns 8-45 unable to load the EU gem it had installed, hand-copying
        # it into GEM_HOME, and ran out of budget as it finally began writing -> scored 0, a
        # measurement of this bug not the model. This is the SIBLING of _ruby_keep_path (same
        # GEM_PATH-replaces-not-extends root cause): that adds Ruby's OWN gems back; this adds the
        # cell's OWN installs back. It is the cell-local dir (per-workspace, inside .cell-installs),
        # NOT the shared host user_dir _ruby_keep_path still drops, so isolation is unchanged and
        # `user_install_listing` remains the tripwire.
        "GEM_PATH": os.pathsep.join([str(root / "gem"),
                                    *_ruby_cell_install_dirs(root),
                                    *_ruby_keep_path()]),
        # python: `pip install --user` and `site.getusersitepackages()`.
        "PYTHONUSERBASE": str(root / "py"),
        # node: `npm install -g` and `npm root -g`.
        "npm_config_prefix": str(root / "npm"),
        # go and rust install binaries here; the module/registry caches stay shared.
        "GOBIN": str(root / "go" / "bin"),
        "CARGO_INSTALL_ROOT": str(root / "cargo"),
        # Install destinations are not usable until their executable dirs are on PATH. This replaces
        # the dead hard-coded Node 22 prepend at the launch site; preserve the ambient runtime path
        # after the cell dirs so node/npm/codex remain resolvable while cell installs take precedence.
        "PATH": os.pathsep.join([*_cell_install_bin_dirs(root), os.environ["PATH"]]),
    }


def user_install_listing() -> set:
    """`{"<ecosystem>:<name>"}` for everything currently installed at user level, across ecosystems.

    The delta between two calls is recorded per row so contamination is EVIDENCE, never a silent
    confound. Nothing is prevented or cleaned here — a leak that is visible can be reasoned about;
    the two weeks of cross-run poisoning this was built after were invisible.

    (Measured first on Python: an editable install of a suite /tmp workspace via a .pth left a broken
    resolver.py shadowing `import resolver` for every later run AND the verifier.)"""
    out = set()
    for label, root in _user_install_roots().items():
        try:
            out.update(f"{label}:{n}" for n in os.listdir(root))
        except OSError:
            continue
    return out


def stop_process_group(proc, *, grace: float = KILL_GRACE, sleeper=time.sleep) -> None:
    """Stop only the harness process group this runner created, never another operator's Codex.

    `Popen(..., start_new_session=True)` makes `proc.pid` the group leader. The old process-list
    sweep matched every host `codex exec --yolo`, so ending one battery cell could SIGKILL unrelated
    interactive or campaign work. Ownership is already precise; use it."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    if proc.poll() is not None:
        return
    sleeper(grace)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        # The group may have exited while its leader's state has not been reaped. Never broaden
        # ownership here; the caller records the terminal outcome and the OS reaps the child.
        pass


def collect_capture(session_dirs) -> dict:
    """Every call the run made, across ALL of its capture directories.

    cria opens a fresh capture directory per server session, and one cell can span several: the
    harness reconnects, or the run trails a short session after the main one. Reading only the
    newest directory reports that tail as the whole run. L2 cart-billing-go x ternary-bonsai
    recorded `calls: 2` against 93 real calls in the directory next to it, which reads in the
    report as a model that produced nothing in half an hour. Sum them.
    """
    calls = sorted(f for d in session_dirs for f in d.glob("*.response.json"))
    phases, tok_n, tok_ms = {}, 0, 0.0
    for f in calls:
        m = re.match(r"\d+-(.+?)(?:-s\d+.*)?\.response\.json$", f.name)
        phase = m.group(1) if m else "unknown"
        phases[phase] = phases.get(phase, 0) + 1
        try:
            t = json.loads(f.read_text()).get("timings") or {}
            if t.get("predicted_n"):
                tok_n += t["predicted_n"]
                tok_ms += t["predicted_ms"]
        except Exception:  # noqa: BLE001
            pass
    return {"calls": len(calls), "phases": phases,
            "avg_tok_s": round(tok_n / (tok_ms / 1000), 1) if tok_ms else None,
            "output_tokens_timed": tok_n}


def collect_assists(t0: float, t1: float) -> dict:
    """Count rlog event kinds in the run's window. Single-run-at-a-time makes the time window
    authoritative; refine to session-scoped when events grow a session field."""
    kinds = {}
    for day_file in sorted(EVENTS_DIR.glob("cria-*.jsonl")):
        try:
            with open(day_file, errors="replace") as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    if t0 <= ev.get("ts", 0) <= t1:
                        k = ev.get("kind", "?")
                        kinds[k] = kinds.get(k, 0) + 1
                        # the floor's own confession that a request may not fit even after every
                        # lever — fired 58x in one run (C1) with nothing counting it.
                        if k == "context.floor" and ev.get("over_budget"):
                            kinds["context.floor_over_budget"] = kinds.get("context.floor_over_budget", 0) + 1
        except OSError:
            continue
    # A DENYLIST, NOT AN ALLOWLIST. This was a list of substrings a kind had to MATCH to be counted,
    # so every intervention nobody thought to name was dropped in silence — and the dropped ones were
    # the interesting ones. Measured on rust-toml-cli x nemotron-elastic: `writeproxy.exec_output_bounded`
    # fired 80 times, the single most important number in that run, and the row recorded none of it;
    # six distinct steer texts and thirty gate-carrying prompts came out as 0 steers and 2 gates. Every
    # "cria intervened N times" this campaign has quoted from this field was a floor, not a count (#12).
    #
    # Inverted so it fails the safe way: a NEW intervention kind is counted by default, and only
    # transport and bookkeeping are named. Adding an assist can no longer make it invisible.
    plumbing = ("upstream.", "http.", "request.", "response.", "ctx.estimate", "usage.",
                "toolmenu.", "indicators.", "coder.reasoning", "route.classify",
                "writeproxy.advertised", "writeproxy.represented", "capture.", "log.")
    # loop.compaction_reframed fires on every REQUEST that re-reads a compacted history (stateless
    # re-processing, by design) — counting it as an assist inflated one run by 85. Occurrences of
    # compaction itself are context.self_compact / route.compaction.
    kinds.pop("loop.compaction_reframed", None)
    return {k: v for k, v in kinds.items() if not any(k.startswith(p) for p in plumbing)}


def budget_intervals(task_dir: Path) -> int:
    """Maximum milestone intervals for this task; never a description of required work."""
    meta = tomllib.loads((task_dir / "meta.toml").read_text())
    value = meta.get("budget_intervals")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"{task_dir.name}/meta.toml must declare a positive integer "
                           "budget_intervals for pacing")
    return value


@dataclass
class MilestonePacing:
    """First inference at minute 30, then every 15 active minutes; judge waits cost no time."""

    started_at: float
    interval_minutes: int
    budget_intervals: int
    paused_seconds: float = 0.0
    next_milestone: int = field(init=False)

    def __post_init__(self) -> None:
        if self.interval_minutes != TASK_MINUTES:
            raise ValueError("suite pacing is fixed at 15 active minutes")
        if self.budget_intervals < 2:
            raise ValueError("suite pacing requires a budget of at least 30 active minutes")
        self.next_milestone = 30 * 60

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60

    @property
    def maximum_active_seconds(self) -> int:
        return self.interval_seconds * self.budget_intervals

    @property
    def at_limit(self) -> bool:
        return self.next_milestone >= self.maximum_active_seconds

    def active_elapsed(self, now: float) -> float:
        return now - self.started_at - self.paused_seconds

    def due(self, now: float) -> bool:
        return self.active_elapsed(now) >= self.next_milestone

    def record_pause(self, seconds: float) -> None:
        self.paused_seconds += seconds

    def advance(self) -> None:
        self.next_milestone += self.interval_seconds


def milestone_progress(verdict: dict, minute: int) -> str:
    """The canonical checkpoint progress report: always an inferred usefulness percentage."""
    return (f"[milestone] {minute}min usefulness={verdict['usefulness_percent']}% "
            f"decision={verdict['decision']}: {verdict['reason']}")


def milestone_terminal(verdict: dict, minute: int, at_limit: bool) -> str | None:
    """Translate one grounded, holistic usefulness inference into run control."""
    decision = verdict.get("decision")
    if decision == "complete":
        return f"milestone-complete-{minute}min"
    if decision == "stalled":
        return f"milestone-stalled-{minute}min"
    if at_limit:
        return "budget-killed"
    return None


def throttled_mid_run(session_dir) -> str:
    """A 403/429 from the task's live service, seen in the run's own captures.

    Thirteen back-to-back ladder runs, each making dozens of live calls, got api.handle.me to start
    refusing us: run 1785675899's CLI reported `HTTP error 403 for .../handles/goose` while the same
    request from a shell seconds later returned 200. Counted across every capture at the time: 251
    coder prompts carrying a 403, in 3 runs.

    Such a run fails for a reason that is neither cria's nor the model's, which corrupts the
    campaign evidence. It is annotated, not deleted, and the
    oracle skips it the way it skips any aborted row."""
    if not session_dir:
        return ""
    hits = 0
    for p in pathlib.Path(session_dir).glob("*coder*.prompt.txt"):
        try:
            body = p.read_text(errors="replace")
        except OSError:
            continue
        if "HTTP error 403" in body or "403 Client Error" in body or "429 Client Error" in body:
            hits += 1
    if hits < THROTTLE_PROMPTS:
        return ""
    return (f"the task's live service refused us mid-run — {hits} coder prompts carry a 403/429. "
            "Not the model's failure and not cria's; excluded from the ladder.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", required=True, choices=sorted(set(SERVICES) | set(EXTERNAL)))
    ap.add_argument("--harness", default="codex", choices=sorted(HARNESSES))
    ap.add_argument("--planner", required=True, choices=["on", "off"])
    ap.add_argument("--note", default="")
    # The engagement level this cell ran at, recorded as a FIELD rather than parsed back out of the
    # note. The note is prose and has been reformatted twice; a column that a status command counts
    # must not depend on a regex over prose surviving the next edit.
    ap.add_argument("--level", type=int, default=None)
    ap.add_argument("--milestone-minutes", type=int, choices=[TASK_MINUTES], default=TASK_MINUTES,
                    help="fixed 15-minute pacing; the first inference judgment is at minute 30")
    args = ap.parse_args()
    if args.milestone_minutes <= 0:
        ap.error("--milestone-minutes must be positive")

    if args.harness == "codex":
        _require_codex_home()   # fail before any model swap if cria routing is not set up

    task_dir = SUITE / "tasks" / args.task
    prompt = (task_dir / "prompt.txt").read_text().strip()
    run_id = f"{args.task}_{args.model}_{args.harness}_p{args.planner}_{int(time.time())}"
    ws = Path(tempfile.mkdtemp(prefix=f"suite-{run_id}-", dir=RUNS_DIR))
    log_path = SUITE / "results" / f"{run_id}.log"

    swap_model(args.model)
    spec = configure_cria(args.model, args.planner == "on")
    print(f"[sampling] {args.model}: "
          + "  ".join(f"{r}={dict(k)}" for r, k in spec.items()), flush=True)
    # SEEDED tasks start from existing code the model must read, not a blank directory. Every task
    # before this one was greenfield, which exercises research and creation and never touches the
    # machinery most of cria's measured footguns live in: reading a file it did not write, editing
    # it surgically, and reading its own gate output. The seed is committed so `git status` is clean
    # and the model's own diff is legible to it.
    seed = task_dir / "seed"
    if seed.is_dir():
        sh("cp", "-r", *[str(p) for p in seed.iterdir()], str(ws), timeout=120)
    sh("git", "-C", str(ws), "init", "-q")
    if seed.is_dir():
        sh("git", "-C", str(ws), "add", "-A")
        sh("git", "-C", str(ws), "-c", "user.email=suite@local", "-c", "user.name=suite",
           "commit", "-qm", "seed", timeout=120)
    before_sessions = set(p.name for p in CALLS_DIR.glob("2*"))
    installs_before = user_install_listing()

    env = _codex_env(dict(os.environ, **_isolated_installs(ws)))
    t0 = time.time()
    with open(log_path, "w") as lf:
        # stdin MUST be closed explicitly: `codex exec` reads stdin to EOF as "additional input"
        # BEFORE starting the turn, and after an interrupted turn it returns to reading stdin.
        # An inherited never-closing stdin (a live socket from the launch environment) froze two
        # cells for their full 30-minute walls with zero work — pre-banner, zero API calls.
        proc = subprocess.Popen(HARNESSES[args.harness](prompt), cwd=ws,
                                stdin=subprocess.DEVNULL,
                                stdout=lf, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
    def pause_run() -> bool:
        try:
            os.killpg(proc.pid, signal.SIGSTOP)
            return True
        except ProcessLookupError:
            return False

    def resume_run():
        try:
            os.killpg(proc.pid, signal.SIGCONT)
        except ProcessLookupError:
            pass

    def stop_run():
        resume_run()
        stop_process_group(proc)

    pacing = MilestonePacing(started_at=t0, interval_minutes=args.milestone_minutes,
                             budget_intervals=budget_intervals(task_dir))
    terminal = "exited"
    milestone_judgments = []

    while proc.poll() is None:
        if pacing.due(time.time()):
            minute = round(pacing.next_milestone / 60)
            pause_started = time.time()
            if not pause_run():
                terminal = "exited"
                break
            try:
                sys.path.insert(0, str(SUITE))
                import milestones
                checkpoint = milestones.create(run_id, minute, ws, task_dir)
                print(f"[milestone] {minute} active minutes -> {checkpoint}", flush=True)
                print("[milestone] waiting for the campaign agent's inference judgment", flush=True)
                verdict = milestones.wait(checkpoint)
            except BaseException:
                # Never strand the harness in SIGSTOP when packet creation, waiting, or the operator
                # session is interrupted. The judgment remains mandatory; this run aborts loudly.
                stop_run()
                raise
            finally:
                pacing.record_pause(time.time() - pause_started)
            milestone_judgments.append({"at_active_minutes": minute, **verdict})
            print(milestone_progress(verdict, minute), flush=True)
            outcome = milestone_terminal(verdict, minute, at_limit=pacing.at_limit)
            if outcome is not None:
                terminal = outcome
                stop_run()
                break
            pacing.advance()
            resume_run()
        time.sleep(2)
    t1 = time.time()
    if terminal == "exited" and t1 - t0 < 60:
        terminal = "crashed-early"

    new_sessions = [CALLS_DIR / n for n in
                    set(p.name for p in CALLS_DIR.glob("2*")) - before_sessions]
    # The primary directory is the one that carries the work, not the one that finished last.
    session_dir = max(new_sessions, key=lambda p: len(list(p.glob("*.response.json"))),
                      default=None) if new_sessions else None
    capture = collect_capture(new_sessions) if new_sessions else \
        {"calls": 0, "phases": {}, "avg_tok_s": None, "output_tokens_timed": 0}

    # EVIDENCE PRESERVATION (operator directive 2026-07-29): every run's artifacts are evidence
    # for cria improvements and are kept until reviewed. The /tmp workspace is copied to a
    # durable archive; the capture dir and harness log paths ride in the row. Nothing under
    # ~/.cria/suite is ever auto-cleaned.
    archive = Path.home() / ".cria" / "suite" / run_id
    archive.mkdir(parents=True, exist_ok=True)
    sh("cp", "-r", str(ws), str(archive / "workspace"), timeout=300)
    # SAY SO WHEN THE EVIDENCE IS GONE. `sh` does not check, so a failed copy was silent and
    # indistinguishable from a model that built nothing.
    workspace_lost = not ws.is_dir() or not (archive / "workspace").is_dir()

    if workspace_lost:
        print(f"[archive] WORKSPACE MISSING: {ws}", flush=True)

    row = {
        "run_id": run_id, "task": args.task, "model": args.model, "harness": args.harness,
        "planner": args.planner, "note": args.note, "sampling": spec,
        **({"level": args.level} if args.level is not None else {}),
        "started": t0, "wall_seconds": round(t1 - t0, 1),
        "active_seconds": round(pacing.active_elapsed(t1), 1), "terminal": terminal,
        "milestone_minutes": args.milestone_minutes,
        "budget_intervals": pacing.budget_intervals,
        "milestone_judgments": milestone_judgments,
        **capture,
        "assists": collect_assists(t0, t1),
        "workspace": str(ws),
        "archive": str(archive),
        "user_install_leak": sorted(user_install_listing() - installs_before),
        "capture_dir": str(session_dir) if session_dir else None,
        "capture_dirs": sorted(str(d) for d in new_sessions) or None,
        "harness_log": str(log_path),
    }
    throttled = throttled_mid_run(session_dir)
    if throttled:
        row["aborted"] = throttled
        print(f"[throttled] {throttled}")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps({k: row[k] for k in
                      ("run_id", "terminal", "wall_seconds", "calls", "avg_tok_s")}, indent=1))
    _freeze_usefulness_evidence(row)
    _refresh_grid(row)


def _freeze_usefulness_evidence(row: dict) -> None:
    """Save the judge's evidence packet NOW, while the workspace still exists.

    The usefulness judgment — "was real work done?", the question the operator actually cares about —
    is judged from a packet built by walking the archived workspace. The workspace is the perishable
    half: of 503 recorded runs, 455 had no verdict and only 138 of those still had a workspace on
    disk, so the rest can never be judged at all. Every BASE row that could still be judged already
    had been; the other 57 are gone for good, which is why the arms cannot be compared on the number
    that matters.

    Nothing in `suite/` deletes an archive, so the loss came from outside — and a mechanism that
    depends on 3.4 GB of trees surviving indefinitely is one that will keep losing runs. A few KB of
    text per run does not. Judging can then happen whenever, on whatever is left.

    Best-effort by construction: a packet that cannot be written must never fail a run that
    finished, and the row is already on disk by the time this runs."""
    try:
        sys.path.insert(0, str(SUITE))
        import usefulness
        out = usefulness.save_packet(row)
        if out is not None:
            print(f"[usefulness] evidence frozen -> {out}", flush=True)
    except Exception as e:                       # noqa: BLE001 — never fail a finished run
        print(f"[usefulness] could not freeze evidence: {e}", flush=True)


def _refresh_grid(row: dict | None = None) -> None:
    """Rewrite the operator grid from results.jsonl, here, where the row was just appended.

    The grid is the operator view and is refreshed automatically after every run.

    Best-effort and non-fatal: the run's RESULT is already durably on disk one line above, and a
    reporting step must never be able to fail a completed run."""
    # The campaign table is silent when no BATTERY rows exist, so an ordinary run does not touch it.
    # rows exist, so an ordinary ladder run does not touch it.
    try:
        sys.path.insert(0, str(SUITE))
        import battery_status
        if rs := battery_status.rows():
            battery_status.write_report(rs)
            print("[battery] refreshed docs/audits/battery-report.md")
        # A ROW THE GRID CANNOT SEE MUST SAY SO. `battery_status.rows()` keeps only rows whose note
        # starts with a counted prefix, and `cell()` then matches an arm token inside it — so a run
        # launched with free text in --note completes, gets judged, and is silently absent from the
        # operator's only view. Nothing is
        # rejected here — a deliberate one-off run is legitimate — but it is named (#3 is about
        # noise, not about hiding a fact the operator is about to act on).
        if row and not any(r.get("run_id") == row.get("run_id") for r in rs):
            print(f"[battery] NOT COUNTED in the grid: note {row.get('note')!r} does not start with one "
                  f"of {battery_status.COUNTED_PREFIXES}. A counted note looks like "
                  f"'{battery_status.NOTE_PREFIX} L<level> <model> <commit> p<rev>' — "
                  f"suite/battery_run.py composes it for you.")
    except Exception as e:  # noqa: BLE001
        print(f"[battery] refresh skipped: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
