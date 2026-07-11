// Command wraparg inserts the adapter the model forgot.
//
//	NewRouter(NewMemStore())
//	// cannot use NewMemStore() (value of interface type Store) as *API value
//	// in argument to NewRouter
//
// The project declares exactly one function turning a Store into an *API —
// NewAPI — so the composition the model meant is unambiguous, and the repair is
// to wrap the argument in it:
//
//	NewRouter(NewAPI(NewMemStore()))
//
// The caller (the Python gate) proves the adapter is unique before invoking
// this; all this program does is perform the rewrite at the exact position the
// compiler named, which needs an AST rather than text surgery — the argument can
// be any expression, and the same call can appear more than once in a file.
//
// Usage: wraparg <line> <col> <adapter> < src.go > rewritten.go
// Exit 3 means nothing was rewritten.
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
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "usage: wraparg <line> <col> <adapter>")
		os.Exit(2)
	}
	line, err1 := strconv.Atoi(os.Args[1])
	col, err2 := strconv.Atoi(os.Args[2])
	adapter := os.Args[3]
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

	// Collect the sites first and rewrite AFTER the walk. Mutating during
	// ast.Inspect would hand the walker the node we just built, whose argument
	// still starts at the position we are looking for — so it would wrap it
	// again, and again, forever.
	type site struct {
		call *ast.CallExpr
		i    int
	}
	var sites []site
	ast.Inspect(file, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		for i, arg := range call.Args {
			p := fset.Position(arg.Pos())
			if p.Line != line || p.Column != col {
				continue
			}
			// Never wrap something that is already the adapter call.
			if inner, isCall := arg.(*ast.CallExpr); isCall {
				if id, isID := inner.Fun.(*ast.Ident); isID && id.Name == adapter {
					continue
				}
			}
			sites = append(sites, site{call, i})
		}
		return true
	})
	if len(sites) == 0 {
		fmt.Fprintln(os.Stderr, "NOOP")
		os.Exit(3)
	}
	for _, s := range sites {
		s.call.Args[s.i] = &ast.CallExpr{
			Fun:  ast.NewIdent(adapter),
			Args: []ast.Expr{s.call.Args[s.i]},
		}
	}
	if err := format.Node(os.Stdout, fset, file); err != nil {
		fmt.Fprintln(os.Stderr, "format:", err)
		os.Exit(2)
	}
}
