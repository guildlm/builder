package store

import (
	"context"
	"errors"
	"testing"

	"guildlm.dev/workapi/internal/models"
)

func TestMemStore(t *testing.T) {
	t.Run("create->nil / dup->ErrExists", func(t *testing.T) {
		s := NewMemStore()
		if err := s.CreateTask(context.Background(), models.Task{ID: "1", Title: "task1"}); err != nil {
			t.Fatalf("CreateTask() error = %v", err)
		}
		if err := s.CreateTask(context.Background(), models.Task{ID: "1", Title: "task1"}); !errors.Is(err, ErrExists) {
			t.Fatalf("duplicate CreateTask() error = %v, want ErrExists", err)
		}
	})

	t.Run("Get present/missing ->ErrNotFound", func(t *testing.T) {
		s := NewMemStore()
		if _, err := s.GetTask(context.Background(), "1"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("GetTask() error = %v, want ErrNotFound", err)
		}
		if err := s.CreateTask(context.Background(), models.Task{ID: "1", Title: "task1"}); err != nil {
			t.Fatalf("CreateTask() error = %v", err)
		}
		got, err := s.GetTask(context.Background(), "1")
		if err != nil {
			t.Fatalf("GetTask() error = %v", err)
		}
		if got.Title != "task1" {
			t.Errorf("Title = %q, want task1", got.Title)
		}
	})

	t.Run("List id-sorted", func(t *testing.T) {
		s := NewMemStore()
		if err := s.CreateTask(context.Background(), models.Task{ID: "2", Title: "task2"}); err != nil {
			t.Fatalf("CreateTask() error = %v", err)
		}
		if err := s.CreateTask(context.Background(), models.Task{ID: "1", Title: "task1"}); err != nil {
			t.Fatalf("CreateTask() error = %v", err)
		}
		list, err := s.ListTasks(context.Background())
		if err != nil {
			t.Fatalf("ListTasks() error = %v", err)
		}
		if len(list) != 2 || list[0].ID != "1" || list[1].ID != "2" {
			t.Errorf("List order wrong: %+v", list)
		}
	})

	t.Run("Delete present then Get->ErrNotFound", func(t *testing.T) {
		s := NewMemStore()
		if err := s.CreateTask(context.Background(), models.Task{ID: "1", Title: "task1"}); err != nil {
			t.Fatalf("CreateTask() error = %v", err)
		}
		if err := s.DeleteTask(context.Background(), "1"); err != nil {
			t.Fatalf("DeleteTask() error = %v", err)
		}
		if _, err := s.GetTask(context.Background(), "1"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("GetTask() error = %v, want ErrNotFound", err)
		}
	})

	t.Run("Delete missing->ErrNotFound", func(t *testing.T) {
		s := NewMemStore()
		if err := s.DeleteTask(context.Background(), "missing"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("DeleteTask() error = %v, want ErrNotFound", err)
		}
	})
}
