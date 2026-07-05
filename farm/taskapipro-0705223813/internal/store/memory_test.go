package store

import (
	"context"
	"testing"

	"guildlm.dev/taskapipro/internal/models"
)

func TestMemStore(t *testing.T) {
	tests := []struct {
		name       string
		create     models.Task
		getID      string
		getWant    error
		listWant   []models.Task
		deleteID   string
		deleteWant error
	}{
		{
			name:    "create->nil / dup->ErrExists",
			create:  models.Task{ID: "1", Title: "Task 1", Status: "todo"},
			getID:   "1",
			getWant: nil,
			listWant: []models.Task{
				{ID: "1", Title: "Task 1", Status: "todo"},
			},
			deleteID:   "1",
			deleteWant: nil,
		},
		{
			name:       "Get present/missing ->ErrNotFound",
			create:     models.Task{ID: "2", Title: "Task 2", Status: "todo"},
			getID:      "2",
			getWant:    nil,
			deleteID:   "2",
			deleteWant: nil,
		},
		{
			name:   "List id-sorted",
			create: models.Task{ID: "3", Title: "Task 3", Status: "todo"},
			listWant: []models.Task{
				{ID: "1", Title: "Task 1", Status: "todo"},
				{ID: "2", Title: "Task 2", Status: "todo"},
				{ID: "3", Title: "Task 3", Status: "todo"},
			},
		},
		{
			name:       "Delete present then Get->ErrNotFound",
			create:     models.Task{ID: "4", Title: "Task 4", Status: "todo"},
			deleteID:   "4",
			deleteWant: nil,
			getID:      "4",
			getWant:    ErrNotFound,
		},
		{
			name:       "Delete missing->ErrNotFound",
			deleteID:   "5",
			deleteWant: ErrNotFound,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := NewMemStore()

			// Create
			if err := s.CreateTask(context.Background(), tt.create); (err != nil) != (tt.getWant != nil) {
				t.Errorf("CreateTask(%+v) = %v, want %v", tt.create, err, tt.getWant)
			}

			// Get
			got, err := s.GetTask(context.Background(), tt.getID)
			if err != tt.getWant {
				t.Errorf("GetTask(%s) = %v, want %v", tt.getID, err, tt.getWant)
			}
			if tt.getWant == nil && got.ID != tt.getID {
				t.Errorf("GetTask(%s) = %v, want %s", tt.getID, got, tt.getID)
			}

			// List
			list, err := s.ListTasks(context.Background())
			if err != nil {
				t.Errorf("ListTasks() = %v, want nil", err)
			}
			if !equalTasks(list, tt.listWant) {
				t.Errorf("ListTasks() = %v, want %v", list, tt.listWant)
			}

			// Delete
			if err := s.DeleteTask(context.Background(), tt.deleteID); (err != nil) != (tt.deleteWant != nil) {
				t.Errorf("DeleteTask(%s) = %v, want %v", tt.deleteID, err, tt.deleteWant)
			}
		})
	}
}

func equalTasks(a, b []models.Task) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
