package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCreateTask(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	body, _ := json.Marshal(Task{Title: "test task"})
	req := httptest.NewRequest("POST", "/tasks", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Errorf("CreateTask: want 201, got %d", rec.Code)
	}

	var createdTask Task
	if err := json.NewDecoder(rec.Body).Decode(&createdTask); err != nil {
		t.Fatalf("CreateTask: decode response body: %v", err)
	}
	if createdTask.Title != "test task" {
		t.Errorf("CreateTask: title = %q, want test task", createdTask.Title)
	}
}

func TestGetTask(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	task := Task{Title: "test task"}
	if err := s.Create(task); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}

	req := httptest.NewRequest("GET", "/tasks/1", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("GetTask: want 200, got %d", rec.Code)
	}

	var gotTask Task
	if err := json.NewDecoder(rec.Body).Decode(&gotTask); err != nil {
		t.Fatalf("GetTask: decode response body: %v", err)
	}
	if gotTask.Title != "test task" {
		t.Errorf("GetTask: title = %q, want test task", gotTask.Title)
	}
}

func TestUpdateTask(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	task := Task{Title: "test task"}
	if err := s.Create(task); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}

	body, _ := json.Marshal(Task{Title: "updated task"})
	req := httptest.NewRequest("PUT", "/tasks/1", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("UpdateTask: want 200, got %d", rec.Code)
	}

	var updatedTask Task
	if err := json.NewDecoder(rec.Body).Decode(&updatedTask); err != nil {
		t.Fatalf("UpdateTask: decode response body: %v", err)
	}
	if updatedTask.Title != "updated task" {
		t.Errorf("UpdateTask: title = %q, want updated task", updatedTask.Title)
	}
}

func TestDeleteTask(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	task := Task{Title: "test task"}
	if err := s.Create(task); err != nil {
		t.Fatalf("CreateTask: %v", err)
	}

	req := httptest.NewRequest("DELETE", "/tasks/1", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Errorf("DeleteTask: want 204, got %d", rec.Code)
	}

	_, err := s.Get(1)
	if err != ErrNotFound {
		t.Errorf("DeleteTask: want ErrNotFound, got %v", err)
	}
}

func TestCreateTaskWithEmptyTitle(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	body, _ := json.Marshal(Task{Title: ""})
	req := httptest.NewRequest("POST", "/tasks", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Errorf("CreateTaskWithEmptyTitle: want 400, got %d", rec.Code)
	}

	var errResponse struct {
		Error string `json:"error"`
	}
	if err := json.NewDecoder(rec.Body).Decode(&errResponse); err != nil {
		t.Fatalf("CreateTaskWithEmptyTitle: decode response body: %v", err)
	}
	if errResponse.Error != "invalid task: title is required" {
		t.Errorf("CreateTaskWithEmptyTitle: error = %q, want invalid task: title is required", errResponse.Error)
	}
}

func TestGetNonExistentTask(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	req := httptest.NewRequest("GET", "/tasks/1", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Errorf("GetNonExistentTask: want 404, got %d", rec.Code)
	}

	var errResponse struct {
		Error string `json:"error"`
	}
	if err := json.NewDecoder(rec.Body).Decode(&errResponse); err != nil {
		t.Fatalf("GetNonExistentTask: decode response body: %v", err)
	}
	if errResponse.Error != "not found" {
		t.Errorf("GetNonExistentTask: error = %q, want not found", errResponse.Error)
	}
}

func TestUpdateNonExistentTask(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	body, _ := json.Marshal(Task{Title: "updated task"})
	req := httptest.NewRequest("PUT", "/tasks/1", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Errorf("UpdateNonExistentTask: want 404, got %d", rec.Code)
	}

	var errResponse struct {
		Error string `json:"error"`
	}
	if err := json.NewDecoder(rec.Body).Decode(&errResponse); err != nil {
		t.Fatalf("UpdateNonExistentTask: decode response body: %v", err)
	}
	if errResponse.Error != "not found" {
		t.Errorf("UpdateNonExistentTask: error = %q, want not found", errResponse.Error)
	}
}

func TestDeleteNonExistentTask(t *testing.T) {
	s := NewStore()
	api := NewAPI(s)
	router := NewRouter(api)

	req := httptest.NewRequest("DELETE", "/tasks/1", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Errorf("DeleteNonExistentTask: want 404, got %d", rec.Code)
	}

	var errResponse struct {
		Error string `json:"error"`
	}
	if err := json.NewDecoder(rec.Body).Decode(&errResponse); err != nil {
		t.Fatalf("DeleteNonExistentTask: decode response body: %v", err)
	}
	if errResponse.Error != "not found" {
		t.Errorf("DeleteNonExistentTask: error = %q, want not found", errResponse.Error)
	}
}
