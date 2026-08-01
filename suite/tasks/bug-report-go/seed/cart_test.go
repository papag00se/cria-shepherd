package cartsvc

import "testing"

func TestSubtotal(t *testing.T) {
	c := &Cart{Items: []Item{{"pen", 2.50, 4}, {"pad", 5.00, 1}}}
	if got := c.Subtotal(); got != 15.00 {
		t.Errorf("Subtotal() = %v, want 15.00", got)
	}
}

func TestTotalWithDiscount(t *testing.T) {
	c := &Cart{Items: []Item{{"pen", 10.00, 1}}, Code: "WELCOME10"}
	got, err := c.Total()
	if err != nil {
		t.Fatal(err)
	}
	if got != 9.72 {
		t.Errorf("Total() = %v, want 9.72", got)
	}
}

func TestUnknownCode(t *testing.T) {
	c := &Cart{Items: []Item{{"pen", 1.00, 1}}, Code: "NOPE"}
	if _, err := c.Total(); err == nil {
		t.Error("expected an error for an unknown code")
	}
}
