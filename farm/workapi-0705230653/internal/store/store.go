package store

import (
	"context"
	"errors"
	"sort"
	"sync"

	"guildlm.dev/workapi/internal/models"
)

// Sentinel errors returned by the store; callers compare with errors.Is.
var (
	ErrNotFound = errors.New("not found")
	ErrExists   = errors.New("already exists")
)

// Store is the interface for the task store.
type Store interface {
	CreateTask(ctx context.Context, t models.Task) error
	GetTask(ctx context.Context, id string) (models.Task, error)
	ListTasks(ctx context.Context) ([]models.Task, error)
	DeleteTask(ctx context.Context, id string) error
}

// MemStore is a concurrency-safe in-memory implementation of the store.
type MemStore struct {
	mu    sync.RWMutex
	tasks map[string]models.Task
}

// NewMemStore returns an initialised, empty store.
func NewMemStore() *MemStore {
	return &MemStore{tasks: make(map[string]models.Task)}
}

// Create inserts t, returning ErrExists if the ID is already present.
func (s *MemStore) CreateTask(ctx context.Context, t models.Task) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[t.ID]; ok {
		return ErrExists
	}
	s.tasks[t.ID] = t
	return nil
}

// Get returns the task, or ErrNotFound if absent.
func (s *MemStore) GetTask(ctx context.Context, id string) (models.Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.tasks[id]
	if !ok {
		return models.Task{}, ErrNotFound
	}
	return t, nil
}

// Delete removes the task, or returns ErrNotFound if absent.
func (s *MemStore) DeleteTask(ctx context.Context, id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[id]; !ok {
		return ErrNotFound
	}
	delete(s.tasks, id)
	return nil
}

// List returns all tasks sorted by ID.
func (s *MemStore) ListTasks(ctx context.Context) ([]models.Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]models.Task, 0, len(s.tasks))
	for _, t := range s.tasks {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}
