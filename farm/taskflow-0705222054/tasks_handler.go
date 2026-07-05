package main

import (
	"errors"
	"net/http"
)

// TaskHandler handles HTTP requests for the /tasks resource.
type TaskHandler struct {
	store *Store
}

// NewTaskHandler creates a new TaskHandler with the given Store.
func NewTaskHandler(store *Store) *TaskHandler {
	return &TaskHandler{store: store}
}

// Create decodes a JSON Task from the request body, validates it, and stores it.
func (h *TaskHandler) Create(w http.ResponseWriter, r *http.Request) {
	var t Task
	if err := decodeJSON(r, &t); err != nil {
		writeError(w, http.StatusBadRequest, "malformed request body")
		return
	}
	if err := t.Validate(); err != nil {
		if errors.Is(err, ErrValidation) {
			writeError(w, http.StatusBadRequest, err.Error())
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	if err := h.store.CreateTask(t); err != nil {
		if errors.Is(err, ErrExists) {
			writeError(w, http.StatusConflict, "task already exists")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusCreated, t)
}

// List parses pagination parameters, retrieves tasks, and returns them as JSON.
func (h *TaskHandler) List(w http.ResponseWriter, r *http.Request) {
	limit, offset := parsePage(r)
	tasks := h.store.ListTasks()
	paginatedTasks := paginate(tasks, limit, offset)
	writeJSON(w, http.StatusOK, paginatedTasks)
}

// Get retrieves a task by ID and returns it as JSON.
func (h *TaskHandler) Get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	t, err := h.store.GetTask(id)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			writeError(w, http.StatusNotFound, "task not found")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// Delete removes a task by ID and returns a 204 status.
func (h *TaskHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.store.DeleteTask(id); err != nil {
		if errors.Is(err, ErrNotFound) {
			writeError(w, http.StatusNotFound, "task not found")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
