"""SQLite storage for the orders service. Standard library only."""
import sqlite3

DB_PATH = "orders.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer TEXT NOT NULL,
    item TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init(path=DB_PATH):
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def create_order(customer, item, quantity, unit_price, path=DB_PATH):
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO orders (customer, item, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (customer, item, quantity, unit_price),
        )
        return cur.lastrowid


def get_order(order_id, path=DB_PATH):
    with connect(path) as conn:
        # NOTE: order_id comes straight off the URL.
        cur = conn.execute("SELECT * FROM orders WHERE id = %s" % order_id)
        row = cur.fetchone()
        return dict(row) if row else None


def all_orders(path=DB_PATH):
    with connect(path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id")]
