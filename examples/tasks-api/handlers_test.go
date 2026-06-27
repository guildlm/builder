package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// newTestServer returns an httptest.Server backed by a fresh store.
func newTestServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(NewRouter(NewAPI(NewStore())))
	t.Cleanup(srv.Close)
	return srv
}

// doJSON performs a request and decodes the JSON body (if out != nil).
func doJSON(t *testing.T, method, url, body string, out any) *http.Response {
	t.Helper()
	var rdr *bytes.Reader
	if body == "" {
		rdr = bytes.NewReader(nil)
	} else {
		rdr = bytes.NewReader([]byte(body))
	}
	req, err := http.NewRequest(method, url, rdr)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("do request: %v", err)
	}
	if out != nil {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
			t.Fatalf("decode body: %v", err)
		}
	}
	resp.Body.Close()
	return resp
}

func TestCreateAndGet(t *testing.T) {
	srv := newTestServer(t)

	var created Task
	resp := doJSON(t, http.MethodPost, srv.URL+"/tasks", `{"title":"write tests"}`, &created)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("POST status = %d, want 201", resp.StatusCode)
	}
	if created.ID == 0 || created.Title != "write tests" || created.CreatedAt.IsZero() {
		t.Fatalf("created task malformed: %+v", created)
	}

	var got Task
	resp = doJSON(t, http.MethodGet, srv.URL+"/tasks/1", "", &got)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("GET status = %d, want 200", resp.StatusCode)
	}
	if got.ID != created.ID || got.Title != created.Title {
		t.Fatalf("GET task = %+v, want %+v", got, created)
	}
}

func TestList(t *testing.T) {
	srv := newTestServer(t)
	doJSON(t, http.MethodPost, srv.URL+"/tasks", `{"title":"one"}`, nil)
	doJSON(t, http.MethodPost, srv.URL+"/tasks", `{"title":"two"}`, nil)

	var tasks []Task
	resp := doJSON(t, http.MethodGet, srv.URL+"/tasks", "", &tasks)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if len(tasks) != 2 {
		t.Fatalf("len(tasks) = %d, want 2", len(tasks))
	}
}

func TestUpdateToggle(t *testing.T) {
	srv := newTestServer(t)
	doJSON(t, http.MethodPost, srv.URL+"/tasks", `{"title":"toggle me"}`, nil)

	var updated Task
	resp := doJSON(t, http.MethodPut, srv.URL+"/tasks/1", `{"title":"toggle me","done":true}`, &updated)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}
	if !updated.Done {
		t.Fatalf("expected Done=true, got %+v", updated)
	}
}

func TestDelete(t *testing.T) {
	srv := newTestServer(t)
	doJSON(t, http.MethodPost, srv.URL+"/tasks", `{"title":"delete me"}`, nil)

	resp := doJSON(t, http.MethodDelete, srv.URL+"/tasks/1", "", nil)
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("DELETE status = %d, want 204", resp.StatusCode)
	}

	resp = doJSON(t, http.MethodGet, srv.URL+"/tasks/1", "", nil)
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("GET after delete status = %d, want 404", resp.StatusCode)
	}
}

func TestNotFound(t *testing.T) {
	srv := newTestServer(t)
	var er errorResponse
	resp := doJSON(t, http.MethodGet, srv.URL+"/tasks/4242", "", &er)
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", resp.StatusCode)
	}
	if er.Error == "" {
		t.Error("expected non-empty error message in body")
	}
}

func TestBadRequests(t *testing.T) {
	srv := newTestServer(t)

	// Invalid JSON.
	resp := doJSON(t, http.MethodPost, srv.URL+"/tasks", `{not json`, nil)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("invalid JSON status = %d, want 400", resp.StatusCode)
	}

	// Empty title fails validation.
	var er errorResponse
	resp = doJSON(t, http.MethodPost, srv.URL+"/tasks", `{"title":"   "}`, &er)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("empty title status = %d, want 400", resp.StatusCode)
	}
	if !strings.Contains(er.Error, "title") {
		t.Errorf("error body = %q, want it to mention title", er.Error)
	}

	// Non-numeric id.
	resp = doJSON(t, http.MethodGet, srv.URL+"/tasks/abc", "", nil)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("bad id status = %d, want 400", resp.StatusCode)
	}
}

func TestMethodNotAllowed(t *testing.T) {
	srv := newTestServer(t)
	// PATCH is not registered for /tasks, ServeMux returns 405.
	resp := doJSON(t, http.MethodPatch, srv.URL+"/tasks", "", nil)
	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("PATCH status = %d, want 405", resp.StatusCode)
	}
}
