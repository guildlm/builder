package service

import (
	"context"

	"guildlm.dev/workapi/internal/models"
	"guildlm.dev/workapi/internal/store"
)

// EventEnqueuer is the service's outbound seam; a worker satisfies it in
// production, a slice-backed fake records calls in tests.
type EventEnqueuer interface {
	Enqueue(e models.Event)
}

// TaskService validates, delegates to the store, and emits an event ONLY
// after a successful create — a failed create never enqueues anything.
type TaskService interface {
	Create(ctx context.Context, t models.Task) (models.Task, error)
	Get(ctx context.Context, id string) (models.Task, error)
	List(ctx context.Context, limit, offset int, status string) ([]models.Task, error)
	Delete(ctx context.Context, id string) error
}

type taskService struct {
	store  store.Store
	events EventEnqueuer
}

// NewTaskService takes EVERY dependency the service uses — match the
// project's constructor signature exactly when calling it.
func NewTaskService(s store.Store, e EventEnqueuer) TaskService {
	return &taskService{store: s, events: e}
}

func (svc *taskService) Create(ctx context.Context, t models.Task) (models.Task, error) {
	if err := t.Validate(); err != nil {
		return models.Task{}, err
	}
	if err := svc.store.CreateTask(ctx, t); err != nil {
		return models.Task{}, err
	}
	svc.events.Enqueue(models.Event{Type: "task.created", TaskID: t.ID})
	return t, nil
}

func (svc *taskService) Get(ctx context.Context, id string) (models.Task, error) {
	return svc.store.GetTask(ctx, id)
}

func (svc *taskService) Delete(ctx context.Context, id string) error {
	return svc.store.DeleteTask(ctx, id)
}

func (svc *taskService) List(ctx context.Context, limit, offset int, status string) ([]models.Task, error) {
	items, err := svc.store.ListTasks(ctx)
	if err != nil {
		return nil, err
	}
	if status != "" {
		items = filterByStatus(items, status)
	}
	return paginate(items, limit, offset), nil
}

func filterByStatus(items []models.Task, status string) []models.Task {
	var out []models.Task
	for _, t := range items {
		if t.Status == status {
			out = append(out, t)
		}
	}
	return out
}

func paginate[T any](items []T, limit, offset int) []T {
	if offset >= len(items) {
		return []T{}
	}
	if limit <= 0 || limit > len(items)-offset {
		limit = len(items) - offset
	}
	return items[offset : offset+limit]
}

var _ TaskService = (*taskService)(nil)
