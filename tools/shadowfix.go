// Command shadowfix repairs the single most stubborn test-authoring mistake the
// 7B model makes: shadowing the *testing.T parameter with a domain loop
// variable.
//
//	for _, t := range tasks {          // t now shadows *testing.T
//	        if err := s.Create(t); err != nil {
//	                t.Fatalf("Create: %v", err)   // meant the tester; got a Task
//	        }
//	}
//
// The compiler names it exactly: "t.Fatalf undefined (type Task has no field or
// method Fatalf)". The repair is a scope-aware rename of the SHADOW (never the
// tester): the declaration and every non-tester use of t inside the shadowed
// scope become a fresh name, while t.<testing method> is left alone so it
// resolves to the un-shadowed *testing.T again.
//
// This needs real scope resolution, not a regex: a single-letter identifier
// appears in selectors, nested closures, struct fields and inner shadows. The
// rewrite therefore runs on go/ast, and BAILS (leaving the file untouched) on
// every construct it cannot resolve with certainty. Source arrives on stdin and
// the rewritten source leaves on stdout; exit code 3 means "nothing to do".
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

// Methods that only ever belong to *testing.T in this position. A use of
// t.<one of these> inside the shadowed scope is the author reaching for the
// tester, which is precisely the intent the shadow broke.
var testingMethods = map[string]bool{
	"Fatal": true, "Fatalf": true, "Error": true, "Errorf": true,
	"Log": true, "Logf": true, "Fail": true, "FailNow": true, "Failed": true,
	"Skip": true, "Skipf": true, "SkipNow": true, "Skipped": true,
	"Helper": true, "Cleanup": true, "Parallel": true, "Run": true,
	"TempDir": true, "Setenv": true, "Chdir": true, "Name": true,
	"Deadline": true,
}

// Candidate replacement names, in preference order.
var freshNames = []string{"tk", "tv", "item", "elem", "entry", "val"}

func main() {
	src, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	fset := token.NewFileSet()
	// The file type-checks badly (that is why we are here) but must PARSE; a
	// syntax error is a different failure and not ours to touch.
	file, err := parser.ParseFile(fset, "src.go", src, parser.ParseComments)
	if err != nil {
		fmt.Fprintln(os.Stderr, "parse:", err)
		os.Exit(3)
	}

	changed := false
	for _, decl := range file.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || fn.Body == nil {
			continue
		}
		if !hasTesterParam(fn) {
			continue
		}
		if fixFunc(fn) {
			changed = true
		}
	}
	if !changed {
		fmt.Fprintln(os.Stderr, "NOOP")
		os.Exit(3)
	}
	if err := format.Node(os.Stdout, fset, file); err != nil {
		fmt.Fprintln(os.Stderr, "format:", err)
		os.Exit(2)
	}
}

// hasTesterParam reports whether fn takes a parameter literally named "t" of
// type *testing.T — the only situation in which shadowing "t" is a bug worth
// repairing.
func hasTesterParam(fn *ast.FuncDecl) bool {
	if fn.Type.Params == nil {
		return false
	}
	for _, f := range fn.Type.Params.List {
		if !isTesterType(f.Type) {
			continue
		}
		for _, n := range f.Names {
			if n.Name == "t" {
				return true
			}
		}
	}
	return false
}

// isTesterType reports whether expr is the type *testing.T.
func isTesterType(expr ast.Expr) bool {
	star, ok := expr.(*ast.StarExpr)
	if !ok {
		return false
	}
	sel, ok := star.X.(*ast.SelectorExpr)
	if !ok || sel.Sel.Name != "T" {
		return false
	}
	pkg, ok := sel.X.(*ast.Ident)
	return ok && pkg.Name == "testing"
}

// shadow is one declaration of "t" inside a tester function, together with the
// scope over which that declaration is visible.
type shadow struct {
	decls []*ast.Ident    // the declaring identifier(s) named "t"
	scope ast.Node        // block the shadow is visible in
	from  token.Pos       // uses before this position are NOT the shadow (:= case)
	stmt  *ast.AssignStmt // set for `t := ...`; its scope needs an enclosing block
}

// fixFunc rewrites every repairable shadow in fn and reports whether it changed
// anything.
func fixFunc(fn *ast.FuncDecl) bool {
	shadows := findShadows(fn.Body)
	if len(shadows) == 0 {
		return false
	}
	// Nested or overlapping shadows mean a use of "t" can belong to more than
	// one binding; resolving that needs more than we can prove here. Bail.
	for i := range shadows {
		for j := range shadows {
			if i != j && overlaps(shadows[i], shadows[j]) {
				return false
			}
		}
	}
	taken := identsIn(fn)
	changed := false
	for _, sh := range shadows {
		if fixShadow(sh, taken) {
			changed = true
		}
	}
	return changed
}

// findShadows collects the declarations of "t" nested anywhere inside body.
func findShadows(body *ast.BlockStmt) []shadow {
	var out []shadow
	ast.Inspect(body, func(n ast.Node) bool {
		switch s := n.(type) {
		case *ast.RangeStmt:
			if s.Tok != token.DEFINE {
				return true
			}
			var decls []*ast.Ident
			for _, e := range []ast.Expr{s.Key, s.Value} {
				if id, ok := e.(*ast.Ident); ok && id.Name == "t" {
					decls = append(decls, id)
				}
			}
			if len(decls) > 0 {
				out = append(out, shadow{decls: decls, scope: s.Body, from: s.Body.Pos()})
			}
		case *ast.AssignStmt:
			if s.Tok != token.DEFINE {
				return true
			}
			var decls []*ast.Ident
			for _, e := range s.Lhs {
				if id, ok := e.(*ast.Ident); ok && id.Name == "t" {
					decls = append(decls, id)
				}
			}
			if len(decls) > 0 {
				// Visible from this statement to the end of its block; the
				// enclosing block is found by the caller's walk below.
				out = append(out, shadow{decls: decls, scope: nil, from: s.End(), stmt: s})
			}
		case *ast.FuncLit:
			if s.Type.Params == nil {
				return true
			}
			var decls []*ast.Ident
			for _, f := range s.Type.Params.List {
				// `t.Run("x", func(t *testing.T) {...})` re-binds t to a NEW
				// tester. That is the idiomatic subtest, not the bug: it is
				// correct Go and renaming it would silently report failures
				// against the parent test. Only a non-tester parameter shadows.
				if isTesterType(f.Type) {
					continue
				}
				for _, id := range f.Names {
					if id.Name == "t" {
						decls = append(decls, id)
					}
				}
			}
			if len(decls) > 0 {
				out = append(out, shadow{decls: decls, scope: s.Body, from: s.Body.Pos()})
			}
		}
		return true
	})
	// A `t := ...` short declaration is visible from itself to the end of the
	// block it sits in, so resolve that block. A declaration in the INIT clause
	// of an if/for/switch is scoped to that statement instead, which the
	// innermost enclosing block over-approximates — renaming on that wider span
	// would rewrite the real tester after the statement ends. Those declarations
	// are not directly in a block's statement list, which is exactly how we
	// detect them, and we refuse the whole file rather than guess.
	for i := range out {
		if out[i].scope != nil {
			continue
		}
		blk := innermostBlock(body, out[i].decls[0].Pos())
		if blk == nil || !directlyIn(blk, out[i].stmt) {
			return nil // unresolvable scope; refuse to touch the file
		}
		out[i].scope = blk
	}
	return out
}

// directlyIn reports whether stmt is a top-level statement of blk, rather than
// nested in some statement's init/cond clause.
func directlyIn(blk *ast.BlockStmt, stmt ast.Stmt) bool {
	for _, s := range blk.List {
		if s == stmt {
			return true
		}
	}
	return false
}

// innermostBlock returns the tightest *ast.BlockStmt in root containing pos.
func innermostBlock(root ast.Node, pos token.Pos) *ast.BlockStmt {
	var best *ast.BlockStmt
	ast.Inspect(root, func(n ast.Node) bool {
		blk, ok := n.(*ast.BlockStmt)
		if !ok {
			return true
		}
		if blk.Pos() <= pos && pos < blk.End() {
			if best == nil || blk.Pos() > best.Pos() {
				best = blk
			}
		}
		return true
	})
	return best
}

func overlaps(a, b shadow) bool {
	as, ae := a.scope.Pos(), a.scope.End()
	bs, be := b.scope.Pos(), b.scope.End()
	return as < be && bs < ae
}

// identsIn collects every identifier name appearing in fn, so a replacement name
// can be chosen that collides with nothing.
func identsIn(fn *ast.FuncDecl) map[string]bool {
	taken := map[string]bool{}
	ast.Inspect(fn, func(n ast.Node) bool {
		if id, ok := n.(*ast.Ident); ok {
			taken[id.Name] = true
		}
		return true
	})
	return taken
}

// fixShadow renames one shadow's declaration and its non-tester uses. It reports
// whether it made a change, and does nothing at all unless the scope actually
// contains a tester call (t.Fatalf and friends) — a shadow the author never
// used as a tester compiles fine and is none of our business.
func fixShadow(sh shadow, taken map[string]bool) bool {
	uses, testerUses, ok := classifyUses(sh)
	if !ok || testerUses == 0 {
		return false
	}
	name := freshName(taken)
	if name == "" {
		return false
	}
	taken[name] = true
	for _, id := range sh.decls {
		id.Name = name
	}
	for _, id := range uses {
		id.Name = name
	}
	return true
}

// classifyUses splits the identifiers named "t" inside the shadow's scope into
// uses of the shadowing variable (to be renamed) and tester calls (to be left
// alone so they bind to *testing.T again). ok is false when the scope contains a
// construct whose meaning cannot be decided without type information.
func classifyUses(sh shadow) (uses []*ast.Ident, testerUses int, ok bool) {
	ok = true
	// Parent tracking: an identifier's role depends on the node above it.
	stack := []ast.Node{}
	ast.Inspect(sh.scope, func(n ast.Node) bool {
		if n == nil {
			stack = stack[:len(stack)-1]
			return true
		}
		defer func() { stack = append(stack, n) }()
		parent := ast.Node(nil)
		if len(stack) > 0 {
			parent = stack[len(stack)-1]
		}

		switch s := n.(type) {
		case *ast.LabeledStmt:
			// `t:` as a label is a different namespace we will not reason about.
			if s.Label != nil && s.Label.Name == "t" {
				ok = false
			}
			return true
		case *ast.KeyValueExpr:
			// A key named "t" is a struct field in one literal and a real
			// variable use in another (a map key); telling them apart needs
			// types. Refuse.
			if id, isID := s.Key.(*ast.Ident); isID && id.Name == "t" {
				ok = false
			}
			return true
		case *ast.RangeStmt:
			if s.Tok == token.DEFINE && declaresT(s.Key, s.Value) && s.Body != sh.scope {
				ok = false // an inner re-shadow; uses below it are ambiguous
			}
			return true
		case *ast.AssignStmt:
			if s.Tok == token.DEFINE && declaresT(s.Lhs...) && !within(sh.decls, s.Lhs) {
				ok = false
			}
			return true
		case *ast.FuncLit:
			if s.Type.Params != nil {
				for _, f := range s.Type.Params.List {
					for _, id := range f.Names {
						if id.Name == "t" && s.Body != sh.scope {
							ok = false
						}
					}
				}
			}
			return true
		}

		id, isID := n.(*ast.Ident)
		if !isID || id.Name != "t" || id.Pos() < sh.from {
			return true
		}
		if isDecl(sh.decls, id) {
			return true
		}
		if sel, isSel := parent.(*ast.SelectorExpr); isSel {
			if sel.Sel == id {
				return true // the field name in x.t, not our variable
			}
			if sel.X == id && testingMethods[sel.Sel.Name] {
				testerUses++
				return true // leave it: this is the tester the shadow stole
			}
		}
		uses = append(uses, id)
		return true
	})
	return uses, testerUses, ok
}

func declaresT(exprs ...ast.Expr) bool {
	for _, e := range exprs {
		if id, ok := e.(*ast.Ident); ok && id.Name == "t" {
			return true
		}
	}
	return false
}

// within reports whether the shadow's own declaring identifiers are the ones in
// lhs — so a shadow does not mistake itself for an inner re-shadow.
func within(decls []*ast.Ident, lhs []ast.Expr) bool {
	for _, e := range lhs {
		for _, d := range decls {
			if e == ast.Expr(d) {
				return true
			}
		}
	}
	return false
}

func isDecl(decls []*ast.Ident, id *ast.Ident) bool {
	for _, d := range decls {
		if d == id {
			return true
		}
	}
	return false
}

func freshName(taken map[string]bool) string {
	for _, n := range freshNames {
		if !taken[n] {
			return n
		}
	}
	return ""
}
