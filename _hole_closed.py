"""Grade PREDICTION-taskflow-contenttype-hole.txt against the regenerated artifact.

Two claims, and the second is the one that would make me revert:
  (1) the Content-Type mutation flips SURVIVED -> CAUGHT;
  (2) no previously-CAUGHT taskflow mutation regresses to SURVIVED — a spec edit that
      buys one hole and opens another is not a fix.
"""
import re, sys, pathlib, shutil, tempfile
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
