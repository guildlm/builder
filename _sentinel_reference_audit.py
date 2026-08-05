#!/usr/bin/env python3
"""Does every CROSS-PACKAGE sentinel reference in a draw name a sentinel that EXISTS?

    ./_sentinel_reference_audit.py <tree> [<tree> ...]
    ./_sentinel_reference_audit.py --self-test

THIS IS THE PRE-REGISTERED ENDPOINT of logs/PREREG-expose-grouped-sentinels-in-the-cross-
package-api-block.txt, and it is being written BEFORE the draw it will score finishes. An
endpoint measured by a tool authored after the data exists is not an endpoint, it is a summary;
this campaign has already had one prediction invalidated for being written after its own file
was on disk (P2, 31 July).

    PRIMARY: in .pre-fix.json, every `models.ErrX` referenced by another package must be a name
    the referenced package actually declares.

⚠️ AS-DRAWN ONLY, AND IT REFUSES RATHER THAN FALLING BACK. A tree on disk is POST-REPAIR, and
the fix loop repairs about three fifths of exactly this defect (12 of 20 measured). Scoring a
repaired tree would report the LOOP's work as the model's and turn a red endpoint green. That
mistake is the single error behind every retraction on 29 July, it recurred in _parity_grade.py
on 31 July, and it was found in a published propagation note on 5 August. So: no snapshot, no
verdict.

⚠️ WHAT COUNTS AS A REFERENCE. `pkg.ErrX` where `pkg` is a package this project declares. A
reference to an imported stdlib or third-party symbol is not the model's to get right and is
skipped — the qualifier must match a package present in the tree.

⚠️ WHY 'Err' AND NOT EVERY QUALIFIED NAME. The defect being tracked is sentinel naming: one file
derives a name from the spec's prose while another abbreviates it. Types (models.Account) travel
through the same channel and were already correct in every tree inspected, so folding them in
would dilute the endpoint with cases nobody claims are broken. --all lifts the restriction for
anyone who wants the wider number, and says so in the header.
"""

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from builder import pkg_name_of, top_level_decls  # noqa: E402

# `pkg.Name`. The negative lookbehind for a dot or word char stops `a.b.ErrX` and `x.pkg.ErrX`
# from being read as a package reference, and the lookbehind for `"` keeps import strings out.
_QUAL_RE = re.compile(r"(?<![\w.\"])([a-z][a-z0-9_]*)\.([A-Z]\w*)")


def _files(tree: pathlib.Path) -> dict[str, str]:
    snap = tree / ".pre-fix.json"
    if not snap.is_file():
        raise FileNotFoundError(f"{tree}: no .pre-fix.json — refusing to score a post-repair tree")
    d = json.loads(snap.read_text())
    files = d.get("files", d)
    if not isinstance(files, dict):
        raise ValueError(f"{tree}: .pre-fix.json has no file map")
    return files


def audit(tree: pathlib.Path, err_only: bool = True) -> dict:
    files = _files(tree)
    # package name -> the exported names it declares, unioned over the package's files.
    declared: dict[str, set[str]] = {}
    pkg_of_file: dict[str, str] = {}
    for path, code in files.items():
        if not path.endswith(".go") or not code:
            continue
        pkg = pkg_name_of(code)
        if not pkg:
            continue
        pkg_of_file[path] = pkg
        declared.setdefault(pkg, set()).update(top_level_decls(code))

    refs: list[tuple[str, str, str]] = []   # (file, pkg, name)
    for path, code in files.items():
        if not path.endswith(".go") or not code:
            continue
        own = pkg_of_file.get(path)
        for pkg, name in _QUAL_RE.findall(code):
            if pkg == own or pkg not in declared:
                continue           # same package, or not one of ours (stdlib/3rd party)
            if err_only and not name.startswith("Err"):
                continue
            refs.append((path, pkg, name))

    missing = [(f, p, n) for (f, p, n) in refs if n not in declared[p]]

    # ⚠️ 'BROKEN' IS TWO DEFECTS AND REPORTING ONE NUMBER HIDES THAT. Found 5 August by reading
    # the cases behind a count instead of quoting it: of 23 broken trees, 18 fail because the
    # DECLARER wrote a different name (ErrInsufficient for ErrInsufficientFunds) and 5 fail
    # because the CONSUMER named the wrong package — internal/api reaches for
    # `service.ErrNotFound` while `service` declares no sentinel at all and `models` declares
    # exactly that name. Those are different defects with different fixes, and averaging them
    # produces a percentage that no single change can move.
    #
    # The partition is mechanical, not a judgement call:
    #   DECLARER-GAP     the referenced package declares SOME Err*, just not this one
    #   WRONG-QUALIFIER  the referenced package declares NO Err*, and some OTHER package in
    #                    the tree declares this exact name
    #   UNRESOLVED       neither — the name exists nowhere, so nothing says who should own it
    kinds: dict[tuple[str, str], str] = {}
    for _f, p, n in missing:
        if any(x.startswith("Err") for x in declared[p]):
            kinds[(p, n)] = "DECLARER-GAP"
        elif any(n in names for q, names in declared.items() if q != p):
            kinds[(p, n)] = "WRONG-QUALIFIER"
        else:
            kinds[(p, n)] = "UNRESOLVED"

    return {
        "tree": tree.name,
        "refs": refs,
        "missing": missing,
        "declared": declared,
        "kinds": kinds,
        "verdict": "CLEAN" if not missing else "BROKEN",
    }


def report(trees: list[pathlib.Path], err_only: bool = True) -> int:
    print(f"  state: AS DRAWN (.pre-fix.json) · scope: "
          f"{'cross-package Err* references' if err_only else 'ALL cross-package references'}")
    worst = 0
    for t in trees:
        try:
            r = audit(t, err_only)
        except (FileNotFoundError, ValueError) as e:
            print(f"  REFUSING  {e}")
            worst = max(worst, 2)
            continue
        uniq = sorted({(p, n) for _, p, n in r["refs"]})
        print(f"\n  {r['tree']}   {r['verdict']}   {len(r['refs'])} reference(s), "
              f"{len(uniq)} distinct")
        for pkg, name in uniq:
            ok = name in r["declared"][pkg]
            print(f"      {'ok ' if ok else 'MISSING'}  {pkg}.{name}")
        if r["missing"]:
            worst = max(worst, 1)
            seen: set[tuple[str, str]] = set()
            for f, p, n in r["missing"]:
                if (p, n) in seen:
                    continue
                seen.add((p, n))
                kind = r["kinds"][(p, n)]
                owner = next((q for q, names in r["declared"].items() if q != p and n in names), None)
                where = f"; {owner} declares it" if owner else ""
                print(f"      ^ {kind}: {f} references {p}.{n}; {p} declares "
                      f"{sorted(x for x in r['declared'][p] if x.startswith('Err')) or '(no Err*)'}{where}")
    print("\n  PRIMARY endpoint: CLEAN = every cross-package sentinel reference resolves.")
    print("  ⚠️ A green BUILD is not this endpoint — the fix loop repairs ~3/5 of these.")
    return worst


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    import tempfile

    def tree(files: dict[str, str]) -> pathlib.Path:
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".pre-fix.json").write_text(json.dumps({"files": files}))
        return d

    MODELS_LONG = ('package models\n\nimport "errors"\n\nvar (\n'
                   '\tErrInsufficientFunds = errors.New("insufficient funds")\n'
                   '\tErrNotFound = errors.New("nf")\n)\n')
    MODELS_SHORT = ('package models\n\nimport "errors"\n\nvar (\n'
                    '\tErrInsufficient = errors.New("insufficient funds")\n'
                    '\tErrNotFound = errors.New("nf")\n)\n')
    API = ('package api\n\nimport "m/internal/models"\n\n'
           'func h() { _ = models.ErrInsufficientFunds; _ = models.ErrNotFound }\n')

    r = audit(tree({"internal/models/models.go": MODELS_LONG, "internal/api/response.go": API}))
    chk("matching names -> CLEAN", r["verdict"], "CLEAN")
    chk("both refs seen", len(r["refs"]), 2)

    r = audit(tree({"internal/models/models.go": MODELS_SHORT, "internal/api/response.go": API}))
    chk("abbreviated declarer -> BROKEN", r["verdict"], "BROKEN")
    chk("names the missing one", [n for _, _, n in r["missing"]], ["ErrInsufficientFunds"])

    # THE GROUPED BLOCK IS THE WHOLE POINT: a declarer whose sentinels are grouped must still
    # count as declaring them. If top_level_decls ever regressed the way exported_api had, this
    # tool would report every correct tree as BROKEN.
    r = audit(tree({"internal/models/models.go": MODELS_LONG, "internal/api/r.go": API}))
    chk("grouped decls are found", r["verdict"], "CLEAN")

    # same-package use is not a cross-package reference
    same = ('package models\n\nfunc f() { _ = models.ErrGhost }\n')
    r = audit(tree({"internal/models/models.go": MODELS_LONG, "internal/models/b.go": same}))
    chk("same package skipped", r["refs"], [])

    # a qualifier that is not one of ours (stdlib) must be ignored
    std = 'package api\n\nimport "errors"\n\nvar e = errors.New("x")\n'
    r = audit(tree({"internal/models/models.go": MODELS_LONG, "internal/api/a.go": std}))
    chk("stdlib qualifier ignored", r["refs"], [])

    # non-Err cross-package names are out of scope by default, in scope with --all
    typ = ('package api\n\nimport "m/internal/models"\n\nfunc h() models.Account { return models.Account{} }\n')
    t = tree({"internal/models/models.go": MODELS_LONG, "internal/api/a.go": typ})
    chk("types skipped by default", audit(t)["refs"], [])
    chk("types counted with --all", len(audit(t, err_only=False)["refs"]) > 0, True)

    # ---- the two defect classes must not collapse into one another ----
    r = audit(tree({"internal/models/models.go": MODELS_SHORT, "internal/api/response.go": API}))
    chk("abbreviated declarer is a DECLARER-GAP",
        r["kinds"][("models", "ErrInsufficientFunds")], "DECLARER-GAP")

    # api reaches for service.ErrNotFound; service has no sentinels, models has that exact name
    SVC = "package service\n\nfunc Do() error { return nil }\n"
    WRONGQ = ('package api\n\nimport "m/internal/service"\n\nfunc h() { _ = service.ErrNotFound }\n')
    r = audit(tree({"internal/models/models.go": MODELS_LONG,
                    "internal/service/service.go": SVC, "internal/api/a.go": WRONGQ}))
    chk("wrong package is a WRONG-QUALIFIER",
        r["kinds"][("service", "ErrNotFound")], "WRONG-QUALIFIER")

    # ⚠️ A NAME OWNED BY NOBODY, ASKED OF A PACKAGE THAT OWNS SENTINELS, IS STILL A DECLARER-GAP
    # — and this expectation was wrong when first written, which is what the self-test is for.
    # From the tree alone there is NO WAY to tell "the declarer omitted it" from "the consumer
    # invented it": both leave a package that owns sentinels missing the one asked for. The
    # category is named for where the fix would land, not for a cause the evidence cannot reach.
    GHOST = ('package api\n\nimport "m/internal/models"\n\nfunc h() { _ = models.ErrGhost }\n')
    r = audit(tree({"internal/models/models.go": MODELS_LONG, "internal/api/a.go": GHOST}))
    chk("an invented name on a sentinel-owning package is a DECLARER-GAP",
        r["kinds"][("models", "ErrGhost")], "DECLARER-GAP")

    # UNRESOLVED is the genuinely unattributable case: the package owns no sentinels AND no
    # other package declares the name, so nothing in the tree says who should have.
    NOWHERE = ('package api\n\nimport "m/internal/service"\n\nfunc h() { _ = service.ErrGhost }\n')
    r = audit(tree({"internal/models/models.go": MODELS_LONG,
                    "internal/service/service.go": "package service\n\nfunc D() {}\n",
                    "internal/api/a.go": NOWHERE}))
    chk("a name nobody declares, on a package with no sentinels, is UNRESOLVED",
        r["kinds"][("service", "ErrGhost")], "UNRESOLVED")

    # NO SNAPSHOT -> REFUSE, never fall back to disk
    import tempfile as _tf
    bare = pathlib.Path(_tf.mkdtemp())
    (bare / "internal").mkdir()
    try:
        audit(bare)
        chk("missing snapshot must raise", "no raise", "FileNotFoundError")
    except FileNotFoundError:
        pass

    print("  self-test: OK — matching/abbreviated separated, grouped decls found, same-package"
          " and stdlib skipped, no-snapshot refused" if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if not args:
        raise SystemExit(__doc__)
    raise SystemExit(report([pathlib.Path(a) for a in args], err_only="--all" not in sys.argv))
