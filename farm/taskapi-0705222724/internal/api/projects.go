package api

import (
	"errors"
	"net/http"

	"guildlm.dev/taskapi/internal/models"
	"guildlm.dev/taskapi/internal/store"
)

// ProjectHandler handles HTTP requests for the /projects resource.
type ProjectHandler struct {
	store store.Store
}

// NewProjectHandler creates a new ProjectHandler with the given Store.
func NewProjectHandler(store store.Store) *ProjectHandler {
	return &ProjectHandler{store: store}
}

// Create decodes a JSON Project from the request body and stores it.
func (h *ProjectHandler) Create(w http.ResponseWriter, r *http.Request) {
	var p models.Project
	if err := decodeJSON(r, &p); err != nil {
		writeError(w, http.StatusBadRequest, "malformed request body")
		return
	}
	if err := p.Validate(); err != nil {
		writeError(w, http.StatusBadRequest, "invalid project")
		return
	}
	if err := h.store.CreateProject(p); err != nil {
		if errors.Is(err, store.ErrExists) {
			writeError(w, http.StatusConflict, "project already exists")
		} else {
			writeError(w, http.StatusInternalServerError, "failed to create project")
		}
		return
	}
	writeJSON(w, http.StatusCreated, p)
}

// Get reads the {id} path value and returns the project as JSON.
func (h *ProjectHandler) Get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	p, err := h.store.GetProject(id)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "project not found")
		} else {
			writeError(w, http.StatusInternalServerError, "failed to get project")
		}
		return
	}
	writeJSON(w, http.StatusOK, p)
}

// List returns all projects as a JSON array.
func (h *ProjectHandler) List(w http.ResponseWriter, r *http.Request) {
	projects := h.store.ListProjects()
	writeJSON(w, http.StatusOK, projects)
}

// Delete removes {id} returning 204, or 404 if absent.
func (h *ProjectHandler) Delete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.store.DeleteProject(id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "project not found")
		} else {
			writeError(w, http.StatusInternalServerError, "failed to delete project")
		}
		return
	}
	writeJSON(w, http.StatusNoContent, nil)
}
