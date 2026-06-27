# tasks-api

A small, idiomatic, **stdlib-only** Go REST API for a "tasks" service. No
external dependencies — just `net/http`, `encoding/json`, and `sync`. It uses
Go 1.22+ `http.ServeMux` method+pattern routing and an in-memory, thread-safe
store.

This is the **reference of the quality target** for the GuildLM Builder: the
agentic generator aims to produce backends of this shape and quality.

## Routes

| Method | Path          | Description            | Success | Errors        |
|--------|---------------|------------------------|---------|---------------|
| POST   | `/tasks`      | Create a task          | 201     | 400           |
| GET    | `/tasks`      | List all tasks         | 200     | —             |
| GET    | `/tasks/{id}` | Get one task           | 200     | 400, 404      |
| PUT    | `/tasks/{id}` | Update / toggle a task | 200     | 400, 404      |
| DELETE | `/tasks/{id}` | Delete a task          | 204     | 400, 404      |

Unregistered methods on a known path return `405 Method Not Allowed`. All error
bodies are JSON: `{"error":"..."}`.

## Task shape

```json
{ "id": 1, "title": "buy milk", "done": false, "created_at": "2026-06-28T12:00:00Z" }
```

`title` is required (non-empty, non-whitespace). `id` and `created_at` are
assigned by the server.

## Run

```sh
go run .            # listens on :8080
PORT=9090 go run .  # custom port
```

The server shuts down gracefully on `Ctrl-C` (SIGINT) or SIGTERM.

## Example curl

```sh
# create
curl -s -X POST localhost:8080/tasks -d '{"title":"write tests"}'
# list
curl -s localhost:8080/tasks
# get
curl -s localhost:8080/tasks/1
# toggle done
curl -s -X PUT localhost:8080/tasks/1 -d '{"title":"write tests","done":true}'
# delete
curl -s -i -X DELETE localhost:8080/tasks/1
```

## Test

```sh
go vet ./...
go build ./...
go test ./...
go test -race ./...
```
