package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestEcho(t *testing.T) {
	srv := httptest.NewServer(newMux())
	defer srv.Close()

	body, _ := json.Marshal(echoRequest{Message: "hi"})
	res, err := http.Post(srv.URL+"/echo", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", res.StatusCode)
	}
	var out echoResponse
	if err := json.NewDecoder(res.Body).Decode(&out); err != nil {
		t.Fatal(err)
	}
	if out.Echo != "hi" || out.Length != 2 {
		t.Fatalf("got %+v, want {Echo:hi Length:2}", out)
	}

	res, _ = http.Post(srv.URL+"/echo", "application/json", bytes.NewReader([]byte(`{}`)))
	if res.StatusCode != http.StatusBadRequest {
		t.Fatalf("empty message status = %d, want 400", res.StatusCode)
	}
}
