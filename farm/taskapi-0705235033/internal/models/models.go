package models

import (
	"errors"
	"fmt"
)

// ErrInvalid is the sentinel wrapped by every validation failure.
var ErrInvalid = errors.New("invalid")

// Task is a domain entity representing a task with a lifecycle status.
type Task struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Status    string `json:"status"`
	ProjectID string `json:"project_id"`
}

// Project is a domain entity representing a project.
type Project struct {
	ID   string `json:"id"`
	Name string `json:"name"`
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

// Validate reports whether the project is well-formed, wrapping ErrInvalid.
func (p Project) Validate() error {
	if p.ID == "" {
		return fmt.Errorf("%w: id is required", ErrInvalid)
	}
	if p.Name == "" {
		return fmt.Errorf("%w: name is required", ErrInvalid)
	}
	return nil
}
