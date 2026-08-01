package cartsvc

import "testing"

// Hidden regression tests — cases where TRUNCATION and ROUNDING differ. Copied in only at scoring
// time, so nothing in the workspace hints at the exact inputs during the run.
func TestReportedCartRoundsUp(t *testing.T) {
	c := &Cart{Items: []Item{{"widget", 19.99, 3}}, Code: "SUMMER25"}
	got, err := c.Total()
	if err != nil {
		t.Fatal(err)
	}
	if got != 48.58 {
		t.Errorf("the reported cart: Total() = %v, want 48.58", got)
	}
}

func TestRoundingAcrossManyCarts(t *testing.T) {
	cases := []struct {
		price float64
		qty   int
		code  string
		want  float64
	}{
		{19.99, 3, "SUMMER25", 48.58},
		{7.77, 7, "WELCOME10", 52.87},
		{3.33, 3, "", 10.79},
		{1.11, 1, "VIP50", 0.60},
		{99.95, 2, "SUMMER25", 161.92},
	}
	for _, tc := range cases {
		c := &Cart{Items: []Item{{"x", tc.price, tc.qty}}, Code: tc.code}
		got, err := c.Total()
		if err != nil {
			t.Fatalf("%v: %v", tc, err)
		}
		if got != tc.want {
			t.Errorf("price=%v qty=%d code=%q: Total() = %v, want %v",
				tc.price, tc.qty, tc.code, got, tc.want)
		}
	}
}

// The fix must not smuggle in a behaviour change: an unknown code is still an error.
func TestUnknownCodeStillErrors(t *testing.T) {
	c := &Cart{Items: []Item{{"x", 1.00, 1}}, Code: "BOGUS"}
	if _, err := c.Total(); err == nil {
		t.Error("expected an error for an unknown code")
	}
}
