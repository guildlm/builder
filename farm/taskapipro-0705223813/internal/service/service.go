package service

import (
	"context"

	"guildlm.dev/taskapipro/internal/models"
	"guildlm.dev/taskapipro/internal/store"
)

// TaskService defines the business logic for tasks.
type TaskService interface {
	Create(ctx context.Context, t models.Task) (models.Task, error)
	Get(ctx context.Context, id string) (models.Task, error)
	List(ctx context.Context, limit, offset int, status string) ([]models.Task, error)
	Delete(ctx context.Context, id string) error
}

// ProjectService defines the business logic for projects.
type ProjectService interface {
	Create(ctx context.Context, p models.Project) (models.Project, error)
	Get(ctx context.Context, id string) (models.Project, error)
	List(ctx context.Context, limit, offset int) ([]models.Project, error)
	Delete(ctx context.Context, id string) error
}

// taskService is an unexported implementation of TaskService.
type taskService struct {
	store store.Store
}

// NewTaskService creates a new TaskService.
func NewTaskService(s store.Store) TaskService {
	return &taskService{store: s}
}

// Create creates a new task.
func (s *taskService) Create(ctx context.Context, t models.Task) (models.Task, error) {
	if err := t.Validate(); err != nil {
		return models.Task{}, err
	}
	if err := s.store.CreateTask(ctx, t); err != nil {
		return models.Task{}, err
	}
	return t, nil
}

// Get retrieves a task by ID.
func (s *taskService) Get(ctx context.Context, id string) (models.Task, error) {
	return s.store.GetTask(ctx, id)
}

// List lists tasks with optional filtering and pagination.
func (s *taskService) List(ctx context.Context, limit, offset int, status string) ([]models.Task, error) {
	items, err := s.store.ListTasks(ctx)
	if err != nil {
		return nil, err
	}
	if status != "" {
		items = filterTasks(items, status)
	}
	return paginate(items, limit, offset), nil
}

// Delete deletes a task by ID.
func (s *taskService) Delete(ctx context.Context, id string) error {
	return s.store.DeleteTask(ctx, id)
}

// projectService is an unexported implementation of ProjectService.
type projectService struct {
	store store.Store
}

// NewProjectService creates a new ProjectService.
func NewProjectService(s store.Store) ProjectService {
	return &projectService{store: s}
}

// Create creates a new project.
func (s *projectService) Create(ctx context.Context, p models.Project) (models.Project, error) {
	if err := p.Validate(); err != nil {
		return models.Project{}, err
	}
	if err := s.store.CreateProject(ctx, p); err != nil {
		return models.Project{}, err
	}
	return p, nil
}

// Get retrieves a project by ID.
func (s *projectService) Get(ctx context.Context, id string) (models.Project, error) {
	return s.store.GetProject(ctx, id)
}

// List lists projects with optional pagination.
func (s *projectService) List(ctx context.Context, limit, offset int) ([]models.Project, error) {
	items, err := s.store.ListProjects(ctx)
	if err != nil {
		return nil, err
	}
	return paginate(items, limit, offset), nil
}

// Delete deletes a project by ID.
func (s *projectService) Delete(ctx context.Context, id string) error {
	return s.store.DeleteProject(ctx, id)
}

// paginate returns a subset of items based on limit and offset.
func paginate[T any](items []T, limit, offset int) []T {
	if limit <= 0 {
		return items
	}
	if offset >= len(items) {
		return []T{}
	}
	if offset+len(items)-offset < limit {
		return items[offset:]
	}
	return items[offset : offset+limit]
}

// filterTasks filters tasks by status.
func filterTasks(tasks []models.Task, status string) []models.Task {
	var filtered []models.Task
	for _, t := range tasks {
		if t.Status == status {
			filtered = append(filtered, t)
		}
	}
	return filtered
}

// var _ TaskService = (*taskService)(nil)
// var _ ProjectService = (*projectService)(nil)
