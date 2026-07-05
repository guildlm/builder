package config

import (
	"testing"
)

func TestLoad_AppliesDefaults(t *testing.T) {
	t.Setenv("ADDR", "")
	t.Setenv("AUTH_TOKEN", "")
	t.Setenv("QUEUE_SIZE", "")
	got, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got.Addr != ":8080" {
		t.Errorf("Addr = %q, want :8080", got.Addr)
	}
	if got.AuthToken != "secret" {
		t.Errorf("AuthToken = %q, want secret", got.AuthToken)
	}
	if got.QueueSize != 64 {
		t.Errorf("QueueSize = %d, want 64", got.QueueSize)
	}
}

func TestLoad_OverrideAndValidate(t *testing.T) {
	t.Setenv("ADDR", ":9090")
	t.Setenv("AUTH_TOKEN", "custom")
	t.Setenv("QUEUE_SIZE", "128")
	got, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got.Addr != ":9090" {
		t.Errorf("Addr = %q, want :9090", got.Addr)
	}
	if got.AuthToken != "custom" {
		t.Errorf("AuthToken = %q, want custom", got.AuthToken)
	}
	if got.QueueSize != 128 {
		t.Errorf("QueueSize = %d, want 128", got.QueueSize)
	}
}

func TestLoad_InvalidQueueSize(t *testing.T) {
	t.Setenv("QUEUE_SIZE", "-1")
	_, err := Load()
	if err == nil {
		t.Fatalf("Load() should return an error for invalid QUEUE_SIZE")
	}
}

func TestLoad_InvalidTimeouts(t *testing.T) {
	t.Setenv("READ_TIMEOUT", "invalid")
	t.Setenv("WRITE_TIMEOUT", "invalid")
	t.Setenv("SHUTDOWN_TIMEOUT", "invalid")
	_, err := Load()
	if err == nil {
		t.Fatalf("Load() should return an error for invalid timeouts")
	}
}
