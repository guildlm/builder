package main

import (
	"errors"
	"sort"
	"sync"
	"time"
)

// ErrNotFound is the sentinel returned by Store methods when a task with the
// requested ID does not exist. Callers use errors.Is(err, ErrNotFound).
var ErrNotFound = errors.New("task not found")

// Store is a thread-safe, in-memory collection of tasks. The zero value is not
// usable; construct one with NewStore.
type Store struct {
	mu     sync.RWMutex
	tasks  map[int]Task
	nextID int
	// now is injectable so tests can control timestamps; defaults to time.Now.
	now func() time.Time
}

// NewStore returns an empty, ready-to-use Store.
func NewStore() *Store {
	return &Store{
		tasks:  make(map[int]Task),
		nextID: 1,
		now:    time.Now,
	}
}

// Create validates and inserts a new task, assigning it a fresh auto-increment
// ID and a creation timestamp. It returns the stored task.
func (s *Store) Create(t Task) (Task, error) {
	if err := t.Validate(); err != nil {
		return Task{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	t.ID = s.nextID
	s.nextID++
	t.CreatedAt = s.now()
	s.tasks[t.ID] = t
	return t, nil
}

// List returns all tasks ordered by ascending ID. The returned slice is a copy
// and safe for the caller to mutate.
func (s *Store) List() []Task {
	s.mu.RLock()
	defer s.mu.RUnlock()

	out := make([]Task, 0, len(s.tasks))
	for _, t := range s.tasks {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// Get returns the task with the given ID, or ErrNotFound.
func (s *Store) Get(id int) (Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	t, ok := s.tasks[id]
	if !ok {
		return Task{}, ErrNotFound
	}
	return t, nil
}

// Update applies the mutable fields (Title, Done) of in to the stored task with
// the given ID. ID and CreatedAt are preserved. It returns the updated task or
// ErrNotFound.
func (s *Store) Update(id int, in Task) (Task, error) {
	if err := in.Validate(); err != nil {
		return Task{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	existing, ok := s.tasks[id]
	if !ok {
		return Task{}, ErrNotFound
	}
	existing.Title = in.Title
	existing.Done = in.Done
	s.tasks[id] = existing
	return existing, nil
}

// Delete removes the task with the given ID, or returns ErrNotFound.
func (s *Store) Delete(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, ok := s.tasks[id]; !ok {
		return ErrNotFound
	}
	delete(s.tasks, id)
	return nil
}
