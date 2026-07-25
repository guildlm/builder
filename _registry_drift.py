"""How many registered mutations survive a REGENERATION? Measured without regenerating.

A mutation is a string lifted from one artifact, so it expires when the next run renames
anything — silently, because a patch that no longer applies reports NOAPPLY, and under a
heading that says "must not regress" that reads as "nothing regressed". Two of them were
found expired this way against fresh usersapi/ratelimit trees and repaired by matching on
shape. The obvious next question is how brittle the OTHER twenty-eight are, and there are
only two fresh trees to ask.

So ask the matcher instead of the artifact. Brittleness is a property of the PATTERN, not
of the code, and the drift a regeneration actually produces is overwhelmingly renaming:
a different receiver, a different field for the same map, a different local for the same
slice. Apply those renames textually and see which patterns let go. Nothing here has to
compile — the question is only whether the matcher still matches.

    python _registry_drift.py                # every registered mutation
    python _registry_drift.py --self-test    # the renamer must actually rename, and a
                                             # pattern pinned to a name must be flagged
"""
import pathlib, re, sys, importlib.util

# SPLIT BY EVIDENCE, because a brittleness number is only as honest as the drift fed into
# it, and my first pass mixed renames I had watched happen with ones I made up.
#
# OBSERVED — taken from the fresh usersapi tree against its archive, identifier for
# identifier. This is the only tier that supports a claim about how brittle the registry
# actually is.
OBSERVED = [(r"\bs\b", "m"), (r"\busers\b", "items"), (r"\bok\b", "exists"),
            (r"\bout\b", "result")]
# PLAUSIBLE — the same CLASS as an observed rename (a collection field renamed), different
# word. Generalisation, not evidence.
PLAUSIBLE = [(r"\btasks\b", "entries"), (r"\bprojects\b", "records")]
# UNLIKELY — kept visible so the number they produce cannot be quoted by accident. `w` for
# an http.ResponseWriter and `b` for a receiver are near-universal Go convention; a coder
# renaming them is not the drift this is meant to model, and including them inflated the
# first measurement I took.
UNLIKELY = [(r"\bb\b", "bkt"), (r"\bw\b", "rw")]

TIERS = {"observed": OBSERVED, "plausible": OBSERVED + PLAUSIBLE,
         "all": OBSERVED + PLAUSIBLE + UNLIKELY}


def rename(text: str, tier: str = "observed") -> str:
    for pat, sub in TIERS[tier]:
        text = re.sub(pat, sub, text)
    return text


def _load_registry():
    spec = importlib.util.spec_from_file_location("ts", "_teeth_suite.py")
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["_teeth_suite.py"]
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    return mod.MUTATIONS


def applies(mut, text) -> bool:
    if mut is None:
        return False
    try:
        out = mut(text)
    except Exception:
        return False
    return bool(out) and out != text


def self_test():
    """The renamer must rename, and a name-pinned pattern must come back BRITTLE."""
    src = "\tif _, ok := s.users[u.ID]; ok {\n\t\treturn ErrExists\n\t}\n"
    assert rename(src) != src, "renamer changed nothing"
    assert "m.items" in rename(src), f"expected m.items in {rename(src)!r}"
    pinned = lambda t: (t.replace("s.users", "X") if "s.users" in t else None)
    assert applies(pinned, src) and not applies(pinned, rename(src)), "brittle case not detected"
    shaped = lambda t: (re.sub(r"\w+\.\w+\[\w+\.ID\]", "X", t) if re.search(r"\w+\.\w+\[\w+\.ID\]", t) else None)
    assert applies(shaped, src) and applies(shaped, rename(src)), "robust case misreported"
    print("OK — the renamer renames, a name-pinned pattern is BRITTLE, a shaped one SURVIVES")


if "--self-test" in sys.argv:
    self_test(); raise SystemExit

# This tool sweeps the registry against the archive and takes NO target, so an argument
# means the caller expected something this cannot do. Rejecting it beats answering a
# question that was not asked — nine of the other ten instruments already do, and this one
# is mine, written today, in the middle of fixing exactly this in four others.
_unexpected = [a for a in sys.argv[1:] if not a.startswith("-")]
if _unexpected:
    raise SystemExit(f"{__file__} takes no target — it sweeps the whole registry against "
                     f"generated/. Got: {', '.join(_unexpected)}")

GEN = pathlib.Path("generated")
rows, brittle, robust, inapplicable = [], 0, 0, 0
for spec_name, rel, desc, mut in _load_registry():
    f = GEN / f"{spec_name}-v4" / rel
    if not f.exists() or mut is None:
        inapplicable += 1
        rows.append((spec_name, rel, desc, "no-baseline")); continue
    text = f.read_text()
    if not applies(mut, text):
        inapplicable += 1
        rows.append((spec_name, rel, desc, "no-baseline")); continue
    verdicts = {t: applies(mut, rename(text, t)) for t in TIERS}
    if verdicts["observed"]:
        robust += 1
    else:
        brittle += 1
    rows.append((spec_name, rel, desc, verdicts))

total = brittle + robust
print(f"{total} mutations testable ({inapplicable} have no live baseline to drift)\n")
for tier in TIERS:
    survived = sum(1 for r in rows if isinstance(r[3], dict) and r[3][tier])
    note = {"observed": "  <- the defensible number: renames taken from a real regeneration",
            "plausible": "  <- same class, invented words",
            "all": "  <- includes renames convention makes unlikely; do not quote"}[tier]
    print(f"  survives {tier:<10} {survived:>2}/{total}{note}")
print()
for s, rel, desc, v in rows:
    if isinstance(v, dict) and not v["observed"]:
        print(f"  BRITTLE  {s:<12} {rel:<28} {desc[:42]}")
