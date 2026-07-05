package api

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"guildlm.dev/workapi/internal/store"

	"guildlm.dev/workapi/internal/service"

	"guildlm.dev/workapi/internal/models"
)

func TestRouterCRUD(t *testing.T) {
	t.Run("POST valid task with token -> 201+echo", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("create: want 201, got %d (%s)", rec.Code, rec.Body.String())
		}
		var createdTask models.Task
		if err := json.NewDecoder(rec.Body).Decode(&createdTask); err != nil {
			t.Fatalf("decode created task: %v", err)
		}
		if createdTask.ID != "1" || createdTask.Title != "task1" || createdTask.Status != "todo" {
			t.Fatalf("echo wrong: %+v", createdTask)
		}
	})

	t.Run("POST with wrong token -> 401", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer wrong")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("wrong token: want 401, got %d", rec.Code)
		}
	})

	t.Run("POST with no token -> 401", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("no token: want 401, got %d", rec.Code)
		}
	})

	t.Run("invalid status (with token) -> 400", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"invalid"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("invalid status: want 400, got %d", rec.Code)
		}
	})

	t.Run("duplicate (same id, with token) -> 409", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("first create: want 201, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusConflict {
			t.Fatalf("duplicate create: want 409, got %d", rec.Code)
		}
	})

	t.Run("GET missing -> 404 (no token needed)", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("GET", "/tasks/999", nil)
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("get missing: want 404, got %d", rec.Code)
		}
	})

	t.Run("GET -> 200", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("create: want 201, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/tasks/1", nil)
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("get: want 200, got %d", rec.Code)
		}
		var got models.Task
		if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
			t.Fatalf("decode get response: %v", err)
		}
		if got.ID != "1" || got.Title != "task1" || got.Status != "todo" {
			t.Fatalf("get response wrong: %+v", got)
		}
	})

	t.Run("list -> 200 JSON array", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("create: want 201, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"2","title":"task2","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("second create: want 201, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/tasks", nil)
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("list: want 200, got %d", rec.Code)
		}
		var got []models.Task
		if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
			t.Fatalf("decode list response: %v", err)
		}
		if len(got) != 2 || got[0].ID != "1" || got[1].ID != "2" {
			t.Fatalf("list response wrong: %+v", got)
		}
	})

	t.Run("?limit=1 returns at most 1", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("create: want 201, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"2","title":"task2","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("second create: want 201, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/tasks?limit=1", nil)
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("list with limit: want 200, got %d", rec.Code)
		}
		var got []models.Task
		if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
			t.Fatalf("decode list response: %v", err)
		}
		if len(got) != 1 || got[0].ID != "1" {
			t.Fatalf("list response wrong: %+v", got)
		}
	})

	t.Run("DELETE (with token) -> 204 then GET -> 404", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("create: want 201, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("DELETE", "/tasks/1", nil)
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusNoContent {
			t.Fatalf("delete: want 204, got %d", rec.Code)
		}
		rec = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/tasks/1", nil)
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("get after delete: want 404, got %d", rec.Code)
		}
	})

	t.Run("malformed JSON (truncated, with token) -> 400", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1",`))
		req.Header.Set("Authorization", "Bearer secret")
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("malformed JSON: want 400, got %d", rec.Code)
		}
	})

	t.Run("GET /healthz -> 200", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("GET", "/healthz", nil)
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("GET /healthz: want 200, got %d", rec.Code)
		}
	})

	t.Run("GET /readyz -> 200", func(t *testing.T) {
		svc := service.NewTaskService(store.NewMemStore(), &fakeEnqueuer{})
		h := NewRouter(svc, "secret", slog.New(slog.NewTextHandler(io.Discard, nil)))
		rec := httptest.NewRecorder()
		req := httptest.NewRequest("GET", "/readyz", nil)
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("GET /readyz: want 200, got %d", rec.Code)
		}
	})
}

type fakeEnqueuer struct{}

func (f *fakeEnqueuer) Enqueue(e models.Event) {}
