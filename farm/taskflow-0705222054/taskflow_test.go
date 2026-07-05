package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func newAPI() http.Handler { return NewRouter(NewStore()) }

func do(t *testing.T, h http.Handler, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	var r *http.Request
	if body != "" {
		r = httptest.NewRequest(method, path, bytes.NewBufferString(body))
		r.Header.Set("Content-Type", "application/json")
	} else {
		r = httptest.NewRequest(method, path, nil)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

func TestCreateTaskReturns201AndEcho(t *testing.T) {
	h := newAPI()
	w := do(t, h, "POST", "/tasks", `{"id":"1","title":"Task 1","status":"todo","project_id":"1"}`)
	if w.Code != http.StatusCreated {
		t.Fatalf("create task: want 201, got %d (%s)", w.Code, w.Body)
	}
	var task Task
	json.Unmarshal(w.Body.Bytes(), &task)
	if task.ID != "1" || task.Title != "Task 1" || task.Status != "todo" {
		t.Fatalf("echo wrong: %+v", task)
	}
}

func TestInvalidTaskReturns400(t *testing.T) {
	h := newAPI()
	w := do(t, h, "POST", "/tasks", `{"id":"1","title":"Task 1","status":"invalid"}`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("invalid task: want 400, got %d", w.Code)
	}
}

func TestDuplicateTaskIDReturns409(t *testing.T) {
	h := newAPI()
	do(t, h, "POST", "/tasks", `{"id":"1","title":"Task 1","status":"todo","project_id":"1"}`)
	w := do(t, h, "POST", "/tasks", `{"id":"1","title":"Task 1","status":"todo","project_id":"1"}`)
	if w.Code != http.StatusConflict {
		t.Fatalf("duplicate task ID: want 409, got %d", w.Code)
	}
}

func TestGetMissingTaskReturns404(t *testing.T) {
	h := newAPI()
	w := do(t, h, "GET", "/tasks/1", "")
	if w.Code != http.StatusNotFound {
		t.Fatalf("get missing task: want 404, got %d", w.Code)
	}
}

func TestListTasksReturnsAll(t *testing.T) {
	h := newAPI()
	do(t, h, "POST", "/tasks", `{"id":"1","title":"Task 1","status":"todo","project_id":"1"}`)
	do(t, h, "POST", "/tasks", `{"id":"2","title":"Task 2","status":"doing","project_id":"2"}`)
	w := do(t, h, "GET", "/tasks", "")
	if w.Code != http.StatusOK {
		t.Fatalf("list tasks: want 200, got %d", w.Code)
	}
	var tasks []Task
	json.Unmarshal(w.Body.Bytes(), &tasks)
	if len(tasks) != 2 {
		t.Fatalf("list tasks len: want 2, got %d", len(tasks))
	}
}

func TestPaginationReturnsLimitedResults(t *testing.T) {
	h := newAPI()
	do(t, h, "POST", "/tasks", `{"id":"1","title":"Task 1","status":"todo","project_id":"1"}`)
	do(t, h, "POST", "/tasks", `{"id":"2","title":"Task 2","status":"doing","project_id":"2"}`)
	do(t, h, "POST", "/tasks", `{"id":"3","title":"Task 3","status":"done","project_id":"3"}`)
	w := do(t, h, "GET", "/tasks?limit=1", "")
	if w.Code != http.StatusOK {
		t.Fatalf("pagination: want 200, got %d", w.Code)
	}
	var tasks []Task
	json.Unmarshal(w.Body.Bytes(), &tasks)
	if len(tasks) != 1 {
		t.Fatalf("pagination len: want 1, got %d", len(tasks))
	}
}

func TestDeleteTaskThen404(t *testing.T) {
	h := newAPI()
	do(t, h, "POST", "/tasks", `{"id":"1","title":"Task 1","status":"todo","project_id":"1"}`)
	if w := do(t, h, "DELETE", "/tasks/1", ""); w.Code != http.StatusNoContent {
		t.Fatalf("delete task: want 204, got %d", w.Code)
	}
	if w := do(t, h, "GET", "/tasks/1", ""); w.Code != http.StatusNotFound {
		t.Fatalf("get task after delete: want 404, got %d", w.Code)
	}
}

func TestDeleteMissingTaskReturns404(t *testing.T) {
	h := newAPI()
	if w := do(t, h, "DELETE", "/tasks/absent", ""); w.Code != http.StatusNotFound {
		t.Fatalf("delete missing task: want 404, got %d", w.Code)
	}
}

func TestMalformedJSONReturns400(t *testing.T) {
	h := newAPI()
	w := do(t, h, "POST", "/tasks", `{"id":"1",`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("malformed JSON: want 400, got %d", w.Code)
	}
}

func TestCreateProjectReturns201AndEcho(t *testing.T) {
	h := newAPI()
	w := do(t, h, "POST", "/projects", `{"id":"1","name":"Project 1"}`)
	if w.Code != http.StatusCreated {
		t.Fatalf("create project: want 201, got %d (%s)", w.Code, w.Body)
	}
	var project Project
	json.Unmarshal(w.Body.Bytes(), &project)
	if project.ID != "1" || project.Name != "Project 1" {
		t.Fatalf("echo wrong: %+v", project)
	}
}

func TestInvalidProjectReturns400(t *testing.T) {
	h := newAPI()
	w := do(t, h, "POST", "/projects", `{"id":"1","name":""}`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("invalid project: want 400, got %d", w.Code)
	}
}

func TestDuplicateProjectIDReturns409(t *testing.T) {
	h := newAPI()
	do(t, h, "POST", "/projects", `{"id":"1","name":"Project 1"}`)
	w := do(t, h, "POST", "/projects", `{"id":"1","name":"Project 1"}`)
	if w.Code != http.StatusConflict {
		t.Fatalf("duplicate project ID: want 409, got %d", w.Code)
	}
}

func TestGetMissingProjectReturns404(t *testing.T) {
	h := newAPI()
	w := do(t, h, "GET", "/projects/1", "")
	if w.Code != http.StatusNotFound {
		t.Fatalf("get missing project: want 404, got %d", w.Code)
	}
}

func TestListProjectsReturnsAll(t *testing.T) {
	h := newAPI()
	do(t, h, "POST", "/projects", `{"id":"1","name":"Project 1"}`)
	do(t, h, "POST", "/projects", `{"id":"2","name":"Project 2"}`)
	w := do(t, h, "GET", "/projects", "")
	if w.Code != http.StatusOK {
		t.Fatalf("list projects: want 200, got %d", w.Code)
	}
	var projects []Project
	json.Unmarshal(w.Body.Bytes(), &projects)
	if len(projects) != 2 {
		t.Fatalf("list projects len: want 2, got %d", len(projects))
	}
}

func TestDeleteProjectThen404(t *testing.T) {
	h := newAPI()
	do(t, h, "POST", "/projects", `{"id":"1","name":"Project 1"}`)
	if w := do(t, h, "DELETE", "/projects/1", ""); w.Code != http.StatusNoContent {
		t.Fatalf("delete project: want 204, got %d", w.Code)
	}
	if w := do(t, h, "GET", "/projects/1", ""); w.Code != http.StatusNotFound {
		t.Fatalf("get project after delete: want 404, got %d", w.Code)
	}
}

func TestDeleteMissingProjectReturns404(t *testing.T) {
	h := newAPI()
	if w := do(t, h, "DELETE", "/projects/absent", ""); w.Code != http.StatusNotFound {
		t.Fatalf("delete missing project: want 404, got %d", w.Code)
	}
}

func TestMalformedJSONProjectReturns400(t *testing.T) {
	h := newAPI()
	w := do(t, h, "POST", "/projects", `{"id":"1",`)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("malformed JSON project: want 400, got %d", w.Code)
	}
}
