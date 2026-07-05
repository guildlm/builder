package service

import (
	"context"
	"strconv"
	"testing"

	"guildlm.dev/taskapipro/internal/models"
	"guildlm.dev/taskapipro/internal/store"
)

func TestCreateValidTask(t *testing.T) {
	s := store.NewMemStore()
	svc := NewTaskService(s)
	tk := models.Task{ID: "1", Title: "task1", Status: "todo"}
	got, err := svc.Create(context.Background(), tk)
	if err != nil {
		t.Fatalf("Create() error = %v, want nil", err)
	}
	if got.ID != tk.ID || got.Title != tk.Title || got.Status != tk.Status {
		t.Errorf("Create() = %v, want %v", got, tk)
	}
}

func TestCreateInvalidTask(t *testing.T) {
	s := store.NewMemStore()
	svc := NewTaskService(s)
	tk := models.Task{ID: "1", Title: "", Status: "todo"}
	_, err := svc.Create(context.Background(), tk)
	if err == nil {
		t.Fatalf("Create() error = %v, want %v", err, models.ErrInvalid)
	}
}

func TestListWithLimit(t *testing.T) {
	s := store.NewMemStore()
	svc := NewTaskService(s)
	for i := 0; i < 5; i++ {
		tk := models.Task{ID: strconv.Itoa(i), Title: "task " + strconv.Itoa(i), Status: "todo"}
		if _, err := svc.Create(context.Background(), tk); err != nil {
			t.Fatalf("Create(%s): unexpected error: %v", tk.ID, err)
		}
	}
	got, err := svc.List(context.Background(), 1, 0, "")
	if err != nil {
		t.Fatalf("List() error = %v, want nil", err)
	}
	if len(got) != 1 {
		t.Errorf("List() = %v, want 1 item", got)
	}
}

func TestListFiltersByStatus(t *testing.T) {
	s := store.NewMemStore()
	svc := NewTaskService(s)
	tk1 := models.Task{ID: "1", Title: "task1", Status: "todo"}
	tk2 := models.Task{ID: "2", Title: "task2", Status: "doing"}
	if _, err := svc.Create(context.Background(), tk1); err != nil {
		t.Fatalf("Create(%s): unexpected error: %v", tk1.ID, err)
	}
	if _, err := svc.Create(context.Background(), tk2); err != nil {
		t.Fatalf("Create(%s): unexpected error: %v", tk2.ID, err)
	}
	got, err := svc.List(context.Background(), 0, 0, "todo")
	if err != nil {
		t.Fatalf("List() error = %v, want nil", err)
	}
	if len(got) != 1 || got[0].ID != tk1.ID {
		t.Errorf("List() = %v, want 1 item with status 'todo'", got)
	}
}
