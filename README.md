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
  code, ignored error). An edit is kept only if the project stays green.
  FIRST FIELD MEASUREMENT, 2026-07-25 (logs/FINDING-review-pass-returns-fragments.txt),
  after this pass had never run in any of the 578 archived runs:
  - Against a planted, spec-relevant bug that no test covers, the specialist localised
    it from the SPEC alone — right file, right function, right constant — with no
    toolchain signal. That is the capability the residue needs: 36 of 44 archived
    failures now compile and fail a TEST, where no gate can reach.
  - It was being lost to a reply-format mismatch. Asked for the complete file, the
    specialist answers like a human reviewer: prose, then the function it fixed. The
    harness wrote that over the file and reverted the wreckage in silence. Fixed —
    fragments are now spliced back when every function they declare already exists,
    and refused otherwise.
  - On CORRECT code the same pass changed one file, behaviour-neutrally (three method
    registrations rewritten as equivalent closures). Never-hurt held; help was zero.
  So: real capability, small churn, N=1 each way. Worth turning on for a spec you are
  going to read; not yet worth quoting a number for.
- **Fleet routing / escalation** (`--fleet model@url,model@url`) — the base model
  writes every file; a file that keeps failing the gate is escalated to the next
  member, per file. This exists because no single model wins: on the 48-task dev
  bench the best single model *is* the plain base (44/48), yet a
  `{base, 7B specialist, 14B specialist}` union solves all 48 — each member owns a
  niche the base misses. Passing `build+vet+test` **is** the success criterion, so
  the gate that selects is the gate that scores. Measured at project scale on
  `specs/shortener.yaml`: same base, same 8-round budget, `--fleet` the only
  difference — **base-only 2/3 RED → fleet 3/3 GREEN** (independently re-verified
  with `go test`). Two honest caveats: it costs wall clock (+63% there, and up to
  3.1× on a spec it never greens — cost scales with *unresolved* escalations, so
  the expensive case is the one where routing is not working), and escalation is
  **not monotone** — a member can sit on a bug the base had already fixed.
  Both caveats argued for escalating only files the toolchain *blames*. That was
  built, measured and REVERTED the same day: shortener went 3/3 GREEN to 2/3 RED and
  workapi 3/3 to 2/3, on 2 and 5 escalations instead of 12 and 17. A compiler error
  names an implementation file; a failing assertion names the TEST — so across 32
  archived failures, 18 of the 19 that fail at runtime are repairing implementation
  files with NOT ONE of them blamed. Cut the widened files out of escalation and a
  defect only a test can reveal can never reach a stronger model
  (logs/FINDING-escalation-granularity.txt).

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

### Instruments

Model-free tools that answer a question the test suite cannot. All read-only, all free
(the Go toolchain, no model server) — and each exists because an assumption turned out to
be measurable:

| tool | question it answers |
|------|--------------------|
| `_gate_audit.py` | Which gates fire on real artifacts, and what is left once they run to a fixpoint? (`--regress` re-drives the whole archive; `--mechanisms` finds machinery that never runs at all) |
| `_escalation_surface.py` | How much of a fix round rests on inference rather than on what the toolchain named? |
| `_unrouted_compat.py` | Did a fix-loop change alter builds that do not use `--fleet`? Diff two trees instead of arguing. |
| `_named_test_audit.py` | Did the model write every test the spec NAMES — and does the spec name a mirrored route's tests at all? |
| `_teeth_suite.py`, `_mutant_check.sh` | Does a green suite actually defend its contract? (see [TEETH.md](TEETH.md)) |
| `_deadlock_detector.py` | Does a method re-acquire a mutex it already deferred-unlocked? |
| `_hole_hunt.py` | Sweep for undefended promises nobody thought to check — six mutation shapes, every site. An INERT clamp forwards to shape 6b, which breaks what the clamp ASSIGNS, because breaking what it tests changes nothing by construction. |
| `_bound_probe.py` | Is a SURVIVED row a HOLE, or was nothing broken? Writes the test the spec would get and requires it to pass unmutated and fail mutated. Split the fifteen boundary survivors 9 real / 6 not. `--locate` flips each occurrence in a file alone, because a shape tag is not an address. |
| `_hole_closed.py` | Did a spec edit close the hole it targeted **and open no other**? |
| `_registry_drift.py` | How many registered mutations survive a REGENERATION? Renames the artifact textually instead of regenerating it — brittleness is a property of the pattern. |
| `_why_red.py` | Triage a RED artifact: which tests fail, and do they cluster into one shape? |
| `_candidate_triage.py` | Before spending a run on a SURVIVED row: does the spec promise it, and can the site even take effect? Two greps that have ruled out two 20-minute runs. |
| `_test_durability.py` | Across several trees of ONE spec: which named tests does the model write EVERY run, **and does each one keep the same number of assertions**? A name persisting is not a promise staying defended. |
| `_mapsort_audit.py` | Which functions return a slice built from a MAP without sorting it? Go randomises map order per run, so one `go test` catches this only by luck. |

The habit worth copying is not the tools but what they do to themselves. A checker never
seen catching anything is indistinguishable from one that does nothing, so
`_escalation_surface.py --self-test` plants defects and requires the checker to flag them,
and `_teeth_suite.py` refuses to score a mutant whose UNMUTATED baseline is already red
(**BASELINE-RED — verdict void**), because a red baseline turns every mutant into a fake
CAUGHT. That is not paranoia: this session found `_gate_audit` scoring untouched artifacts
as "advanced" because it compared toolchain output that changes between runs of identical
code, and `_escalation_surface` counting empty archives as evidence for the very hypothesis
it was measuring. Instruments need instruments.

A later session sharpened the rule. Probing all nine with a target that does not exist
found **four** that answered about nothing with status 0 — an unmatched spec name printing
an empty table, a typo'd selector reporting a clean teeth run, an unreadable file exiting
green. Empty input, unmatched selector and unreadable file all collapse into the output of
a clean result, because *no findings* is what clean looks like. So every per-item check
here now prints its **denominator** beside its numerator: how many mutations actually ran,
how many packages ran tests, how many probes applied. `score_backend.py` prints how many
tests failed rather than the first one — the line that read `✗ test — --- FAIL: TestX`
looked identical for an artifact with one failure and one with six, and that ambiguity
carried two specs as *blocked on coder capability* through two full regenerations. Both
turned out to be one edit from green.

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
