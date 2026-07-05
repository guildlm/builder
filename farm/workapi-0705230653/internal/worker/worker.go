package worker

import (
	"log/slog"
	"sync"
	"sync/atomic"

	"guildlm.dev/workapi/internal/models"
)

type Worker struct {
	ch        chan models.Event
	logger    *slog.Logger
	wg        sync.WaitGroup
	processed atomic.Int64
}

func NewWorker(size int, logger *slog.Logger) *Worker {
	return &Worker{
		ch:     make(chan models.Event, size),
		logger: logger,
	}
}

func (w *Worker) Start() {
	w.wg.Add(1)
	go func() {
		defer w.wg.Done()
		for e := range w.ch {
			w.process(e)
		}
	}()
}

func (w *Worker) Enqueue(e models.Event) {
	w.ch <- e
}

func (w *Worker) process(e models.Event) {
	w.processed.Add(1)
	w.logger.Debug("Processing event", "type", e.Type)
}

func (w *Worker) Stop() {
	close(w.ch)
	w.wg.Wait()
}

func (w *Worker) Processed() int64 {
	return w.processed.Load()
}
