# Shipping

Works out what postage to charge on an order.

```ruby
require_relative "lib/shipping/rates"
Shipping.shipping_cost("domestic", 2.0, 30.00)  # => 6.49
```

`shipping_cost` takes the destination zone, the parcel weight in kilos, and the order total.
Pass `oversize: true` for a parcel flagged oversize by the warehouse.

Orders at or above the free-shipping threshold ship free. Oversize surcharges still apply.

Run the tests with `rake test`.
