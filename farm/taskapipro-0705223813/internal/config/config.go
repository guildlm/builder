package config

import (
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config holds server settings loaded from the environment with sane defaults.
type Config struct {
	Addr            string
	ReadTimeout     time.Duration
	WriteTimeout    time.Duration
	ShutdownTimeout time.Duration
	DefaultPageSize int
	MaxPageSize     int
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
		DefaultPageSize: 20,
		MaxPageSize:     100,
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
	if s := os.Getenv("DEFAULT_PAGE_SIZE"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil {
			return Config{}, fmt.Errorf("invalid DEFAULT_PAGE_SIZE: %w", err)
		}
		c.DefaultPageSize = n
	}
	if s := os.Getenv("MAX_PAGE_SIZE"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil {
			return Config{}, fmt.Errorf("invalid MAX_PAGE_SIZE: %w", err)
		}
		c.MaxPageSize = n
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
	if c.MaxPageSize <= 0 {
		return fmt.Errorf("max page size must be positive, got %d", c.MaxPageSize)
	}
	if c.DefaultPageSize <= 0 {
		return fmt.Errorf("default page size must be positive, got %d", c.DefaultPageSize)
	}
	if c.DefaultPageSize > c.MaxPageSize {
		return fmt.Errorf("default page size must not be greater than max page size")
	}
	return nil
}
