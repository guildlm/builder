package service

import (
	"context"
	"errors"
	"strconv"
	"testing"

	"guildlm.dev/workapi/internal/store"

	"guildlm.dev/workapi/internal/models"
)

type fakeEnqueuer struct {
	Events []models.Event
}

func (f *fakeEnqueuer) Enqueue(e models.Event) {
	f.Events = append(f.Events, e)
}

func TestCreateEnqueuesOnlyOnSuccess(t *testing.T) {
	cases := []struct {
		name       string
		task       models.Task
		wantErr    error
		wantEvents int // 1 for a valid create, 0 when validation fails
	}{
		{"valid task", models.Task{ID: "1", Title: "t1", Status: "todo"}, nil, 1},
		{"invalid status", models.Task{ID: "2", Title: "t2", Status: "bogus"}, models.ErrInvalid, 0},
		{"missing title", models.Task{ID: "3", Title: "", Status: "todo"}, models.ErrInvalid, 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fake := &fakeEnqueuer{}
			svc := NewTaskService(store.NewMemStore(), fake) // fresh deps per row
			_, err := svc.Create(context.Background(), tc.task)
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("Create() error = %v, want %v", err, tc.wantErr)
			}
			if len(fake.Events) != tc.wantEvents {
				t.Fatalf("Enqueue() called %d times, want %d", len(fake.Events), tc.wantEvents)
			}
			if tc.wantEvents == 1 {
				// only inspect the event when the row expects one
				if fake.Events[0].Type != "task.created" || fake.Events[0].TaskID != tc.task.ID {
					t.Fatalf("Enqueue() got wrong event: %+v", fake.Events[0])
				}
			}
		})
	}
}

func TestListWithLimit(t *testing.T) {
	cases := []struct {
		name  string
		limit int
		want  int
	}{
		{"limit 2 of 5", 2, 2},
		{"limit 0 means all", 0, 5},
		{"limit beyond len", 99, 5},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			svc := NewTaskService(store.NewMemStore(), &fakeEnqueuer{}) // fresh per subtest
			for i := 0; i < 5; i++ {
				id := strconv.Itoa(i) // unique per iteration, never string(i)
				if _, err := svc.Create(context.Background(), models.Task{ID: id, Title: "task " + id, Status: "todo"}); err != nil {
					t.Fatalf("Create(%s): unexpected error: %v", id, err)
				}
			}
			items, err := svc.List(context.Background(), tc.limit, 0, "")
			if err != nil {
				t.Fatalf("List() error = %v", err)
			}
			if got := len(items); got != tc.want {
				t.Fatalf("List(%d) returned %d tasks, want %d", tc.limit, got, tc.want)
			}
		})
	}
}
