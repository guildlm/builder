// Package main implements a small, idiomatic, stdlib-only REST API for a
// "tasks" service. It is intentionally dependency-free so it can serve as a
// reference of the quality target for the GuildLM Builder agentic generator.
package main

import (
	"errors"
	"fmt"
	"strings"
	"time"
)

// Task is the core domain model. JSON tags define the wire format used by the
// HTTP handlers.
type Task struct {
	ID        int       `json:"id"`
	Title     string    `json:"title"`
	Done      bool      `json:"done"`
	CreatedAt time.Time `json:"created_at"`
}

// ErrInvalidTask is returned (wrapped) by Validate when a task fails
// validation. Callers can use errors.Is to detect it and map it to HTTP 400.
var ErrInvalidTask = errors.New("invalid task")

// Validate checks that a task is well-formed before it is stored. It returns an
// error wrapping ErrInvalidTask when the title is empty or only whitespace.
func (t Task) Validate() error {
	if strings.TrimSpace(t.Title) == "" {
		return fmt.Errorf("%w: title must not be empty", ErrInvalidTask)
	}
	return nil
}
