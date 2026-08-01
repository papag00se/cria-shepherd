import os
import tempfile

from orders import db


def _tmpdb():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init(path)
    return path


def test_create_and_get():
    p = _tmpdb()
    oid = db.create_order("alice", "pen", 3, 2.50, path=p)
    got = db.get_order(oid, path=p)
    assert got["customer"] == "alice"
    assert got["quantity"] == 3


def test_all_orders():
    p = _tmpdb()
    db.create_order("alice", "pen", 1, 1.0, path=p)
    db.create_order("bob", "pad", 2, 3.0, path=p)
    assert len(db.all_orders(path=p)) == 2
