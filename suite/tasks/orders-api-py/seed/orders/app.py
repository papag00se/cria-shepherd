"""A tiny HTTP API over the orders table. Standard library only.

Routes:
  POST /orders            {"customer","item","quantity","unit_price"} -> {"id": N}
  GET  /orders/<id>       -> the order
"""
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import db

ORDER_RE = re.compile(r"^/orders/([^/]+)$")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        m = ORDER_RE.match(self.path)
        if m:
            order = db.get_order(m.group(1))
            if order is None:
                return self._send(404, {"error": "not found"})
            return self._send(200, order)
        self._send(404, {"error": "no such route"})

    def do_POST(self):
        if self.path != "/orders":
            return self._send(404, {"error": "no such route"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "invalid json"})
        try:
            oid = db.create_order(payload["customer"], payload["item"],
                                  int(payload["quantity"]), float(payload["unit_price"]))
        except (KeyError, TypeError, ValueError):
            return self._send(400, {"error": "missing or invalid fields"})
        self._send(201, {"id": oid})

    def log_message(self, *_args):
        pass


def serve(port=8080, path=db.DB_PATH):
    db.DB_PATH = path
    db.init(path)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8080)
