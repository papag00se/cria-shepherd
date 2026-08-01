"""Nightly supplier feed importer.

Reads supplier CSVs and produces a per-SKU summary. Parallel workers are disabled — turning them
on made the totals come out different every run and nobody got to the bottom of it.
"""
import csv
import os
import threading

WORKERS_ENABLED = False   # see module docstring
NUM_WORKERS = 4

# Running totals, shared across workers when they are enabled.
totals = {}
row_count = 0


def _known_skus(rows):
    """Every SKU seen so far, as a list."""
    seen = []
    for r in rows:
        if r["sku"] not in seen:          # linear scan, once per row
            seen.append(r["sku"])
    return seen


def _accumulate(row):
    global row_count
    sku = row["sku"]
    value = int(row["quantity"]) * float(row["unit_price"])
    if sku in totals:
        totals[sku] = totals[sku] + value
    else:
        totals[sku] = value
    row_count = row_count + 1


def _worker(rows):
    for row in rows:
        _accumulate(row)


def load(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def summarize(path):
    """Import one feed file and return (per-sku totals, rows imported)."""
    global totals, row_count
    totals, row_count = {}, 0
    rows = load(path)

    # Deduplicating the SKU list this way is O(n^2) — it was fine on the first feeds we got.
    skus = _known_skus(rows)

    if WORKERS_ENABLED:
        chunk = max(1, len(rows) // NUM_WORKERS)
        threads = [threading.Thread(target=_worker, args=(rows[i:i + chunk],))
                   for i in range(0, len(rows), chunk)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    else:
        _worker(rows)

    return {"skus": len(skus), "totals": totals, "rows": row_count}


def main(path):
    result = summarize(path)
    print(f"imported {result['rows']} rows covering {result['skus']} SKUs")
    for sku, value in sorted(result["totals"].items()):
        print(f"  {sku}: {value:.2f}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "feed.csv"))
