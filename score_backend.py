#!/usr/bin/env python3
"""Project-level scorer for a generated Go backend — the REAL GuildLM target.

The 12-task unit benchmark (guild-code crucible) is a cheap gate. The headline
metric is whether a *whole multi-file backend* the Builder produced actually
works. This scores any generated Go project directory objectively with the real
toolchain, and (optionally) by starting the server and probing an endpoint:

    score = builds(1) + vets(1) + tests_pass(1) + server_runs(1)   # 0..4

Use it to compare coders at the level that matters — run the Builder on the same
spec with a general baseline vs a trained Go specialist, then:

    python score_backend.py ./generated/tasks-api-baseline
    python score_backend.py ./generated/tasks-api-go-dev --smoke "POST /tasks {\\"title\\":\\"x\\"}=201"

A coder is better at "writing big backends" iff it earns a higher score here —
not on toy functions. Pure stdlib + the local `go` toolchain; no Docker.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

_ASSERTION_RE = re.compile(r"\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b")


def _trivial_test_files(project: str) -> list[str]:
    """*_test.go files that pass without asserting anything — a green build can
    lie if its tests never call t.Error/t.Fatal/… so we surface them."""
    trivial = []
    for dirpath, _dirs, files in os.walk(project):
        for f in files:
            if not f.endswith("_test.go"):
                continue
            try:
                with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                    code = fh.read()
            except OSError:
                continue
            if "func Test" in code and not _ASSERTION_RE.search(code):
                trivial.append(os.path.relpath(os.path.join(dirpath, f), project))
    return trivial


def _go(args: list[str], cwd: str, timeout: int = 120) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["go", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        return False, "go toolchain not found"
    except subprocess.TimeoutExpired:
        return False, f"`go {' '.join(args)}` timed out"
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _has_main(cwd: str) -> bool:
    ok, out = _go(["list", "-f", "{{.Name}}", "./..."], cwd)
    return ok and "main" in out.split()


def _smoke(cwd: str, spec: str) -> tuple[bool, str]:
    """Build the binary, start it on $PORT, and check one HTTP probe.

    spec form: "METHOD /path [body]=STATUS", e.g. 'GET /tasks=200' or
    'POST /tasks {"title":"x"}=201'.
    """
    import urllib.error
    import urllib.request

    head, _, want_status = spec.rpartition("=")
    method, _, rest = head.strip().partition(" ")
    path, _, body = rest.strip().partition(" ")
    binp = os.path.join(cwd, "_score_bin")
    ok, out = _go(["build", "-o", binp, "."], cwd)
    if not ok:
        return False, f"binary build failed: {out[:200]}"
    port = _free_port()
    proc = subprocess.Popen(
        [binp], cwd=cwd, env=dict(os.environ, PORT=str(port)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        url = f"http://127.0.0.1:{port}{path}"
        last = ""
        for _ in range(20):  # ~2s for the server to bind
            try:
                req = urllib.request.Request(
                    url, method=method.upper(),
                    data=body.encode() if body else None,
                )
                with urllib.request.urlopen(req, timeout=2) as r:
                    code = r.status
                last = str(code)
                if last == want_status.strip():
                    return True, f"{method} {path} -> {code}"
            except urllib.error.HTTPError as e:
                last = str(e.code)
                if last == want_status.strip():
                    return True, f"{method} {path} -> {e.code}"
            except Exception as e:  # not up yet
                last = type(e).__name__
            time.sleep(0.1)
        return False, f"{method} {path} -> {last}, want {want_status.strip()}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(binp):
            os.remove(binp)


def score(project: str, smoke: str | None) -> dict:
    if not os.path.isdir(project):
        raise SystemExit(f"not a directory: {project}")
    if not shutil.which("go"):
        raise SystemExit("go toolchain not found on PATH")

    res: dict = {"project": project, "stages": {}, "score": 0, "max": 4}

    builds, b_out = _go(["build", "./..."], project)
    res["stages"]["build"] = {"ok": builds, "detail": "" if builds else b_out[:300]}

    vets, v_out = _go(["vet", "./..."], project) if builds else (False, "skipped (build failed)")
    res["stages"]["vet"] = {"ok": vets, "detail": "" if vets else v_out[:300]}

    tests, t_out = _go(["test", "./..."], project) if builds else (False, "skipped (build failed)")
    # A green test run that asserts nothing is not real coverage — don't credit it.
    trivial = _trivial_test_files(project) if tests else []
    if trivial:
        tests = False
        t_out = f"tests pass but assert nothing (trivial): {', '.join(trivial)}"
    res["stages"]["test"] = {"ok": tests, "detail": t_out[:300]}

    res["score"] = int(builds) + int(vets) + int(tests)

    if smoke and builds and _has_main(project):
        ran, s_out = _smoke(project, smoke)
        res["stages"]["server"] = {"ok": ran, "detail": s_out}
        res["score"] += int(ran)
    else:
        res["max"] = 3  # no runnable server requested / present

    return res


_FIXTURES = {
    # name: (files, expected stage verdicts, expected score)
    "green": (
        {"go.mod": "module example.com/x\n\ngo 1.23\n",
         "lib.go": "package x\n\nfunc Add(a, b int) int { return a + b }\n",
         "lib_test.go": "package x\n\nimport \"testing\"\n\n"
                        "func TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n"
                        "\t\tt.Fatalf(\"boom\")\n\t}\n}\n"},
        {"build": True, "vet": True, "test": True}, 3),
    "does not build": (
        {"go.mod": "module example.com/x\n\ngo 1.23\n",
         "lib.go": "package x\n\nfunc Add(a, b int) int { return a + }\n"},
        {"build": False, "vet": False, "test": False}, 0),
    "test asserts nothing": (
        {"go.mod": "module example.com/x\n\ngo 1.23\n",
         "lib.go": "package x\n\nfunc Add(a, b int) int { return a + b }\n",
         "lib_test.go": "package x\n\nimport \"testing\"\n\n"
                        "func TestAdd(t *testing.T) {\n\t_ = Add(1, 2)\n}\n"},
        {"build": True, "vet": True, "test": False}, 2),
    "test genuinely fails": (
        {"go.mod": "module example.com/x\n\ngo 1.23\n",
         "lib.go": "package x\n\nfunc Add(a, b int) int { return a - b }\n",
         "lib_test.go": "package x\n\nimport \"testing\"\n\n"
                        "func TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n"
                        "\t\tt.Fatalf(\"boom\")\n\t}\n}\n"},
        {"build": True, "vet": True, "test": False}, 2),
}


def self_test() -> int:
    """Prove the scorer separates the four outcomes it exists to separate.

    This tool produces every A/B number in the project — routing wins, recipe
    comparisons, regression sweeps all quote it — and until now nothing checked that it
    can tell them apart. A scorer that quietly credits a build that does not build, or a
    test suite that asserts nothing, does not fail loudly; it publishes a number, and the
    number goes into a finding.

    Four planted projects, real `go`, no model. The third is the one worth having: a suite
    that passes while asserting nothing is the exact way a green score can be a lie, and
    it is why the demotion exists.
    """
    import tempfile

    failures = []
    for name, (files, want_stages, want_score) in _FIXTURES.items():
        with tempfile.TemporaryDirectory() as tmp:
            for fname, content in files.items():
                with open(os.path.join(tmp, fname), "w", encoding="utf-8") as fh:
                    fh.write(content)
            got = score(tmp, None)
        for stage, want in want_stages.items():
            actual = got["stages"].get(stage, {}).get("ok")
            if actual != want:
                failures.append(f"[{name}] stage {stage}: got {actual}, want {want}")
        if got["score"] != want_score:
            failures.append(f"[{name}] score: got {got['score']}, want {want_score}")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — green scores 3, a broken build scores 0, and a suite that asserts "
          "nothing is not credited")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", nargs="?",
                    help="path to a generated Go project directory")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the scorer separates green / no-build / vacuous-tests / "
                         "failing-tests, using real go and no model")
    ap.add_argument("--smoke", help='HTTP probe, e.g. "GET /tasks=200" or "POST /tasks {\\"title\\":\\"x\\"}=201"')
    ap.add_argument("--json", action="store_true", help="emit raw JSON only")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.project:
        ap.error("need a project directory (or --self-test)")

    res = score(args.project, args.smoke)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        for name, st in res["stages"].items():
            mark = "✓" if st["ok"] else "✗"
            line = f"  {mark} {name}"
            if not st["ok"] and st["detail"]:
                line += f"  — {st['detail'].splitlines()[0][:120]}"
            elif st["ok"] and st.get("detail"):
                line += f"  — {st['detail'][:80]}"
            print(line)
        print(f"\nscore: {res['score']}/{res['max']}  ({os.path.basename(res['project'].rstrip('/'))})")
    return 0 if res["score"] == res["max"] else 1


if __name__ == "__main__":
    sys.exit(main())
