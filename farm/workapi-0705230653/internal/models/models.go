package models

import (
	"errors"
	"fmt"
)

// ErrInvalid is the sentinel wrapped by every validation failure.
var ErrInvalid = errors.New("invalid")

// Task is a domain entity representing a task with a lifecycle status.
type Task struct {
	ID     string `json:"id"`
	Title  string `json:"title"`
	Status string `json:"status"`
}

// Event is a SEPARATE domain type in the SAME package — a package often holds
// more than one type; define EVERY type the spec lists, not just the first.
type Event struct {
	Type   string `json:"type"`
	TaskID string `json:"task_id"`
}

// Validate reports whether the task is well-formed, wrapping ErrInvalid.
func (t Task) Validate() error {
	if t.ID == "" {
		return fmt.Errorf("%w: id is required", ErrInvalid)
	}
	if t.Title == "" {
		return fmt.Errorf("%w: title is required", ErrInvalid)
	}
	if t.Status != "todo" && t.Status != "doing" && t.Status != "done" {
		return fmt.Errorf("%w: bad status %q", ErrInvalid, t.Status)
	}
	return nil
}
