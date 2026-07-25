#!/usr/bin/env python3
"""Systematic hole hunt: swap one status code per artifact, ask whether the suite notices.

The teeth campaign found its holes by hand, one invariant at a time, and reached 29
CAUGHT / 0 SURVIVED — which reads as "no holes left" and is really "no holes left among
the ones we thought to check". This sweeps instead: for every archived artifact, find a
status-code write in the CODE (not a comment), swap it for a plausible neighbour, and ask
whether the suite goes red.

Status codes are the documented hole shape — response headers and error paths in small
HTTP specs — so this is the cheapest place to sweep, not the only one.

    python _hole_hunt.py

A SURVIVED row is a green build with a real behaviour change. It is a candidate, NOT a
verdict: the next question is always whether the SPEC promises the behaviour that was
broken. On the first run one of the two survivors was a genuine undefended promise and
the other was log-only output, and nothing but reading the spec could tell them apart.
See logs/FINDING-status-code-holes.txt.

Uses _teeth_suite.verdict_for, so an artifact whose baseline is already red reports
BASELINE-RED rather than a fake CAUGHT.
"""
import re, sys, pathlib
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _teeth_suite import verdict_for, GEN

SWAP = {"StatusNotFound": "StatusBadRequest", "StatusCreated": "StatusOK",
        "StatusBadRequest": "StatusNotFound", "StatusTooManyRequests": "StatusServiceUnavailable",
        "StatusMovedPermanently": "StatusFound", "StatusNoContent": "StatusOK",
        "StatusConflict": "StatusBadRequest", "StatusMethodNotAllowed": "StatusBadRequest",
        "StatusUnprocessableEntity": "StatusBadRequest", "StatusOK": "StatusAccepted"}
CODE = re.compile(r"^\s*(?!//)(?!\s*\*).*http\.(Status[A-Za-z]+)")

rows = []
for art in sorted(GEN.glob("*-v4")):
    for f in sorted(art.glob("*.go")):
        if f.name.endswith("_test.go"):
            continue
        hit = None
        for ln in f.read_text(errors="ignore").splitlines():
            m = CODE.match(ln)
            if m and m.group(1) in SWAP:
                hit = (f.name, m.group(1)); break
        if hit:
            rel, old = hit
            new = SWAP[old]
            def mut(text, o=old, n=new):
                out, k = re.subn(rf"http\.{o}\b", f"http.{n}", text, count=1)
                return out if k else None
            v, note = verdict_for(art, rel, mut)
            rows.append((art.name, rel, f"{old}->{new}", v))
            print(f"{art.name:<26} {rel:<22} {old}->{new:<26} {v}", flush=True)
            break
surv = [r for r in rows if r[3] == "SURVIVED"]
print(f"\n{len(rows)} artifacts probed · {len(surv)} SURVIVED (green build, real bug)")
for r in surv:
    print("   ", r)
