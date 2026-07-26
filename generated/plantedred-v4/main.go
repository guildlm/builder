// PLANTED, ON PURPOSE. This artifact does not compile, and that is its entire job.
//
// _teeth_suite's central rule is that a mutation applied to an artifact whose baseline is
// ALREADY red produces a VOID verdict, not a CAUGHT. Until 2026-07-26 the only inputs
// exercising that rule were tasks-api-min-v4 and tasks-api-noshadownudge-v4 — two real
// archived failures — and FINDING-the-broken-archives-are-the-only-control.txt is about
// exactly them. I deleted both with a careless glob (FINDING-i-deleted-the-corpus.txt),
// and with them went every BASELINE-RED row in the corpus.
//
// tests/test_corpus_keeps_a_red_baseline.py says in its own docstring that regenerating
// the artifacts is fine "as long as something still fails to build", so this plants the
// property directly instead of hoping a future run fails in the right way. It is a
// deliberate stand-in for evidence that was lost, not a discovery — a real failing
// artifact carries a real defect shape and this carries none, so if a genuine red archive
// appears again, prefer it and delete this.
package main

import "fmt"

func main() {
	// A type error the compiler cannot miss and no gate will repair: assigning a string
	// to an int. Deliberately NOT one of the shapes the deterministic gates fix, so the
	// artifact stays red under _gate_audit's chain as well as under a plain build.
	var count int = "not a number"
	fmt.Println(count)
}
