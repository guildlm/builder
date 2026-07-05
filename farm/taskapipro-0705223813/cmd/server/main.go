package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"

	"guildlm.dev/taskapipro/internal/api"
	"guildlm.dev/taskapipro/internal/config"
	"guildlm.dev/taskapipro/internal/service"
	"guildlm.dev/taskapipro/internal/store"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, _ := config.Load()
	if err := cfg.Validate(); err != nil {
		logger.Error("config validation failed", "error", err)
		os.Exit(1)
	}

	s := store.NewMemStore()
	ts := service.NewTaskService(s)
	ps := service.NewProjectService(s)
	handler := api.NewRouter(ts, ps, logger)

	srv := &http.Server{
		Addr:         cfg.Addr,
		Handler:      handler,
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
	}

	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server failed", "error", err)
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
}
