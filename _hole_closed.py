#!/usr/bin/env python3
"""Did a spec edit close the hole it was meant to, and open no other?

A hole found by _hole_hunt.py is closed by NAMING a test in the spec — no compiler error
exists for "a promise nothing checks", so it is the spec-writer's job, not a gate's. Then
the project is regenerated and the claim has to be graded, which is two questions:

  (1) does the mutation that used to SURVIVE now get CAUGHT?
  (2) does every mutation that already passed still pass?

(2) is the one that matters and the one it is tempting to skip. A spec edit reaches EVERY
file's prompt — _file_list puts every purpose into every one — so an edit that buys one
hole and opens another looks like a success from (1) alone. This project has needed three
attempts on a single spec edit before.

    python _hole_closed.py <regenerated-artifact-dir> [spec-name] [--probe=content-type|status|badrequest] [--file=router.go]

The spec name defaults to the directory's leading segment; it selects which registered
mutations in _teeth_suite must not regress. Question (1) probes whichever shape _hole_hunt used to FIND the hole, chosen with
--probe; a mismatch there grades the wrong thing and would report a hole closed that was
never touched.

Uses _teeth_suite.verdict_for, so an artifact whose baseline is already red reports
BASELINE-RED rather than a fake CAUGHT.
"""
import re, sys, pathlib
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _teeth_suite import verdict_for, MUTATIONS, GEN

NEW = pathlib.Path(sys.argv[1])
# A directory that does not exist must be an ERROR, not a quiet "nothing found".
# Called as `--dir X --probe=...` (no positional) this took "--dir" as the artifact
# path, globbed an absent directory, matched no sites and printed
#   drop Content-Type applies in: None / (1) SKIPPED
# which reads exactly like a real answer about a real artifact. A grader whose
# failure mode is a plausible-looking SKIP is worse than no grader.
if not NEW.is_dir():
    raise SystemExit(f"{NEW} is not a directory — pass the artifact dir POSITIONALLY:\n"
                     f"  python _hole_closed.py <artifact-dir> [spec] [--probe=...] [--file=...]")
if not any(f for f in NEW.glob("*.go") if not f.name.endswith("_test.go")):
    raise SystemExit(f"{NEW} has no non-test .go files — nothing to grade")
SPEC = sys.argv[2] if len(sys.argv) > 2 else NEW.name.split("-")[0]
# Which hole is being graded. Question (1) has to probe the SAME shape _hole_hunt used to
# find it, so the probe is chosen rather than assumed — the first version hardcoded
# Content-Type and could not have graded the /health hole it was about to be pointed at.
PROBES = {
    "content-type": (
        re.compile(r'^\s*w\.Header\(\)\.Set\("Content-Type", *"[^"]*"\)', re.M),
        "\t// MUTANT: header dropped",
        "drop Content-Type"),
    "status": (
        re.compile(r'\bhttp\.StatusOK\b'),
        "http.StatusAccepted",
        "StatusOK -> StatusAccepted"),
    "badrequest": (
        re.compile(r'\bhttp\.StatusBadRequest\b'),
        "http.StatusNotFound",
        "StatusBadRequest -> StatusNotFound"),
}
PROBE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--probe=")),
             "content-type")
if PROBE not in PROBES:
    raise SystemExit(f"unknown --probe={PROBE}; choose from {', '.join(PROBES)}")
PATTERN, REPLACEMENT, LABEL = PROBES[PROBE]


def break_it(text):
    m = PATTERN.search(text)
    return text.replace(m.group(0), REPLACEMENT, 1) if m else None


# 1. the hole itself.
#
# PIN THE FILE. Taking "the first file the pattern matches" grades whichever site comes
# first alphabetically, which is not the site the hole was found in: probing shortener for
# StatusOK picks handlers.go and reports CAUGHT, while the /health hole lives in router.go
# and is SURVIVED. That is a false "hole closed" on a site nobody touched — caught by
# running this against the artifact whose answer was already known, which is the only
# reason it did not become a result.
PINNED = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--file=")), None)
target = PINNED or next(
    (f.name for f in sorted(NEW.glob("*.go"))
     if not f.name.endswith("_test.go") and PATTERN.search(f.read_text())), None)
if PINNED and not (NEW / PINNED).exists():
    raise SystemExit(f"--file={PINNED} is not in {NEW}")
print(f"{LABEL} applies in: {target}")
if target:
    v, note = verdict_for(NEW, target, break_it)
    print(f"  (1) {LABEL} -> {v}   [was SURVIVED before the spec edit]")
else:
    print(f"  (1) SKIPPED — nothing for {LABEL} in this artifact")

# 2. the registered mutations must not regress
print(f"  (2) previously-registered {SPEC} mutations (must not regress):")
# NOAPPLY IS NOT A PASS. The registry pins EXACT strings lifted from the ARCHIVED
# artifact, and a fresh coder writes the same behaviour differently — so against a newly
# generated tree the patches stop applying and every row reads "· NOAPPLY", which in a
# list headed "must not regress" looks like nothing regressed. Measured, not assumed:
# against fresh trees usersapi went 2 live -> 0 (the check was entirely vacuous and I
# nearly reported it as clean), while ratelimit stayed 1 -> 1 and its CAUGHT was real.
# So: say how many actually RAN, and refuse to exit 0 when none did.
ran = noapply = 0
for spec, rel, desc, mut in MUTATIONS:
    if spec != SPEC:
        continue
    if mut is None:
        print(f"      {rel:<16} {desc[:44]:<44} (no mutator)"); continue
    v, _ = verdict_for(NEW, rel, mut)
    if v == "NOAPPLY":
        noapply += 1
    else:
        ran += 1
    print(f"      {rel:<16} {desc[:44]:<44} {v}")
if noapply:
    print(f"      -> {ran} mutation(s) actually ran, {noapply} did NOT APPLY to this tree.")
if noapply and not ran:
    raise SystemExit("      REGRESSION UNMEASURED — every registered mutation failed to "
                     "apply.\n      This is not 'no regression'; it is no check. Re-pin the "
                     "mutations against\n      this artifact before claiming the closure "
                     "composes.")
