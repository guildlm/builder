# GuildLM Builder

**An agentic Go project generator with real compile/test feedback.**

## The honest thesis

A 7B coder model does **not** reliably one-shot a working backend. Ask it for "a
tasks REST API" and you get plausible-looking code that misses an import, botches
a route signature, or fails a test. The fix is not a bigger prompt — it is an
**agent loop** that treats the compiler and test suite as ground truth:

```
        ┌─────────────────────────────────────────────────────┐
        │                                                     ▼
  spec ──► plan ──► generate ──► compile / vet / test ──► green? ──► done
            ▲          │                  │                  │
            │          │              (failure)            (no)
            │          │                  ▼                  │
            └──────────┴──────── fix (feed errors back) ◄────┘
                         up to max_fix_rounds
```

The model proposes; the Go toolchain disposes. Errors from `go build` / `go vet`
/ `go test` are fed back to the coder as targeted fix requests until the project
is green or the round budget is exhausted. That feedback loop is what turns a
fallible generator into one that emits **working** code.

GuildLM is a system for building specialist SLMs — `forge` (data), `anvil`
(training), `crucible` (eval / Go sandbox), `brain` (router). The Builder is the
front end that points such a coder model at a whole backend project.

## Capability = model × algorithm

The lever for "a small model writes big backends" is the **algorithm around the
model**, not raw parameter count. The Builder stacks the techniques that make a
narrow 7–14B Go specialist punch above a big general model:

- **Retrieval-grounded generation** (`--examples` / `--shots`) — show the coder
  the top-N *compile-verified* examples most similar to the file it's writing
  (offline Jaccard few-shot over the teacher dataset). Known-good Go in, idiomatic
  Go out.
- **Best-of-N rejection sampling** (`--candidates N`) — draw N samples per file,
  keep the first that `gofmt`-parses. Turns a small model's variance into a
  quality lift instead of a failed build.
- **Verification loop** — `go build`/`vet`/`test` as ground-truth reward; targeted
  fixes fed back until green.
- **Role routing** (`--test-model`) — the guild splits the work: the Go *dev*
  specialist writes implementation files, the Go *test* specialist writes
  `_test.go`. Each role is its own model/adapter.
- **Non-regressing review pass** (`--review-model`) — after green, the Go *review*
  specialist hunts for semantic bugs a green build hides (off-by-one, wrong status
  code, ignored error). An edit is kept only if the project stays green — review
  can help, never hurt.

Measure it at the level that matters with [`score_backend.py`](score_backend.py):
a whole generated backend scored `build + vet + test + server-runs` (0..4) by the
real toolchain — so you compare coders on *working backends*, not toy functions.

## Two parts

| Part | Path | What |
|------|------|------|
| **A — the proof** | [`examples/tasks-api/`](examples/tasks-api/) | A real, green, stdlib-only Go REST API. The quality target. |
| **B — the generator** | [`src/builder.py`](src/builder.py) | The agentic loop: plan → generate → compile → fix → iterate. |

## Quickstart

### Run the generator against a local Ollama `guildlm-go` model

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# Defaults talk to Ollama at http://localhost:11434/v1, model guildlm-go.
.venv/bin/guildlm-build --spec specs/tasks-api.yaml --out ./generated
```

### Or any OpenAI-compatible API

```sh
export GUILDLM_BUILDER_BASE_URL=https://api.openai.com/v1
export GUILDLM_BUILDER_API_KEY=sk-...
.venv/bin/guildlm-build --spec specs/tasks-api.yaml --out ./generated --model gpt-4o-mini
```

Configuration knobs (CLI flags override env):

| Env var | CLI flag | Default |
|---------|----------|---------|
| `GUILDLM_BUILDER_BASE_URL` | `--base-url` | `http://localhost:11434/v1` |
| `GUILDLM_BUILDER_MODEL` | `--model` | `guildlm-go` |
| `GUILDLM_BUILDER_API_KEY` | — | `ollama` |
| — | `--max-fix-rounds` | `4` |
| — | `--candidates` (best-of-N per file) | `1` |
| — | `--examples` / `--shots` (retrieval few-shot) | — / `2` |
| — | `--test-model` (route `_test.go` to a test specialist) | — |
| — | `--review-model` (non-regressing review pass) | — |

The full guild stack on one spec:

```sh
.venv/bin/guildlm-build --spec specs/tasks-api.yaml --out ./generated \
  --model guildlm-go-dev --test-model guildlm-go-test --review-model guildlm-go-review \
  --candidates 2 --examples ../guild-code/go/datasets/specialists/code_guild_go_dev/code_guild_go_dev.train.jsonl --shots 2
```

### See the quality target

[`examples/tasks-api/`](examples/tasks-api/) is what "good" looks like: clean
multi-file layout, `http.ServeMux` pattern routing, a thread-safe store, graceful
shutdown, and full vet/build/test/-race coverage. The spec in
[`specs/tasks-api.yaml`](specs/tasks-api.yaml) describes that project so a capable
coder, run through the loop, regenerates something equivalent.

## How it works (the moving parts)

- **`Spec` / `plan`** — a YAML describes the project and its target files;
  `plan` turns it into an ordered list of file tasks. Earlier files become
  context for later ones.
- **`Coder` protocol** — pluggable model. `OpenAICoder` (Ollama / vLLM / OpenAI)
  and `FakeCoder` (deterministic, for tests).
- **`extract_code`** — pulls the fenced ```` ```go ```` block out of chatty model
  output, or takes the whole text if it is already code.
- **`GoToolchain`** — runs the real `go build` / `vet` / `test` via subprocess
  and returns `(ok, combined_output)`. This is the feedback signal.
- **`build()`** — the loop: generate every file (retrieval-grounded, best-of-N),
  run the toolchain, and on failure send the offending file(s) back to the coder
  with the error output for a targeted fix, re-running until green or
  `max_fix_rounds` is hit; then an optional review pass.
- **`Retriever`** — offline Jaccard few-shot over a JSONL of verified examples;
  grounds each file's generation in similar known-good Go.
- **`RoleRoutingCoder` / `role_for_path`** — dispatch each file to its specialist
  (`_test.go` → test model, else dev model).
- **review pass** — after green, the review specialist proposes bug fixes that are
  applied only if the project stays green (`reviewer=`, `--review-model`).
- **`score_backend.py`** — project-level objective score (`build+vet+test+run`).

## Develop / test

```sh
# Python harness (uses the real local `go` for the toolchain tests)
.venv/bin/python -m pytest -q

# The reference Go backend
cd examples/tasks-api
go vet ./... && go build ./... && go test ./... && go test -race ./...
```

## Honest limitations

- **It produces a working MVP / scaffold, not a finished product.** The loop
  gets you to *compiles and passes its own tests*; it does not guarantee
  architectural elegance, security hardening, or business-logic correctness
  beyond what the spec and generated tests cover.
- **Quality scales with the coder model.** A weak model may never converge within
  the fix budget; a strong one converges in one or two rounds. The loop makes a
  mediocre model usable and a good model reliable — it does not turn a bad model
  into a good one.
- **Feedback is only as good as the tests.** Green means "builds, vets, and the
  generated tests pass." Thin tests mean thin guarantees. Treat the output as a
  starting point to iterate on, not a final deliverable.
- **Go-focused.** The toolchain wrapper and prompts target Go today.

## License

[Apache-2.0](LICENSE).
