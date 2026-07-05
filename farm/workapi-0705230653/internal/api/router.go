package api

import (
	"log/slog"
	"net/http"

	"guildlm.dev/workapi/internal/auth"
	"guildlm.dev/workapi/internal/service"
)

// NewRouter registers method+pattern routes; only the mutating routes (POST, DELETE) are wrapped in auth (GET stays open).
func NewRouter(svc service.TaskService, authToken string, logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	taskHandler := NewTaskHandler(svc)

	mux.Handle("POST /tasks", auth.TokenAuth(authToken)(http.HandlerFunc(taskHandler.Create)))
	mux.HandleFunc("GET /tasks", taskHandler.List)
	mux.HandleFunc("GET /tasks/{id}", taskHandler.Get)
	mux.Handle("DELETE /tasks/{id}", auth.TokenAuth(authToken)(http.HandlerFunc(taskHandler.Delete)))

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, "ok")
	})

	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, "ready")
	})

	return Chain(mux, Logging(logger), Recover(logger))
}
