// Command hoistcall repairs a two-value call used where one value is expected.
//
//	func (s *projectService) List(ctx context.Context, limit, offset int) ([]models.Project, error) {
//	        return paginate(s.store.ListProjects(ctx), limit, offset), nil
//	}
//	// multiple-value s.store.ListProjects(ctx) (value of type ([]models.Project,
//	// error)) in single-value context
//
// ListProjects returns (items, error), and the model dropped the error on the
// floor by using the call as an argument. Go has no way to express that, so it
// does not compile. The repair is the one a Go programmer writes without
// thinking: hoist the call into its own statement, handle the error, use the
// value.
//
//	items, err := s.store.ListProjects(ctx)
//	if err != nil {
//	        return nil, err
//	}
//	return paginate(items, limit, offset), nil
//
// This is the class that stayed un-gated for months, because unlike every other
// gate it must INTRODUCE statements rather than rewrite one. What makes it
// tractable is that the enclosing function's signature decides everything: the
// error goes to the last result, and each earlier result gets its zero value. If
// any of that cannot be settled — the function does not end in error, a result's
// zero value is not inferable — it refuses.
//
// Usage: hoistcall <line> <col> < src.go   (exit 3 = nothing done)
package main

import (
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"io"
	"os"
	"strconv"
)

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: hoistcall <line> <col>")
		os.Exit(2)
	}
	line, err1 := strconv.Atoi(os.Args[1])
	col, err2 := strconv.Atoi(os.Args[2])
	if err1 != nil || err2 != nil {
		fmt.Fprintln(os.Stderr, "bad position")
		os.Exit(2)
	}
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

	// The call the compiler named, the statement it sits in, the block that
	// statement belongs to, and the function whose signature decides the repair.
	var call *ast.CallExpr
	var stmt ast.Stmt
	var block *ast.BlockStmt
	var fn *ast.FuncDecl

	for _, d := range file.Decls {
		f, ok := d.(*ast.FuncDecl)
		if !ok || f.Body == nil {
			continue
		}
		ast.Inspect(f.Body, func(n ast.Node) bool {
			b, ok := n.(*ast.BlockStmt)
			if !ok {
				return true
			}
			for _, s := range b.List {
				ast.Inspect(s, func(m ast.Node) bool {
					c, ok := m.(*ast.CallExpr)
					if !ok {
						return true
					}
					p := fset.Position(c.Pos())
					if p.Line == line && p.Column == col {
						call, stmt, block, fn = c, s, b, f
						return false
					}
					return true
				})
			}
			return true
		})
	}
	if call == nil || fn.Type.Results == nil {
		fmt.Fprintln(os.Stderr, "NOOP")
		os.Exit(3)
	}

	// The function must end in `error`, or there is nowhere for the error to go.
	results := flatten(fn.Type.Results)
	if len(results) == 0 || !isError(results[len(results)-1]) {
		fmt.Fprintln(os.Stderr, "NOOP: enclosing function does not return an error")
		os.Exit(3)
	}
	structs := structsIn(file)
	zeros := make([]ast.Expr, 0, len(results)-1)
	for _, r := range results[:len(results)-1] {
		z := zeroValue(r, structs)
		if z == nil {
			fmt.Fprintln(os.Stderr, "NOOP: cannot infer a zero value to return")
			os.Exit(3)
		}
		zeros = append(zeros, z)
	}

	taken := identsIn(fn)
	val, errName := freshName(taken, "items", "vals", "list", "res"), freshName(taken, "err", "e", "rerr")
	if val == "" || errName == "" {
		fmt.Fprintln(os.Stderr, "NOOP: no free name")
		os.Exit(3)
	}

	hoist := &ast.AssignStmt{
		Lhs: []ast.Expr{ast.NewIdent(val), ast.NewIdent(errName)},
		Tok: token.DEFINE,
		Rhs: []ast.Expr{&ast.CallExpr{Fun: call.Fun, Args: call.Args, Ellipsis: call.Ellipsis}},
	}
	guard := &ast.IfStmt{
		Cond: &ast.BinaryExpr{
			X: ast.NewIdent(errName), Op: token.NEQ, Y: ast.NewIdent("nil"),
		},
		Body: &ast.BlockStmt{List: []ast.Stmt{
			&ast.ReturnStmt{Results: append(append([]ast.Expr{}, zeros...), ast.NewIdent(errName))},
		}},
	}

	// The call becomes the hoisted value, wherever in the statement it sat.
	replaceExpr(stmt, call, ast.NewIdent(val))

	var out []ast.Stmt
	for _, s := range block.List {
		if s == stmt {
			out = append(out, hoist, guard)
		}
		out = append(out, s)
	}
	block.List = out

	if err := format.Node(os.Stdout, fset, file); err != nil {
		fmt.Fprintln(os.Stderr, "format:", err)
		os.Exit(2)
	}
}

func flatten(fl *ast.FieldList) []ast.Expr {
	var out []ast.Expr
	for _, f := range fl.List {
		n := len(f.Names)
		if n == 0 {
			n = 1
		}
		for i := 0; i < n; i++ {
			out = append(out, f.Type)
		}
	}
	return out
}

func isError(e ast.Expr) bool {
	id, ok := e.(*ast.Ident)
	return ok && id.Name == "error"
}

// structsIn collects the names this file declares as structs, so a zero value of
// T{} can be PROVEN correct rather than assumed.
func structsIn(f *ast.File) map[string]bool {
	out := map[string]bool{}
	for _, d := range f.Decls {
		g, ok := d.(*ast.GenDecl)
		if !ok || g.Tok != token.TYPE {
			continue
		}
		for _, s := range g.Specs {
			ts, ok := s.(*ast.TypeSpec)
			if !ok {
				continue
			}
			if _, isStruct := ts.Type.(*ast.StructType); isStruct {
				out[ts.Name.Name] = true
			}
		}
	}
	return out
}

// zeroValue is the value to return for a result when the error path is taken. It
// returns nil for anything it cannot SETTLE — not merely anything it cannot guess
// — and the caller then refuses. `models.Project{}` looks obvious and is not: if
// models.Project were an interface, that literal would not compile, and this file
// cannot see the other package to know. A named type is only given a composite
// literal when THIS file declares it a struct.
func zeroValue(e ast.Expr, structs map[string]bool) ast.Expr {
	switch t := e.(type) {
	case *ast.StarExpr, *ast.ArrayType, *ast.MapType, *ast.ChanType,
		*ast.FuncType, *ast.InterfaceType:
		return ast.NewIdent("nil")
	case *ast.Ident:
		switch t.Name {
		case "string":
			return &ast.BasicLit{Kind: token.STRING, Value: `""`}
		case "bool":
			return ast.NewIdent("false")
		case "error", "any":
			return ast.NewIdent("nil")
		case "int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16",
			"uint32", "uint64", "byte", "rune", "float32", "float64":
			return &ast.BasicLit{Kind: token.INT, Value: "0"}
		}
		if structs[t.Name] {
			return &ast.CompositeLit{Type: t}
		}
		return nil // a named type we cannot prove is a struct
	}
	return nil // including a qualified type from a package we cannot see
}

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

func freshName(taken map[string]bool, options ...string) string {
	for _, o := range options {
		if !taken[o] {
			taken[o] = true
			return o
		}
	}
	return ""
}

// replaceExpr swaps one expression for another wherever it appears in a
// statement's operands.
func replaceExpr(root ast.Node, old, new ast.Expr) {
	ast.Inspect(root, func(n ast.Node) bool {
		switch t := n.(type) {
		case *ast.CallExpr:
			for i, a := range t.Args {
				if a == old {
					t.Args[i] = new
				}
			}
		case *ast.ReturnStmt:
			for i, r := range t.Results {
				if r == old {
					t.Results[i] = new
				}
			}
		case *ast.AssignStmt:
			for i, r := range t.Rhs {
				if r == old {
					t.Rhs[i] = new
				}
			}
		}
		return true
	})
}
