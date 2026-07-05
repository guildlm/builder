package main

import (
	"bytes"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestUsersAPI(t *testing.T) {
	store := NewMemStore()
	router := NewRouter(store)

	testCases := []struct {
		method string
		path   string
		body   string
		want   int
	}{
		{"POST", "/users", `{"ID":"1","Name":"Ada","Email":"a@x.io"}`, http.StatusCreated},
		{"POST", "/users", `{"ID":"1","Name":"Ada"}`, http.StatusConflict},
		{"GET", "/users/1", "", http.StatusOK},
		{"GET", "/users/2", "", http.StatusNotFound},
		{"GET", "/users", "", http.StatusOK},
		{"DELETE", "/users/1", "", http.StatusNoContent},
		{"GET", "/users/1", "", http.StatusNotFound},
		{"DELETE", "/users/1", "", http.StatusNotFound},
		{"POST", "/users", `{"ID":"1",`, http.StatusBadRequest},
	}

	for _, tc := range testCases {
		t.Run(fmt.Sprintf("%s %s", tc.method, tc.path), func(t *testing.T) {
			req, err := http.NewRequest(tc.method, tc.path, bytes.NewBufferString(tc.body))
			if err != nil {
				t.Fatal(err)
			}
			req.Header.Set("Content-Type", "application/json")

			rec := httptest.NewRecorder()
			router.ServeHTTP(rec, req)

			if rec.Code != tc.want {
				t.Errorf("got %d, want %d", rec.Code, tc.want)
			}
		})
	}
}
