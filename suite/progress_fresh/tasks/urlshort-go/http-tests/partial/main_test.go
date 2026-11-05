package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestShorten(t *testing.T) {
	mux := newMux(NewStore())
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest("GET", "/shorten?url=https://example.com", nil))
	if rec.Code != http.StatusOK || strings.TrimSpace(rec.Body.String()) == "" {
		t.Fatalf("bad response %d %q", rec.Code, rec.Body.String())
	}
}
