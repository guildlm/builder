// Command deadassert removes the happy-path guard that makes an error-expecting
// assertion unreachable.
//
//	_, err := svc.List(ctx, 1, 0, "")
//	if err != nil {
//	        t.Fatalf("List: %v", err)      // fires on the very error we asked for
//	}
//	if !errors.Is(err, errBoom) {          // DEAD CODE — never runs
//	        t.Fatalf("want errBoom, got %v", err)
//	}
//
// In a test that EXPECTS an error, the error is the RESULT, not an obstacle. The
// model writes the assertion the spec asked for and then layers the file's
// dominant rhythm — `if err != nil { t.Fatalf }` — ON TOP of it rather than
// INSTEAD of it. The guard fires first, the test fails with the error it was
// written to observe, and the errors.Is check below it can never execute.
//
// It is nudge-resistant. The spec forbids the guard in so many words ("the error
// is the RESULT, not an obstacle; do NOT open with the happy-path boilerplate"),
// the fixer is now shown that same purpose AND the test-authoring defaults, and
// the model re-adds the guard anyway — at GENERATION it obeyed, and a FIX round
// put it back. A nudge is not a gate.
//
// THE REPAIR, and why it is safe by construction: the guard is deleted ONLY when
// the SAME `err` identifier is, later in the SAME block, the subject of an
// `errors.Is(err, ...)` / `errors.As(err, ...)` check. That combination is
// unconditionally contradictory — a test cannot both demand that err be nil and
// assert what it wraps — so removing the first is the only reading that leaves a
// test with any meaning. Nothing else is touched: a guard with no errors.Is below
// it is an ordinary happy-path check and is left exactly where it is.
//
// Source arrives on stdin, rewritten source leaves on stdout; exit 3 = nothing to
// do (including a parse error, which is a different failure and not ours).
package main

import (
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"io"
	"os"
)

// isErrNilFatalGuard matches `if <err> != nil { t.Fatalf/Errorf/Fatal/Error(...) }`
// with a body that does nothing else. It returns the error identifier's name.
func isErrNilFatalGuard(st ast.Stmt) (string, bool) {
	ifs, ok := st.(*ast.IfStmt)
	if !ok || ifs.Init != nil || ifs.Else != nil {
		return "", false
	}
	bin, ok := ifs.Cond.(*ast.BinaryExpr)
	if !ok || bin.Op != token.NEQ {
		return "", false
	}
	id, ok := bin.X.(*ast.Ident)
	if !ok {
		return "", false
	}
	if nilIdent, ok := bin.Y.(*ast.Ident); !ok || nilIdent.Name != "nil" {
		return "", false
	}
	// the body must be exactly one t.Fatalf/Errorf/Fatal/Error call — anything
	// richer is a guard doing real work, and not ours to delete.
	if len(ifs.Body.List) != 1 {
		return "", false
	}
	es, ok := ifs.Body.List[0].(*ast.ExprStmt)
	if !ok {
		return "", false
	}
	call, ok := es.X.(*ast.CallExpr)
	if !ok {
		return "", false
	}
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok {
		return "", false
	}
	switch sel.Sel.Name {
	case "Fatalf", "Errorf", "Fatal", "Error":
	default:
		return "", false
	}
	return id.Name, true
}

// checksErrorsIs reports whether stmt is an `if !errors.Is(<name>, ...)` /
// `errors.As(<name>, ...)` assertion on the same identifier. Its presence is what
// proves the guard above it is contradictory.
func checksErrorsIs(st ast.Stmt, name string) bool {
	found := false
	ast.Inspect(st, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok || len(call.Args) < 1 {
			return true
		}
		sel, ok := call.Fun.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		pkg, ok := sel.X.(*ast.Ident)
		if !ok || pkg.Name != "errors" {
			return true
		}
		if sel.Sel.Name != "Is" && sel.Sel.Name != "As" {
			return true
		}
		if arg, ok := call.Args[0].(*ast.Ident); ok && arg.Name == name {
			found = true
		}
		return true
	})
	return found
}

// fixBlock deletes each guard that is contradicted by a later errors.Is on the
// same identifier, within the same statement list.
func fixBlock(stmts []ast.Stmt) ([]ast.Stmt, bool) {
	drop := map[int]bool{}
	for i, st := range stmts {
		name, ok := isErrNilFatalGuard(st)
		if !ok {
			continue
		}
		for _, later := range stmts[i+1:] {
			// a reassignment of the same err makes the later check a DIFFERENT
			// error; stop looking.
			if as, ok := later.(*ast.AssignStmt); ok {
				reassigned := false
				for _, lhs := range as.Lhs {
					if id, ok := lhs.(*ast.Ident); ok && id.Name == name {
						reassigned = true
					}
				}
				if reassigned {
					break
				}
			}
			if checksErrorsIs(later, name) {
				drop[i] = true
				break
			}
		}
	}
	if len(drop) == 0 {
		return stmts, false
	}
	out := make([]ast.Stmt, 0, len(stmts))
	for i, st := range stmts {
		if !drop[i] {
			out = append(out, st)
		}
	}
	return out, true
}

func main() {
	src, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "src.go", src, parser.ParseComments)
	if err != nil {
		fmt.Fprintln(os.Stderr, "parse:", err)
		os.Exit(3)
	}

	changed := false
	for _, d := range file.Decls {
		fn, ok := d.(*ast.FuncDecl)
		if !ok || fn.Body == nil {
			continue
		}
		if body, did := fixBlock(fn.Body.List); did {
			fn.Body.List = body
			changed = true
		}
	}
	if !changed {
		os.Exit(3)
	}
	if err := format.Node(os.Stdout, fset, file); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}
