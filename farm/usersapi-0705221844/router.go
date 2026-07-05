package main

import (
	"net/http"
)

// NewRouter builds an http.ServeMux mapping method+pattern routes to a UserHandler.
func NewRouter(s Store) http.Handler {
	mux := http.NewServeMux()
	userHandler := NewUserHandler(s)

	mux.HandleFunc("POST /users", userHandler.Create)
	mux.HandleFunc("GET /users", userHandler.List)
	mux.HandleFunc("GET /users/{id}", userHandler.Get)
	mux.HandleFunc("DELETE /users/{id}", userHandler.Delete)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})

	return Chain(mux, Logging, Recover)
}
