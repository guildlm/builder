package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"

	"guildlm.dev/workapi/internal/api"
	"guildlm.dev/workapi/internal/config"
	"guildlm.dev/workapi/internal/service"
	"guildlm.dev/workapi/internal/store"
	"guildlm.dev/workapi/internal/worker"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, _ := config.Load()
	if err := cfg.Validate(); err != nil {
		logger.Error("config validation failed", "error", err)
		os.Exit(1)
	}

	s := store.NewMemStore()
	w := worker.NewWorker(cfg.QueueSize, logger)
	w.Start()

	svc := service.NewTaskService(s, w)
	handler := api.NewRouter(svc, cfg.AuthToken, logger)

	srv := &http.Server{
		Addr:         cfg.Addr,
		Handler:      handler,
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
	}

	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server error", "error", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, os.Interrupt)
	<-quit
	logger.Info("shutting down server")

	ctx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		logger.Error("shutdown failed", "error", err)
	}
	w.Stop()
	logger.Info("server stopped")
}
