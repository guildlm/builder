package main

import (
	"encoding/json"
	"net/http"
)

type echoRequest struct {
	Message string `json:"message"`
}

type echoResponse struct {
	Echo   string `json:"echo"`
	Length int    `json:"length"`
}

// newMux exposes POST /echo: decode a JSON body, validate it, and respond with
// JSON. Standard library only — encoding/json + net/http.
func newMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/echo", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req echoRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}
		if req.Message == "" {
			http.Error(w, "message required", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(echoResponse{Echo: req.Message, Length: len(req.Message)})
	})
	return mux
}

func main() {
	http.ListenAndServe(":8080", newMux())
}
