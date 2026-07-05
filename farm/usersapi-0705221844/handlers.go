package main

import (
	"encoding/json"
	"errors"
	"net/http"
)

// UserHandler handles HTTP requests for the /users resource.
type UserHandler struct {
	store Store
}

// NewUserHandler creates a new UserHandler with the given Store.
func NewUserHandler(store Store) *UserHandler {
	return &UserHandler{store: store}
}

// Create decodes a JSON User from the request body and stores it.
func (h *UserHandler) Create(w http.ResponseWriter, r *http.Request) {
	var u User
	if err := json.NewDecoder(r.Body).Decode(&u); err != nil {
		writeJSON(w, http.StatusBadRequest, nil)
		return
	}
	if err := h.store.Create(u); err != nil {
		if errors.Is(err, ErrExists) {
			writeJSON(w, http.StatusConflict, nil)
		} else {
			writeJSON(w, http.StatusInternalServerError, nil)
		}
		return
	}
	writeJSON(w, http.StatusCreated, u)
}

// Get reads the {id} path value and returns the user as JSON.
func (h *UserHandler) Get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	u, err := h.store.Get(id)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			writeJSON(w, http.StatusNotFound, nil)
		} else {
			writeJSON(w, http.StatusInternalServerError, nil)
		}
		return
	}
	writeJSON(w, http.StatusOK, u)
}

// List returns all users as a JSON array.
func (h *UserHandler) List(w http.ResponseWriter, r *http.Request) {
	users := h.store.List()
	writeJSON(w, http.StatusOK, users)
}

// Delete removes {id} returning 204, or 404 if absent.
func (h *UserHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.store.Delete(id); err != nil {
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
