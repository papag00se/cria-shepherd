require "minitest/autorun"
require_relative "../lib/shipping/rates"

class TestRates < Minitest::Test
  def test_domestic_light_parcel
    assert_equal 6.49, Shipping.shipping_cost("domestic", 2.0, 30.00)
  end

  def test_eu_heavier_parcel
    assert_equal 15.99, Shipping.shipping_cost("eu", 4.0, 50.00)
  end

  def test_free_shipping_at_the_threshold
    # An order EXACTLY at the threshold ships free.
    assert_equal 0.0, Shipping.shipping_cost("domestic", 3.0, 75.00)
  end

  def test_free_shipping_above_the_threshold
    assert_equal 0.0, Shipping.shipping_cost("international", 5.0, 120.00)
  end

  def test_oversize_surcharge_still_applies_to_free_shipping
    assert_equal 12.00, Shipping.shipping_cost("domestic", 25.0, 200.00)
  end

  def test_unknown_zone_rejected
    assert_raises(ArgumentError) { Shipping.shipping_cost("moon", 1.0, 10.00) }
  end

  def test_negative_weight_rejected
    assert_raises(ArgumentError) { Shipping.shipping_cost("domestic", -1.0, 10.00) }
  end
end
