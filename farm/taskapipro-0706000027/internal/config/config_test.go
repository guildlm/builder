package config

import (
	"testing"
	"time"
)

func TestLoad_AppliesDefaults(t *testing.T) {
	t.Setenv("ADDR", "")
	t.Setenv("READ_TIMEOUT", "")
	t.Setenv("WRITE_TIMEOUT", "")
	t.Setenv("SHUTDOWN_TIMEOUT", "")
	t.Setenv("DEFAULT_PAGE_SIZE", "")
	t.Setenv("MAX_PAGE_SIZE", "")
	got, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got.Addr != ":8080" {
		t.Errorf("Addr = %q, want :8080", got.Addr)
	}
	if got.MaxPageSize != 100 {
		t.Errorf("MaxPageSize = %d, want 100", got.MaxPageSize)
	}
}

func TestLoad_OverrideAndValidate(t *testing.T) {
	t.Setenv("ADDR", ":9090")
	t.Setenv("READ_TIMEOUT", "15s")
	t.Setenv("WRITE_TIMEOUT", "20s")
	t.Setenv("SHUTDOWN_TIMEOUT", "25s")
	t.Setenv("DEFAULT_PAGE_SIZE", "30")
	t.Setenv("MAX_PAGE_SIZE", "40")
	got, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got.Addr != ":9090" {
		t.Errorf("Addr = %q, want :9090", got.Addr)
	}
	if got.ReadTimeout != 15*time.Second {
		t.Errorf("ReadTimeout = %v, want 15s", got.ReadTimeout)
	}
	if got.WriteTimeout != 20*time.Second {
		t.Errorf("WriteTimeout = %v, want 20s", got.WriteTimeout)
	}
	if got.ShutdownTimeout != 25*time.Second {
		t.Errorf("ShutdownTimeout = %v, want 25s", got.ShutdownTimeout)
	}
	if got.DefaultPageSize != 30 {
		t.Errorf("DefaultPageSize = %d, want 30", got.DefaultPageSize)
	}
	if got.MaxPageSize != 40 {
		t.Errorf("MaxPageSize = %d, want 40", got.MaxPageSize)
	}
}

func TestLoad_InvalidMaxPageSize(t *testing.T) {
	t.Setenv("MAX_PAGE_SIZE", "10")
	t.Setenv("DEFAULT_PAGE_SIZE", "20")
	_, err := Load()
	if err == nil {
		t.Fatalf("Load() should have returned an error for invalid max page size")
	}
}
