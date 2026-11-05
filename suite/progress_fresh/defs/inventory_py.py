TASK = dict(name="inventory-py", language="Python", seed={
"inventory/__init__.py": "",
"inventory/stock.py": '''"""Stock tracking."""
import csv


def load(path):
    with open(path, newline="") as f:
        return {r["sku"]: int(r["qty"]) for r in csv.DictReader(f)}


def low_stock(stock, threshold):
    """SKUs at or below the threshold."""
    return sorted(s for s, q in stock.items() if q < threshold)
''',
"inventory/cli.py": '''import argparse

from inventory import stock


def main(argv=None):
    p = argparse.ArgumentParser(prog="inventory")
    p.add_argument("csv")
    p.add_argument("--low", type=int, default=None, help="only SKUs below this quantity")
    args = p.parse_args(argv)
    data = stock.load(args.csv)
    for sku, qty in sorted(data.items()):
        if args.low is not None and not qty < args.low:
            continue
        print(f"{sku}\\t{qty}")


if __name__ == "__main__":
    main()
''',
"README.md": "# inventory\n\nPrints stock levels from a CSV with `sku,qty` columns.\n\n    python -m inventory.cli stock.csv --low 5\n",
"tests/test_stock.py": '''from inventory import stock


def test_low_stock_below():
    assert stock.low_stock({"a": 1, "b": 9}, 5) == ["a"]
''',
}, unrelated={"README.md": "# inventory\n\nPrints stock levels from a CSV with `sku,qty` columns (UTF-8).\n\n    python -m inventory.cli stock.csv --low 5\n"},
reqs=[
dict(id="low-boundary", text="Fix the off-by-one: a SKU whose quantity equals the threshold must be reported as low, both by stock.low_stock and by the CLI's --low filter.",
 partial={"inventory/stock.py": '''"""Stock tracking."""
import csv


def load(path):
    with open(path, newline="") as f:
        return {r["sku"]: int(r["qty"]) for r in csv.DictReader(f)}


def low_stock(stock, threshold):
    """SKUs at or below the threshold."""
    return sorted(s for s, q in stock.items() if q <= threshold)
'''},
 done={"inventory/stock.py": '''"""Stock tracking."""
import csv


def load(path):
    with open(path, newline="") as f:
        return {r["sku"]: int(r["qty"]) for r in csv.DictReader(f)}


def low_stock(stock, threshold):
    """SKUs at or below the threshold."""
    return sorted(s for s, q in stock.items() if q <= threshold)
''', "inventory/cli.py": '''import argparse

from inventory import stock


def main(argv=None):
    p = argparse.ArgumentParser(prog="inventory")
    p.add_argument("csv")
    p.add_argument("--low", type=int, default=None, help="only SKUs at or below this quantity")
    args = p.parse_args(argv)
    data = stock.load(args.csv)
    if args.low is not None:
        keep = set(stock.low_stock(data, args.low))
        data = {k: v for k, v in data.items() if k in keep}
    for sku, qty in sorted(data.items()):
        print(f"{sku}\\t{qty}")


if __name__ == "__main__":
    main()
'''}),
dict(id="json-flag", text="Add a --json flag to the CLI that prints the (optionally --low filtered) report as one JSON object mapping sku to quantity instead of tab-separated lines.",
 partial={"inventory/cli.py": '''import argparse
import json

from inventory import stock


def main(argv=None):
    p = argparse.ArgumentParser(prog="inventory")
    p.add_argument("csv")
    p.add_argument("--low", type=int, default=None, help="only SKUs below this quantity")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    data = stock.load(args.csv)
    if args.json and args.low is None:
        print(json.dumps(data))
        return
    for sku, qty in sorted(data.items()):
        if args.low is not None and not qty < args.low:
            continue
        print(f"{sku}\\t{qty}")


if __name__ == "__main__":
    main()
'''},
 done={"inventory/cli.py": '''import argparse
import json

from inventory import stock


def main(argv=None):
    p = argparse.ArgumentParser(prog="inventory")
    p.add_argument("csv")
    p.add_argument("--low", type=int, default=None, help="only SKUs below this quantity")
    p.add_argument("--json", action="store_true", help="print a JSON object sku -> qty")
    args = p.parse_args(argv)
    data = stock.load(args.csv)
    rows = {s: q for s, q in sorted(data.items()) if args.low is None or q < args.low}
    if args.json:
        print(json.dumps(rows))
        return
    for sku, qty in rows.items():
        print(f"{sku}\\t{qty}")


if __name__ == "__main__":
    main()
'''}),
dict(id="tests", text="Add tests in tests/test_stock.py for low_stock with a quantity exactly at, below and above the threshold, and for load() reading a real CSV file.",
 partial={"tests/test_stock.py": '''from inventory import stock


def test_low_stock_below():
    assert stock.low_stock({"a": 1, "b": 9}, 5) == ["a"]


def test_low_stock_above():
    assert stock.low_stock({"a": 10}, 5) == []


def test_low_stock_at():
    assert stock.low_stock({"a": 5}, 5) == ["a"]
'''},
 done={"tests/test_stock.py": '''from inventory import stock


def test_low_stock_below():
    assert stock.low_stock({"a": 1, "b": 9}, 5) == ["a"]


def test_low_stock_above():
    assert stock.low_stock({"a": 10}, 5) == []


def test_low_stock_at():
    assert stock.low_stock({"a": 5}, 5) == ["a"]


def test_load_reads_csv(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("sku,qty\\nx,3\\ny,0\\n")
    assert stock.load(str(f)) == {"x": 3, "y": 0}
'''}),
])
