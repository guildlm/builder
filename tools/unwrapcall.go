// Command unwrapcall passes a function BY VALUE where the model called it.
//
//	Chain(mux, Logging(logger), Recover(logger))
//	// cannot use Logging(logger) (value of interface type http.Handler)
//	// as Middleware value in argument to Chain
//
// Logging is declared `func Logging(next http.Handler) http.Handler`, which IS
// the Middleware type — so it should be handed to Chain as a value, not invoked:
//
//	Chain(mux, Logging, Recover)
//
// The caller (the Python gate) proves the function's signature is exactly the
// wanted named func type before invoking this. All this program does is replace
// the call expression at the position the compiler named with the bare function
// it was calling.
//
// Usage: unwrapcall <line> <col> <fn> < src.go > rewritten.go
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
		fmt.Fprintln(os.Stderr, "usage: unwrapcall <line> <col> <fn>")
		os.Exit(2)
	}
	line, err1 := strconv.Atoi(os.Args[1])
	col, err2 := strconv.Atoi(os.Args[2])
	fn := os.Args[3]
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

	// Collect the sites first; rewriting during the walk would hand the walker a
	// node we just replaced.
	type site struct {
		call *ast.CallExpr
		i    int
	}
	var sites []site
	ast.Inspect(file, func(n ast.Node) bool {
		outer, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		for i, arg := range outer.Args {
			p := fset.Position(arg.Pos())
			if p.Line != line || p.Column != col {
				continue
			}
			inner, isCall := arg.(*ast.CallExpr)
			if !isCall {
				continue // already a value; nothing to unwrap
			}
			id, isID := inner.Fun.(*ast.Ident)
			if !isID || id.Name != fn {
				continue // not the function the gate proved
			}
			sites = append(sites, site{outer, i})
		}
		return true
	})
	if len(sites) == 0 {
		fmt.Fprintln(os.Stderr, "NOOP")
		os.Exit(3)
	}
	for _, s := range sites {
		inner := s.call.Args[s.i].(*ast.CallExpr)
		s.call.Args[s.i] = inner.Fun
	}
	if err := format.Node(os.Stdout, fset, file); err != nil {
		fmt.Fprintln(os.Stderr, "format:", err)
		os.Exit(2)
	}
}
