package api

import (
	"errors"
	"net/http"
	"strconv"

	"guildlm.dev/taskapipro/internal/service"

	"guildlm.dev/taskapipro/internal/models"
	"guildlm.dev/taskapipro/internal/store"
)

// ProjectHandler handles HTTP requests for the /projects resource.
type ProjectHandler struct {
	svc service.ProjectService
}

// NewProjectHandler creates a new ProjectHandler with the given ProjectService.
func NewProjectHandler(svc service.ProjectService) *ProjectHandler {
	return &ProjectHandler{svc: svc}
}

// Create decodes a JSON Project from the request body and stores it.
func (h *ProjectHandler) Create(w http.ResponseWriter, r *http.Request) {
	var p models.Project
	if err := decodeJSON(r, &p); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON")
		return
	}
	ctx := r.Context()
	p, err := h.svc.Create(ctx, p)
	if err != nil {
		if errors.Is(err, models.ErrInvalid) {
			writeError(w, http.StatusBadRequest, "invalid project")
		} else if errors.Is(err, store.ErrExists) {
			writeError(w, http.StatusConflict, "project already exists")
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusCreated, p)
}

// List returns all projects as a JSON array.
func (h *ProjectHandler) List(w http.ResponseWriter, r *http.Request) {
	limitStr := r.URL.Query().Get("limit")
	offsetStr := r.URL.Query().Get("offset")

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
	projects, err := h.svc.List(ctx, limit, offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal server error")
		return
	}
	writeJSON(w, http.StatusOK, projects)
}

// Get reads the {id} path value and returns the project as JSON.
func (h *ProjectHandler) Get(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	ctx := r.Context()
	p, err := h.svc.Get(ctx, id)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeJSON(w, http.StatusNotFound, nil)
		} else {
			writeError(w, http.StatusInternalServerError, "internal server error")
		}
		return
	}
	writeJSON(w, http.StatusOK, p)
}

// Delete removes {id} returning 204, or 404 if absent.
func (h *ProjectHandler) Delete(w http.ResponseWriter, r *http.Request) {
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
