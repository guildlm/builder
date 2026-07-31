#!/usr/bin/env python3
"""What would `_fill_empty_planned_files` MOVE, over the whole corpus, under each extractor?

    python _repair_take_audit.py                 # both extractors, corpus summary
    python _repair_take_audit.py --cases         # ... plus one line per empty-file instance
    python _repair_take_audit.py --entries       # what each spec entry is claimed to declare
    python _repair_take_audit.py --self-test     # fixed strings, no corpus needed

WHY THIS EXISTS AS A FILE RATHER THAN A SHELL PIPELINE.
The 03:30 baseline (64 of 125 trees ship an empty planned .go file; 54 movable, 10 take-EMPTY) and
the 04:05/05:00 simulations of the widened extractor were all run ad hoc and thrown away. The
numbers went into logs/ and the code that produced them did not, so "re-run the 03:30 check with
the widened regex" — which the pre-registration names as FIX 2's entire acceptance test — could not
actually be re-run. It is re-implemented here once, and committed, so the before/after comparison
is a rerun rather than a reconstruction.

THE TWO EXTRACTORS, stated in one place because the edit under test moves builder.py from one to
the other and this file has to keep measuring BOTH afterwards:

    NARROW   `Name struct|interface`                      — builder.py's _REQUIRED_TYPE_RE
    WIDE     ... OR `Name` backticked and capitalised
             ... OR `var Name` / `const Name`, capitalised

    Both add "main" when the purpose names a main function, as builder.py does.

⚠️ THE SCRIPT DOES NOT TRUST ITS OWN COPY. On every run it evaluates builder.py's live
`_required_decls` over every purpose in the three specs and reports which of NARROW/WIDE it agrees
with — so a drift between this instrument and the code it measures is printed, not assumed away.
That check is the reason the extractor is duplicated here instead of imported: after FIX 2 lands,
importing would make the "before" column unmeasurable.

WHAT A CASE IS. For each tree: every planned .go file that declares NOTHING (builder's
`empty_go_files`), classified by whether the repair would find something to move —
a same-directory, non-test sibling holding symbols this file's purpose promises and the sibling's
own purpose does NOT. That is builder.py:1596-1616 replicated; the classification is
order-independent (it asks whether ANY donor qualifies), so reading the tree off disk rather than
from the builder's `written` dict cannot change it.

⚠️ IT READS THE SHIPPED TREE by default, not .pre-fix.json — the repair pass runs at _finish_green
over post-fix-loop content, so the shipped tree is the input it would actually see. `--as-drawn`
switches; on this corpus the two agree exactly, which is itself a small result (see read_tree).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))
import builder  # noqa: E402

SPECS = pathlib.Path("specs")
GENERATED = pathlib.Path("generated")

NARROW_RE = re.compile(r"(?<![.\w])([A-Z]\w*)\s+(?i:struct|interface)\b")
BACKTICK_RE = re.compile(r"`([A-Z]\w*)`")
VARCONST_RE = re.compile(r"\b(?:var|const)\s+([A-Z]\w*)")


def required(purpose: str, wide: bool) -> set[str]:
    """The extractor, both versions. Mirrors builder._required_decls including its
    main-function rule; `wide` adds the two patterns FIX 2 proposes.

    ⚠️ The wide patterns keep only MixedCaps names. Go's exported identifiers are MixedCaps;
    an all-caps token in a purpose is prose emphasis or an env var name. Measured, and the
    reason this guard exists: taskapi's config.go says "Treat an EMPTY env var EXACTLY like
    an UNSET one", and `var EXACTLY` reads the ENGLISH noun "var" as a Go declaration. It was
    the only false claim in the whole spec directory, and the 05:00 blast-radius check missed
    it because that check covered three specs and this extractor feeds all of them.
    Residual, unfixed by the guard: a purpose writing "env var Timeout" would still be
    misread. No spec does today."""
    purpose = purpose or ""
    names = set(NARROW_RE.findall(purpose))
    if wide:
        wide_names = set(BACKTICK_RE.findall(purpose)) | set(VARCONST_RE.findall(purpose))
        names |= {n for n in wide_names if any(c.islower() for c in n)}
    if re.search(r"\bfunc main\b|\bmain\(\)", purpose):
        names.add("main")
    return names


def spec_for(tree: str) -> pathlib.Path | None:
    """The spec a tree was drawn from: the longest spec stem that is the tree name or a
    dash-delimited prefix of it. `ledger-order1` -> ledger-order1.yaml; `ledger-pairA-p6`
    -> ledger.yaml, since no ledger-pairA spec exists (the pair arms are the base spec and
    its -origorder twin, selected by the driver, and the base is what the A arm used)."""
    best = None
    for path in SPECS.glob("*.yaml"):
        stem = path.stem
        if tree == stem or tree.startswith(stem + "-"):
            if best is None or len(stem) > len(best.stem):
                best = path
    if best is not None:
        return best
    # `workapi25`, `taskapipro7b` — the campaign's older trees suffix the spec name without a
    # separator. They are the same spec and the 125-tree baseline counted them, so a bare
    # prefix match is the fallback, never the first choice: `ledger-order1` must reach
    # ledger-order1.yaml and not ledger.yaml.
    for path in SPECS.glob("*.yaml"):
        if tree.startswith(path.stem):
            if best is None or len(path.stem) > len(best.stem):
                best = path
    if best is not None:
        return best
    # `_fail-workapi-0712014714`, `_iso-taskapipro-2`, `_ledger-ARM-B-oldspec-ruleon` — arm and
    # failure trees carry the spec name in the middle. Last resort, longest match wins, and it
    # uses TODAY's spec text for a tree drawn from an older one, which is a real limitation of
    # every corpus-wide number here: the purposes are the current ones.
    for path in SPECS.glob("*.yaml"):
        if path.stem in tree:
            if best is None or len(path.stem) > len(best.stem):
                best = path
    return best


def read_tree(root: pathlib.Path, as_drawn: bool) -> dict[str, str]:
    """The shipped tree, or — with `as_drawn` — what the model wrote before the fix loop and
    any repair touched it. The mode is a flag and is printed with every number rather than
    being a silent default, because mixing the two populations cost a retraction on 30 July.

    ⚠️ MEASURED, and worth knowing before reaching for the flag: on this corpus the two modes
    give the SAME classification. 20 trees carry a .pre-fix.json, all 20 differ in content from
    the shipped tree, and not one of those differences changes which planned files are empty.
    Emptiness is decided when the file is drawn; the fix loop neither creates nor clears it."""
    if as_drawn:
        pre = root / ".pre-fix.json"
        if pre.exists():
            try:
                data = json.loads(pre.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict):
                files = data.get("files", data)
                if isinstance(files, dict) and all(
                    isinstance(v, str) for v in files.values()
                ):
                    return {k: v for k, v in files.items() if k.endswith(".go")}
    written = {}
    for path in sorted(root.rglob("*.go")):
        try:
            written[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
        except OSError:
            pass
    return written


def classify(spec, written: dict[str, str], wide: bool) -> list[dict]:
    """builder.py:1596-1616, minus the actual move. One record per empty planned file."""
    by_path = {f.path: f.purpose or "" for f in spec.files}
    cases = []
    for path in builder.empty_go_files(written):
        wanted = required(by_path.get(path, ""), wide)
        take, donor = set(), None
        for p, code in written.items():
            if (
                p == path or not p.endswith(".go") or p.endswith("_test.go")
                or builder._dir_of(p) != builder._dir_of(path)
            ):
                continue
            candidate = wanted - required(by_path.get(p, ""), wide)
            if candidate and candidate <= (
                builder.top_level_decls(code) | builder.method_decls(code)
            ):
                take, donor = candidate, p
                break
        cases.append(
            {"path": path, "wanted": wanted, "take": take, "donor": donor,
             "planned": path in by_path}
        )
    return cases


def audit(wide: bool, args) -> tuple[list[tuple[str, dict]], int]:
    cases, trees = [], 0
    for root in sorted(GENERATED.iterdir()):
        if not root.is_dir():
            continue
        spec_path = spec_for(root.name)
        if spec_path is None:
            continue
        if args.specs and not any(s in root.name for s in args.specs):
            continue
        trees += 1
        spec = builder.Spec.from_yaml(spec_path)
        for case in classify(spec, read_tree(root, args.as_drawn), wide):
            cases.append((root.name, case))
    return cases, trees


def drift_check() -> str:
    """Which extractor does the SHIPPED builder.py implement, right now?"""
    purposes = []
    for path in sorted(SPECS.glob("*.yaml")):
        try:
            purposes += [f.purpose or "" for f in builder.Spec.from_yaml(path).files]
        except Exception:
            pass
    live = [builder._required_decls(p) for p in purposes]
    narrow = [required(p, False) for p in purposes]
    wide = [required(p, True) for p in purposes]
    if live == narrow == wide:
        return "NARROW==WIDE on this corpus (specs name nothing the widening adds)"
    if live == narrow:
        return "builder.py = NARROW (FIX 2 not applied)"
    if live == wide:
        return "builder.py = WIDE (FIX 2 applied)"
    return "⚠️ builder.py matches NEITHER — this instrument has drifted from the code"


def report(args) -> int:
    print(drift_check())
    print("content:", "AS-DRAWN (.pre-fix.json)" if args.as_drawn else "SHIPPED (disk)",
          "· specs:", ",".join(args.specs) if args.specs else "ALL")
    print()
    summaries = {}
    for wide in (False, True):
        cases, trees = audit(wide, args)
        movable = [c for _, c in cases if c["take"]]
        empty = [c for _, c in cases if not c["take"]]
        summaries[wide] = (cases, trees, len(movable), len(empty))
    for wide in (False, True):
        cases, trees, movable, empty = summaries[wide]
        label = "WIDE  " if wide else "NARROW"
        affected = len({t for t, _ in cases})
        print(f"{label}  {trees} trees · {affected} with an empty planned .go file · "
              f"{len(cases)} empty files · take non-empty {movable} · take EMPTY {empty}")
    if args.cases:
        print()
        narrow_cases = {(t, c["path"]): c for t, c in summaries[False][0]}
        for tree, case in summaries[True][0]:
            n = narrow_cases.get((tree, case["path"]))
            before = "MOVABLE" if n and n["take"] else "EMPTY  "
            after = "MOVABLE" if case["take"] else "EMPTY  "
            flag = " <-- CHANGED" if before != after else ""
            print(f"  {before} -> {after}  {tree:28s} {case['path']:34s} "
                  f"wants={sorted(case['wanted'])} take={sorted(case['take'])}{flag}")
    if args.entries:
        print()
        for path in sorted(SPECS.glob("*.yaml")):
            spec = builder.Spec.from_yaml(path)
            for f in spec.files:
                n, w = required(f.purpose, False), required(f.purpose, True)
                if n != w:
                    print(f"  {path.stem:22s} {f.path:34s} {sorted(n)} -> {sorted(w)} "
                          f"(+{sorted(w - n)})")
    return 0


def self_test() -> int:
    """Fixed strings. The extractor's job is to claim what an entry promises and NOTHING it
    merely mentions — the failure that would corrupt generation, not just the repair."""
    checks = [
        # (purpose, narrow, wide)
        ("Defines Event struct with Type and TaskID", {"Event"}, {"Event"}),
        ("Implements the `MemStore` type", set(), {"MemStore"}),
        ("Exported sentinels var ErrNotFound and var ErrExists",
         set(), {"ErrNotFound", "ErrExists"}),
        ("Declares const MaxRetries", set(), {"MaxRetries"}),
        # the guard: prose emphasis and env-var names are not identifiers
        ("Treat an EMPTY env var EXACTLY like an UNSET one", set(), set()),
        ("Reads `ADDR` and `READ_TIMEOUT` from the environment", set(), set()),
        # a qualified mention is another package's type in BOTH versions
        ("Wraps an http.Handler interface", set(), set()),
        # lowercase is unexported and not part of the file's contract
        ("Uses `internalCache` and var localOnly", set(), set()),
        ("Entrypoint with func main", {"main"}, {"main"}),
        # the widening must not start claiming a type merely REFERENCED in backticks by a
        # file that implements it — that distinction is the donor rule's job, not the
        # extractor's, and this row documents that the extractor deliberately over-collects
        # (and note the narrow regex misses it even though the word "interface" is RIGHT
        # THERE — a backtick between the name and the keyword breaks the adjacency it needs)
        ("Implements the `Store` interface declared in store.go", set(), {"Store"}),
    ]
    failures = 0
    for purpose, want_narrow, want_wide in checks:
        for wide, want in ((False, want_narrow), (True, want_wide)):
            got = required(purpose, wide)
            if got != want:
                failures += 1
                print(f"FAIL wide={wide} {purpose!r}: got {sorted(got)}, want {sorted(want)}")
    # the donor rule: a sibling promised the same symbol keeps it
    spec = builder.Spec.from_dict({
        "name": "t", "description": "t",
        "files": [
            {"path": "internal/store/store.go", "purpose": "Declares Store interface"},
            {"path": "internal/store/memory.go",
             "purpose": "Implements the `MemStore` type satisfying Store interface"},
        ],
    })
    written = {
        "internal/store/store.go":
            "package store\ntype Store interface{}\ntype MemStore struct{}\n"
            "func (m *MemStore) Get() {}\n",
        "internal/store/memory.go": "package store\n",
    }
    narrow_cases = classify(spec, written, False)
    wide_cases = classify(spec, written, True)
    if len(narrow_cases) != 1 or narrow_cases[0]["take"]:
        failures += 1
        print(f"FAIL narrow donor rule: {narrow_cases}")
    if len(wide_cases) != 1 or wide_cases[0]["take"] != {"MemStore"}:
        failures += 1
        print(f"FAIL wide donor rule: {wide_cases}")
    # and a symbol the donor was ALSO promised is refused under both
    spec2 = builder.Spec.from_dict({
        "name": "t", "description": "t",
        "files": [
            {"path": "a/x.go", "purpose": "Declares Store interface"},
            {"path": "a/y.go", "purpose": "Declares Store interface"},
        ],
    })
    written2 = {"a/x.go": "package a\n", "a/y.go": "package a\ntype Store interface{}\n"}
    if classify(spec2, written2, True)[0]["take"]:
        failures += 1
        print("FAIL: took a symbol the donor's own purpose promised")
    print("self-test:", "OK" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", action="store_true")
    ap.add_argument("--entries", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--as-drawn", action="store_true",
                    help="read .pre-fix.json (what the model wrote) instead of the shipped tree")
    ap.add_argument("--specs", default="",
                    help="comma-separated substrings of the tree name, e.g. ledger,workapi,taskapipro"
                         " — substring, so it catches _fail-workapi-... and _iso-taskapipro-... too")
    args = ap.parse_args()
    args.specs = [x for x in args.specs.split(",") if x]
    if args.self_test:
        return self_test()
    return report(args)


if __name__ == "__main__":
    raise SystemExit(main())
