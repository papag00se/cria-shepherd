package cartsvc

import "fmt"

// Discount codes the shop accepts. PercentOff is applied to the subtotal.
var Discounts = map[string]float64{
	"WELCOME10": 0.10,
	"SUMMER25":  0.25,
	"VIP50":     0.50,
}

type Item struct {
	Name     string
	Price    float64
	Quantity int
}

// Cart totals a set of items and applies at most one discount code.
type Cart struct {
	Items []Item
	Code  string
}

func (c *Cart) Subtotal() float64 {
	var sum float64
	for _, it := range c.Items {
		sum += it.Price * float64(it.Quantity)
	}
	return sum
}

// Total applies the discount code, then adds 8% sales tax, rounded to cents.
func (c *Cart) Total() (float64, error) {
	sub := c.Subtotal()
	if c.Code != "" {
		pct, ok := Discounts[c.Code]
		if !ok {
			return 0, fmt.Errorf("unknown discount code: %s", c.Code)
		}
		sub = sub - sub*pct
	}
	taxed := sub * 1.08
	return float64(int(taxed*100)) / 100, nil
}
