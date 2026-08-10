#!/usr/bin/env python3
"""How many times does a spec MENTION each sentinel, and how often is it declared?

    ./_sentinel_mention_census.py                  # every spec, every Err name, joined to rates
    ./_sentinel_mention_census.py ledger           # one project
    ./_sentinel_mention_census.py --self-test

THE QUESTION IT ANSWERS. 31 July localised the whole corpus defect to ONE identifier
(ErrInsufficientFunds, 9/25, against five siblings at 100%) and listed four properties unique to
it — longest, only two-concept compound, only one with a plausible shorter form, only one whose
domain has its own package — and refused to choose between them, because with n=1 they are the
same observation wearing four labels.

This measures a FIFTH property that nobody had counted: how many times the spec says the name at
all. In the ledger spec the failing name is mentioned TWICE and the five that never fail are
mentioned five to ten times. That property is different in kind from the other four, because it
is GRADED and it varies ACROSS SPECS — so unlike "is the longest", it can be refuted by the
archive alone, without a draw: if some other name is also mentioned twice and is still declared
100% of the time, scarcity of mention is not sufficient, and this hypothesis dies for free.

⚠️ MENTIONS ARE COUNTED ON THE LOADED (FOLDED) PURPOSE, NOT THE RAW YAML. Every purpose here is
a folded scalar (`>-`), so the newlines a reader sees are spaces by the time the model sees
anything. Counting raw lines would measure the hard-wrap, which is invisible downstream — the
same trap that made a "re-wrap" look like one of the treatment's ingredients on 6 August, when
folding meant it had never reached the model at all.

⚠️ MENTIONS ARE TOKENS, NOT SUBSTRINGS. `ErrInsufficient` is a prefix of `ErrInsufficientFunds`,
so substring counting would score the abbreviation as an occurrence of the full name and hide
exactly the distinction the campaign turns on.

⚠️⚠️ THE RATE IS POOLED OVER A PROJECT'S SPEC VARIANTS AND THE JOIN REFUSES WHEN THEY DISAGREE.
An archived tree does not record which spec variant drew it, so a per-spec rate cannot be
computed — only a per-PROJECT one. Where a project's specs disagree about how often a name is
mentioned, joining would attach one rate to several different inputs; this prints DISAGREE and
declines rather than picking one. That is the same refusal `_asdrawn_census.py` makes about
reading from disk: a weaker measurement is better stated than silently substituted.
"""

import collections
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from builder import top_level_decls  # noqa: E402

HERE = pathlib.Path(__file__).parent
SPECS = HERE / "specs"
GEN = HERE / "generated"

ERR_TOKEN = re.compile(r"\bErr[A-Z][A-Za-z0-9]*\b")

# A mention is not automatically a demand. Three kinds exist and they must never be pooled:
#
#   DEMANDED   a described USE SITE — some function is said to return/wrap/assert it.
#   LISTED     named in a declaration list, or mapped to a status code, and nowhere else.
#   FORBIDDEN  named in order to BAN it ("no ErrNotImplemented, no panic, no TODO").
#
# ⚠️ THE FORBIDDEN CLASS IS NOT A REFINEMENT, IT IS A CORRECTION. Without it this tool printed
# `ErrNotImplemented  0/3  0%  <-- SCARCE AND DEFECTIVE` for taskapipro and workapi and I nearly
# published it as a second failing identifier. Zero declarations of a name the spec forbids is
# PERFECT COMPLIANCE. The sign was inverted, and only reading the spec line caught it.
CLAUSE_SPLIT = re.compile(r"(?:[.;:]\s|,\s|\s—\s|\s--\s)")
DEMAND_MARKER = re.compile(r"\b(?:returns?|returning|wraps?|wrapping|assert\w*)\b|errors\.Is", re.I)
NEGATION = re.compile(r"\b(?:no|not|never|without)\b", re.I)
NEGATION_REACH = 30  # characters before the name; "no ErrNotImplemented" is adjacent, and a
#                      distant "NEVER" belonging to another instruction must not capture it.


# ---------------------------------------------------------------- spec side


class Stat(collections.namedtuple("Stat", "total files demanded forbidden")):
    """How a spec talks about one sentinel. `total` = demanded + listed + forbidden."""

    @property
    def listed(self) -> int:
        return self.total - self.demanded - self.forbidden


def classify(text: str, name: str) -> list[str]:
    """One verdict per occurrence of `name` in `text`: DEMANDED / LISTED / FORBIDDEN.

    Clause-scoped ON PURPOSE. A character window leaks: response.go's purpose says "maps a
    domain error to a status with errors.Is and writes" two clauses before the mapping line, so
    any window wide enough to be safe elsewhere would read `ErrInsufficientFunds -> 422` as a
    described use site — which is the exact row this whole measurement turns on.
    """
    out = []
    for clause in CLAUSE_SPLIT.split(text):
        masked = ERR_TOKEN.sub(lambda m: "@" * len(m.group()), clause)
        demanded = bool(DEMAND_MARKER.search(masked))
        for m in re.finditer(r"\b" + re.escape(name) + r"\b", clause):
            before = masked[max(0, m.start() - NEGATION_REACH):m.start()]
            out.append("FORBIDDEN" if NEGATION.search(before)
                       else "DEMANDED" if demanded else "LISTED")
    return out


def mentions(spec: dict) -> dict[str, Stat]:
    """{name: Stat}. The project description counts toward totals but is not a file."""
    texts = [(None, spec.get("description") or "")]
    texts += [(i, (f.get("purpose") or "")) for i, f in enumerate(spec.get("files") or [])]

    names = {n for _, t in texts for n in ERR_TOKEN.findall(t)}
    out = {}
    for name in names:
        total = demanded = forbidden = 0
        files = set()
        for idx, text in texts:
            verdicts = classify(text, name)
            if verdicts and idx is not None:
                files.add(idx)
            total += len(verdicts)
            demanded += verdicts.count("DEMANDED")
            forbidden += verdicts.count("FORBIDDEN")
        out[name] = Stat(total, len(files), demanded, forbidden)
    return out


def load_specs() -> dict[str, dict]:
    import yaml

    out = {}
    for path in sorted(SPECS.glob("*.yaml")):
        try:
            d = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if isinstance(d, dict) and d.get("files"):
            out[path.name] = d
    return out


def project_of(spec_name: str, spec: dict) -> str:
    """The project a spec belongs to — its declared `name`, which variants share."""
    return str(spec.get("name") or spec_name.split(".")[0])


# ------------------------------------------------------------- archive side


def as_drawn(tree: pathlib.Path) -> dict | None:
    """The write-once snapshot of what the model WROTE, or None. NEVER falls back to disk.

    Two shapes exist in the archive: a bare {path: source} map (what the harness writes today)
    and a {"files": {...}} envelope. Both are accepted; anything else is refused rather than
    coerced, because a snapshot this tool cannot read must show up as MISSING in the denominator
    and not as a tree that happens to declare nothing.
    """
    snap = tree / ".pre-fix.json"
    if not snap.is_file():
        return None
    try:
        d = json.loads(snap.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("files"), dict):
        d = d["files"]
    if d and all(isinstance(k, str) and isinstance(v, str) for k, v in d.items()):
        return d
    return None


def declared_names(files: dict[str, str]) -> set[str]:
    """Every top-level Err* declaration anywhere in the tree, grouped blocks included."""
    out: set[str] = set()
    for path, code in files.items():
        if not path.endswith(".go"):
            continue
        out |= {d for d in top_level_decls(code) if d.startswith("Err")}
    return out


def archive_rates(project: str) -> tuple[dict[str, int], int, int]:
    """({name: trees declaring it}, trees with any sentinel, trees with no snapshot)."""
    got: collections.Counter = collections.Counter()
    pool = missing = 0
    for tree in sorted(GEN.glob("*")):
        if not tree.is_dir() or project.lower() not in tree.name.lower():
            continue
        files = as_drawn(tree)
        if files is None:
            missing += 1
            continue
        names = declared_names(files)
        if not names:
            continue
        pool += 1
        got.update(names)
    return dict(got), pool, missing


# ----------------------------------------------------------------- report


def report(only: str | None = None) -> int:
    specs = load_specs()
    by_project: collections.defaultdict = collections.defaultdict(dict)
    for spec_name, spec in specs.items():
        proj = project_of(spec_name, spec)
        if only and only.lower() not in proj.lower():
            continue
        by_project[proj][spec_name] = mentions(spec)

    if not by_project:
        print("REFUSING: no spec matched." if only else "REFUSING: no specs found.")
        return 2

    print("  spec side: mentions counted on FOLDED purposes, as tokens")
    print("  archive side: AS DRAWN (.pre-fix.json only), pooled over the project's variants\n")

    rows = []
    for proj in sorted(by_project):
        per_spec = by_project[proj]
        counts, pool, missing = archive_rates(proj)
        every = sorted({n for m in per_spec.values() for n in m})
        if not every:
            continue
        print(f"=== {proj}   ({len(per_spec)} spec file(s), {pool} archived tree(s) "
              f"declaring sentinels, {missing} without a snapshot)")
        for name in sorted(every, key=lambda n: (-len(n), n)):
            uniq = {m[name] for m in per_spec.values() if name in m}
            if len(uniq) == 1:
                st = uniq.pop()
                col = f"{st.total:>4}{st.files:>4}{st.demanded:>5}{st.listed:>5}{st.forbidden:>6}"
                joinable = True
            else:
                st, col, joinable = None, "  DISAGREE across variants          ", False
            declared = counts.get(name, 0)
            rate = f"{declared:>3}/{pool:<3} {100*declared/pool:5.0f}%" if pool else "   n/a    "
            note = "" if joinable else "(not joined)"
            if joinable and st.forbidden and not st.demanded:
                note = "<-- FORBIDDEN by the spec; 0 declared is COMPLIANCE, not a defect"
            print(f"    {name:<22} len{len(name):>3} {col}   {rate}   {note}")
            if joinable and pool and not (st.forbidden and not st.demanded):
                rows.append((st.demanded, st.total, name, proj, declared, pool))
        print()

    if rows:
        print("=== every (project, name) the spec actually ASKS FOR, by described use sites ===")
        print("    forbidden names are excluded; they are complied with, not failed\n")
        print(f"    {'demands':>7} {'mentions':>8}  {'name':<22} {'project':<12} declared")
        for dem, tot, name, proj, declared, pool in sorted(rows):
            pct = 100 * declared / pool
            flag = ""
            if dem == 0:
                flag = ("  <-- NO USE SITE, AND PERFECT (refutes the use-site hypothesis)"
                        if pct == 100 else "  <-- NO USE SITE, AND DEFECTIVE")
            print(f"    {dem:>7} {tot:>8}  {name:<22} {proj:<12} {declared:>3}/{pool:<3}"
                  f" {pct:5.0f}%{flag}")
    return 0


# ---------------------------------------------------------------- self-test


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  ok   {name}")

    # mentions: totals, distinct files, description, qualified names, prefix safety
    spec = {
        "description": "uses ErrNotFound everywhere",
        "files": [
            {"path": "a.go", "purpose": "declares ErrNotFound and ErrInsufficientFunds. "
                                        "returns models.ErrNotFound when absent."},
            {"path": "b.go", "purpose": "maps ErrNotFound -> 404 and ErrInsufficientFunds -> 422"},
            {"path": "c.go", "purpose": "no errors here"},
        ],
    }
    m = mentions(spec)
    chk("total counts description + purposes", m["ErrNotFound"].total, 4)
    chk("distinct files counted", m["ErrNotFound"].files, 2)
    chk("second name counted separately", m["ErrInsufficientFunds"].total, 2)
    chk("file with no error not counted", len(m), 2)

    # the abbreviation must NOT count as the long name, and vice versa
    m2 = mentions({"files": [{"path": "a.go", "purpose": "ErrInsufficient and ErrInsufficientFunds"}]})
    chk("prefix is not a mention of the longer name", m2["ErrInsufficientFunds"].total, 1)
    chk("longer name is not a mention of the prefix", m2["ErrInsufficient"].total, 1)

    # lowercase / non-sentinel tokens are not swept in
    m3 = mentions({"files": [{"path": "a.go", "purpose": "err, Error, Errors, ErrX"}]})
    chk("only Err<Upper> tokens count", sorted(m3), ["ErrX"])

    # --- the three kinds of mention, each a real line from the corpus -------------------
    chk("a described use site is a DEMAND",
        classify("Get/Delete return ErrNotFound. List methods return items", "ErrNotFound"),
        ["DEMANDED"])
    chk("wrapping counts as a demand",
        classify("and an error wrapping ErrUnbalanced when the postings do not sum to zero",
                 "ErrUnbalanced"), ["DEMANDED"])
    chk("a BAN is not a demand",
        classify("Do NOT stub any method with a placeholder (no ErrNotImplemented, no panic)",
                 "ErrNotImplemented"), ["FORBIDDEN"])
    chk("bare list members are LISTED, not demanded",
        classify("Sentinel errors, all matchable with errors.Is: ErrInvalid, ErrNotFound, "
                 "ErrExists, ErrUnbalanced, ErrInsufficientFunds.", "ErrInsufficientFunds"),
        ["LISTED"])

    # ⚠️ REGRESSION: the status-code mapping must stay LISTED even though the SAME purpose says
    # "errors.Is" two clauses earlier. A character window instead of a clause fails this, and it
    # fails in the direction that would silently confirm the hypothesis under test.
    response_purpose = ('`writeError(w http.ResponseWriter, err error)` maps a domain error to a '
                        'status with errors.Is and writes {"error": "..."}: ErrNotFound -> 404, '
                        'ErrExists -> 409, ErrUnbalanced -> 422, ErrInsufficientFunds -> 422, '
                        'anything else -> 500.')
    chk("a status mapping is not a use site (no leak from an earlier clause)",
        classify(response_purpose, "ErrInsufficientFunds"), ["LISTED"])

    # ⚠️ REGRESSION: a negation that belongs to a LATER instruction must not reach backwards.
    chk("a distant NEVER does not forbid",
        classify("check each account by reading s.accounts[id] DIRECTLY (return models.ErrNotFound "
                 "if absent) — it must NEVER call GetAccount", "ErrNotFound"), ["DEMANDED"])

    # a name mentioned once, in a ban, and never demanded
    banned = mentions({"files": [{"path": "a.go", "purpose": "IMPLEMENT FULLY (no ErrNotImplemented)"}]})
    chk("forbidden-only name has zero demands", banned["ErrNotImplemented"],
        Stat(total=1, files=1, demanded=0, forbidden=1))
    chk("listed count derives from the others", banned["ErrNotImplemented"].listed, 0)

    # declared_names sees GROUPED var blocks (every ledger models.go writes them grouped)
    grouped = "package m\n\nvar (\n\tErrA = errors.New(\"a\")\n\tErrB = errors.New(\"b\")\n)\n"
    chk("grouped sentinels are declarations", declared_names({"m.go": grouped}), {"ErrA", "ErrB"})
    chk("non-go files ignored", declared_names({"m.txt": grouped}), set())

    # as_drawn REFUSES to fall back to disk
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td) / "tree"
        (t / "internal").mkdir(parents=True)
        (t / "internal" / "models.go").write_text(grouped)
        chk("no snapshot -> None even though the file is on disk", as_drawn(t), None)
        (t / ".pre-fix.json").write_text(json.dumps({"files": {"internal/models.go": grouped}}))
        chk("envelope shape is read", declared_names(as_drawn(t)), {"ErrA", "ErrB"})
        (t / ".pre-fix.json").write_text(json.dumps({"internal/models.go": grouped}))
        chk("bare {path: source} shape is read", declared_names(as_drawn(t)), {"ErrA", "ErrB"})
        (t / ".pre-fix.json").write_text(json.dumps({"meta": {"model": "x"}}))
        chk("unreadable shape is MISSING, not empty", as_drawn(t), None)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(self_test() if arg == "--self-test" else report(arg))
