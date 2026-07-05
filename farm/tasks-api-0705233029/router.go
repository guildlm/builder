package main

import (
	"net/http"
)

// NewRouter registers method+pattern routes for the tasks API.
func NewRouter(api *API) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /tasks", api.Create)
	mux.HandleFunc("GET /tasks", api.List)
	mux.HandleFunc("GET /tasks/{id}", api.Get)
	mux.HandleFunc("PUT /tasks/{id}", api.Update)
	mux.HandleFunc("DELETE /tasks/{id}", api.Delete)
	return mux
}
