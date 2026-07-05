package main

import (
	"errors"
	"fmt"
	"time"
)

// ErrInvalidTask is the sentinel error returned when a task is invalid.
var ErrInvalidTask = errors.New("invalid task")

// Task represents a task with an ID, title, completion status, and creation time.
type Task struct {
	ID        int       `json:"id"`
	Title     string    `json:"title"`
	Done      bool      `json:"done"`
	CreatedAt time.Time `json:"created_at"`
}

// Validate checks if the task is valid, wrapping ErrInvalidTask via fmt.Errorf.
func (t Task) Validate() error {
	if t.Title == "" {
		return fmt.Errorf("%w: title is required", ErrInvalidTask)
	}
	return nil
}
