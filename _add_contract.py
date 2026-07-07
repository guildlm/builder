#!/usr/bin/env python3
"""Append the verified map-of-structs write-back contract to the corpus.

Uses a file (not an inline heredoc) so the shell never command-substitutes the
```go backticks in the response (documented corruption trap).
"""
import json
import os

CORPUS = os.path.join(os.path.dirname(__file__), "examples/verified_contracts.jsonl")

instruction = (
    "Write a package main, goroutine-safe in-memory store backed by a "
    "map[string]Record guarded by a sync.RWMutex, where Record is a struct "
    "with a Hits int access counter. Get(key) returns the record and "
    "increments its Hits count, or a sentinel ErrNotFound (errors.Is-matchable) "
    "when absent; Peek(key) returns the record WITHOUT touching Hits, or "
    "ErrNotFound. The increment must persist so a later read sees it. "
    "Standard library only."
)

response = """```go
package main

import (
\t"errors"
\t"sync"
)

// ErrNotFound is a sentinel returned when a record is absent (errors.Is-matchable).
var ErrNotFound = errors.New("not found")

type Record struct {
\tKey   string
\tValue string
\tHits  int
}

type Store struct {
\tmu sync.RWMutex
\tm  map[string]Record
}

func NewStore() *Store { return &Store{m: make(map[string]Record)} }

func (s *Store) Put(key, value string) {
\ts.mu.Lock()
\tdefer s.mu.Unlock()
\ts.m[key] = Record{Key: key, Value: value}
}

// Get increments Hits. A map value is NOT addressable, so `s.m[key].Hits++`
// does not compile; copy the value, mutate it, then write it back.
func (s *Store) Get(key string) (Record, error) {
\ts.mu.Lock()
\tdefer s.mu.Unlock()
\tr, ok := s.m[key]
\tif !ok {
\t\treturn Record{}, ErrNotFound
\t}
\tr.Hits++
\ts.m[key] = r
\treturn r, nil
}

// Peek reads without incrementing Hits.
func (s *Store) Peek(key string) (Record, error) {
\ts.mu.RLock()
\tdefer s.mu.RUnlock()
\tr, ok := s.m[key]
\tif !ok {
\t\treturn Record{}, ErrNotFound
\t}
\treturn r, nil
}
```"""

rec = {"instruction": instruction, "response": response}

# guard against accidental double-add
existing = open(CORPUS).read()
if instruction[:60] in existing:
    print("ALREADY PRESENT — not appending")
else:
    with open(CORPUS, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print("appended 1 contract")

n = sum(1 for _ in open(CORPUS))
print(f"corpus now {n} contracts")
