#!/usr/bin/env python3
"""Which config fields are parsed, validated, tested — and then read by NOBODY?

WHY THIS EXISTS. taskapipro's config declares DefaultPageSize 20 and MaxPageSize 100. Load()
parses both from the environment, Validate() rejects a MaxPageSize below the default and a
DefaultPageSize of zero, and config_test.go asserts all of it across four tests. One of those
boundaries is a closure I graded CAUGHT this week. Then the handler that paginates writes:

    if limit <= 0  { limit = 100 }      // not cfg.DefaultPageSize — and not 20 either
    if limit > 100 { limit = 100 }      // not cfg.MaxPageSize

Nothing outside the config package reads either field. Setting DEFAULT_PAGE_SIZE=5 changes
nothing an HTTP client can observe. The documented default of 20 has never been served.

MUTATION TESTING IS STRUCTURALLY BLIND TO THIS. Every probe asks "if I break this line, does
a test notice?" — and here a test DOES notice, because config_test.go pins the value. The site
grades DEFENDED while the feature is entirely absent from behaviour. That is the inverse of
every hole this repo has hunted so far: not an untested invariant, but a TESTED one with no
consumer. A test can only defend a promise something keeps; it cannot notice that nothing
ever asked.

So this asks a question no mutation can: is there a READ of this field anywhere outside the
package that declares it and the tests that pin it?

WHAT A HIT IS AND IS NOT. A hit is a CANDIDATE. A field can be legitimately unread by this
tree and still be right — a struct mirroring an external format, a field a future endpoint
will take. What it cannot be is "covered": whatever the tests say about it, no request has
ever been served differently because of it.

Usage:  _dead_config.py <tree> [<tree>...]     |     _dead_config.py --self-test
"""
from __future__ import annotations

import pathlib
import re
import sys

# A field line inside a struct block: `Name Type` or `Name  Type` with an optional tag.
FIELD_RE = re.compile(r"^\s*([A-Z]\w*)\s+([\w\.\*\[\]]+)(?:\s+`[^`]*`)?\s*(?://.*)?$")
STRUCT_OPEN_RE = re.compile(r"^\s*type\s+(\w*Config\w*)\s+struct\s*\{")


def config_fields(src: str) -> dict[str, list[str]]:
    """Field names declared in each `type ...Config... struct` block."""
    out: dict[str, list[str]] = {}
    name = None
    for line in src.splitlines():
        if name is None:
            m = STRUCT_OPEN_RE.match(line)
            if m:
                name, out[m.group(1)] = m.group(1), []
            continue
        if line.strip().startswith("}"):
            name = None
            continue
        m = FIELD_RE.match(line)
        if m:
            out[name].append(m.group(1))
    return out


def go_files(tree: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in tree.rglob("*.go") if p.is_file())


def audit_tree(tree: pathlib.Path) -> list[dict]:
    """One row per config field, with WHERE it is read broken out by kind of file."""
    decls: list[tuple[pathlib.Path, str, str]] = []  # (file, struct, field)
    for p in go_files(tree):
        if p.name.endswith("_test.go"):
            continue
        for struct, fields in config_fields(p.read_text(errors="replace")).items():
            decls.extend((p, struct, f) for f in fields)
    if not decls:
        return []

    rows = []
    for path, struct, field in decls:
        # A READ is `.Field` — a selector. Matching the bare name would count the declaration
        # itself, the env-var string, and any local variable that happens to share the name.
        pat = re.compile(r"\.\s*" + re.escape(field) + r"\b")
        owner_dir = path.parent
        elsewhere, in_tests, in_owner = [], [], []
        for p in go_files(tree):
            hits = len(pat.findall(p.read_text(errors="replace")))
            if not hits:
                continue
            rel = str(p.relative_to(tree))
            if p.name.endswith("_test.go"):
                in_tests.append(rel)
            elif p.parent == owner_dir:
                in_owner.append(rel)
            else:
                elsewhere.append(rel)
        rows.append({
            "file": str(path.relative_to(tree)), "struct": struct, "field": field,
            "elsewhere": elsewhere, "tests": in_tests, "owner": in_owner,
            "dead": not elsewhere,
        })
    return rows


def self_test() -> int:
    import tempfile
    fails = []
    fields = config_fields(
        "type Config struct {\n\tAddr string\n\tMaxPageSize int\n\tD time.Duration `env:\"D\"`\n}\n")
    if fields != {"Config": ["Addr", "MaxPageSize", "D"]}:
        fails.append(f"struct fields misparsed: {fields}")
    if config_fields("type Server struct {\n\tAddr string\n}\n"):
        fails.append("only a *Config* struct is a config struct; Server is not one")

    with tempfile.TemporaryDirectory() as d:
        tree = pathlib.Path(d)
        (tree / "internal/config").mkdir(parents=True)
        (tree / "cmd").mkdir(parents=True)
        (tree / "internal/config/config.go").write_text(
            "package config\n"
            "type Config struct {\n\tAddr string\n\tMaxPageSize int\n}\n"
            "func Validate(c Config) bool { return c.MaxPageSize > 0 && c.Addr != \"\" }\n")
        (tree / "internal/config/config_test.go").write_text(
            "package config\n"
            "func TestX(t *testing.T) { _ = c.MaxPageSize; _ = c.Addr }\n")
        # main READS Addr and never mentions MaxPageSize: one live field, one dead one.
        (tree / "cmd/main.go").write_text("package main\nfunc main() { _ = cfg.Addr }\n")
        rows = {r["field"]: r for r in audit_tree(tree)}
        if set(rows) != {"Addr", "MaxPageSize"}:
            fails.append(f"both fields must be audited: {sorted(rows)}")
        # REJECT-NOTHING PIN. A field a consumer actually reads must NOT be reported, or the
        # tool says "everything is dead" and means nothing.
        if rows.get("Addr", {}).get("dead"):
            fails.append("Addr is read by cmd/main.go — reporting it makes the tool useless")
        if not rows.get("MaxPageSize", {}).get("dead"):
            fails.append("MaxPageSize is read only by its own package and its test — that is "
                         "the whole shape this tool exists to see")
        # And the reason must be visible: validated and tested is exactly why it looks fine.
        if rows.get("MaxPageSize", {}).get("tests") != ["internal/config/config_test.go"]:
            fails.append(f"a dead field's TESTS must still be reported — being tested is what "
                         f"makes it invisible: {rows.get('MaxPageSize', {}).get('tests')}")
        if audit_tree(tree / "cmd"):
            fails.append("a tree with no config struct must report nothing, not crash")

    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — flags the field nobody reads, silent on the field main() uses"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    trees = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not trees:
        # `-prevN` is a SUPERSEDED draw, preserved rather than deleted by _ab_run/_ab_run_v5
        # (29 Jul) so a re-run stops destroying the evidence behind a graded RESULT. This is
        # the second tool that globs generated/ broadly and therefore has to know about them;
        # _cross_draw was the first. Auditing a superseded draw is not WRONG — it is a real
        # tree — but it silently doubles the corpus with artifacts nobody is reasoning about.
        trees = sorted(p for p in pathlib.Path("generated").glob("*")
                       if p.is_dir() and not p.name.startswith("_")
                       and not re.search(r"-prev\d+$", p.name))
    audited = flagged = 0
    for tree in trees:
        rows = audit_tree(tree)
        if not rows:
            continue
        dead = [r for r in rows if r["dead"]]
        audited += len(rows)
        flagged += len(dead)
        if not dead:
            continue
        print(f"\n{tree}")
        for r in dead:
            tested = " TESTED" if r["tests"] else ""
            print(f"  {r['struct']}.{r['field']:<20} declared {r['file']}"
                  f"  read outside its package: NEVER{tested}")
            if r["tests"]:
                print(f"     pinned by: {', '.join(r['tests'])}")
    print(f"\n{flagged} field(s) read by nothing outside their own package, "
          f"out of {audited} config field(s) in {len(trees)} tree(s)")
    if not audited:
        print("no config struct found — this audit had nothing to check, which is not a pass")
