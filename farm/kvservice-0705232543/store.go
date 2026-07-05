package main

import (
	"sync"
)

type Store struct {
	mu sync.RWMutex
	m  map[string]string
}

func NewStore() *Store { return &Store{m: make(map[string]string)} }

func (s *Store) Get(key string) (string, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.m[key]
	return v, ok
}

func (s *Store) Set(key, value string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.m[key] = value
}
