package api

import (
	"errors"
	"net/http"

	"guildlm.dev/taskapi/internal/models"
	"guildlm.dev/taskapi/internal/store"
)

// TaskHandler handles HTTP requests for the /tasks resource.
type TaskHandler struct {
	store store.Store
}

// NewTaskHandler creates a new TaskHandler with the given Store.
func NewTaskHandler(store store.Store) *TaskHandler {
	return &TaskHandler{store: store}
}

// Create decodes a JSON Task from the request body and stores it.
func (h *TaskHandler) Create(w http.ResponseWriter, r *http.Request) {
	var t models.Task
	if err := decodeJSON(r, &t); err != nil {
		writeError(w, http.StatusBadRequest, "malformed request body")
		return
	}
	if err := t.Validate(); err != nil {
		writeError(w, http.StatusBadRequest, "invalid task")
		return
	}
	if err := h.store.CreateTask(t); err != nil {
		if errors.Is(err, store.ErrExists) {
			writeError(w, http.StatusConflict, "task already exists")
		} else {
			writeError(w, http.StatusInternalServerError, "failed to create task")
		}
		return
	}
	writeJSON(w, http.StatusCreated, t)
}

// Get reads the {id} path value and returns the task as JSON.
func (h *TaskHandler) Get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	t, err := h.store.GetTask(id)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "task not found")
		} else {
			writeError(w, http.StatusInternalServerError, "failed to get task")
		}
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// List returns all tasks as a JSON array.
func (h *TaskHandler) List(w http.ResponseWriter, r *http.Request) {
	tasks := h.store.ListTasks()
	writeJSON(w, http.StatusOK, tasks)
}

// Delete removes {id} returning 204, or 404 if absent.
func (h *TaskHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.store.DeleteTask(id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "task not found")
		} else {
			writeError(w, http.StatusInternalServerError, "failed to delete task")
		}
		return
	}
	writeJSON(w, http.StatusNoContent, nil)
}
