package main

import (
	"errors"
)

// Sentinel errors returned by the store; callers compare with errors.Is.
var (
	ErrNotFound   = errors.New("not found")
	ErrExists     = errors.New("already exists")
	ErrValidation = errors.New("validation error")
)
