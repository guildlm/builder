package main

import (
	"fmt"
)

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

// Validate reports whether the task is well-formed, wrapping ErrValidation via fmt.Errorf on empty or invalid fields.
func (t Task) Validate() error {
	if t.Title == "" {
		return fmt.Errorf("%w: title is required", ErrValidation)
	}
	if t.Status != "todo" && t.Status != "doing" && t.Status != "done" {
		return fmt.Errorf("%w: bad status %q", ErrValidation, t.Status)
	}
	return nil
}

// Validate reports whether the project is well-formed, wrapping ErrValidation via fmt.Errorf on empty or invalid fields.
func (p Project) Validate() error {
	if p.Name == "" {
		return fmt.Errorf("%w: name is required", ErrValidation)
	}
	return nil
}
