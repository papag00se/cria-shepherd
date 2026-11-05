package main

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
