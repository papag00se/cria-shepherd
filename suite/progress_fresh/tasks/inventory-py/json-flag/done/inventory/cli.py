import argparse
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
        print(f"{sku}\t{qty}")


if __name__ == "__main__":
    main()
