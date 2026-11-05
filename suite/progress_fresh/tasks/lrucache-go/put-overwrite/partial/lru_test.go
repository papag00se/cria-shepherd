package lru

import "testing"

func TestEvictsOldest(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	c.Put("b", 2)
	c.Put("c", 3)
	if _, ok := c.Get("a"); ok {
		t.Fatal("a should be evicted")
	}
}

func TestPutOverwritesValue(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	c.Put("a", 9)
	if v, _ := c.Get("a"); v != 9 {
		t.Fatalf("a = %d, want 9", v)
	}
}
