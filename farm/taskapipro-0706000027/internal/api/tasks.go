package api

import (
	"errors"
	"net/http"
	"strconv"

	"guildlm.dev/taskapipro/internal/models"
	"guildlm.dev/taskapipro/internal/store"
)

// TaskHandler handles HTTP requests for the /tasks resource.
type TaskHandler struct {
	svc service.TaskService
}

// NewTaskHandler creates a new TaskHandler with the given TaskService.
func NewTaskHandler(svc service.TaskService) *TaskHandler {
	return &TaskHandler{svc: svc}
}

// Create decodes a JSON Task from the request body and stores it.
func (h *TaskHandler) Create(w http.ResponseWriter, r *http.Request) {
	var t models.Task
	if err := decodeJSON(r, &t); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	ctx := r.Context()
	t, err := h.svc.Create(ctx, t)
	if err != nil {
		if errors.Is(err, models.ErrInvalid) {
			writeError(w, http.StatusBadRequest, "invalid task")
		} else if errors.Is(err, store.ErrExists) {
			writeError(w, http.StatusConflict, "task already exists")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusCreated, t)
}

// List returns all tasks as a JSON array.
func (h *TaskHandler) List(w http.ResponseWriter, r *http.Request) {
	limitStr := r.URL.Query().Get("limit")
	offsetStr := r.URL.Query().Get("offset")
	status := r.URL.Query().Get("status")

	limit, err := strconv.Atoi(limitStr)
	if err != nil {
		limit = 0
	}
	if limit < 0 {
		limit = 0
	}

	offset, err := strconv.Atoi(offsetStr)
	if err != nil {
		offset = 0
	}
	if offset < 0 {
		offset = 0
	}

	ctx := r.Context()
	tasks, err := h.svc.List(ctx, limit, offset, status)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal server error")
		return
	}
	writeJSON(w, http.StatusOK, tasks)
}

// Get reads the {id} path value and returns the task as JSON.
func (h *TaskHandler) Get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	ctx := r.Context()
	t, err := h.svc.Get(ctx, id)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeJSON(w, http.StatusNotFound, nil)
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// Delete removes {id} returning 204, or 404 if absent.
func (h *TaskHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	ctx := r.Context()
	if err := h.svc.Delete(ctx, id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeJSON(w, http.StatusNotFound, nil)
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusNoContent, nil)
}
