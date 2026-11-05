"""Stock tracking."""
import csv


def load(path):
    with open(path, newline="") as f:
        return {r["sku"]: int(r["qty"]) for r in csv.DictReader(f)}


def low_stock(stock, threshold):
    """SKUs at or below the threshold."""
    return sorted(s for s, q in stock.items() if q <= threshold)
