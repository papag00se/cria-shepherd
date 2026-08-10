# Shipping cost rules.
#
# Cost = base rate for the destination zone, plus per-kilo weight cost, plus surcharges.
# Orders at or above the free-shipping threshold ship free (surcharges still apply).

module Shipping
  ZONE_BASE = { "domestic" => 4.99, "eu" => 9.99, "international" => 19.99 }.freeze
  PER_KILO  = { "domestic" => 0.75, "eu" => 1.50, "international" => 3.25 }.freeze
  FREE_SHIPPING_THRESHOLD = 75.00
  OVERSIZE_SURCHARGE = 12.00
  OVERSIZE_KILOS = 20.0

  def self.shipping_cost(zone, weight_kilos, order_total, oversize: false)
    raise ArgumentError, "unknown zone: #{zone}" unless ZONE_BASE.key?(zone)
    raise ArgumentError, "weight cannot be negative" if weight_kilos.negative?

    surcharge = (oversize || weight_kilos > OVERSIZE_KILOS) ? OVERSIZE_SURCHARGE : 0.0

    return surcharge if order_total > FREE_SHIPPING_THRESHOLD

    base = ZONE_BASE[zone]
    weight_cost = PER_KILO[zone] * weight_kilos
    (base + weight_cost + surcharge).round(2)
  end
end
