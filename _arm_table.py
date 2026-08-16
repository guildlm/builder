#!/usr/bin/env python3
"""Assemble the arm table for a probe series from the LEDGER and the AS-DRAWN trees.

    ./_arm_table.py --prefix p3-
    ./_arm_table.py --prefix p3- --baseline specs/ledger-origorder-baseline.yaml
    ./_arm_table.py --self-test

WHY THIS EXISTS. Every result log in this campaign carries a table of arms — spec, size delta,
verdict, sha — and every one of those tables has so far been TYPED, by reading verdicts off the
terminal and shas off a second command. This repo's standing rule says a hand-retyped analysis
snippet is an uninstrumented measurement and its eyeballed column will be the one that is wrong;
three retractions came from exactly that shape. The table is the artefact readers trust most, so
it is the last thing that should be assembled by hand.

WHAT IT CHECKS, rather than assumes — the point is not formatting, it is that four independent
records of the same draw agree:

  1. THE LEDGER ROW says a verdict.        (written when the probe ran)
  2. THE TREE is re-classified NOW with the same classifier the probe called, `_sentinel_verdict`.
     Disagreement means a tree was overwritten, a label was reused, or the classifier changed
     under a published table — all silent today, all fatal to a result.
  3. THE PROBE LOG is re-scanned for repair activity. The probe refuses on it at draw time; this
     re-checks at READ time, because "as-drawn" is a property of the artefact being read.
  4. THE SPEC DELTA is COMPUTED from the two yaml files at the named purpose, never typed. The
     rendered purpose is what reaches the model; the file's byte size is not (yaml quoting and
     folding differ), and the two numbers disagree by ~6 characters on these specs.

It REFUSES rather than degrading: a missing tree, a verdict disagreement, repair activity, a
duplicated label, or arms drawn on more than one pid all stop the table. A table that quietly
dropped a row would be worse than no table, because the rows that remained would look complete.

⚠️ THE LABEL PREFIX IS NOT A SERIES IDENTIFIER, AND THIS TOOL FOUND THAT OUT ON ITS FIRST RUN.
`--prefix p3-` matched the 11 August series AND four rows from 6 August, where `p3-` meant "the
third process of that day" on pid 64149. Both series contain a `p3-...treated`-shaped arm with
verdict LONG, so a hand-grepped table would have looked entirely plausible with two days mixed
into it. The multi-pid refusal caught it; `--pid` is the narrowing, because process identity is
what a series actually is in this campaign.
"""

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import yaml  # noqa: E402

from _sentinel_verdict import verdict as classify  # noqa: E402

LEDGER_RE = re.compile(
    r"^(?P<ts>\S+)\s+pid=(?P<pid>\S+)\s+label=(?P<label>\S+)\s+"
    r"spec=(?P<spec>\S+)\s+VERDICT=(?P<verdict>\S+)\s*$"
)
# The same expression the probe uses to decide a tree is not as-drawn. Kept identical on purpose:
# a reader-side check that is WEAKER than the writer-side one would pass trees the probe rejected.
REPAIR_RE = re.compile(r"compile/test FAILED|fix round|deterministic fix|converged to green")

TARGET = "internal/models/models.go"


class Refuse(Exception):
    pass


def read_ledger(path: pathlib.Path, prefix: str, pid: str = "") -> list:
    rows = []
    seen = set()
    for line in path.read_text().splitlines():
        m = LEDGER_RE.match(line)
        if not m or not m.group("label").startswith(prefix):
            continue
        if pid and m.group("pid") != pid:
            continue
        d = m.groupdict()
        if d["label"] in seen:
            raise Refuse(f"label {d['label']!r} appears twice in the ledger — a reused label "
                         f"means one of the two trees on disk is not the one that row describes")
        seen.add(d["label"])
        rows.append(d)
    if not rows:
        raise Refuse(f"no ledger rows with label prefix {prefix!r}"
                     + (f" on pid {pid}" if pid else ""))
    return rows


def purpose_of(spec: pathlib.Path, target: str) -> str:
    doc = yaml.safe_load(spec.read_text())
    for f in doc.get("files", []):
        if f.get("path") == target:
            return f.get("purpose", "")
    raise Refuse(f"{spec} has no file {target}")


def differs_elsewhere(base: pathlib.Path, spec: pathlib.Path, target: str) -> bool:
    """True if the spec differs from the baseline at some purpose OTHER than the target.

    ⚠️ WITHOUT THIS THE DELTA COLUMN LIES BY OMISSION. Two arms in this campaign inject their
    edit into the STORE purposes, three files away from models.go; measured at models.go their
    delta is +0, which reads as "no edit" when it means "the edit is elsewhere". One of those
    rows is a NULL control and the other FLIPS the process — precisely the pair a reader must
    not confuse. The delta stays measured at the target, because that is the honest number; the
    marker says where the manipulation actually is.
    """
    a, b = yaml.safe_load(base.read_text()), yaml.safe_load(spec.read_text())
    pa = {f.get("path"): f.get("purpose") for f in a.get("files", [])}
    pb = {f.get("path"): f.get("purpose") for f in b.get("files", [])}
    return any(k != target and pa.get(k) != pb.get(k) for k in set(pa) | set(pb))


# ⚠️ VERDICTS THAT CLASSIFY NOTHING. A row with one of these is not an arm — the draw failed, or
# the process died under it, or the tree was repaired. Added 16 August, when the Metal driver
# killed pid 68231 in the middle of an arm and the resulting VOID row stopped the whole table:
# every arm drawn on that process became unreadable because ONE row had no tree. Dropping them
# silently would be worse than refusing, so they are dropped LOUDLY — see `Rows.dropped`, which
# render() prints and the tally reprints. A void row that DOES have a tree still refuses: then the
# verdict and the artefact disagree, and that is the thing this tool exists to catch.
NON_CLASSIFYING = ("NO-FILE", "VOID-REPAIRED", "VOID-CLASSIFIER", "VOID-SERVER-DIED")


class Rows(list):
    """The classifying arms — which REMEMBERS what it dropped, so nothing leaves without a line."""

    dropped = ()


def build(root: pathlib.Path, prefix: str, baseline: str, target: str = TARGET,
          pid: str = "") -> Rows:
    rows = read_ledger(root / "logs" / "PROBE-LEDGER.txt", prefix, pid)

    dropped = []
    kept = []
    for r in rows:
        if r["verdict"] in NON_CLASSIFYING:
            tree = root / "generated" / f"probe-{r['label']}" / target
            if tree.is_file():
                raise Refuse(
                    f"{r['label']}: the ledger says {r['verdict']} — a verdict that means no arm "
                    f"was measured — but a tree exists at {tree}. One of the two is lying and "
                    f"guessing which is how a void draw becomes a data point")
            dropped.append(r)
        else:
            kept.append(r)
    rows = kept
    if not rows:
        raise Refuse(f"every row with prefix {prefix!r}"
                     + (f" on pid {pid}" if pid else "")
                     + f" is non-classifying ({', '.join(r['verdict'] for r in dropped)})")

    pids = {r["pid"] for r in rows}
    if len(pids) > 1:
        raise Refuse(f"arms span {len(pids)} pids ({', '.join(sorted(pids))}) — a series table is "
                     f"about ONE process; pass --pid or the table is a confound")

    base_purpose = purpose_of(root / baseline, target) if baseline else None

    out = []
    for r in rows:
        tree = root / "generated" / f"probe-{r['label']}" / target
        if not tree.is_file():
            raise Refuse(f"{r['label']}: no tree at {tree} — the ledger says this arm was drawn")

        log = root / "logs" / f"probe-{r['label']}.log"
        if log.is_file() and REPAIR_RE.search(log.read_text(errors="replace")):
            raise Refuse(f"{r['label']}: repair activity in {log} — NOT as-drawn")

        code = tree.read_text()
        now = classify(code)
        if now != r["verdict"]:
            raise Refuse(f"{r['label']}: ledger says {r['verdict']} but the tree on disk "
                         f"classifies as {now} — one of the two is not what it claims to be")

        import hashlib
        sha = hashlib.sha256(code.encode()).hexdigest()[:8]

        delta, elsewhere = "", False
        spec_path = root / "specs" / r["spec"]
        if base_purpose is not None:
            if spec_path.is_file():
                delta = f"{len(purpose_of(spec_path, target)) - len(base_purpose):+d}"
                elsewhere = differs_elsewhere(root / baseline, spec_path, target)
            else:
                delta = "?"

        out.append({"label": r["label"], "pid": r["pid"], "spec": r["spec"], "delta": delta,
                    "elsewhere": elsewhere, "verdict": now, "sha": sha, "ts": r["ts"]})
    result = Rows(out)
    result.dropped = tuple(dropped)
    return result


def render(rows: list) -> str:
    w = max(len(r["label"]) for r in rows)
    s = max(len(r["spec"]) for r in rows)
    lines = [f"    {'arm'.ljust(w)}  {'spec'.ljust(s)}  delta  verdict                     sha"]
    for r in rows:
        d = r["delta"] + ("*" if r.get("elsewhere") else "")
        lines.append(f"    {r['label'].ljust(w)}  {r['spec'].ljust(s)}  {d:>6}  "
                     f"{r['verdict']:<26}  {r['sha']}")
    if any(r.get("elsewhere") for r in rows):
        lines.append("    * the delta is measured AT THE TARGET; this spec's edit is at a "
                     "DIFFERENT purpose, so +0 here does not mean no edit")
    for d in getattr(rows, "dropped", ()):
        lines.append(f"    DROPPED  {d['label']}  {d['spec']}  {d['verdict']} — classifies "
                     f"nothing, counted nowhere, printed here so it is not invisible")
    return "\n".join(lines)


def self_test() -> int:
    import tempfile
    ok = True

    def chk(name, cond):
        nonlocal ok
        if not cond:
            ok = False
            print(f"  FAIL {name}")

    GROUPED = ('package models\n\nimport "errors"\n\nvar (\n\t%s\n)\n')

    def fixture(tmp, verdict_written, decl, repair=False, drop_tree=False):
        root = pathlib.Path(tmp)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "specs").mkdir(parents=True, exist_ok=True)
        (root / "generated" / "probe-t-a" / "internal" / "models").mkdir(parents=True, exist_ok=True)
        (root / "logs" / "PROBE-LEDGER.txt").write_text(
            "noise line that is not a row\n"
            f"2026-01-01T00:00:00  pid=1  label=t-a  spec=treated.yaml VERDICT={verdict_written}\n")
        if not drop_tree:
            (root / "generated" / "probe-t-a" / TARGET).write_text(GROUPED % decl)
        (root / "logs" / "probe-t-a.log").write_text("fix round 1\n" if repair else "all good\n")
        for name, extra in (("base.yaml", ""), ("treated.yaml", "0123456789")):
            (root / "specs" / name).write_text(yaml.safe_dump(
                {"files": [{"path": TARGET, "purpose": "abc" + extra}]}))
        return root

    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficientFunds = errors.New("x")')
        rows = build(root, "t-", "specs/base.yaml")
        chk("happy path returns one row", len(rows) == 1)
        # the delta is COMPUTED from the rendered purpose, not read off the file size
        chk("delta computed from the purpose", rows[0]["delta"] == "+10")
        chk("verdict re-classified", rows[0]["verdict"] == "LONG")
        chk("sha is 8 hex", len(rows[0]["sha"]) == 8)
        chk("render mentions the arm", "t-a" in render(rows))

    # ⚠️ THE CHECK THIS TOOL EXISTS FOR: ledger and tree disagreeing must STOP the table, not
    # pick one. A published table whose rows came from two different draws is the failure mode.
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficient = errors.New("x")')
        try:
            build(root, "t-", "specs/base.yaml")
            chk("disagreement refuses", False)
        except Refuse as e:
            chk("disagreement names both readings", "LONG" in str(e) and "ABBREVIATED" in str(e))

    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficientFunds = errors.New("x")', repair=True)
        try:
            build(root, "t-", "specs/base.yaml")
            chk("repair activity refuses", False)
        except Refuse as e:
            chk("repair refusal says as-drawn", "as-drawn" in str(e))

    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'x', drop_tree=True)
        try:
            build(root, "t-", "specs/base.yaml")
            chk("missing tree refuses", False)
        except Refuse:
            pass

    # ⚠️ THE 16 AUGUST CASE: a draw the process died under. It must not stop the table, must not
    # be counted, and must not vanish — all three, or the next crash costs a session's arms.
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficientFunds = errors.New("x")')
        (root / "logs" / "PROBE-LEDGER.txt").write_text(
            "2026-01-01T00:00:00  pid=1  label=t-a  spec=treated.yaml VERDICT=LONG\n"
            "2026-01-01T00:00:01  pid=1  label=t-dead spec=treated.yaml VERDICT=VOID-SERVER-DIED\n")
        rows = build(root, "t-", "specs/base.yaml")
        chk("a void row does not stop the table", len(rows) == 1)
        chk("the void row is remembered", [d["label"] for d in rows.dropped] == ["t-dead"])
        chk("and render names it", "DROPPED" in render(rows) and "t-dead" in render(rows))

    # a void row that HAS a tree is a contradiction and must still refuse
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "NO-FILE", 'ErrInsufficientFunds = errors.New("x")')
        try:
            build(root, "t-", "specs/base.yaml")
            chk("a void verdict with a tree refuses", False)
        except Refuse as e:
            chk("that refusal names the contradiction", "no arm was measured" in str(e))

    # and a series that is ONLY void rows is not a table with zero arms, it is a refusal
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'x', drop_tree=True)
        (root / "logs" / "PROBE-LEDGER.txt").write_text(
            "2026-01-01T00:00:00  pid=1  label=t-a  spec=treated.yaml VERDICT=NO-FILE\n")
        try:
            build(root, "t-", "specs/base.yaml")
            chk("an all-void series refuses", False)
        except Refuse as e:
            chk("it says why", "non-classifying" in str(e))

    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficientFunds = errors.New("x")')
        (root / "logs" / "PROBE-LEDGER.txt").write_text(
            "2026-01-01T00:00:00  pid=1  label=t-a  spec=treated.yaml VERDICT=LONG\n"
            "2026-01-01T00:00:01  pid=2  label=t-b  spec=treated.yaml VERDICT=LONG\n")
        try:
            build(root, "t-", "specs/base.yaml")
            chk("two pids refuse", False)
        except Refuse as e:
            chk("pid refusal says confound", "confound" in str(e))

    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficientFunds = errors.New("x")')
        (root / "logs" / "PROBE-LEDGER.txt").write_text(
            "2026-01-01T00:00:00  pid=1  label=t-a  spec=treated.yaml VERDICT=LONG\n"
            "2026-01-01T00:00:01  pid=1  label=t-a  spec=base.yaml VERDICT=ABSENT\n")
        try:
            build(root, "t-", "specs/base.yaml")
            chk("duplicate label refuses", False)
        except Refuse:
            pass

    # the narrowing itself: same prefix, two pids, --pid picks exactly one series
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficientFunds = errors.New("x")')
        (root / "logs" / "PROBE-LEDGER.txt").write_text(
            "2026-01-01T00:00:00  pid=1  label=t-a  spec=treated.yaml VERDICT=LONG\n"
            "2026-01-01T00:00:01  pid=2  label=t-a  spec=treated.yaml VERDICT=LONG\n")
        rows = build(root, "t-", "specs/base.yaml", pid="1")
        chk("--pid narrows to one series", len(rows) == 1 and rows[0]["pid"] == "1")
        try:
            build(root, "t-", "specs/base.yaml", pid="9")
            chk("--pid with no rows refuses", False)
        except Refuse as e:
            chk("empty --pid refusal names the pid", "pid 9" in str(e))

    # a spec that edits a DIFFERENT purpose must be marked, not silently shown as +0
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp, "LONG", 'ErrInsufficientFunds = errors.New("x")')
        (root / "specs" / "treated.yaml").write_text(yaml.safe_dump(
            {"files": [{"path": TARGET, "purpose": "abc"},
                       {"path": "other.go", "purpose": "CHANGED"}]}))
        (root / "specs" / "base.yaml").write_text(yaml.safe_dump(
            {"files": [{"path": TARGET, "purpose": "abc"},
                       {"path": "other.go", "purpose": "original"}]}))
        rows = build(root, "t-", "specs/base.yaml")
        chk("delta at target is 0", rows[0]["delta"] == "+0")
        chk("edit elsewhere is flagged", rows[0]["elsewhere"] is True)
        chk("render marks it", "+0*" in render(rows))
        chk("render explains the marker", "does not mean no edit" in render(rows))

    print("  self-test: OK — agreement enforced across ledger, tree, log and spec; every "
          "disagreement refuses" if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix")
    ap.add_argument("--pid", default="", help="restrict to one server pid; a label prefix is "
                                              "NOT a series identifier (see the docstring)")
    ap.add_argument("--baseline", default="specs/ledger-origorder-baseline.yaml")
    ap.add_argument("--target", default=TARGET)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        raise SystemExit(self_test())
    if not a.prefix:
        raise SystemExit(__doc__)
    try:
        print(render(build(pathlib.Path(__file__).parent, a.prefix, a.baseline, a.target, a.pid)))
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        raise SystemExit(2)
