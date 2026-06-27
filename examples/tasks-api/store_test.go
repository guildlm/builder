package main

import (
	"errors"
	"sync"
	"testing"
)

func TestStoreCreateValidation(t *testing.T) {
	tests := []struct {
		name    string
		title   string
		wantErr error
	}{
		{name: "valid", title: "buy milk", wantErr: nil},
		{name: "empty title", title: "", wantErr: ErrInvalidTask},
		{name: "whitespace title", title: "   ", wantErr: ErrInvalidTask},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s := NewStore()
			got, err := s.Create(Task{Title: tc.title})
			if tc.wantErr != nil {
				if !errors.Is(err, tc.wantErr) {
					t.Fatalf("Create() err = %v, want %v", err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("Create() unexpected err = %v", err)
			}
			if got.ID != 1 {
				t.Errorf("first ID = %d, want 1", got.ID)
			}
			if got.CreatedAt.IsZero() {
				t.Error("CreatedAt was not set")
			}
		})
	}
}

func TestStoreCRUD(t *testing.T) {
	s := NewStore()

	a, err := s.Create(Task{Title: "a"})
	if err != nil {
		t.Fatalf("Create a: %v", err)
	}
	b, err := s.Create(Task{Title: "b"})
	if err != nil {
		t.Fatalf("Create b: %v", err)
	}
	if a.ID == b.ID {
		t.Fatalf("IDs must be unique, both = %d", a.ID)
	}

	// List is sorted by ID.
	list := s.List()
	if len(list) != 2 || list[0].ID != a.ID || list[1].ID != b.ID {
		t.Fatalf("List() = %+v, want [a b] sorted by ID", list)
	}

	// Get existing.
	got, err := s.Get(a.ID)
	if err != nil || got.Title != "a" {
		t.Fatalf("Get(%d) = %+v, %v", a.ID, got, err)
	}

	// Update preserves ID/CreatedAt, changes Title/Done.
	upd, err := s.Update(a.ID, Task{Title: "a2", Done: true})
	if err != nil {
		t.Fatalf("Update: %v", err)
	}
	if upd.ID != a.ID || !upd.Done || upd.Title != "a2" || !upd.CreatedAt.Equal(a.CreatedAt) {
		t.Fatalf("Update result = %+v", upd)
	}

	// Delete then confirm not found.
	if err := s.Delete(b.ID); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, err := s.Get(b.ID); !errors.Is(err, ErrNotFound) {
		t.Fatalf("Get after delete err = %v, want ErrNotFound", err)
	}
}

func TestStoreNotFound(t *testing.T) {
	s := NewStore()
	if _, err := s.Get(999); !errors.Is(err, ErrNotFound) {
		t.Errorf("Get err = %v, want ErrNotFound", err)
	}
	if _, err := s.Update(999, Task{Title: "x"}); !errors.Is(err, ErrNotFound) {
		t.Errorf("Update err = %v, want ErrNotFound", err)
	}
	if err := s.Delete(999); !errors.Is(err, ErrNotFound) {
		t.Errorf("Delete err = %v, want ErrNotFound", err)
	}
}

// TestStoreConcurrent exercises the RWMutex under the race detector.
func TestStoreConcurrent(t *testing.T) {
	s := NewStore()
	const n = 50
	var wg sync.WaitGroup
	wg.Add(n)
	for i := 0; i < n; i++ {
		go func() {
			defer wg.Done()
			created, err := s.Create(Task{Title: "concurrent"})
			if err != nil {
				t.Errorf("Create: %v", err)
				return
			}
			if _, err := s.Get(created.ID); err != nil {
				t.Errorf("Get: %v", err)
			}
			_ = s.List()
		}()
	}
	wg.Wait()
	if got := len(s.List()); got != n {
		t.Errorf("after %d concurrent creates, len = %d", n, got)
	}
}
