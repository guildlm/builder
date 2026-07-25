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

    python _hole_closed.py <regenerated-artifact-dir> [spec-name]

The spec name defaults to the directory's leading segment; it selects which registered
mutations in _teeth_suite must not regress. Question (1) currently probes the
Content-Type shape, which is the one this was built for — a second shape means a second
probe here, not a flag.

Uses _teeth_suite.verdict_for, so an artifact whose baseline is already red reports
BASELINE-RED rather than a fake CAUGHT.
"""
import re, sys, pathlib
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _teeth_suite import verdict_for, MUTATIONS, GEN

NEW = pathlib.Path(sys.argv[1])
SPEC = sys.argv[2] if len(sys.argv) > 2 else NEW.name.split("-")[0]
HEADER = re.compile(r'^\s*w\.Header\(\)\.Set\("Content-Type", *"[^"]*"\)', re.M)

def drop_ct(text):
    m = HEADER.search(text)
    return text.replace(m.group(0), "\t// MUTANT: header dropped", 1) if m else None

# 1. the hole itself
target = next((f.name for f in NEW.glob("*.go")
               if not f.name.endswith("_test.go") and HEADER.search(f.read_text())), None)
print(f"Content-Type is set in: {target}")
if target:
    v, note = verdict_for(NEW, target, drop_ct)
    print(f"  (1) drop Content-Type -> {v}   [was SURVIVED before the spec edit]")
else:
    print("  (1) SKIPPED — no Content-Type set in this artifact")

# 2. the registered mutations must not regress
print(f"  (2) previously-registered {SPEC} mutations (must not regress):")
for spec, rel, desc, mut in MUTATIONS:
    if spec != SPEC:
        continue
    if mut is None:
        print(f"      {rel:<16} {desc[:44]:<44} (no mutator)"); continue
    v, _ = verdict_for(NEW, rel, mut)
    print(f"      {rel:<16} {desc[:44]:<44} {v}")
