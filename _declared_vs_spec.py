#!/usr/bin/env python3
"""Which sentinels a spec asks a file to declare, and which of them the draw actually declared.

    ./_declared_vs_spec.py <spec.yaml> <tree-or-models.go> [--path internal/models/models.go]
    ./_declared_vs_spec.py --self-test

WHY IT EXISTS AND WHY IT EXISTS *NOW*, BEFORE THE ARMS ARE DRAWN. `_sentinel_verdict.py` answers
one question — which insufficient-funds name did this file declare — because that was the only
name under test in August. The job-strip experiment's endpoint is a DIFFERENT name (ErrExists),
and the failure mode it predicts includes renaming (ErrAlreadyExists, ErrDuplicate), which a
name-specific classifier cannot see. An endpoint tool written after the data exists is a summary,
not an endpoint; P2 was invalidated for exactly that on 5 August.

⚠️ EXTRA declarations are reported, not ignored. "Declared something else instead" and "declared
nothing" are different results and the prereg distinguishes them.

⚠️ IT CERTIFIES NOTHING ABOUT PROVENANCE. It cannot see the build log, so it cannot tell a draw
from a repaired tree. The CALLER establishes as-drawn status — _probe_process_sentinel.sh greps
the log for repair lines and voids the probe if any appear. This tool grades bytes; reading a
post-repair tree as a draw is the error class behind three retractions and it is the caller's
job to prevent it here.
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from builder import top_level_decls  # noqa: E402

ERR_TOKEN = re.compile(r"\bErr[A-Z][A-Za-z0-9]*\b")
DEFAULT_PATH = "internal/models/models.go"


def asked_of(spec: dict, path: str) -> list[str]:
    """The sentinel names that file's OWN purpose mentions, in the order the purpose says them.

    Order is kept because list position is one of the properties the campaign cannot yet
    separate from length, and a set would throw it away silently.
    """
    for f in spec.get("files") or []:
        if f.get("path") == path:
            seen, out = set(), []
            for name in ERR_TOKEN.findall(f.get("purpose") or ""):
                if name not in seen:
                    seen.add(name)
                    out.append(name)
            return out
    raise KeyError(f"spec has no file at {path!r}")


def grade(asked: list[str], code: str) -> dict:
    declared = {d for d in top_level_decls(code) if d.startswith("Err")}
    return {
        "asked": asked,
        "declared": sorted(declared),
        "present": [n for n in asked if n in declared],
        "missing": [n for n in asked if n not in declared],
        "extra": sorted(declared - set(asked)),
    }


def report(spec_path: str, target: str, path: str) -> int:
    import yaml

    spec = yaml.safe_load(pathlib.Path(spec_path).read_text())
    t = pathlib.Path(target)
    code_file = t / path if t.is_dir() else t
    if not code_file.is_file():
        print(f"REFUSING: no file at {code_file}")
        return 2

    g = grade(asked_of(spec, path), code_file.read_text())
    print(f"  spec   : {spec_path}")
    print(f"  file   : {code_file}")
    print(f"  asked  : {', '.join(g['asked']) or '(none)'}")
    print(f"  present: {', '.join(g['present']) or '(none)'}")
    print(f"  MISSING: {', '.join(g['missing']) or '(none)'}")
    print(f"  EXTRA  : {', '.join(g['extra']) or '(none)'}")
    return 1 if g["missing"] or g["extra"] else 0


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  ok   {name}")

    spec = {"files": [
        {"path": "a.go", "purpose": "irrelevant"},
        {"path": DEFAULT_PATH, "purpose": "Sentinel errors: ErrInvalid, ErrNotFound, ErrExists. "
                                          "Validate wraps ErrInvalid."},
    ]}
    chk("asked, in order, deduped", asked_of(spec, DEFAULT_PATH),
        ["ErrInvalid", "ErrNotFound", "ErrExists"])

    grouped = ('package models\n\nvar (\n\tErrInvalid = errors.New("invalid")\n'
               '\tErrNotFound = errors.New("not found")\n\tErrExists = errors.New("exists")\n)\n')
    g = grade(asked_of(spec, DEFAULT_PATH), grouped)
    chk("all three found in a grouped block", (g["missing"], g["extra"]), ([], []))

    dropped = grouped.replace('\tErrExists = errors.New("exists")\n', "")
    chk("a dropped name is MISSING", grade(asked_of(spec, DEFAULT_PATH), dropped)["missing"],
        ["ErrExists"])

    renamed = grouped.replace("ErrExists", "ErrAlreadyExists")
    g2 = grade(asked_of(spec, DEFAULT_PATH), renamed)
    chk("a RENAME is missing AND extra, not silently ok",
        (g2["missing"], g2["extra"]), (["ErrExists"], ["ErrAlreadyExists"]))

    single = 'package models\n\nvar ErrInvalid = errors.New("x")\n'
    chk("ungrouped single var is seen too",
        grade(["ErrInvalid"], single)["present"], ["ErrInvalid"])

    try:
        asked_of(spec, "nope.go")
        chk("missing path raises", False, True)
    except KeyError:
        chk("missing path raises", True, True)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = DEFAULT_PATH
    if "--path" in sys.argv:
        path = sys.argv[sys.argv.index("--path") + 1]
        args = [a for a in args if a != path]
    if len(args) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(report(args[0], args[1], path))
