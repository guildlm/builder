#!/usr/bin/env python3
"""Structural twins should make the same calls. Which twin is missing one?

Eight of the twenty-one holes confirmed on 2026-07-27 are MIRRORS: a guard whose identical
twin on a neighbouring route has a test and it does not. tasks-api's invalid-id 400 on Get,
Update and Delete; shortener's 404 from Stats beside Redirect's; taskflow's 404 from Delete
beside Get's. The shape is always the same — one resource, one route or one handler gets the
treatment, and its structural twin quietly does not.

This asks the same question of the CODE rather than the tests, and it is a PRE-TEST check:
it needs no `go test`, no mutation and no model.

    tasks_handler.go     t.Validate()   ...
    projects_handler.go  (nothing)      ...

Found live: taskflow's six-hour closure run produced a projects_handler that had lost its
Project.Validate call entirely. The suite caught it — TestProjectCreateInvalid went red —
but only after generation, eight fix rounds and six hours. This flags it from the source in
milliseconds.

    python _mirror_calls_audit.py [artifact ...]   # default: every -v4 artifact
    python _mirror_calls_audit.py --self-test

WHY THE RESOURCE FILTER IS THE WHOLE TRICK
  Twins differ on purpose: tasks_handler calls CreateTask, projects_handler calls
  CreateProject. Reporting those is reporting the design. So call names are normalised by
  removing the resource token each FILE is named for, which cancels the intended differences
  and leaves the unintended ones. On taskflow-v4 (green) that reduces a 8-name diff to ZERO;
  on the regressed tree it leaves exactly `Validate`.

WHAT IT DOES NOT CLAIM
  An asymmetry is a CANDIDATE. Two twins may legitimately differ — one resource may have a
  field the other lacks, and taskflow's own trees differ in JSON decode style
  (json.NewDecoder on one side, a shared helper on the other) with both correct. It prints
  the names and the direction; the reading takes seconds.
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys
import tempfile

CALL = re.compile(r"\.([A-Z]\w*)\(")
# The resource words this corpus names files after. Longest first so "projects" is stripped
# before "project" and the singular does not leave a stray "s".
RESOURCES = ["projects", "project", "tasks", "task", "users", "user", "links", "link",
             "events", "event", "items", "item", "accounts", "account", "orders", "order"]


def resource_of(stem: str) -> str | None:
    """Which resource is this file named for, if any?"""
    low = stem.lower()
    for r in RESOURCES:
        if r in low:
            return r
    return None


def normalise(name: str, res: str) -> str:
    """Cancel the resource token so CreateTask and CreateProject compare equal.

    BOTH forms, plural first. The file is named `tasks_handler.go`, so the resource comes
    back as "tasks" — and the method is `CreateTask`, singular. Stripping only the form the
    FILE happens to use cancels nothing, every twin looks asymmetric, and the audit reports
    the design instead of the defect. Caught by the self-test on the first run, which is the
    entire reason the symmetric fixture is in there.
    """
    singular = res[:-1] if res.endswith("s") else res
    out = re.sub(re.escape(singular + "s"), "", name, flags=re.I)
    out = re.sub(re.escape(singular), "", out, flags=re.I)
    return out or name


def twin_pairs(art: pathlib.Path):
    """Files in the same directory that are the same thing for different resources."""
    by_dir = collections.defaultdict(list)
    for f in sorted(art.rglob("*.go")):
        if f.name.endswith("_test.go"):
            continue
        res = resource_of(f.stem)
        if res:
            by_dir[(f.parent, re.sub(re.escape(res), "", f.stem, flags=re.I))].append((f, res))
    out = []
    for (_, _shape), fs in sorted(by_dir.items()):
        for i, (a, ra) in enumerate(fs):
            for b, rb in fs[i + 1:]:
                if ra != rb:
                    out.append((a, ra, b, rb))
    return out


def asymmetries(a: pathlib.Path, ra: str, b: pathlib.Path, rb: str):
    """Calls present in one twin and absent from the other, resource names cancelled."""
    na = {normalise(c, ra) for c in CALL.findall(a.read_text(errors="ignore"))}
    nb = {normalise(c, rb) for c in CALL.findall(b.read_text(errors="ignore"))}
    return sorted(na - nb), sorted(nb - na)


def audit(arts) -> int:
    findings = 0
    pairs = 0
    for art in arts:
        for a, ra, b, rb in twin_pairs(art):
            pairs += 1
            only_a, only_b = asymmetries(a, ra, b, rb)
            if not (only_a or only_b):
                continue
            findings += 1
            print(f"{art.name}  {a.name} vs {b.name}")
            if only_a:
                print(f"    only {a.name} calls: {', '.join(only_a)}")
            if only_b:
                print(f"    only {b.name} calls: {', '.join(only_b)}")
    if pairs == 0:
        raise SystemExit("NO TWIN PAIRS FOUND — nothing was compared, which is not a clean "
                         "report. Check the artifact list.")
    print(f"\n{findings} asymmetric pair(s) of {pairs} compared")
    if findings:
        print("An asymmetry is a CANDIDATE: twins may differ for real reasons (a field one\n"
              "resource has and the other does not, a different decode style). Read the\n"
              "names — a missing Validate is not a style difference.")
    return 0


_HANDLER = """package main

import "net/http"

func Create%(R)s(w http.ResponseWriter, r *http.Request) {
	var x %(R)s
	%(VALIDATE)s
	store.Create%(R)s(x)
	w.WriteHeader(http.StatusCreated)
}
"""


def self_test() -> int:
    """A symmetric pair must be CLEAN; a pair missing one call must be FLAGGED.

    The clean case is the one that matters. A twin audit that reports the intended
    differences — CreateTask against CreateProject — flags every pair in the corpus and is
    worth nothing, which is what the first prototype did before the resource filter existed.
    """
    failures = []
    for label, validate_b, want in (("symmetric", "if err := x.Validate(); err != nil { return }", 0),
                                    ("one twin dropped Validate", "", 1)):
        with tempfile.TemporaryDirectory() as td:
            art = pathlib.Path(td) / "art"
            art.mkdir()
            (art / "tasks_handler.go").write_text(
                _HANDLER % {"R": "Task", "VALIDATE": "if err := x.Validate(); err != nil { return }"})
            (art / "projects_handler.go").write_text(
                _HANDLER % {"R": "Project", "VALIDATE": validate_b})
            pairs = twin_pairs(art)
            if len(pairs) != 1:
                failures.append(f"{label}: expected 1 twin pair, got {len(pairs)}")
                continue
            a, ra, b, rb = pairs[0]
            only_a, only_b = asymmetries(a, ra, b, rb)
            got = len(only_a) + len(only_b)
            if got != want:
                failures.append(f"{label}: expected {want} asymmetric call(s), got {got} "
                                f"({only_a} / {only_b})")
    # And the filter itself: the intended difference must cancel.
    if normalise("CreateTask", "task") != normalise("CreateProject", "project"):
        failures.append("CreateTask and CreateProject must normalise to the same name")
    if normalise("ListTasks", "task") != normalise("ListProjects", "project"):
        failures.append("ListTasks and ListProjects must normalise to the same name")
    if normalise("Validate", "task") != "Validate":
        failures.append("a name with no resource token must be left alone")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — twins that make the same calls are clean, a twin missing one is flagged,\n"
          "     and the intended resource differences cancel instead of being reported")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    targets = [a for a in sys.argv[1:] if not a.startswith("-")]
    if targets:
        dirs = [pathlib.Path(t) for t in targets]
        for d in dirs:
            if not d.is_dir():
                raise SystemExit(f"{d} is not a directory")
    else:
        dirs = sorted(pathlib.Path("generated").glob("*-v4"))
        if not dirs:
            raise SystemExit("no -v4 artifacts found — nothing was compared")
    # A HALF-WRITTEN TREE IS ALL ASYMMETRY. Generation writes file by file, so a tree caught
    # with tasks_handler.go on disk and projects_handler.go still to come reports every call
    # in the first file as missing from the second — a page of findings about an artifact
    # nobody finished.
    from _corpus_state import check as _corpus_check
    if any(_corpus_check(d) == "refuse" for d in dirs):
        raise SystemExit(2)
    raise SystemExit(audit(dirs))
