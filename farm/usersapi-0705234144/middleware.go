package main

import (
	"log"
	"net/http"
	"time"
)

// Middleware wraps an http.Handler to add one cross-cutting concern.
// Composing them keeps handlers focused on business logic.
type Middleware func(http.Handler) http.Handler

// Chain applies middlewares so the FIRST listed is the OUTERMOST layer:
// Chain(h, Logging, Recover) runs Logging(Recover(h)).
func Chain(h http.Handler, mws ...Middleware) http.Handler {
	for i := len(mws) - 1; i >= 0; i-- {
		h = mws[i](h)
	}
	return h
}

// statusRecorder captures the status code a downstream handler writes so the
// logging middleware can report it. It defaults to 200 like net/http does.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

// Logging records method, path, resolved status and latency for each request.
func Logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		log.Printf("%s %s -> %d (%s)", r.Method, r.URL.Path, rec.status, time.Since(start))
	})
}

// Recover converts a panic in any downstream handler into a 500 response
// instead of letting it crash the server.
func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if err := recover(); err != nil {
				log.Printf("panic: %v", err)
				http.Error(w, "internal server error", http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}
