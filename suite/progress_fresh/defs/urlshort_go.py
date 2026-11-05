TASK = dict(name="urlshort-go", language="Go", seed={
"go.mod": "module example.com/urlshort\n\ngo 1.22\n",
"store.go": '''package main

import (
	"crypto/sha1"
	"encoding/hex"
	"sync"
)

type Store struct {
	mu   sync.Mutex
	urls map[string]string
}

func NewStore() *Store { return &Store{urls: map[string]string{}} }

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
''',
"main.go": '''package main

import (
	"fmt"
	"log"
	"net/http"
)

func newMux(s *Store) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/shorten", func(w http.ResponseWriter, r *http.Request) {
		target := r.URL.Query().Get("url")
		fmt.Fprintln(w, s.Put(target))
	})
	mux.HandleFunc("/r/", func(w http.ResponseWriter, r *http.Request) {
		t, ok := s.Get(r.URL.Path[len("/r/"):])
		if !ok {
			http.NotFound(w, r)
			return
		}
		http.Redirect(w, r, t, http.StatusFound)
	})
	return mux
}

func main() {
	log.Fatal(http.ListenAndServe(":8080", newMux(NewStore())))
}
''',
"store_test.go": '''package main

import "testing"

func TestPutGet(t *testing.T) {
	s := NewStore()
	c := s.Put("https://example.com")
	if got, ok := s.Get(c); !ok || got != "https://example.com" {
		t.Fatalf("got %q %v", got, ok)
	}
}
''',
}, unrelated={"go.mod": "module example.com/urlshort\n\ngo 1.23\n"},
reqs=[
dict(id="validate-url", text="POST-free validation: /shorten must answer 400 Bad Request (and store nothing) when the url query parameter is empty or is not an absolute http/https URL.",
 partial={"main.go": '''package main

import (
	"fmt"
	"log"
	"net/http"
)

func newMux(s *Store) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/shorten", func(w http.ResponseWriter, r *http.Request) {
		target := r.URL.Query().Get("url")
		if target == "" {
			http.Error(w, "missing url", http.StatusBadRequest)
			return
		}
		fmt.Fprintln(w, s.Put(target))
	})
	mux.HandleFunc("/r/", func(w http.ResponseWriter, r *http.Request) {
		t, ok := s.Get(r.URL.Path[len("/r/"):])
		if !ok {
			http.NotFound(w, r)
			return
		}
		http.Redirect(w, r, t, http.StatusFound)
	})
	return mux
}

func main() {
	log.Fatal(http.ListenAndServe(":8080", newMux(NewStore())))
}
'''},
 done={"main.go": '''package main

import (
	"fmt"
	"log"
	"net/http"
	"net/url"
)

func validTarget(raw string) bool {
	u, err := url.Parse(raw)
	return err == nil && (u.Scheme == "http" || u.Scheme == "https") && u.Host != ""
}

func newMux(s *Store) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/shorten", func(w http.ResponseWriter, r *http.Request) {
		target := r.URL.Query().Get("url")
		if !validTarget(target) {
			http.Error(w, "url must be an absolute http or https URL", http.StatusBadRequest)
			return
		}
		fmt.Fprintln(w, s.Put(target))
	})
	mux.HandleFunc("/r/", func(w http.ResponseWriter, r *http.Request) {
		t, ok := s.Get(r.URL.Path[len("/r/"):])
		if !ok {
			http.NotFound(w, r)
			return
		}
		http.Redirect(w, r, t, http.StatusFound)
	})
	return mux
}

func main() {
	log.Fatal(http.ListenAndServe(":8080", newMux(NewStore())))
}
'''}),
dict(id="hit-counter", text="Count redirects: Store records how many times each code has been followed, /r/<code> increments it, and a new GET /stats/<code> endpoint returns that count as plain text (404 for an unknown code).",
 partial={"store.go": '''package main

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
	if ok {
		s.hits[code]++
	}
	return t, ok
}

func (s *Store) Hits(code string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.hits[code]
}
'''},
 done={"store.go": '''package main

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
''', "main.go": '''package main

import (
	"fmt"
	"log"
	"net/http"
)

func newMux(s *Store) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/shorten", func(w http.ResponseWriter, r *http.Request) {
		target := r.URL.Query().Get("url")
		fmt.Fprintln(w, s.Put(target))
	})
	mux.HandleFunc("/r/", func(w http.ResponseWriter, r *http.Request) {
		t, ok := s.Follow(r.URL.Path[len("/r/"):])
		if !ok {
			http.NotFound(w, r)
			return
		}
		http.Redirect(w, r, t, http.StatusFound)
	})
	mux.HandleFunc("/stats/", func(w http.ResponseWriter, r *http.Request) {
		n, ok := s.Hits(r.URL.Path[len("/stats/"):])
		if !ok {
			http.NotFound(w, r)
			return
		}
		fmt.Fprintln(w, n)
	})
	return mux
}

func main() {
	log.Fatal(http.ListenAndServe(":8080", newMux(NewStore())))
}
'''}),
dict(id="http-tests", text="Add main_test.go with httptest-based tests that exercise the real mux: shortening a URL then following its /r/ redirect (302 and Location header), and an unknown code returning 404.",
 partial={"main_test.go": '''package main

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
'''},
 done={"main_test.go": '''package main

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
'''}),
])
