import argparse

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
        print(f"{sku}\t{qty}")


if __name__ == "__main__":
    main()
