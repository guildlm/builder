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


def dead_else_branch(pkg_text: str, code: str, needle: str) -> str | None:
    """An else-branch reached only by an error the callee never returns.

    The shape, seen three times today:

        if err := s.CreateTask(t); err != nil {
            if errors.Is(err, ErrExists) { ...409... } else { ...500... }
        }

    CreateTask returns ErrExists or nil and nothing else, so the else is unreachable and
    mutating its status changes nothing. This is the check the tool used to say it could
    not do; it was done by hand for taskflow's six 500s, and by hand is how it gets
    skipped.
    """
    for m in re.finditer(r"if err :?= ([\w.]+)\.(\w+)\(", code):
        method = m.group(2)
        # BOUND THE WINDOW TO THE STATEMENT. A fixed 900-character tail runs past the end
        # of the if/else and swallows whatever function comes next: it found Content-Type
        # inside writeJSON, three functions below a Delete handler, and declared a closure
        # I had verified CAUGHT to be unreachable. Brace-match instead.
        start = code.find("{", m.end())
        if start < 0:
            continue
        depth, end = 0, len(code)
        for i in range(start, len(code)):
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        tail = code[m.end():end]
        # The needle must be INSIDE the else block. Checking only that it appears
        # somewhere in the tail called the REACHABLE branch dead — the self-test caught
        # that, the third time today a self-test caught a defect in the checker it guards.
        else_at = tail.find("else")
        if else_at < 0 or needle not in tail[else_at:]:
            continue
        handled = set(re.findall(r"errors\.Is\(err,\s*(\w+)\)", tail))
        if not handled:
            continue
        body = re.search(rf"func \([^)]*\) {method}\([^)]*\)[^{{]*{{(.*?)\n}}",
                         pkg_text, re.S)
        if not body:
            continue
        returns = set(re.findall(r"return (?:\w+, )?(Err\w+)", body.group(1)))
        if returns and returns <= handled:
            return (f"{method} returns only {', '.join(sorted(returns))}, all handled by "
                    f"the errors.Is branch — the else carrying {needle} is unreachable")
    return None


def is_tag_shape(code: str, needle: str) -> bool:
    """Is this candidate a JSON struct tag rather than a write?

    Extracted so the decision is pinnable. The reachability checks below model a WRITE —
    a status write, an error branch — and a struct tag is neither: it has exactly one site
    by construction, enforced by the mutation's own uniqueness guard. Running a write-shaped
    check on it produced a NOISE verdict for jsonapi's `echo`, a genuinely undefended wire
    key, because the word appeared twice in the file (once as the tag, once as the field
    being assigned)."""
    return f'json:"{needle}"' in code


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
    # the third check, against the shape it was written for
    pkg = ("func (s *Store) CreateTask(t Task) error {\n\tif _, ok := s.m[t.ID]; ok {\n"
           "\t\treturn ErrExists\n\t}\n\treturn nil\n}\n")
    call = ("if err := s.CreateTask(t); err != nil {\n"
            "\t\tif errors.Is(err, ErrExists) {\n\t\t\twriteError(w, http.StatusConflict, \"x\")\n"
            "\t\t} else {\n\t\t\twriteError(w, http.StatusInternalServerError, \"y\")\n\t\t}\n")
    assert dead_else_branch(pkg, call, "StatusInternalServerError"), "missed a dead else"
    assert dead_else_branch(pkg, call, "StatusConflict") is None, \
        "flagged the REACHABLE branch as dead"
    # A needle far below the if/else must NOT be picked up — the fixed-window version
    # reached into the next function and mislabelled a verified closure.
    trailing = call + "\t}\n}\n\nfunc writeJSON(w http.ResponseWriter) {\n" + \
        "\tw.Header().Set(\"Content-Type\", \"application/json\")\n}\n"
    assert dead_else_branch(pkg, trailing, "Content-Type") is None, \
        "reached past the if/else into the next function"
    wider = pkg.replace("return nil", "return ErrOther")
    assert dead_else_branch(wider, call, "StatusInternalServerError") is None, \
        "called an else dead when the callee returns an unhandled error"
    # The shape guard, pinned: a struct tag is recognised as a tag and an ordinary status
    # write is not, so the write-shaped reachability checks run on exactly one of them.
    tagged = 'type resp struct {\n\tEcho string `json:"echo"`\n}\n'
    if not is_tag_shape(tagged, "echo"):
        print("FAIL: a struct tag is not recognised as a tag — the write-shaped checks would "
              "run on it, which is how jsonapi's echo was called NOISE"); raise SystemExit(1)
    if is_tag_shape('w.WriteHeader(http.StatusOK)\n', "StatusOK"):
        print("FAIL: an ordinary status write is being treated as a tag"); raise SystemExit(1)
    print("OK — spec mentions, dead double-write, dead else-branch; live/branched/reachable not")


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
pkg = "".join(f.read_text(errors="ignore") for f in src.parent.glob("*.go")
              if not f.name.endswith("_test.go"))
# BOTH REACHABILITY CHECKS MODEL A *WRITE* — a status write or an error branch. Handed a
# JSON STRUCT TAG they answer about the wrong thing: asked about jsonapi's `echo`, the
# double-write check found the word twice in the file (the tag, and the field being set) and
# declared the site dead, which reported a genuine undefended wire key as NOISE. A struct tag
# has exactly one site by construction — the mutation's own uniqueness guard enforces that —
# so the honest answer is to say the check does not apply rather than to run it anyway.
tag_shape = is_tag_shape(code, needle)
dead = None if tag_shape else (dead_double_write(code, needle)
                               or dead_else_branch(pkg, code, needle))

print(f"candidate: {spec_name} · {rel} · {needle}\n")
print(f"  1. does the SPEC promise it?  {'yes: ' + ', '.join(mentions) if mentions else 'NO'}")
print(f"  2. can the site take effect?  "
      + ("yes — a struct tag has ONE site; the write-shaped reachability checks do not "
         "apply and were not run" if tag_shape else ('NO — ' + dead if dead else 'yes')))
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
    print("  Two reachability shapes are checked above: a dead double-write, and an\n"
          "  else-branch whose if already handles every error the callee returns.\n"
          "  STILL BY HAND: a guard on an error that cannot occur at all — kvservice's 400\n"
          "  guards io.ReadAll failing, which an httptest body never does, and nothing\n"
          "  here can see that the caller never supplies a failing reader.")
# 0 only when there is work to do on a PROMISE. A spec gap is real work too, so it
# gets its own code rather than being lumped with dead sites.
raise SystemExit(0 if (mentions and not dead) else (2 if not dead else 1))
