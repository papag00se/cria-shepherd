#!/usr/bin/env python3
"""Is this box ready to run the matrix, so a cell measures the MODEL and not the environment?

A run gets 30 minutes. If the first `mvn test` spends eight of them downloading plugins, or
`composer require` fails because composer was never installed, the cell records a model failure that
is really a machine failure — and a call-by-call walk then hunts for a cria footgun that does not
exist. This checks the toolchains, and warms the caches that are cold on first use.

    python3 suite/preflight.py            # report
    python3 suite/preflight.py --warm     # report, and warm the package caches (slow, once)

Reports three states per toolchain: present, MISSING, or present-but-COLD (installed, but its first
real use in a workspace would hit the network).
"""
import argparse
import glob
import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
from pathlib import Path

SUITE = Path(__file__).resolve().parent

# tool -> (version probe, what it is needed for)
TOOLS = {
    "python3": (["python3", "--version"], "ada-handles, sqlite-inventory, the seeded Python tasks"),
    "pytest": (["python3", "-m", "pytest", "--version"], "every Python task's verifier"),
    "go": (["go", "version"], "handles-go, cart-billing-go"),
    "cargo": (["cargo", "--version"], "handles-rust, rust-toml-cli"),
    "node": (["node", "--version"], "handles-node, handles-cli-node"),
    "npm": (["npm", "--version"], "handles-node package scripts"),
    "ruby": (["ruby", "--version"], "handles-ruby"),
    "rspec": (["rspec", "--version"], "handles-ruby's verifier"),
    "php": (["php", "--version"], "handles-php"),
    "phpunit": (["phpunit", "--version"], "handles-php's verifier"),
    "composer": (["composer", "--version"], "PHP dependency install inside a run"),
    "mvn": (["mvn", "-v"], "handles-java"),
    # OPTIONAL: the containerise deliverable is scored by READING the Dockerfile (FROM + CMD), not
    # by building it. Docker Desktop's binary is on PATH under WSL but its engine is not exposed to
    # this distro, and requiring it would fail readiness over a check nothing performs.
    "docker": (["docker", "--version"], "OPTIONAL — handles-cli-node's Dockerfile is read, not built"),
    "unshare": (["unshare", "--version"], "the network block every live-test check depends on"),
}


# The synthetic tools cria advertises to the model. A package on the path with one of these names is
# something a model installed after mistaking a TOOL for a library, and it turns that rare mistake
# into an inexplicable one. Kept in sync by hand with cria/toolmenu.py — a short, stable list.
TOOL_NAMES = ("web_fetch", "web_search", "read_file", "write_file", "edit_file", "list_dir",
              "exec_command", "update_plan", "view_image")


def stale_suite_installs():
    """Packages a PREVIOUS run installed into the real user site-packages, still on sys.path.

    A run is `--yolo`: nothing stops the model running `pip install -e .` on its own workspace.
    That drops a `.pth` naming the run's `/tmp` directory into the user's site-packages, and it
    OUTLIVES the run — every later Python process on the box, including the next cell's tests and
    the verifier itself, imports the dead run's code.

    Found live on 2026-08-01: `__editable__.handle_resolver-0.1.0.pth` from a gemma4 run on 07-31
    was still resolving `import handle_resolver` to that run's temp directory two days later.

    run.py's `site_packages_leak` column records the DELTA across one run, which is the right thing
    for attributing a leak to the cell that caused it — and is blind by construction to a leak that
    was ALREADY there. This is the standing check the delta cannot be: it asks what is on the path
    right now, not what changed.
    """
    found = []
    try:
        user_site = site.getusersitepackages()
    except Exception:  # noqa: BLE001
        return found

    # A package whose name COLLIDES with one of cria's synthetic tool names. Measured 2026-08-01:
    # `web_fetch` — an unrelated third-party scraper off PyPI — sat here from 2026-07-23, installed
    # by some earlier --yolo run. Nine days later a model wrote `from web_fetch import web_fetch`
    # into its source (a rational mistake: `web_fetch` is a TOOL it is given), and instead of a
    # clean ModuleNotFoundError the import SUCCEEDED and bound a module, producing
    # "TypeError: 'module' object is not callable" — an error with no reachable explanation from
    # where the model stood. It burned ~12,000 characters of reasoning on that one line.
    # The install itself is now refused by dirguard; this catches the ones already on the box.
    for name in sorted(TOOL_NAMES):
        for suffix in ("", ".py"):
            p = os.path.join(user_site, name + suffix)
            if os.path.exists(p):
                found.append({"pth": p, "target": f"shadows cria's own `{name}` tool name",
                              "target_exists": True})

    for pth in sorted(glob.glob(os.path.join(user_site, "*.pth"))):
        try:
            body = open(pth, errors="replace").read()
        except OSError:
            continue
        for line in body.splitlines():
            target = line.strip()
            # A suite workspace is a mkdtemp under /tmp; anything pointing into a temp dir is by
            # definition not a durable install, whoever wrote it.
            if target.startswith("/tmp/"):
                found.append({"pth": pth, "target": target,
                              "target_exists": os.path.exists(target)})
    return found


def probe(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        first = (p.stdout or p.stderr or "").strip().splitlines()
        return p.returncode == 0, (first[0][:60] if first else "")
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


def warm():
    """Fetch what a first real use would fetch, so a run does not pay for it.

    Each is a throwaway project in a temp dir — nothing here touches a task's seed.
    """
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        if shutil.which("cargo"):
            (t / "warm-rs" / "src").mkdir(parents=True)
            (t / "warm-rs" / "Cargo.toml").write_text(
                '[package]\nname = "warm"\nversion = "0.1.0"\nedition = "2021"\n'
                '\n[dependencies]\ntoml = "0.8"\nserde = { version = "1", features = ["derive"] }\n')
            (t / "warm-rs" / "src" / "main.rs").write_text("fn main() {}\n")
            ok, _ = probe(["cargo", "build", "--quiet", "--manifest-path",
                           str(t / "warm-rs" / "Cargo.toml")])
            out.append(("cargo crates.io index + toml/serde", ok))
        if shutil.which("go"):
            (t / "warm-go").mkdir()
            (t / "warm-go" / "go.mod").write_text("module warm\n\ngo 1.22\n")
            (t / "warm-go" / "m.go").write_text("package main\n\nfunc main() {}\n")
            ok, _ = probe(["go", "build", "-C", str(t / "warm-go"), "./..."])
            out.append(("go build cache", ok))
        if shutil.which("npm"):
            ok, _ = probe(["npm", "--version"])
            out.append(("npm (no deps needed by the battery)", ok))
    return out


def live_services():
    """[(task, url, status)] for every task that declares a `live_probe` in its meta.

    A task whose deliverable must talk to a real service cannot be judged when that service is not
    answering. Measured need: thirteen back-to-back ladder runs got api.handle.me to start returning
    403 mid-run, and those runs were scored as ordinary failures — the model and cria both blamed
    for a throttle. The URL is declared in the TASK's meta, never in cria: cria must not know what
    api.handle.me is."""
    import urllib.error
    import urllib.request
    out = []
    for meta in sorted((SUITE / "tasks").glob("*/meta.toml")):
        url = ""
        for line in meta.read_text().splitlines():
            if line.strip().startswith("live_probe"):
                url = line.split("=", 1)[1].strip().strip('"\'')
        if not url:
            continue
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception:  # noqa: BLE001 — offline / DNS / TLS all mean "cannot judge this task"
            status = 0
        out.append((meta.parent.name, url, status))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warm", action="store_true", help="also warm package caches (slow, once)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows, missing = [], []
    for name, (argv, why) in TOOLS.items():
        ok, ver = probe(argv)
        optional = why.startswith("OPTIONAL")
        rows.append({"tool": name, "ok": ok, "optional": optional, "version": ver,
                     "needed_for": why})
        if not ok and not optional:
            missing.append(name)

    stale = stale_suite_installs()
    ready = not missing and not stale

    if args.json:
        print(json.dumps({"ready": ready, "missing": missing,
                          "stale_installs": stale, "tools": rows}, indent=1))
    else:
        print(f"{'tool':10s} {'state':8s} {'version':32s} needed for")
        print("-" * 100)
        for r in rows:
            state = "ok" if r["ok"] else ("absent" if r["optional"] else "MISSING")
            print(f"{r['tool']:10s} {state:8s} "
                  f"{r['version']:32s} {r['needed_for']}")
        print()
        for s in stale:
            print(f"LEAKED INSTALL  {s['pth']}\n"
                  f"                -> {s['target']} "
                  f"({'still present' if s['target_exists'] else 'gone'})")
        if stale:
            print("  A previous run installed itself into your real site-packages. It is on the\n"
                  "  path for every Python process, so the next cell's imports may resolve to it.\n"
                  "  Remove the .pth and its dist-info before running.\n")
        live = live_services()
        for task, url, status in live:
            mark = "ok  " if status == 200 else "FAIL"
            print(f"  {mark} live service for {task}: {url} -> HTTP {status or 'unreachable'}")
        down = [t for t, _u, st in live if st != 200]
        if down:
            ready = False
        if ready:
            print("READY")
        else:
            reasons = []
            if missing:
                reasons.append(f"missing: {', '.join(missing)}")
            if stale:
                reasons.append(f"{len(stale)} leaked install(s) on sys.path")
            if down:
                reasons.append("live service not answering for: " + ", ".join(down)
                               + " — a task that must call it cannot be judged; wait and retry")
            print(f"NOT READY — {'; '.join(reasons)}")

    if args.warm:
        print("\nwarming caches (first use in a run then costs nothing):")
        for what, ok in warm():
            print(f"  {'ok  ' if ok else 'FAIL'} {what}")

    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
