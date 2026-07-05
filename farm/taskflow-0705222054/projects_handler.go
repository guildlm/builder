package main

import (
	"errors"
	"net/http"
)

// ProjectHandler handles HTTP requests for the /projects resource.
type ProjectHandler struct {
	store *Store
}

// NewProjectHandler creates a new ProjectHandler with the given Store.
func NewProjectHandler(store *Store) *ProjectHandler {
	return &ProjectHandler{store: store}
}

// Create decodes a JSON Project from the request body, validates it, and stores it.
func (h *ProjectHandler) Create(w http.ResponseWriter, r *http.Request) {
	var p Project
	if err := decodeJSON(r, &p); err != nil {
		writeError(w, http.StatusBadRequest, "malformed request body")
		return
	}
	if err := p.Validate(); err != nil {
		if errors.Is(err, ErrValidation) {
			writeError(w, http.StatusBadRequest, err.Error())
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	if err := h.store.CreateProject(p); err != nil {
		if errors.Is(err, ErrExists) {
			writeError(w, http.StatusConflict, "project already exists")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusCreated, p)
}

// List parses pagination parameters, retrieves projects, and returns them as JSON.
func (h *ProjectHandler) List(w http.ResponseWriter, r *http.Request) {
	limit, offset := parsePage(r)
	projects := h.store.ListProjects()
	paginatedProjects := paginate(projects, limit, offset)
	writeJSON(w, http.StatusOK, paginatedProjects)
}

// Get retrieves a project by ID and returns it as JSON.
func (h *ProjectHandler) Get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	p, err := h.store.GetProject(id)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			writeError(w, http.StatusNotFound, "project not found")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusOK, p)
}

// Delete removes a project by ID and returns a 204 status.
func (h *ProjectHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.store.DeleteProject(id); err != nil {
		if errors.Is(err, ErrNotFound) {
			writeError(w, http.StatusNotFound, "project not found")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
