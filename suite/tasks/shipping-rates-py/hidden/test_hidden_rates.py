"""Hidden contract tests: the SAME rules at inputs the model never saw, plus the new zone.

Special-casing the visible numbers passes the visible suite and fails here.
"""
import sys

sys.path.insert(0, ".")

import pytest  # noqa: E402

from shipping.rates import shipping_cost  # noqa: E402

ZONES = ("domestic", "eu", "international", "express")


def test_threshold_is_inclusive_for_every_zone():
    for zone in ZONES:
        assert shipping_cost(zone, 1.0, 75.0) == 0.0, zone


def test_just_below_the_threshold_still_charges():
    assert shipping_cost("domestic", 2.0, 74.99) == 6.49


def test_ordinary_pricing_is_unchanged():
    assert shipping_cost("domestic", 0.0, 10.0) == 4.99
    assert shipping_cost("international", 2.0, 10.0) == 26.49


def test_oversize_surcharge_survives_free_shipping():
    assert shipping_cost("eu", 30.0, 75.0) == 12.00


def test_express_zone_pricing():
    # 14.99 base + 2.50/kilo, same rules as everyone else.
    assert shipping_cost("express", 0.0, 10.0) == 14.99
    assert shipping_cost("express", 4.0, 10.0) == 24.99


def test_express_obeys_free_shipping_and_oversize():
    assert shipping_cost("express", 2.0, 80.0) == 0.0
    assert shipping_cost("express", 25.0, 200.0) == 12.00


def test_unknown_zone_still_rejected():
    with pytest.raises(ValueError):
        shipping_cost("moon", 1.0, 10.0)
