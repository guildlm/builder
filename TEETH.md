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

`_named_test_audit.py` matches on names, so a test that is *present but vacuous* (right
name, missing assertion) passes the audit while the hole stays open. Names are checkable
by grep; teeth are not. That is why the mutation tools exist alongside it.

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

## Current coverage

`_teeth_suite.py` covers **every valid generated spec — 30 registered mutations across 23
specs, verdict 29 CAUGHT / 0 SURVIVED / 1 n·a** (ledger carries two file-variant entries, one
of which does not apply to the current artifact layout). It exits non-zero on any UNDEFENDED
or VOID entry (CI-ready).
Two broken-baseline specs (tasks-api-min, tasks-api-noshadownudge) are deliberately excluded:
they send RED baselines, which make every verdict void.

The blow-by-blow of each hole found and closed (with the fix-arc predictions and audits) is
in `logs/FINDING-taskflow-teeth.txt`.

## Adding an entry

Break a promise the spec actually makes: name a real invariant the impl-spec REQUIRES, write
a mutation that removes it (validated by hand — it changes real behaviour, it is unique in its
file, and the correct code passes while the mutant fails *iff* a test defends it), and register
it in `MUTATIONS`. A mutation that does not apply is reported as `NOAPPLY`, never silently
counted as CAUGHT.
