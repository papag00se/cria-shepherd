import argparse

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
        print(f"{sku}\t{qty}")


if __name__ == "__main__":
    main()
