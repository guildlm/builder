package store

import (
	"context"
	"errors"
	"sort"
	"sync"

	"guildlm.dev/taskapipro/internal/models"
)

// ErrNotFound is returned when a lookup key is absent.
var ErrNotFound = errors.New("not found")

// ErrExists is returned by Create when the ID is already taken.
var ErrExists = errors.New("already exists")

// Store is the abstraction the rest of the app depends on. A Postgres or SQLite
// implementation can be dropped in without touching callers.
type Store interface {
	CreateTask(ctx context.Context, t models.Task) error
	GetTask(ctx context.Context, id string) (models.Task, error)
	ListTasks(ctx context.Context) ([]models.Task, error)
	DeleteTask(ctx context.Context, id string) error
	CreateProject(ctx context.Context, p models.Project) error
	GetProject(ctx context.Context, id string) (models.Project, error)
	ListProjects(ctx context.Context) ([]models.Project, error)
	DeleteProject(ctx context.Context, id string) error
}

// MemStore is a goroutine-safe in-memory Store.
type MemStore struct {
	mu       sync.RWMutex
	tasks    map[string]models.Task
	projects map[string]models.Project
}

// NewMemStore returns a ready-to-use empty store.
func NewMemStore() *MemStore {
	return &MemStore{
		tasks:    make(map[string]models.Task),
		projects: make(map[string]models.Project),
	}
}

func (s *MemStore) CreateTask(ctx context.Context, t models.Task) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[t.ID]; ok {
		return ErrExists
	}
	s.tasks[t.ID] = t
	return nil
}

func (s *MemStore) GetTask(ctx context.Context, id string) (models.Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.tasks[id]
	if !ok {
		return models.Task{}, ErrNotFound
	}
	return t, nil
}

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

func (s *MemStore) DeleteTask(ctx context.Context, id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[id]; !ok {
		return ErrNotFound
	}
	delete(s.tasks, id)
	return nil
}

func (s *MemStore) CreateProject(ctx context.Context, p models.Project) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.projects[p.ID]; ok {
		return ErrExists
	}
	s.projects[p.ID] = p
	return nil
}

func (s *MemStore) GetProject(ctx context.Context, id string) (models.Project, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.projects[id]
	if !ok {
		return models.Project{}, ErrNotFound
	}
	return p, nil
}

func (s *MemStore) ListProjects(ctx context.Context) ([]models.Project, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]models.Project, 0, len(s.projects))
	for _, p := range s.projects {
		out = append(out, p)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out, nil
}

func (s *MemStore) DeleteProject(ctx context.Context, id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.projects[id]; !ok {
		return ErrNotFound
	}
	delete(s.projects, id)
	return nil
}

// compile-time proof MemStore satisfies Store.
var _ Store = (*MemStore)(nil)
