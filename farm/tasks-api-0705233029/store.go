package main

import (
	"errors"
	"sort"
	"sync"
	"time"
)

// ErrNotFound is returned when a lookup key is absent. Callers match it with
// errors.Is so the sentinel can be wrapped with context higher up.
var ErrNotFound = errors.New("not found")

// ErrExists is returned by Create when the ID is already taken.
var ErrExists = errors.New("already exists")

// Store is the abstraction the rest of the app depends on. A Postgres or SQLite
// implementation can be dropped in without touching callers.
type Store interface {
	Create(t Task) error
	Get(id int) (Task, error)
	List() []Task
	Delete(id int) error
}

// MemStore is a goroutine-safe in-memory Store.
type MemStore struct {
	mu     sync.RWMutex
	tasks  map[int]Task
	nextID int
}

// NewStore returns a ready-to-use empty store.
func NewStore() *MemStore {
	return &MemStore{tasks: make(map[int]Task), nextID: 1}
}

func (s *MemStore) Create(t Task) error {
	if err := t.Validate(); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[t.ID]; ok {
		return ErrExists
	}
	t.ID = s.nextID
	t.CreatedAt = time.Now()
	s.tasks[t.ID] = t
	s.nextID++
	return nil
}

func (s *MemStore) Get(id int) (Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.tasks[id]
	if !ok {
		return Task{}, ErrNotFound
	}
	return t, nil
}

// List returns every task ordered by ID so results are deterministic.
func (s *MemStore) List() []Task {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Task, 0, len(s.tasks))
	for _, t := range s.tasks {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func (s *MemStore) Delete(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[id]; !ok {
		return ErrNotFound
	}
	delete(s.tasks, id)
	return nil
}

// compile-time proof MemStore satisfies Store.
var _ Store = (*MemStore)(nil)
