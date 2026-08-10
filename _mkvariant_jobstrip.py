#!/usr/bin/env python3
"""Build the two arms of the job-strip experiment from the baseline ledger spec.

    ./_mkvariant_jobstrip.py            # writes specs/ledger-jobstrip.yaml and -placebo.yaml
    ./_mkvariant_jobstrip.py --self-test

THE EXPERIMENT. 10 August's census found that of 17 sentinels the specs ask for, sixteen have a
described USE SITE and are declared in every archived tree; the seventeenth has none and is
declared 9 of 27. That seventeenth is ErrInsufficientFunds — the identifier the whole corpus
defect localises to. But "has no use site" is one more property unique to ONE name, exactly as
untestable on the archive as "is the longest".

Unless you take the job away from a DIFFERENT name. That is what this builds:

  JOBSTRIP   ErrExists (9 chars, declared 27/27) is stripped down to ErrInsufficientFunds'
             exact profile — listed in models.go's purpose, mapped in response.go's purpose,
             DEMANDED NOWHERE. The behaviour stays: the store still rejects a duplicate ID and
             the test still checks it; only the NAME's job is removed.
  PLACEBO    the same two purposes are edited by a comparable amount, touching no sentinel at
             all — so that "editing store purposes perturbs models.go" cannot be mistaken for
             the effect.

⚠️⚠️ MODELS.GO'S OWN PURPOSE IS NOT TOUCHED BY EITHER ARM, and that is the point of choosing
ErrExists over ErrUnbalanced: ErrUnbalanced's use sites live in models.go's own purpose, so
stripping it would rewrite the target file's own prompt. ErrExists' use sites are all in
internal/store purposes, which reach models.go only through the rendered file list.

⚠️ THE PARAPHRASE MUST NOT PLANT A NAME. The first draft said "the models package's already-
exists sentinel", which is a suggestion of `ErrAlreadyExists` — and the endpoint scores a RENAME
as degradation, so the arm would have manufactured its own positive result. Every paraphrase here
refers to the sentinel by its ROLE with no adjective a name could be read off ("the matching
models sentinel", "the same sentinel CreateAccount returns in that case"). A self-test asserts no
arm introduces any Err* token the baseline does not have.

⚠️ REPLACEMENTS ARE ASSERTED UNIQUE. A substitution that silently matched twice, or zero times,
would produce a spec that looks right and differs somewhere unintended — and the guard downstream
only checks WHICH purposes differ, not whether the intended edit landed.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
JOBSTRIP = HERE / "specs" / "ledger-jobstrip.yaml"
PLACEBO = HERE / "specs" / "ledger-jobstrip-placebo.yaml"

# --- arm 1: take ErrExists' job away, keep the behaviour -------------------------------------
# Every mention removed here is a DEMAND (a clause saying some function returns/asserts it).
# The two LISTED mentions — models.go's sentinel list and response.go's 409 mapping — are kept,
# because those are exactly what ErrInsufficientFunds has and this arm reproduces its profile.
STRIP = [
    (
        "      models package (models.ErrExists, models.ErrNotFound), returned DIRECTLY —\n",
        "      models package (models.ErrNotFound is one of the two), returned DIRECTLY —\n",
    ),
    (
        "      CreateAccount returns models.ErrExists on a duplicate ID and initialises that\n"
        "      account's balance to money.Money(0). GetAccount returns models.ErrNotFound.\n",
        "      CreateAccount returns the matching models sentinel on a duplicate ID and\n"
        "      initialises that account's balance to money.Money(0). GetAccount returns\n"
        "      models.ErrNotFound.\n",
    ),
    (
        "      TestCreateAccountDuplicate: create the same ID twice -> errors.Is ErrExists.\n",
        "      TestCreateAccountDuplicate: create the same ID twice -> the same sentinel\n"
        "      CreateAccount returns in that case, checked with errors.Is.\n",
    ),
]

# --- arm 2: edit the same two purposes by a comparable amount, naming no sentinel -------------
PLACEBO_EDITS = [
    (
        "      ListAccounts and ListTransactions return their items sorted by ID, and\n"
        "      NEVER return nil — an empty ledger returns an EMPTY, NON-NIL slice.\n",
        "      ListAccounts and ListTransactions return the items they hold sorted by ID, and\n"
        "      NEVER return nil — an empty ledger returns an EMPTY, NON-NIL slice that is safe\n"
        "      to range over.\n",
    ),
    (
        "      Balances returns a COPY of the map, never the live one.\n",
        "      Balances returns a COPY of the map it holds, never the live one itself.\n",
    ),
    (
        '      TestListAccountsSorted: create "b" then "a"; ListAccounts returns them in\n'
        "      the order a, b.\n",
        '      TestListAccountsSorted: create "b" then "a"; ListAccounts hands them back in\n'
        "      the order a, b, smallest ID first.\n",
    ),
]


def apply_once(text: str, edits: list[tuple[str, str]], label: str) -> str:
    for old, new in edits:
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"REFUSING [{label}]: pattern occurs {n} times, expected 1:\n{old}")
        text = text.replace(old, new)
    return text


# --- the unbundling: each of the three removed mentions, ALONE -------------------------------
# The jobstrip arm removed three ErrExists mentions at once and flipped models.go from 3a78b0d8
# to ef8c15d6 (logs/RESULT-the-job-hypothesis-failed-its-own-prediction-...). Which one did it is
# unknown, and a three-part treatment whose parts are never separated is a recipe, not a finding.
# Same protocol as 6 August, where a three-part spec treatment reduced to ONE sufficient part.
SUBARMS = {
    "a": ([STRIP[0]], ["internal/store/memory.go"]),        # the parenthetical enumeration
    "b": ([STRIP[1]], ["internal/store/memory.go"]),        # CreateAccount's return clause
    "c": ([STRIP[2]], ["internal/store/memory_test.go"]),   # the test's assertion
    # ⚠️ THE PAIRS ARE NOT AN AFTERTHOUGHT, THEY ARE WHERE THE ANSWER MUST BE. On pid 60986 all
    # three singles left models.go byte-identical to baseline while the bundle flipped it twice.
    # So the effect is not carried by any one mention, and "three mentions" is not an answer —
    # a threshold at two and a genuine three-way conjunction are different claims.
    "ab": ([STRIP[0], STRIP[1]], ["internal/store/memory.go"]),
    "ac": ([STRIP[0], STRIP[2]], ["internal/store/memory.go", "internal/store/memory_test.go"]),
    "bc": ([STRIP[1], STRIP[2]], ["internal/store/memory.go", "internal/store/memory_test.go"]),
}


def build() -> int:
    base = BASE.read_text()
    for key, (edits, _) in SUBARMS.items():
        out = apply_once(base, edits, f"jobstrip-{key}")
        p = HERE / "specs" / f"ledger-jobstrip-{key}.yaml"
        p.write_text(out)
        print(f"  wrote {p.name:<32} {len(out):>6} bytes ({len(out) - len(base):+d} vs baseline)")

    for path, edits, label in ((JOBSTRIP, STRIP, "jobstrip"), (PLACEBO, PLACEBO_EDITS, "placebo")):
        out = apply_once(base, edits, label)
        path.write_text(out)
        delta = len(out) - len(base)
        print(f"  wrote {path.name:<32} {len(out):>6} bytes ({delta:+d} vs baseline)")

    # The two arms must perturb the prompt by a COMPARABLE amount, or the placebo is not one.
    d1 = len(JOBSTRIP.read_text()) - len(base)
    d2 = len(PLACEBO.read_text()) - len(base)
    print(f"\n  jobstrip {d1:+d} chars · placebo {d2:+d} chars · "
          f"difference {abs(d1 - d2)} — comparable is the claim, and it is printed, not assumed")
    return 0


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  ok   {name}")

    chk("apply_once substitutes", apply_once("a b a", [("b", "c")], "t"), "a c a")
    for bad, why in ((["a"], "twice"), (["z"], "never")):
        try:
            apply_once("a b a", [(bad[0], "x")], "t")
            chk(f"refuses a pattern matching {why}", False, True)
        except SystemExit:
            chk(f"refuses a pattern matching {why}", True, True)

    base = BASE.read_text()
    strip = apply_once(base, STRIP, "jobstrip")
    placebo = apply_once(base, PLACEBO_EDITS, "placebo")

    chk("baseline mentions ErrExists 5 times", base.count("ErrExists"), 5)
    chk("jobstrip keeps exactly the two LISTED mentions", strip.count("ErrExists"), 2)
    chk("placebo touches no ErrExists mention", placebo.count("ErrExists"), 5)

    for name in ("ErrInvalid", "ErrNotFound", "ErrUnbalanced", "ErrInsufficientFunds"):
        chk(f"{name} is untouched by jobstrip", strip.count(name), base.count(name))
        chk(f"{name} is untouched by placebo", placebo.count(name), base.count(name))

    # ⚠️ no arm may introduce an Err* token the baseline does not have — a paraphrase that
    # suggests a name would manufacture the RENAME the endpoint is watching for
    import re as _re

    tokens = lambda t: set(_re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731
    chk("jobstrip introduces no new Err name", tokens(strip) - tokens(base), set())
    chk("placebo introduces no new Err name", tokens(placebo) - tokens(base), set())

    # models.go's own purpose must be byte-identical in every arm — the whole design rests on it
    import yaml

    def purpose(text: str, path: str) -> str:
        for f in yaml.safe_load(text)["files"]:
            if f["path"] == path:
                return f["purpose"]
        raise KeyError(path)

    for label, text in (("jobstrip", strip), ("placebo", placebo)):
        chk(f"models.go's own purpose is byte-identical under {label}",
            purpose(text, "internal/models/models.go"),
            purpose(base, "internal/models/models.go"))
        chk(f"response.go's 409 mapping survives {label}",
            "ErrExists -> 409" in purpose(text, "internal/api/response.go"), True)

    # and the strip must actually remove the DEMANDS, measured by the census classifier
    sys.path.insert(0, str(HERE))
    from _sentinel_mention_census import mentions  # noqa: E402

    chk("baseline ErrExists has use sites", mentions(yaml.safe_load(base))["ErrExists"].demanded, 3)
    chk("jobstrip ErrExists has NONE", mentions(yaml.safe_load(strip))["ErrExists"].demanded, 0)
    chk("jobstrip ErrExists profile matches the failing name",
        mentions(yaml.safe_load(strip))["ErrExists"].demanded,
        mentions(yaml.safe_load(base))["ErrInsufficientFunds"].demanded)
    chk("placebo ErrExists keeps its use sites",
        mentions(yaml.safe_load(placebo))["ErrExists"].demanded, 3)

    # --- the sub-arms: each removes exactly ONE mention, and together they equal the bundle ----
    subs = {k: apply_once(base, edits, f"sub-{k}") for k, (edits, _) in SUBARMS.items()}
    for k, text in subs.items():
        chk(f"sub-arm {k} removes exactly {len(k)} ErrExists mention(s)",
            text.count("ErrExists"), 5 - len(k))
        chk(f"sub-arm {k} introduces no new Err name", tokens(text) - tokens(base), set())
        chk(f"sub-arm {k} leaves models.go's purpose byte-identical",
            purpose(text, "internal/models/models.go"),
            purpose(base, "internal/models/models.go"))
    chk("every sub-arm is distinct", len({*subs.values()}), len(SUBARMS))
    chk("a pair is not the bundle", subs["ab"] == strip, False)
    chk("applying all three in sequence reproduces the bundle exactly",
        apply_once(apply_once(apply_once(base, [STRIP[0]], "x"), [STRIP[1]], "y"),
                   [STRIP[2]], "z"), strip)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
