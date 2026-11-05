package main

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
