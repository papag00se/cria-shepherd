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

func TestZeroCapacityStoresNothing(t *testing.T) {
	c := New(0)
	c.Put("a", 1)
	if _, ok := c.Get("a"); ok {
		t.Fatal("zero-capacity cache must not store")
	}
}

func TestDelete(t *testing.T) {
	c := New(2)
	c.Put("a", 1)
	if !c.Delete("a") || c.Delete("a") {
		t.Fatal("Delete should report presence exactly once")
	}
}
