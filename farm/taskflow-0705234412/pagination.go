package main

import (
	"net/http"
	"strconv"
)

// parsePage reads ?limit= and ?offset= query params with strconv, defaulting
// limit to 20 (max 100) and offset to 0, clamping negatives to the default/zero.
func parsePage(r *http.Request) (limit, offset int) {
	limitStr := r.URL.Query().Get("limit")
	if limitStr != "" {
		limit, _ = strconv.Atoi(limitStr)
		if limit < 0 {
			limit = 0
		} else if limit > 100 {
			limit = 100
		}
	} else {
		limit = 20
	}

	offsetStr := r.URL.Query().Get("offset")
	if offsetStr != "" {
		offset, _ = strconv.Atoi(offsetStr)
		if offset < 0 {
			offset = 0
		}
	} else {
		offset = 0
	}

	return
}

// paginate is a generic function that safely slices items with bounds checks.
// Offset past the end returns empty, never panics.
func paginate[T any](items []T, limit, offset int) []T {
	if offset >= len(items) {
		return []T{}
	}
	if offset+limit > len(items) {
		limit = len(items) - offset
	}
	return items[offset : offset+limit]
}
