package api

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"guildlm.dev/taskapipro/internal/models"

	"guildlm.dev/taskapipro/internal/store"

	"guildlm.dev/taskapipro/internal/service"
)

func TestCreateValidTask(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	if w.Code != http.StatusCreated {
		t.Fatalf("create valid task: want 201, got %d", w.Code)
	}
	var task models.Task
	if err := json.NewDecoder(w.Body).Decode(&task); err != nil {
		t.Fatalf("decode created task: %v", err)
	}
	if task.ID != "1" || task.Title != "task1" || task.Status != "todo" {
		t.Fatalf("echo wrong: %+v", task)
	}
}

func TestCreateInvalidTask(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"invalid"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("create invalid task: want 400, got %d", w.Code)
	}
}

func TestDuplicateTask(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	w = httptest.NewRecorder()
	req = httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	if w.Code != http.StatusConflict {
		t.Fatalf("duplicate task: want 409, got %d", w.Code)
	}
}

func TestGetMissingTask(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/tasks/1", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusNotFound {
		t.Fatalf("get missing task: want 404, got %d", w.Code)
	}
}

func TestGetTask(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	w = httptest.NewRecorder()
	req = httptest.NewRequest("GET", "/tasks/1", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("get task: want 200, got %d", w.Code)
	}
	var task models.Task
	if err := json.NewDecoder(w.Body).Decode(&task); err != nil {
		t.Fatalf("decode task: %v", err)
	}
	if task.ID != "1" || task.Title != "task1" || task.Status != "todo" {
		t.Fatalf("echo wrong: %+v", task)
	}
}

func TestListTasks(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	w = httptest.NewRecorder()
	req = httptest.NewRequest("GET", "/tasks", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("list tasks: want 200, got %d", w.Code)
	}
	var tasks []models.Task
	if err := json.NewDecoder(w.Body).Decode(&tasks); err != nil {
		t.Fatalf("decode tasks: %v", err)
	}
	if len(tasks) != 1 || tasks[0].ID != "1" || tasks[0].Title != "task1" || tasks[0].Status != "todo" {
		t.Fatalf("echo wrong: %+v", tasks)
	}
}

func TestListTasksLimit(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	w = httptest.NewRecorder()
	req = httptest.NewRequest("GET", "/tasks?limit=1", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("list tasks with limit: want 200, got %d", w.Code)
	}
	var tasks []models.Task
	if err := json.NewDecoder(w.Body).Decode(&tasks); err != nil {
		t.Fatalf("decode tasks: %v", err)
	}
	if len(tasks) != 1 || tasks[0].ID != "1" || tasks[0].Title != "task1" || tasks[0].Status != "todo" {
		t.Fatalf("echo wrong: %+v", tasks)
	}
}

func TestDeleteTask(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"id":"1","title":"task1","status":"todo"}`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	w = httptest.NewRecorder()
	req = httptest.NewRequest("DELETE", "/tasks/1", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusNoContent {
		t.Fatalf("delete task: want 204, got %d", w.Code)
	}
	w = httptest.NewRecorder()
	req = httptest.NewRequest("GET", "/tasks/1", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusNotFound {
		t.Fatalf("get task after delete: want 404, got %d", w.Code)
	}
}

func TestDeleteMissingTask(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("DELETE", "/tasks/1", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusNotFound {
		t.Fatalf("delete missing task: want 404, got %d", w.Code)
	}
}

func TestMalformedJSON(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(`{"x":`))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("malformed JSON: want 400, got %d", w.Code)
	}
}

func TestHealthz(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/healthz", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("healthz: want 200, got %d", w.Code)
	}
	var resp string
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode healthz response: %v", err)
	}
	if resp != "ok" {
		t.Fatalf("healthz response: want 'ok', got %s", resp)
	}
}

func TestReadyz(t *testing.T) {
	h := NewRouter(service.NewTaskService(store.NewMemStore()), service.NewProjectService(store.NewMemStore()), slog.New(slog.NewTextHandler(io.Discard, nil)))
	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/readyz", nil)
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("readyz: want 200, got %d", w.Code)
	}
	var resp string
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode readyz response: %v", err)
	}
	if resp != "ready" {
		t.Fatalf("readyz response: want 'ready', got %s", resp)
	}
}
