package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
)

// API wraps a Store and provides HTTP handlers for tasks.
type API struct {
	store Store
}

// NewAPI creates a new API with the given Store.
func NewAPI(store Store) *API {
	return &API{store: store}
}

// Create decodes a JSON Task from the request body and stores it.
func (a *API) Create(w http.ResponseWriter, r *http.Request) {
	var t Task
	if err := json.NewDecoder(r.Body).Decode(&t); err != nil {
		writeJSON(w, http.StatusBadRequest, nil)
		return
	}
	if err := a.store.Create(t); err != nil {
		if errors.Is(err, ErrInvalidTask) {
			writeJSON(w, http.StatusBadRequest, nil)
		} else if errors.Is(err, ErrExists) {
			writeJSON(w, http.StatusConflict, nil)
		} else {
			writeJSON(w, http.StatusInternalServerError, nil)
		}
		return
	}
	writeJSON(w, http.StatusCreated, t)
}

// List returns all tasks as a JSON array.
func (a *API) List(w http.ResponseWriter, r *http.Request) {
	tasks := a.store.List()
	writeJSON(w, http.StatusOK, tasks)
}

// Get reads the {id} path value and returns the task as JSON.
func (a *API) Get(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.Atoi(idStr)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, nil)
		return
	}
	t, err := a.store.Get(id)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			writeJSON(w, http.StatusNotFound, nil)
		} else {
			writeJSON(w, http.StatusInternalServerError, nil)
		}
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// Update decodes a JSON Task from the request body and updates the existing task.
func (a *API) Update(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.Atoi(idStr)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, nil)
		return
	}
	var t Task
	if err := json.NewDecoder(r.Body).Decode(&t); err != nil {
		writeJSON(w, http.StatusBadRequest, nil)
		return
	}
	t.ID = id
	if err := a.store.Update(t); err != nil {
		if errors.Is(err, ErrNotFound) {
			writeJSON(w, http.StatusNotFound, nil)
		} else if errors.Is(err, ErrInvalidTask) {
			writeJSON(w, http.StatusBadRequest, nil)
		} else {
			writeJSON(w, http.StatusInternalServerError, nil)
		}
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// Delete removes the task with the given ID.
func (a *API) Delete(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.Atoi(idStr)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, nil)
		return
	}
	if err := a.store.Delete(id); err != nil {
		if errors.Is(err, ErrNotFound) {
			writeJSON(w, http.StatusNotFound, nil)
		} else {
			writeJSON(w, http.StatusInternalServerError, nil)
		}
		return
	}
	writeJSON(w, http.StatusNoContent, nil)
}

// writeJSON writes the given value as JSON to the response writer with the given status code.
func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if v != nil {
		json.NewEncoder(w).Encode(v)
	}
}
