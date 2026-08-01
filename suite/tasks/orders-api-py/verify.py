#!/usr/bin/env python3
"""Verifier for orders-api-py — categories 8 (new endpoint), 9 (database change), 5 (integration
tests), 11 (security fix).

The seed is a running stdlib HTTP service over SQLite with a REAL SQL injection: `get_order` builds
its WHERE clause with `%s`, so `id=1 OR 1=1` returns a row. Everything is scored by driving the
service over HTTP, because "the function returns the right thing" is not the same claim as "the
route works".

Four points:

  1. GET /customers/<name>/orders returns that customer's orders and a total
  2. the schema gained `status` (default 'pending') and an index on customer, AND an OLD database
     written by the seed still works — the prompt asks for that explicitly and "works only on a
     fresh db" is the usual half-done shape
  3. the model's own tests go through HTTP, not just the db module
  4. the injection is gone — probed through the running service, and ordinary lookups still work

Every check starts the service on a free port against a temp database, so nothing depends on the
model's own test setup.
"""
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 180


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(cmd, cwd, timeout=TIMEOUT, env=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **(env or {})})
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return -2, f"VERIFIER-EXEC-ERROR: {e}"


class Service:
    """Starts the model's service on a free port against a PREPARED database.

    The seed reads `orders.db` relative to the working directory — no env var, no argument — so the
    prepared database is installed AT that path and any real one is set aside and restored. Passing
    it by environment only (the first cut of this) meant the service quietly used its own database
    and every probe failed for a reason that had nothing to do with the model's work. The env vars
    are still set, as a courtesy to a solution that made the path configurable.
    """

    STARTERS = [
        [sys.executable, "-m", "orders.app"],
        [sys.executable, "-m", "orders"],
        [sys.executable, "app.py"],
        [sys.executable, "orders/app.py"],
    ]

    def __init__(self, ws, db_path):
        self.ws, self.db_path, self.proc, self.port = ws, db_path, None, None
        self.installed = ws / "orders.db"
        self.stashed = ws / "_orders.db.verifier-stash"

    def __enter__(self):
        if self.installed.exists():
            self.installed.replace(self.stashed)
        shutil.copy(self.db_path, self.installed)
        for starter in self.STARTERS:
            port = free_port()
            proc = subprocess.Popen(starter + [str(port)], cwd=self.ws,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env={**os.environ, "ORDERS_DB": self.db_path,
                                                    "DB_PATH": self.db_path})
            for _ in range(40):
                if proc.poll() is not None:
                    break
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/orders/1", timeout=1)
                    self.proc, self.port = proc, port
                    return self
                except urllib.error.HTTPError:
                    self.proc, self.port = proc, port     # answered — that is up
                    return self
                except Exception:  # noqa: BLE001
                    time.sleep(0.25)
            proc.kill()
        return self

    def __exit__(self, *_):
        if self.proc:
            self.proc.kill()
        # Read back what the service wrote, so schema checks see the live file, then restore.
        if self.installed.exists():
            shutil.copy(self.installed, self.db_path)
            self.installed.unlink()
        if self.stashed.exists():
            self.stashed.replace(self.installed)

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except Exception as e:  # noqa: BLE001
            return 0, str(e)

    def post(self, path, payload):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except Exception as e:  # noqa: BLE001
            return 0, str(e)


def seed_old_db(path):
    """A database in the SEED's shape — no status column, no index. Live data, in other words."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            item TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL
        );
        INSERT INTO orders (customer, item, quantity, unit_price)
        VALUES ('alice', 'pen', 3, 2.50), ('alice', 'pad', 1, 5.00), ('bob', 'ink', 2, 4.00);
    """)
    conn.commit()
    conn.close()


def main() -> None:
    ws = Path(sys.argv[1]).resolve()
    r = {"task": "orders-api-py", "score": 0.0, "max_score": 4.0, "success": False, "parts": {}}
    tmp = tempfile.mkdtemp()

    # --- 1 + 2: an OLD database must survive, and the new route must work against it.
    old_db = os.path.join(tmp, "old.db")
    seed_old_db(old_db)
    route_ok, route_detail = False, "service did not start"
    mig_ok, mig_detail = False, "service did not start"
    with Service(ws, old_db) as svc:
        if svc.port:
            code, body = svc.get("/customers/alice/orders")
            has_orders = "pen" in body and "pad" in body
            total = re.search(r"1[12]\.5", body)          # 3*2.50 + 1*5.00 = 12.50
            route_ok = code == 200 and has_orders and bool(total)
            route_detail = f"GET /customers/alice/orders -> {code}, alice's items: {has_orders}, total present: {bool(total)}"

            # the old rows survived, and the schema really changed
            code2, body2 = svc.get("/orders/1")
            survived = code2 == 200 and "alice" in body2
            live = sqlite3.connect(str(svc.installed if svc.installed.exists() else old_db))
            cols = {row[1] for row in live.execute("PRAGMA table_info(orders)")}
            indexed = False
            for i in live.execute("PRAGMA index_list(orders)").fetchall():
                named = [c[2] for c in live.execute(f"PRAGMA index_info({i[1]})").fetchall()]
                if "customer" in named:      # sqlite makes its OWN index for AUTOINCREMENT — a bare
                    indexed = True           # "an index exists" test passes on the seed for free
            live.close()
            mig_ok = survived and "status" in cols and indexed
            mig_detail = (f"old rows readable: {survived}, status column: {'status' in cols}, "
                          f"index on customer: {indexed}")
    r["parts"]["customer_orders_route"] = {"ok": route_ok, "detail": route_detail}
    r["parts"]["schema_migrated"] = {"ok": mig_ok, "detail": mig_detail}

    # --- 3: the model's tests must actually go through HTTP
    code, out = run([sys.executable, "-m", "pytest", "-q", "--tb=short"], ws)
    suite_green = code == 0 and bool(re.search(r"(\d+) passed", out))
    test_text = " ".join(p.read_text(errors="replace")
                         for p in list(ws.rglob("test_*.py")) + list(ws.rglob("*_test.py"))
                         if ".git" not in p.parts)
    over_http = any(w in test_text for w in ("urlopen", "http://", "requests.get", "HTTPConnection",
                                             "urllib.request", "httpx"))
    r["parts"]["integration_tests"] = {
        "ok": suite_green and over_http,
        "detail": f"suite green: {suite_green}; tests make real HTTP calls: {over_http}"}

    # --- 4: the injection, probed through the running service
    inj_db = os.path.join(tmp, "inj.db")
    seed_old_db(inj_db)
    inj_probe = """
import json, sys
sys.path.insert(0, {ws!r})
from orders import db
out = {{}}
try:
    out["normal"] = bool(db.get_order(1, path={dbp!r}))
except Exception as e:
    out["normal"] = "ERR:" + type(e).__name__
for name, payload in (("or", "1 OR 1=1"), ("union", "1 UNION SELECT 1,2,3,4,5"),
                      ("drop", "1; DROP TABLE orders")):
    try:
        out[name] = bool(db.get_order(payload, path={dbp!r}))
    except Exception:
        out[name] = False          # rejected/errored = not exploitable
try:
    out["alive"] = bool(db.all_orders(path={dbp!r}))
except Exception:
    out["alive"] = False
print("VERIFY_JSON=" + json.dumps(out))
"""
    code, out = run([sys.executable, "-c",
                     inj_probe.format(ws=str(ws), dbp=inj_db)], ws)
    m = re.search(r"VERIFY_JSON=(\{.*\})", out)
    probe = json.loads(m.group(1)) if m else {}
    normal_ok = probe.get("normal") is True
    exploitable = any(probe.get(k) is True for k in ("or", "union", "drop"))
    inj_ok = normal_ok and not exploitable and probe.get("alive") is True
    inj_detail = (f"normal lookup works: {normal_ok}, exploitable: {exploitable}, "
                  f"table intact: {probe.get('alive')}" if probe
                  else f"probe failed: {out.strip()[-80:]}")
    r["parts"]["sql_injection_fixed"] = {"ok": inj_ok, "detail": inj_detail}

    r["score"] = float(sum(1 for p in r["parts"].values() if p["ok"]))
    r["success"] = r["score"] == r["max_score"]
    print(json.dumps(r))


if __name__ == "__main__":
    main()
