package main

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestKV(t *testing.T) {
	tests := []struct {
		name    string
		key     string
		value   string
		want    int
		wantVal string
	}{
		{"PUT and GET existing key", "a", "hi", http.StatusCreated, "hi"},
		{"GET missing key", "missing", "", http.StatusNotFound, ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(newMux(NewStore()))
			defer srv.Close()

			// PUT request
			req, _ := http.NewRequest(http.MethodPut, srv.URL+"/kv/"+tt.key, bytes.NewReader([]byte(tt.value)))
			res, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			if res.StatusCode != tt.want {
				t.Fatalf("PUT status = %d, want %d", res.StatusCode, tt.want)
			}

			// GET request
			res, err = http.Get(srv.URL + "/kv/" + tt.key)
			if err != nil {
				t.Fatal(err)
			}
			if res.StatusCode != tt.want {
				t.Fatalf("GET status = %d, want %d", res.StatusCode, tt.want)
			}
			body, _ := io.ReadAll(res.Body)
			if string(body) != tt.wantVal {
				t.Fatalf("GET body = %q, want %q", body, tt.wantVal)
			}
		})
	}
}
