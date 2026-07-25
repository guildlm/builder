# Teeth: does a green suite actually DEFEND its contract?

A passing test suite proves the lines ran, not that the promises hold. This project
measured that directly: a ledger that drops every credit, a rate limiter with no burst
cap, an LRU that forgets to refresh an updated key, an event bus whose `Publish` blocks
on a full subscriber — **all ship green, all pass coverage**. Coverage counts lines
executed; it cannot count invariants defended, because a sorted and an unsorted list
execute the same lines.

The only instrument that sees the difference is a **deliberate break**: mutate the code
so it violates a promise the spec actually makes, then ask whether any test goes red.

- **CAUGHT** — the suite went red on broken code → the invariant is *defended* (it has teeth).
- **SURVIVED** — the suite stayed green on broken code → the invariant is *undefended* (a hole).

## Tools (all model-free, deterministic)

| tool | question it answers | runs code? |
|------|--------------------|:---------:|
| `_teeth_suite.py` | Do the registered mutations each get caught? (regression suite) | yes (`go test`) |
| `_mutant_check.sh <spec>` | Does one spec's suite catch a hand-written bug? (exploratory) | yes (build+vet+test) |
| `_named_test_audit.py` | Did the model write every test the spec NAMES? | no (static) |
| `_deadlock_detector.py` | Does a method re-acquire a mutex it already deferred-unlocked? | no (static) |
| `_hole_hunt.py` | Sweep for holes nobody thought to check — mutate every status write and drop every response header, across every artifact | yes (`go test`) |
| `_hole_closed.py` | Did a spec edit close the hole it targeted **and open no other**? | yes (`go test`) |

`_named_test_audit.py` matches on names, so a test that is *present but vacuous* (right
name, missing assertion) passes the audit while the hole stays open. Names are checkable
by grep; teeth are not. That is why the mutation tools exist alongside it.

`_hole_hunt.py` exists because the registry reached **29 CAUGHT / 0 SURVIVED** by testing
invariants someone chose one at a time — which reads as "no holes left" and means "no holes
left among the ones I thought of". Sweeping instead, across four shapes and every site:

| shape | probe | genuine holes / probes |
|-------|-------|:---------------------:|
| status code | swap for a plausible neighbour | 3 / 9 |
| response header | delete the `Header().Set` line | 1 / 8 (+3 spec gaps) |
| sort order | REVERSE the comparator (never delete the sort) | 0 / 6 |
| error wrapping | `%w` → `%v` | **2 / 5** |

**34 probes, 11 survivors, 6 genuine undefended promises** — including `shortener`'s
`GET /health -> 200 "ok"`, which the spec states outright and **no test touches at all**.

Error wrapping is the best yield and that is not an accident of this corpus: the other
shapes change something a test can notice by accident — a status, a header, an order —
while `%w` → `%v` leaves the message byte-identical and breaks only `errors.Is`. A suite
passes unless somebody deliberately wrote `errors.Is`. Most likely to be undefended, least
likely to be spotted by reading.

Sort order yielding nothing is also a result: it is the invariant this campaign hardened by
hand, three of those six are registered mutations, and an independent sweep agreeing with
the registry is the cross-check the registry never had.

Two rules keep it honest:

- **A SURVIVED row is a candidate, not a verdict.** The next question is always whether the
  SPEC promises the behaviour that was broken. Of 9 survivors, 4 were real, 2 were a
  recurring log-only false positive (marked `SURVIVED*` rather than filtered out — removing
  a class is how a hunter goes quiet), and 3 were behaviour the spec never asked for. Those
  last three are SPEC gaps, not test gaps: by this project's own law, implicit means broken.
- **Closing a hole means naming a test in the spec**, then regenerating and grading with
  `_hole_closed.py` — which asks both questions, because a spec edit reaches every file's
  prompt and one that buys a hole while opening another still looks like a win from the
  headline number.

### The loop, demonstrated end to end (2026-07-25)

`shortener`'s `GET /health -> 200 "ok"` — promised by the spec, touched by no test — was
closed and graded against a rule fixed in advance:

    sweep finds it -> spec NAMES TestHealthOK -> regenerate -> grade
    TestHealthOK written and passing · build 3/3 GREEN
    /health mutation SURVIVED -> CAUGHT      <- the hole
    registered redirect-301 mutation CAUGHT  <- nothing regressed

It took three attempts and **every failure was in the edit, not the method**:

1. **Appending is not naming.** The first attempt added a requirement to an existing
   test's description instead of naming a test. The model dropped it entirely. Naming is
   what the model produces and what `_named_test_audit` can see; a clause inside another
   test's prose is neither.
2. **Write for a reader who does not already know the answer.** The second attempt named
   the test and the model wrote it — then it failed, because it `json.Decode`d a body that
   is the plain text `ok`. The spec said "the body is exactly `ok`" in a service where
   every other response is JSON. The model followed the house style, correctly. *Implicit
   means broken* applies to the spec sentence itself.
3. **A hole cannot be graded on a spec the coder cannot green.** Both failed attempts also
   came back RED, which voids every verdict under the baseline-green rule. The bare 7B is
   recorded at 2/3 on `shortener`; the successful run used the three-member fleet.

The predictions were written before each run, which is the only reason attempt 1 reads as
"I shipped a weaker edit than I designed" rather than "the model ignores specs".

## The baseline-green rule (why a red baseline is not a CAUGHT)

A CAUGHT/SURVIVED verdict is only meaningful if the **unmutated** artifact is green. If the
baseline is already red — a stray build/vet/test failure — the mutant goes red for the
wrong reason and reports a **fake CAUGHT** that measures nothing. This bit the by-hand runs
four times (walkv, usersapi, taskapipro). Both mutation tools now check the pristine tree
first and report **BASELINE-RED (verdict void)** instead of a fake CAUGHT.
An instrument that cannot tell "red because defended" from "red because already broken" is
decoration.

## Deterministic mutations, not probabilistic ones

Dropping a `sort.Slice` catches only ~probabilistically: the un-sorted result depends on
Go's map-iteration randomness, so the verdict flakes. Every sort/order invariant here uses a
**REVERSE** mutation (`<` → `>`) instead: an ascending-order assertion catches a descending
sort *every* run. A mutation that cannot be relied on to fail is not a test.

## The four shapes of a hole

Holes cluster in HTTP/service specs and in secondary/edge invariants; pure-library specs
(the invariant *is* the test subject) are well-defended. The undefended ones fell into four
shapes:

1. **No test at all** for a required invariant — e.g. `List sorted by ID` (taskflow,
   usersapi, taskapipro): both list methods call `sort.Slice`, no test checks order.
2. **The guard's happy path is tested, its edge never runs** — e.g. bitset `Clear(200)`:
   the test does `Test(200)` but never `Clear(200)`, so dropping Clear's range guard ships
   green yet `Clear(200)` on a small set panics.
3. **The live effect is only observed via another path** — e.g. walkv `Delete`: the effect
   is checked only after Close+reopen (replay rebuilds the map), so a same-session
   Delete-then-Get is undefended.
4. **The invariant has no output signature** — e.g. workerpool bounded concurrency
   (`w<workers` → `w<len(items)`): output is bit-identical whether it runs 2 goroutines or
   one-per-item. Coverage and output tests are structurally blind; only a concurrency probe
   (peak-goroutine count) sees it.

A fifth non-hole shape is a **flaky guard**: a named order test that exists but with only two
elements catches a broken sort ~20% of the time. "A named test exists" ≠ "the invariant is
usually defended."

## The discriminator

Not "is there a green test" but **"does one test DETERMINISTICALLY run the whole promise."**
The same `List sorted by ID` invariant is undefended in taskflow/usersapi and robustly
defended in taskapi — the difference is the *test*, not the code.

## Why the fix loop makes this mandatory rather than nice to have

A property of the Go toolchain, measured across 32 archived failures
(`logs/FINDING-escalation-granularity.txt`): **a compiler error names an implementation
file; a failing assertion names the TEST.** In 18 of the 19 archives whose tests fail at
runtime, implementation files are being repaired and not one of them is blamed.

So on every runtime failure the fix loop is handed the test file as the accused, and asked
to repair it. That is deliberate — sometimes the test really is wrong, and `_fix_prompt`
says so out loud ("if the implementation already matches the spec's stated rules, correct
the test's expected value"). But it means the loop is *routinely one round away* from
changing `want 3` into `want -1` and going green against a bug.

The existing guard stops only the crude version: a candidate `_test.go` that asserts
nothing at all is rejected (`has_assertions`). A test edited into agreement with the
implementation still asserts something, still compiles, still passes — and every signal
the builder has says success. Coverage cannot see it. The gate cannot see it. The spec
sees it only if a human reads both.

**Mutation is the only instrument that can.** A suite weakened to match a bug reports
SURVIVED the moment the bug is planted deliberately, which is exactly the shape teeth
measures. That is the argument for keeping this campaign running as the fix loop gets
stronger, not for retiring it: a better fix loop is a loop that finds green faster, and
one of the routes to green is through a weakened test.

## Current coverage

`_teeth_suite.py` covers **every valid generated spec — 30 registered mutations across 23
specs, verdict 29 CAUGHT / 0 SURVIVED / 1 n·a** (ledger carries two file-variant entries, one
of which does not apply to the current artifact layout). It exits non-zero on any UNDEFENDED
or VOID entry (CI-ready).
Two broken-baseline specs (tasks-api-min, tasks-api-noshadownudge) are deliberately excluded:
they send RED baselines, which make every verdict void.

That headline was **re-verified end to end on 2026-07-25**, after the judgement was
extracted out of `_run` into `verdict_for(art, rel, mutate)` so `--self-test` could reach
it. Extracting a function that decides 30 recorded verdicts is exactly the kind of change
that passes review and quietly moves a number, so the whole suite was re-run rather than
argued about: **29 CAUGHT / 0 SURVIVED / 1 n·a, unchanged**. A refactor of an instrument is
not verified by the instrument's own tests — those were written against the new shape — but
by the numbers it produced before still coming out the same.

The blow-by-blow of each hole found and closed (with the fix-arc predictions and audits) is
in `logs/FINDING-taskflow-teeth.txt`.

## Adding an entry

Break a promise the spec actually makes: name a real invariant the impl-spec REQUIRES, write
a mutation that removes it (validated by hand — it changes real behaviour, it is unique in its
file, and the correct code passes while the mutant fails *iff* a test defends it), and register
it in `MUTATIONS`. A mutation that does not apply is reported as `NOAPPLY`, never silently
counted as CAUGHT.
