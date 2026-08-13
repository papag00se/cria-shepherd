package cartsvc

import (
	"fmt"
	"math"
	"strconv"
	"testing"
)

// Hidden regression tests — cases where TRUNCATION and ROUNDING differ. Copied in only at scoring
// time, so nothing in the workspace hints at the exact inputs during the run.
//
// TYPE-AGNOSTIC ON PURPOSE. These used to compare `got != 48.58` directly, which only compiles when
// Total() returns float64 — and the task tells the model to stop doing money arithmetic in floating
// point. Return a decimal, as the task plainly implies, and this file failed to COMPILE, taking the
// check down with it. Both models did exactly that and both were failed by the instrument rather
// than by their work. What the task asks for is the right total; the return type is not something
// it names, so `money` reads the value through fmt and compares numerically (operator ruling: a
// check may only fail a run over the property the task actually asks for).

// money renders any numeric-ish value — float64, a decimal type, anything with a String method —
// and parses it back, so the comparison works whatever Total() was changed to return.
func money(t *testing.T, v interface{}) float64 {
	t.Helper()
	f, err := strconv.ParseFloat(fmt.Sprintf("%v", v), 64)
	if err != nil {
		t.Fatalf("Total() returned %v, which is not a number: %v", v, err)
	}
	return f
}

// A cent either way. Money compared to the cent is the whole point of the task.
func sameMoney(a, b float64) bool { return math.Abs(a-b) < 0.005 }
func TestReportedCartRoundsUp(t *testing.T) {
	c := &Cart{Items: []Item{{"widget", 19.99, 3}}, Code: "SUMMER25"}
	got, err := c.Total()
	if err != nil {
		t.Fatal(err)
	}
	if !sameMoney(money(t, got), 48.58) {
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
		if !sameMoney(money(t, got), tc.want) {
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
