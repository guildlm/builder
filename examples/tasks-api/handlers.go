package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
)

// API wraps a Store and exposes HTTP handlers for the tasks resource.
type API struct {
	store *Store
}

// NewAPI returns an API backed by the given store.
func NewAPI(store *Store) *API {
	return &API{store: store}
}

// errorResponse is the JSON shape returned for all error responses.
type errorResponse struct {
	Error string `json:"error"`
}

// writeJSON encodes v as JSON with the given status code. Encoding errors are
// logged implicitly via the http package; the header is already committed.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if v != nil {
		_ = json.NewEncoder(w).Encode(v)
	}
}

// writeError sends a JSON error body with the given status code.
func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, errorResponse{Error: msg})
}

// parseID extracts and validates the {id} path value.
func parseID(r *http.Request) (int, error) {
	return strconv.Atoi(r.PathValue("id"))
}

// Create handles POST /tasks.
func (a *API) Create(w http.ResponseWriter, r *http.Request) {
	var t Task
	if err := json.NewDecoder(r.Body).Decode(&t); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	created, err := a.store.Create(t)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

// List handles GET /tasks.
func (a *API) List(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, a.store.List())
}

// Get handles GET /tasks/{id}.
func (a *API) Get(w http.ResponseWriter, r *http.Request) {
	id, err := parseID(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid id")
		return
	}
	t, err := a.store.Get(id)
	if err != nil {
		a.writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, t)
}

// Update handles PUT /tasks/{id}. It replaces the mutable fields (title, done),
// which is also how a client toggles completion.
func (a *API) Update(w http.ResponseWriter, r *http.Request) {
	id, err := parseID(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid id")
		return
	}
	var in Task
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	updated, err := a.store.Update(id, in)
	if err != nil {
		a.writeStoreError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, updated)
}

// Delete handles DELETE /tasks/{id}.
func (a *API) Delete(w http.ResponseWriter, r *http.Request) {
	id, err := parseID(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid id")
		return
	}
	if err := a.store.Delete(id); err != nil {
		a.writeStoreError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// writeStoreError maps a store error to the appropriate HTTP status. ErrNotFound
// becomes 404, validation errors become 400, anything else 500.
func (a *API) writeStoreError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		writeError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, ErrInvalidTask):
		writeError(w, http.StatusBadRequest, err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "internal error")
	}
}
