package main

import "net/http"

// NewRouter builds an *http.ServeMux wired to the API's handlers using Go 1.22+
// method+pattern routing. Unmatched methods on a known path automatically yield
// 405 Method Not Allowed from the ServeMux.
func NewRouter(api *API) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /tasks", api.Create)
	mux.HandleFunc("GET /tasks", api.List)
	mux.HandleFunc("GET /tasks/{id}", api.Get)
	mux.HandleFunc("PUT /tasks/{id}", api.Update)
	mux.HandleFunc("DELETE /tasks/{id}", api.Delete)
	return mux
}
