package worker

import (
	"io"
	"log/slog"
	"strconv"
	"sync"
	"testing"

	"guildlm.dev/workapi/internal/models"
)

func TestWorkerDrains(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	w := NewWorker(8, logger)
	w.Start()

	for i := 0; i < 5; i++ {
		w.Enqueue(models.Event{Type: "task.created", TaskID: "task" + strconv.Itoa(i)})
	}

	w.Stop()
	if got := w.Processed(); got != 5 {
		t.Errorf("Processed() = %d; want 5", got)
	}
}

func TestWorkerEnqueueConcurrent(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	w := NewWorker(8, logger)
	w.Start()

	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			w.Enqueue(models.Event{Type: "task.created", TaskID: "task" + strconv.Itoa(i)})
		}(i)
	}
	wg.Wait()

	w.Stop()
	if got := w.Processed(); got != 10 {
		t.Errorf("Processed() = %d; want 10", got)
	}
}
