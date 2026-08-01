import pytest

from shipping.rates import shipping_cost


def test_domestic_light_parcel():
    assert shipping_cost("domestic", 2.0, 30.00) == 6.49


def test_eu_heavier_parcel():
    assert shipping_cost("eu", 4.0, 50.00) == 15.99


def test_free_shipping_at_the_threshold():
    # An order EXACTLY at the threshold ships free.
    assert shipping_cost("domestic", 3.0, 75.00) == 0.0


def test_free_shipping_above_the_threshold():
    assert shipping_cost("international", 5.0, 120.00) == 0.0


def test_oversize_surcharge_still_applies_to_free_shipping():
    assert shipping_cost("domestic", 25.0, 200.00) == 12.00


def test_unknown_zone_rejected():
    with pytest.raises(ValueError):
        shipping_cost("moon", 1.0, 10.00)


def test_negative_weight_rejected():
    with pytest.raises(ValueError):
        shipping_cost("domestic", -1.0, 10.00)
