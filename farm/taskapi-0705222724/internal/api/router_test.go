package api

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"guildlm.dev/taskapi/internal/models"
	"guildlm.dev/taskapi/internal/store"
)

func TestRouter(t *testing.T) {
	t.Run("POST valid task returns 201 and echoes", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		if w.Code != http.StatusCreated {
			t.Fatalf("create: want 201, got %d", w.Code)
		}
		var task models.Task
		if err := json.NewDecoder(w.Body).Decode(&task); err != nil {
			t.Fatalf("decode created task: %v", err)
		}
		if task.ID != "1" || task.Title != "task1" || task.Status != "todo" {
			t.Fatalf("echo wrong: %+v", task)
		}
	})

	t.Run("POST invalid task returns 400", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"invalid"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		if w.Code != http.StatusBadRequest {
			t.Fatalf("create invalid: want 400, got %d", w.Code)
		}
	})

	t.Run("POST duplicate id returns 409", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		w = httptest.NewRecorder()
		req = httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		if w.Code != http.StatusConflict {
			t.Fatalf("duplicate create: want 409, got %d", w.Code)
		}
	})

	t.Run("GET missing task returns 404", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("GET", "/tasks/1", nil)
		h.ServeHTTP(w, req)
		if w.Code != http.StatusNotFound {
			t.Fatalf("get missing: want 404, got %d", w.Code)
		}
	})

	t.Run("GET existing task returns 200", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		w = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/tasks/1", nil)
		h.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("get existing: want 200, got %d", w.Code)
		}
		var task models.Task
		if err := json.NewDecoder(w.Body).Decode(&task); err != nil {
			t.Fatalf("decode existing task: %v", err)
		}
		if task.ID != "1" || task.Title != "task1" || task.Status != "todo" {
			t.Fatalf("echo wrong: %+v", task)
		}
	})

	t.Run("DELETE existing task returns 204", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		w = httptest.NewRecorder()
		req = httptest.NewRequest("DELETE", "/tasks/1", nil)
		h.ServeHTTP(w, req)
		if w.Code != http.StatusNoContent {
			t.Fatalf("delete existing: want 204, got %d", w.Code)
		}
		w = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/tasks/1", nil)
		h.ServeHTTP(w, req)
		if w.Code != http.StatusNotFound {
			t.Fatalf("get after delete: want 404, got %d", w.Code)
		}
	})

	t.Run("DELETE missing task returns 404", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("DELETE", "/tasks/1", nil)
		h.ServeHTTP(w, req)
		if w.Code != http.StatusNotFound {
			t.Fatalf("delete missing: want 404, got %d", w.Code)
		}
	})

	t.Run("List tasks returns 200 JSON array", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		w = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/tasks", nil)
		h.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("list: want 200, got %d", w.Code)
		}
		var tasks []models.Task
		if err := json.NewDecoder(w.Body).Decode(&tasks); err != nil {
			t.Fatalf("decode list: %v", err)
		}
		if len(tasks) != 1 || tasks[0].ID != "1" {
			t.Fatalf("list wrong: %+v", tasks)
		}
	})

	t.Run("Malformed JSON returns 400", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1",`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		if w.Code != http.StatusBadRequest {
			t.Fatalf("malformed JSON: want 400, got %d", w.Code)
		}
	})

	t.Run("Project create/get happy path", func(t *testing.T) {
		s := store.NewMemStore()
		h := NewRouter(s, slog.New(slog.NewTextHandler(io.Discard, nil)))
		w := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/projects", bytes.NewBufferString(`{"id":"1","name":"project1"}`))
		req.Header.Set("Content-Type", "application/json")
		h.ServeHTTP(w, req)
		if w.Code != http.StatusCreated {
			t.Fatalf("project create: want 201, got %d", w.Code)
		}
		w = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/projects/1", nil)
		h.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("project get: want 200, got %d", w.Code)
		}
		var project models.Project
		if err := json.NewDecoder(w.Body).Decode(&project); err != nil {
			t.Fatalf("decode project: %v", err)
		}
		if project.ID != "1" || project.Name != "project1" {
			t.Fatalf("project echo wrong: %+v", project)
		}
	})
}
