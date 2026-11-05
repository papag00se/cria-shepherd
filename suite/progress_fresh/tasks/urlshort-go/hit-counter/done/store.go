package main

import (
	"crypto/sha1"
	"encoding/hex"
	"sync"
)

type Store struct {
	mu   sync.Mutex
	urls map[string]string
	hits map[string]int
}

func NewStore() *Store { return &Store{urls: map[string]string{}, hits: map[string]int{}} }

func (s *Store) Put(target string) string {
	sum := sha1.Sum([]byte(target))
	code := hex.EncodeToString(sum[:])[:6]
	s.mu.Lock()
	s.urls[code] = target
	s.mu.Unlock()
	return code
}

func (s *Store) Get(code string) (string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	t, ok := s.urls[code]
	return t, ok
}

// Follow returns the target and counts one hit.
func (s *Store) Follow(code string) (string, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	t, ok := s.urls[code]
	if ok {
		s.hits[code]++
	}
	return t, ok
}

func (s *Store) Hits(code string) (int, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.urls[code]
	return s.hits[code], ok
}
