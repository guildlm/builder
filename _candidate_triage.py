"""Is this SURVIVED row a HOLE, or is it noise? Two cheap checks before a 20-minute run.

A SURVIVED row means a mutation changed behaviour and the suite stayed green. That is a
CANDIDATE, not a hole. Twice today a candidate turned out to be neither:

    ratelimit 429   a DEAD DOUBLE-WRITE — the status is written twice and the second
                    never reaches the response, so mutating it changes nothing observable
    kvservice 400   NO PROMISE — the spec never mentions 400; the branch is the model's
                    own guard on io.ReadAll failing, which does not happen for an
                    httptest request body

Each was ruled out by one grep, and between them they saved two regeneration runs of
roughly twenty minutes. Doing it by hand worked until the time I forgot and paid 94
seconds for a closure aimed at a promise that was already defended.

    python _candidate_triage.py <artifact-dir> <spec-name> <file.go> <needle>
    python _candidate_triage.py --self-test
"""
import pathlib, re, sys

# What to grep the spec for, given a Go constant. A spec says "400", not
# "http.StatusBadRequest".
CODE_WORDS = {
    "StatusBadRequest": ["400", "bad request", "badrequest"],
    "StatusNotFound": ["404", "not found", "notfound"],
    "StatusConflict": ["409", "conflict"],
    "StatusOK": ["200", " ok"],
    "StatusCreated": ["201", "created"],
    "StatusNoContent": ["204", "no content"],
    "StatusTooManyRequests": ["429", "too many", "rate limit"],
    "StatusInternalServerError": ["500", "internal server"],
    "StatusMovedPermanently": ["301", "moved"],
    "Content-Type": ["content-type"],
}


def spec_mentions(spec_text: str, needle: str) -> list[str]:
    """Which spec phrasings of `needle` appear. Empty means the spec never asks for it."""
    low = spec_text.lower()
    return [w for w in CODE_WORDS.get(needle, [needle.lower()]) if w.lower() in low]


def dead_double_write(code: str, needle: str) -> str | None:
    """A second write of the same thing that cannot take effect.

    Go's http.ResponseWriter ignores a status set after WriteHeader and a header set after
    it. So two writes of `needle` with a WriteHeader between them means the second is dead
    and mutating it is unobservable — the ratelimit 429 case exactly.
    """
    hits = [i for i, l in enumerate(code.splitlines()) if needle in l]
    if len(hits) < 2:
        return None
    lines = code.splitlines()
    def depth_at(i):
        return sum(l.count("{") - l.count("}") for l in lines[:i + 1])

    for a, b in zip(hits, hits[1:]):
        # SAME PATH ONLY. Two writes in mutually exclusive if-branches are both live, and
        # the inclusive rule below flagged them as a dead pair — the self-test caught that
        # the moment the rule was widened. If the block containing the first write CLOSES
        # before the second, they are on different paths and neither kills the other.
        if min(depth_at(i) for i in range(a, b)) < depth_at(a):
            continue
        # INCLUSIVE of the first hit: the commit that kills the second write is usually the
        # FIRST write itself — `w.WriteHeader(429)` writes the status AND closes the
        # header. Looking only BETWEEN them missed exactly the shape this was written for.
        region = "\n".join(lines[a:b])
        if "WriteHeader" in region or "http.Error" in region:
            return (f"lines {a+1} and {b+1} both write {needle}, with a WriteHeader/Error "
                    f"between them — the second cannot take effect")
    return None


def self_test():
    spec = "Create validates the body and returns 400 on a blank title."
    assert spec_mentions(spec, "StatusBadRequest") == ["400"]
    assert spec_mentions(spec, "StatusConflict") == [], "found a code the spec never names"
    dead = ('w.WriteHeader(http.StatusTooManyRequests)\n'
            'w.Write(body)\n'
            'w.WriteHeader(http.StatusTooManyRequests)\n')
    assert dead_double_write(dead, "StatusTooManyRequests"), "missed a dead double-write"
    live = 'w.Header().Set("Content-Type", "application/json")\nw.WriteHeader(status)\n'
    assert dead_double_write(live, "Content-Type") is None, "flagged a single live write"
    two_live = ('if a {\n\tw.WriteHeader(http.StatusOK)\n}\nif b {\n'
                '\tw.WriteHeader(http.StatusOK)\n}\n')
    assert dead_double_write(two_live, "StatusOK") is None, \
        "flagged two writes on separate branches"
    # the three-way split must hold: dead beats unpromised, unpromised-but-live is a gap
    assert spec_mentions("no codes here", "StatusOK") == []
    print("OK — spec mentions detected, dead double-write flagged, live and branched writes not")


if "--self-test" in sys.argv:
    self_test(); raise SystemExit

args = [a for a in sys.argv[1:] if not a.startswith("-")]
if len(args) != 4:
    raise SystemExit(__doc__)
art, spec_name, rel, needle = args
art_p, spec_p = pathlib.Path(art), pathlib.Path("specs") / f"{spec_name}.yaml"
if not art_p.is_dir():
    raise SystemExit(f"{art} is not a directory")
if not spec_p.exists():
    raise SystemExit(f"no spec {spec_p}")
src = art_p / rel
if not src.exists():
    raise SystemExit(f"{rel} is not in {art}")

code = src.read_text(errors="ignore")
mentions = spec_mentions(spec_p.read_text(), needle)
dead = dead_double_write(code, needle)

print(f"candidate: {spec_name} · {rel} · {needle}\n")
print(f"  1. does the SPEC promise it?  {'yes: ' + ', '.join(mentions) if mentions else 'NO'}")
print(f"  2. dead double-write?         {dead or 'no'}")
# "Unpromised" is not one verdict but two, and collapsing them mislabels the most
# actionable case. kvservice's 400 is unpromised AND unreachable — noise. tasks-api's
# Content-Type is unpromised but LIVE: the API really does set it and the spec really
# does not say so, which is a SPEC GAP and is exactly what the five Content-Type
# closures today were. Calling that "noise" would have told me to skip the very work
# that produced them.
verdict = ("NOISE — the site cannot take effect" if dead else
           "SPEC GAP — the behaviour is real and live, and the spec never asks for it. "
           "Same shape as today's Content-Type closures: name it in the spec."
           if not mentions else
           "CANDIDATE STANDS — spec promises it and the site is live")
print(f"\n  {verdict}")
if not dead:
    # The reachability question applies to BOTH remaining verdicts, not just to promises.
    # kvservice's 400 now reads SPEC GAP, and by hand it is unpromised AND unreachable —
    # its branch guards io.ReadAll failing, which an httptest body never does. Writing a
    # spec sentence for a branch that cannot execute buys nothing, so the gap verdict
    # needs the same caveat the promise verdict needed.
    print("  Still to check by hand: is the branch REACHABLE? An else-branch whose if\n"
          "  already handles the only error the callee returns is dead, and so is a guard\n"
          "  on an error that cannot occur — no grep sees either. It is how taskflow's six\n"
          "  500s and kvservice's 400 were both ruled out.")
# 0 only when there is work to do on a PROMISE. A spec gap is real work too, so it
# gets its own code rather than being lumped with dead sites.
raise SystemExit(0 if (mentions and not dead) else (2 if not dead else 1))
