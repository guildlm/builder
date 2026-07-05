package api

import (
	"log/slog"
	"net/http"

	"guildlm.dev/taskapi/internal/store"
)

// NewRouter builds an http.ServeMux and registers the task and project handlers.
func NewRouter(s store.Store, logger *slog.Logger) http.Handler {
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

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, "ok")
	})

	return Chain(mux, Logging(logger), Recover(logger))
}
