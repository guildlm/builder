package api

import (
	"log/slog"
	"net/http"

	"guildlm.dev/taskapipro/internal/service"
)

// NewRouter builds an http.ServeMux with routes for tasks and projects.
func NewRouter(ts service.TaskService, ps service.ProjectService, logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /tasks", NewTaskHandler(ts).Create)
	mux.HandleFunc("GET /tasks", NewTaskHandler(ts).List)
	mux.HandleFunc("GET /tasks/{id}", NewTaskHandler(ts).Get)
	mux.HandleFunc("DELETE /tasks/{id}", NewTaskHandler(ts).Delete)
	mux.HandleFunc("POST /projects", NewProjectHandler(ps).Create)
	mux.HandleFunc("GET /projects", NewProjectHandler(ps).List)
	mux.HandleFunc("GET /projects/{id}", NewProjectHandler(ps).Get)
	mux.HandleFunc("DELETE /projects/{id}", NewProjectHandler(ps).Delete)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, "ok")
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, "ready")
	})
	return Chain(mux, Logging(logger), Recover(logger))
}
