#!/usr/bin/env python3
"""Read ONE arm across EVERY process that drew it. Does its verdict transport?

    ./_transport_table.py                                  # the axis arms + the positive control
    ./_transport_table.py --spec ledger-origorder.yaml     # one spec, every process
    ./_transport_table.py --only p4,p5                     # restrict to named processes
    ./_transport_table.py --self-test

WHY THIS EXISTS, AND WHY IT DID NOT EXIST UNTIL NOW. Every table in this campaign reads DOWN one
process: `_arm_table.py --pid N` is a series, and a series is a process. The claim of 21 August is
the other direction — the same spec read ACROSS processes — and that reading has been done by eye
every time it was done at all. 15 August is what that costs: F1 is byte-identical LONG twice on
pid 4970 and byte-identical ABSENT twice on pid 36921, and the sentence that survived from the
session before it ("the sharpest pair in the campaign") was written from ONE process's column.

WHAT IT REFUSES TO CONFLATE, because the campaign has confused each of these at least once:

  WITHIN-PROCESS DETERMINISM   the same spec drawn twice on ONE process agreeing.
  CROSS-PROCESS TRANSPORT      the same spec agreeing on TWO processes.

  They are different claims and the first is not evidence for the second — that is 15 August's
  result stated as a rule. So a spec gets TWO columns: `within` (are this process's own draws
  consistent?) and the overall transport verdict, and neither is computed from the other.

TRANSPORT VERDICTS, three-valued like everything else here (ABBREVIATED is its own value, never
folded into LONG — 11 August):

  STABLE     every process that drew it landed on the SAME verdict         (>= 2 processes)
  SPLIT      processes disagree — the verdict is a fact about the process, not the spec
  SINGLE     exactly one process has ever drawn it; it says NOTHING about transport, and it is
             printed as SINGLE rather than as agreement-so-far, because a 1-process arm reading
             "STABLE" is precisely the misreading this tool was written to stop.
  WOBBLE     at least one process disagrees with ITSELF across redraws. Transport is not computed
             at all in that case: the within-process value is not defined, so the across-process
             question has no operand. Reported loudly, never silently dropped.

⚠️ IT READS THE SAME RECORDS `_arm_table.py` DOES, THROUGH `_arm_table.py`. Verdicts come from the
ledger AND are recomputed from the tree on disk by the same classifier the probe called; a
disagreement REFUSES there and this tool inherits the refusal rather than re-implementing it.
Non-classifying rows (GPU deaths) are dropped loudly by that build and reprinted here.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import _arm_table  # noqa: E402
from _size_floor_tally import SERIES  # noqa: E402

HERE = pathlib.Path(__file__).parent
BASELINE = "specs/ledger-origorder-baseline.yaml"

# The arms the 21 August prereg turns on. Named, not inferred: a tool that picked "interesting"
# specs by a rule would pick different ones after the draw than before it.
DEFAULT_SPECS = [
    "ledger-sentinelline-placebo.yaml",   # paraphrase +20, replace   — the anchor
    "ledger-consaxis-rep1.yaml",          # R1 +20, replace
    "ledger-consaxis-pad1.yaml",          # G1 +20, pad
    "ledger-linefloor-4.yaml",            # F4 +20, pad (adverb ladder)
    "ledger-linefloor-1.yaml",            # F1 +15, the arm that proved transport is not free
    "ledger-origorder.yaml",              # shipped +51, the positive control
    "ledger-origorder-baseline.yaml",     # the untreated draw itself
]


def collect(root: pathlib.Path, only: set = frozenset()) -> tuple:
    """-> ({spec: {process: [row, ...]}}, [dropped-row-note, ...])

    Rows are whatever `_arm_table.build` returns for each series, so every check that tool makes
    has already been made by the time a row arrives here.
    """
    by_spec, dropped = {}, []
    for name, pid, prefix in SERIES:
        if only and name not in only:
            continue
        try:
            rows = _arm_table.build(root, prefix, BASELINE, pid=pid)
        except _arm_table.Refuse as e:
            raise SystemExit(f"REFUSING on series {name} (pid {pid}, prefix {prefix}): {e}")
        for d in getattr(rows, "dropped", ()):
            dropped.append(f"{name}/{d['label']} {d['spec']} {d['verdict']}")
        for r in rows:
            by_spec.setdefault(r["spec"], {}).setdefault(name, []).append(r)
    return by_spec, dropped


def verdict_of_process(rows: list) -> str:
    """The process's own value for this spec, or "" when its draws disagree."""
    vs = {r["verdict"] for r in rows}
    return vs.pop() if len(vs) == 1 else ""


def transport(per_process: dict) -> str:
    values = {p: verdict_of_process(rs) for p, rs in per_process.items()}
    if any(v == "" for v in values.values()):
        return "WOBBLE"
    if len(values) < 2:
        return "SINGLE"
    return "STABLE" if len(set(values.values())) == 1 else "SPLIT"


def render(by_spec: dict, specs: list, dropped: list) -> str:
    out = []
    for spec in specs:
        per_process = by_spec.get(spec)
        if not per_process:
            out.append(f"  {spec}\n      never drawn on a screened process")
            continue
        t = transport(per_process)
        out.append(f"  {spec}   ->  {t}   ({len(per_process)} process"
                   f"{'es' if len(per_process) != 1 else ''})")
        for name, _pid, _prefix in SERIES:
            rows = per_process.get(name)
            if not rows:
                continue
            own = verdict_of_process(rows) or "DISAGREES WITH ITSELF"
            draws = "  ".join(f"{r['verdict']}/{r['sha']}" for r in rows)
            out.append(f"      {name:<4} {rows[0]['pid']:<7} {len(rows)} draw"
                       f"{'s' if len(rows) != 1 else ' '}  {own:<28} {draws}")
    if dropped:
        out.append("")
        out.append("  DROPPED (classify nothing, counted nowhere, printed so they are not invisible)")
        for d in dropped:
            out.append(f"      {d}")
    return "\n".join(out)


def self_test() -> int:
    ok = True

    def chk(name, cond):
        nonlocal ok
        if not cond:
            ok = False
            print(f"  FAIL {name}")
        else:
            print(f"  ok   {name}")

    def rows(*verdicts):
        return [{"verdict": v, "sha": "0" * 8, "pid": "1"} for v in verdicts]

    # --- the four transport verdicts, on synthetic rows -------------------------------------
    chk("two processes agreeing is STABLE",
        transport({"pA": rows("LONG"), "pB": rows("LONG")}) == "STABLE")
    chk("two processes disagreeing is SPLIT",
        transport({"pA": rows("LONG"), "pB": rows("ABSENT")}) == "SPLIT")
    chk("one process is SINGLE, never STABLE",
        transport({"pA": rows("LONG", "LONG")}) == "SINGLE")
    chk("a process disagreeing with itself is WOBBLE",
        transport({"pA": rows("LONG", "ABSENT"), "pB": rows("LONG")}) == "WOBBLE")
    chk("WOBBLE wins over SPLIT — an undefined operand is not a disagreement",
        transport({"pA": rows("LONG", "ABSENT"), "pB": rows("ABSENT")}) == "WOBBLE")

    # ⚠️ THREE-VALUED, and this is the assertion 11 August's correction earns. ABBREVIATED is a
    # rung of its own; folding it into LONG would have turned pid 16225's broken positive control
    # into "the control reproduced".
    chk("ABBREVIATED does not count as LONG",
        transport({"pA": rows("LONG"), "pB": rows("ABBREVIATED:ErrInsufficient")}) == "SPLIT")
    chk("ABBREVIATED agreeing with ABBREVIATED is STABLE",
        transport({"pA": rows("ABBREVIATED:ErrInsufficient"),
                   "pB": rows("ABBREVIATED:ErrInsufficient")}) == "STABLE")

    # --- against the REAL archive, on two processes that are DEAD -----------------------------
    # ⚠️ PINNED ON DEAD PROCESSES ON PURPOSE. p4 (pid 4970) and p5 (pid 36921) can never gain a
    # row, so this assertion cannot be broken by a future draw — which means it can never be
    # "fixed" by editing the expectation after a result. F1 is the campaign's proof that
    # within-process determinism does not transport: byte-identical LONG twice on p4,
    # byte-identical ABSENT twice on p5.
    root = HERE
    by_spec, _ = collect(root, only={"p4", "p5"})
    f1 = by_spec.get("ledger-linefloor-1.yaml", {})
    chk("F1 was drawn on both p4 and p5", set(f1) == {"p4", "p5"})
    chk("F1 is deterministic WITHIN p4 (LONG)", verdict_of_process(f1.get("p4", [])) == "LONG")
    chk("F1 is deterministic WITHIN p5 (ABSENT)", verdict_of_process(f1.get("p5", [])) == "ABSENT")
    chk("F1 is SPLIT across p4/p5 — the whole point of the tool", transport(f1) == "SPLIT")
    chk("F1's p4 draws are byte-identical to each other",
        len({r["sha"] for r in f1.get("p4", [])}) == 1)

    print("SELF-TEST OK" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", action="append", default=[],
                    help="spec file name (repeatable); default is the 21 August arm set")
    ap.add_argument("--only", default="", help="comma-separated process names, e.g. p4,p5")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    only = {s.strip() for s in a.only.split(",") if s.strip()}
    by_spec, dropped = collect(HERE, only)
    specs = a.spec or DEFAULT_SPECS
    print()
    print("    THE SAME ARM ACROSS PROCESSES — transport, which is not within-process determinism")
    print()
    print(render(by_spec, specs, dropped))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
