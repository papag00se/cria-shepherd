"""Shipping cost rules.

Cost = base rate for the destination zone, plus per-kilo weight cost, plus surcharges.
Orders at or above the free-shipping threshold ship free (surcharges still apply).
"""

ZONE_BASE = {"domestic": 4.99, "eu": 9.99, "international": 19.99}
PER_KILO = {"domestic": 0.75, "eu": 1.50, "international": 3.25}
FREE_SHIPPING_THRESHOLD = 75.00
OVERSIZE_SURCHARGE = 12.00
OVERSIZE_KILOS = 20.0


def shipping_cost(zone, weight_kilos, order_total, oversize=False):
    if zone not in ZONE_BASE:
        raise ValueError(f"unknown zone: {zone}")
    if weight_kilos < 0:
        raise ValueError("weight cannot be negative")

    surcharge = OVERSIZE_SURCHARGE if (oversize or weight_kilos > OVERSIZE_KILOS) else 0.0

    if order_total > FREE_SHIPPING_THRESHOLD:
        return surcharge

    base = ZONE_BASE[zone]
    weight_cost = PER_KILO[zone] * weight_kilos
    return round(base + weight_cost + surcharge, 2)
