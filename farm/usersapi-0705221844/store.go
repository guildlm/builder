package main

import (
	"errors"
	"sort"
	"sync"
)

// ErrNotFound is returned when a lookup key is absent. Callers match it with
// errors.Is so the sentinel can be wrapped with context higher up.
var ErrNotFound = errors.New("not found")

// ErrExists is returned by Create when the ID is already taken.
var ErrExists = errors.New("already exists")

// User is the stored entity.
type User struct {
	ID    string
	Name  string
	Email string
}

// Store is the abstraction the rest of the app depends on. A Postgres or SQLite
// implementation can be dropped in without touching callers.
type Store interface {
	Create(u User) error
	Get(id string) (User, error)
	List() []User
	Delete(id string) error
}

// MemStore is a goroutine-safe in-memory Store.
type MemStore struct {
	mu    sync.RWMutex
	users map[string]User
}

// NewMemStore returns a ready-to-use empty store.
func NewMemStore() *MemStore {
	return &MemStore{users: make(map[string]User)}
}

func (s *MemStore) Create(u User) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.users[u.ID]; ok {
		return ErrExists
	}
	s.users[u.ID] = u
	return nil
}

func (s *MemStore) Get(id string) (User, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	u, ok := s.users[id]
	if !ok {
		return User{}, ErrNotFound
	}
	return u, nil
}

// List returns every user ordered by ID so results are deterministic.
func (s *MemStore) List() []User {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]User, 0, len(s.users))
	for _, u := range s.users {
		out = append(out, u)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func (s *MemStore) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.users[id]; !ok {
		return ErrNotFound
	}
	delete(s.users, id)
	return nil
}

// compile-time proof MemStore satisfies Store.
var _ Store = (*MemStore)(nil)
