package config

import (
	"fmt"
	"os"
	"time"
)

// Config holds server settings loaded from the environment with sane defaults.
type Config struct {
	Addr            string
	ReadTimeout     time.Duration
	WriteTimeout    time.Duration
	ShutdownTimeout time.Duration
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// Load reads configuration from environment variables, applying defaults for
// any that are unset, then validates the result.
func Load() (Config, error) {
	c := Config{
		Addr:            getenv("ADDR", ":8080"),
		ReadTimeout:     5 * time.Second,
		WriteTimeout:    10 * time.Second,
		ShutdownTimeout: 10 * time.Second,
	}
	if s := os.Getenv("READ_TIMEOUT"); s != "" {
		d, err := time.ParseDuration(s)
		if err != nil {
			return Config{}, fmt.Errorf("invalid READ_TIMEOUT: %w", err)
		}
		c.ReadTimeout = d
	}
	if s := os.Getenv("WRITE_TIMEOUT"); s != "" {
		d, err := time.ParseDuration(s)
		if err != nil {
			return Config{}, fmt.Errorf("invalid WRITE_TIMEOUT: %w", err)
		}
		c.WriteTimeout = d
	}
	if s := os.Getenv("SHUTDOWN_TIMEOUT"); s != "" {
		d, err := time.ParseDuration(s)
		if err != nil {
			return Config{}, fmt.Errorf("invalid SHUTDOWN_TIMEOUT: %w", err)
		}
		c.ShutdownTimeout = d
	}
	if err := c.Validate(); err != nil {
		return Config{}, err
	}
	return c, nil
}

// Validate reports whether the configuration is usable.
func (c Config) Validate() error {
	if c.Addr == "" {
		return fmt.Errorf("addr must not be empty")
	}
	if c.ReadTimeout <= 0 {
		return fmt.Errorf("read timeout must be positive, got %s", c.ReadTimeout)
	}
	if c.WriteTimeout <= 0 {
		return fmt.Errorf("write timeout must be positive, got %s", c.WriteTimeout)
	}
	if c.ShutdownTimeout <= 0 {
		return fmt.Errorf("shutdown timeout must be positive, got %s", c.ShutdownTimeout)
	}
	return nil
}
