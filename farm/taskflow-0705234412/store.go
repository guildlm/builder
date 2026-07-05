package main

import (
	"sort"
	"sync"
)

// Store is the in-memory repository for tasks and projects.
type Store struct {
	mu       sync.RWMutex
	tasks    map[string]Task
	projects map[string]Project
}

// NewStore returns a new, empty in-memory store.
func NewStore() *Store {
	return &Store{
		tasks:    make(map[string]Task),
		projects: make(map[string]Project),
	}
}

// CreateTask inserts a task into the store, returning ErrExists if the ID is already present.
func (s *Store) CreateTask(t Task) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[t.ID]; ok {
		return ErrExists
	}
	s.tasks[t.ID] = t
	return nil
}

// GetTask returns the task with the given ID, or ErrNotFound if absent.
func (s *Store) GetTask(id string) (Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	t, ok := s.tasks[id]
	if !ok {
		return Task{}, ErrNotFound
	}
	return t, nil
}

// ListTasks returns all tasks sorted by ID.
func (s *Store) ListTasks() []Task {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Task, 0, len(s.tasks))
	for _, t := range s.tasks {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// DeleteTask removes the task with the given ID, or returns ErrNotFound if absent.
func (s *Store) DeleteTask(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.tasks[id]; !ok {
		return ErrNotFound
	}
	delete(s.tasks, id)
	return nil
}

// CreateProject inserts a project into the store, returning ErrExists if the ID is already present.
func (s *Store) CreateProject(p Project) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.projects[p.ID]; ok {
		return ErrExists
	}
	s.projects[p.ID] = p
	return nil
}

// GetProject returns the project with the given ID, or ErrNotFound if absent.
func (s *Store) GetProject(id string) (Project, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.projects[id]
	if !ok {
		return Project{}, ErrNotFound
	}
	return p, nil
}

// ListProjects returns all projects sorted by ID.
func (s *Store) ListProjects() []Project {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Project, 0, len(s.projects))
	for _, p := range s.projects {
		out = append(out, p)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// DeleteProject removes the project with the given ID, or returns ErrNotFound if absent.
func (s *Store) DeleteProject(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.projects[id]; !ok {
		return ErrNotFound
	}
	delete(s.projects, id)
	return nil
}
