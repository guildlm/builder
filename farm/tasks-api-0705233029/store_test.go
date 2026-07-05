package main

import (
	"errors"
	"fmt"
	"sync"
	"testing"
)

func TestStoreCRUD(t *testing.T) {
	t.Run("create then get", func(t *testing.T) {
		s := NewStore()
		if err := s.Create(Task{Title: "a"}); err != nil {
			t.Fatalf("Create() error = %v", err)
		}
		got, err := s.Get(1)
		if err != nil {
			t.Fatalf("Get() error = %v", err)
		}
		if got.Title != "a" {
			t.Errorf("Title = %q, want a", got.Title)
		}
	})

	t.Run("duplicate create returns ErrExists", func(t *testing.T) {
		s := NewStore()
		if err := s.Create(Task{Title: "a"}); err != nil {
			t.Fatalf("first Create() error = %v", err)
		}
		if err := s.Create(Task{Title: "a"}); !errors.Is(err, ErrExists) {
			t.Fatalf("duplicate Create() error = %v, want ErrExists", err)
		}
	})

	t.Run("get missing returns ErrNotFound", func(t *testing.T) {
		s := NewStore()
		if _, err := s.Get(1); !errors.Is(err, ErrNotFound) {
			t.Fatalf("Get() error = %v, want ErrNotFound", err)
		}
	})

	t.Run("delete missing returns ErrNotFound", func(t *testing.T) {
		s := NewStore()
		if err := s.Delete(1); !errors.Is(err, ErrNotFound) {
			t.Fatalf("Delete() error = %v, want ErrNotFound", err)
		}
	})

	t.Run("list is ID-ordered", func(t *testing.T) {
		s := NewStore()
		if err := s.Create(Task{Title: "b"}); err != nil {
			t.Fatalf("Create() error = %v", err)
		}
		if err := s.Create(Task{Title: "a"}); err != nil {
			t.Fatalf("Create() error = %v", err)
		}
		list := s.List()
		if len(list) != 2 || list[0].Title != "a" || list[1].Title != "b" {
			t.Fatalf("list order wrong: %+v", list)
		}
	})

	t.Run("delete removes task", func(t *testing.T) {
		s := NewStore()
		if err := s.Create(Task{Title: "a"}); err != nil {
			t.Fatalf("Create() error = %v", err)
		}
		if err := s.Delete(1); err != nil {
			t.Fatalf("Delete() error = %v", err)
		}
		if _, err := s.Get(1); !errors.Is(err, ErrNotFound) {
			t.Fatalf("Get() error = %v, want ErrNotFound", err)
		}
	})
}

func TestStoreConcurrentAccess(t *testing.T) {
	s := NewStore()
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			id := i + 1
			_ = s.Create(Task{ID: id, Title: fmt.Sprintf("task%d", id)})
			_, _ = s.Get(id)
			_ = s.List()
		}(i)
	}
	wg.Wait()
}
