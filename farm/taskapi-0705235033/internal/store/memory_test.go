package store

import (
	"errors"
	"testing"

	"guildlm.dev/taskapi/internal/models"
)

func TestMemStore(t *testing.T) {
	t.Run("create then get", func(t *testing.T) {
		s := NewMemStore()
		if err := s.CreateTask(models.Task{ID: "1", Title: "a"}); err != nil {
			t.Fatalf("CreateTask() error = %v", err)
		}
		got, err := s.GetTask("1")
		if err != nil {
			t.Fatalf("GetTask() error = %v", err)
		}
		if got.Title != "a" {
			t.Errorf("Title = %q, want a", got.Title)
		}
	})

	t.Run("duplicate create returns ErrExists", func(t *testing.T) {
		s := NewMemStore()
		if err := s.CreateTask(models.Task{ID: "1"}); err != nil {
			t.Fatalf("first CreateTask() error = %v", err)
		}
		if err := s.CreateTask(models.Task{ID: "1"}); !errors.Is(err, ErrExists) {
			t.Fatalf("duplicate CreateTask() error = %v, want ErrExists", err)
		}
	})

	t.Run("get missing returns ErrNotFound", func(t *testing.T) {
		s := NewMemStore()
		if _, err := s.GetTask("missing"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("GetTask() error = %v, want ErrNotFound", err)
		}
	})

	t.Run("delete missing returns ErrNotFound", func(t *testing.T) {
		s := NewMemStore()
		if err := s.DeleteTask("missing"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("DeleteTask() error = %v, want ErrNotFound", err)
		}
	})
}
