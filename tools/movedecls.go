// Command movedecls moves declarations out of one file of a package and into
// another file of the SAME package.
//
// The plan splits a package in two: store.go declares the interface, memory.go
// implements it. The model writes both in store.go, so memory.go has nothing left
// to declare and ships as a bare `package store`. Go does not care which file in
// a package holds what, so the build is green and the project quietly does not
// match the plan it was built from. Every multi-package artifact in the suite has
// one of these dead files, and a prompt telling the model to stay in its lane did
// not stop it.
//
// Moving a declaration between files of the same package cannot change what the
// program means — the package is the compilation unit, not the file. That is what
// makes this repair safe rather than clever.
//
// Each half is given exactly the imports its own declarations use. That cannot be
// left to goimports: it runs on stdin here, with no module context, so it resolves
// `sync` but not the project's own `models` package. And because an unused import
// is a compile error in Go, the source half has to SHED what it no longer uses
// just as surely as the moved half has to gain what it now does.
//
// Reads the source file on stdin; writes JSON {"source": …, "moved": …} on stdout,
// where "source" is the file with the declarations removed and "moved" is a
// compilable file (package clause + the declarations) for the destination.
// Exit 3 means nothing moved.
//
// Usage: movedecls <package> <Name,Name,…> < source.go
package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"io"
	"os"
	"sort"
	"strings"
)

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: movedecls <package> <Name,Name,...>")
		os.Exit(2)
	}
	pkg := os.Args[1]
	wanted := map[string]bool{}
	for _, n := range strings.Split(os.Args[2], ",") {
		if n = strings.TrimSpace(n); n != "" {
			wanted[n] = true
		}
	}
	if len(wanted) == 0 {
		os.Exit(3)
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

	// A type moves with everything attached to it: its methods, and the
	// constructor that returns it. Splitting those across files would compile,
	// but it would be a worse layout than the one we are repairing.
	var keep, move []ast.Decl
	for _, d := range file.Decls {
		if declMoves(d, wanted) {
			move = append(move, d)
		} else {
			keep = append(keep, d)
		}
	}
	if len(move) == 0 || len(keep) == 0 {
		// Nothing to move, or moving would empty the SOURCE file — which just
		// relocates the problem instead of fixing it.
		fmt.Fprintln(os.Stderr, "NOOP")
		os.Exit(3)
	}

	// Each half gets exactly the imports its own declarations use. This cannot be
	// left to goimports: it runs on stdin here, with no module context, so it can
	// resolve `sync` but not the project's own `models` package — and an import
	// that is present but unused is a compile error, so the source half has to
	// SHED what it no longer uses just as surely as the moved half has to gain it.
	imports := importsOf(file)
	source := file
	source.Decls = keep
	source.Imports = nil
	setImports(source, imports, usedPackages(keep))

	moved := &ast.File{Name: ast.NewIdent(pkg), Decls: move}
	setImports(moved, imports, usedPackages(move))

	out := map[string]string{}
	for key, f := range map[string]*ast.File{"source": source, "moved": moved} {
		var b strings.Builder
		if err := format.Node(&b, fset, f); err != nil {
			fmt.Fprintln(os.Stderr, "format:", err)
			os.Exit(2)
		}
		out[key] = b.String()
	}
	if err := json.NewEncoder(os.Stdout).Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

// importsOf maps the name a file refers to each import by (its alias, or the last
// path segment) to the import spec itself.
func importsOf(f *ast.File) map[string]*ast.ImportSpec {
	out := map[string]*ast.ImportSpec{}
	for _, im := range f.Imports {
		name := strings.Trim(im.Path.Value, `"`)
		if i := strings.LastIndex(name, "/"); i >= 0 {
			name = name[i+1:]
		}
		if im.Name != nil {
			name = im.Name.Name
		}
		out[name] = im
	}
	return out
}

// usedPackages collects every `pkg.Something` qualifier the declarations mention.
func usedPackages(decls []ast.Decl) map[string]bool {
	used := map[string]bool{}
	for _, d := range decls {
		ast.Inspect(d, func(n ast.Node) bool {
			if sel, ok := n.(*ast.SelectorExpr); ok {
				if id, ok := sel.X.(*ast.Ident); ok {
					used[id.Name] = true
				}
			}
			return true
		})
	}
	return used
}

// setImports rebuilds a file's import block from the ones its declarations use.
func setImports(f *ast.File, all map[string]*ast.ImportSpec, used map[string]bool) {
	var specs []ast.Spec
	for name, im := range all {
		if used[name] {
			specs = append(specs, &ast.ImportSpec{
				Name: im.Name,
				Path: &ast.BasicLit{Kind: token.STRING, Value: im.Path.Value},
			})
		}
	}
	// Drop any import declaration the file already carries, then add ours.
	var decls []ast.Decl
	for _, d := range f.Decls {
		if g, ok := d.(*ast.GenDecl); ok && g.Tok == token.IMPORT {
			continue
		}
		decls = append(decls, d)
	}
	if len(specs) > 0 {
		sort.Slice(specs, func(i, j int) bool {
			return specs[i].(*ast.ImportSpec).Path.Value <
				specs[j].(*ast.ImportSpec).Path.Value
		})
		decls = append([]ast.Decl{&ast.GenDecl{
			Tok:    token.IMPORT,
			Lparen: token.Pos(1), // force the parenthesised form
			Specs:  specs,
			Rparen: token.Pos(2),
		}}, decls...)
	}
	f.Decls = decls
	f.Imports = nil
}

// declMoves reports whether a declaration belongs to one of the wanted types:
// the type itself, a method on it, or a function returning it.
func declMoves(d ast.Decl, wanted map[string]bool) bool {
	switch t := d.(type) {
	case *ast.GenDecl:
		if t.Tok != token.TYPE {
			return false // sentinels, consts and vars stay where they were declared
		}
		for _, s := range t.Specs {
			if ts, ok := s.(*ast.TypeSpec); ok && wanted[ts.Name.Name] {
				return true
			}
		}
	case *ast.FuncDecl:
		if t.Recv != nil {
			for _, f := range t.Recv.List {
				if wanted[baseTypeName(f.Type)] {
					return true // a method on a moved type
				}
			}
			return false
		}
		if t.Type.Results != nil {
			for _, r := range t.Type.Results.List {
				if wanted[baseTypeName(r.Type)] {
					return true // its constructor
				}
			}
		}
	}
	return false
}

// baseTypeName unwraps *T and T to T.
func baseTypeName(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.StarExpr:
		return baseTypeName(t.X)
	case *ast.Ident:
		return t.Name
	}
	return ""
}
