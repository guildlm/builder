// Command freshreq repairs the drained-request bug: an *http.Request built ONCE
// and handed to ServeHTTP more than once.
//
//	req := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(body))
//	h.ServeHTTP(w, req)          // 201 — and DRAINS req.Body
//	w = httptest.NewRecorder()
//	h.ServeHTTP(w, req)          // body is now EMPTY -> json.Decode EOF -> 400
//
// A request Body is an io.Reader. The first ServeHTTP consumes it, so the second
// call sends nothing, the handler answers 400, and a "POST twice -> 409" case
// reports `want 409, got 400` against a handler that maps ErrExists to 409
// perfectly correctly. The test is wrong; the product is right.
//
// This is the one place the model reaches for reuse, because the duplicate case
// is the ONE test in which both requests are a POST of the SAME body to the SAME
// URL — and that identity is exactly what makes reusing `req` look correct. Six
// escalating versions of the prompt default failed to stop it: the rule names the
// variable, forbids the reuse, explains the drain, predicts the exact status code,
// quotes the wrong code verbatim as "exactly the bug", and anchors the example to
// the duplicate test by name. The model writes it anyway. A nudge is not a gate.
//
// THE REPAIR, and why it is safe by construction:
//   - It fires ONLY on a variable assigned from httptest.NewRequest with a body
//     argument that is NOT the literal nil. A bodyless request (GET, DELETE) can
//     legally be replayed — there is nothing to drain — and is left alone.
//   - It fires ONLY when that same variable reaches ServeHTTP twice or more with
//     NO reassignment in between. Any reassignment means the author already
//     rebuilt it, and the file is correct.
//   - The repair rebuilds the request in place: every ServeHTTP call after the
//     first gets a FRESH httptest.NewRequest with the same method, URL and a new
//     reader over the same body expression. Semantics are preserved exactly —
//     the second request is the same request, which is what the test meant.
//   - Anything it cannot resolve with certainty (a request built by a helper, a
//     body expression that is itself consumed, a loop) it leaves untouched.
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

// reqInfo is a request variable we know how to rebuild.
//
// `mutations` is the reason this cannot simply inline a fresh NewRequest at the
// second call site. A request is usually built and then MUTATED — most often
// `req.Header.Set("Authorization", "Bearer secret")`. Inlining a bare fresh
// request drops those mutations, and the repaired test then fails 401 instead of
// 400: the drain is fixed and the auth is silently gone. The rebuild has to
// replay every mutation the author applied, in order.
type reqInfo struct {
	name      string
	call      *ast.CallExpr // the httptest.NewRequest(...) that built it
	mutations []ast.Stmt    // req.Header.Set(...) and friends, in source order
	serve     []int         // indices into the statement list, of each ServeHTTP
}

func isNewRequest(e ast.Expr) (*ast.CallExpr, bool) {
	call, ok := e.(*ast.CallExpr)
	if !ok {
		return nil, false
	}
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok || sel.Sel.Name != "NewRequest" {
		return nil, false
	}
	pkg, ok := sel.X.(*ast.Ident)
	if !ok || pkg.Name != "httptest" {
		return nil, false
	}
	return call, len(call.Args) == 3
}

// hasBody reports whether the third argument is anything other than the literal
// nil. Only a request WITH a body can be drained.
func hasBody(call *ast.CallExpr) bool {
	id, ok := call.Args[2].(*ast.Ident)
	return !(ok && id.Name == "nil")
}

// serveArg returns the identifier passed as the request to a ServeHTTP call.
func serveArg(call *ast.CallExpr) (*ast.Ident, bool) {
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok || sel.Sel.Name != "ServeHTTP" || len(call.Args) != 2 {
		return nil, false
	}
	id, ok := call.Args[1].(*ast.Ident)
	return id, ok
}

// isMutationOf reports whether stmt is a call on `name` (e.g. req.Header.Set(...)).
func isMutationOf(st ast.Stmt, name string) bool {
	es, ok := st.(*ast.ExprStmt)
	if !ok {
		return false
	}
	call, ok := es.X.(*ast.CallExpr)
	if !ok {
		return false
	}
	// walk down the selector chain to its root identifier: req.Header.Set -> req
	e := call.Fun
	for {
		sel, ok := e.(*ast.SelectorExpr)
		if !ok {
			break
		}
		e = sel.X
	}
	id, ok := e.(*ast.Ident)
	return ok && id.Name == name
}

// fixBlock rewrites ONE flat statement list in source order. Order is the whole
// point: a reassignment between two ServeHTTP calls means the author already
// rebuilt the request, and that code is correct.
//
// It returns the (possibly rewritten) statement list. Nested blocks are handled
// on their own, independently: a request built in an outer scope and served
// inside an if/for is left alone — that is the "cannot resolve with certainty"
// case, and the model keeps it.
func fixBlock(stmts []ast.Stmt) ([]ast.Stmt, bool) {
	live := map[string]*reqInfo{}
	changed := false

	// Pass 1 — read the block in order and record, for each request variable, the
	// call that built it, the mutations applied to it, and every ServeHTTP it
	// reaches. A reassignment resets all three.
	for i, st := range stmts {
		if as, ok := st.(*ast.AssignStmt); ok && len(as.Lhs) == 1 && len(as.Rhs) == 1 {
			if id, ok := as.Lhs[0].(*ast.Ident); ok {
				if call, isReq := isNewRequest(as.Rhs[0]); isReq && hasBody(call) {
					live[id.Name] = &reqInfo{name: id.Name, call: call}
					continue
				}
				delete(live, id.Name) // rebuilt or overwritten by something else
				continue
			}
		}
		if es, ok := st.(*ast.ExprStmt); ok {
			if call, ok := es.X.(*ast.CallExpr); ok {
				if id, ok := serveArg(call); ok {
					if info, ours := live[id.Name]; ours {
						info.serve = append(info.serve, i)
						if len(info.serve) > 1 {
							changed = true
						}
						continue
					}
				}
			}
		}
		for name, info := range live {
			if len(info.serve) == 0 && isMutationOf(st, name) {
				info.mutations = append(info.mutations, st)
			}
		}
	}
	if !changed {
		return stmts, false
	}

	// Pass 2 — before every ServeHTTP after the FIRST, splice in a rebuild of the
	// request: the same method, the same URL, a NEW reader over the same body
	// expression, followed by a replay of every mutation the author applied. The
	// second request is then the identical request, freshly readable — which is
	// exactly what the test meant by sending it twice.
	rebuildAt := map[int]*reqInfo{}
	for _, info := range live {
		for _, idx := range info.serve[min(1, len(info.serve)):] {
			rebuildAt[idx] = info
		}
	}
	out := make([]ast.Stmt, 0, len(stmts)+2*len(rebuildAt))
	for i, st := range stmts {
		if info, ok := rebuildAt[i]; ok {
			out = append(out, &ast.AssignStmt{
				Lhs: []ast.Expr{ast.NewIdent(info.name)},
				Tok: token.ASSIGN,
				Rhs: []ast.Expr{&ast.CallExpr{
					Fun: info.call.Fun,
					Args: []ast.Expr{
						info.call.Args[0], info.call.Args[1], info.call.Args[2],
					},
				}},
			})
			out = append(out, info.mutations...)
		}
		out = append(out, st)
	}
	return out, true
}

func fixFunc(fn *ast.FuncDecl) bool {
	body, changed := fixBlock(fn.Body.List)
	fn.Body.List = body
	return changed
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
		if fixFunc(fn) {
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
