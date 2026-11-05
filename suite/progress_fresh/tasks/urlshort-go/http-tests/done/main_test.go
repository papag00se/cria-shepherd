package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestShortenThenRedirect(t *testing.T) {
	mux := newMux(NewStore())
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest("GET", "/shorten?url=https://example.com", nil))
	code := strings.TrimSpace(rec.Body.String())
	if rec.Code != http.StatusOK || code == "" {
		t.Fatalf("bad shorten response %d %q", rec.Code, rec.Body.String())
	}
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest("GET", "/r/"+code, nil))
	if rec.Code != http.StatusFound || rec.Header().Get("Location") != "https://example.com" {
		t.Fatalf("redirect = %d %q", rec.Code, rec.Header().Get("Location"))
	}
}

func TestUnknownCode404(t *testing.T) {
	rec := httptest.NewRecorder()
	newMux(NewStore()).ServeHTTP(rec, httptest.NewRequest("GET", "/r/nope", nil))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("code = %d", rec.Code)
	}
}
