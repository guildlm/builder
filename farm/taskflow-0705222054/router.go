package main

import (
	"net/http"
)

// NewRouter builds an http.ServeMux mapping method+pattern routes to handlers.
func NewRouter(s *Store) http.Handler {
	mux := http.NewServeMux()
	taskHandler := NewTaskHandler(s)
	projectHandler := NewProjectHandler(s)

	mux.HandleFunc("POST /tasks", taskHandler.Create)
	mux.HandleFunc("GET /tasks", taskHandler.List)
	mux.HandleFunc("GET /tasks/{id}", taskHandler.Get)
	mux.HandleFunc("DELETE /tasks/{id}", taskHandler.Delete)
	mux.HandleFunc("POST /projects", projectHandler.Create)
	mux.HandleFunc("GET /projects", projectHandler.List)
	mux.HandleFunc("GET /projects/{id}", projectHandler.Get)
	mux.HandleFunc("DELETE /projects/{id}", projectHandler.Delete)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})

	return Chain(mux, Logging, Recover)
}
