package main

import "testing"

func TestPutGet(t *testing.T) {
	s := NewStore()
	c := s.Put("https://example.com")
	if got, ok := s.Get(c); !ok || got != "https://example.com" {
		t.Fatalf("got %q %v", got, ok)
	}
}
