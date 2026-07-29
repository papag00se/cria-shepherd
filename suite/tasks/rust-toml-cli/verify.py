#!/usr/bin/env python3
"""Deterministic verifier for rust-toml-cli. Exercises the pinned `cargo run -- <file> <path>`
contract with a fixture, error behavior on a missing key, and `cargo test`. Cargo needs network
for the first crate fetch and real compile time — generous timeouts."""

import json
import subprocess
import sys
from pathlib import Path

FIXTURE = """[server]
port = 8080
name = "edge-1"

[server.limits]
max_conn = 250
"""


def run(cmd, cwd, timeout=600):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return -2, "", f"VERIFIER-EXEC-ERROR: {e}"


def main(ws: Path) -> dict:
    r = {"task": "rust-toml-cli", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}
    (ws / "vfixture.toml").write_text(FIXTURE)

    # 1) Builds at all (separate point: a compiling Rust project is real work for a small model).
    code, _, err = run(["cargo", "build", "--quiet"], ws)
    r["parts"]["builds"] = {"ok": code == 0, "detail": err.strip()[-150:] if code != 0 else "clean build"}

    # 2) Pinned lookup contract: nested int, string, deep table.
    ok_n = 0
    checks = [("server.port", "8080"), ("server.name", "edge-1"), ("server.limits.max_conn", "250")]
    last = ""
    for key, want in checks:
        code, out, err = run(["cargo", "run", "--quiet", "--", "vfixture.toml", key], ws, timeout=300)
        got = out.strip().strip('"')
        if code == 0 and want in got:
            ok_n += 1
        last = f"{key} → exit={code} out={got[:40]!r}"
    r["parts"]["lookup"] = {"ok": ok_n == len(checks), "detail": f"{ok_n}/{len(checks)} lookups; last: {last}"}

    # 3) Missing key → stderr + nonzero exit (the pinned error contract). GATED on a working
    #    build — in a broken/empty project `cargo run` fails for its own reasons, which must not
    #    score as the error contract (the negative control caught exactly that).
    if r["parts"]["builds"]["ok"]:
        code, out, err = run(["cargo", "run", "--quiet", "--", "vfixture.toml", "no.such.key"], ws, timeout=300)
        err_ok = code not in (0, -1, -2) and bool(err.strip() or not out.strip())
        r["parts"]["error_contract"] = {"ok": err_ok, "detail": f"missing key → exit={code}"}
    else:
        r["parts"]["error_contract"] = {"ok": False, "detail": "skipped: project does not build"}

    # 4) cargo test passes with ≥1 test; README covers build/use/test (half point each folded
    #    into one part to keep the 4-point scale).
    code, out, err = run(["cargo", "test", "--quiet"], ws)
    tests_ok = code == 0 and ("test result: ok" in out + err) and "0 passed" not in (out + err).split("test result")[0][-40:]
    readme = next((p for p in ws.iterdir() if p.name.lower().startswith("readme")), None)
    readme_ok = bool(readme) and all(w in readme.read_text(errors="replace").lower()
                                     for w in ("build", "test"))
    r["parts"]["tests_and_readme"] = {"ok": tests_ok and readme_ok,
                                      "detail": f"cargo test ok={tests_ok}, README ok={readme_ok}"}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    return r


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]).resolve()), indent=1))
